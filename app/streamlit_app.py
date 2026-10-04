"""Streamlit UI for the Shift Fill Assistant.  Run: `streamlit run app/streamlit_app.py`."""

from __future__ import annotations

import re
from html import escape
from inspect import signature
from pathlib import Path
from typing import Any

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
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import Embedder, create_embedder
from shift_assistant.retrieval.knowledge import GLOBAL_SCOPE
from shift_assistant.review import DraftStatus, OutreachReview
from shift_assistant.tools.facts import FRIENDLY_NOTES
from shift_assistant.tools.outreach import format_local_datetime, unit_label
from shift_assistant.tools.schemas import PolicyExcerpt, ShiftSummary

ASSETS = Path(__file__).parent / "assets"
CONTENT_WIDTH = 1080
IMAGE_SUPPORTS_ALT = "alt" in signature(st.image).parameters


def display_image(image: str, *, width: int, alt: str) -> None:
    """Supply accessible image labels when supported, including Streamlit 1.64 compatibility."""
    options: dict[str, Any] = {"width": width}
    if IMAGE_SUPPORTS_ALT:
        options["alt"] = alt
    st.image(image, **options)


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

EXAMPLE_DETAILS = {
    "ICU night shift": (":material/nightlight:", "Two nurses, with outreach drafts"),
    "PICU shortlist": (":material/pediatrics:", "Pediatric care, with a credential warning"),
    "Ambiguous request": (":material/help:", "See how the assistant asks for details"),
    "Unknown facility": (":material/location_on:", "Choose from the available facilities"),
    "Nobody eligible": (":material/person_search:", "Review the reasons candidates were excluded"),
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
    ReportStatus.NO_ELIGIBLE_CANDIDATES: (
        st.error,
        ":material/block:",
        "No eligible clinicians found",
    ),
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
        "The LLM planned and ranked. Code rendered recorded facts and decided compliance. Every "
        "referenced clinician, policy and draft was checked against tool evidence.",
    ),
    RunMode.FALLBACK: (
        "orange",
        "rule",
        "Rule-based fallback",
        "The AI workflow was unavailable, so deterministic rules alone built this report.",
    ),
}

# Coordinator-facing wording for verification issues; the raw messages stay in Technical details.
ISSUE_ACTIONS = {
    "INCOMPLETE_VETTING": "Some candidates in the pool were not compliance-checked, so a better "
    "match may exist.",
    "POOL_NOT_SEARCHED": "The shift's candidate pool was never searched, so other eligible "
    "clinicians may exist.",
    "UNKNOWN_CITATION": "A source was removed from a rationale because it could not be verified.",
    "OTHER_FACILITY_CITATION": "A source from another facility was removed from a rationale.",
    "RATIONALE_WARNING_MISMATCH": "A rationale does not mention a credential warning. Rely on the "
    "credential badges, not the rationale text.",
    "INVALID_DRAFT": "An outreach draft was removed because it could not be verified. Write that "
    "message manually.",
}
REMOVED_RECOMMENDATION = "A recommendation was removed because it failed evidence checks."
INFORMATIONAL_ISSUES = {"FALLBACK_MODE"}  # already shown as the report mode

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

APPROVE_PROMPT = "Approve this message."
APPROVED_MESSAGE = "Message approved successfully."
DEMO_NOTE = "Demo mode: delivery is simulated."


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
    st.set_page_config(
        page_title="Shift Fill Assistant", page_icon=str(ASSETS / "mark.svg"), layout="wide"
    )
    st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "mark.svg"), size="large")
    simulate_outage, selected_shift = render_sidebar()
    with st.container(horizontal_alignment="center"), st.container(width=CONTENT_WIDTH):
        render_workspace(simulate_outage, selected_shift)


def render_workspace(simulate_outage: bool, selected_shift: str | None) -> None:
    render_header()
    assistant = get_assistant(simulate_outage)
    if assistant.retrieval_degraded:
        st.sidebar.warning(
            "The semantic search model could not be loaded, so keyword matching is used. "
            "Policy and profile search will be less accurate."
        )

    request = render_request_form(selected_shift)
    if request is not None:
        # Drop the previous result first so a failed run never leaves stale results on screen.
        st.session_state.pop("report", None)
        st.session_state.pop("review", None)
        new_report = run_with_progress(assistant, request)
        # A new run gets a new review, so no approval carries over from an earlier result.
        st.session_state["report"] = new_report
        st.session_state["review"] = OutreachReview.for_report(new_report)

    report: StaffingReport | None = st.session_state.get("report")
    if report is not None:
        review: OutreachReview = st.session_state["review"]
        render_report(report, review, assistant)
    else:
        render_empty_state()


