"""Deterministic fallback used when the AI workflow cannot finish.

It reuses the same eligibility engine and outreach templates, so coordinators still get a
compliant (if less nuanced) shortlist when the LLM is down, misconfigured or misbehaving.
"""

from __future__ import annotations

from datetime import date

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
from shift_assistant.intent import relative_date_window
from shift_assistant.reliability.reporting import (
    alternates,
    candidate_coverage,
    coverage_summary,
    exclusions,
    fill_status,
    relative_date_clarification,
)
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.facts import DEFAULT_NOTE, candidate_rationale
from shift_assistant.tools.toolkit import StaffingToolkit

FALLBACK_NOTE = DEFAULT_NOTE


class DeterministicFallback:
    def __init__(
        self, repository: StaffingRepository, toolkit: StaffingToolkit, max_recommendations: int
    ) -> None:
        self._repository = repository
        self._toolkit = toolkit
        self._max_recommendations = max_recommendations

    def build_report(
        self,
        request: StaffingRequest,
        ledger: EvidenceLedger,
        reason: str,
        today: date | None = None,
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

        window = relative_date_window(request.text, today) if today is not None else None
        if not request.shift_id and window is not None and not window.contains(shift.start.date()):
            assert today is not None
            clarification = relative_date_clarification(
                request, [self._toolkit.summarize(shift)], today
            )
            assert clarification is not None
            summary, question = clarification
            return StaffingReport(
                request=request,
                status=ReportStatus.NEEDS_CLARIFICATION,
                mode=RunMode.FALLBACK,
                summary=summary,
                clarification_question=question,
                issues=[issue],
            )

        clinicians = {c.id: c for c in self._repository.candidate_pool(shift)}
        evaluations = [self._toolkit.evaluate(shift, c) for c in clinicians.values()]
        eligible = sorted(
            (e for e in evaluations if e.eligible),
            key=lambda e: (len(e.warnings), -clinicians[e.clinician_id].years_experience),
        )
        target = request.shortlist_target(shift.positions_open)
        shortlist = eligible[: min(target, self._max_recommendations)]
        recommendations = [
            CandidateRecommendation(
                rank=rank,
                clinician_id=e.clinician_id,
                clinician_name=e.clinician_name,
                rationale=candidate_rationale(e),
                warnings=e.warnings,
                credentials=e.credentials,
                outreach=self._toolkit.create_draft(
                    shift, clinicians[e.clinician_id], FALLBACK_NOTE, e
                )
                if request.draft_outreach
                else None,
            )
            for rank, e in enumerate(shortlist, start=1)
        ]
        eligible_alternates = alternates(evaluations, {r.clinician_id for r in recommendations})
        excluded = exclusions(evaluations)
        coverage = candidate_coverage(
            recommendations, eligible_alternates, excluded, pool_ids=list(clinicians)
        )
        return StaffingReport(
            request=request,
            status=fill_status(len(recommendations), len(eligible), target),
            mode=RunMode.FALLBACK,
            summary=(
                f"{coverage_summary(coverage, shift.positions_open, request.requested_count)} "
                "Ranked by credential warnings, then experience."
            ),
            shift=self._toolkit.summarize(shift),
            recommendations=recommendations,
            alternates=eligible_alternates,
            excluded=excluded,
            coverage=coverage,
            issues=[
                issue,
                *(
                    [
                        VerificationIssue(
                            severity=IssueSeverity.WARNING,
                            code="SHORTLIST_LIMIT",
                            message=(
                                f"Requested {target}; configured limit is "
                                f"{self._max_recommendations}."
                            ),
                        )
                    ]
                    if target > self._max_recommendations
                    else []
                ),
            ],
        )

    def _resolve_shift(self, request: StaffingRequest, ledger: EvidenceLedger) -> Shift | None:
        """Use the selected shift, else the one the agent worked on, else the one it found.

        "Worked on" means it searched or vetted candidates for a shift that find_open_shifts
        returned, which survives the agent first finding several shifts and then narrowing down.
        """
        if request.shift_id:
            return self._repository.shift(request.shift_id)
        worked_on = {e.shift_id for e in ledger.evaluations.values()} | set(
            ledger.searched_candidates
        )
        candidates = (worked_on & set(ledger.shifts)) or set(ledger.shifts)
        if len(candidates) == 1:
            return self._repository.shift(next(iter(candidates)))
        return None
