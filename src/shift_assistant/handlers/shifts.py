"""Answers about open shifts, built from find_open_shifts and, for "hardest to fill", from the
same eligibility engine the staffing workflow uses. Nothing here is written by a model."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from shift_assistant import templates
from shift_assistant.contracts import Answer, AnswerTable, IntentEntities
from shift_assistant.domain.models import Facility
from shift_assistant.handlers.common import HandlerReply, answered, find_facility
from shift_assistant.intent import RelativeDateWindow, requested_dates, requested_units
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.outreach import format_local_datetime, unit_label
from shift_assistant.tools.schemas import FindOpenShiftsArgs, FindOpenShiftsResult, ShiftSummary
from shift_assistant.tools.toolkit import StaffingToolkit

_I = re.IGNORECASE
_SHIFT_ID = re.compile(r"\bSHF-\d+\b", _I)
_ASKS_PLACES = re.compile(
    r"\bhow\s+many\b|\bopen\s+places\b|\bpositions?\b|\bopenings?\b|\bspots?\b", _I
)
_ASKS_TIMES = re.compile(
    r"\bwhat\s+time\b(?!\s*zone)|\bwhen\s+(?:does|do|will|is)\b|\b(?:start|end)\s+time\b|\bhours\b",
    _I,
)
_HARDEST = re.compile(r"\b(?:hardest|toughest|most\s+difficult|hard)\b", _I)
_PERIOD = re.compile(r"\b(day|night)(?:time)?\s+shifts?\b|\b(nights|days)\b|\b(overnight)\b", _I)
_HOLIDAYS = {  # month, day; the next occurrence is used
    "christmas eve": (12, 24),
    "christmas": (12, 25),
    "new years eve": (12, 31),
    "new years day": (1, 1),
    "halloween": (10, 31),
    "independence day": (7, 4),
    "fourth of july": (7, 4),
}
_HOLIDAY = re.compile(r"\b(" + "|".join(sorted(_HOLIDAYS, key=len, reverse=True)) + r")\b", _I)
_NEXT_LIMIT = 3


@dataclass(frozen=True)
class _DateFilter:
    days: frozenset[date]
    window: RelativeDateWindow | None

    def contains(self, day: date) -> bool:
        return day in self.days or (self.window is not None and self.window.contains(day))

    @property
    def last(self) -> date:
        return max([*self.days, *([self.window.end] if self.window else [])])

    @property
    def label(self) -> str:
        parts = []
        if self.days:
            parts.append("on " + " or ".join(templates.short_date(d) for d in sorted(self.days)))
        if self.window is not None:
            start, end = self.window.start, self.window.end
            span = templates.short_date(start)
            if end != start:
                span += f" to {templates.short_date(end)}"
            parts.append(f"{self.window.phrase} ({span})")
        return " or ".join(parts)


class ShiftQuestions:
    def __init__(
        self,
        repository: StaffingRepository,
        toolkit: StaffingToolkit,
        today: Callable[[], date],
    ) -> None:
        self._repository = repository
        self._toolkit = toolkit
        self._today = today

    def answer(self, text: str, entities: IntentEntities) -> HandlerReply:
        if shift_id := entities.shift_id or _first_shift_id(text):
            return self._one_shift(shift_id.upper(), text)
        if _HARDEST.search(text):
            return self._hardest_to_fill()

        match = find_facility(text, entities, self._repository)
        if match.unknown_name:
            known = [f.name for f in self._repository.facilities()]
            return answered(templates.facility_not_found(match.unknown_name, known))
        units = set(requested_units(text)) or ({entities.unit} if entities.unit else set())
        period = _period(text)
        dates = self._date_filter(text, entities)

        def fits(shift: ShiftSummary) -> bool:
            return (not units or shift.unit in units) and (period is None or shift.period == period)

        candidates = [s for s in self._open_shifts(match.facility) if fits(s)]
        rows = [s for s in candidates if dates is None or dates.contains(_local_day(s))]
        kind = " ".join([*sorted(unit_label(u) for u in units), *([period] if period else [])])
        scope = _scope(match.facility, dates)
        if len(rows) == 1 and _ASKS_TIMES.search(text):
            return answered(_times(rows[0]), _table(rows))
        if len(rows) == 1 and _ASKS_PLACES.search(text):
            return answered(
                templates.open_places(rows[0].shift_id, rows[0].positions_open), _table(rows)
            )
        if rows:
            return answered(templates.open_shifts(len(rows), kind, scope), _table(rows))

        message = templates.no_open_shifts(kind, scope)
        later = [s for s in candidates if _local_day(s) > dates.last][:_NEXT_LIMIT] if dates else []
        if later:
            return answered(f"{message} {templates.NEXT_SHIFTS}", _table(later))
        return answered(message, Answer())

    # --- Sub-answers -----------------------------------------------------------------------------

    def _one_shift(self, shift_id: str, text: str) -> HandlerReply:
        found = self._find(FindOpenShiftsArgs(shift_id=shift_id))
        if not found:
            return answered(templates.shift_not_found(shift_id), Answer())
        shift = found[0]
        if _ASKS_PLACES.search(text) and not _ASKS_TIMES.search(text):
            return answered(
                templates.open_places(shift.shift_id, shift.positions_open), _table(found)
            )
        return answered(_times(shift), _table(found))

    def _hardest_to_fill(self) -> HandlerReply:
        """Fewest eligible nurses per open place, counted by the eligibility engine."""
        counted: list[tuple[ShiftSummary, int]] = []
        for shift in self._repository.shifts():
            pool = self._repository.candidate_pool(shift)
            eligible = sum(self._toolkit.evaluate(shift, nurse).eligible for nurse in pool)
            counted.append((self._toolkit.summarize(shift), eligible))
        counted.sort(key=lambda pair: (pair[1] / pair[0].positions_open, pair[1], pair[0].start))
        first, fewest = counted[0]
        hardest = [
            s.shift_id
            for s, eligible in counted
            if (eligible, s.positions_open) == (fewest, first.positions_open)
        ]
        table = AnswerTable(
            columns=list(templates.HARDEST_COLUMNS),
            rows=[
                [
                    s.shift_id,
                    s.facility_name,
                    unit_label(s.unit),
                    _day_label(s),
                    str(s.positions_open),
                    str(eligible),
                ]
                for s, eligible in counted
            ],
        )
        return answered(
            templates.hardest_to_fill(hardest, fewest, first.positions_open),
            Answer(
                items=[templates.ELIGIBLE_COUNT_NOTE],
                table=table,
                sources=[s.shift_id for s, _ in counted],
            ),
        )

    # --- Data access -----------------------------------------------------------------------------

    def _open_shifts(self, facility: Facility | None) -> list[ShiftSummary]:
        return self._find(FindOpenShiftsArgs(facility=facility.id if facility else None))

    def _find(self, args: FindOpenShiftsArgs) -> list[ShiftSummary]:
        result = self._toolkit.find_open_shifts(args).result
        assert isinstance(result, FindOpenShiftsResult)
        return list(result.shifts)

    def _date_filter(self, text: str, entities: IntentEntities) -> _DateFilter | None:
        today = self._today()
        # Yearless dates are read in this year even if they have passed: a lookup has no
        # booking risk, and a passed date simply has no open shifts.
        explicit = requested_dates(text, date(today.year, 1, 1)).dates
        days = set(explicit) | _holidays(text, today)
        if not days and entities.shift_date:
            days.add(entities.shift_date)
        window = requested_dates(text, today).window
        return _DateFilter(frozenset(days), window) if days or window else None


# --- Helpers -------------------------------------------------------------------------------------


def _first_shift_id(text: str) -> str | None:
    match = _SHIFT_ID.search(text)
    return match.group(0) if match else None


def _period(text: str) -> str | None:
    found = set()
    for match in _PERIOD.finditer(text):
        word = (match[1] or match[2] or match[3]).lower()
        found.add("night" if word in {"night", "nights", "overnight"} else "day")
    return found.pop() if len(found) == 1 else None


def _holidays(text: str, today: date) -> set[date]:
    days = set()
    plain = text.lower().replace("'", "").replace("\N{RIGHT SINGLE QUOTATION MARK}", "")
    for match in _HOLIDAY.finditer(plain):
        month, day = _HOLIDAYS[match[1].lower()]
        this_year = date(today.year, month, day)
        days.add(this_year if this_year >= today else date(today.year + 1, month, day))
    return days


def _scope(facility: Facility | None, dates: _DateFilter | None) -> str:
    parts = []
    if facility is not None:
        parts.append(f"at {facility.name}")
    if dates is not None:
        parts.append(dates.label)
    return "".join(f" {part}" for part in parts)


def _local(moment: datetime, timezone: str) -> datetime:
    return moment.astimezone(ZoneInfo(timezone))


def _local_day(shift: ShiftSummary) -> date:
    return _local(shift.start, shift.timezone).date()


def _day_label(shift: ShiftSummary) -> str:
    start = _local(shift.start, shift.timezone)
    return f"{start:%a, %b} {start.day}"


def _clock(moment: datetime) -> str:
    return f"{moment:%I:%M %p}".lstrip("0")


def _times(shift: ShiftSummary) -> str:
    what = f"{shift.facility_name} {unit_label(shift.unit)} {shift.period} shift"
    start, end = _local(shift.start, shift.timezone), _local(shift.end, shift.timezone)
    return templates.shift_times(
        shift.shift_id,
        what,
        format_local_datetime(start),
        format_local_datetime(end),
        shift.timezone,
    )


def _table(shifts: Sequence[ShiftSummary]) -> Answer:
    rows = []
    for s in shifts:
        start, end = _local(s.start, s.timezone), _local(s.end, s.timezone)
        rows.append(
            [
                s.shift_id,
                s.facility_name,
                unit_label(s.unit),
                _day_label(s),
                f"{_clock(start)} to {_clock(end)} {start.tzname()}",
                s.period,
                str(s.positions_open),
            ]
        )
    return Answer(
        table=AnswerTable(columns=list(templates.SHIFT_COLUMNS), rows=rows),
        sources=[s.shift_id for s in shifts],
    )
