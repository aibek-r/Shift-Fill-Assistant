"""Deterministic eligibility rules.

Compliance decisions (licensure, certifications, experience, double-booking, rest time) are made
here in plain code, never by the LLM. The agent may only recommend clinicians this engine marks
eligible, and the verifier re-applies the verdicts before anything reaches a coordinator.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from shift_assistant.domain.models import (
    COMPACT_JURISDICTION,
    Assignment,
    Clinician,
    ClinicianStatus,
    Credential,
    CredentialType,
    Facility,
    Shift,
    UnitRequirement,
)


class CheckCode(StrEnum):
    # Blockers: the clinician cannot be offered the shift.
    INACTIVE = "INACTIVE"
    ROLE_MISMATCH = "ROLE_MISMATCH"
    SPECIALTY_MISMATCH = "SPECIALTY_MISMATCH"
    UNIT_NOT_CONFIGURED = "UNIT_NOT_CONFIGURED"
    INSUFFICIENT_EXPERIENCE = "INSUFFICIENT_EXPERIENCE"
    MISSING_CREDENTIAL = "MISSING_CREDENTIAL"
    LICENSE_NOT_VALID_IN_STATE = "LICENSE_NOT_VALID_IN_STATE"
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
    INSUFFICIENT_REST = "INSUFFICIENT_REST"
    # Warnings: eligible, but a coordinator should act.
    CREDENTIAL_EXPIRING_SOON = "CREDENTIAL_EXPIRING_SOON"


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: CheckCode
    message: str
    credential: CredentialType | None = None


class EligibilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    clinician_id: str
    shift_id: str
    blockers: list[Finding]
    warnings: list[Finding]

    @property
    def eligible(self) -> bool:
        return not self.blockers


class EligibilityEngine:
    def __init__(self, expiry_warning_days: int = 30) -> None:
        self._warning_window = timedelta(days=expiry_warning_days)

    def evaluate(
        self,
        clinician: Clinician,
        shift: Shift,
        facility: Facility,
        bookings: Sequence[Assignment],
    ) -> EligibilityResult:
        blockers: list[Finding] = []
        warnings: list[Finding] = []

        blockers.extend(self._profile_blockers(clinician, shift))
        requirement = facility.units.get(shift.unit)
        if requirement is None:
            blockers.append(
                Finding(
                    code=CheckCode.UNIT_NOT_CONFIGURED,
                    message=f"{facility.name} has no requirements configured for {shift.unit}.",
                )
            )
        else:
            if clinician.years_experience < requirement.min_years_experience:
                blockers.append(
                    Finding(
                        code=CheckCode.INSUFFICIENT_EXPERIENCE,
                        message=(
                            f"{clinician.years_experience} years of experience; "
                            f"{shift.unit} requires {requirement.min_years_experience}."
                        ),
                    )
                )
            for finding in self._credential_findings(clinician, shift, facility, requirement):
                is_warning = finding.code is CheckCode.CREDENTIAL_EXPIRING_SOON
                (warnings if is_warning else blockers).append(finding)
        blockers.extend(self._schedule_blockers(shift, facility, bookings))

        return EligibilityResult(
            clinician_id=clinician.id, shift_id=shift.id, blockers=blockers, warnings=warnings
        )

    @staticmethod
    def _profile_blockers(clinician: Clinician, shift: Shift) -> Iterator[Finding]:
        if clinician.status is not ClinicianStatus.ACTIVE:
            yield Finding(
                code=CheckCode.INACTIVE, message=f"Clinician status is {clinician.status}."
            )
        if clinician.role is not shift.role:
            yield Finding(
                code=CheckCode.ROLE_MISMATCH,
                message=f"Role {clinician.role} does not match required role {shift.role}.",
            )
        if shift.unit not in clinician.specialties:
            yield Finding(
                code=CheckCode.SPECIALTY_MISMATCH,
                message=f"No {shift.unit} specialty on profile.",
            )

    def _credential_findings(
        self,
        clinician: Clinician,
        shift: Shift,
        facility: Facility,
        requirement: UnitRequirement,
    ) -> Iterator[Finding]:
        # A credential must stay active through the (facility-local) date the shift ends.
        must_be_valid_on = shift.end.date()
        for credential_type in requirement.required_credentials:
            held = clinician.credentials_of(credential_type)
            if credential_type is CredentialType.RN_LICENSE:
                usable = [c for c in held if _license_valid_in(c, facility)]
                if held and not usable:
                    yield Finding(
                        code=CheckCode.LICENSE_NOT_VALID_IN_STATE,
                        message=_license_mismatch_message(held, facility),
                        credential=credential_type,
                    )
                    continue
                held = usable
            if not held:
                yield Finding(
                    code=CheckCode.MISSING_CREDENTIAL,
                    message=f"No {credential_type} on file.",
                    credential=credential_type,
                )
                continue
            latest = max(held, key=lambda c: c.expires_on)
            yield from self._expiry_findings(latest, must_be_valid_on)

    def _expiry_findings(self, credential: Credential, valid_through: date) -> Iterator[Finding]:
        if credential.expires_on < valid_through:
            yield Finding(
                code=CheckCode.CREDENTIAL_EXPIRED,
                message=(
                    f"{credential.type} expires {credential.expires_on}, "
                    f"before the shift ends on {valid_through}."
                ),
                credential=credential.type,
            )
        elif credential.expires_on <= valid_through + self._warning_window:
            days_left = (credential.expires_on - valid_through).days
            yield Finding(
                code=CheckCode.CREDENTIAL_EXPIRING_SOON,
                message=(
                    f"{credential.type} expires {credential.expires_on}, "
                    f"{days_left} days after the shift. Request a renewal."
                ),
                credential=credential.type,
            )

    @staticmethod
    def _schedule_blockers(
        shift: Shift, facility: Facility, bookings: Sequence[Assignment]
    ) -> Iterator[Finding]:
        min_rest = timedelta(hours=facility.min_rest_hours)
        for booking in bookings:
            if booking.start < shift.end and shift.start < booking.end:
                yield Finding(
                    code=CheckCode.SCHEDULE_CONFLICT,
                    message=(
                        f"Already booked ({booking.id}) {booking.start.isoformat()} to "
                        f"{booking.end.isoformat()}, overlapping this shift."
                    ),
                )
                continue
            rest = (
                shift.start - booking.end
                if booking.end <= shift.start
                else booking.start - shift.end
            )
            if rest < min_rest:
                hours = rest.total_seconds() / 3600
                yield Finding(
                    code=CheckCode.INSUFFICIENT_REST,
                    message=(
                        f"Only {hours:.1f}h between this shift and booking {booking.id}; "
                        f"{facility.name} requires {facility.min_rest_hours}h of rest."
                    ),
                )


def _license_valid_in(license_: Credential, facility: Facility) -> bool:
    if license_.jurisdiction == facility.state:
        return True
    return license_.jurisdiction == COMPACT_JURISDICTION and facility.accepts_compact_license


def _license_mismatch_message(licenses: Sequence[Credential], facility: Facility) -> str:
    held = ", ".join(sorted({c.jurisdiction or "unknown" for c in licenses}))
    accepted = (
        f"{facility.state} or COMPACT" if facility.accepts_compact_license else facility.state
    )
    return f"RN license jurisdiction ({held}) is not valid in {facility.state}; needs {accepted}."
