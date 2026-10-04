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
