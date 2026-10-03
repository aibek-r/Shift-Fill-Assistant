"""Hallucination guard: every reference in the agent's answer must exist in this run's evidence.

The same check runs twice. During validation its messages go back to the model so it can repair
the answer. During verification its actions are enforced, so ungrounded content never reaches a
coordinator even if the model ran out of repair attempts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shift_assistant.agent.submission import AgentSubmission, SubmissionStatus
from shift_assistant.tools.evidence import EvidenceLedger


class GroundingAction(StrEnum):
    REJECT_SUBMISSION = "reject_submission"
    DROP_RECOMMENDATION = "drop_recommendation"
    DROP_CITATION = "drop_citation"
    DROP_DRAFT = "drop_draft"
    FLAG = "flag"  # nothing to remove; report it so the coordinator knows


@dataclass(frozen=True)
class GroundingProblem:
    code: str
    message: str
    action: GroundingAction
    index: int | None = None  # position in submission.recommendations
    citation_id: str | None = None


def check_grounding(
    submission: AgentSubmission, ledger: EvidenceLedger, max_recommendations: int
) -> list[GroundingProblem]:
    if submission.status is SubmissionStatus.NEEDS_CLARIFICATION:
        return []
    shift_id = submission.shift_id or ""
    if shift_id not in ledger.shifts:
        return [
            GroundingProblem(
                code="UNKNOWN_SHIFT",
                message=f"Shift '{shift_id}' was not returned by find_open_shifts in this session.",
                action=GroundingAction.REJECT_SUBMISSION,
            )
        ]

    problems: list[GroundingProblem] = []
    if unvetted := ledger.unvetted_candidates(shift_id):
        problems.append(
            GroundingProblem(
                code="INCOMPLETE_VETTING",
                message=(
                    f"search_clinicians returned {', '.join(unvetted)} for {shift_id}, but they "
                    "were never vetted, so the shortlist may miss better candidates. Vet them "
                    "with evaluate_candidates, then submit again."
                ),
                action=GroundingAction.FLAG,
            )
        )
    seen: set[str] = set()
    for index, rec in enumerate(submission.recommendations):
        cid = rec.clinician_id
        evaluation = ledger.evaluation(shift_id, cid)
        if cid in seen:
            problems.append(_drop(index, "DUPLICATE_CANDIDATE", f"{cid} is recommended twice."))
            continue
        seen.add(cid)
        if index >= max_recommendations:
            problems.append(
                _drop(index, "TOO_MANY_CANDIDATES", f"At most {max_recommendations} allowed.")
            )
            continue
        if evaluation is None:
            problems.append(
                _drop(
                    index,
                    "NOT_VETTED",
                    f"{cid} was not vetted with evaluate_candidates for {shift_id}. "
                    "Vet the clinician or remove the recommendation.",
                )
            )
            continue
        if not evaluation.eligible:
            reasons = "; ".join(b.message for b in evaluation.blockers)
            problems.append(_drop(index, "INELIGIBLE", f"{cid} is not eligible: {reasons}"))
            continue

        problems.extend(
            GroundingProblem(
                code="UNKNOWN_CITATION",
                message=f"Citation '{chunk_id}' was not returned by search_facility_policies.",
                action=GroundingAction.DROP_CITATION,
                index=index,
                citation_id=chunk_id,
            )
            for chunk_id in rec.citation_ids
            if chunk_id not in ledger.policy_excerpts
        )
        if rec.draft_id is not None:
            draft = ledger.drafts.get(rec.draft_id)
            if draft is None or draft.clinician_id != cid or draft.shift_id != shift_id:
                problems.append(
                    GroundingProblem(
                        code="INVALID_DRAFT",
                        message=f"Draft '{rec.draft_id}' does not exist for {cid} on {shift_id}.",
                        action=GroundingAction.DROP_DRAFT,
                        index=index,
                    )
                )
    return problems


def _drop(index: int, code: str, message: str) -> GroundingProblem:
    return GroundingProblem(code, message, GroundingAction.DROP_RECOMMENDATION, index)
