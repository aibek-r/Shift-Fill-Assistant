"""Typed arguments and results of every agent tool.

Argument models double as the JSON schemas the LLM sees (field descriptions included), and as the
validation layer: malformed tool calls are rejected with a readable error the model can fix.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shift_assistant.domain.eligibility import CredentialCheck, Finding
from shift_assistant.domain.models import Facility, Role, Shift, Unit


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
    # Shown in the report, kept out of the model's context: findings already carry what it needs.
    credentials: list[CredentialCheck] = Field(default_factory=list, exclude=True)
    years_experience: int | None = Field(default=None, exclude=True)
    preference_quotes: list[str] = Field(default_factory=list, exclude=True)


class EvaluateCandidatesResult(_Result):
    shift_id: str
    evaluations: list[CandidateEvaluation]
    unknown_clinician_ids: list[str]


# --- draft_outreach ----------------------------------------------------------------------------

_PII_OR_PAY = re.compile(
    r"[\w.+-]+@[\w-]+\.\w+"  # email address
    r"|\+?\d[\d\s().-]{8,}\d"  # phone number
    r"|\$\s?\d|\bper hour\b|/hr\b",  # pay rates (not allowed in first-touch outreach)
    re.IGNORECASE,
)


class DraftOutreachArgs(_Args):
    shift_id: str
    clinician_id: str
    personal_note: str = Field(
        min_length=20,
        max_length=500,
        description=(
            "Select 1-3 of these exact friendly sentences: 'We would love to have you on this "
            "shift.'; 'Would you be interested in this shift?'; 'Thank you for considering this "
            "opportunity.'; 'We would be happy to discuss this opportunity with you.'; "
            "'We think you would fit this unit well.'. Recorded experience, exact profile "
            "preferences, shift logistics and credential reminders are added automatically. "
            "Do not write facts, pay rates, contact details or other clinicians in this note."
        ),
    )

    @field_validator("personal_note")
    @classmethod
    def _no_pii_or_pay(cls, note: str) -> str:
        if _PII_OR_PAY.search(note):
            raise ValueError("must not contain contact details or pay rates")
        return note


class OutreachDraft(_Result):
    draft_id: str
    shift_id: str
    clinician_id: str
    personal_note: str
    subject: str
    body: str
