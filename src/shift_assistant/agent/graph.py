"""The agent workflow as a LangGraph state machine.

    START -> agent --(tool calls)--> tools -> agent ...           (ReAct loop)
               |--(submit)--------> validate --(ok)----------> verify -> END
               |                       |--(fixable)-> agent             (self-repair)
               |--(failure)-------> fallback -> END   <--(unrecoverable)--|

Budgets (LLM calls, wall-clock time, repair attempts) bound the loop; any LLM failure degrades
to the deterministic fallback instead of an error page.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from shift_assistant.agent.llm import ToolCallingModel
from shift_assistant.agent.state import AgentState
from shift_assistant.agent.submission import SUBMIT_TOOL_NAME, AgentSubmission
from shift_assistant.config import Settings
from shift_assistant.contracts import TraceEvent
from shift_assistant.reliability.fallback import DeterministicFallback
from shift_assistant.reliability.grounding import GroundingAction, check_grounding
from shift_assistant.reliability.verifier import build_agent_report
from shift_assistant.tools.registry import ToolRegistry, describe_validation_error

logger = logging.getLogger(__name__)

Update = dict[str, Any]


@dataclass(frozen=True)
class AgentDependencies:
    model: ToolCallingModel | None
    tools: ToolRegistry
    fallback: DeterministicFallback
    settings: Settings


def build_agent_graph(deps: AgentDependencies) -> CompiledStateGraph[AgentState]:
    nodes = _Nodes(deps)
    graph = StateGraph(AgentState)
    graph.add_node("agent", nodes.agent)
    graph.add_node("tools", nodes.tools)
    graph.add_node("validate", nodes.validate)
    graph.add_node("verify", nodes.verify)
    graph.add_node("fallback", nodes.fallback)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", nodes.route_after_agent, ["tools", "validate", "fallback"])
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges(
        "validate", nodes.route_after_validate, ["agent", "verify", "fallback"]
    )
    graph.add_edge("verify", END)
    graph.add_edge("fallback", END)
    return graph.compile()


class _Nodes:
    def __init__(self, deps: AgentDependencies) -> None:
        self._deps = deps
        self._settings = deps.settings

    # --- Nodes -------------------------------------------------------------------------------

    def agent(self, state: AgentState) -> Update:
        if self._deps.model is None:
            return {"failure": "no LLM configured (OPENAI_API_KEY is missing)"}
        if state["llm_calls"] >= self._settings.max_agent_steps:
            return {"failure": f"step budget of {self._settings.max_agent_steps} LLM calls used up"}
        if time.perf_counter() - state["started_at"] > self._settings.max_run_seconds:
            return {"failure": f"time budget of {self._settings.max_run_seconds:g}s used up"}

        started = time.perf_counter()
        step = len(state["trace"]) + 1
        try:
            response = self._deps.model.invoke(state["messages"])
        except Exception as exc:  # provider error after SDK retries: degrade, don't crash
            logger.warning("LLM call failed (%s)", type(exc).__name__)
            return {
                "failure": f"LLM call failed ({type(exc).__name__})",
                "trace": [
                    _event(
                        step,
                        "llm",
                        "model",
                        started,
                        ok=False,
                        detail=f"Provider failure ({type(exc).__name__})",
                    )
                ],
            }
        if not isinstance(response, AIMessage):
            return {"failure": f"unexpected model response type {type(response).__name__}"}

        usage = response.usage_metadata
        planned = ", ".join(call["name"] for call in response.tool_calls) or "no tool call"
        return {
            "messages": [response],
            "llm_calls": state["llm_calls"] + 1,
            "trace": [
                _event(
                    step,
                    "llm",
                    "model",
                    started,
                    detail=f"Planned: {planned}",
                    input_tokens=usage["input_tokens"] if usage else None,
                    output_tokens=usage["output_tokens"] if usage else None,
                )
            ],
        }

    def tools(self, state: AgentState) -> Update:
        ai_message = _last_ai_message(state)
        ledger = state["ledger"]
        messages: list[ToolMessage] = []
        trace: list[TraceEvent] = []
        step = len(state["trace"])

        for call in ai_message.tool_calls:
            step += 1
            started = time.perf_counter()
            if call["name"] == SUBMIT_TOOL_NAME:
                content = (
                    f"ERROR: {SUBMIT_TOOL_NAME} must be called on its own, after the other tool "
                    "results are back. Call it again by itself."
                )
                ok = False
            elif state["request"].shift_id and call["args"].get("shift_id") not in (
                None,
                state["request"].shift_id,
            ):
                content = f"ERROR: Use pinned shift {state['request'].shift_id}."
                ok = False
            elif call["name"] == "draft_outreach" and not state["request"].draft_outreach:
                content = "ERROR: The coordinator requested no outreach drafts."
                ok = False
            else:
                args = dict(call["args"])
                if call["name"] == "find_open_shifts" and state["request"].shift_id:
                    args["shift_id"] = state["request"].shift_id
                execution = self._deps.tools.execute(call["name"], args)
                ledger = ledger.merge(execution.evidence)
                content, ok = execution.content, execution.ok
            messages.append(_tool_message(call["id"], call["name"], content, ok))
            detail = _compact(call["args"]) if ok else content
            trace.append(_event(step, "tool", call["name"], started, ok=ok, detail=detail))

        for bad in ai_message.invalid_tool_calls:
            step += 1
            name = bad["name"] or "unknown"
            content = f"ERROR: arguments for {name} were not valid JSON. Send valid JSON."
            messages.append(_tool_message(bad["id"], name, content, ok=False))
            trace.append(_event(step, "tool", name, time.perf_counter(), ok=False, detail=content))

        return {"messages": messages, "ledger": ledger, "trace": trace}

    def validate(self, state: AgentState) -> Update:
        started = time.perf_counter()
        ai_message = _last_ai_message(state)
        submission: AgentSubmission | None = None
        rejected = True  # whether the submission is unusable even after enforcement

        if not ai_message.tool_calls:
            errors = [f"No tool call received. Finish by calling {SUBMIT_TOOL_NAME}."]
            reply: HumanMessage | ToolMessage = HumanMessage(errors[0])
        else:
            call = ai_message.tool_calls[0]
            try:
                submission = AgentSubmission.model_validate(call["args"])
            except ValidationError as exc:
                errors = [f"Invalid submission: {describe_validation_error(exc)}"]
            else:
                problems = check_grounding(
                    submission,
                    state["ledger"],
                    self._settings.max_recommendations,
                    state["request"],
                )
                errors = [p.message for p in problems]
                rejected = any(p.action is GroundingAction.REJECT_SUBMISSION for p in problems)
            reply = _tool_message(call["id"], SUBMIT_TOOL_NAME, _feedback(errors), not errors)

        attempts = state["repair_attempts"] + (1 if errors else 0)
        update: Update = {
            "messages": [reply],
            "submission": submission,
            "validation_errors": errors,
            "repair_attempts": attempts,
            "trace": [
                _event(
                    len(state["trace"]) + 1,
                    "validation",
                    SUBMIT_TOOL_NAME,
                    started,
                    ok=not errors,
                    detail="; ".join(errors)[:500] or "Submission accepted.",
                )
            ],
        }
        if errors and attempts > self._settings.max_repair_attempts and rejected:
            update["failure"] = f"no valid answer after {attempts} submission attempts"
        return update

    def verify(self, state: AgentState) -> Update:
        started = time.perf_counter()
        submission = state["submission"]
        assert submission is not None, "routing guarantees a parsed submission"
        report = build_agent_report(
            state["request"], submission, state["ledger"], self._settings.max_recommendations
        )
        detail = (
            f"{len(report.recommendations)} recommendation(s) verified; "
            f"{len(report.issues)} issue(s) enforced."
        )
        event = _event(len(state["trace"]) + 1, "verification", "grounding", started, detail=detail)
        return {"report": report, "trace": [event]}

    def fallback(self, state: AgentState) -> Update:
        started = time.perf_counter()
        reason = state["failure"] or "unknown failure"
        report = self._deps.fallback.build_report(state["request"], state["ledger"], reason)
        event = _event(len(state["trace"]) + 1, "fallback", "rules", started, detail=reason)
        return {"report": report, "trace": [event]}

    # --- Routing -----------------------------------------------------------------------------

    @staticmethod
    def route_after_agent(state: AgentState) -> Literal["tools", "validate", "fallback"]:
        if state["failure"]:
            return "fallback"
        message = _last_ai_message(state)
        calls = message.tool_calls
        only_submit = len(calls) == 1 and calls[0]["name"] == SUBMIT_TOOL_NAME
        if message.invalid_tool_calls or (calls and not only_submit):
            return "tools"
        return "validate"  # a lone submission, or no tool call at all (validate will nudge)

    def route_after_validate(self, state: AgentState) -> Literal["agent", "verify", "fallback"]:
        if state["failure"]:
            return "fallback"
        if not state["validation_errors"]:
            return "verify"
        if state["repair_attempts"] > self._settings.max_repair_attempts:
            return "verify"  # out of repairs but usable: the verifier strips what is ungrounded
        return "agent"


# --- Helpers ---------------------------------------------------------------------------------


def _last_ai_message(state: AgentState) -> AIMessage:
    message = state["messages"][-1]
    if not isinstance(message, AIMessage):
        raise TypeError(f"expected AIMessage, got {type(message).__name__}")
    return message


def _tool_message(call_id: str | None, name: str, content: str, ok: bool) -> ToolMessage:
    return ToolMessage(
        content=content, tool_call_id=call_id or "", name=name, status="success" if ok else "error"
    )


def _feedback(errors: list[str]) -> str:
    if not errors:
        return "Submission accepted."
    bullet_list = "\n".join(f"- {e}" for e in errors)
    return f"ERROR: submission rejected. Fix these problems and submit again:\n{bullet_list}"


def _compact(args: dict[str, Any], limit: int = 200) -> str:
    text = json.dumps(args, default=str)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _event(
    step: int,
    kind: Literal["llm", "tool", "validation", "verification", "fallback"],
    name: str,
    started: float,
    *,
    ok: bool = True,
    detail: str = "",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> TraceEvent:
    return TraceEvent(
        step=step,
        kind=kind,
        name=name,
        ok=ok,
        detail=detail,
        duration_ms=round((time.perf_counter() - started) * 1000),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
