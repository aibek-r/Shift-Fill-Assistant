"""Fixed replies in simple English: help, refusals, clarifying questions and input errors.

Code picks a template; no model writes or edits these texts. Examples come from the mock data, so
every one of them works (tests check that each routes to its intent).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from shift_assistant.contracts import MAX_MESSAGE_CHARS, Intent, ReplyReason
from shift_assistant.domain.models import Unit


@dataclass(frozen=True)
class Capability:
    can: str  # completes "I can ..."
    cannot_yet: str  # completes "I can't ... yet"
    example: str


CAPABILITIES: dict[Intent, Capability] = {
    Intent.FILL_SHIFT: Capability(
        "find and check nurses for an open shift, and draft messages for you to review",
        "fill shifts",
        "Find two ICU nurses for the St. Mary's night shift on October 14.",
    ),
    Intent.SHIFT_LOOKUP: Capability(
        "list open shifts",
        "look up open shifts",
        "What shifts are open at St. Mary's?",
    ),
    Intent.CREDENTIAL_CHECK: Capability(
        "show licenses and certifications that expire soon",
        "check expiring credentials",
        "Whose ACLS expires in the next 30 days?",
    ),
    Intent.ELIGIBILITY_CHECK: Capability(
        "check if a nurse can work a shift",
        "check if one nurse can work a shift",
        "Can Maria Santos work SHF-1001?",
    ),
    Intent.POLICY_QUESTION: Capability(
        "answer questions from facility policies, with sources",
        "answer policy questions",
        "Where do night nurses park at St. Mary's?",
    ),
}

ABOUT = "I'm the Shift Fill Assistant. I help staffing coordinators fill open shifts."
SAFETY_NOTE = (
    "I only make suggestions. You review every result, and I never send messages or book shifts."
)
_GREETING = "Hi! " + ABOUT
_THANKS = "You're welcome. Is there anything else I can help with?"

_REFUSALS = {
    ReplyReason.OFF_TOPIC: "Sorry, I can't help with that. I can only help with staffing tasks.",
    ReplyReason.CLINICAL_ADVICE: (
        "Sorry, I can't give medical or clinical advice. Please ask a clinician or your "
        "facility's clinical lead."
    ),
    ReplyReason.LEGAL_ADVICE: (
        "Sorry, I can't give legal advice. Please ask your legal or compliance team."
    ),
}
BLOCKED = "Sorry, I can't help with that request."

_CLARIFYING_QUESTIONS = {
    Intent.FILL_SHIFT: (
        "Do you want me to find nurses for a shift? If so, please tell me the facility, unit "
        "and date."
    ),
    Intent.SHIFT_LOOKUP: "Do you want me to list open shifts? If so, for which facility or dates?",
    Intent.CREDENTIAL_CHECK: (
        "Do you want to see credentials that expire soon? If so, which credential and how many "
        "days ahead?"
    ),
    Intent.ELIGIBILITY_CHECK: (
        "Do you want me to check if a nurse can work a shift? If so, please tell me the nurse's "
        "name and the shift."
    ),
    Intent.POLICY_QUESTION: "Is this a question about a facility policy? If so, which facility?",
}
_CLARIFY_PINNED_SHIFT = (
    "Do you want me to find nurses for the shift you selected? If so, how many do you need?"
)
_CLARIFY_DEFAULT = "Sorry, I'm not sure what you need. Could you say it like one of the examples?"


@dataclass(frozen=True)
class Reply:
    message: str
    examples: tuple[str, ...] = ()


def help_reply(reason: ReplyReason | None, available: Sequence[Intent]) -> Reply:
    if reason is ReplyReason.THANKS:
        return Reply(_THANKS, examples(available))
    intro = _GREETING if reason is ReplyReason.GREETING else ABOUT
    return Reply(f"{intro}\n\n{capability_list(available)}\n\n{SAFETY_NOTE}", examples(available))


def refusal(reason: ReplyReason | None, available: Sequence[Intent]) -> Reply:
    if reason is ReplyReason.BLOCKED:
        return Reply(BLOCKED)
    text = _REFUSALS.get(reason or ReplyReason.OFF_TOPIC, _REFUSALS[ReplyReason.OFF_TOPIC])
    return Reply(f"{text}\n\n{capability_list(available)}", examples(available))


def clarifying_question(
    intent: Intent, available: Sequence[Intent], *, shift_pinned: bool = False
) -> Reply:
    """One short question about the likely intent, or a general one when the guess is not an
    intent the assistant can handle yet."""
    if intent not in available:
        return Reply(_CLARIFY_DEFAULT, examples(available))
    if intent is Intent.FILL_SHIFT and shift_pinned:
        return Reply(_CLARIFY_PINNED_SHIFT, examples(available))
    return Reply(_CLARIFYING_QUESTIONS.get(intent, _CLARIFY_DEFAULT), examples(available))


def not_available_yet(intent: Intent, available: Sequence[Intent]) -> Reply:
    can = " or ".join(CAPABILITIES[i].can for i in available)
    return Reply(
        f"Sorry, I can't {CAPABILITIES[intent].cannot_yet} yet. Right now I can {can}.",
        examples(available),
    )


def capability_list(available: Sequence[Intent]) -> str:
    return "I can:\n" + "\n".join(f"- {CAPABILITIES[intent].can}" for intent in available)


def examples(available: Sequence[Intent]) -> tuple[str, ...]:
    return tuple(CAPABILITIES[intent].example for intent in available)


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
            messages.append("Please type a request.")
        elif field == "start_date":
            messages.append("The date must look like 2026-10-14.")
        elif field == "unit":
            messages.append(f"The unit must be one of: {', '.join(u.value for u in Unit)}.")
        elif field == "facility":
            messages.append("The facility name is too long.")
        else:
            messages.append(f"The {field or 'request'} value is not valid.")
    return " ".join(dict.fromkeys(messages))
