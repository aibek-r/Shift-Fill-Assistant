"""Turns a validated agent submission into the final report, enforcing grounding.

Division of labour: the model contributes judgement (which candidates, in what order, why).
Every fact in the report (names, warnings, citation text, outreach) comes from the evidence
ledger, which only tools write.
"""

from __future__ import annotations

from collections import defaultdict

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
from shift_assistant.reliability.reporting import alternates, exclusions, fill_status
from shift_assistant.tools.evidence import EvidenceLedger


def build_agent_report(
    request: StaffingRequest,
    submission: AgentSubmission,
    ledger: EvidenceLedger,
    max_recommendations: int,
) -> StaffingReport:
    if submission.status is SubmissionStatus.NEEDS_CLARIFICATION:
        return StaffingReport(
            request=request,
            status=ReportStatus.NEEDS_CLARIFICATION,
            mode=RunMode.AGENT,
            summary=submission.summary,
            clarification_question=submission.clarification_question,
        )

    problems = check_grounding(submission, ledger, max_recommendations)
    shift = ledger.shifts.get(submission.shift_id or "")
    if shift is None or any(p.action is GroundingAction.REJECT_SUBMISSION for p in problems):
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
        if rec.draft_id is not None and GroundingAction.DROP_DRAFT not in actions:
            draft = ledger.drafts.get(rec.draft_id)
        recommendations.append(
            CandidateRecommendation(
                rank=len(recommendations) + 1,
                clinician_id=evaluation.clinician_id,
                clinician_name=evaluation.clinician_name,
                rationale=rec.rationale,
                warnings=evaluation.warnings,
                citations=[
                    ledger.policy_excerpts[c]
                    for c in dict.fromkeys(rec.citation_ids)
                    if c not in dropped_citations
                ],
                outreach=draft,
            )
        )

    return StaffingReport(
        request=request,
        status=fill_status(len(recommendations), shift.positions_open),
        mode=RunMode.AGENT,
        summary=submission.summary,
        shift=shift,
        recommendations=recommendations,
        alternates=alternates(evaluations, {r.clinician_id for r in recommendations}),
        excluded=exclusions(evaluations),
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