def clear_result() -> None:
    st.session_state.pop("report", None)
    st.session_state.pop("review", None)


def render_sidebar() -> tuple[bool, str | None]:
    with st.sidebar:
        st.caption("Staffing operations")
        if not Settings().llm_enabled:
            st.warning("AI is unavailable. Shortlists will use the recorded eligibility rules.")

        st.subheader("Select a shift", icon=":material/calendar_month:")
        st.caption("Optional. Pin a shift or let the assistant find it.")
        shifts = get_repository().shifts()
        labels = {
            s.id: f"{s.id} - {unit_label(s.unit)} - {format_local_datetime(s.start)}"
            for s in shifts
        }
        selected = st.selectbox(
            "Shift",
            options=[None, *labels],
            format_func=lambda sid: "Let the agent find it" if sid is None else labels[sid],
            key="selected_shift",
            on_change=clear_result,
        )

        st.subheader("Try an example", icon=":material/lightbulb:")
        for name, example in EXAMPLES.items():
            icon, description = EXAMPLE_DETAILS[name]
            with st.container(gap="xsmall"):
                st.button(name, width="stretch", icon=icon, on_click=use_example, args=(example,))
                st.caption(description)

        with st.expander("Demo controls", icon=":material/science:"):
            simulate_outage = st.toggle(
                "Simulate LLM outage",
                help="Every model call fails, so you can see the deterministic fallback.",
                on_change=clear_result,
            )
        render_about()
        st.caption(":material/lock: Human review before outreach. Delivery is simulated.")
    return simulate_outage, selected


def use_example(text: str) -> None:
    st.session_state["request_text"] = text
    st.session_state["selected_shift"] = None
    clear_result()


def render_header() -> None:
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        display_image(str(ASSETS / "mark.svg"), width=56, alt="Shift Fill calendar and checkmark")
        with st.container(width="content", gap=None):
            st.caption("YOUR STAFFING WORKSPACE")
            st.title("Shift Fill Assistant")
    st.markdown("Find eligible clinicians. Review the shortlist. Make the next shift happen.")


def render_about() -> None:
    with st.expander("About this assistant", icon=":material/info:"):
        st.markdown(
            "- **Compliance is rule-based.** Licensure, certifications, experience, "
            "double-booking and rest time are checked by deterministic code, never by the model.\n"
            "- **References are verified.** Every clinician, policy citation and draft in the "
            "answer is checked against tool evidence before it reaches you (see Technical "
            "details). Candidate facts and explanations are rendered from records.\n"
            "- **Nothing is sent.** A coordinator reviews, edits and approves each outreach "
            "message; delivery is simulated in this demo."
        )


def render_request_form(selected_shift: str | None) -> StaffingRequest | None:
    # Inside a form, Ctrl/Cmd+Enter in the text area submits the request.
    with st.form("request_form", border=True):
        st.subheader("What shift do you need to fill?", icon=":material/edit_note:")
        st.caption("Include the facility, unit, date and number of clinicians you need.")
        text = st.text_area(
            "Staffing request",
            key="request_text",
            height=110,
            placeholder="e.g. Find two ICU nurses for the St. Mary's night shift on October 14.",
        )
        with st.container(horizontal=True, vertical_alignment="center"):
            submitted = st.form_submit_button(
                "Run assistant", type="primary", icon=":material/auto_awesome:"
            )
            st.caption("or press **Ctrl+Enter** (**⌘+Enter** on Mac)")
    if not submitted:
        return None
    clear_result()
    if not text.strip():
        st.warning("Enter a staffing request first.")
        return None
    try:
        return StaffingRequest(text=text, shift_id=selected_shift)
    except ValueError as exc:
        st.error(f"Invalid request: {exc}")
        return None


