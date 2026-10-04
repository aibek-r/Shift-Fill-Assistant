"""The model-facing instructions that shape how shift preferences are worded."""

from __future__ import annotations

from datetime import date

from shift_assistant.agent.prompts import build_initial_messages
from shift_assistant.contracts import StaffingRequest
from shift_assistant.tools.schemas import DraftOutreachArgs


def test_preference_and_willingness_stay_distinct_in_every_generated_text() -> None:
    request = StaffingRequest(text="Two ICU nurses for the St. Mary's night shift.")
    system = str(build_initial_messages(request, date(2026, 10, 2), 5)[0].content)
    note = DraftOutreachArgs.model_json_schema()["properties"]["personal_note"]["description"]

    assert "in the summary, rationales and outreach notes alike" in system
    assert "Never turn willingness into a preference" in system
    assert "never describe it as unwillingness" in system
    assert "make no claim about it" in system  # unknown preference: omit the claim
    assert "keeping preference and willingness distinct" in note


def test_clarifications_must_state_dates_accurately() -> None:
    request = StaffingRequest(text="Can you find an ICU nurse for St. Mary's next week?")
    system = str(build_initial_messages(request, date(2026, 10, 2), 5)[0].content)

    assert "Today is 2026-10-02." in system
    assert "say plainly when none falls on the requested dates" in system
    assert "never describe a shift as matching dates it does not" in system
