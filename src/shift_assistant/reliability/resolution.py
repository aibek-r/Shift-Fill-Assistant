"""Deterministic shift resolution for the rule-based fallback.

Order: a pinned shift; explicit typed request fields; then conservative parsing of the request
text (facility names, a small unit synonym list, "day shift"/"night shift", and explicit or
relative dates). Typed fields override the text. Missing details are never invented: several
matches produce a clarification with the options, and no match produces a clarification that
says which details did not match. Dates are facility-local shift start dates, as in
find_open_shifts, and relative dates use each facility's own "today".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from shift_assistant.contracts import StaffingRequest
from shift_assistant.domain.models import Facility, Shift, Unit
from shift_assistant.intent import (
    RequestedDates,
    requested_dates,
    requested_period,
    requested_units,
)
from shift_assistant.reliability.reporting import clarification_summary
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.outreach import unit_label
from shift_assistant.tools.schemas import ShiftSummary

TodayIn = Callable[[str], date]  # facility time zone -> that facility's "today"


@dataclass(frozen=True)
class ShiftResolution:
    shift: Shift | None = None
    method: Literal["pinned", "agent", "request", ""] = ""
    criteria: str = ""  # what the request matched on, for the report summary
    clarification: tuple[str, str] | None = None  # (summary, question)


def resolve_shift(
    request: StaffingRequest,
    repository: StaffingRepository,
    summarize: Callable[[Shift], ShiftSummary],
    ledger: EvidenceLedger,
    today_in: TodayIn,
) -> ShiftResolution:
    if request.shift_id:
        return ShiftResolution(repository.shift(request.shift_id), "pinned")

    known = "; ".join(f"{f.name} ({f.id})" for f in repository.facilities())
    if request.facility is not None:
        facilities = repository.find_facilities(request.facility)
        if not facilities:
            return _ask(
                f"No facility matches '{request.facility}'. Known facilities: {known}.",
                "Which facility should I use?",
            )
    else:
        facilities = repository.facilities_mentioned(request.text)
    scope = facilities or repository.facilities()

    dates: dict[str, RequestedDates] = {}
    if request.start_date is None:
        dates = {f.id: requested_dates(request.text, today_in(f.timezone)) for f in scope}
        if problem := _date_problem(list(dates.values())):
            return _ask(problem, "Which date do you mean?")

    units: set[Unit] = {request.unit} if request.unit else set(requested_units(request.text))
    period = requested_period(request.text)

    def date_matches(shift: Shift) -> bool:
        if request.start_date is not None:
            return shift.start.date() == request.start_date
        requested = dates[shift.facility_id]
        return not requested.given or requested.contains(shift.start.date())

    scope_ids = {f.id for f in scope}
    in_scope = [
        s
        for s in repository.shifts()
        if s.facility_id in scope_ids and (not units or s.unit in units)
    ]
    matched = [
        s for s in in_scope if (period is None or summarize(s).period == period) and date_matches(s)
    ]
    criteria = _criteria(facilities, units, period, request.start_date, dates)

    if len(matched) == 1:
        return ShiftResolution(matched[0], "request", criteria)
    found = set(ledger.shifts)
    worked_on = {e.shift_id for e in ledger.evaluations.values()} | set(ledger.searched_candidates)
    agent_choice = ((worked_on & found) or found) & {s.id for s in matched}
    if len(agent_choice) == 1:  # the agent narrowed the request down before it failed
        return ShiftResolution(repository.shift(agent_choice.pop()), "agent", criteria)
    if matched:
        listing = clarification_summary([summarize(s) for s in matched], "")
        return _ask(
            f"Several open shifts match the request. {listing}", "Which shift should I staff?"
        )

    summary = (
        f"No open shift matches the request ({criteria})."
        if criteria
        else ("No open shift matches the request.")
    )
    if in_scope and len(in_scope) < len(repository.shifts()):
        listing = clarification_summary([summarize(s) for s in in_scope], "")
        summary += f" Other dates or shift periods: {listing}"
    if not facilities:
        summary += f" The request does not name a known facility. Known facilities: {known}."
    return _ask(summary, "Which facility, unit and date should I use?")


def _date_problem(requested: Sequence[RequestedDates]) -> str | None:
    """Unreadable or already-past yearless dates are asked about, never guessed or rolled over."""
    invalid = sorted({mention for r in requested for mention in r.invalid})
    if invalid:
        return f"The request mentions a date that does not exist: {', '.join(invalid)}."
    past = sorted({mention for r in requested for mention in r.past})
    if past:
        return (
            f"The request mentions {', '.join(past)}, which has already passed this year. "
            "Dates without a year are read as this year and are never moved to next year."
        )
    return None


def _criteria(
    facilities: Sequence[Facility],
    units: set[Unit],
    period: str | None,
    start_date: date | None,
    dates: dict[str, RequestedDates],
) -> str:
    parts = []
    if facilities:
        parts.append(f"facility {' or '.join(f.name for f in facilities)}")
    if units:
        parts.append(f"unit {' or '.join(sorted(unit_label(u) for u in units))}")
    if period:
        parts.append(f"{period} shift")
    labels = sorted({r.label for r in dates.values() if r.given})
    if start_date is not None:
        parts.append(f"start date {start_date.isoformat()}")
    elif labels:
        parts.append(f"start date {' / '.join(labels)}")
    return "; ".join(parts)


def _ask(summary: str, question: str) -> ShiftResolution:
    return ShiftResolution(clarification=(summary, f"{summary} {question}"))
