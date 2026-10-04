"""Relative-date regressions: dates are checked even when model prose is incorrect."""

from datetime import date

import pytest

from shift_assistant.agent.prompts import build_initial_messages
from shift_assistant.contracts import ReportStatus, RunMode, StaffingRequest
from shift_assistant.domain.models import Unit
from shift_assistant.intent import relative_date_window
from shift_assistant.reliability.reporting import relative_date_clarification
from shift_assistant.tools.schemas import FindOpenShiftsArgs
from shift_assistant.tools.toolkit import StaffingToolkit
from tests.conftest import AssistantFactory, ai, tool_call
from tests.test_agent_workflow import SUBMIT, clarification, rec, research_steps, submission


@pytest.mark.parametrize(
    ("phrase", "today", "start", "end"),
    [
        ("next week", "2026-10-02", "2026-10-05", "2026-10-11"),
        ("next week", "2026-10-04", "2026-10-05", "2026-10-11"),
        ("next week", "2026-10-05", "2026-10-12", "2026-10-18"),
        ("next week", "2026-12-31", "2027-01-04", "2027-01-10"),
        ("this week", "2026-10-04", "2026-09-28", "2026-10-04"),
        ("tomorrow", "2026-12-31", "2027-01-01", "2027-01-01"),
        ("today", "2026-10-02", "2026-10-02", "2026-10-02"),
    ],
)
def test_calendar_windows(phrase: str, today: str, start: str, end: str) -> None:
    window = relative_date_window(f"Find an ICU nurse {phrase}", date.fromisoformat(today))
    assert window is not None
    assert (window.start, window.end) == (date.fromisoformat(start), date.fromisoformat(end))


@pytest.mark.parametrize("text", ["Find a nurse October 14", "Find a nurse tomorrow or next week"])
def test_unsupported_or_ambiguous_dates_are_not_guessed(text: str) -> None:
    assert relative_date_window(text, date(2026, 10, 2)) is None


def test_model_receives_the_exact_calendar_window() -> None:
    request = StaffingRequest(text="Can you find an ICU nurse for St. Mary's next week?")
    messages = build_initial_messages(request, date(2026, 10, 2), 5)
    assert "next week (2026-10-05 to 2026-10-11)" in str(messages[1].content)


def test_clarification_filters_outside_dates_when_a_matching_shift_exists(
    toolkit: StaffingToolkit,
) -> None:
    shifts = list(
        toolkit.find_open_shifts(FindOpenShiftsArgs(unit=Unit.ICU)).evidence.shifts.values()
    )
    request = StaffingRequest(text="Find an ICU nurse tomorrow")
    rendered = relative_date_clarification(request, shifts, date(2026, 10, 13))
    assert rendered is not None
    summary, question = rendered
    assert "SHF-1001" in summary and "SHF-1003" not in summary
    assert "Thu, Oct 15, 2026" in question and "America/Chicago" in question
    assert "Alternatives" not in question


def test_outside_week_submission_is_repaired_into_a_grounded_clarification(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, model = scripted_assistant(
        [
            *research_steps(),
            ai(tool_call(SUBMIT, **submission(rec("C-101"), rec("C-107")))),
            ai(tool_call(SUBMIT, **clarification())),
        ]
    )
    report = assistant.run(StaffingRequest(text="Find two ICU nurses next week without outreach"))
    assert report.mode is RunMode.AGENT and report.status is ReportStatus.NEEDS_CLARIFICATION
    assert "starts outside next week (2026-10-05 to 2026-10-11)" in str(
        model.received[-1][-1].content
    )
    assert "Alternatives outside that period" in (report.clarification_question or "")
    assert not report.recommendations and report.shift is None
    assert [e.ok for e in report.trace if e.kind == "validation"] == [False, True]


def test_fallback_cannot_silently_staff_an_outside_week_shift(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [
            *research_steps(),
            ai(tool_call(SUBMIT, **submission(rec("C-101"), rec("C-107")))),
        ],
        max_repair_attempts=0,
    )
    report = assistant.run(StaffingRequest(text="Find two ICU nurses next week without outreach"))
    assert report.mode is RunMode.FALLBACK and report.status is ReportStatus.NEEDS_CLARIFICATION
    assert "2026-10-05 to 2026-10-11" in (report.clarification_question or "")
    assert not report.recommendations and report.shift is None


def test_matching_week_can_complete_a_shortlist(scripted_assistant: AssistantFactory) -> None:
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **submission(rec("C-101"), rec("C-107"))))],
        reference_date=date(2026, 10, 9),
    )
    report = assistant.run(StaffingRequest(text="Find two ICU nurses next week without outreach"))
    assert report.mode is RunMode.AGENT and report.status is ReportStatus.READY
    assert len(report.recommendations) == 2


def test_pinned_shift_still_overrides_conflicting_relative_dates(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **submission(rec("C-101"), rec("C-107"))))]
    )
    report = assistant.run(
        StaffingRequest(text="Find two ICU nurses next week without outreach", shift_id="SHF-1001")
    )
    assert report.mode is RunMode.AGENT and report.status is ReportStatus.READY
