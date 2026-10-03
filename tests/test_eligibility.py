from __future__ import annotations

from datetime import date

import pytest

from shift_assistant.domain.eligibility import CheckCode, EligibilityEngine, EligibilityResult
from shift_assistant.domain.models import CredentialType
from shift_assistant.repository import StaffingRepository


def evaluate(repo: StaffingRepository, clinician_id: str, shift_id: str) -> EligibilityResult:
    clinician, shift = repo.clinician(clinician_id), repo.shift(shift_id)
    assert clinician is not None and shift is not None
    facility = repo.facility(shift.facility_id)
    assert facility is not None
    return EligibilityEngine(30).evaluate(
        clinician, shift, facility, repo.bookings_for(clinician_id)
    )


@pytest.mark.parametrize(
    ("clinician_id", "shift_id", "expected"),
    [
        ("C-102", "SHF-1001", CheckCode.CREDENTIAL_EXPIRED),  # ACLS lapses before the shift
        ("C-103", "SHF-1001", CheckCode.INSUFFICIENT_REST),  # day shift ends as this one starts
        ("C-105", "SHF-1001", CheckCode.INSUFFICIENT_EXPERIENCE),
        ("C-106", "SHF-1001", CheckCode.LICENSE_NOT_VALID_IN_STATE),  # CA license, TX facility
        ("C-108", "SHF-1001", CheckCode.INACTIVE),
        ("C-109", "SHF-1001", CheckCode.SCHEDULE_CONFLICT),
        ("C-110", "SHF-1002", CheckCode.MISSING_CREDENTIAL),  # no TNCC for the ED
        ("C-118", "SHF-3001", CheckCode.LICENSE_NOT_VALID_IN_STATE),  # CA rejects compact
        ("C-114", "SHF-2001", CheckCode.LICENSE_NOT_VALID_IN_STATE),
        ("C-120", "SHF-3002", CheckCode.CREDENTIAL_EXPIRED),
    ],
)
def test_blockers(
    repository: StaffingRepository, clinician_id: str, shift_id: str, expected: CheckCode
) -> None:
    result = evaluate(repository, clinician_id, shift_id)

    assert not result.eligible
    assert [b.code for b in result.blockers] == [expected]


def test_fully_compliant_clinician_is_eligible(repository: StaffingRepository) -> None:
    result = evaluate(repository, "C-101", "SHF-1001")

    assert result.eligible
    assert result.warnings == []


def test_credential_expiring_soon_is_a_warning_not_a_blocker(
    repository: StaffingRepository,
) -> None:
    result = evaluate(repository, "C-104", "SHF-1001")

    assert result.eligible
    assert [(w.code, w.credential) for w in result.warnings] == [
        (CheckCode.CREDENTIAL_EXPIRING_SOON, CredentialType.ACLS)
    ]


def test_credential_expiring_on_the_last_shift_day_is_still_valid(
    repository: StaffingRepository,
) -> None:
    clinician, shift = repository.clinician("C-101"), repository.shift("SHF-1001")
    facility = repository.facility("FAC-001")
    assert clinician and shift and facility
    shift_end_day = shift.end.date()
    credentials = [
        c.model_copy(update={"expires_on": shift_end_day}) if c.type is CredentialType.ACLS else c
        for c in clinician.credentials
    ]
    patched = clinician.model_copy(update={"credentials": credentials})

    result = EligibilityEngine(30).evaluate(patched, shift, facility, [])

    assert result.eligible
    assert result.warnings[0].code is CheckCode.CREDENTIAL_EXPIRING_SOON
    assert shift_end_day == date(2026, 10, 15)
