"""Deterministic fallback used when the AI workflow cannot finish.

It reuses the same eligibility engine and outreach templates, so coordinators still get a
compliant (if less nuanced) shortlist when the LLM is down, misconfigured or misbehaving.
"""

from __future__ import annotations

import logging

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
    missing_outreach,
    rule_ranked,
)
from shift_assistant.reliability.resolution import TodayIn, resolve_shift
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.facts import candidate_rationale
from shift_assistant.tools.notes import DEFAULT_NOTE
from shift_assistant.tools.schemas import CandidateEvaluation
from shift_assistant.tools.toolkit import StaffingToolkit

logger = logging.getLogger(__name__)

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
        unresolved: list[str] = []  # a failed check or draft is reported, never crashes the run
        evaluations: list[CandidateEvaluation] = []
        for clinician in clinicians.values():
            try:
                evaluations.append(self._toolkit.evaluate(shift, clinician))
            except Exception as exc:
                logger.warning("Fallback could not vet %s (%s)", clinician.id, type(exc).__name__)
                unresolved.append(
                    f"The compliance check for {clinician.id} could not run "
                    f"({type(exc).__name__}). Vet this clinician manually."
                )
        target = request.shortlist_target(shift.positions_open)
        shortlist = rule_ranked(evaluations)[: min(target, self._max_recommendations)]
        recommendations = []
        for rank, e in enumerate(shortlist, start=1):
            draft = None
            if request.draft_outreach:
                try:
                    draft = self._toolkit.create_draft(
                        shift, clinicians[e.clinician_id], FALLBACK_NOTE, e
                    )
                except Exception as exc:
                    logger.warning(
                        "Fallback could not draft for %s (%s)", e.clinician_id, type(exc).__name__
                    )
                    unresolved.append(
                        f"Outreach for {e.clinician_id} could not be drafted "
                        f"({type(exc).__name__}). Write it manually."
                    )
            recommendations.append(
                CandidateRecommendation(
                    rank=rank,
                    clinician_id=e.clinician_id,
                    clinician_name=e.clinician_name,
                    selected_by=Origin.CODE,
                    rationale=candidate_rationale(e),
                    warnings=e.warnings,
                    credentials=e.credentials,
                    outreach=draft,
                    outreach_by=Origin.CODE if draft else None,
                )
            )
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
                    coverage_summary(
                        coverage,
                        shift.positions_open,
                        request.requested_count,
                        missing_outreach(request, recommendations),
                    ),
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
                *(
                    VerificationIssue(
                        severity=IssueSeverity.WARNING,
                        code="COMPLETION_UNRESOLVED",
                        message=message,
                    )
                    for message in unresolved
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
