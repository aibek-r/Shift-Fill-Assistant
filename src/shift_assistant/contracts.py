"""Public input and output contracts of the assistant."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shift_assistant.domain.eligibility import CredentialCheck, Finding
from shift_assistant.intent import requested_count, wants_outreach
from shift_assistant.tools.schemas import OutreachDraft, PolicyExcerpt, ShiftSummary


class StaffingRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    text: str = Field(min_length=5, max_length=2000)
    shift_id: str | None = Field(
        default=None, description="Optional shift the coordinator pinned in the UI."
    )
    requested_count: int | None = Field(default=None, ge=1, le=100)
    draft_outreach: bool = True

    @model_validator(mode="before")
    @classmethod
    def extract_explicit_intent(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            value = dict(value)
            value.setdefault("requested_count", requested_count(value["text"]))
            value.setdefault("draft_outreach", wants_outreach(value["text"]))
        return value

    def shortlist_target(self, positions_open: int) -> int:
        return self.requested_count or positions_open


class ReportStatus(StrEnum):
    """Completion conditions live in `reliability.reporting.fill_status`."""

    READY = "ready"  # requested shortlist and outreach complete, full pool vetted; nobody booked
    PARTIAL = "partial"  # full pool vetted; fewer eligible (or allowed) clinicians than requested
    NO_ELIGIBLE_CANDIDATES = "no_eligible_candidates"  # full pool vetted; nobody eligible
    NEEDS_REVIEW = "needs_review"  # mandatory work unresolved; verified results are kept
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class RunMode(StrEnum):
    AGENT = "agent"  # the model planned and ranked; code additions are marked with Origin.CODE
    FALLBACK = "fallback"  # deterministic pipeline used because the AI workflow failed


class Origin(StrEnum):
    """Who produced a recommendation or requested its outreach draft."""

    MODEL = "model"  # chosen by the LLM, or drafted through its draft_outreach tool call
    CODE = "code"  # added by deterministic completion or the rule-based fallback


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
    kind: Literal["llm", "tool", "validation", "completion", "verification", "fallback"]
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
    selected_by: Origin
    rationale: str
    warnings: list[Finding] = []
    credentials: list[CredentialCheck] = []
    citations: list[PolicyExcerpt] = []
    outreach: OutreachDraft | None = None
    outreach_by: Origin | None = Field(default=None, description="Set whenever outreach is.")


class ExcludedCandidate(BaseModel):
    clinician_id: str
    clinician_name: str
    reasons: list[Finding]
    credentials: list[CredentialCheck] = []


class AlternateCandidate(BaseModel):
    """Eligible and vetted, but not shortlisted. Computed by code so nobody is silently lost."""

    clinician_id: str
    clinician_name: str
    warnings: list[Finding] = []
    credentials: list[CredentialCheck] = []


class CandidateCoverage(BaseModel):
    """Candidate counts computed by code from verified evaluations, never written by the model."""

    pool_size: int | None = Field(
        default=None,
        description="Clinicians whose role and specialty fit the shift; None if never searched.",
    )
    evaluated: int = 0
    eligible: int = 0
    recommended: int = 0
    alternates: int = 0
    excluded: int = 0
    unevaluated_ids: list[str] = Field(
        default=[], description="Pool clinicians that were never compliance-checked."
    )
    removed_by_verification: int = 0

    @property
    def full_pool_evaluated(self) -> bool:
        return self.pool_size is not None and not self.unevaluated_ids


class CompletionRecord(BaseModel):
    """Mandatory work that deterministic code finished after the model's answer (agent mode).

    Unresolved work is not recorded here: it stays in `issues` and makes the status needs_review.
    """

    pool_determined_by_code: bool = Field(
        default=False, description="search_clinicians was never called; code computed the pool."
    )
    evaluated_ids: list[str] = Field(default=[], description="Pool clinicians vetted by code.")
    selected_ids: list[str] = Field(default=[], description="Recommendations appended by code.")
    drafted_ids: list[str] = Field(
        default=[], description="Clinicians whose outreach code drafted."
    )

    @property
    def applied(self) -> bool:
        return bool(
            self.pool_determined_by_code
            or self.evaluated_ids
            or self.selected_ids
            or self.drafted_ids
        )


class RunMetrics(BaseModel):
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0


class OutreachApproval(BaseModel):
    draft_id: str
    status: Literal["pending", "editing", "approved"]


class OutreachReviewSnapshot(BaseModel):
    run_id: str
    approvals: list[OutreachApproval]


class StaffingReport(BaseModel):
    request: StaffingRequest
    status: ReportStatus
    mode: RunMode
    summary: str = Field(description="Built by code from the verified report, except when asking.")
    agent_notes: str | None = Field(
        default=None,
        description="Reserved for reviewed notes. Unverified model prose is not copied here.",
    )
    shift: ShiftSummary | None = None
    recommendations: list[CandidateRecommendation] = []
    alternates: list[AlternateCandidate] = []
    excluded: list[ExcludedCandidate] = []
    coverage: CandidateCoverage | None = None
    completion: CompletionRecord | None = Field(
        default=None, description="Present when code completed work in agent mode."
    )
    clarification_question: str | None = None
    issues: list[VerificationIssue] = []
    trace: list[TraceEvent] = []
    metrics: RunMetrics = RunMetrics()
    outreach_review: OutreachReviewSnapshot | None = None
