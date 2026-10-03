"""Deterministic fallback used when the AI workflow cannot finish.

It reuses the same eligibility engine and outreach templates, so coordinators still get a
compliant (if less nuanced) shortlist when the LLM is down, misconfigured or misbehaving.
"""

from __future__ import annotations

from shift_assistant.contracts import (
    CandidateRecommendation,
    IssueSeverity,
    ReportStatus,
    RunMode,
    StaffingReport,
    StaffingRequest,
    VerificationIssue,
)
from shift_assistant.domain.models import Shift
from shift_assistant.reliability.reporting import alternates, exclusions, fill_status
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.outreach import unit_label
from shift_assistant.tools.toolkit import StaffingToolkit

FALLBACK_NOTE = (
    "Your experience and credentials match the requirements for this unit, and we would love "
    "to have you on this shift."
)


class DeterministicFallback:
    def __init__(
        self, repository: StaffingRepository, toolkit: StaffingToolkit, max_recommendations: int
    ) -> None:
        self._repository = repository
        self._toolkit = toolkit
        self._max_recommendations = max_recommendations

    def build_report(
        self, request: StaffingRequest, ledger: EvidenceLedger, reason: str
    ) -> StaffingReport:
        issue = VerificationIssue(
            severity=IssueSeverity.WARNING,
            code="FALLBACK_MODE",
            message=f"AI workflow unavailable ({reason}). Results use deterministic rules only.",
        )
        shift = self._resolve_shift(request, ledger)
        if shift is None:
            return StaffingReport(
                request=request,
                status=ReportStatus.FAILED,
                mode=RunMode.FALLBACK,
                summary=(
                    "The AI workflow could not finish and no single shift could be identified. "
                    "Select a specific shift and try again."
                ),
                issues=[issue],
            )

        clinicians = {c.id: c for c in self._repository.candidate_pool(shift)}
        evaluations = [self._toolkit.evaluate(shift, c) for c in clinicians.values()]
        eligible = sorted(
            (e for e in evaluations if e.eligible),
            key=lambda e: (len(e.warnings), -clinicians[e.clinician_id].years_experience),
        )
        shortlist = eligible[: min(shift.positions_open, self._max_recommendations)]
        recommendations = [
            CandidateRecommendation(
                rank=rank,
                clinician_id=e.clinician_id,
                clinician_name=e.clinician_name,
                rationale=(
                    f"Meets every {unit_label(shift.unit)} requirement with "
                    f"{clinicians[e.clinician_id].years_experience} years of experience."
                ),
                warnings=e.warnings,
                outreach=self._toolkit.create_draft(
                    shift, clinicians[e.clinician_id], FALLBACK_NOTE, e
                ),
            )
            for rank, e in enumerate(shortlist, start=1)
        ]
        return StaffingReport(
            request=request,
            status=fill_status(len(recommendations), shift.positions_open),
            mode=RunMode.FALLBACK,
            summary=(
                f"Rule-based shortlist: {len(eligible)} of {len(evaluations)} candidates meet all "
                "requirements, ranked by credential warnings, then experience."
            ),
            shift=self._toolkit.summarize(shift),
            recommendations=recommendations,
            alternates=alternates(evaluations, {r.clinician_id for r in recommendations}),
            excluded=exclusions(evaluations),
            issues=[issue],
        )

    def _resolve_shift(self, request: StaffingRequest, ledger: EvidenceLedger) -> Shift | None:
        """Use the pinned shift, else the agent's lookup if it found exactly one shift."""
        if request.shift_id:
            return self._repository.shift(request.shift_id)
        if len(ledger.shifts) == 1:
            return self._repository.shift(next(iter(ledger.shifts)))
        return None
