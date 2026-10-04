"""The evaluation harness runs end to end offline and never builds a real model."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from evals.cases import CASES
from evals.run import main, run_case
from shift_assistant.contracts import ReportStatus
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import HashingEmbedder


def forbid_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("the offline harness must not build a real chat model")

    monkeypatch.setattr("shift_assistant.agent.llm.ChatOpenAI", forbidden)


def test_offline_harness_runs_every_case_on_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_real_model(monkeypatch)

    exit_code = main(["--output", str(tmp_path)])

    (results,) = tmp_path.glob("*.md")
    text = results.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "| agent (scripted model) | fallback |" in text
    passed = f"{len(CASES)}/{len(CASES)}"
    assert f"| Runs passed (all checks) | {passed} | {passed} |" in text
    assert "| Token usage | unavailable (no model call reported usage) |" in text
    assert "not live model reasoning" in text
    assert "not proof of general prompt-injection resistance" in text


def test_a_wrong_expectation_is_reported_as_a_failure(repository: StaffingRepository) -> None:
    case = CASES[0]
    wrong = replace(case, expected=replace(case.expected, status=ReportStatus.PARTIAL))

    results = list(run_case(wrong, repository, HashingEmbedder(), live=False))

    assert results and not any(r.passed for r in results)
    assert all(r.checks["status"] is False for r in results)


def test_live_mode_requires_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")  # the environment overrides any .env key
    forbid_real_model(monkeypatch)

    assert main(["--live", "--output", str(tmp_path)]) == 2
    assert "--live needs OPENAI_API_KEY" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
