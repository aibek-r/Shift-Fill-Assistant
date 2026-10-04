"""Turns a validated agent submission into the final report, enforcing grounding.

The model chooses candidates and their order. Candidate explanations are rendered from recorded
facts; arbitrary model rationales and summary notes are never promoted to report evidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from shift_assistant.agent.submission import AgentSubmission, SubmissionStatus
from shift_assistant.contracts import (
    CandidateRecommendation,
    IssueSeverity,
    ReportStatus,
    RunMode,
    StaffingReport,
    StaffingRequest,
    VerificationIssue,
)
from shift_assistant.reliability.grounding import (
    GroundingAction,
    GroundingProblem,
    check_grounding,
)
from shift_assistant.reliability.reporting import (
    alternates,
    candidate_coverage,
    clarification_summary,
    coverage_summary,
    exclusions,
    fill_status,
    relative_date_clarification,
)
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.facts import candidate_rationale


def build_agent_report(
    request: StaffingRequest,
    submission: AgentSubmission,
    ledger: EvidenceLedger,
    max_recommendations: int,
    today: date | None = None,
) -> StaffingReport:
    problems = check_grounding(submission, ledger, max_recommendations, request, today)
    if any(p.action is GroundingAction.REJECT_SUBMISSION for p in problems):
        return StaffingReport(
            request=request,
            status=ReportStatus.FAILED,
            mode=RunMode.AGENT,
            summary="The agent's answer could not be verified against the requested shift.",
            issues=[_issue(p) for p in problems],
        )
    if submission.status is SubmissionStatus.NEEDS_CLARIFICATION:
        question = submission.clarification_question or ""
        summary = clarification_summary(list(ledger.shifts.values()), question)
        if today is not None and (
            grounded := relative_date_clarification(request, list(ledger.shifts.values()), today)
        ):
            summary, question = grounded
        return StaffingReport(
            request=request,
            status=ReportStatus.NEEDS_CLARIFICATION,
            mode=RunMode.AGENT,
            summary=summary,
            clarification_question=question,
        )

    shift = ledger.shifts.get(submission.shift_id or "")
    if shift is None:
        return StaffingReport(
            request=request,
            status=ReportStatus.FAILED,
            mode=RunMode.AGENT,
            summary="The agent's answer referenced a shift that could not be verified.",
            issues=[_issue(p) for p in problems],
        )

    by_index: defaultdict[int | None, list[GroundingProblem]] = defaultdict(list)
    for problem in problems:
        by_index[problem.index].append(problem)

    evaluations = ledger.evaluations_for(shift.shift_id)
    recommendations: list[CandidateRecommendation] = []
    for index, rec in enumerate(submission.recommendations):
        actions = {p.action for p in by_index[index]}
        evaluation = ledger.evaluation(shift.shift_id, rec.clinician_id)
        if GroundingAction.DROP_RECOMMENDATION in actions or evaluation is None:
            continue
        dropped_citations = {p.citation_id for p in by_index[index]}
        draft = None
        if (
            request.draft_outreach
            and rec.draft_id is not None
            and GroundingAction.DROP_DRAFT not in actions
        ):
            draft = ledger.drafts.get(rec.draft_id)
        recommendations.append(
            CandidateRecommendation(
                rank=len(recommendations) + 1,
                clinician_id=evaluation.clinician_id,
                clinician_name=evaluation.clinician_name,
                rationale=candidate_rationale(evaluation),
                warnings=evaluation.warnings,
                credentials=evaluation.credentials,
                citations=[
                    ledger.policy_excerpts[c]
                    for c in dict.fromkeys(rec.citation_ids)
                    if c not in dropped_citations
                ],
                outreach=draft,
            )
        )

    eligible_alternates = alternates(evaluations, {r.clinician_id for r in recommendations})
    excluded = exclusions(evaluations)
    removed = len(submission.recommendations) - len(recommendations)
    coverage = candidate_coverage(
        recommendations,
        eligible_alternates,
        excluded,
        ledger.candidate_pools.get(shift.shift_id),
        removed_by_verification=removed,
    )
    return StaffingReport(
        request=request,
        status=fill_status(
            len(recommendations), coverage.eligible, request.shortlist_target(shift.positions_open)
        ),
        mode=RunMode.AGENT,
        summary=coverage_summary(coverage, shift.positions_open, request.requested_count),
        # Model prose may contain unsupported claims even when every reference is valid.
        agent_notes=None,
        shift=shift,
        recommendations=recommendations,
        alternates=eligible_alternates,
        excluded=excluded,
        coverage=coverage,
        issues=[_issue(p) for p in problems],
    )


def _issue(problem: GroundingProblem) -> VerificationIssue:
    if problem.action is GroundingAction.FLAG:
        return VerificationIssue(
            severity=IssueSeverity.WARNING, code=problem.code, message=problem.message
        )
    removes_candidate = problem.action in {
        GroundingAction.REJECT_SUBMISSION,
        GroundingAction.DROP_RECOMMENDATION,
    }
    return VerificationIssue(
        severity=IssueSeverity.ERROR if removes_candidate else IssueSeverity.WARNING,
        code=problem.code,
        message=f"Removed from the answer: {problem.message}",
    )
