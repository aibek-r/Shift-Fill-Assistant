"""Streamlit UI for the Shift Fill Assistant.  Run: `streamlit run app/streamlit_app.py`."""

from __future__ import annotations

import streamlit as st

from shift_assistant.agent.llm import unavailable_model
from shift_assistant.assistant import ShiftFillAssistant, build_assistant
from shift_assistant.config import Settings
from shift_assistant.contracts import (
    CandidateRecommendation,
    IssueSeverity,
    ReportStatus,
    RunMode,
    StaffingReport,
    StaffingRequest,
    TraceEvent,
)
from shift_assistant.domain.eligibility import (
    CheckCode,
    CredentialCheck,
    CredentialStatus,
    Finding,
)
from shift_assistant.domain.models import COMPACT_JURISDICTION, CredentialType
from shift_assistant.reliability.reporting import plural, shortlist_phrase
from shift_assistant.rendering import describe_shift
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import Embedder, create_embedder
from shift_assistant.review import DraftStatus, OutreachReview
from shift_assistant.tools.outreach import format_local_datetime, unit_label

EXAMPLES = {
    "ICU night shift": (
        "Find two ICU nurses for the St. Mary's night shift on October 14 "
        "and draft outreach for each."
    ),
    "PICU shortlist": (
        "Who can cover the PICU night shift at Bayview on Oct 18? "
        "Give me a shortlist of two with outreach drafts."
    ),
    "Ambiguous request": "Can you find an ICU nurse for St. Mary's next week?",
    "Unknown facility": "Find a nurse for Mercy General tomorrow night.",
    "Nobody eligible": "We need a NICU nurse at Bayview Children's for the October 19 day shift.",
}

PROGRESS_LABELS = {
    "llm": "planning the next step",
    "find_open_shifts": "finding the shift",
    "search_facility_policies": "reading facility policies",
    "search_clinicians": "searching clinicians",
    "evaluate_candidates": "checking compliance",
    "draft_outreach": "drafting outreach",
    "validation": "validating the answer",
    "verification": "verifying against evidence",
    "fallback": "running the rule-based fallback",
}

STATUS_STYLE = {
    ReportStatus.READY: (st.success, ":material/check_circle:", "Shortlist ready"),
    ReportStatus.PARTIAL: (st.warning, ":material/warning:", "Partial shortlist"),
    ReportStatus.NO_ELIGIBLE_CANDIDATES: (st.error, ":material/block:", "No eligible clinicians"),
    ReportStatus.NEEDS_CLARIFICATION: (st.info, ":material/help:", "Needs clarification"),
    ReportStatus.FAILED: (st.error, ":material/error:", "Failed"),
}

STATUS_MESSAGES = {
    ReportStatus.NO_ELIGIBLE_CANDIDATES: "No clinician passed this shift's compliance checks.",
    ReportStatus.NEEDS_CLARIFICATION: "The assistant needs more information before it can search.",
    ReportStatus.FAILED: "The request could not be completed.",
}

MODE_LABELS = {
    RunMode.AGENT: (
        "blue",
        "smart_toy",
        "AI agent",
        "The LLM planned and ranked; rules decided compliance and every claim was verified.",
    ),
    RunMode.FALLBACK: (
        "orange",
        "rule",
        "Rule-based fallback",
        "The AI workflow was unavailable, so deterministic rules alone built this report.",
    ),
}

CREDENTIAL_LABELS = {
    CredentialStatus.VALID_THROUGH_SHIFT: ("green", "check", "{name} valid through shift"),
    CredentialStatus.EXPIRING_SOON: ("orange", "schedule", "{name} expires {expires}"),
    CredentialStatus.EXPIRES_BEFORE_SHIFT_END: ("red", "block", "{name} expires before shift ends"),
    CredentialStatus.MISSING: ("red", "block", "{name} missing"),
    CredentialStatus.NOT_VALID_IN_STATE: ("red", "block", "{name} not valid in this state"),
}

BLOCKER_LABELS = {
    CheckCode.CREDENTIAL_EXPIRED: "{credential} expires before shift ends",
    CheckCode.MISSING_CREDENTIAL: "{credential} missing",
    CheckCode.LICENSE_NOT_VALID_IN_STATE: "{credential} not valid in this state",
}

APPROVED_MESSAGE = "Draft approved. Delivery simulated; no message sent."


@st.cache_resource(show_spinner="Loading the embedding model...")
def get_embedder() -> Embedder:
    settings = Settings()
    return create_embedder(settings.embedding_model, settings.cache_dir)


@st.cache_resource
def get_repository() -> StaffingRepository:
    return StaffingRepository.from_directory(Settings().data_dir)


