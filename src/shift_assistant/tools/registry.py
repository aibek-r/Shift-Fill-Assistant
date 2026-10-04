"""Tool registry: JSON schemas for the LLM and a safe executor for its tool calls.

The executor never raises. Bad arguments, domain errors and unexpected failures all become an
error result the model can read and recover from, so one bad call cannot crash the workflow.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ValidationError

from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.schemas import (
    DraftOutreachArgs,
    EvaluateCandidatesArgs,
    FindOpenShiftsArgs,
    SearchCliniciansArgs,
    SearchFacilityPoliciesArgs,
)
from shift_assistant.tools.toolkit import StaffingToolkit, ToolInputError, ToolOutput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Any], ToolOutput]

    def openai_schema(self) -> dict[str, Any]:
        return openai_tool_schema(self.name, self.description, self.args_model)


@dataclass(frozen=True)
class ToolExecution:
    name: str
    ok: bool
    content: str
    evidence: EvidenceLedger
    duration_ms: int


class ToolRegistry:
    def __init__(self, specs: Sequence[ToolSpec], output_char_limit: int) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self._output_char_limit = output_char_limit

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [spec.openai_schema() for spec in self._specs.values()]

    def execute(self, name: str, arguments: Mapping[str, Any]) -> ToolExecution:
        started = time.perf_counter()

        def failure(message: str) -> ToolExecution:
            return ToolExecution(name, False, f"ERROR: {message}", EvidenceLedger(), _ms(started))

        spec = self._specs.get(name)
        if spec is None:
            return failure(f"Unknown tool '{name}'. Available tools: {', '.join(self._specs)}.")
        try:
            output = spec.handler(spec.args_model.model_validate(arguments))
        except ValidationError as exc:
            return failure(f"Invalid arguments for {name}: {describe_validation_error(exc)}")
        except ToolInputError as exc:
            return failure(str(exc))
        except Exception as exc:  # exception text can contain secrets; log only its class
            logger.warning("Tool %s failed (%s)", name, type(exc).__name__)
            return failure(f"{name} failed unexpectedly. Try different arguments.")

        content = fit_to_limit(output.result, self._output_char_limit)
        return ToolExecution(name, True, content, output.evidence, _ms(started))


def build_tool_registry(toolkit: StaffingToolkit, output_char_limit: int) -> ToolRegistry:
    specs = [
        ToolSpec(
            name="find_open_shifts",
            description=(
                "Look up open shifts. Use it first to resolve the request to a concrete shift_id. "
                "All filters are optional and combined with AND."
            ),
            args_model=FindOpenShiftsArgs,
            handler=toolkit.find_open_shifts,
        ),
        ToolSpec(
            name="search_facility_policies",
            description=(
                "Semantic search over the facility's agency handbook plus organisation-wide "
                "staffing policies. Returns excerpts with chunk_id citations. Use it for unit "
                "preferences, arrival logistics and outreach rules."
            ),
            args_model=SearchFacilityPoliciesArgs,
            handler=toolkit.search_facility_policies,
        ),
        ToolSpec(
            name="search_clinicians",
            description=(
                "List clinicians whose role and specialty fit the shift, ranked by semantic match "
                "to optional preferences. Does NOT check compliance."
            ),
            args_model=SearchCliniciansArgs,
            handler=toolkit.search_clinicians,
        ),
        ToolSpec(
            name="evaluate_candidates",
            description=(
                "Authoritative compliance check: licensure for the facility state, required "
                "certifications valid through the shift, experience, double-booking and rest "
                "time. Only clinicians marked eligible may be recommended."
            ),
            args_model=EvaluateCandidatesArgs,
            handler=toolkit.evaluate_candidates,
        ),
        ToolSpec(
            name="draft_outreach",
            description=(
                "Create an outreach draft for an eligible clinician; it is never sent "
                "automatically. Shift logistics, reply deadline and credential reminders are "
                "filled in from the system of record. You provide only a short personal note."
            ),
            args_model=DraftOutreachArgs,
            handler=toolkit.draft_outreach,
        ),
    ]
    return ToolRegistry(specs, output_char_limit)


def openai_tool_schema(name: str, description: str, args_model: type[BaseModel]) -> dict[str, Any]:
    schema = convert_to_openai_tool(args_model)
    schema["function"]["name"] = name
    schema["function"]["description"] = description
    return schema


def describe_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'input'}: {error['msg']}"
        for error in exc.errors()
    )


def fit_to_limit(result: BaseModel, limit: int) -> str:
    """Serialize a tool result in at most `limit` characters while keeping it valid JSON.

    Drops trailing items from the largest list (or shortens the longest string) and adds a
    `truncated` note, so the model knows the result is incomplete instead of reading cut-off JSON.
    The ledger still holds the full result.
    """
    payload: dict[str, Any] = result.model_dump(mode="json", exclude_none=True)
    text = _dumps(payload)
    omitted = 0
    while len(text) > limit and (field := _largest_field(payload)) is not None:
        value = payload[field]
        if isinstance(value, list):
            value.pop()
            omitted += 1
            payload["truncated"] = f"{omitted} {field} item(s) omitted to fit the output limit."
        else:
            keep = max(0, len(value) - (len(text) - limit) - 80)
            payload[field] = f"{value[:keep]}..."
            payload["truncated"] = f"{field} shortened to fit the output limit."
        text = _dumps(payload)
    if len(text) > limit:
        return _dumps({"truncated": "Result too large for the output limit. Narrow the request."})
    return text


def _largest_field(payload: dict[str, Any]) -> str | None:
    shrinkable = [
        key
        for key, value in payload.items()
        if key != "truncated"
        and ((isinstance(value, list) and value) or (isinstance(value, str) and len(value) > 3))
    ]
    return max(shrinkable, key=lambda key: len(_dumps(payload[key])), default=None)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
