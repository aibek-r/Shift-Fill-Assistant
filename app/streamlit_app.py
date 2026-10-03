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
from shift_assistant.rendering import describe_shift
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import Embedder, create_embedder
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
    ReportStatus.READY: (st.success, "Ready: enough eligible candidates for every open position."),
    ReportStatus.PARTIAL: (st.warning, "Partial: fewer eligible candidates than open positions."),
    ReportStatus.NO_ELIGIBLE_CANDIDATES: (st.error, "No eligible candidates for this shift."),
    ReportStatus.NEEDS_CLARIFICATION: (st.info, "The assistant needs more information."),
    ReportStatus.FAILED: (st.error, "The request could not be completed."),
}


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
    simulate_outage, pinned_shift = render_sidebar()
    assistant = get_assistant(simulate_outage)

    st.title("Shift Fill Assistant")
    st.caption(
        "Turns a staffing request into a vetted shortlist with outreach drafts. "
        "Compliance verdicts come from deterministic rules, every claim is checked against "
        "tool evidence, and nothing is sent automatically."
    )

    text = st.text_area(
        "Staffing request",
        key="request_text",
        height=90,
        placeholder="e.g. Find two ICU nurses for the St. Mary's night shift on October 14.",
    )
    if st.button("Run assistant", type="primary", disabled=not text.strip()):
        try:
            request = StaffingRequest(text=text, shift_id=pinned_shift)
        except ValueError as exc:
            st.error(f"Invalid request: {exc}")
        else:
            st.session_state["report"] = run_with_progress(assistant, request)

    report: StaffingReport | None = st.session_state.get("report")
    if report is not None:
        render_report(report)


def render_sidebar() -> tuple[bool, str | None]:
    with st.sidebar:
        st.header("Setup")
        settings = Settings()
        if settings.llm_enabled:
            st.success(f"AI agent enabled: `{settings.openai_model}`")
        else:
            st.warning("No OPENAI_API_KEY: running the deterministic fallback only.")
        simulate_outage = st.toggle(
            "Simulate LLM outage",
            help="Every model call fails, so you can see the deterministic fallback.",
        )

        st.header("Pin a shift (optional)")
        shifts = get_repository().shifts()
        labels = {
            s.id: f"{s.id} - {unit_label(s.unit)} - {format_local_datetime(s.start)}"
            for s in shifts
        }
        pinned = st.selectbox(
            "Shift",
            options=[None, *labels],
            format_func=lambda sid: "Let the agent find it" if sid is None else labels[sid],
        )

        st.header("Examples")
        for name, example in EXAMPLES.items():
            if st.button(name, width="stretch"):
                st.session_state["request_text"] = example
                st.session_state.pop("report", None)
                st.rerun()
    return simulate_outage, pinned


def run_with_progress(assistant: ShiftFillAssistant, request: StaffingRequest) -> StaffingReport:
    """Show one friendly progress line; the detailed log lives in the Trace tab."""
    with st.status("Agent working...", expanded=False) as status:

        def show(event: TraceEvent) -> None:
            status.update(label=f"Agent working: {progress_label(event)}...")

        report = assistant.run(request, on_event=show)
        status.update(label="Done", state="complete", expanded=False)
    return report


def progress_label(event: TraceEvent) -> str:
    if event.kind == "tool":
        return PROGRESS_LABELS.get(event.name, "using a tool")
    return PROGRESS_LABELS[event.kind]


def render_report(report: StaffingReport) -> None:
    show_banner, message = STATUS_STYLE[report.status]
    show_banner(message)
    if report.mode is RunMode.FALLBACK:
        st.warning("Fallback mode: the AI workflow was unavailable, so rules alone were used.")

    m = report.metrics
    cols = st.columns(5)
    cols[0].metric("Recommended", len(report.recommendations))
    cols[1].metric("Excluded", len(report.excluded))
    cols[2].metric("LLM / tool calls", f"{m.llm_calls} / {m.tool_calls}")
    cols[3].metric("Tokens", f"{m.input_tokens + m.output_tokens:,}")
    cols[4].metric("Time", f"{m.duration_ms / 1000:.1f}s")

    if report.shift:
        st.markdown(f"**Shift:** {describe_shift(report.shift)}")
    st.markdown(f"**Summary:** {report.summary}")
    if report.clarification_question:
        st.info(f"**Question:** {report.clarification_question}")

    tabs = st.tabs(
        ["Recommendations", "Other eligible", "Excluded", "Verification", "Trace", "JSON"]
    )
    with tabs[0]:
        if not report.recommendations:
            st.write("No recommendations.")
        for rec in report.recommendations:
            render_recommendation(rec)
    with tabs[1]:
        if report.alternates:
            st.dataframe(
                [
                    {
                        "Clinician": f"{a.clinician_name} ({a.clinician_id})",
                        "Warnings": "; ".join(w.message for w in a.warnings) or "None",
                    }
                    for a in report.alternates
                ],
                hide_index=True,
            )
        else:
            st.write("No other eligible candidates were vetted.")
    with tabs[2]:
        if report.excluded:
            st.dataframe(
                [
                    {
                        "Clinician": f"{e.clinician_name} ({e.clinician_id})",
                        "Reasons": "; ".join(f"{r.code}: {r.message}" for r in e.reasons),
                    }
                    for e in report.excluded
                ],
                hide_index=True,
            )
        else:
            st.write("Nobody was excluded.")
    with tabs[3]:
        if not report.issues:
            st.success("All references were verified against tool evidence.")
        for issue in report.issues:
            show = st.error if issue.severity is IssueSeverity.ERROR else st.warning
            show(f"`{issue.code}` {issue.message}")
    with tabs[4]:
        st.dataframe([e.model_dump() for e in report.trace], hide_index=True)
    with tabs[5]:
        payload = report.model_dump_json(indent=2)
        st.download_button("Download JSON", payload, "staffing_report.json", "application/json")
        st.json(payload, expanded=False)


def render_recommendation(rec: CandidateRecommendation) -> None:
    with st.container(border=True):
        st.subheader(f"#{rec.rank} {rec.clinician_name}  ({rec.clinician_id})")
        st.write(rec.rationale)
        for warning in rec.warnings:
            st.warning(f"{warning.code}: {warning.message}")
        for citation in rec.citations:
            with st.expander(f"Source: {citation.chunk_id}"):
                st.write(citation.text)
        if rec.outreach:
            st.text_area(
                f"Outreach draft: {rec.outreach.subject}",
                rec.outreach.body,
                height=260,
                disabled=True,
                key=f"draft-{rec.outreach.draft_id}",
            )
            st.caption("Draft only. A coordinator reviews and sends it.")


main()
