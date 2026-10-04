"""Deterministic content rules for the personal note in an outreach draft.

The note is the only free text in a draft; code adds recorded experience, a matching shift
preference, shift details, credential reminders and the reply deadline separately. The model and
coordinators may write the note in their own words, but it must not carry facts of its own. The
same check runs for both, server-side, before any draft is created or saved.

This is a guardrail, not a guarantee: fixed patterns catch common unsafe content (pay, numbers,
contact details, other clinicians, qualifications, claims, logistics, promises) and can miss
paraphrases. A coordinator's approval of each draft stays the final check.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# One-click suggestions in the editor, and safe defaults. Every one passes the rules below.
FRIENDLY_NOTES = (
    "We would love to have you on this shift.",
    "Would you be interested in this shift?",
    "Thank you for considering this opportunity.",
    "We would be happy to discuss this opportunity with you.",
    "We think you would fit this unit well.",
)
DEFAULT_NOTE = FRIENDLY_NOTES[0]

MAX_NOTE_CHARS = 400
MAX_NOTE_SENTENCES = 4


@dataclass(frozen=True)
class NoteViolation:
    text: str  # the exact offending text; empty for length and sentence-count problems
    reason: str

    @property
    def message(self) -> str:
        return f'Remove "{self.text}": {self.reason}.' if self.text else f"{self.reason}."


def _words(*words: str) -> str:
    return r"\b(?:" + "|".join(words) + r")\b"


_NUMBER_WORDS = _words(
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "thousand", "dozen",
)  # fmt: skip
# "May" is left out: as a verb it is far more common in a note than the month.
_MONTHS = (
    r"\b(?:january|february|march|april|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?(?:\s+\d{1,2}(?:st|nd|rd|th)?)?\b"
)
_WEEKDAYS = _words("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_RELATIVE = (
    _words("today", "tonight", "tomorrow", "yesterday", "noon", "midnight", "o'clock")
    + r"|\b(?:this|next|coming)\s+(?:week|weekend|month)\b"
)

# Checked in this order, so the first rule names the problem: "$55/hour" is reported as pay,
# not as a number. A match that lies entirely inside an earlier one is not reported again.
_CONTACT = (
    "contact details can't appear in outreach",
    re.compile(
        r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"  # email
        r"|\b(?:https?://|www\.)\S*[^\s.,;:!?)]"  # URL, without trailing punctuation
        r"|\b[\w-]+\.(?:com|org|net|io|gov|edu|us|co)\b(?:/\S*[^\s.,;:!?)])?"
        r"|(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"  # US phone
        r"|\+\d[\d\s().-]{7,}\d",  # international phone
        re.IGNORECASE,
    ),
)
_PAY = (
    "pay can't appear in outreach",
    re.compile(
        r"[$€£]\s?\d[\d,]*(?:\.\d+)?k?(?:\s?(?:/|per\s+|an?\s+)(?:hour|hr|h|shift|day|week|night))?"
        r"|\b\d[\d,]*(?:\.\d+)?\s?(?:dollars?|usd|bucks)\b"
        r"|\b\d[\d,]*(?:\.\d+)?\s?(?:/|per\s+|an\s+)(?:hour|hr)\b"
        r"|\bper\s+(?:hour|hr|shift)\b|/\s?hr\b|\btime\s+and\s+a\s+half\b|"
        + _words(
            "pay", "pays", "paid", "paying", "payment", "payments", "rates?", "wages?",
            "salary", "salaries", "bonus", "bonuses", "stipends?", "compensation",
            "incentives?", "overtime", "hourly", "dollars?", "cash", "money", r"reimburs\w*",
        ),
        re.IGNORECASE,
    ),
)  # fmt: skip
_CREDENTIALS = (
    "credentials and qualifications come from verified records, not the note",
    re.compile(
        r"\b(?:(?:\d+|[a-z]+)\+?\s+)?years?\s+(?:of\s+)?experience\b|"
        + _words(
            "ACLS", "BLS", "PALS", "TNCC", "NRP", "CCRN", "ECMO", "CRRT", "RN", "LPN", "BSN",
            "MSN", "CNA", r"licen[cs]e[sd]?", "licensure", r"certif\w*", r"credentials?",
            r"qualifi\w*", "experienced", "trained", "skilled", r"experts?", "expertise",
            "specialist", r"speciali[sz]\w*",
        ),
        re.IGNORECASE,
    ),
)  # fmt: skip
_TIME = (
    "numbers, dates and times come from the shift record, not the note",
    re.compile(
        "|".join(
            [
                _MONTHS,
                _WEEKDAYS,
                _RELATIVE,
                r"\d+(?:[:.,/-]\d+)*(?:\s?(?:am|pm|a\.m\.|p\.m\.))?",
                _NUMBER_WORDS,
            ]
        ),
        re.IGNORECASE,
    ),
)
_LOGISTICS = (
    "shift logistics come from the facility record, not the note",
    re.compile(
        r"\breport(?:ing)?\s+(?:to|at)\b|\barriv\w*|\bcheck-in\b|\bcheck\s+in\s+at\b"
        r"|\bbring\s+(?:your|a|an)\b|\bdress\s+code\b|"
        + _words(
            "park", "parking", "parked", "garage", "valet", r"badges?", "badging", "entrance",
            "lobby", "elevator", "floor", "orientation", "huddle", r"lockers?", r"uniforms?",
            "scrubs",
        ),
        re.IGNORECASE,
    ),
)  # fmt: skip
_PROMISES = (
    "outreach can't promise bookings, pay or outcomes",
    re.compile(
        r"\blocked\s+in\b|\b(?:the\s+)?shift\s+is\s+yours\b|"
        + _words(
            r"guarantee[sd]?", "booked", "confirmed", "secured", "reserved", r"promise[sd]?",
            "assured",
        ),
        re.IGNORECASE,
    ),
)  # fmt: skip
_CLAIM_REASON = "claims about the clinician can't be verified"
_CLAUSE = r"\b[^.!?;,]*"  # the rest of the clause, so the whole claim is quoted
_APOSTROPHE = "['" + chr(0x2019) + "]"  # straight or typographic, as editors often insert
_CLAIMS = re.compile(
    # "you prefer nights", "you strongly prefer nights", "you have worked here"
    r"\byou\s+(?:\w+ly\s+)?(?:prefer\w*|like[sd]?|lov(?:e|es|ed)|enjoy\w*|want\w*|wish\w*"
    r"|always|usually|often|never|already|regularly|said|told|mentioned|asked|requested"
    r"|indicated|listed|signed|agreed|worked|work|know|had|have\s+(?:\w+ly\s+)?(?:worked|done"
    r"|completed|taken|picked|been|had|shown|experience|a\s+background))"
    + _CLAUSE
    # "you are available", "you're ACLS certified"
    + r"|\byou(?:\s+are|\s+were|"
    + _APOSTROPHE
    + r"re)\s+(?:\w+\s+)?(?:available|open|free|flexible"
    r"|comfortable|ready|willing|certified|licensed|qualified|experienced|trained|skilled"
    r"|eligible|approved|cleared|on\s+file)"
    + _CLAUSE
    # "you've worked nights"
    + r"|\byou"
    + _APOSTROPHE
    + r"ve\s+(?:\w+ly\s+)?(?:\w+ed|been|done|had|shown|always|never)"
    + _CLAUSE
    # "your preference is nights"
    + r"|\byour\s+(?:preferences?|availability|profile|history|record|schedule|background"
    r"|skills?|expertise|experience|certifications?|licen[cs]e)" + _CLAUSE,
    re.IGNORECASE,
)
# A "you" after these words starts a condition or a question, not a claim:
# "if you are available", "would you like this shift?".
_NOT_A_CLAIM_BEFORE = re.compile(
    r"\b(?:if|whether|when|unless|would|could|do|does|did|are|were|will|can|might|may|should"
    r"|have|has|had|shall)\s+$",
    re.IGNORECASE,
)


def note_violations(
    note: str, other_clinicians: Iterable[str] = (), recipient: str = ""
) -> list[NoteViolation]:
    """Every rule the note breaks, quoting the exact text, in the order it appears."""
    text = note.strip()
    if not text:
        return [NoteViolation("", "Write a short note of 1 to 4 sentences")]

    problems: list[NoteViolation] = []
    if len(text) > MAX_NOTE_CHARS:
        problems.append(
            NoteViolation(
                "", f"Shorten the note to {MAX_NOTE_CHARS} characters or fewer (it has {len(text)})"
            )
        )
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if len(sentences) > MAX_NOTE_SENTENCES:
        problems.append(
            NoteViolation(
                "", f"Use at most {MAX_NOTE_SENTENCES} sentences (the note has {len(sentences)})"
            )
        )

    rules = [_CONTACT, _PAY, *_names_rule(other_clinicians, recipient)]
    rules += [_CREDENTIALS, _TIME, _LOGISTICS, _PROMISES, (_CLAIM_REASON, _CLAIMS)]
    found: list[tuple[int, int, NoteViolation]] = []
    for reason, pattern in rules:
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            quoted = match.group(0).strip()
            if not quoted or any(s <= start and end <= e for s, e, _ in found):
                continue
            if reason == _CLAIM_REASON and _NOT_A_CLAIM_BEFORE.search(text[:start]):
                continue
            found.append((start, end, NoteViolation(quoted, reason)))

    seen: set[tuple[str, str]] = set()
    for _, _, violation in sorted(found, key=lambda item: item[:2]):
        key = (violation.text.casefold(), violation.reason)
        if key not in seen:
            seen.add(key)
            problems.append(violation)
    return problems


def _names_rule(
    other_clinicians: Iterable[str], recipient: str
) -> list[tuple[str, re.Pattern[str]]]:
    """Full names, first names and last names of other clinicians, matched case-sensitively.

    Name parts shared with the recipient are skipped, so a note can greet the recipient.
    """
    own = set(recipient.split())
    names = {name for name in other_clinicians if name}
    names |= {part for name in names for part in name.split() if len(part) >= 3}
    names -= own
    if not names:
        return []
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return [("outreach can't mention other clinicians", re.compile(rf"\b(?:{alternatives})\b"))]
