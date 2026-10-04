"""Deterministic completion: finish mandatory work that the model's final answer left undone.

It runs after validation succeeds or repairs run out, never after a rejected submission. It reuses
the repository's candidate-pool query, the eligibility engine, the fallback's rule ordering and
the outreach template. Everything it produces is recorded in the evidence ledger, so the verifier
checks it like any other evidence. Valid model picks keep their order: code only appends
eligible clinicians until the requested shortlist is reached, and records what it added.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shift_assistant.agent.submission import AgentSubmission, RecommendedCandidate, SubmissionStatus
from shift_assistant.contracts import CompletionRecord, StaffingRequest
from shift_assistant.domain.models import Shift
from shift_assistant.reliability.grounding import GroundingAction, check_grounding
from shift_assistant.reliability.reporting import rule_ranked
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.notes import DEFAULT_NOTE
from shift_assistant.tools.schemas import CandidateEvaluation, OutreachDraft
from shift_assistant.tools.toolkit import StaffingToolkit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Completion:
    submission: AgentSubmission
    ledger: EvidenceLedger
    record: CompletionRecord = field(default_factory=CompletionRecord)
    unresolved: list[str] = field(default_factory=list)  # why mandatory work is still missing


class DeterministicCompletion:
    def __init__(
        self, repository: StaffingRepository, toolkit: StaffingToolkit, max_recommendations: int
    ) -> None:
        self._repository = repository
        self._toolkit = toolkit
        self._max_recommendations = max_recommendations

    def complete(
        self, request: StaffingRequest, submission: AgentSubmission, ledger: EvidenceLedger
    ) -> Completion:
        if submission.status is not SubmissionStatus.COMPLETED:
            return Completion(submission, ledger)
        shift = self._repository.shift(submission.shift_id or "")
        if shift is None or shift.id not in ledger.shifts:  # validation rejects this first
            return Completion(submission, ledger, unresolved=["The shift could not be resolved."])

        unresolved: list[str] = []
        pool = ledger.candidate_pools.get(shift.id)
        pool_determined_by_code = pool is None
        if pool is None:  # the same query search_clinicians records
            pool = [c.id for c in self._repository.candidate_pool(shift)]
            ledger = ledger.merge(EvidenceLedger.of(candidate_pools={shift.id: pool}))

        evaluated = self._evaluate_rest(shift, pool, ledger, unresolved)
        ledger = ledger.merge(EvidenceLedger.of(evaluations=evaluated))

        recommendations, verified, invalid_drafts = self._verified(request, submission, ledger)
        selected: list[str] = []
        cap = min(request.shortlist_target(shift.positions_open), self._max_recommendations)
        present = {r.clinician_id for r in recommendations}
        pool_evaluations = [e for cid in pool if (e := ledger.evaluation(shift.id, cid))]
        for evaluation in rule_ranked(pool_evaluations):
            if len(verified) >= cap:
                break
            if evaluation.clinician_id in present:
                continue
            recommendations.append(
                RecommendedCandidate(
                    clinician_id=evaluation.clinician_id, rationale=_rationale(evaluation)
                )
            )
            verified.append(len(recommendations) - 1)
            selected.append(evaluation.clinician_id)

        drafts: list[OutreachDraft] = []
        if request.draft_outreach:
            for index in verified:
                rec = recommendations[index]
                if rec.draft_id is not None and index not in invalid_drafts:
                    continue
                if (draft := self._draft(shift, rec.clinician_id, ledger, unresolved)) is None:
                    continue
                drafts.append(draft)
                recommendations[index] = rec.model_copy(update={"draft_id": draft.draft_id})
        ledger = ledger.merge(EvidenceLedger.of(drafts=drafts))

        record = CompletionRecord(
            pool_determined_by_code=pool_determined_by_code,
            evaluated_ids=[e.clinician_id for e in evaluated],
            selected_ids=selected,
            drafted_ids=[d.clinician_id for d in drafts],
        )
        augmented = submission.model_copy(update={"recommendations": recommendations})
        return Completion(augmented, ledger, record, unresolved)

    def _evaluate_rest(
        self, shift: Shift, pool: list[str], ledger: EvidenceLedger, unresolved: list[str]
    ) -> list[CandidateEvaluation]:
        evaluations = []
        for clinician_id in pool:
            if ledger.evaluation(shift.id, clinician_id) is not None:
                continue
            try:
                clinician = self._repository.clinician(clinician_id)
                if clinician is None:
                    raise LookupError("clinician not in the system of record")
                evaluations.append(self._toolkit.evaluate(shift, clinician))
            except Exception as exc:  # a required check could not run: leave it unresolved
                logger.warning("Completion could not vet %s (%s)", clinician_id, type(exc).__name__)
                unresolved.append(
                    f"The compliance check for {clinician_id} could not run "
                    f"({type(exc).__name__}). Vet this clinician manually."
                )
        return evaluations

    def _verified(
        self, request: StaffingRequest, submission: AgentSubmission, ledger: EvidenceLedger
    ) -> tuple[list[RecommendedCandidate], list[int], set[int]]:
        """The submission's picks, the indices that pass grounding, and those with bad drafts."""
        problems = check_grounding(submission, ledger, self._max_recommendations, request)
        dropped = {p.index for p in problems if p.action is GroundingAction.DROP_RECOMMENDATION}
        invalid_drafts = {
            p.index
            for p in problems
            if p.action is GroundingAction.DROP_DRAFT and p.index is not None
        }
        recommendations = list(submission.recommendations)
        verified = [i for i in range(len(recommendations)) if i not in dropped]
        return recommendations, verified, invalid_drafts

    def _draft(
        self, shift: Shift, clinician_id: str, ledger: EvidenceLedger, unresolved: list[str]
    ) -> OutreachDraft | None:
        evaluation = ledger.evaluation(shift.id, clinician_id)
        clinician = self._repository.clinician(clinician_id)
        try:
            if evaluation is None or not evaluation.eligible or clinician is None:
                raise LookupError("no eligible evaluation on record")
            return self._toolkit.create_draft(shift, clinician, DEFAULT_NOTE, evaluation)
        except Exception as exc:
            logger.warning(
                "Completion could not draft for %s (%s)", clinician_id, type(exc).__name__
            )
            unresolved.append(
                f"Outreach for {clinician_id} could not be drafted ({type(exc).__name__}). "
                "Write it manually."
            )
            return None


def _rationale(evaluation: CandidateEvaluation) -> str:
    """Satisfies the submission schema; the report renders its own explanation from evidence."""
    facts = ["Added by deterministic completion after passing the recorded compliance checks."]
    facts.extend(w.message for w in evaluation.warnings)
    return " ".join(facts)[:600]
