"""Render supported candidate facts without promoting model prose to evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from shift_assistant.domain.models import ShiftPeriod
    from shift_assistant.tools.schemas import CandidateEvaluation

PeriodFit = Literal["prefers_day", "prefers_night", "open_to_day", "open_to_night"]
"""How a clinician's structured preferences relate to the offered shift's period."""

_FIT_PHRASES: dict[PeriodFit, str] = {
    "prefers_day": "prefers day shifts",
    "prefers_night": "prefers night shifts",
    "open_to_day": "is open to day shifts",
    "open_to_night": "is open to night shifts",
}

# Coordinator edits and model notes select neutral wording. Facts are added separately by code.
# This finite vocabulary intentionally rejects unverifiable pay, logistics and qualifications.
FRIENDLY_NOTES = (
    "We would love to have you on this shift.",
    "Would you be interested in this shift?",
    "Thank you for considering this opportunity.",
    "We would be happy to discuss this opportunity with you.",
    "We think you would fit this unit well.",
)
DEFAULT_NOTE = FRIENDLY_NOTES[0]


def period_fit(
    shift_preference: ShiftPeriod | None, open_to: Sequence[ShiftPeriod], period: str
) -> PeriodFit | None:
    """Only a matching preference or explicit openness to the offered period counts.

    A preference for the other period is not support for the match, so it yields None.
    """
    if shift_preference == period:
        return "prefers_day" if period == "day" else "prefers_night"
    if period in open_to:
        return "open_to_day" if period == "day" else "open_to_night"
    return None


def period_fit_phrase(fit: PeriodFit) -> str:
    return _FIT_PHRASES[fit]


def validate_personal_note(note: str) -> None:
    sentences = re.split(r"(?<=[.!?])\s+", note.strip())
    allowed = {sentence.casefold() for sentence in FRIENDLY_NOTES}
    if not 1 <= len(sentences) <= 3 or any(s.casefold() not in allowed for s in sentences):
        raise ValueError(
            "Use 1-3 approved friendly sentences from the note suggestions. "
            "Qualifications, preferences, pay and logistics cannot be entered in the note; "
            "recorded facts are added automatically."
        )


def candidate_rationale(evaluation: CandidateEvaluation) -> str:
    facts = ["Passed the recorded compliance checks for this shift."]
    if evaluation.years_experience is not None:
        facts.append(f"Recorded experience: {evaluation.years_experience} years.")
    if evaluation.period_fit is not None:
        facts.append(f"Self-reported: {period_fit_phrase(evaluation.period_fit)}.")
    facts.extend(w.message for w in evaluation.warnings)
    return " ".join(facts)