def render_empty_state() -> None:
    with (
        st.container(border=True, gap="small"),
        st.container(horizontal=True, vertical_alignment="center", gap="medium"),
    ):
        display_image(
            str(ASSETS / "workflow.svg"),
            width=260,
            alt="A shift calendar, checked clinician profile, and outreach message",
        )
        with st.container(width=550, gap="xsmall"):
            st.subheader("A clear path from open shift to shortlist")
            st.caption("Start with a request above, or choose an example in the sidebar.")
            st.markdown(
                ":blue-badge[:material/calendar_month: Find shift] "
                ":blue-badge[:material/verified_user: Check eligibility] "
                ":blue-badge[:material/mail: Review outreach]"
            )


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
    if report.status is ReportStatus.NEEDS_CLARIFICATION:
        render_clarification(report, assistant)
    else:
        show, icon, label = STATUS_STYLE[report.status]
        show(f"**{label}:** {status_message(report)}", icon=icon)
    render_action_items(report)
    st.markdown(f"**Summary:** {report.summary}")
    color, mode_icon, mode, explanation = MODE_LABELS[report.mode]
    st.markdown(f"**Report mode:** {badge(color, mode_icon, mode)}", help=explanation)
    if report.coverage is None:
        # Nothing was evaluated (a clarifying question or a failed run), so zero counts and
        # empty candidate tabs would only suggest a search that never happened.
        render_technical_details(report, review)
        return
    if report.shift:
        render_shift_overview(report.shift)
    render_counts(report)

    recommendations, alternates, excluded = st.tabs(["Recommendations", "Alternates", "Excluded"])
    with recommendations:
        if report.agent_notes:
            title = "Why these clinicians?" if report.recommendations else "Agent notes"
            with st.expander(title, icon=":material/psychology:"):
                st.markdown(report.agent_notes)
        if not report.recommendations:
            st.write("No recommendations.")
        for rec in report.recommendations:
            render_recommendation(rec, review, assistant)
    with alternates:
        if not report.alternates:
            st.write("No eligible alternates.")
        for alt in report.alternates:
            render_candidate_row(
                alt.clinician_name,
                alt.clinician_id,
                credential_badges(alt.credentials),
                [w.message for w in alt.warnings],
            )
    with excluded:
        if not report.excluded:
            st.write("Nobody was excluded.")
        for blocked in report.excluded:
            render_candidate_row(
                blocked.clinician_name,
                blocked.clinician_id,
                " ".join(badge("red", "block", blocker_label(r)) for r in blocked.reasons),
                [r.message for r in blocked.reasons],
            )

    render_technical_details(report, review)


def render_clarification(report: StaffingReport, assistant: ShiftFillAssistant) -> None:
    question = report.clarification_question or "Update the request with a facility and shift date."
    normalized = re.sub(r"[^a-z0-9]", "", question.casefold())
    facilities = (
        [
            facility
            for facility in assistant.repository.facilities()
            if re.sub(r"[^a-z0-9]", "", facility.name.casefold()) in normalized
        ]
        if report.request.shift_id is None
        else []
    )
    with st.container(border=True):
        st.subheader(
            "Choose a facility" if len(facilities) > 1 else "One detail to confirm",
            icon=":material/help:",
        )
        if len(facilities) > 1:
            st.caption("Choose a facility to update your request, then run the assistant again.")
            with st.expander("Clarification details", icon=":material/info:"):
                st.write(question)
            with st.container(horizontal=True, gap="small"):
                for facility in facilities:
                    with st.container(border=True, width=300, gap="xsmall"):
                        st.markdown(f"**{facility.name}**")
                        st.caption(f"{facility.city}, {facility.state}")
                        st.button(
                            "Use this facility",
                            key=f"clarify-{facility.id}",
                            icon=":material/location_on:",
                            width="stretch",
                            on_click=use_facility,
                            args=(report, facility.name),
                        )
        else:
            st.write(question)


def use_facility(report: StaffingReport, facility_name: str) -> None:
    if st.session_state.get("report") is not report:
        return  # Ignore a click from a report that has already been replaced.
    text = report.request.text
    # Replace the rejected facility only when the tool's own error identifies it exactly.
    for event in report.trace:
        if event.name != "find_open_shifts":
            continue
        if (
            match := re.search(r"No facility matches '(.+)'\. Known facilities:", event.detail)
        ) and re.search(re.escape(match[1]), text, re.IGNORECASE):
            text = re.sub(
                re.escape(match[1]), lambda _: facility_name, text, count=1, flags=re.IGNORECASE
            )
            break
    else:
        text += f"\nFacility clarification: use {facility_name} for this request."
    st.session_state["request_text"] = text
    st.session_state["selected_shift"] = None
    clear_result()


