"""Run-scoped memory of everything the tools returned.

The ledger is the agent's structured working memory and the source of truth for grounding
checks: a final answer may only reference shifts, policies, evaluations and drafts recorded here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from shift_assistant.tools.schemas import (
    CandidateEvaluation,
    OutreachDraft,
    PolicyExcerpt,
    ShiftSummary,
)


class EvidenceLedger(BaseModel):
    model_config = ConfigDict(frozen=True)

    shifts: dict[str, ShiftSummary] = {}
    policy_excerpts: dict[str, PolicyExcerpt] = {}
    searched_candidates: dict[str, list[str]] = {}  # shift_id -> clinician IDs surfaced
    candidate_pools: dict[str, list[str]] = {}  # shift_id -> every role and specialty match
    evaluations: dict[str, CandidateEvaluation] = {}  # keyed by evaluation_key()
    drafts: dict[str, OutreachDraft] = {}

    @staticmethod
    def evaluation_key(shift_id: str, clinician_id: str) -> str:
        return f"{shift_id}/{clinician_id}"

    @classmethod
    def of(
        cls,
        *,
        shifts: Sequence[ShiftSummary] = (),
        policy_excerpts: Sequence[PolicyExcerpt] = (),
        searched_candidates: Mapping[str, Sequence[str]] | None = None,
        candidate_pools: Mapping[str, Sequence[str]] | None = None,
        evaluations: Sequence[CandidateEvaluation] = (),
        drafts: Sequence[OutreachDraft] = (),
    ) -> EvidenceLedger:
        return cls(
            shifts={s.shift_id: s for s in shifts},
            policy_excerpts={p.chunk_id: p for p in policy_excerpts},
            searched_candidates={k: list(v) for k, v in (searched_candidates or {}).items()},
            candidate_pools={k: list(v) for k, v in (candidate_pools or {}).items()},
            evaluations={cls.evaluation_key(e.shift_id, e.clinician_id): e for e in evaluations},
            drafts={d.draft_id: d for d in drafts},
        )

    def merge(self, other: EvidenceLedger) -> EvidenceLedger:
        searched = dict(self.searched_candidates)
        for shift_id, ids in other.searched_candidates.items():
            searched[shift_id] = list(dict.fromkeys([*searched.get(shift_id, []), *ids]))
        return EvidenceLedger(
            shifts={**self.shifts, **other.shifts},
            policy_excerpts={**self.policy_excerpts, **other.policy_excerpts},
            searched_candidates=searched,
            candidate_pools={**self.candidate_pools, **other.candidate_pools},
            evaluations={**self.evaluations, **other.evaluations},
            drafts={**self.drafts, **other.drafts},
        )

    def evaluation(self, shift_id: str, clinician_id: str) -> CandidateEvaluation | None:
        return self.evaluations.get(self.evaluation_key(shift_id, clinician_id))

    def evaluations_for(self, shift_id: str) -> list[CandidateEvaluation]:
        return [e for e in self.evaluations.values() if e.shift_id == shift_id]

    def unvetted_candidates(self, shift_id: str) -> list[str]:
        """Candidates surfaced by search for this shift that were never compliance-checked."""
        return [
            cid
            for cid in self.searched_candidates.get(shift_id, [])
            if self.evaluation(shift_id, cid) is None
        ]
