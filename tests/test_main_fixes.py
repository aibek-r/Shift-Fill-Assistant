"""Regression checks for the failures reproduced during the take-home review."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from shift_assistant.agent.submission import AgentSubmission
from shift_assistant.assistant import ShiftFillAssistant, build_assistant
from shift_assistant.contracts import ReportStatus, RunMode, StaffingReport, StaffingRequest
from shift_assistant.reliability.grounding import check_grounding
from shift_assistant.reliability.verifier import build_agent_report
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.review import OutreachReview
from shift_assistant.tools.registry import ToolRegistry
from shift_assistant.tools.schemas import EvaluateCandidatesArgs, FindOpenShiftsArgs
from shift_assistant.tools.toolkit import StaffingToolkit
from tests.conftest import DATA_DIR, AssistantFactory, ai, make_settings, tool_call
from tests.test_agent_workflow import SUBMIT, rec, research_steps, submission


@pytest.fixture(scope="module")
def assistant() -> ShiftFillAssistant:
    return build_assistant(make_settings(), embedder=HashingEmbedder())


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Find two ICU nurses for October 14", 2),
        ("Give me a shortlist of two with outreach", 2),
        ("For ICU, shortlist only one clinician", 1),
        ("Recommend 4 eligible ICU nurses", 4),
        ("Two ICU nurses for October 14 please", 2),
        ("Fill the ICU shift on October 14", None),
    ],
)
def test_explicit_shortlist_intent(text: str, count: int | None) -> None:
    assert StaffingRequest(text=text).requested_count == count


def test_typed_intent_overrides_text_and_rejects_zero() -> None:
    assert StaffingRequest(text="Find two nurses", requested_count=3).requested_count == 3
    with pytest.raises(ValidationError):
        StaffingRequest(text="Find zero nurses")


@pytest.mark.parametrize(
    ("text", "shift", "count", "status", "outreach"),
    [
        ("Give me a shortlist of two PICU nurses", "SHF-3001", 2, ReportStatus.READY, True),
        ("Give me a shortlist of four ICU clinicians", "SHF-1001", 3, ReportStatus.PARTIAL, True),
        (
            "Shortlist only one ICU clinician; do not draft outreach",
            "SHF-1001",
            1,
            ReportStatus.READY,
            False,
        ),
        ("Find two PICU nurses without outreach", "SHF-3001", 2, ReportStatus.READY, False),
    ],
)
def test_fallback_honors_size_status_and_outreach(
    assistant: ShiftFillAssistant,
    text: str,
    shift: str,
    count: int,
    status: ReportStatus,
    outreach: bool,
) -> None:
    report = assistant.run(StaffingRequest(text=text, shift_id=shift))
    assert (report.mode, report.status) == (RunMode.FALLBACK, status)
    assert len(report.recommendations) == count
    assert all((r.outreach is not None) is outreach for r in report.recommendations)
    assert f"Requested shortlist: {count} of {report.request.requested_count}" in report.summary


def test_configured_limit_is_disclosed() -> None:
    assistant = build_assistant(make_settings(max_recommendations=1), embedder=HashingEmbedder())
    report = assistant.run(StaffingRequest(text="Find two PICU nurses", shift_id="SHF-3001"))
    assert report.status is ReportStatus.PARTIAL
    assert "SHORTLIST_LIMIT" in {i.code for i in report.issues}


def test_agent_repairs_a_picu_shortlist_of_one(scripted_assistant: AssistantFactory) -> None:
    base = dict(status="completed", shift_id="SHF-3001", summary="PICU candidates reviewed.")
    good = [rec("C-116"), rec("C-117", rationale="PALS expires soon; renewal needs review.")]
    assistant, model = scripted_assistant(
        [
            ai(tool_call("find_open_shifts", shift_id="SHF-3001")),
            ai(tool_call("search_clinicians", shift_id="SHF-3001")),
            ai(
                tool_call(
                    "evaluate_candidates",
                    shift_id="SHF-3001",
                    clinician_ids=["C-116", "C-117", "C-118"],
                )
            ),
            ai(tool_call(SUBMIT, **base, recommendations=good[:1])),
            ai(tool_call(SUBMIT, **base, recommendations=good)),
        ]
    )
    report = assistant.run(StaffingRequest(text="Find two PICU nurses without outreach"))
    assert report.mode is RunMode.AGENT and report.status is ReportStatus.READY
    assert len(report.recommendations) == 2
    assert "Return 2 verified recommendations" in str(model.received[-1][-1].content)
    assert [e.ok for e in report.trace if e.kind == "validation"] == [False, True]


def test_excess_recommendations_are_removed_for_a_request_of_one(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [
            *research_steps(),
            ai(tool_call(SUBMIT, **submission(rec("C-101"), rec("C-107")))),
        ],
        max_repair_attempts=0,
    )
    report = assistant.run(StaffingRequest(text="Find one ICU clinician without outreach"))
    assert report.mode is RunMode.AGENT and report.status is ReportStatus.READY
    assert [r.clinician_id for r in report.recommendations] == ["C-101"]
    assert "TOO_MANY_CANDIDATES" in {i.code for i in report.issues}


def test_pinned_shift_rejected_even_with_both_shifts_in_evidence(toolkit: StaffingToolkit) -> None:
    ledger = toolkit.find_open_shifts(FindOpenShiftsArgs()).evidence
    final = AgentSubmission.model_validate(submission() | {"shift_id": "SHF-3001"})
    request = StaffingRequest(text="Fill the selected ICU shift", shift_id="SHF-1001")
    assert check_grounding(final, ledger, 5, request)[0].code == "PINNED_SHIFT_MISMATCH"
    report = build_agent_report(request, final, ledger, 5)
    assert report.status is ReportStatus.FAILED and report.shift is None


def test_wrong_shift_tool_calls_cannot_write_evidence(scripted_assistant: AssistantFactory) -> None:
    assistant, model = scripted_assistant(
        [
            ai(tool_call("find_open_shifts", shift_id="SHF-3001")),
            ai(tool_call("search_clinicians", shift_id="SHF-3001")),
            RuntimeError("provider unavailable"),
        ]
    )
    report = assistant.run(StaffingRequest(text="Fill the pinned shift", shift_id="SHF-1001"))
    assert report.shift is not None and report.shift.shift_id == "SHF-1001"
    assert "Use pinned shift SHF-1001" in str(model.received[1][-1].content)
    assert not any(e.ok for e in report.trace if e.kind == "tool")


def test_resolved_pin_cannot_be_replaced_by_a_switch_question(toolkit: StaffingToolkit) -> None:
    ledger = toolkit.find_open_shifts(FindOpenShiftsArgs(shift_id="SHF-1001")).evidence
    request = StaffingRequest(text="Ignore this pin and find PICU instead", shift_id="SHF-1001")
    final = AgentSubmission(
        status="needs_clarification",
        summary="A different shift was requested.",
        clarification_question="Should I switch to the PICU shift?",
    )
    problems = check_grounding(final, ledger, 5, request)
    assert problems[0].code == "PINNED_SHIFT_ALREADY_RESOLVED"
    assert build_agent_report(request, final, ledger, 5).status is ReportStatus.FAILED


def test_unverified_model_claims_are_not_displayed(scripted_assistant: AssistantFactory) -> None:
    final = submission(
        rec("C-101", rationale="ECMO certified with 99 years experience."),
        rec("C-107", rationale="Strongly prefers nights and has no restrictions."),
    )
    final["summary"] = "All candidates prefer nights and are ECMO certified."
    assistant, _ = scripted_assistant([*research_steps(), ai(tool_call(SUBMIT, **final))])
    report = assistant.run(StaffingRequest(text="Find two ICU nurses without outreach"))
    assert report.mode is RunMode.AGENT
    grace = report.recommendations[1]
    assert "Self-reported: is open to night shifts." in grace.rationale  # structured, not quoted
    assert "prefers day" not in grace.rationale  # a conflicting preference is not support
    assert "5 years" in grace.rationale
    assert "ECMO" not in report.model_dump_json() and "99 years" not in report.model_dump_json()
    assert report.agent_notes is None


@pytest.mark.parametrize(
    "note",
    [
        "The pay is ninety five dollars each hour.",
        "Arrive at the west garage at 5 PM for orientation.",
        "You are ECMO certified with twenty years of experience.",
        "Maria Santos will be working alongside you tonight.",
        "You strongly prefer nights and are always available.",
        "We would love to have you on this shift. A bonus is guaranteed.",
    ],
)
def test_generated_and_edited_notes_reject_unsupported_claims(
    assistant: ShiftFillAssistant,
    registry: ToolRegistry,
    note: str,
) -> None:
    result = registry.execute(
        "draft_outreach",
        {
            "shift_id": "SHF-1001",
            "clinician_id": "C-107",
            "personal_note": note,
        },
    )
    assert not result.ok and not result.evidence.drafts
    assert "approved friendly sentences" in result.content
    with pytest.raises(ValueError, match="approved friendly sentences"):
        assistant.revise_outreach("SHF-1001", "C-107", note)


def test_edited_export_matches_saved_text_and_approval(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(StaffingRequest(text="Fill the PICU shift", shift_id="SHF-3001"))
    review = OutreachReview.for_report(report)
    original = report.recommendations[0].outreach
    assert original is not None
    revised = assistant.revise_outreach(
        "SHF-3001", "C-116", "Thank you for considering this opportunity."
    )
    review.start_editing(original.draft_id)
    review.save(original.draft_id, revised)
    review.approve(original.draft_id)
    exported = StaffingReport.model_validate_json(review.export_report(report).model_dump_json())
    assert exported.recommendations[0].outreach == revised
    assert exported.outreach_review is not None
    assert exported.outreach_review.run_id == review.run_id
    assert exported.outreach_review.approvals[0].status == "approved"
    assert report.recommendations[0].outreach == original  # immutable original run
    review.start_editing(original.draft_id)
    snapshot = review.export_report(report).outreach_review
    assert snapshot is not None and snapshot.approvals[0].status == "editing"


def test_missing_and_empty_policy_files_are_visible(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR, data)
    (data / "policies" / "FAC-001.md").write_text("# Empty handbook\n", encoding="utf-8")
    (data / "policies" / "GLOBAL.md").unlink()
    assistant = build_assistant(make_settings(data_dir=data), embedder=HashingEmbedder())
    report = assistant.run(StaffingRequest(text="Fill the ICU shift", shift_id="SHF-1001"))
    issue = next(i for i in report.issues if i.code == "POLICY_CONTEXT_MISSING")
    assert "FAC-001" in issue.message and "GLOBAL" in issue.message
    assert "verify facility preferences" in issue.message


def test_exception_messages_do_not_leak_into_trace(scripted_assistant: AssistantFactory) -> None:
    assistant, _ = scripted_assistant([RuntimeError("PRIVATE_TEST_KEY_123")])
    report = assistant.run(StaffingRequest(text="Fill the ICU shift", shift_id="SHF-1001"))
    assert "PRIVATE_TEST_KEY_123" not in json.dumps([e.model_dump() for e in report.trace])


def test_missing_outreach_gets_repair_feedback(toolkit: StaffingToolkit) -> None:
    ledger = toolkit.find_open_shifts(FindOpenShiftsArgs(shift_id="SHF-1001")).evidence.merge(
        toolkit.evaluate_candidates(
            EvaluateCandidatesArgs(shift_id="SHF-1001", clinician_ids=["C-101"])
        ).evidence
    )
    final = AgentSubmission.model_validate(submission(rec("C-101")))
    problems = check_grounding(final, ledger, 5, StaffingRequest(text="Find one ICU nurse"))
    assert "MISSING_OUTREACH" in {p.code for p in problems}