def status_message(report: StaffingReport) -> str:
    if report.status is ReportStatus.NEEDS_CLARIFICATION and report.clarification_question:
        return report.clarification_question
    coverage = report.coverage
    if report.status is ReportStatus.NO_ELIGIBLE_CANDIDATES and (
        coverage is None or not coverage.full_pool_evaluated
    ):
        return (
            "No evaluated candidate passed the compliance checks, but the shift's candidate pool "
            "was not fully checked. Review before closing this shift."
        )
    if report.status not in (ReportStatus.READY, ReportStatus.PARTIAL) or report.shift is None:
        return STATUS_MESSAGES.get(report.status, "")
    recommended, positions = len(report.recommendations), report.shift.positions_open
    if report.request.requested_count is not None:
        target = report.request.requested_count
        return (
            f"{recommended} of {target} requested clinicians shortlisted; "
            f"{plural(positions, 'open position')}. Human review required."
        )
    if recommended == 0:
        alternates = plural(len(report.alternates), "eligible alternate")
        message = f"No one shortlisted yet; {alternates} to review"
    elif report.status is ReportStatus.PARTIAL:
        message = f"Only {shortlist_phrase(recommended, positions)}"
    else:
        message = shortlist_phrase(recommended, positions)
    return f"{message}. Human review required."


def render_action_items(report: StaffingReport) -> None:
    """Verification findings a coordinator should act on, in plain words."""
    issues = [
        i
        for i in report.issues
        if i.severity is not IssueSeverity.INFO and i.code not in INFORMATIONAL_ISSUES
    ]
    if not issues:
        return
    actions = dict.fromkeys(
        REMOVED_RECOMMENDATION
        if i.severity is IssueSeverity.ERROR
        else ISSUE_ACTIONS.get(i.code, i.message)
        for i in issues
    )
    alert = st.error if any(i.severity is IssueSeverity.ERROR for i in issues) else st.warning
    bullets = "\n".join(f"- {action}" for action in actions)
    alert(f"**Check before contacting anyone:**\n{bullets}\n\nDetails are under Technical details.")


def render_shift_overview(shift: ShiftSummary) -> None:
    with st.container(border=True):
        st.markdown(f"**Shift overview** :gray[{shift.shift_id}]")
        where = {
            "Facility": f"{shift.facility_name}, {shift.location}",
            "Unit": f"{unit_label(shift.unit)} ({shift.period})",
            "Open positions": str(shift.positions_open),
        }
        when = {
            "Start": format_local_datetime(shift.start),
            "End": format_local_datetime(shift.end),  # carries its own date for overnight shifts
            "Time zone": shift.timezone,
        }
        for fields in (where, when):
            with st.container(horizontal=True, gap="medium"):  # wraps on narrow screens
                for label, value in fields.items():
                    st.markdown(f":gray[{label}]  \n**{value}**", width="content")


def render_counts(report: StaffingReport) -> None:
    coverage = report.coverage
    shortlisted = len(report.recommendations)
    alternates, excluded = len(report.alternates), len(report.excluded)
    counts = [
        (
            "Shortlisted",
            shortlisted,
            "Proposed for human review only: not contacted, not accepted and not booked.",
        ),
        ("Alternates", alternates, "Eligible, but not shortlisted."),
        ("Excluded", excluded, "Failed at least one compliance rule."),
        (
            "Evaluated",
            coverage.evaluated if coverage else shortlisted + alternates + excluded,
            vetting_note(report),
        ),
    ]
    # A wrapping row: four across on desktop, two per line on a phone.
    with st.container(horizontal=True, horizontal_alignment="distribute", gap="medium"):
        for label, value, explanation in counts:
            st.metric(label, value, help=explanation, width=220, border=True)


def vetting_note(report: StaffingReport) -> str:
    coverage = report.coverage
    if coverage is None or coverage.pool_size is None:
        return "The shift's candidate pool was not searched, so coverage is unconfirmed."
    if coverage.unevaluated_ids:
        return f"Not evaluated from the pool: {', '.join(coverage.unevaluated_ids)}."
    return "Every candidate in the shift's pool was evaluated."


def render_technical_details(report: StaffingReport, review: OutreachReview) -> None:
    with st.expander("Technical details", icon=":material/build:"):
        verification, trace, raw = st.tabs(["Verification", "Trace", "JSON"])
        with verification:
            if not report.issues:
                st.success("All references were verified against tool evidence.")
            for issue in report.issues:
                show = st.error if issue.severity is IssueSeverity.ERROR else st.warning
                show(f"`{issue.code}` {issue.message}")
        with trace:
            st.dataframe([e.model_dump() for e in report.trace], hide_index=True)
            m = report.metrics
            cols = st.columns(5)
            cols[0].metric("LLM calls", m.llm_calls)
            cols[1].metric("Tool calls", m.tool_calls)
            cols[2].metric("Input tokens", f"{m.input_tokens:,}")
            cols[3].metric("Output tokens", f"{m.output_tokens:,}")
            cols[4].metric("Elapsed time (s)", f"{m.duration_ms / 1000:.1f}")
        with raw:
            payload = review.export_report(report).model_dump_json(indent=2)
            st.download_button("Download JSON", payload, "staffing_report.json", "application/json")
            st.json(payload, expanded=False)


