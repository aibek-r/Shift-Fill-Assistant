"""End-to-end tests of the LangGraph workflow, driven by a scripted chat model."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from shift_assistant.assistant import build_assistant
from shift_assistant.contracts import Origin, ReportStatus, RunMode, StaffingRequest
from shift_assistant.domain.eligibility import CheckCode
from shift_assistant.retrieval.embedder import HashingEmbedder
from tests.conftest import AssistantFactory, ai, make_settings, tool_call

SUBMIT = "submit_recommendation"
REQUEST = StaffingRequest(
    text="Two ICU nurses for the St. Mary's night shift on Oct 14, please.",
    draft_outreach=False,
)
ICU_PROFILE = "FAC-001#icu-unit-profile"
MARIA_DRAFT = "DRAFT-SHF-1001-C-101"
ICU_POOL = ["C-101", "C-102", "C-103", "C-104", "C-105", "C-106", "C-107", "C-108", "C-109"]
DANIEL_RATIONALE = "Eligible ICU nurse; his ACLS expires soon after the shift, so it needs renewal."


def rec(
    clinician_id: str,
    citations: tuple[str, ...] = (),
    draft: str | None = None,
    rationale: str = "Eligible per evaluate_candidates and matches the unit preferences.",
) -> dict[str, Any]:
    return {
        "clinician_id": clinician_id,
        "rationale": rationale,
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


def research_steps(*, outreach: bool = False) -> list[AIMessage]:
    """Typical ReAct steps: resolve the shift, retrieve policy, search and vet the pool, draft."""
    steps = [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(
            tool_call(
                "search_facility_policies", facility_id="FAC-001", query="ICU unit profile", top_k=8
            ),
            tool_call("search_clinicians", shift_id="SHF-1001", query="ICU nights"),
        ),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=ICU_POOL)),
    ]
    if outreach:
        steps.append(
            ai(
                tool_call(
                    "draft_outreach",
                    shift_id="SHF-1001",
                    clinician_id="C-101",
                    personal_note="We would love to have you on this shift.",
                ),
                tool_call(
                    "draft_outreach",
                    shift_id="SHF-1001",
                    clinician_id="C-104",
                    personal_note="Thank you for considering this opportunity.",
                ),
            )
        )
    return steps


def test_happy_path_produces_a_grounded_report(scripted_assistant: AssistantFactory) -> None:
    final = submission(
        rec("C-101", (ICU_PROFILE,), MARIA_DRAFT),
        rec("C-104", draft="DRAFT-SHF-1001-C-104", rationale=DANIEL_RATIONALE),
    )
    assistant, _ = scripted_assistant(
        [*research_steps(outreach=True), ai(tool_call(SUBMIT, **final))]
    )

    report = assistant.run(REQUEST.model_copy(update={"draft_outreach": True}))

    assert (report.mode, report.status) == (RunMode.AGENT, ReportStatus.READY)
    assert [r.clinician_name for r in report.recommendations] == ["Maria Santos", "Daniel Kim"]
    maria, daniel = report.recommendations
    assert [c.chunk_id for c in maria.citations] == [ICU_PROFILE]
    assert maria.outreach is not None and maria.outreach.draft_id == MARIA_DRAFT
    assert [w.code for w in daniel.warnings] == [CheckCode.CREDENTIAL_EXPIRING_SOON]
    assert {e.clinician_id for e in report.excluded} == {
        "C-102",
        "C-103",
        "C-105",
        "C-106",
        "C-108",
        "C-109",
    }
    assert [a.clinician_id for a in report.alternates] == ["C-107"]
    assert report.issues == []
    assert (report.metrics.llm_calls, report.metrics.tool_calls) == (5, 6)


def test_hallucinated_and_ineligible_candidates_are_sent_back_for_repair(
    scripted_assistant: AssistantFactory,
) -> None:
    bad = submission(rec("C-999"), rec("C-102"), rec("C-101"))
    good = submission(rec("C-101"), rec("C-107"))
    assistant, model = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **bad)), ai(tool_call(SUBMIT, **good))]
    )

    report = assistant.run(REQUEST)

    feedback = model.received[-1][-1]
    assert isinstance(feedback, ToolMessage) and feedback.status == "error"
    assert "C-999 was not vetted" in str(feedback.content)
    assert "C-102 is not eligible" in str(feedback.content)
    assert [r.clinician_id for r in report.recommendations] == ["C-101", "C-107"]
    assert [a.clinician_id for a in report.alternates] == ["C-104"]
    assert report.status is ReportStatus.READY
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
    assert [r.clinician_id for r in report.recommendations] == ["C-101", "C-107"]
    maria, grace = report.recommendations
    assert maria.citations == [] and maria.outreach is None
    # The removed pick's slot is refilled by rules, and the addition is labelled as such.
    assert (maria.selected_by, grace.selected_by) == (Origin.MODEL, Origin.CODE)
    assert {i.code for i in report.issues} == {"NOT_VETTED", "UNKNOWN_CITATION", "INVALID_DRAFT"}
    assert report.status is ReportStatus.READY


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
    assert report.clarification_question is not None
    assert "None of the shifts found starts next week (2026-10-05 to 2026-10-11)" in (
        report.clarification_question
    )
    assert "Would you like one of these alternatives" in report.clarification_question
    assert report.recommendations == []
    # The summary is built from find_open_shifts, not from the model's description of it.
    assert report.summary == (
        "None of the shifts found starts next week (2026-10-05 to 2026-10-11). "
        "Alternatives outside that period: Open shifts found: "
        "SHF-1001, ICU night shift at St. Mary's Medical Center, "
        "Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM (America/Chicago); "
        "SHF-1003, ICU day shift at St. Mary's Medical Center, "
        "Fri, Oct 16, 2026, 7:00 AM to Fri, Oct 16, 2026, 7:00 PM (America/Chicago)."
    )
    assert report.agent_notes is None  # unverified model explanations are not published


def test_clarification_without_matching_shifts_says_so(
    scripted_assistant: AssistantFactory,
) -> None:
    unknown = clarification() | {"clarification_question": "Which facility did you mean?"}
    assistant, _ = scripted_assistant(
        [
            ai(tool_call("find_open_shifts", facility="Mercy General")),  # unknown facility
            ai(tool_call(SUBMIT, **unknown)),
        ]
    )

    report = assistant.run(StaffingRequest(text="Find a nurse for Mercy General tomorrow night."))

    assert report.summary == "No open shift matched the request."


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


def test_incomplete_vetting_is_completed_by_code_when_repairs_run_out(
    scripted_assistant: AssistantFactory,
) -> None:
    lazy = submission(rec("C-107"))
    assistant, _ = scripted_assistant(
        [*partial_vetting_steps(), ai(tool_call(SUBMIT, **lazy))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert [r.clinician_id for r in report.recommendations] == ["C-107", "C-101"]
    assert report.completion is not None
    assert report.completion.evaluated_ids == [c for c in ICU_POOL if c != "C-107"]
    assert report.issues == []  # repaired by completion, not left as an active warning
    assert report.coverage is not None and report.coverage.full_pool_evaluated


def vet_one_without_searching() -> list[AIMessage]:
    """A lazy agent: checks one (ineligible) clinician and never searches the pool."""
    return [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=["C-102"])),
    ]


def test_no_eligible_claim_after_partial_vetting_is_sent_back(
    scripted_assistant: AssistantFactory,
) -> None:
    nobody = submission()
    search = ai(tool_call("search_clinicians", shift_id="SHF-1001"))
    vet_all = ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=ICU_POOL))
    assistant, model = scripted_assistant(
        [
            *vet_one_without_searching(),
            ai(tool_call(SUBMIT, **nobody)),
            search,
            vet_all,
            ai(tool_call(SUBMIT, **submission(rec("C-101"), rec("C-107")))),
        ]
    )

    report = assistant.run(REQUEST)

    feedback = model.received[3][-1]
    assert isinstance(feedback, ToolMessage) and "search_clinicians was never called" in str(
        feedback.content
    )
    assert report.status is ReportStatus.READY
    assert report.coverage is not None and report.coverage.full_pool_evaluated


def test_no_eligible_claim_after_partial_vetting_is_completed_by_code(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [*vet_one_without_searching(), ai(tool_call(SUBMIT, **submission()))],
        max_repair_attempts=0,
    )

    report = assistant.run(REQUEST)

    assert report.status is ReportStatus.READY  # three ICU nurses are eligible after all
    assert [(r.clinician_id, r.selected_by) for r in report.recommendations] == [
        ("C-101", Origin.CODE),
        ("C-107", Origin.CODE),
    ]
    assert report.completion is not None and report.completion.pool_determined_by_code
    assert report.issues == []


def test_another_facilitys_policy_cannot_be_cited(scripted_assistant: AssistantFactory) -> None:
    steps = [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(
            tool_call("search_facility_policies", facility_id="FAC-002", query="parking", top_k=8),
            tool_call("search_clinicians", shift_id="SHF-1001"),
        ),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=ICU_POOL)),
    ]
    final = submission(rec("C-101", ("FAC-002#parking",)))
    assistant, _ = scripted_assistant(
        [*steps, ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert report.recommendations[0].citations == []
    assert [i.code for i in report.issues] == ["OTHER_FACILITY_CITATION"]


def test_rationale_must_mention_the_credential_warning(
    scripted_assistant: AssistantFactory,
) -> None:
    silent = submission(rec("C-101"), rec("C-104", rationale="Strong ICU nurse; no warnings."))
    fixed = submission(rec("C-101"), rec("C-104", rationale=DANIEL_RATIONALE))
    research = [step for step in research_steps() if step.tool_calls[0]["name"] != "draft_outreach"]
    assistant, model = scripted_assistant(
        [*research, ai(tool_call(SUBMIT, **silent)), ai(tool_call(SUBMIT, **fixed))]
    )

    report = assistant.run(REQUEST)

    feedback = model.received[-1][-1]
    assert isinstance(feedback, ToolMessage) and "must mention its credential warning" in str(
        feedback.content
    )
    assert "ACLS" in str(feedback.content)
    assert report.issues == []


def test_fallback_uses_the_shift_the_agent_narrowed_down_to(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [
            ai(tool_call("find_open_shifts", facility="St. Mary's", unit="ICU")),  # two shifts
            ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
            ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=["C-101"])),
            RuntimeError("503 Service Unavailable"),
        ]
    )

    report = assistant.run(REQUEST)

    assert (report.mode, report.status) == (RunMode.FALLBACK, ReportStatus.READY)
    assert report.shift is not None and report.shift.shift_id == "SHF-1001"


def test_time_budget_degrades_to_rules(scripted_assistant: AssistantFactory) -> None:
    assistant, model = scripted_assistant([], max_run_seconds=1e-9)

    report = assistant.run(StaffingRequest(text="Fill the ICU night shift", shift_id="SHF-1001"))

    assert model.received == []  # the budget is checked before any LLM call
    assert report.mode is RunMode.FALLBACK
    assert "time budget" in report.issues[0].message
