"""Report-building helpers shared by the agent verifier and the deterministic fallback.

Counts and the summary are computed here from verified evaluations, so they always agree with
the recommendations, alternates and exclusions in the same report.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

from shift_assistant.contracts import (
    AlternateCandidate,
    CandidateCoverage,
    CandidateRecommendation,
    ExcludedCandidate,
    ReportStatus,
)
from shift_assistant.tools.schemas import CandidateEvaluation


def fill_status(recommended: int, eligible: int, positions_open: int) -> ReportStatus:
    if eligible == 0:
        return ReportStatus.NO_ELIGIBLE_CANDIDATES
    if recommended < positions_open:
        return ReportStatus.PARTIAL
    return ReportStatus.READY


def exclusions(evaluations: Iterable[CandidateEvaluation]) -> list[ExcludedCandidate]:
    return [
        ExcludedCandidate(
            clinician_id=e.clinician_id,
            clinician_name=e.clinician_name,
            reasons=e.blockers,
            credentials=e.credentials,
        )
        for e in evaluations
        if not e.eligible
    ]


def alternates(
    evaluations: Iterable[CandidateEvaluation], recommended_ids: Collection[str]
) -> list[AlternateCandidate]:
    return [
        AlternateCandidate(
            clinician_id=e.clinician_id,
            clinician_name=e.clinician_name,
            warnings=e.warnings,
            credentials=e.credentials,
        )
        for e in evaluations
        if e.eligible and e.clinician_id not in recommended_ids
    ]


def candidate_coverage(
    recommendations: Sequence[CandidateRecommendation],
    alternates: Sequence[AlternateCandidate],
    excluded: Sequence[ExcludedCandidate],
    pool_ids: Sequence[str] | None,
    removed_by_verification: int = 0,
) -> CandidateCoverage:
    evaluated_ids = {
        c.clinician_id for group in (recommendations, alternates, excluded) for c in group
    }
    return CandidateCoverage(
        pool_size=None if pool_ids is None else len(pool_ids),
        evaluated=len(evaluated_ids),
        eligible=len(recommendations) + len(alternates),
        recommended=len(recommendations),
        alternates=len(alternates),
        excluded=len(excluded),
        unevaluated_ids=[cid for cid in pool_ids or [] if cid not in evaluated_ids],
        removed_by_verification=removed_by_verification,
    )


def coverage_summary(coverage: CandidateCoverage, positions_open: int) -> str:
    sentences = [_vetting_sentence(coverage), _shortlist_sentence(coverage, positions_open)]
    if coverage.removed_by_verification:
        removed = plural(coverage.removed_by_verification, "recommendation")
        sentences.append(f"Verification removed {removed} that failed evidence checks.")
    return " ".join(sentences)


def shortlist_phrase(recommended: int, positions_open: int) -> str:
    """E.g. '2 eligible clinicians shortlisted for 2 open positions'. Nobody is booked yet."""
    return (
        f"{plural(recommended, 'eligible clinician')} shortlisted for "
        f"{plural(positions_open, 'open position')}"
    )


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _vetting_sentence(coverage: CandidateCoverage) -> str:
    if coverage.pool_size == 0 and coverage.evaluated == 0:
        return "No clinicians match this shift's role and specialty."
    evaluated = plural(coverage.evaluated, "candidate")
    counts = f"{coverage.eligible} eligible, {coverage.excluded} excluded"
    if coverage.pool_size is None:
        return (
            f"{evaluated} evaluated: {counts}. The shift's candidate pool was not searched, "
            "so coverage is unconfirmed."
        )
    if coverage.unevaluated_ids:
        missing = len(coverage.unevaluated_ids)
        checked = coverage.pool_size - missing
        return (
            f"{evaluated} evaluated, covering {checked} of {coverage.pool_size} in the shift's "
            f"pool ({missing} not evaluated): {counts}."
        )
    return f"{evaluated} evaluated, covering the shift's full candidate pool: {counts}."


def _shortlist_sentence(coverage: CandidateCoverage, positions_open: int) -> str:
    if coverage.eligible == 0:
        return "Nobody is eligible, so no one was shortlisted."
    sentence = shortlist_phrase(coverage.recommended, positions_open)
    if (open_gap := positions_open - coverage.recommended) > 0:
        sentence += f"; {plural(open_gap, 'position')} still without a candidate"
    if coverage.alternates:
        verb = "was" if coverage.alternates == 1 else "were"
        alternates = plural(coverage.alternates, "eligible alternate")
        sentence += f"; {alternates} {verb} not shortlisted"
    return sentence + "."
