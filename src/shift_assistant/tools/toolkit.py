"""Tool implementations. Pure Python, framework-free and unit-testable.

Each public tool takes a validated args model and returns a `ToolOutput`: the result shown to the
LLM plus the evidence recorded in the run's ledger. Expected problems raise `ToolInputError`, whose
message is returned to the model so it can correct itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from shift_assistant.domain.eligibility import EligibilityEngine
from shift_assistant.domain.models import Clinician, Facility, Shift
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.knowledge import ClinicianProfileIndex, PolicyKnowledgeBase
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.facts import period_fit
from shift_assistant.tools.notes import NoteViolation, note_violations
from shift_assistant.tools.outreach import render_outreach
from shift_assistant.tools.schemas import (
    CandidateEvaluation,
    ClinicianProfile,
    DraftOutreachArgs,
    EvaluateCandidatesArgs,
    EvaluateCandidatesResult,
    FindOpenShiftsArgs,
    FindOpenShiftsResult,
    OutreachDraft,
    PolicyExcerpt,
    SearchCliniciansArgs,
    SearchCliniciansResult,
    SearchFacilityPoliciesArgs,
    SearchFacilityPoliciesResult,
    ShiftSummary,
)


class ToolInputError(ValueError):
    """A recoverable problem with tool arguments. The message is shown to the model."""


class NoteRejected(ToolInputError):
    """A personal note broke the content rules. Lists every violation with the exact text."""

    def __init__(self, violations: Sequence[NoteViolation]) -> None:
        self.violations = tuple(violations)
        listed = "\n".join(f"- {v.message}" for v in self.violations)
        super().__init__(
            "personal_note was rejected. Rewrite it in your own words without these, then "
            f"call draft_outreach again:\n{listed}"
        )


@dataclass(frozen=True)
class ToolOutput:
    result: BaseModel
    evidence: EvidenceLedger


class StaffingToolkit:
    def __init__(
        self,
        repository: StaffingRepository,
        policies: PolicyKnowledgeBase,
        profiles: ClinicianProfileIndex,
        engine: EligibilityEngine,
    ) -> None:
        self._repository = repository
        self._policies = policies
        self._profiles = profiles
        self._engine = engine

    # --- Agent tools -------------------------------------------------------------------------

    def find_open_shifts(self, args: FindOpenShiftsArgs) -> ToolOutput:
        shifts = self._repository.shifts()
        if args.shift_id:
            shifts = [s for s in shifts if s.id == args.shift_id]
        if args.facility:
            matches = self._repository.find_facilities(args.facility)
            if not matches:
                known = "; ".join(f"{f.name} ({f.id})" for f in self._repository.facilities())
                raise ToolInputError(
                    f"No facility matches '{args.facility}'. Known facilities: {known}."
                )
            facility_ids = {f.id for f in matches}
            shifts = [s for s in shifts if s.facility_id in facility_ids]
        if args.unit:
            shifts = [s for s in shifts if s.unit is args.unit]
        if args.start_date:
            shifts = [s for s in shifts if s.start.date() == args.start_date]

        summaries = [self.summarize(s) for s in shifts]
        return ToolOutput(
            FindOpenShiftsResult(shifts=summaries), EvidenceLedger.of(shifts=summaries)
        )

    def search_facility_policies(self, args: SearchFacilityPoliciesArgs) -> ToolOutput:
        if self._repository.facility(args.facility_id) is None:
            raise ToolInputError(f"Unknown facility_id '{args.facility_id}'.")
        excerpts = [
            PolicyExcerpt(
                chunk_id=hit.document.id,
                facility_id=hit.document.metadata["facility_id"],
                section=hit.document.metadata["section"],
                text=hit.document.text,
                score=hit.score,
            )
            for hit in self._policies.search(args.facility_id, args.query, top_k=args.top_k)
        ]
        warnings = self.policy_warnings(args.facility_id)
        if not excerpts:
            warnings.append(
                "No relevant policy excerpts were retrieved. Review facility context manually."
            )
        return ToolOutput(
            SearchFacilityPoliciesResult(excerpts=excerpts, warnings=warnings),
            EvidenceLedger.of(policy_excerpts=excerpts),
        )

    def search_clinicians(self, args: SearchCliniciansArgs) -> ToolOutput:
        shift = self._require_shift(args.shift_id)
        pool = {c.id: c for c in self._repository.candidate_pool(shift)}
        ranked: list[tuple[Clinician, float | None]]
        if args.query:
            hits = self._profiles.rank(args.query, pool.keys(), top_k=args.limit)
            ranked = [(pool[hit.document.id], hit.score) for hit in hits]
        else:
            by_experience = sorted(pool.values(), key=lambda c: -c.years_experience)
            ranked = [(c, None) for c in by_experience[: args.limit]]

        profiles = [_profile(clinician, relevance) for clinician, relevance in ranked]
        return ToolOutput(
            SearchCliniciansResult(
                shift_id=shift.id, candidates_in_pool=len(pool), candidates=profiles
            ),
            EvidenceLedger.of(
                searched_candidates={shift.id: [p.clinician_id for p in profiles]},
                candidate_pools={shift.id: list(pool)},
            ),
        )

    def evaluate_candidates(self, args: EvaluateCandidatesArgs) -> ToolOutput:
        shift = self._require_shift(args.shift_id)
        evaluations: list[CandidateEvaluation] = []
        unknown: list[str] = []
        for clinician_id in dict.fromkeys(args.clinician_ids):  # de-duplicate, keep order
            clinician = self._repository.clinician(clinician_id)
            if clinician is None:
                unknown.append(clinician_id)
            else:
                evaluations.append(self.evaluate(shift, clinician))
        return ToolOutput(
            EvaluateCandidatesResult(
                shift_id=shift.id, evaluations=evaluations, unknown_clinician_ids=unknown
            ),
            EvidenceLedger.of(evaluations=evaluations),
        )

    def draft_outreach(self, args: DraftOutreachArgs) -> ToolOutput:
        shift = self._require_shift(args.shift_id)
        clinician = self._repository.clinician(args.clinician_id)
        if clinician is None:
            raise ToolInputError(f"Unknown clinician_id '{args.clinician_id}'.")
        evaluation = self.evaluate(shift, clinician)
        if not evaluation.eligible:
            codes = ", ".join(b.code for b in evaluation.blockers)
            raise ToolInputError(
                f"{clinician.id} is not eligible for {shift.id} ({codes}). "
                "Outreach can only be drafted for eligible clinicians."
            )
        draft = self.create_draft(shift, clinician, args.personal_note, evaluation)
        return ToolOutput(draft, EvidenceLedger.of(drafts=[draft], evaluations=[evaluation]))

    # --- Domain operations shared with the deterministic fallback ----------------------------

    def summarize(self, shift: Shift) -> ShiftSummary:
        return ShiftSummary.of(shift, self._facility_of(shift))

    def evaluate(self, shift: Shift, clinician: Clinician) -> CandidateEvaluation:
        result = self._engine.evaluate(
            clinician, shift, self._facility_of(shift), self._repository.bookings_for(clinician.id)
        )
        return CandidateEvaluation(
            shift_id=shift.id,
            clinician_id=clinician.id,
            clinician_name=clinician.name,
            eligible=result.eligible,
            blockers=result.blockers,
            warnings=result.warnings,
            credentials=result.credentials,
            years_experience=clinician.years_experience,
            period_fit=period_fit(
                clinician.shift_preference, clinician.open_to, self.summarize(shift).period
            ),
        )

    def create_draft(
        self,
        shift: Shift,
        clinician: Clinician,
        personal_note: str,
        evaluation: CandidateEvaluation,
    ) -> OutreachDraft:
        """Render a draft around a note that passed the content rules.

        The same check covers model-written notes and coordinator edits, so neither the model
        nor the UI is trusted to have filtered the note.
        """
        others = [c.name for c in self._repository.clinicians() if c.id != clinician.id]
        if violations := note_violations(personal_note, others, recipient=clinician.name):
            raise NoteRejected(violations)
        return render_outreach(self.summarize(shift), clinician, personal_note, evaluation.warnings)

    def policy_warnings(self, facility_id: str) -> list[str]:
        missing = self._policies.missing_scopes(facility_id)
        return (
            [
                f"Policy context is missing or empty for {', '.join(missing)}. "
                "Eligibility uses recorded rules; verify facility preferences and "
                "procedures manually."
            ]
            if missing
            else []
        )

    # --- Helpers -----------------------------------------------------------------------------

    def _require_shift(self, shift_id: str) -> Shift:
        shift = self._repository.shift(shift_id)
        if shift is None:
            raise ToolInputError(
                f"Unknown shift_id '{shift_id}'. Use find_open_shifts to get valid IDs."
            )
        return shift

    def _facility_of(self, shift: Shift) -> Facility:
        facility = self._repository.facility(shift.facility_id)
        if facility is None:  # prevented by the repository integrity check
            raise LookupError(f"Shift {shift.id} references unknown facility {shift.facility_id}")
        return facility


def _profile(clinician: Clinician, relevance: float | None) -> ClinicianProfile:
    return ClinicianProfile(
        clinician_id=clinician.id,
        name=clinician.name,
        specialties=clinician.specialties,
        years_experience=clinician.years_experience,
        home_city=clinician.home_city,
        profile=clinician.profile,
        shift_preference=clinician.shift_preference,
        open_to=clinician.open_to,
        relevance=relevance,
    )
