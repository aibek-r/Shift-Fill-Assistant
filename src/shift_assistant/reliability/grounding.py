"""Hallucination guard: every reference in the agent's answer must exist in this run's evidence.

The same check runs twice. During validation its messages go back to the model so it can repair
the answer. During verification its actions are enforced, so ungrounded content never reaches a
coordinator even if the model ran out of repair attempts.

It verifies references (shift, clinicians, citations, drafts), eligibility and vetting coverage.
Free-text explanations are not fact-checked; the one text check is that every credential warning
is mentioned in the rationale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from shift_assistant.agent.submission import AgentSubmission, RecommendedCandidate, SubmissionStatus
from shift_assistant.domain.models import CredentialType
from shift_assistant.retrieval.knowledge import GLOBAL_SCOPE
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.schemas import CandidateEvaluation

_NO_WARNINGS_CLAIM = re.compile(r"\bno (?:credential )?warnings?\b", re.IGNORECASE)


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
    if shift_id not in ledger.candidate_pools:
        problems.append(
            GroundingProblem(
                code="POOL_NOT_SEARCHED",
                message=(
                    f"search_clinicians was never called for {shift_id}, so its candidate pool "
                    "is unknown and better or eligible candidates may be missed. Search the pool, "
                    "vet every candidate with evaluate_candidates, then submit again."
                ),
                action=GroundingAction.FLAG,
            )
        )
    elif unvetted := ledger.unvetted_candidates(shift_id):
        problems.append(
            GroundingProblem(
                code="INCOMPLETE_VETTING",
                message=(
                    f"The candidate pool for {shift_id} includes {', '.join(unvetted)}, but they "
                    "were never vetted, so the shortlist may miss better candidates. Vet them "
                    "with evaluate_candidates, then submit again."
                ),
                action=GroundingAction.FLAG,
            )
        )
    facility_scopes = {ledger.shifts[shift_id].facility_id, GLOBAL_SCOPE}
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

        for chunk_id in rec.citation_ids:
            excerpt = ledger.policy_excerpts.get(chunk_id)
            if excerpt is None:
                problems.append(
                    _drop_citation(
                        index,
                        chunk_id,
                        "UNKNOWN_CITATION",
                        f"Citation '{chunk_id}' was not returned by search_facility_policies.",
                    )
                )
            elif excerpt.facility_id not in facility_scopes:
                problems.append(
                    _drop_citation(
                        index,
                        chunk_id,
                        "OTHER_FACILITY_CITATION",
                        f"Citation '{chunk_id}' is another facility's policy and cannot support "
                        f"a recommendation for {shift_id}.",
                    )
                )
        problems.extend(_warning_mismatches(index, rec, evaluation))
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


def _warning_mismatches(
    index: int, rec: RecommendedCandidate, evaluation: CandidateEvaluation
) -> list[GroundingProblem]:
    """The rationale must mention each credential warning and must not deny having any."""
    if not evaluation.warnings:
        return []
    rationale = rec.rationale.lower()
    missing = [
        w.credential
        for w in evaluation.warnings
        if w.credential is not None and _credential_word(w.credential) not in rationale
    ]
    if not missing and not _NO_WARNINGS_CLAIM.search(rec.rationale):
        return []
    details = "; ".join(w.message for w in evaluation.warnings)
    return [
        GroundingProblem(
            code="RATIONALE_WARNING_MISMATCH",
            message=(
                f"The rationale for {rec.clinician_id} must mention its credential warning "
                f"and must not say there are none: {details}"
            ),
            action=GroundingAction.FLAG,
            index=index,
        )
    ]


def _credential_word(credential: CredentialType) -> str:
    return "license" if credential is CredentialType.RN_LICENSE else credential.value.lower()


def _drop(index: int, code: str, message: str) -> GroundingProblem:
    return GroundingProblem(code, message, GroundingAction.DROP_RECOMMENDATION, index)


def _drop_citation(index: int, chunk_id: str, code: str, message: str) -> GroundingProblem:
    return GroundingProblem(code, message, GroundingAction.DROP_CITATION, index, chunk_id)
