"""Report-building helpers shared by the agent verifier and the deterministic fallback.

Counts and the summary are computed here from verified evaluations, so they always agree with
the recommendations, alternates and exclusions in the same report.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from datetime import date

from shift_assistant.contracts import (
    AlternateCandidate,
    CandidateCoverage,
    CandidateRecommendation,
    CompletionRecord,
    ExcludedCandidate,
    ReportStatus,
    StaffingRequest,
)
from shift_assistant.intent import relative_date_window
from shift_assistant.tools.outreach import format_local_datetime, unit_label
from shift_assistant.tools.schemas import CandidateEvaluation, ShiftSummary


def fill_status(
    coverage: CandidateCoverage,
    recommendations: Sequence[CandidateRecommendation],
    request: StaffingRequest,
    positions_open: int,
    max_recommendations: int,
) -> ReportStatus:
    """Completion conditions shared by agent and fallback reports.

    Nothing is ruled out until the shift's whole candidate pool is known and vetted, so
    `no_eligible_candidates` and `partial` require full coverage. `ready` also needs the
    requested shortlist and, when requested, a verified draft for every recommendation.
    """
    if not coverage.full_pool_evaluated:
        return ReportStatus.NEEDS_REVIEW  # pool unknown or members unvetted
    if coverage.eligible == 0:
        return ReportStatus.NO_ELIGIBLE_CANDIDATES
    if missing_outreach(request, recommendations):
        return ReportStatus.NEEDS_REVIEW
    target = request.shortlist_target(positions_open)
    if len(recommendations) < min(target, coverage.eligible, max_recommendations):
        return ReportStatus.NEEDS_REVIEW  # eligible clinicians left off a short shortlist
    if len(recommendations) < target:
        return ReportStatus.PARTIAL  # a genuine shortage, or the configured limit
    return ReportStatus.READY


def missing_outreach(
    request: StaffingRequest, recommendations: Sequence[CandidateRecommendation]
) -> int:
    if not request.draft_outreach:
        return 0
    return sum(r.outreach is None for r in recommendations)


_FIT_ORDER = {"prefers_day": 0, "prefers_night": 0, "open_to_day": 1, "open_to_night": 1}


def rule_ranked(evaluations: Iterable[CandidateEvaluation]) -> list[CandidateEvaluation]:
    """Eligible clinicians in the fallback's order: fewest credential warnings, then experience.

    A recorded preference for the shift's period, then openness to it, only breaks ties left by
    those two. The sort is stable, so remaining ties keep the caller's (candidate pool) order.
    """
    return sorted(
        (e for e in evaluations if e.eligible),
        key=lambda e: (
            len(e.warnings),
            -(e.years_experience or 0),
            _FIT_ORDER.get(e.period_fit or "", 2),
        ),
    )


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


def coverage_summary(
    coverage: CandidateCoverage,
    positions_open: int,
    requested_count: int | None = None,
    missing_drafts: int = 0,
) -> str:
    sentences = [_vetting_sentence(coverage), _shortlist_sentence(coverage, positions_open)]
    if requested_count is not None:
        gap = max(0, requested_count - coverage.recommended)
        target = f"Requested shortlist: {coverage.recommended} of {requested_count} clinicians"
        if gap:
            target += f"; {gap} fewer than requested"
        sentences.append(target + ".")
    if missing_drafts:
        sentences.append(
            f"Requested outreach is missing for {plural(missing_drafts, 'recommendation')}."
        )
    if coverage.removed_by_verification:
        removed = plural(coverage.removed_by_verification, "recommendation")
        sentences.append(f"Verification removed {removed} that failed evidence checks.")
    return " ".join(sentences)


def completion_summary(record: CompletionRecord) -> str:
    """One sentence on the work code completed after the model's answer."""
    parts = []
    if record.pool_determined_by_code:
        parts.append("determined the candidate pool")
    if record.evaluated_ids:
        parts.append(f"vetted {plural(len(record.evaluated_ids), 'remaining pool clinician')}")
    if record.selected_ids:
        parts.append(f"added {plural(len(record.selected_ids), 'recommendation')}")
    if record.drafted_ids:
        parts.append(f"drafted {plural(len(record.drafted_ids), 'template outreach message')}")
    if not parts:
        return ""
    listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    return f"After the model's answer, deterministic rules {listed}."


def clarification_summary(shifts: Sequence[ShiftSummary], question: str) -> str:
    """What find_open_shifts returned, with exact dates, for a report that asks a question.

    Lists the shifts the question names, or every shift found if it names none.
    """
    if not shifts:
        return "No open shift matched the request."
    named = [s for s in shifts if s.shift_id in question] or list(shifts)
    listed = "; ".join(
        f"{s.shift_id}, {unit_label(s.unit)} {s.period} shift at {s.facility_name}, "
        f"{format_local_datetime(s.start)} to {format_local_datetime(s.end)} ({s.timezone})"
        for s in sorted(named, key=lambda s: s.start)
    )
    return f"Open shifts found: {listed}."


def relative_date_clarification(
    request: StaffingRequest, shifts: Sequence[ShiftSummary], today: date
) -> tuple[str, str] | None:
    """Render relative-date options from evidence instead of trusting the model's question."""
    window = relative_date_window(request.text, today)
    if request.shift_id or window is None or not shifts:
        return None
    matching = [s for s in shifts if window.contains(s.start.date())]
    if matching:
        summary = f"Shifts found for {window.label}. {clarification_summary(matching, '')}"
        question = f"{summary} Which shift should I staff?"
    else:
        summary = (
            f"None of the shifts found starts {window.label}. "
            f"Alternatives outside that period: {clarification_summary(shifts, '')}"
        )
        question = (
            f"{summary} Would you like one of these alternatives, or a shift within "
            "the requested dates?"
        )
    return summary, question


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
        if not coverage.full_pool_evaluated:  # unchecked clinicians may still qualify
            return "No evaluated candidate is eligible, so no one was shortlisted."
        return "Nobody is eligible, so no one was shortlisted."
    sentence = shortlist_phrase(coverage.recommended, positions_open)
    if (open_gap := positions_open - coverage.recommended) > 0:
        sentence += f"; {plural(open_gap, 'position')} still without a candidate"
    if coverage.alternates:
        verb = "was" if coverage.alternates == 1 else "were"
        alternates = plural(coverage.alternates, "eligible alternate")
        sentence += f"; {alternates} {verb} not shortlisted"
    return sentence + "."
