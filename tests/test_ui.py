"""Real Streamlit widgets and callbacks, exercised headlessly without paid model calls."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from shift_assistant.config import PROJECT_ROOT
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.review import DraftStatus


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


@pytest.mark.parametrize("invalid", ["", "x"])
def test_invalid_submissions_clear_previous_results(app: AppTest, invalid: str) -> None:
    run_icu(app)
    app.text_area(key="request_text").set_value(invalid)
    click(app, "Run assistant")
    assert "report" not in app.session_state and "review" not in app.session_state
    assert not app.json and not app.code
    assert app.warning or app.error
