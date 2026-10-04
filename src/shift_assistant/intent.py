"""Conservative extraction of explicit shortlist, outreach, date and unit instructions.

This handles common phrases, not arbitrary natural language. API callers can set the typed
request fields explicitly (shortlist size, outreach, facility, unit, start date) when a request
uses other wording; typed fields always win over the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from shift_assistant.domain.models import Unit


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


_MONTH_NUMBERS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
# Longest names first; "May" must be capitalized so the verb "may" is not read as a month.
_MONTH_NAMES = [
    "(?-i:May)" if name == "may" else name for name in sorted(_MONTH_NUMBERS, key=len, reverse=True)
]
_MONTH = "(?P<month>" + "|".join(_MONTH_NAMES) + r")\.?"
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s+(?P<year>\d{4}))?"
_EXPLICIT_DATES = [
    re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b"),  # 2026-10-14
    re.compile(rf"\b{_MONTH}\s+{_DAY}\b{_YEAR}", re.IGNORECASE),  # Oct 14, October 14th, 2026
    re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH}\b{_YEAR}", re.IGNORECASE),  # 14 October
    # 10/14 or 10/14/2026, month first. Out-of-range pairs such as "24/7" are not dates.
    re.compile(r"\b(?P<month>0?[1-9]|1[0-2])/(?P<day>0?[1-9]|[12]\d|3[01])(?:/(?P<year>\d{4}))?\b"),
]


@dataclass(frozen=True)
class RequestedDates:
    """Facility-local shift start dates a request names: explicit dates and/or a relative window.

    Yearless dates take the reference year and are never rolled into the next year: one that has
    already passed is reported in `past`, so the caller can ask instead of guessing.
    """

    dates: frozenset[date] = frozenset()
    window: RelativeDateWindow | None = None
    past: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()
    mentions: tuple[str, ...] = ()

    @property
    def given(self) -> bool:
        return bool(self.dates or self.window or self.past or self.invalid)

    def contains(self, day: date) -> bool:
        return day in self.dates or (self.window is not None and self.window.contains(day))

    @property
    def label(self) -> str:
        parts = [d.isoformat() for d in sorted(self.dates)]
        if self.window is not None:
            parts.append(self.window.label)
        return " or ".join(parts)


def requested_dates(text: str, today: date) -> RequestedDates:
    dates: set[date] = set()
    past: list[str] = []
    invalid: list[str] = []
    mentions: list[str] = []
    spans: list[tuple[int, int]] = []
    for pattern in _EXPLICIT_DATES:
        for match in pattern.finditer(text):
            if any(start < match.end() and match.start() < end for start, end in spans):
                continue  # already read by an earlier, more specific pattern
            spans.append(match.span())
            mention = match.group(0).strip()
            mentions.append(mention)
            month = match.group("month").lower().rstrip(".")
            year = match.group("year")
            try:
                day = date(
                    int(year) if year else today.year,
                    int(month) if month.isdigit() else _MONTH_NUMBERS[month],
                    int(match.group("day")),
                )
            except ValueError:
                invalid.append(mention)
                continue
            if year is None and day < today:
                past.append(f"{mention} ({day.isoformat()})")
            else:
                dates.add(day)
    return RequestedDates(
        dates=frozenset(dates),
        window=relative_date_window(text, today),
        past=tuple(past),
        invalid=tuple(invalid),
        mentions=tuple(mentions),
    )


# A small, documented synonym list per unit; no fuzzy matching. Pediatric and neonatal phrases
# are excluded from the adult ICU pattern.
_UNIT_PATTERNS: list[tuple[Unit, re.Pattern[str]]] = [
    (Unit.PICU, re.compile(r"\bpicu\b|\bpediatric\s+(?:icu|intensive\s+care)\b", re.I)),
    (Unit.NICU, re.compile(r"\bnicu\b|\bneonatal\s+(?:icu|intensive\s+care)\b", re.I)),
    (
        Unit.ICU,
        re.compile(r"(?<!pediatric )(?<!neonatal )\b(?:icu|intensive\s+care)\b", re.I),
    ),
    (Unit.ED, re.compile(r"\b(?:ED|ER)\b|\b(?i:emergency(?:\s+(?:department|room))?)\b")),
    (Unit.TELEMETRY, re.compile(r"\btele(?:metry)?\b", re.I)),
    (Unit.MED_SURG, re.compile(r"\bmed[-\s]?surg\b|\bmedical[-\s]surgical\b", re.I)),
]


def requested_units(text: str) -> frozenset[Unit]:
    return frozenset(unit for unit, pattern in _UNIT_PATTERNS if pattern.search(text))


def requested_period(text: str) -> str | None:
    """'day' or 'night' when the request names exactly one, as in 'the night shift'."""
    periods = {p.lower() for p in re.findall(r"\b(day|night)\s+shift\b", text, re.IGNORECASE)}
    return periods.pop() if len(periods) == 1 else None


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
