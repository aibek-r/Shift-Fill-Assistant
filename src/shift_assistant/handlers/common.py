"""Shared pieces of the read-only handlers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shift_assistant.contracts import Answer, IntentEntities, ReplyReason, ResponseKind
from shift_assistant.domain.models import Facility, Unit
from shift_assistant.repository import StaffingRepository


@dataclass(frozen=True)
class HandlerReply:
    kind: ResponseKind
    message: str
    answer: Answer | None = None
    examples: tuple[str, ...] = ()
    reason: ReplyReason | None = None


def answered(message: str, answer: Answer | None = None) -> HandlerReply:
    return HandlerReply(ResponseKind.ANSWER, message, answer or Answer())


@dataclass(frozen=True)
class FacilityMatch:
    facility: Facility | None = None
    unknown_name: str | None = None  # a name the message gives that matches no facility


# A capitalized name after "about", "at", "for", "in" or "from", for facilities the records do
# not know ("Tell me about Mercy General"). Months, units and shift IDs are not names.
_NAME_AFTER_PREPOSITION = re.compile(
    r"\b(?:about|at|for|in|from)\s+(?P<name>[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*){0,4})"
)
_NOT_A_NAME = re.compile(
    r"^(?:SHF-|C-\d|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*day\b|christmas|halloween|new\b|today|tomorrow"
    r"|this\b|next\b|the\b)",
    re.IGNORECASE,
)
_MAX_NAME_CHARS = 60
_GENERIC_NAME_WORDS = {"medical", "center", "community", "hospital", "childrens", "children's"}


def find_facility(
    text: str, entities: IntentEntities, repository: StaffingRepository
) -> FacilityMatch:
    """The one facility the message names, or the name it gives that matches none."""
    mentioned = repository.facilities_mentioned(text)
    if len(mentioned) == 1:
        return FacilityMatch(mentioned[0])
    if mentioned:
        return FacilityMatch()  # several: the caller lists or asks
    if entities.facility:
        matches = repository.find_facilities(entities.facility)
        if len(matches) == 1:
            return FacilityMatch(matches[0])
        return FacilityMatch(unknown_name=_clean_name(entities.facility))
    for match in _NAME_AFTER_PREPOSITION.finditer(text):
        name = match["name"]
        units = {u.value for u in Unit}
        if not _NOT_A_NAME.match(name) and name.split()[0].upper() not in units:
            return FacilityMatch(unknown_name=_clean_name(name))
    return FacilityMatch()


def short_name(name: str) -> str:
    """'St. Mary's Medical Center' -> "St. Mary's", 'Bayview Children's Hospital' -> 'Bayview'."""
    words = name.split()
    while len(words) > 1 and words[-1].lower() in _GENERIC_NAME_WORDS:
        words.pop()
    return " ".join(words)


def _clean_name(name: str) -> str:
    """A user-supplied name, reduced to plain characters before it is repeated back."""
    cleaned = re.sub(r"[^\w '.-]", "", name).strip(" .'-")
    return cleaned[:_MAX_NAME_CHARS] or "That facility"
