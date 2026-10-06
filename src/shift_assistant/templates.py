"""Every fixed text the assistant shows, in simple English.

Code picks a template and fills in values taken from records (shift IDs, facility names, dates).
No model writes or edits these texts. The example requests come from the mock data, so each one
works; tests check that they route to a working handler.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from shift_assistant.contracts import MAX_MESSAGE_CHARS, Intent, RefusedTopic
from shift_assistant.domain.models import CredentialType, Unit
from shift_assistant.tools.outreach import unit_label


@dataclass(frozen=True)
class Reply:
    message: str
    examples: tuple[str, ...] = ()


EXAMPLES = (
    "Find two ICU nurses for the St. Mary's night shift on October 14.",
    "What shifts are open?",
    "Where do agency nurses park at St. Mary's?",
)

# --- Help and small talk -------------------------------------------------------------------------

HELP = (
    "I help staffing coordinators. I can find open shifts, check nurses for a shift, answer "
    "questions about facility policies, check credentials, and draft messages for you to review."
)
EMPTY = "Please type a request."
THANKS = "You're welcome. Anything else?"
IDENTITY = "I'm the Shift Fill Assistant, an internal staffing tool."
SYSTEM_QUESTION = (
    "I'm the Shift Fill Assistant. I can find open shifts, check nurses for a shift, answer "
    "questions about facility policies, check credentials, and draft messages for you to review. "
    "I don't share technical details about how I work."
)
NOT_UNDERSTOOD = "I didn't understand."

# --- Refusals ------------------------------------------------------------------------------------

OUT_OF_SCOPE = (
    "Sorry, I can only help with shift staffing: open shifts, nurse credentials and eligibility, "
    "facility policies, and outreach drafts."
)
OUT_OF_SCOPE_EXAMPLES = EXAMPLES[:2]
MEDICAL_LEGAL = (
    "I can't give medical or legal advice. Please ask a clinician, your manager, or your legal "
    "team."
)
INVALID_LICENSE_NOTE = "The system will not recommend nurses with invalid licenses."
ACTION_NOT_ALLOWED = (
    "I can't book shifts, send messages, or change data. I can prepare a shortlist and draft "
    "messages for you to review and send."
)
CREDENTIAL_UPDATE_NOTE = "Please update it in the credentials system."
PAY_OR_CONTRACT = "I can't share pay, bill rates, or contract terms."
BULK_EXPORT = (
    "I can't export data in bulk. I can export a single report as JSON from Technical details."
)
AUDIT_DATA = "I can't share usage or audit data. Only admins can see it."
BLOCKED = "Sorry, I can't help with that request."
ELIGIBILITY_RULES_NOTE = "Eligibility rules always apply."

_TOPIC_LABELS = {
    RefusedTopic.WEATHER: "the weather",
    RefusedTopic.SPORTS: "sports",
    RefusedTopic.ENTERTAINMENT: "movies, music or games",
    RefusedTopic.CREATIVE_WRITING: "creative writing",
    RefusedTopic.FOOD: "food or restaurants",
    RefusedTopic.FINANCE: "finance",
    RefusedTopic.NEWS_AND_POLITICS: "news or politics",
    RefusedTopic.TRANSLATION: "translation",
    RefusedTopic.CODE: "code",
    RefusedTopic.MATH: "math",
    RefusedTopic.TRAVEL: "travel",
    RefusedTopic.GENERAL_KNOWLEDGE: "general knowledge questions",
}


def refused_part(topic: RefusedTopic) -> str:
    """One line for a declined part of a mixed message."""
    if topic in (RefusedTopic.MEDICAL_ADVICE, RefusedTopic.LEGAL_ADVICE):
        return MEDICAL_LEGAL
    if topic is RefusedTopic.ACTION:
        return ACTION_NOT_ALLOWED
    return f"I can't help with {_TOPIC_LABELS[topic]}."


# --- Questions -----------------------------------------------------------------------------------

NON_ENGLISH = "Sorry, I can only read English. Please write your request in English."
FOLLOW_UP_GENERIC = "I don't remember earlier messages yet. Please write the full request."
_CLARIFYING_QUESTIONS = {
    Intent.FILL_SHIFT: (
        "Do you want me to find nurses for a shift? If so, please tell me the facility, unit "
        "and date."
    ),
    Intent.SHIFT_LOOKUP: "Do you want me to list open shifts? If so, for which facility or dates?",
    Intent.POLICY_QUESTION: "Is this a question about a facility policy? If so, which facility?",
    Intent.FACILITY_INFO: "Is this a question about a facility? If so, which one?",
}
_CLARIFY_PINNED_SHIFT = (
    "Do you want me to find nurses for the shift you selected? If so, how many do you need?"
)
_CLARIFY_DEFAULT = "Sorry, I'm not sure what you need. Could you say it like one of the examples?"


def clarifying_question(intent: Intent, *, shift_pinned: bool = False) -> Reply:
    """One short question about the likely intent, or a general one."""
    if intent is Intent.FILL_SHIFT and shift_pinned:
        return Reply(_CLARIFY_PINNED_SHIFT, EXAMPLES)
    return Reply(_CLARIFYING_QUESTIONS.get(intent, _CLARIFY_DEFAULT), EXAMPLES)


def follow_up(when: str | None) -> str:
    """'What would you like for October 16?' while there is no conversation memory."""
    return f"What would you like for {when}?" if when else FOLLOW_UP_GENERIC


_NOT_YET = {
    Intent.CREDENTIAL_CHECK: "look up credential expiry dates",
    Intent.ELIGIBILITY_CHECK: "check one named nurse against a shift",
}


def not_available_yet(intent: Intent) -> Reply:
    can_not = _NOT_YET.get(intent, "answer this kind of question")
    return Reply(f"Sorry, I can't {can_not} yet.", EXAMPLES)


# --- Shift answers -------------------------------------------------------------------------------

SHIFT_COLUMNS = ["Shift", "Facility", "Unit", "Date", "Time", "Day/night", "Open places"]
HARDEST_COLUMNS = ["Shift", "Facility", "Unit", "Date", "Open places", "Eligible nurses"]
NEXT_SHIFTS = "The next open shifts are listed below."
ELIGIBLE_COUNT_NOTE = (
    "Eligible nurses are counted with the same eligibility rules used for staffing."
)


def shift_not_found(shift_id: str) -> str:
    return f'I couldn\'t find shift {shift_id}. Ask "What shifts are open?" to see the list.'


def open_shifts(count: int, kind: str, scope: str) -> str:
    """E.g. 'There is 1 open night shift at St. Mary's Medical Center.'"""
    what = f"{kind} {_plural(count, 'shift')}" if kind else _plural(count, "shift")
    return f"There {_is_are(count)} {count} open {what}{scope}."


