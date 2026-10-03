"""End-to-end tests of the LangGraph workflow, driven by a scripted chat model."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from shift_assistant.assistant import build_assistant
from shift_assistant.contracts import ReportStatus, RunMode, StaffingRequest
from shift_assistant.domain.eligibility import CheckCode
from shift_assistant.retrieval.embedder import HashingEmbedder
from tests.conftest import AssistantFactory, ai, make_settings, tool_call

SUBMIT = "submit_recommendation"
REQUEST = StaffingRequest(text="Two ICU nurses for the St. Mary's night shift on Oct 14, please.")
ICU_PROFILE = "FAC-001#icu-unit-profile"
MARIA_DRAFT = "DRAFT-SHF-1001-C-101"


def rec(
    clinician_id: str, citations: tuple[str, ...] = (), draft: str | None = None
) -> dict[str, Any]:
    return {
        "clinician_id": clinician_id,
        "rationale": "Eligible per evaluate_candidates and matches the unit preferences.",
        "citation_ids": list(citations),
        "draft_id": draft,
    }


def submission(*recs: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "completed",
        "shift_id": "SHF-1001",
        "recommendations": list(recs),
        "summary": "Vetted the ICU candidates for SHF-1001.",
    }


def clarification() -> dict[str, Any]:
    return {
        "status": "needs_clarification",
        "summary": "Two ICU shifts match the request.",
        "clarification_question": "Do you mean SHF-1001 (night) or SHF-1003 (day)?",
    }


def research_steps() -> list[AIMessage]:
    """Typical ReAct steps: resolve the shift, retrieve policy, vet, draft."""
    return [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(
            tool_call(
                "search_facility_policies", facility_id="FAC-001", query="ICU unit profile", top_k=8
            ),
            tool_call(
                "evaluate_candidates",
                shift_id="SHF-1001",
                clinician_ids=["C-101", "C-102", "C-104"],
            ),
        ),
        ai(
            tool_call(
                "draft_outreach",
                shift_id="SHF-1001",
                clinician_id="C-101",
                personal_note="Your CCRN certification and CRRT experience fit this ICU well.",
            )
        ),
    ]


def test_happy_path_produces_a_grounded_report(scripted_assistant: AssistantFactory) -> None:
    final = submission(rec("C-101", (ICU_PROFILE,), MARIA_DRAFT), rec("C-104"))
    assistant, _ = scripted_assistant([*research_steps(), ai(tool_call(SUBMIT, **final))])

    report = assistant.run(REQUEST)

    assert (report.mode, report.status) == (RunMode.AGENT, ReportStatus.READY)
    assert [r.clinician_name for r in report.recommendations] == ["Maria Santos", "Daniel Kim"]
    maria, daniel = report.recommendations
    assert [c.chunk_id for c in maria.citations] == [ICU_PROFILE]
    assert maria.outreach is not None and maria.outreach.draft_id == MARIA_DRAFT
    assert [w.code for w in daniel.warnings] == [CheckCode.CREDENTIAL_EXPIRING_SOON]
    assert [e.clinician_id for e in report.excluded] == ["C-102"]
    assert report.issues == []
    assert (report.metrics.llm_calls, report.metrics.tool_calls) == (4, 4)


def test_hallucinated_and_ineligible_candidates_are_sent_back_for_repair(
    scripted_assistant: AssistantFactory,
) -> None:
    bad = submission(rec("C-999"), rec("C-102"), rec("C-101"))
    good = submission(rec("C-101"))
    assistant, model = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **bad)), ai(tool_call(SUBMIT, **good))]
    )

    report = assistant.run(REQUEST)

    feedback = model.received[-1][-1]
    assert isinstance(feedback, ToolMessage) and feedback.status == "error"
    assert "C-999 was not vetted" in str(feedback.content)
    assert "C-102 is not eligible" in str(feedback.content)
    assert [r.clinician_id for r in report.recommendations] == ["C-101"]
    assert [a.clinician_id for a in report.alternates] == ["C-104"]  # eligible, not shortlisted
    assert report.status is ReportStatus.PARTIAL  # 1 candidate for 2 open positions
    assert [e.ok for e in report.trace if e.kind == "validation"] == [False, True]


def test_ungrounded_content_is_stripped_when_repairs_run_out(
    scripted_assistant: AssistantFactory,
) -> None:
    final = submission(rec("C-999"), rec("C-101", ("FAC-001#invented-policy",), "DRAFT-FAKE"))
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert report.mode is RunMode.AGENT
    assert [r.clinician_id for r in report.recommendations] == ["C-101"]
    assert report.recommendations[0].citations == []
    assert report.recommendations[0].outreach is None
    assert {i.code for i in report.issues} == {"NOT_VETTED", "UNKNOWN_CITATION", "INVALID_DRAFT"}


def test_unparseable_answer_falls_back_to_rules(scripted_assistant: AssistantFactory) -> None:
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, status="completed"))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert report.mode is RunMode.FALLBACK
    assert report.shift is not None and report.shift.shift_id == "SHF-1001"  # from the ledger
    assert [r.clinician_name for r in report.recommendations] == ["Maria Santos", "Grace Liu"]
    assert report.issues[0].code == "FALLBACK_MODE"


def test_llm_outage_degrades_to_rules_for_a_pinned_shift(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant([RuntimeError("503 Service Unavailable")])

    report = assistant.run(StaffingRequest(text="Fill the NICU shift", shift_id="SHF-3002"))

    assert (report.mode, report.status) == (RunMode.FALLBACK, ReportStatus.NO_ELIGIBLE_CANDIDATES)
    assert {e.clinician_id for e in report.excluded} == {"C-116", "C-119", "C-120"}
    assert "LLM call failed (RuntimeError)" in report.issues[0].message


def test_step_budget_stops_a_looping_agent(scripted_assistant: AssistantFactory) -> None:
    loop = [ai(tool_call("find_open_shifts", facility="St. Mary's", unit="ICU")) for _ in range(3)]
    assistant, model = scripted_assistant(loop, max_agent_steps=2)

    report = assistant.run(REQUEST)

    assert len(model.received) == 2
    assert (report.mode, report.status) == (RunMode.FALLBACK, ReportStatus.FAILED)  # 2 shifts
    assert "step budget" in report.issues[0].message


def test_missing_api_key_runs_in_fallback_mode() -> None:
    assistant = build_assistant(make_settings(), embedder=HashingEmbedder())

    report = assistant.run(StaffingRequest(text="Fill the PICU shift", shift_id="SHF-3001"))

    assert assistant.llm_enabled is False
    assert report.mode is RunMode.FALLBACK
    assert [r.clinician_id for r in report.recommendations] == ["C-116"]
    assert report.recommendations[0].outreach is not None


def test_clarification_question_is_returned(scripted_assistant: AssistantFactory) -> None:
    assistant, _ = scripted_assistant(
        [
            ai(tool_call("find_open_shifts", facility="St. Mary's", unit="ICU")),
            ai(tool_call(SUBMIT, **clarification())),
        ]
    )

    report = assistant.run(StaffingRequest(text="An ICU nurse for St. Mary's next week"))

    assert report.status is ReportStatus.NEEDS_CLARIFICATION
    assert report.clarification_question == clarification()["clarification_question"]
    assert report.recommendations == []


def test_protocol_errors_are_reported_back_to_the_model(
    scripted_assistant: AssistantFactory,
) -> None:
    malformed = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "find_open_shifts",
                "args": "{oops",
                "id": "call_bad",
                "error": "bad json",
                "type": "invalid_tool_call",
            }
        ],
    )
    submit_too_early = ai(
        tool_call("find_open_shifts", shift_id="SHF-1001"), tool_call(SUBMIT, **clarification())
    )
    assistant, model = scripted_assistant(
        [malformed, submit_too_early, ai(tool_call(SUBMIT, **clarification()))]
    )

    report = assistant.run(REQUEST)

    json_error = model.received[1][-1]
    assert isinstance(json_error, ToolMessage) and "not valid JSON" in str(json_error.content)
    submit_error = model.received[2][-1]
    assert isinstance(submit_error, ToolMessage) and "on its own" in str(submit_error.content)
    assert report.status is ReportStatus.NEEDS_CLARIFICATION


ICU_POOL = ["C-101", "C-102", "C-103", "C-104", "C-105", "C-106", "C-107", "C-108", "C-109"]


def partial_vetting_steps() -> list[AIMessage]:
    """The agent searches the whole pool but vets only one candidate."""
    return [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(tool_call("search_clinicians", shift_id="SHF-1001", limit=25)),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=["C-107"])),
    ]


def test_partial_vetting_is_sent_back_until_the_pool_is_covered(
    scripted_assistant: AssistantFactory,
) -> None:
    lazy = submission(rec("C-107"))
    vet_all = ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=ICU_POOL))
    thorough = submission(rec("C-101"), rec("C-107"))
    assistant, model = scripted_assistant(
        [
            *partial_vetting_steps(),
            ai(tool_call(SUBMIT, **lazy)),
            vet_all,
            ai(tool_call(SUBMIT, **thorough)),
        ]
    )

    report = assistant.run(REQUEST)

    feedback = model.received[4][-1]
    assert isinstance(feedback, ToolMessage) and "were never vetted" in str(feedback.content)
    assert [r.clinician_id for r in report.recommendations] == ["C-101", "C-107"]
    assert report.issues == []


def test_incomplete_vetting_is_flagged_when_repairs_run_out(
    scripted_assistant: AssistantFactory,
) -> None:
    lazy = submission(rec("C-107"))
    assistant, _ = scripted_assistant(
        [*partial_vetting_steps(), ai(tool_call(SUBMIT, **lazy))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert [r.clinician_id for r in report.recommendations] == ["C-107"]
    assert [(i.code, i.severity) for i in report.issues] == [("INCOMPLETE_VETTING", "warning")]
