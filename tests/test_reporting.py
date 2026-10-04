"""Summary consistency: counts come from verified evaluations and always match the report lists."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from shift_assistant.assistant import build_assistant
from shift_assistant.contracts import (
    CandidateCoverage,
    CandidateRecommendation,
    Origin,
    ReportStatus,
    RunMode,
    StaffingReport,
    StaffingRequest,
)
from shift_assistant.reliability.completion import DeterministicCompletion
from shift_assistant.reliability.reporting import coverage_summary, fill_status
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.tools.schemas import OutreachDraft
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

    assert report.summary == FULL_POOL_SUMMARY + " Requested shortlist: 2 of 2 clinicians."
    assert_counts_match_lists(report)
    assert report.coverage is not None and report.coverage.full_pool_evaluated
    assert [a.clinician_id for a in report.alternates] == ["C-104"]
    assert report.agent_notes is None  # false model counts are not published


def test_fallback_summary_uses_the_same_counts() -> None:
    assistant = build_assistant(make_settings(), embedder=HashingEmbedder())

    report = assistant.run(StaffingRequest(text="Fill the ICU night shift", shift_id="SHF-1001"))

    assert report.mode is RunMode.FALLBACK
    assert report.summary.startswith(FULL_POOL_SUMMARY)
    assert_counts_match_lists(report)


def test_summary_does_not_claim_full_coverage_when_the_pool_is_undetermined(
    scripted_assistant: AssistantFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("completion unavailable")

    monkeypatch.setattr(DeterministicCompletion, "complete", broken)
    steps = [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=["C-101", "C-102"])),
    ]
    final = submission(rec("C-101"))
    assistant, _ = scripted_assistant(
        [*steps, ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert report.status is ReportStatus.NEEDS_REVIEW
    assert [i.code for i in report.issues] == ["POOL_NOT_SEARCHED", "COMPLETION_UNRESOLVED"]
    assert "full" not in report.summary
    assert (
        "The shift's candidate pool was not searched, so coverage is unconfirmed." in report.summary
    )
    assert report.coverage is not None and not report.coverage.full_pool_evaluated
    assert [r.clinician_id for r in report.recommendations] == ["C-101"]  # verified pick kept


def test_summary_reports_pool_members_completion_could_not_vet(
    scripted_assistant: AssistantFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(self: object, clinician_id: str) -> None:
        return None  # e.g. a record that disappeared between search and vetting

    monkeypatch.setattr("shift_assistant.repository.StaffingRepository.clinician", unavailable)
    steps = [
        ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
        ai(tool_call("search_clinicians", shift_id="SHF-1001", limit=3)),
    ]
    assistant, _ = scripted_assistant(
        [*steps, ai(tool_call(SUBMIT, **submission()))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert "0 candidates evaluated, covering 0 of 9 in the shift's pool (9 not evaluated)" in (
        report.summary
    )
    assert report.status is ReportStatus.NEEDS_REVIEW  # not no_eligible_candidates
    assert report.coverage is not None and len(report.coverage.unevaluated_ids) == 9
    assert {i.code for i in report.issues} == {"INCOMPLETE_VETTING", "COMPLETION_UNRESOLVED"}


def test_summary_is_rebuilt_after_verification_removes_a_recommendation(
    scripted_assistant: AssistantFactory,
) -> None:
    final = submission(rec("C-999"), rec("C-101"))
    final["summary"] = "Recommended C-999 and Maria Santos."
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert [r.clinician_id for r in report.recommendations] == ["C-101", "C-107"]
    assert report.status is ReportStatus.READY
    assert report.summary.endswith(
        "2 eligible clinicians shortlisted for 2 open positions; "
        "1 eligible alternate was not shortlisted. "
        "Requested shortlist: 2 of 2 clinicians. "
        "Verification removed 1 recommendation that failed evidence checks. "
        "After the model's answer, deterministic rules added 1 recommendation."
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


def _recommendations(count: int, drafted: bool = True) -> list[CandidateRecommendation]:
    return [
        CandidateRecommendation(
            rank=i + 1,
            clinician_id=f"C-{i}",
            clinician_name=f"Clinician {i}",
            selected_by=Origin.MODEL,
            rationale="Passed the recorded compliance checks for this shift.",
            outreach=OutreachDraft(
                draft_id=f"D-{i}",
                shift_id="S",
                clinician_id=f"C-{i}",
                personal_note="n",
                subject="s",
                body="b",
            )
            if drafted
            else None,
        )
        for i in range(count)
    ]


def _coverage(
    pool: int | None, eligible: int, recommended: int, unvetted: int = 0
) -> CandidateCoverage:
    evaluated = (pool or eligible) - unvetted
    return CandidateCoverage(
        pool_size=pool,
        evaluated=evaluated,
        eligible=eligible,
        recommended=recommended,
        alternates=eligible - recommended,
        excluded=evaluated - eligible,
        unevaluated_ids=[f"U-{i}" for i in range(unvetted)],
    )


@pytest.mark.parametrize(
    ("coverage", "recommended", "drafted", "outreach", "status"),
    [
        # Nothing is ruled out until the pool is determined and fully vetted.
        (_coverage(None, 0, 0), 0, True, True, ReportStatus.NEEDS_REVIEW),
        (_coverage(9, 0, 0, unvetted=8), 0, True, True, ReportStatus.NEEDS_REVIEW),
        (_coverage(9, 1, 1, unvetted=8), 1, True, True, ReportStatus.NEEDS_REVIEW),
        (_coverage(3, 0, 0), 0, True, True, ReportStatus.NO_ELIGIBLE_CANDIDATES),
        # Requested outreach must exist for every recommendation.
        (_coverage(9, 3, 2), 2, False, True, ReportStatus.NEEDS_REVIEW),
        (_coverage(9, 3, 2), 2, False, False, ReportStatus.READY),
        # Eligible clinicians left off a short shortlist is unfinished work, not a shortage.
        (_coverage(9, 3, 1), 1, True, True, ReportStatus.NEEDS_REVIEW),
        (_coverage(9, 1, 1), 1, True, True, ReportStatus.PARTIAL),
        (_coverage(9, 3, 2), 2, True, True, ReportStatus.READY),
    ],
)
def test_fill_status_completion_conditions(
    coverage: CandidateCoverage,
    recommended: int,
    drafted: bool,
    outreach: bool,
    status: ReportStatus,
) -> None:
    request = StaffingRequest(text="Find two ICU nurses", draft_outreach=outreach)
    recommendations = _recommendations(recommended, drafted)

    assert fill_status(coverage, recommendations, request, 2, 5) is status


def test_fill_status_treats_the_configured_limit_as_partial() -> None:
    request = StaffingRequest(text="Find three ICU nurses", draft_outreach=False)

    status = fill_status(_coverage(9, 3, 2), _recommendations(2, False), request, 1, 2)

    assert status is ReportStatus.PARTIAL
