"""Summary consistency: counts come from verified evaluations and always match the report lists."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from shift_assistant.assistant import build_assistant
from shift_assistant.contracts import (
    CandidateCoverage,
    ReportStatus,
    RunMode,
    StaffingReport,
    StaffingRequest,
)
from shift_assistant.reliability.reporting import coverage_summary, fill_status
from shift_assistant.retrieval.embedder import HashingEmbedder
from tests.conftest import AssistantFactory, ai, make_settings, tool_call
from tests.test_agent_workflow import ICU_POOL, REQUEST, SUBMIT, rec, research_steps, submission

FULL_POOL_SUMMARY = (
    "9 candidates evaluated, covering the shift's full candidate pool: 3 eligible, 6 excluded. "
    "2 eligible clinicians shortlisted for 2 open positions; "
    "1 eligible alternate was not shortlisted."
)


def full_pool_steps() -> list[AIMessage]:
    return [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(tool_call("search_clinicians", shift_id="SHF-1001", query="ICU nights")),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=ICU_POOL)),
    ]


def assert_counts_match_lists(report: StaffingReport) -> None:
    coverage = report.coverage
    assert coverage is not None
    assert coverage.recommended == len(report.recommendations)
    assert coverage.alternates == len(report.alternates)
    assert coverage.excluded == len(report.excluded)
    assert coverage.eligible == coverage.recommended + coverage.alternates
    assert coverage.evaluated == coverage.eligible + coverage.excluded


def test_agent_summary_counts_come_from_verified_evaluations(
    scripted_assistant: AssistantFactory,
) -> None:
    final = submission(rec("C-101"), rec("C-107"))
    final["summary"] = "Only two clinicians were eligible."  # contradicts the evidence
    assistant, _ = scripted_assistant([*full_pool_steps(), ai(tool_call(SUBMIT, **final))])

    report = assistant.run(REQUEST)

    assert report.summary == FULL_POOL_SUMMARY
    assert_counts_match_lists(report)
    assert report.coverage is not None and report.coverage.full_pool_evaluated
    assert [a.clinician_id for a in report.alternates] == ["C-104"]
    assert report.agent_notes == "Only two clinicians were eligible."  # kept apart, labelled


def test_fallback_summary_uses_the_same_counts() -> None:
    assistant = build_assistant(make_settings(), embedder=HashingEmbedder())

    report = assistant.run(StaffingRequest(text="Fill the ICU night shift", shift_id="SHF-1001"))

    assert report.mode is RunMode.FALLBACK
    assert report.summary.startswith(FULL_POOL_SUMMARY)
    assert_counts_match_lists(report)


def test_summary_does_not_claim_full_coverage_when_the_pool_was_never_searched(
    scripted_assistant: AssistantFactory,
) -> None:
    steps = [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=["C-101", "C-102"])),
    ]
    final = submission(rec("C-101"))
    assistant, _ = scripted_assistant(
        [*steps, ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert [i.code for i in report.issues] == ["POOL_NOT_SEARCHED"]
    assert "full" not in report.summary
    assert (
        "The shift's candidate pool was not searched, so coverage is unconfirmed." in report.summary
    )
    assert report.coverage is not None and not report.coverage.full_pool_evaluated


def test_summary_reports_unevaluated_pool_members(scripted_assistant: AssistantFactory) -> None:
    steps = [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(tool_call("search_clinicians", shift_id="SHF-1001", limit=3)),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=["C-101"])),
    ]
    final = submission(rec("C-101"))
    assistant, _ = scripted_assistant(
        [*steps, ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert "1 candidate evaluated, covering 1 of 9 in the shift's pool (8 not evaluated)" in (
        report.summary
    )
    assert report.coverage is not None and len(report.coverage.unevaluated_ids) == 8
    assert [i.code for i in report.issues] == ["INCOMPLETE_VETTING"]  # beyond the search limit


def test_summary_is_rebuilt_after_verification_removes_a_recommendation(
    scripted_assistant: AssistantFactory,
) -> None:
    final = submission(rec("C-999"), rec("C-101"))
    final["summary"] = "Recommended C-999 and Maria Santos."
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert [r.clinician_id for r in report.recommendations] == ["C-101"]
    assert report.status is ReportStatus.PARTIAL
    assert report.summary.endswith(
        "1 eligible clinician shortlisted for 2 open positions; 1 position still without a "
        "candidate; 2 eligible alternates were not shortlisted. "
        "Verification removed 1 recommendation that failed evidence checks."
    )
    assert report.agent_notes is None  # described a shortlist that no longer exists
    assert_counts_match_lists(report)


@pytest.mark.parametrize(
    ("coverage", "positions", "expected"),
    [
        (
            CandidateCoverage(pool_size=1, evaluated=1, eligible=1, recommended=1),
            1,
            "1 candidate evaluated, covering the shift's full candidate pool: 1 eligible, "
            "0 excluded. 1 eligible clinician shortlisted for 1 open position.",
        ),
        (
            CandidateCoverage(pool_size=3, evaluated=3, excluded=3),
            1,
            "3 candidates evaluated, covering the shift's full candidate pool: 0 eligible, "
            "3 excluded. Nobody is eligible, so no one was shortlisted.",
        ),
        (
            CandidateCoverage(pool_size=9, evaluated=1, excluded=1, unevaluated_ids=["C-1"] * 8),
            2,
            "1 candidate evaluated, covering 1 of 9 in the shift's pool (8 not evaluated): "
            "0 eligible, 1 excluded. "
            "No evaluated candidate is eligible, so no one was shortlisted.",
        ),
        (
            CandidateCoverage(pool_size=0),
            2,
            "No clinicians match this shift's role and specialty. "
            "Nobody is eligible, so no one was shortlisted.",
        ),
        (
            CandidateCoverage(pool_size=4, evaluated=4, eligible=3, alternates=3, excluded=1),
            2,
            "4 candidates evaluated, covering the shift's full candidate pool: 3 eligible, "
            "1 excluded. 0 eligible clinicians shortlisted for 2 open positions; 2 positions "
            "still without a candidate; 3 eligible alternates were not shortlisted.",
        ),
    ],
)
def test_summary_wording(coverage: CandidateCoverage, positions: int, expected: str) -> None:
    assert coverage_summary(coverage, positions) == expected


def test_fill_status_distinguishes_no_shortlist_from_nobody_eligible() -> None:
    assert fill_status(recommended=0, eligible=0, positions_open=2) is (
        ReportStatus.NO_ELIGIBLE_CANDIDATES
    )
    assert fill_status(recommended=0, eligible=3, positions_open=2) is ReportStatus.PARTIAL
    assert fill_status(recommended=2, eligible=3, positions_open=2) is ReportStatus.READY
