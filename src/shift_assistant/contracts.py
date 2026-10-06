"""Public input and output contracts of the assistant."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shift_assistant.domain.eligibility import CredentialCheck, Finding
from shift_assistant.domain.models import Unit
from shift_assistant.intent import requested_count, wants_outreach
from shift_assistant.tools.schemas import OutreachDraft, PolicyExcerpt, ShiftSummary

MAX_MESSAGE_CHARS = 2000


class StaffingRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    shift_id: str | None = Field(
        default=None, description="Optional shift the coordinator pinned in the UI."
    )
    requested_count: int | None = Field(default=None, ge=1, le=100)
    draft_outreach: bool = True
    # Explicit shift details for API callers; each overrides conflicting request text.
    facility: str | None = Field(default=None, max_length=200, description="Facility name or ID.")
    unit: Unit | None = None
    start_date: date | None = Field(default=None, description="Facility-local shift start date.")

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
    input_tokens: int | None = Field(default=None, description="None when no call reported usage.")
    output_tokens: int | None = Field(default=None, description="None when no call reported usage.")
    duration_ms: int = 0

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)


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


# --- Front door: one coordinator message, routed to a handler --------------------------------


class AssistantRequest(BaseModel):
    """One coordinator message. Empty text is valid: it gets the help reply.

    The typed shift fields are used only when the message is routed to the staffing workflow.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    text: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    shift_id: str | None = Field(
        default=None, description="Optional shift the coordinator pinned in the UI."
    )
    facility: str | None = Field(default=None, max_length=200, description="Facility name or ID.")
    unit: Unit | None = None
    start_date: date | None = Field(default=None, description="Facility-local shift start date.")

    def staffing_request(self) -> StaffingRequest:
        return StaffingRequest(
            text=self.text,
            shift_id=self.shift_id,
            facility=self.facility,
            unit=self.unit,
            start_date=self.start_date,
        )


class Intent(StrEnum):
    # Answered from the system of record
    FILL_SHIFT = "fill_shift"
    SHIFT_LOOKUP = "shift_lookup"
    POLICY_QUESTION = "policy_question"
    FACILITY_INFO = "facility_info"
    CREDENTIAL_CHECK = "credential_check"  # recognized; no handler yet
    ELIGIBILITY_CHECK = "eligibility_check"  # recognized; no handler yet
    # Fixed replies
    HELP = "help"
    SMALL_TALK = "small_talk"
    OUT_OF_SCOPE = "out_of_scope"
    MEDICAL_LEGAL = "medical_legal"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    BUSINESS_SENSITIVE = "business_sensitive"
    BLOCKED = "blocked"


class RoutingMethod(StrEnum):
    INPUT_GUARD = "input_guard"  # blocked before routing; goes straight to the refusal template
    FAST_RULE = "fast_rule"  # fixed patterns for empty text, greetings, thanks and help; no AI
    LLM = "llm"  # structured output from the router model
    KEYWORDS = "keywords"  # keyword fallback: no API key, or the router model failed


class ReplyReason(StrEnum):
    """Why the assistant answered with a fixed reply instead of running a workflow."""

    EMPTY_MESSAGE = "empty_message"
    GREETING = "greeting"
    HELP_REQUEST = "help_request"
    THANKS = "thanks"
    IDENTITY = "identity"  # "who made you?", "are you ChatGPT?"
    SYSTEM_QUESTION = "system_question"  # tools, schemas, model: answered in plain words only
    NOT_UNDERSTOOD = "not_understood"
    NON_ENGLISH = "non_english"
    FOLLOW_UP = "follow_up"  # "and for October 16?" with no conversation memory
    OFF_TOPIC = "off_topic"
    CLINICAL_ADVICE = "clinical_advice"
    LEGAL_ADVICE = "legal_advice"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    PAY_OR_CONTRACT = "pay_or_contract"
    BULK_EXPORT = "bulk_export"
    AUDIT_DATA = "audit_data"
    BLOCKED = "blocked"
    LOW_CONFIDENCE = "low_confidence"
    NOT_AVAILABLE_YET = "not_available_yet"
    INVALID_REQUEST = "invalid_request"