def no_open_shifts(kind: str, scope: str) -> str:
    """E.g. 'No open shifts this week (Sep 28 to Oct 4).' or 'No open shifts on Dec 25.'"""
    return f"No open {kind + ' ' if kind else ''}shifts{scope}."


def open_places(shift_id: str, places: int) -> str:
    return f"{shift_id} has {places} open {_plural(places, 'place')}."


def shift_times(shift_id: str, what: str, start: str, end: str, timezone: str) -> str:
    return f"{shift_id} ({what}) starts {start} and ends {end} ({timezone})."


def hardest_to_fill(shift_ids: Sequence[str], eligible: int, places: int) -> str:
    who = " and ".join(shift_ids)
    verb = "is" if len(shift_ids) == 1 else "are"
    nurses = f"{eligible} eligible {_plural(eligible, 'nurse')}"
    return (
        f"{who} {verb} the hardest to fill: {nurses} for {places} open {_plural(places, 'place')}."
    )


# --- Facility answers ----------------------------------------------------------------------------

REQUIREMENT_COLUMNS = ["Unit", "Required credentials", "Minimum experience"]


def facility_not_found(name: str, known: Iterable[str]) -> str:
    return f"{name} is not in the system. Known facilities: {', '.join(known)}."


def which_facility(known: Iterable[str]) -> str:
    return f"Which facility do you mean? Known facilities: {', '.join(known)}."


def compact_license(name: str, accepted: bool, state: str) -> str:
    if accepted:
        return f"Yes. {name} accepts multistate compact RN licenses."
    return (
        f"No. {name} does not accept multistate compact RN licenses. Nurses need an RN license "
        f"valid in {state}."
    )


def rest_hours(name: str, hours: int) -> str:
    return f"{name} requires at least {hours} hours of rest between shifts."


def unit_requirements(
    name: str, unit: Unit, credentials: Sequence[CredentialType], years: int
) -> str:
    return (
        f"The {name} {unit_label(unit)} unit requires {credential_list(credentials)}, and at "
        f"least {years} {_plural(years, 'year')} of experience."
    )


def requirements_by_unit(name: str) -> str:
    return f"Requirements by unit at {name}:"


def unit_not_at_facility(name: str, unit: Unit, units: Sequence[Unit]) -> str:
    return (
        f"{name} has no {unit_label(unit)} unit in the system. Its units are "
        f"{_join(unit_label(u) for u in units)}."
    )


def facility_units(name: str, units: Sequence[Unit]) -> str:
    return f"{name} has these units: {_join(unit_label(u) for u in units)}."


def facility_overview(name: str, city: str, state: str, timezone: str) -> str:
    return f"{name} is in {city}, {state} (time zone {timezone})."


def overview_items(units: Sequence[Unit], compact: bool, rest: int) -> list[str]:
    return [
        f"Units: {_join(unit_label(u) for u in units)}",
        f"Compact RN licenses: {'accepted' if compact else 'not accepted'}",
        f"Minimum rest between shifts: {rest} hours",
    ]


def credential_list(credentials: Iterable[CredentialType]) -> str:
    return _join(
        "an RN license" if c is CredentialType.RN_LICENSE else c.value for c in credentials
    )


# --- Policy answers ------------------------------------------------------------------------------


def policy_found(scope_name: str, section: str) -> str:
    return f"From the {scope_name} policies ({section}):"


def policy_not_found(scope_name: str) -> str:
    return f"I couldn't find this in the {scope_name} policies."


# --- Input errors --------------------------------------------------------------------------------


def input_error(exc: ValidationError) -> str:
    """A plain-English message for an invalid request, one sentence per problem."""
    messages: list[str] = []
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else ""
        if field == "text" and error["type"] == "string_too_long":
            messages.append(
                f"Your message is too long. Please keep it under {MAX_MESSAGE_CHARS:,} characters."
            )
        elif field == "text":
            messages.append(EMPTY)
        elif field == "start_date":
            messages.append("The date must look like 2026-10-14.")
        elif field == "unit":
            messages.append(f"The unit must be one of: {', '.join(u.value for u in Unit)}.")
        elif field == "facility":
            messages.append("The facility name is too long.")
        else:
            messages.append(f"The {field or 'request'} value is not valid.")
    return " ".join(dict.fromkeys(messages))


# --- Formatting helpers --------------------------------------------------------------------------


def long_date(day: date) -> str:
    return f"{day:%B} {day.day}"


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def _is_are(count: int) -> str:
    return "is" if count == 1 else "are"


def _join(parts: Iterable[str]) -> str:
    items = list(parts)
    if len(items) <= 2:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"
