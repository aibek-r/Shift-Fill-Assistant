"""Deterministic fallback used when the AI workflow cannot finish.

It reuses the same eligibility engine and outreach templates, so coordinators still get a
compliant (if less nuanced) shortlist when the LLM is down, misconfigured or misbehaving.
"""

from __future__ import annotations

from shift_assistant.contracts import (
    CandidateRecommendation,
    IssueSeverity,
    Origin,
    ReportStatus,
    RunMode,
    StaffingReport,
    StaffingRequest,
    VerificationIssue,
)
from shift_assistant.reliability.reporting import (
    alternates,
    candidate_coverage,
    coverage_summary,
    exclusions,
    fill_status,
    rule_ranked,
)
from shift_assistant.reliability.resolution import TodayIn, resolve_shift
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
        today_in: TodayIn,
    ) -> StaffingReport:
        issue = VerificationIssue(
            severity=IssueSeverity.WARNING,
            code="FALLBACK_MODE",
            message=f"AI workflow unavailable ({reason}). Results use deterministic rules only.",
        )
        resolution = resolve_shift(
            request, self._repository, self._toolkit.summarize, ledger, today_in
        )
        if resolution.clarification is not None:
            summary, question = resolution.clarification
            return StaffingReport(
                request=request,
                status=ReportStatus.NEEDS_CLARIFICATION,
                mode=RunMode.FALLBACK,
                summary=summary,
                clarification_question=question,
                issues=[issue],
            )
        shift = resolution.shift
        if shift is None:
            return StaffingReport(
                request=request,
                status=ReportStatus.FAILED,
                mode=RunMode.FALLBACK,
                summary=f"The selected shift {request.shift_id} does not exist.",
                issues=[issue],
            )

        clinicians = {c.id: c for c in self._repository.candidate_pool(shift)}
        evaluations = [self._toolkit.evaluate(shift, c) for c in clinicians.values()]
        target = request.shortlist_target(shift.positions_open)
        shortlist = rule_ranked(evaluations)[: min(target, self._max_recommendations)]
        recommendations = [
            CandidateRecommendation(
                rank=rank,
                clinician_id=e.clinician_id,
                clinician_name=e.clinician_name,
                selected_by=Origin.CODE,
                rationale=candidate_rationale(e),
                warnings=e.warnings,
                credentials=e.credentials,
                outreach=self._toolkit.create_draft(
                    shift, clinicians[e.clinician_id], FALLBACK_NOTE, e
                )
                if request.draft_outreach
                else None,
                outreach_by=Origin.CODE if request.draft_outreach else None,
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
            status=fill_status(
                coverage, recommendations, request, shift.positions_open, self._max_recommendations
            ),
            mode=RunMode.FALLBACK,
            summary=" ".join(
                [
                    *_resolution_note(shift.id, resolution.method, resolution.criteria),
                    coverage_summary(coverage, shift.positions_open, request.requested_count),
                    "Ranked by credential warnings, then experience.",
                ]
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


def _resolution_note(shift_id: str, method: str, criteria: str) -> list[str]:
    if method == "request":
        matched = f" ({criteria})" if criteria else ""
        return [f"{shift_id} was matched to the request by rules{matched}."]
    if method == "agent":
        return [f"{shift_id} is the shift the AI workflow was working on before it stopped."]
    return []
