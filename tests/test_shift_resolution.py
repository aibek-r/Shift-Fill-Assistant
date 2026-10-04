"""Rule-based shift resolution when no shift is pinned (fallback mode, no API key).

The reference date is fixed at 2026-10-02 unless a test says otherwise; the mock shifts run from
October 14 to 19, 2026.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from shift_assistant.assistant import ShiftFillAssistant, build_assistant
from shift_assistant.contracts import ReportStatus, RunMode, StaffingReport, StaffingRequest
from shift_assistant.domain.models import Unit
from shift_assistant.intent import requested_dates, requested_period, requested_units
from shift_assistant.reliability.resolution import resolve_shift
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.toolkit import StaffingToolkit
from tests.conftest import make_settings


@pytest.fixture(scope="module")
def assistant() -> ShiftFillAssistant:
    return build_assistant(make_settings(), embedder=HashingEmbedder())


def run(text: str, **fields: Any) -> StaffingReport:
    assistant = build_assistant(
        make_settings(reference_date=fields.pop("today", date(2026, 10, 2))),
        embedder=HashingEmbedder(),
    )
    return assistant.run(StaffingRequest(text=text, **fields))


def shift_of(report: StaffingReport) -> str | None:
    return report.shift.shift_id if report.shift else None


@pytest.mark.parametrize(
    "when",
    ["Oct 14", "October 14", "October 14th", "10/14", "2026-10-14", "14 October", "Oct. 14, 2026"],
)
def test_a_unique_match_is_staffed(assistant: ShiftFillAssistant, when: str) -> None:
    report = assistant.run(StaffingRequest(text=f"Find two ICU nurses for St. Mary's on {when}"))

    assert (report.mode, report.status) == (RunMode.FALLBACK, ReportStatus.READY)
    assert shift_of(report) == "SHF-1001"
    assert "SHF-1001 was matched to the request by rules" in report.summary
    assert "start date 2026-10-14" in report.summary


def test_shortlist_size_and_outreach_intent_are_preserved(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(
        StaffingRequest(text="Shortlist only one nurse for the Bayview PICU night shift, no drafts")
    )

    assert shift_of(report) == "SHF-3001" and report.status is ReportStatus.READY
    assert len(report.recommendations) == 1
    assert all(r.outreach is None for r in report.recommendations)


def test_several_matches_ask_with_the_options(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(StaffingRequest(text="We need an ICU nurse at St. Mary's"))

    assert report.status is ReportStatus.NEEDS_CLARIFICATION and report.shift is None
    question = report.clarification_question or ""
    assert "SHF-1001" in question and "SHF-1003" in question
    assert question.endswith("Which shift should I staff?")
    assert report.recommendations == []


def test_the_shift_period_narrows_a_match(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(StaffingRequest(text="Fill the St. Mary's ICU day shift"))

    assert shift_of(report) == "SHF-1003"


def test_an_unknown_facility_is_not_guessed(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(StaffingRequest(text="Find a nurse for Mercy General tomorrow night."))

    assert report.status is ReportStatus.NEEDS_CLARIFICATION and report.shift is None
    question = report.clarification_question or ""
    assert "start date tomorrow (2026-10-03 to 2026-10-03)" in question
    assert "does not name a known facility" in question
    assert "St. Mary's Medical Center (FAC-001)" in question


def test_an_unknown_typed_facility_is_reported(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(StaffingRequest(text="Find an ICU nurse", facility="Mercy General"))

    assert report.status is ReportStatus.NEEDS_CLARIFICATION
    assert "No facility matches 'Mercy General'" in (report.clarification_question or "")


@pytest.mark.parametrize(
    ("text", "fields", "expected"),
    [
        ("ICU nurse at St. Mary's on Oct 14", {"start_date": date(2026, 10, 16)}, "SHF-1003"),
        ("PICU nurse at St. Mary's", {"facility": "Bayview"}, "SHF-3001"),
        ("PICU nurse at Bayview", {"unit": Unit.NICU}, "SHF-3002"),
        ("ED nurse at St. Mary's on Oct 15", {"facility": "FAC-002", "unit": "MED_SURG"}, None),
    ],
)
def test_typed_fields_override_conflicting_text(
    assistant: ShiftFillAssistant, text: str, fields: dict[str, Any], expected: str | None
) -> None:
    report = assistant.run(StaffingRequest(text=text, **fields))

    assert shift_of(report) == expected
    if expected is None:  # Lakeside med-surg runs on Oct 16, not the Oct 15 in the text
        assert report.status is ReportStatus.NEEDS_CLARIFICATION
        assert "SHF-2001" in (report.clarification_question or "")


def test_a_yearless_future_date_uses_the_reference_year() -> None:
    report = run("ICU night shift at St. Mary's on Oct 14", today=date(2026, 10, 10))

    assert shift_of(report) == "SHF-1001"


def test_a_yearless_past_date_asks_instead_of_rolling_into_next_year() -> None:
    report = run("ICU nurse at St. Mary's on Oct 14", today=date(2026, 10, 20))

    assert report.status is ReportStatus.NEEDS_CLARIFICATION and report.shift is None
    question = report.clarification_question or ""
    assert "Oct 14 (2026-10-14), which has already passed this year" in question
    assert "2027" not in question


def test_an_impossible_date_is_asked_about(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(StaffingRequest(text="ICU nurse at St. Mary's on Oct 32"))

    assert report.status is ReportStatus.NEEDS_CLARIFICATION
    assert "does not exist: Oct 32" in (report.clarification_question or "")


@pytest.mark.parametrize(
    ("text", "today", "expected"),
    [
        ("ICU night shift at St. Mary's tomorrow", date(2026, 10, 13), "SHF-1001"),
        ("ICU night shift at St. Mary's next week", date(2026, 10, 9), "SHF-1001"),
        ("Lakeside telemetry shift this week", date(2026, 10, 12), "SHF-2002"),
        ("Bayview NICU today", date(2026, 10, 19), "SHF-3002"),
    ],
)
def test_relative_dates_resolve_against_the_reference_date(
    text: str, today: date, expected: str
) -> None:
    assert shift_of(run(text, today=today)) == expected


def test_relative_dates_use_the_facility_time_zone(
    repository: StaffingRepository, toolkit: StaffingToolkit
) -> None:
    # Late evening in Los Angeles is already the next day in Chicago.
    local_today = {"America/Los_Angeles": date(2026, 10, 17), "America/Chicago": date(2026, 10, 18)}
    request = StaffingRequest(text="Bayview PICU nurse tomorrow")

    resolution = resolve_shift(
        request, repository, toolkit.summarize, EvidenceLedger(), lambda tz: local_today[tz]
    )

    assert resolution.shift is not None and resolution.shift.id == "SHF-3001"  # Oct 18 in LA


def test_a_pinned_shift_still_wins(assistant: ShiftFillAssistant) -> None:
    report = assistant.run(
        StaffingRequest(text="PICU nurse at Bayview on Oct 18", shift_id="SHF-1001", unit="PICU")
    )

    assert shift_of(report) == "SHF-1001"
    assert "matched to the request" not in report.summary


@pytest.mark.parametrize(
    ("text", "units"),
    [
        ("pediatric intensive care", {Unit.PICU}),
        ("a neonatal ICU nurse", {Unit.NICU}),
        ("intensive care unit", {Unit.ICU}),
        ("emergency department", {Unit.ED}),
        ("the ED", {Unit.ED}),
        ("Ed from scheduling asked", set()),  # a name, not the unit
        ("med-surg", {Unit.MED_SURG}),
        ("medical-surgical", {Unit.MED_SURG}),
        ("tele", {Unit.TELEMETRY}),
        ("critical care", set()),  # ambiguous between adult and pediatric units: not guessed
    ],
)
def test_unit_synonyms_are_a_small_explicit_list(text: str, units: set[Unit]) -> None:
    assert requested_units(text) == units


@pytest.mark.parametrize(
    ("text", "dates", "invalid"),
    [
        ("24/7 ICU coverage", set(), ()),
        ("we may need 2 nurses", set(), ()),
        ("May 20", {date(2026, 5, 20)}, ()),
        ("2/31", set(), ("2/31",)),
    ],
)
def test_date_parsing_is_conservative(text: str, dates: set[date], invalid: tuple[str]) -> None:
    requested = requested_dates(text, date(2026, 1, 15))

    assert requested.dates == dates and requested.invalid == invalid


def test_period_needs_one_explicit_shift_phrase() -> None:
    assert requested_period("the night shift") == "night"
    assert requested_period("nurses who prefer night shifts") is None
    assert requested_period("the day shift or the night shift") is None