@st.cache_resource(show_spinner="Building indexes...")
def get_assistant(simulate_outage: bool) -> ShiftFillAssistant:
    model = unavailable_model() if simulate_outage else None
    return build_assistant(Settings(), embedder=get_embedder(), chat_model=model)


def main() -> None:
    st.set_page_config(page_title="Shift Fill Assistant", page_icon=":hospital:", layout="wide")
    simulate_outage, selected_shift = render_sidebar()
    assistant = get_assistant(simulate_outage)

    render_header()
    request = render_request_form(selected_shift)
    if request is not None:
        new_report = run_with_progress(assistant, request)
        # A new run replaces the review too, so no approval carries over from an earlier result.
        st.session_state["report"] = new_report
        st.session_state["review"] = OutreachReview.for_report(new_report)

    report: StaffingReport | None = st.session_state.get("report")
    if report is not None:
        review: OutreachReview = st.session_state["review"]
        render_report(report, review, assistant)


def render_sidebar() -> tuple[bool, str | None]:
    with st.sidebar:
        if not Settings().llm_enabled:
            st.warning("No OPENAI_API_KEY: running the deterministic fallback only.")

        st.header("Select a shift (optional)")
        shifts = get_repository().shifts()
        labels = {
            s.id: f"{s.id} - {unit_label(s.unit)} - {format_local_datetime(s.start)}"
            for s in shifts
        }
        selected = st.selectbox(
            "Shift",
            options=[None, *labels],
            format_func=lambda sid: "Let the agent find it" if sid is None else labels[sid],
        )

        st.header("Examples")
        for name, example in EXAMPLES.items():
            if st.button(name, width="stretch"):
                st.session_state["request_text"] = example
                st.session_state.pop("report", None)
                st.session_state.pop("review", None)
                st.rerun()

        with st.expander("Demo controls", icon=":material/science:"):
            simulate_outage = st.toggle(
                "Simulate LLM outage",
                help="Every model call fails, so you can see the deterministic fallback.",
            )
    return simulate_outage, selected


def render_header() -> None:
    st.title("Shift Fill Assistant")
    st.caption("Turns a staffing request into a vetted shortlist with outreach drafts.")
    with st.expander("About this assistant", icon=":material/info:"):
        st.markdown(
            "- **Compliance is rule-based.** Licensure, certifications, experience, "
            "double-booking and rest time are checked by deterministic code, never by the model.\n"
            "- **Every claim is verified** against tool evidence before it reaches you "
            "(see the Verification tab).\n"
            "- **Nothing is sent.** A coordinator reviews, edits and approves each outreach "
            "draft; delivery is simulated in this demo."
        )


def render_request_form(selected_shift: str | None) -> StaffingRequest | None:
    # Inside a form, Ctrl/Cmd+Enter in the text area submits the request.
    with st.form("request_form", border=False):
        text = st.text_area(
            "Staffing request",
            key="request_text",
            height=90,
            placeholder="e.g. Find two ICU nurses for the St. Mary's night shift on October 14.",
        )
        with st.container(horizontal=True, vertical_alignment="center"):
            submitted = st.form_submit_button("Run assistant", type="primary")
            st.caption("or press **Ctrl+Enter** (**⌘+Enter** on Mac)")
    if not submitted:
        return None
    if not text.strip():
        st.warning("Enter a staffing request first.")
        return None
    try:
        return StaffingRequest(text=text, shift_id=selected_shift)
    except ValueError as exc:
        st.error(f"Invalid request: {exc}")
        return None


def run_with_progress(assistant: ShiftFillAssistant, request: StaffingRequest) -> StaffingReport:
    """Show one friendly progress line while running, then clear it for the status banner."""
    placeholder = st.empty()
    with placeholder.status("Agent working...", expanded=False) as status:

        def show(event: TraceEvent) -> None:
            status.update(label=f"Agent working: {progress_label(event)}...")

        report = assistant.run(request, on_event=show)
    placeholder.empty()
    return report


def progress_label(event: TraceEvent) -> str:
    if event.kind == "tool":
        return PROGRESS_LABELS.get(event.name, "using a tool")
    return PROGRESS_LABELS[event.kind]


