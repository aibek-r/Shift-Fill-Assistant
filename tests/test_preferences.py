"""Structured shift preferences: soft, recorded signals that are never quoted or used as blockers.

SHF-1001 is a night shift and SHF-1003 a day shift (both St. Mary's ICU).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shift_assistant.domain.eligibility import CheckCode, Finding
from shift_assistant.domain.models import Clinician
from shift_assistant.reliability.reporting import rule_ranked
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.facts import PeriodFit, candidate_rationale
from shift_assistant.tools.outreach import render_outreach
from shift_assistant.tools.registry import ToolRegistry
from shift_assistant.tools.schemas import CandidateEvaluation, OutreachDraft
from shift_assistant.tools.toolkit import StaffingToolkit
from tests.conftest import DATA_DIR


def clinician(repository: StaffingRepository, clinician_id: str) -> Clinician:
    found = repository.clinician(clinician_id)
    assert found is not None
    return found


def evaluate(
    toolkit: StaffingToolkit, repository: StaffingRepository, cid: str, sid: str
) -> CandidateEvaluation:
    shift = repository.shift(sid)
    assert shift is not None
    return toolkit.evaluate(shift, clinician(repository, cid))


def draft(toolkit: StaffingToolkit, repository: StaffingRepository, cid: str, sid: str) -> str:
    shift = repository.shift(sid)
    assert shift is not None
    rendered: OutreachDraft = render_outreach(
        toolkit.summarize(shift),
        clinician(repository, cid),
        "Would you be interested in this shift?",
    )
    return rendered.body


@pytest.mark.parametrize(
    ("clinician_id", "preference", "open_to"),
    [
        ("C-101", "night", []),  # "Strongly prefers night shifts"
        ("C-102", None, ["night"]),  # "Open to night and weekend shifts" (weekends out of scope)
        ("C-107", "day", ["night"]),  # "Prefers day shifts but is open to occasional nights"
        ("C-117", None, ["night"]),  # "available for nights"
        ("C-112", None, []),  # no preference stated
    ],
)
def test_fixtures_record_only_what_profiles_state(
    repository: StaffingRepository, clinician_id: str, preference: str | None, open_to: list[str]
) -> None:
    record = clinician(repository, clinician_id)

    assert (record.shift_preference, record.open_to) == (preference, open_to)


@pytest.mark.parametrize(
    ("preference", "open_to"),
    [("evening", []), ("night", ["night"]), (None, ["day", "day"])],
)
def test_preference_fields_are_validated(preference: str | None, open_to: list[str]) -> None:
    raw = json.loads((DATA_DIR / "clinicians.json").read_text(encoding="utf-8"))[0]

    with pytest.raises(ValidationError):
        Clinician.model_validate(raw | {"shift_preference": preference, "open_to": open_to})


@pytest.mark.parametrize(
    ("clinician_id", "shift_id", "fit", "rationale", "outreach"),
    [
        # Absent: nothing is claimed.
        ("C-112", "SHF-2001", None, None, None),
        # Matching preference.
        (
            "C-101",
            "SHF-1001",
            "prefers_night",
            "Self-reported: prefers night shifts.",
            "Your profile says you prefer night shifts.",
        ),
        (
            "C-107",
            "SHF-1003",
            "prefers_day",
            "Self-reported: prefers day shifts.",
            "Your profile says you prefer day shifts.",
        ),
        # Explicitly flexible: openness to the offered period, not the day preference.
        (
            "C-107",
            "SHF-1001",
            "open_to_night",
            "Self-reported: is open to night shifts.",
            "Your profile says you are open to night shifts.",
        ),
        # Conflicting: a day preference on a night shift is not mentioned at all.
        ("C-103", "SHF-1001", None, None, None),
    ],
)
def test_only_a_matching_preference_or_openness_is_mentioned(
    toolkit: StaffingToolkit,
    repository: StaffingRepository,
    clinician_id: str,
    shift_id: str,
    fit: str | None,
    rationale: str | None,
    outreach: str | None,
) -> None:
    evaluation = evaluate(toolkit, repository, clinician_id, shift_id)
    explanation = candidate_rationale(evaluation)
    body = draft(toolkit, repository, clinician_id, shift_id)

    assert evaluation.period_fit == fit
    if rationale is None or outreach is None:
        assert "Self-reported" not in explanation
        assert "Your profile says" not in body
        assert "prefer" not in body and "open to" not in body
    else:
        assert rationale in explanation and outreach in body
    record = clinician(repository, clinician_id)
    assert record.profile not in body
    assert not any(sentence.strip() in body for sentence in record.profile.split(".") if sentence)


def test_preferences_never_decide_eligibility(
    toolkit: StaffingToolkit, repository: StaffingRepository
) -> None:
    grace = evaluate(toolkit, repository, "C-107", "SHF-1001")  # prefers days, night shift
    patched = clinician(repository, "C-101").model_copy(
        update={"shift_preference": "day", "open_to": []}
    )
    shift = repository.shift("SHF-1001")
    assert shift is not None

    assert grace.eligible
    assert toolkit.evaluate(shift, patched).eligible  # a conflicting preference is no blocker


def _evaluation(
    cid: str, years: int, fit: PeriodFit | None, warnings: int = 0
) -> CandidateEvaluation:
    return CandidateEvaluation(
        shift_id="SHF-1",
        clinician_id=cid,
        clinician_name=cid,
        eligible=True,
        blockers=[],
        warnings=[Finding(code=CheckCode.CREDENTIAL_EXPIRING_SOON, message="m")] * warnings,
        years_experience=years,
        period_fit=fit,
    )


def test_fallback_uses_preference_only_as_the_last_tie_breaker() -> None:
    ranked = rule_ranked(
        [
            _evaluation("none", 5, None),
            _evaluation("open", 5, "open_to_night"),
            _evaluation("prefers", 5, "prefers_night"),
            _evaluation("senior", 6, None),  # experience outranks preference
            _evaluation("warned", 9, "prefers_night", warnings=1),  # warnings outrank both
        ]
    )

    assert [e.clinician_id for e in ranked] == ["senior", "prefers", "open", "none", "warned"]


def test_the_model_sees_structured_fields_not_extracted_quotes(registry: ToolRegistry) -> None:
    search = json.loads(registry.execute("search_clinicians", {"shift_id": "SHF-1001"}).content)
    evaluation = json.loads(
        registry.execute(
            "evaluate_candidates", {"shift_id": "SHF-1001", "clinician_ids": ["C-107"]}
        ).content
    )

    grace = next(c for c in search["candidates"] if c["clinician_id"] == "C-107")
    assert (grace["shift_preference"], grace["open_to"]) == ("day", ["night"])
    assert evaluation["evaluations"][0]["period_fit"] == "open_to_night"
    assert "preference_quotes" not in evaluation["evaluations"][0]
