"""Conservative extraction of explicit shortlist, outreach and relative-date instructions.

This handles common phrases, not arbitrary natural language. API callers can set the typed
request fields explicitly for shortlist size and outreach when a request uses other wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class RelativeDateWindow:
    phrase: str
    start: date
    end: date

    @property
    def label(self) -> str:
        return f"{self.phrase} ({self.start.isoformat()} to {self.end.isoformat()})"

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def relative_date_window(text: str, today: date) -> RelativeDateWindow | None:
    """Resolve common explicit relative dates; weeks run Monday through Sunday.

    Multiple different expressions stay with the model for clarification rather than guessing.
    Dates refer to the shift's facility-local start date, as in find_open_shifts.
    """
    phrases = set(re.findall(r"\b(?:today|tomorrow|this week|next week)\b", text.lower()))
    if len(phrases) != 1:
        return None
    phrase = phrases.pop()
    if phrase in {"today", "tomorrow"}:
        day = today + timedelta(days=phrase == "tomorrow")
        return RelativeDateWindow(phrase, day, day)
    monday = today - timedelta(days=today.weekday())
    start = monday + timedelta(days=7 if phrase == "next week" else 0)
    return RelativeDateWindow(phrase, start, start + timedelta(days=6))


_NUMBERS = {
    word: number
    for number, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
}
_COUNT = r"(?:\d+|" + "|".join(_NUMBERS) + r")"
_PATTERNS = [
    rf"\bshortlist\s+(?:of\s+|only\s+)?(?P<count>{_COUNT})\b",
    rf"\b(?:find|recommend|select|return|give me)\s+(?:only\s+|exactly\s+)?(?P<count>{_COUNT})\b",
    rf"\b(?P<count>{_COUNT})\s+(?:(?:eligible|ICU|PICU|NICU|ED|night|day)\s+)*(?:nurses?|clinicians?|candidates?)\b",
]


def requested_count(text: str) -> int | None:
    for pattern in _PATTERNS:
        if match := re.search(pattern, text, re.IGNORECASE):
            value = match.group("count").lower()
            return int(value) if value.isdigit() else _NUMBERS[value]
    return None


def wants_outreach(text: str) -> bool:
    return not bool(
        re.search(
            r"\b(?:do not|don't|without|no|skip|omit)\s+(?:draft\s+|drafting\s+|any\s+)?"
            r"(?:outreach|messages?|drafts?)\b",
            text,
            re.IGNORECASE,
        )
    )