def render_report(
    report: StaffingReport, review: OutreachReview, assistant: ShiftFillAssistant
) -> None:
    show, icon, label = STATUS_STYLE[report.status]
    show(f"**{label}:** {status_message(report)}", icon=icon)
    color, mode_icon, mode, explanation = MODE_LABELS[report.mode]
    st.markdown(f"**Report mode:** {badge(color, mode_icon, mode)}", help=explanation)

    recommended = len(report.recommendations)
    positions = str(report.shift.positions_open) if report.shift else "-"
    coverage = report.coverage
    cols = st.columns(4)
    cols[0].metric("Recommended", recommended)
    cols[1].metric("Excluded", len(report.excluded))
    cols[2].metric(
        "Shortlisted / open positions",
        f"{recommended} / {positions}",
        help="Shortlisted clinicians have not been contacted, have not accepted, and are not "
        "booked.",
    )
    cols[3].metric(
        "Total vetted",
        coverage.evaluated if coverage else 0,
        help=vetting_note(report),
    )

    if report.shift:
        st.markdown(f"**Shift:** {describe_shift(report.shift)}")
    st.markdown(f"**Summary:** {report.summary}")
    if report.agent_notes:
        st.markdown(f"**Agent notes:** {report.agent_notes}")
    if report.clarification_question:
        st.markdown(f"**Question:** {report.clarification_question}")

    tabs = st.tabs(["Recommendations", "Alternates", "Excluded", "Verification", "Trace", "JSON"])
    with tabs[0]:
        if not report.recommendations:
            st.write("No recommendations.")
        for rec in report.recommendations:
            render_recommendation(rec, review, assistant)
    with tabs[1]:
        if not report.alternates:
            st.write("No eligible alternates.")
        for alt in report.alternates:
            render_candidate_row(
                alt.clinician_name,
                alt.clinician_id,
                credential_badges(alt.credentials),
                [w.message for w in alt.warnings],
            )
    with tabs[2]:
        if not report.excluded:
            st.write("Nobody was excluded.")
        for blocked in report.excluded:
            render_candidate_row(
                blocked.clinician_name,
                blocked.clinician_id,
                " ".join(badge("red", "block", blocker_label(r)) for r in blocked.reasons),
                [r.message for r in blocked.reasons],
            )
    with tabs[3]:
        if not report.issues:
            st.success("All references were verified against tool evidence.")
        for issue in report.issues:
            show = st.error if issue.severity is IssueSeverity.ERROR else st.warning
            show(f"`{issue.code}` {issue.message}")
    with tabs[4]:
        st.dataframe([e.model_dump() for e in report.trace], hide_index=True)
        m = report.metrics
        cols = st.columns(5)
        cols[0].metric("LLM calls", m.llm_calls)
        cols[1].metric("Tool calls", m.tool_calls)
        cols[2].metric("Input tokens", f"{m.input_tokens:,}")
        cols[3].metric("Output tokens", f"{m.output_tokens:,}")
        cols[4].metric("Elapsed time (s)", f"{m.duration_ms / 1000:.1f}")
    with tabs[5]:
        payload = report.model_dump_json(indent=2)
        st.download_button("Download JSON", payload, "staffing_report.json", "application/json")
        st.json(payload, expanded=False)


def status_message(report: StaffingReport) -> str:
    if report.status not in (ReportStatus.READY, ReportStatus.PARTIAL) or report.shift is None:
        return STATUS_MESSAGES.get(report.status, "")
    recommended, positions = len(report.recommendations), report.shift.positions_open
    if recommended == 0:
        alternates = plural(len(report.alternates), "eligible alternate")
        message = f"No one shortlisted yet; {alternates} to review"
    elif report.status is ReportStatus.PARTIAL:
        message = f"Only {shortlist_phrase(recommended, positions)}"
    else:
        message = shortlist_phrase(recommended, positions)
    return f"{message}. Human review required."


def vetting_note(report: StaffingReport) -> str:
    coverage = report.coverage
    if coverage is None or coverage.pool_size is None:
        return "The shift's candidate pool was not searched, so coverage is unconfirmed."
    if coverage.unevaluated_ids:
        return f"Not evaluated from the pool: {', '.join(coverage.unevaluated_ids)}."
    return "Every candidate in the shift's pool was evaluated."


def render_recommendation(
    rec: CandidateRecommendation, review: OutreachReview, assistant: ShiftFillAssistant
) -> None:
    with st.container(border=True):
        st.subheader(f"#{rec.rank} {rec.clinician_name}  ({rec.clinician_id})")
        if badges := credential_badges(rec.credentials):
            st.markdown(badges)
        st.write(rec.rationale)
        for warning in rec.warnings:
            st.caption(f":material/schedule: {warning.message}")
        for citation in rec.citations:
            with st.expander(f"Source: {citation.chunk_id}"):
                st.write(citation.text)
        if rec.outreach:
            render_outreach(review, rec.outreach.draft_id, assistant)


def render_candidate_row(name: str, clinician_id: str, badges: str, notes: list[str]) -> None:
    st.markdown(f"**{name}** ({clinician_id}) {badges}")
    if notes:
        st.caption(" · ".join(notes))


