"""Structured final answer the agent must submit, exposed to the LLM as a tool."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shift_assistant.tools.registry import openai_tool_schema

SUBMIT_TOOL_NAME = "submit_recommendation"


class SubmissionStatus(StrEnum):
    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"


class RecommendedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clinician_id: str
    rationale: str = Field(
        min_length=20,
        max_length=600,
        description="Why this clinician, grounded in tool results. Mention any credential warning.",
    )
    citation_ids: list[str] = Field(
        default_factory=list,
        description="chunk_ids from search_facility_policies that support the rationale.",
    )
    draft_id: str | None = Field(default=None, description="draft_id from draft_outreach.")


class AgentSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SubmissionStatus
    shift_id: str | None = Field(default=None, description="Required when status is completed.")
    recommendations: list[RecommendedCandidate] = Field(
        default_factory=list, description="Best candidate first. Empty if nobody is eligible."
    )
    summary: str = Field(
        min_length=10,
        max_length=1000,
        description=(
            "2-4 sentences for the coordinator. When completed: your ranking judgement, i.e. why "
            "the shortlisted clinicians come first and why each eligible clinician you did not "
            "shortlist ranks lower. Do not state how many clinicians were evaluated, eligible or "
            "excluded; the report adds verified counts. When asking: what you found."
        ),
    )
    clarification_question: str | None = Field(
        default=None, description="Required when status is needs_clarification."
    )

    @model_validator(mode="after")
    def _status_consistency(self) -> Self:
        if self.status is SubmissionStatus.NEEDS_CLARIFICATION:
            if not self.clarification_question:
                raise ValueError("clarification_question is required for needs_clarification")
            if self.recommendations:
                raise ValueError("recommendations must be empty for needs_clarification")
        elif not self.shift_id:
            raise ValueError("shift_id is required when status is completed")
        return self


def submission_tool_schema() -> dict[str, Any]:
    return openai_tool_schema(
        SUBMIT_TOOL_NAME,
        "Submit the final answer. Call it exactly once, on its own, after every other tool "
        "result has come back.",
        AgentSubmission,
    )
