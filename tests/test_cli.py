"""The CLI answers through the front door. Offline: the API key is blanked and search uses the
keyword embedder, so no paid call or model download happens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shift_assistant import templates
from shift_assistant.cli import main
from shift_assistant.retrieval.embedder import HashingEmbedder

ICU_REQUEST = "Find two ICU nurses for the St. Mary's night shift on October 14."


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")  # the environment beats .env
    monkeypatch.setenv("REFERENCE_DATE", "2026-10-02")
    monkeypatch.setattr(
        "shift_assistant.assistant.create_embedder", lambda *args, **kwargs: HashingEmbedder()
    )


def test_greeting_prints_the_help_template(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["hi"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith(templates.HELP)
    assert f"Try:\n- {ICU_REQUEST}" in out.out
    assert "keyword routing" in out.err


def test_off_topic_json_has_no_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["What is the weather today?", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "out_of_scope" and payload["reason"] == "off_topic"
    assert payload["report"] is None and payload["routing"]["method"] == "keywords"


def test_staffing_request_prints_and_saves_the_report(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    saved = tmp_path / "response.json"
    assert main([ICU_REQUEST, "--save", str(saved)]) == 0
    assert capsys.readouterr().out.startswith("# Staffing report")
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["kind"] == "staffing_report"
    assert payload["report"]["status"] == "ready"
    assert payload["report"]["shift"]["shift_id"] == "SHF-1001"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["x" * 2001], "Your message is too long. Please keep it under 2,000 characters."),
        (["x" * 10_000], "Your message is too long. Please keep it under 2,000 characters."),
        (["Find two nurses", "--date", "soon"], "The date must look like 2026-10-14."),
    ],
)
def test_invalid_input_gets_a_friendly_error(
    capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(args)
    assert exited.value.code == 2
    err = capsys.readouterr().err
    assert message in err and "validation error" not in err


def test_policy_answer_quotes_the_section_with_its_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["Where do agency nurses park at St. Mary's?"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("From the St. Mary's Medical Center policies (Parking and arrival):")
    assert "> Agency clinicians park in Garage C on 38th Street." in out
    assert "Source: FAC-001#parking-and-arrival" in out


def test_shift_answer_prints_a_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["Any open night shifts at St. Mary's?"]) == 0
    out = capsys.readouterr().out
    assert "| Shift | Facility | Unit | Date | Time | Day/night | Open places |" in out
    assert "| SHF-1001 | St. Mary's Medical Center | ICU | Wed, Oct 14 |" in out


def test_declined_parts_are_printed_before_the_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["Find ICU nurses for Oct 14 and what's the weather?"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Note: I can't help with the weather.\n\n# Staffing report")