# --- Outreach review ----------------------------------------------------------------------------


def render_outreach(review: OutreachReview, draft_id: str, assistant: ShiftFillAssistant) -> None:
    """Read-only draft with a copy button; the coordinator edits the note and approves."""
    entry = review[draft_id]
    key = f"{review.run_id}-{draft_id}"  # widget state never leaks into another run
    st.markdown(f"**Outreach draft:** {entry.draft.subject}")
    st.code(entry.draft.body, language=None, wrap_lines=True)

    if entry.status is DraftStatus.EDITING:
        st.text_area(
            "Personal note",
            value=entry.draft.personal_note,
            key=f"note-{key}",
            height=110,
            help="Shift details, credential reminders and the reply deadline come from the "
            "system of record and are added back when you save.",
        )
        if entry.error:
            st.error(f"Note not saved: {entry.error}")
        with st.container(horizontal=True):
            st.button(
                "Save note",
                key=f"save-{key}",
                type="primary",
                on_click=save_note,
                args=(review.run_id, draft_id, assistant),
            )
            st.button(
                "Cancel", key=f"cancel-{key}", on_click=cancel_edit, args=(review.run_id, draft_id)
            )
        return

    approved = entry.status is DraftStatus.APPROVED
    if approved:
        st.success(APPROVED_MESSAGE, icon=":material/check:")
    with st.container(horizontal=True, vertical_alignment="center"):
        if not approved:
            st.button(
                "Approve & simulate sending",
                key=f"approve-{key}",
                type="primary",
                icon=":material/send:",
                on_click=approve_draft,
                args=(review.run_id, draft_id),
            )
            st.caption("Demo only—no message will be sent")
        st.button(
            "Edit note",
            key=f"edit-{key}",
            icon=":material/edit:",
            help="Editing withdraws the approval." if approved else None,
            on_click=start_edit,
            args=(review.run_id, draft_id),
        )


def current_review(run_id: str) -> OutreachReview | None:
    """The review for `run_id`, or None when the click came from an earlier run's widgets."""
    review: OutreachReview | None = st.session_state.get("review")
    return review if review is not None and review.run_id == run_id else None


def approve_draft(run_id: str, draft_id: str) -> None:
    if (review := current_review(run_id)) is not None:
        review.approve(draft_id)
        st.toast(APPROVED_MESSAGE, icon=":material/check_circle:")


def start_edit(run_id: str, draft_id: str) -> None:
    if (review := current_review(run_id)) is not None:
        review.start_editing(draft_id)


def cancel_edit(run_id: str, draft_id: str) -> None:
    if (review := current_review(run_id)) is not None:
        review.cancel_editing(draft_id)


def save_note(run_id: str, draft_id: str, assistant: ShiftFillAssistant) -> None:
    if (review := current_review(run_id)) is None:
        return
    draft = review[draft_id].draft
    note = st.session_state[f"note-{run_id}-{draft_id}"]
    try:
        revised = assistant.revise_outreach(draft.shift_id, draft.clinician_id, note)
    except ValueError as exc:
        review.reject_edit(draft_id, str(exc))
    else:
        review.save(draft_id, revised)


# --- Credential badges --------------------------------------------------------------------------


def badge(color: str, icon: str, label: str) -> str:
    return f":{color}-badge[:material/{icon}: {label}]"


def credential_badges(checks: list[CredentialCheck]) -> str:
    """One badge per required credential, straight from the eligibility engine's checks."""
    return " ".join(credential_badge(check) for check in checks)


def credential_badge(check: CredentialCheck) -> str:
    color, icon, template = CREDENTIAL_LABELS[check.status]
    expires = ""
    if check.expires_on is not None:
        expires = f"{check.expires_on:%b} {check.expires_on.day}, {check.expires_on.year}"
    return badge(color, icon, template.format(name=credential_label(check), expires=expires))


def credential_label(check: CredentialCheck) -> str:
    if check.type is not CredentialType.RN_LICENSE:
        return check.type.value
    if check.status is CredentialStatus.NOT_VALID_IN_STATE or not check.jurisdiction:
        return "RN license"
    if check.jurisdiction == COMPACT_JURISDICTION:
        return "Compact RN license"
    return f"{check.jurisdiction} RN license"


def credential_name(credential: CredentialType | None) -> str:
    return "RN license" if credential is CredentialType.RN_LICENSE else str(credential)


def blocker_label(finding: Finding) -> str:
    template = BLOCKER_LABELS.get(finding.code)
    if template is None:
        return finding.code.replace("_", " ").capitalize()
    return template.format(credential=credential_name(finding.credential))


main()
