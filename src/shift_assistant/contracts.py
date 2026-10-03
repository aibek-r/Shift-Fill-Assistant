"""Public input and output contracts of the assistant."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shift_assistant.domain.eligibility import Finding
from shift_assistant.tools.schemas import OutreachDraft, PolicyExcerpt, ShiftSummary


class StaffingRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    text: str = Field(min_length=5, max_length=2000)
    shift_id: str | None = Field(
        default=None, description="Optional shift the coordinator pinned in the UI."
    )


class ReportStatus(StrEnum):
    READY = "ready"  # enough eligible candidates to cover every open position
    PARTIAL = "partial"  # some, but fewer than the open positions
    NO_ELIGIBLE_CANDIDATES = "no_eligible_candidates"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class RunMode(StrEnum):
    AGENT = "agent"
    FALLBACK = "fallback"  # deterministic pipeline used because the AI workflow failed


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class VerificationIssue(BaseModel):
    severity: IssueSeverity
    code: str
    message: str


class TraceEvent(BaseModel):
    step: int
    kind: Literal["llm", "tool", "validation", "verification", "fallback"]
    name: str
    ok: bool = True
    detail: str = ""
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class CandidateRecommendation(BaseModel):
    rank: int
    clinician_id: str
    clinician_name: str
    rationale: str
    warnings: list[Finding] = []
    citations: list[PolicyExcerpt] = []
    outreach: OutreachDraft | None = None


class ExcludedCandidate(BaseModel):
    clinician_id: str
    clinician_name: str
    reasons: list[Finding]


class AlternateCandidate(BaseModel):
    """Eligible and vetted, but not shortlisted. Computed by code so nobody is silently lost."""

    clinician_id: str
    clinician_name: str
    warnings: list[Finding] = []


class RunMetrics(BaseModel):
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0


class StaffingReport(BaseModel):
    request: StaffingRequest
    status: ReportStatus
    mode: RunMode
    summary: str
    shift: ShiftSummary | None = None
    recommendations: list[CandidateRecommendation] = []
    alternates: list[AlternateCandidate] = []
    excluded: list[ExcludedCandidate] = []
    clarification_question: str | None = None
    issues: list[VerificationIssue] = []
    trace: list[TraceEvent] = []
    metrics: RunMetrics = RunMetrics()
