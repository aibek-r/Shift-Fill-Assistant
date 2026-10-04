"""Conservative extraction of explicit shortlist and outreach instructions.

This handles common count phrases, not arbitrary natural language. API callers can set the
typed request fields explicitly when a request uses other wording.
"""

from __future__ import annotations

import re

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