class RefusedTopic(StrEnum):
    """A part of a mixed message the assistant declines, e.g. the weather in N3."""

    WEATHER = "weather"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    CREATIVE_WRITING = "creative_writing"
    FOOD = "food"
    FINANCE = "finance"
    NEWS_AND_POLITICS = "news_and_politics"
    TRANSLATION = "translation"
    CODE = "code"
    MATH = "math"
    TRAVEL = "travel"
    GENERAL_KNOWLEDGE = "general_knowledge"
    MEDICAL_ADVICE = "medical_advice"
    LEGAL_ADVICE = "legal_advice"
    ACTION = "action"  # booking, sending or changing data


class IntentEntities(BaseModel):
    """Details the router read from the message. Hints only: handlers re-check each one
    against the system of record, and the staffing workflow parses the original text."""

    model_config = ConfigDict(frozen=True)

    facility: str | None = None
    unit: Unit | None = None
    shift_date: date | None = None
    clinician_name: str | None = None
    shift_id: str | None = None


class IntentDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: Intent
    confidence: float = Field(ge=0, le=1)
    entities: IntentEntities = Field(default_factory=IntentEntities)
    reason: ReplyReason | None = Field(
        default=None, description="Finer reason for intents answered with a fixed reply."
    )
    refused_parts: tuple[RefusedTopic, ...] = Field(
        default=(), description="Parts of a mixed message that are declined; the rest is answered."
    )
    method: RoutingMethod
    fallback_reason: str | None = Field(
        default=None, description="Why the keyword router stood in for the router model."
    )


class ResponseKind(StrEnum):
    STAFFING_REPORT = "staffing_report"
    ANSWER = "answer"
    CLARIFICATION = "clarification"
    HELP = "help"
    OUT_OF_SCOPE = "out_of_scope"
    REFUSAL = "refusal"
    BLOCKED = "blocked"


class AnswerTable(BaseModel):
    columns: list[str]
    rows: list[list[str]]


class Answer(BaseModel):
    """A read-only answer built by code from tool results. No model writes any of it."""

    items: list[str] = Field(default=[], description="Facts from the records, one per line.")
    table: AnswerTable | None = None
    citations: list[PolicyExcerpt] = Field(default=[], description="Policy text, quoted as is.")
    sources: list[str] = Field(
        default=[], description="IDs of the records used: shifts, facilities, policy sections."
    )


class RefusedPart(BaseModel):
    topic: RefusedTopic
    message: str = Field(description="Fixed one-line template.")


class AssistantResponse(BaseModel):
    """What the coordinator gets back for one message. A staffing run keeps its full
    `StaffingReport`; read-only answers are built from records; every other reply is a fixed
    template. No model prose is shown."""

    request: AssistantRequest
    kind: ResponseKind
    routing: IntentDecision
    message: str = Field(
        description="Text for the coordinator: a fixed template, a sentence built from records, "
        "or the code-built report summary."
    )
    answer: Answer | None = Field(default=None, description="Set for answer responses only.")
    refused_parts: list[RefusedPart] = Field(
        default=[], description="Declined parts of a mixed message, shown with the answer."
    )
    examples: list[str] = Field(default=[], description="Example requests the coordinator can try.")
    reason: ReplyReason | None = None
    report: StaffingReport | None = Field(
        default=None,
        description="Set for staffing_report responses; also for a clarification the staffing "
        "workflow asked.",
    )
    duration_ms: int = 0

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> Self:
        if self.kind is ResponseKind.STAFFING_REPORT and self.report is None:
            raise ValueError("a staffing_report response needs a report")
        if self.report is not None and self.kind not in _REPORT_KINDS:
            raise ValueError(f"a {self.kind} response cannot carry a staffing report")
        if (self.kind is ResponseKind.ANSWER) != (self.answer is not None):
            raise ValueError("an answer is required for answer responses, and only there")
        return self

    @property
    def intent(self) -> Intent:
        return self.routing.intent


_REPORT_KINDS = frozenset({ResponseKind.STAFFING_REPORT, ResponseKind.CLARIFICATION})
