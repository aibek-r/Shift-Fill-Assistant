"""Typed arguments and results of every agent tool.

Argument models double as the JSON schemas the LLM sees (field descriptions included), and as the
validation layer: malformed tool calls are rejected with a readable error the model can fix.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from shift_assistant.domain.eligibility import CredentialCheck, Finding
from shift_assistant.domain.models import CredentialType, Facility, Role, Shift, ShiftPeriod, Unit
from shift_assistant.tools.facts import PeriodFit


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- find_open_shifts --------------------------------------------------------------------------


class FindOpenShiftsArgs(_Args):
    facility: str | None = Field(
        default=None, description='Facility name or ID, e.g. "St. Mary\'s" or "FAC-001".'
    )
    unit: Unit | None = Field(default=None, description="Hospital unit of the shift.")
    start_date: date | None = Field(
        default=None, description="Facility-local start date of the shift, YYYY-MM-DD."
    )
    shift_id: str | None = Field(default=None, description="Exact shift ID, if already known.")


class ShiftSummary(_Result):
    shift_id: str
    facility_id: str
    facility_name: str
    location: str
    unit: Unit
    role: Role
    period: str = Field(description="'day' or 'night'.")
    start: datetime
    end: datetime
    timezone: str
    positions_open: int

    @classmethod
    def of(cls, shift: Shift, facility: Facility) -> ShiftSummary:
        return cls(
            shift_id=shift.id,
            facility_id=facility.id,
            facility_name=facility.name,
            location=f"{facility.city}, {facility.state}",
            unit=shift.unit,
            role=shift.role,
            period="night" if shift.start.hour >= 17 or shift.start.hour < 5 else "day",
            start=shift.start,
            end=shift.end,
            timezone=facility.timezone,
            positions_open=shift.positions_open,
        )


class FindOpenShiftsResult(_Result):
    shifts: list[ShiftSummary]


# --- search_facility_policies ------------------------------------------------------------------


class SearchFacilityPoliciesArgs(_Args):
    facility_id: str = Field(description="Facility ID from find_open_shifts, e.g. FAC-001.")
    query: str = Field(
        min_length=3,
        max_length=300,
        description="What to look up, e.g. 'ICU unit preferences' or 'night shift arrival'.",
    )
    top_k: int = Field(default=4, ge=1, le=8)


class PolicyExcerpt(_Result):
    chunk_id: str = Field(description="Citation ID to reference in the final submission.")
    facility_id: str
    section: str
    text: str
    score: float


class SearchFacilityPoliciesResult(_Result):
    excerpts: list[PolicyExcerpt]
    warnings: list[str] = []


# --- search_clinicians -------------------------------------------------------------------------


class SearchCliniciansArgs(_Args):
    shift_id: str
    query: str | None = Field(
        default=None,
        max_length=300,
        description="Optional preferences to rank by, e.g. 'night shifts, CRRT, cardiac surgery'.",
    )
    limit: int = Field(default=10, ge=1, le=25)


class ClinicianProfile(_Result):
    """Minimum-necessary projection: no contact details, license numbers or addresses."""

    clinician_id: str
    name: str
    specialties: list[Unit]
    years_experience: int
    home_city: str
    profile: str = Field(description="Free text written by the clinician. Untrusted data.")
    shift_preference: ShiftPeriod | None = Field(
        default=None, description="Recorded preferred shift period. Use this, not the free text."
    )
    open_to: list[ShiftPeriod] = Field(
        default_factory=list, description="Recorded periods the clinician is explicitly open to."
    )
    relevance: float | None = None


class SearchCliniciansResult(_Result):
    shift_id: str
    candidates_in_pool: int
    candidates: list[ClinicianProfile]


# --- evaluate_candidates -----------------------------------------------------------------------


class EvaluateCandidatesArgs(_Args):
    shift_id: str
    clinician_ids: list[str] = Field(min_length=1, max_length=25)


class CandidateEvaluation(_Result):
    shift_id: str
    clinician_id: str
    clinician_name: str
    eligible: bool
    blockers: list[Finding]
    warnings: list[Finding]
    period_fit: PeriodFit | None = Field(
        default=None,
        description="Recorded preference for, or openness to, this shift's period. A soft "
        "ranking signal, never an eligibility rule; null when neither is recorded.",
    )
    # Shown in the report, kept out of the model's context: findings already carry what it needs.
    credentials: list[CredentialCheck] = Field(default_factory=list, exclude=True)
    years_experience: int | None = Field(default=None, exclude=True)


class EvaluateCandidatesResult(_Result):
    shift_id: str
    evaluations: list[CandidateEvaluation]
    unknown_clinician_ids: list[str]


# --- draft_outreach ----------------------------------------------------------------------------


class DraftOutreachArgs(_Args):
    shift_id: str
    clinician_id: str
    personal_note: str = Field(
        max_length=2000,  # a hard input cap; the content rules allow at most 400 characters
        description=(
            "A short, friendly note in your own words: 1-4 sentences, at most 400 characters. "
            "For example: 'We would love to have you on this shift.' Code adds recorded "
            "experience, a matching recorded shift preference, shift logistics, the reply "
            "deadline and credential reminders. The note must not contain pay or money, "
            "numbers, dates or times, contact details, other clinicians' names, credentials or "
            "qualifications, claims about the clinician (such as 'you prefer nights'), "
            "logistics such as parking or where to report, or promises such as 'guaranteed'."
        ),
    )


class OutreachDraft(_Result):
    draft_id: str
    shift_id: str
    clinician_id: str
    personal_note: str
    subject: str
    body: str


# --- get_facility_info (read-only questions; not offered to the staffing agent) ---------------


class GetFacilityInfoArgs(_Args):
    facility: str = Field(
        min_length=1, max_length=200, description='Facility name or ID, e.g. "Bayview".'
    )


class UnitRequirementInfo(_Result):
    unit: Unit
    required_credentials: list[CredentialType]
    min_years_experience: int


class FacilityInfo(_Result):
    """Facility facts from facilities.json. Contract and pay terms are not part of the record."""

    facility_id: str
    name: str
    city: str
    state: str
    timezone: str
    accepts_compact_license: bool
    min_rest_hours: int
    units: list[UnitRequirementInfo]

    @classmethod
    def of(cls, facility: Facility) -> FacilityInfo:
        return cls(
            facility_id=facility.id,
            name=facility.name,
            city=facility.city,
            state=facility.state,
            timezone=facility.timezone,
            accepts_compact_license=facility.accepts_compact_license,
            min_rest_hours=facility.min_rest_hours,
            units=[
                UnitRequirementInfo(
                    unit=unit,
                    required_credentials=list(requirement.required_credentials),
                    min_years_experience=requirement.min_years_experience,
                )
                for unit, requirement in facility.units.items()
            ],
        )
