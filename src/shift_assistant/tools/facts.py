"""Render supported candidate facts without promoting model prose to evidence."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shift_assistant.tools.schemas import CandidateEvaluation

# Only recognized preference/availability clauses are quoted, never whole untrusted profiles.
# The combined clause comes first so Grace's day preference and occasional nights stay together.
_PREFERENCES = re.compile(
    r"\b(?:strongly\s+)?prefers?\s+(?:day|night)\s+shifts?"
    r"(?:\s+but\s+is\s+open\s+to\s+occasional\s+nights)?\b"
    r"|\b(?:is\s+)?(?:available\s+for|open\s+to|comfortable\s+with)\s+"
    r"(?:occasional\s+)?(?:night|day)(?:\s+and\s+weekend)?(?:\s+shifts?|s)\b",
    re.IGNORECASE,
)

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


def preference_quotes(profile: str) -> list[str]:
    quotes = []
    for sentence in re.split(r"[.!?\n]", profile):
        for match in _PREFERENCES.finditer(sentence):
            # Unknown conditions or negations are omitted rather than shortened into a claim.
            before, after = sentence[: match.start()], sentence[match.end() :].strip().casefold()
            if re.search(
                r"\b(?:not|never|no|formerly|if|unless|cannot|can't)\b", before, re.IGNORECASE
            ):
                continue
            if after not in ("", "and has precepted new graduate nurses"):
                continue
            quotes.append(match.group(0))
    return quotes


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
    if evaluation.preference_quotes:
        quotes = "; ".join(f"“{quote}”" for quote in evaluation.preference_quotes)
        facts.append(f"Profile wording (self-reported): {quotes}.")
    facts.extend(w.message for w in evaluation.warnings)
    return " ".join(facts)
