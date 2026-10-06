"""Real Streamlit widgets and callbacks, exercised headlessly without paid model calls."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import streamlit as st
from langchain_core.runnables import RunnableLambda
from streamlit.testing.v1 import AppTest

from shift_assistant.config import PROJECT_ROOT
from shift_assistant.contracts import StaffingRequest
from shift_assistant.domain.models import Clinician, Shift
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.review import DraftStatus
from shift_assistant.tools.schemas import CandidateEvaluation
from shift_assistant.tools.toolkit import StaffingToolkit
from tests.conftest import ScriptedModel, ai, tool_call


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Iterator[AppTest]:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("REFERENCE_DATE", "2026-10-02")
    monkeypatch.setattr(
        "shift_assistant.retrieval.embedder.create_embedder",
        lambda *args, **kwargs: HashingEmbedder(),
    )
    st.cache_resource.clear()
    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "streamlit_app.py"), default_timeout=20).run()
    assert not at.exception
    yield at
    st.cache_resource.clear()


def click(app: AppTest, label: str) -> None:
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


ICU_TEXT = "Find two ICU nurses for the St. Mary's night shift on October 14."


def run_icu(app: AppTest) -> None:
    app.selectbox[0].set_value("SHF-1001")
    app.text_area(key="request_text").set_value("Find two ICU nurses and draft outreach")
    click(app, "Run assistant")


def test_ui_export_tracks_edits_and_approval(app: AppTest) -> None:
    run_icu(app)
    review = app.session_state["review"]
    draft_id = app.session_state["report"].recommendations[0].outreach.draft_id
    click(app, "Approve message")
    assert json.loads(app.json[0].value)["outreach_review"]["approvals"][0]["status"] == "approved"
    click(app, "Edit note")
    note = "Thank you for considering this opportunity."
    key = f"note-{review.run_id}-{draft_id}"
    app.text_area(key=key).set_value(note)
    click(app, "Save note")
    exported = json.loads(app.json[0].value)
    assert exported["recommendations"][0]["outreach"]["personal_note"] == note
    assert note in app.code[0].value
    assert exported["outreach_review"]["approvals"][0]["status"] == "pending"
    click(app, "Approve message")
    assert review[draft_id].status is DraftStatus.APPROVED
    click(app, "Edit note")
    app.text_area(key=key).set_value("The pay is ninety five dollars each hour.")
    click(app, "Save note")
    assert app.error and review[draft_id].draft.personal_note == note
    assert json.loads(app.json[0].value)["outreach_review"]["approvals"][0]["status"] == "editing"
    click(app, "Cancel")
    click(app, "Edit note")
    assert app.text_area(key=key).value == note  # rejected text never reappears


def test_note_editor_lists_problems_keeps_text_and_offers_suggestions(app: AppTest) -> None:
    run_icu(app)
    review = app.session_state["review"]
    draft_id = app.session_state["report"].recommendations[0].outreach.draft_id
    saved = review[draft_id].draft.personal_note
    key = f"note-{review.run_id}-{draft_id}"
    click(app, "Edit note")

    rejected = "We would like to have you on this shift. It is $55/hour."
    app.text_area(key=key).set_value(rejected)
    click(app, "Save note")

    assert review[draft_id].problems == ('Remove "$55/hour": pay can\'t appear in outreach.',)
    assert any("Note not saved" in e.value and r"\$55/hour" in e.value for e in app.error)
    assert app.text_area(key=key).value == rejected  # kept so the coordinator can fix it
    exported = json.loads(app.json[0].value)
    assert exported["recommendations"][0]["outreach"]["personal_note"] == saved
    assert "$55" not in app.json[0].value  # rejected text is never saved or exported

    app.text_area(key=key).set_value("We would like to have you on this shift.")
    click(app, "Thank you for considering this opportunity.")  # one-click suggestion
    own_words = (
        "We would like to have you on this shift. Thank you for considering this opportunity."
    )
    assert app.text_area(key=key).value == own_words
    click(app, "Save note")
    assert review[draft_id].status is DraftStatus.PENDING
    assert review[draft_id].draft.personal_note == own_words
    assert own_words in app.code[0].value

    click(app, "Edit note")
    app.text_area(key=key).set_value("Maria Santos will join you.")
    click(app, "Cancel")  # restores the saved note
    assert review[draft_id].draft.personal_note == own_words
    assert app.session_state[key] == own_words


def test_shift_and_mode_changes_clear_results_and_approvals(app: AppTest) -> None:
    run_icu(app)
    click(app, "Approve message")
    previous_run = app.session_state["review"].run_id
    app.selectbox[0].set_value("SHF-3001").run()
    assert "report" not in app.session_state and "review" not in app.session_state
    app.text_area(key="request_text").set_value("Give me a shortlist of two PICU nurses")
    click(app, "Run assistant")
    assert app.session_state["report"].status == "ready"
    assert len(app.session_state["report"].recommendations) == 2
    assert app.session_state["review"].run_id != previous_run
    app.toggle[0].set_value(True).run()
    assert "report" not in app.session_state and "review" not in app.session_state


def page_order(app: AppTest) -> list[tuple[str, str]]:
    """(type, value) of every element on the main page, in display order."""
    order: list[tuple[str, str]] = []

    def walk(node: object) -> None:
        order.append((str(getattr(node, "type", "")), str(getattr(node, "value", ""))))
        for child in getattr(node, "children", {}).values():
            walk(child)

    walk(app.main)
    return order


def position(order: list[tuple[str, str]], kind: str, starts_with: str = "") -> int:
    return next(i for i, (t, v) in enumerate(order) if t == kind and v.startswith(starts_with))


def assert_one_answer_below_the_form(app: AppTest) -> None:
    order = page_order(app)
    title = position(order, "title", "Shift Fill Assistant")
    subtitle = position(order, "markdown", "Find eligible clinicians.")
    assert title < subtitle < position(order, "form") < position(order, "chat_message")
    assert [m.name for m in app.chat_message] == ["assistant"]  # no user bubble, no history


@pytest.mark.parametrize(
    ("message", "answer"),
    [
        ("What can you do?", "I'm the Shift Fill Assistant."),  # help
        ("What's the weather like today?", "Sorry, I can't help with that."),  # refusal
        ("asdf qwerty", "Sorry, I'm not sure what you need."),  # clarification
        (ICU_TEXT, "**Shortlist ready:**"),  # staffing report
    ],
)
def test_answer_appears_below_the_form_and_keeps_the_typed_text(
    app: AppTest, message: str, answer: str
) -> None:
    assert not app.chat_message  # nothing to answer yet
    app.text_area(key="request_text").set_value(message)
    click(app, "Run assistant")

    assert_one_answer_below_the_form(app)
    shown = app.chat_message[0]
    assert any(e.value.startswith(answer) for e in [*shown.markdown, *shown.success])
    assert app.text_area(key="request_text").value == message


@pytest.mark.parametrize(
    ("message", "reply"),
    [
        ("", "I'm the Shift Fill Assistant."),  # empty text gets the help reply
        ("x", "Do you want me to find nurses for the shift you selected?"),  # SHF-1001 is pinned
    ],
)
def test_a_new_answer_replaces_the_previous_one(app: AppTest, message: str, reply: str) -> None:
    run_icu(app)
    app.text_area(key="request_text").set_value(message)
    click(app, "Run assistant")
    assert "report" not in app.session_state and "review" not in app.session_state
    assert not app.json and not app.code  # the staffing report is gone, not stacked
    assert_one_answer_below_the_form(app)
    assert reply in app.chat_message[0].markdown[0].value


def test_answer_stays_through_reruns_from_its_own_buttons(app: AppTest) -> None:
    run_icu(app)
    response = app.session_state["response"]
    click(app, "Approve message")
    click(app, "Edit note")
    click(app, "Cancel")

    assert app.session_state["response"] is response
    assert_one_answer_below_the_form(app)
    assert app.json and app.code  # the full staffing report is still on screen
    assert app.text_area(key="request_text").value == "Find two ICU nurses and draft outreach"


def test_too_long_message_shows_a_friendly_error(app: AppTest) -> None:
    run_icu(app)
    app.text_area(key="request_text").set_value("x" * 2001)
    click(app, "Run assistant")
    assert any("Your message is too long" in e.value for e in app.error)
    assert "report" not in app.session_state and "review" not in app.session_state
    assert "response" not in app.session_state and not app.chat_message


def test_example_buttons_fill_the_form_without_a_user_bubble(app: AppTest) -> None:
    app.text_area(key="request_text").set_value("What can you do?")
    click(app, "Run assistant")
    example = "Find two ICU nurses for the St. Mary's night shift on October 14."
    click(app, example)  # an example button in the help answer
    assert app.text_area(key="request_text").value == example
    assert not app.chat_message  # the old answer is cleared; nothing echoes the text

    click(app, "Off-topic question")  # a sidebar example
    assert app.text_area(key="request_text").value == "What's the weather like today?"
    assert not app.chat_message
    click(app, "Run assistant")
    assert_one_answer_below_the_form(app)


def test_templates_answer_without_a_model(app: AppTest, monkeypatch: pytest.MonkeyPatch) -> None:
    model = ScriptedModel([])
    monkeypatch.setattr(
        "shift_assistant.assistant.build_chat_model", lambda *args: RunnableLambda(model)
    )
    st.cache_resource.clear()
    app.text_area(key="request_text").set_value("hi")
    click(app, "Run assistant")
    assert app.chat_message[0].markdown[0].value.startswith("Hi! I'm the Shift Fill Assistant.")

    click(app, "Off-topic question")
    click(app, "Run assistant")
    assert app.chat_message[0].markdown[0].value.startswith("Sorry, I can't help with that.")
    assert model.received == []  # templates only: no model call

    click(app, "New conversation")
    assert not app.chat_message and "response" not in app.session_state


def test_facility_choice_preserves_dates_count_and_outreach_intent(
    app: AppTest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedModel(
        [
            ai(tool_call("find_open_shifts", facility="Mercy General")),
            ai(
                tool_call(
                    "submit_recommendation",
                    status="needs_clarification",
                    summary="The requested facility is unknown.",
                    clarification_question=(
                        "Which facility did you mean: St. Mary's Medical Center, "
                        "Lakeside Community Hospital, or Bayview Children's Hospital?"
                    ),
                )
            ),
        ]
    )
    monkeypatch.setattr(
        "shift_assistant.assistant.build_chat_model", lambda *args: RunnableLambda(model)
    )
    st.cache_resource.clear()
    app.text_area(key="request_text").set_value(
        "Find two ICU nurses for Mercy General tomorrow night without outreach."
    )
    click(app, "Run assistant")
    assert any(h.value == "Choose a facility" for h in app.subheader)
    assert len([b for b in app.button if b.label == "Use this facility"]) == 3
    app.button(key="clarify-FAC-001").click().run()
    assert not app.exception
    assert app.text_area(key="request_text").value == (
        "Find two ICU nurses for St. Mary's Medical Center tomorrow night without outreach."
    )
    updated = StaffingRequest(text=app.text_area(key="request_text").value)
    assert updated.requested_count == 2 and not updated.draft_outreach
    assert "report" not in app.session_state and "review" not in app.session_state
    assert app.selectbox[0].value is None
    assert len(model.received) == 2  # Choosing a facility prepares the form without a model call.


def test_needs_review_and_code_additions_are_labelled(
    app: AppTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = ScriptedModel(
        [
            ai(tool_call("find_open_shifts", shift_id="SHF-1001")),
            ai(tool_call("search_clinicians", shift_id="SHF-1001")),
            ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=["C-107"])),
            ai(
                tool_call(
                    "submit_recommendation",
                    status="completed",
                    shift_id="SHF-1001",
                    recommendations=[
                        {"clinician_id": "C-107", "rationale": "Eligible per the evaluation."}
                    ],
                    summary="Grace Liu fits the ICU night shift.",
                )
            ),
        ]
    )
    original = StaffingToolkit.evaluate

    def evaluate(self: StaffingToolkit, shift: Shift, clinician: Clinician) -> CandidateEvaluation:
        if clinician.id == "C-103":
            raise RuntimeError("check unavailable")
        return original(self, shift, clinician)

    monkeypatch.setattr(StaffingToolkit, "evaluate", evaluate)
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "0")
    monkeypatch.setattr(
        "shift_assistant.assistant.build_chat_model", lambda *args: RunnableLambda(model)
    )
    st.cache_resource.clear()
    app.text_area(key="request_text").set_value(
        "Find two ICU nurses for St. Mary's on Oct 14 and draft outreach"
    )
    click(app, "Run assistant")

    report = app.session_state["report"]
    assert report.status == "needs_review"
    assert any(w.value.startswith("**Needs review:**") for w in app.warning)
    captions = [c.value for c in app.caption]
    assert any(c.endswith("Selected by the AI agent") for c in captions)
    assert any(c.endswith("Selected by rules") for c in captions)
    assert "Drafted by rules from the standard template." in captions
    assert any("Completed by rules" in m.value for m in app.markdown)


def test_example_choice_clears_a_conflicting_pin(app: AppTest) -> None:
    run_icu(app)
    click(app, "PICU shortlist")
    assert app.selectbox[0].value is None
    assert "Bayview" in (app.text_area(key="request_text").value or "")
    assert "report" not in app.session_state and "review" not in app.session_state
