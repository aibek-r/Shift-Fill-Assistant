"""The model-facing instructions that shape ranking, preferences and date wording."""

from __future__ import annotations

from datetime import date

from shift_assistant.agent.prompts import build_initial_messages
from shift_assistant.contracts import StaffingRequest
from shift_assistant.tools.schemas import DraftOutreachArgs


def test_preferences_come_from_structured_fields_only() -> None:
    request = StaffingRequest(text="Two ICU nurses for the St. Mary's night shift.")
    system = str(build_initial_messages(request, date(2026, 10, 2), 5)[0].content)
    note = DraftOutreachArgs.model_json_schema()["properties"]["personal_note"]["description"]

    assert "(2) period_fit from evaluate_candidates" in system  # ranked after unit fit
    assert "never from profile free text" in system
    assert "never turn openness into a preference" in system
    assert "A preference for the other period does not support a match" in system
    assert "make no claim about it" in system  # nothing recorded: omit the claim
    assert "they never make anyone eligible or ineligible" in system
    assert "exact friendly sentences" in note
    assert "a matching recorded shift preference" in note


def test_clarifications_must_state_dates_accurately() -> None:
    request = StaffingRequest(text="Can you find an ICU nurse for St. Mary's next week?")
    system = str(build_initial_messages(request, date(2026, 10, 2), 5)[0].content)

    assert "Today is 2026-10-02." in system
    assert "say plainly when none falls on the requested dates" in system
    assert "never describe a shift as matching dates it does not" in system


def test_explicit_shift_fields_are_given_to_the_model() -> None:
    request = StaffingRequest(text="ICU nurse at St. Mary's", unit="PICU", facility="Bayview")
    user_turn = str(build_initial_messages(request, date(2026, 10, 2), 5)[1].content)

    assert "Explicit shift details (facility: Bayview; unit: PICU)" in user_turn
    assert "override conflicting request text" in user_turn
