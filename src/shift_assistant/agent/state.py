"""LangGraph state shared by all nodes of the agent workflow."""

from __future__ import annotations

import operator
import time
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, BaseMessage
from langgraph.graph.message import add_messages

from shift_assistant.agent.submission import AgentSubmission
from shift_assistant.contracts import (
    CompletionRecord,
    StaffingReport,
    StaffingRequest,
    TraceEvent,
)
from shift_assistant.tools.evidence import EvidenceLedger


class AgentState(TypedDict):
    request: StaffingRequest
    messages: Annotated[list[AnyMessage], add_messages]  # conversation with the model
    ledger: EvidenceLedger  # structured facts produced by tools (working memory)
    llm_calls: int
    repair_attempts: int
    validation_errors: list[str]  # problems with the latest submission, if any
    submission: AgentSubmission | None
    completion: CompletionRecord | None  # work deterministic completion added to the answer
    unresolved: list[str]  # mandatory work completion could not finish, and why
    failure: str | None  # set when the workflow must hand over to the fallback
    report: StaffingReport | None
    trace: Annotated[list[TraceEvent], operator.add]  # audit trail, append-only
    started_at: float  # time.perf_counter() when the run began, for the wall-clock budget


def initial_state(request: StaffingRequest, messages: list[BaseMessage]) -> AgentState:
    return AgentState(
        request=request,
        messages=list(messages),  # type: ignore[arg-type]
        ledger=EvidenceLedger(),
        llm_calls=0,
        repair_attempts=0,
        validation_errors=[],
        submission=None,
        completion=None,
        unresolved=[],
        failure=None,
        report=None,
        trace=[],
        started_at=time.perf_counter(),
    )
