"""Core domain entities of the staffing platform (the mock "system of record")."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

COMPACT_JURISDICTION = "COMPACT"
"""Jurisdiction value for a multistate (Nurse Licensure Compact) RN license."""

ShiftPeriod = Literal["day", "night"]


class Role(StrEnum):
    RN = "RN"


class Unit(StrEnum):
    ICU = "ICU"
    ED = "ED"
    TELEMETRY = "TELEMETRY"
    MED_SURG = "MED_SURG"
    PICU = "PICU"
    NICU = "NICU"


class CredentialType(StrEnum):
    RN_LICENSE = "RN_LICENSE"
    BLS = "BLS"
    ACLS = "ACLS"
    PALS = "PALS"
    TNCC = "TNCC"
    NRP = "NRP"
    CCRN = "CCRN"


class ClinicianStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class _Entity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Credential(_Entity):
    type: CredentialType
    expires_on: date
    number: str | None = None
    jurisdiction: str | None = Field(
        default=None, description="Issuing state code, or COMPACT for a multistate license."
    )


class Clinician(_Entity):
    id: str
    name: str
    role: Role
    status: ClinicianStatus
    specialties: list[Unit]
    years_experience: int = Field(ge=0)
    home_city: str
    home_state: str
    email: str
    phone: str
    credentials: list[Credential]
    profile: str = Field(description="Free text for semantic search. Untrusted; never quoted.")
    # Self-reported soft signals transcribed from the profile. They never affect eligibility.
    shift_preference: ShiftPeriod | None = None
    open_to: list[ShiftPeriod] = Field(
        default=[], description="Periods the clinician is explicitly open to besides a preference."
    )

    @model_validator(mode="after")
    def _distinct_periods(self) -> Self:
        if len(set(self.open_to)) != len(self.open_to) or self.shift_preference in self.open_to:
            raise ValueError("open_to must list distinct periods other than shift_preference")
        return self

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    def credentials_of(self, credential_type: CredentialType) -> list[Credential]:
        return [c for c in self.credentials if c.type is credential_type]


class UnitRequirement(_Entity):
    required_credentials: list[CredentialType]
    min_years_experience: int = Field(ge=0)


class Facility(_Entity):
    id: str
    name: str
    city: str
    state: str
    timezone: str
    accepts_compact_license: bool
    min_rest_hours: int = Field(ge=0)
    units: dict[Unit, UnitRequirement]


class _TimeBlock(_Entity):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError(f"{type(self).__name__} must end after it starts")
        return self


class Shift(_TimeBlock):
    id: str
    facility_id: str
    unit: Unit
    role: Role
    positions_open: int = Field(ge=1)


class Assignment(_TimeBlock):
    """A shift a clinician is already booked on."""

    id: str
    clinician_id: str
    facility_id: str
    unit: Unit