def render_recommendation(
    rec: CandidateRecommendation, review: OutreachReview, assistant: ShiftFillAssistant
) -> None:
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            display_image(
                initials_avatar(rec.clinician_name),
                width=48,
                alt=f"Initials avatar for {rec.clinician_name}",
            )
            with st.container(width="content", gap=None):
                st.subheader(f"#{rec.rank} {rec.clinician_name}")
                st.caption(f"{rec.clinician_id} · Recommended for review")
        if badges := credential_badges(rec.credentials):
            st.markdown(badges)
        for warning in rec.warnings:  # stays visible: it needs action before the shift
            st.markdown(f":orange[:material/warning:] {warning.message}")
        st.write(rec.rationale)
        for citation in rec.citations:
            with st.expander(f"Source: {source_title(citation)}", icon=":material/description:"):
                st.caption(f"Citation ID: {citation.chunk_id}")
                st.write(citation.text)
        if rec.outreach:
            render_outreach(review, rec.outreach.draft_id, assistant)


def source_title(citation: PolicyExcerpt) -> str:
    if citation.facility_id == GLOBAL_SCOPE:
        return f"{citation.section} (all facilities)"
    return citation.section


def render_candidate_row(name: str, clinician_id: str, badges: str, notes: list[str]) -> None:
    with st.container(border=True, gap="xsmall"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            display_image(initials_avatar(name), width=36, alt=f"Initials avatar for {name}")
            st.markdown(f"**{name}** :gray[{clinician_id}]")
        if badges:
            st.markdown(badges)
        if notes:
            st.caption(" · ".join(notes))


def initials_avatar(name: str) -> str:
    parts = name.split()
    initials = "".join(part[0] for part in (parts[:1] + parts[-1:] if len(parts) > 1 else parts))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
        '<rect width="48" height="48" rx="15" fill="#EAF5F3"/>'
        '<text x="24" y="30" text-anchor="middle" fill="#115E59" '
        'font-family="Arial, sans-serif" font-size="16" font-weight="700">'
        f"{escape(initials.upper() or '?')}</text></svg>"
    )


# --- Outreach review ----------------------------------------------------------------------------


def render_outreach(review: OutreachReview, draft_id: str, assistant: ShiftFillAssistant) -> None:
    """Read-only draft with a copy button; the coordinator edits the note and approves."""
    entry = review[draft_id]
    key = f"{review.run_id}-{draft_id}"  # widget state never leaks into another run or draft
    approved = entry.status is DraftStatus.APPROVED
    with st.expander(
        "Review outreach draft",
        key=f"outreach-{key}",  # tracked, so it stays open across the reruns its buttons cause
        on_change="rerun",
        icon=":material/check_circle:" if approved else ":material/mail:",
    ):
        st.markdown(f"**Subject:** {entry.draft.subject}")
        st.code(entry.draft.body, language=None, wrap_lines=True)

        if entry.status is DraftStatus.EDITING:
            st.caption("Use 1-3 of these sentences. Recorded facts are added automatically:")
            st.write(" ".join(FRIENDLY_NOTES))
            st.text_area(
                "Personal note",
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
                    "Cancel",
                    key=f"cancel-{key}",
                    on_click=cancel_edit,
                    args=(review.run_id, draft_id),
                )
        else:
            if approved:
                st.success(APPROVED_MESSAGE, icon=":material/check:")
            else:
                st.markdown(APPROVE_PROMPT)
            with st.container(horizontal=True):
                if not approved:
                    st.button(
                        "Approve message",
                        key=f"approve-{key}",
                        type="primary",
                        icon=":material/check:",
                        on_click=approve_draft,
                        args=(review.run_id, draft_id),
                    )
                st.button(
                    "Edit note",
                    key=f"edit-{key}",
                    icon=":material/edit:",
                    help="Editing withdraws the approval." if approved else None,
                    on_click=start_edit,
                    args=(review.run_id, draft_id),
                )
        st.caption(DEMO_NOTE)


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
        st.session_state[f"note-{run_id}-{draft_id}"] = review[draft_id].draft.personal_note
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
