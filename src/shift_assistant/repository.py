"""Read-only access to the mock system of record (JSON files validated on load)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from shift_assistant.domain.models import Assignment, Clinician, Facility, Shift

_M = TypeVar("_M", bound=BaseModel)
_Entity = TypeVar("_Entity", Facility, Clinician, Shift, Assignment)

# Words too generic to identify a facility on their own.
_GENERIC_NAME_TOKENS = {"the", "hospital", "medical", "center", "community", "childrens"}


class DataIntegrityError(ValueError):
    """Raised when the source data references entities that do not exist."""


class StaffingRepository:
    def __init__(
        self,
        facilities: Iterable[Facility],
        clinicians: Iterable[Clinician],
        shifts: Iterable[Shift],
        assignments: Iterable[Assignment],
    ) -> None:
        self._facilities = _index(facilities)
        self._clinicians = _index(clinicians)
        self._shifts = _index(shifts)
        self._assignments = list(assignments)
        self._check_integrity()

    @classmethod
    def from_directory(cls, data_dir: Path) -> StaffingRepository:
        return cls(
            facilities=_load(data_dir / "facilities.json", Facility),
            clinicians=_load(data_dir / "clinicians.json", Clinician),
            shifts=_load(data_dir / "shifts.json", Shift),
            assignments=_load(data_dir / "assignments.json", Assignment),
        )

    # Lookups -------------------------------------------------------------------------------

    def facility(self, facility_id: str) -> Facility | None:
        return self._facilities.get(facility_id)

    def facilities(self) -> list[Facility]:
        return list(self._facilities.values())

    def clinician(self, clinician_id: str) -> Clinician | None:
        return self._clinicians.get(clinician_id)

    def clinicians(self) -> list[Clinician]:
        return list(self._clinicians.values())

    def shift(self, shift_id: str) -> Shift | None:
        return self._shifts.get(shift_id)

    def shifts(self) -> list[Shift]:
        return sorted(self._shifts.values(), key=lambda s: s.start)

    def bookings_for(self, clinician_id: str) -> list[Assignment]:
        return [a for a in self._assignments if a.clinician_id == clinician_id]

    # Queries -------------------------------------------------------------------------------

    def find_facilities(self, query: str) -> list[Facility]:
        """Match by exact ID, or when every distinctive query word prefixes a word of the name."""
        if (exact := self._facilities.get(query.strip().upper())) is not None:
            return [exact]
        query_tokens = set(_tokens(query)) - _GENERIC_NAME_TOKENS or set(_tokens(query))
        if not query_tokens:
            return []
        return [
            facility
            for facility in self._facilities.values()
            if all(
                any(name_token.startswith(q) for name_token in _tokens(facility.name))
                for q in query_tokens
            )
        ]

    def candidate_pool(self, shift: Shift) -> list[Clinician]:
        """Clinicians whose role and specialty fit the shift. Compliance is checked separately."""
        return [
            c
            for c in self._clinicians.values()
            if c.role is shift.role and shift.unit in c.specialties
        ]

    def _check_integrity(self) -> None:
        problems = [
            f"shift {s.id} -> unknown facility {s.facility_id}"
            for s in self._shifts.values()
            if s.facility_id not in self._facilities
        ]
        problems += [
            f"assignment {a.id} -> unknown clinician {a.clinician_id}"
            for a in self._assignments
            if a.clinician_id not in self._clinicians
        ]
        if problems:
            raise DataIntegrityError("; ".join(problems))


def _load(path: Path, model: type[_M]) -> list[_M]:
    return TypeAdapter(list[model]).validate_json(path.read_bytes())  # type: ignore[valid-type]


def _index(items: Iterable[_Entity]) -> dict[str, _Entity]:
    indexed: dict[str, _Entity] = {}
    for item in items:
        item_id = item.id
        if item_id in indexed:
            raise DataIntegrityError(f"duplicate id {item_id}")
        indexed[item_id] = item
    return indexed


def _tokens(text: str) -> Sequence[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))
