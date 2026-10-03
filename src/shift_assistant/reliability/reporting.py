"""Report-building helpers shared by the agent verifier and the deterministic fallback."""

from __future__ import annotations

from collections.abc import Collection, Iterable

from shift_assistant.contracts import AlternateCandidate, ExcludedCandidate, ReportStatus
from shift_assistant.tools.schemas import CandidateEvaluation


def fill_status(recommended: int, positions_open: int) -> ReportStatus:
    if recommended == 0:
        return ReportStatus.NO_ELIGIBLE_CANDIDATES
    if recommended < positions_open:
        return ReportStatus.PARTIAL
    return ReportStatus.READY


def exclusions(evaluations: Iterable[CandidateEvaluation]) -> list[ExcludedCandidate]:
    return [
        ExcludedCandidate(
            clinician_id=e.clinician_id, clinician_name=e.clinician_name, reasons=e.blockers
        )
        for e in evaluations
        if not e.eligible
    ]


def alternates(
    evaluations: Iterable[CandidateEvaluation], recommended_ids: Collection[str]
) -> list[AlternateCandidate]:
    return [
        AlternateCandidate(
            clinician_id=e.clinician_id, clinician_name=e.clinician_name, warnings=e.warnings
        )
        for e in evaluations
        if e.eligible and e.clinician_id not in recommended_ids
    ]
