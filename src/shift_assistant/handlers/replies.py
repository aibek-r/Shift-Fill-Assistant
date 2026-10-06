"""Fixed replies for help, small talk and refusals: a template, plus at most one fixed note
chosen by what the message mentions. No model writes any of it."""

from __future__ import annotations

from datetime import date

from shift_assistant import templates
from shift_assistant.contracts import Intent, IntentDecision, ReplyReason, ResponseKind
from shift_assistant.handlers.common import HandlerReply
from shift_assistant.intent import requested_dates
from shift_assistant.router import mentions_credentials, mentions_eligibility

_BUSINESS = {
    ReplyReason.PAY_OR_CONTRACT: templates.PAY_OR_CONTRACT,
    ReplyReason.BULK_EXPORT: templates.BULK_EXPORT,
    ReplyReason.AUDIT_DATA: templates.AUDIT_DATA,
}


def fixed_reply(decision: IntentDecision, text: str, today: date) -> HandlerReply:
    intent, reason = decision.intent, decision.reason
    examples = templates.EXAMPLES
    if intent is Intent.HELP:
        if reason is ReplyReason.FOLLOW_UP:
            question = templates.follow_up(_when(text, today))
            return HandlerReply(ResponseKind.CLARIFICATION, question, reason=reason)
        if reason is ReplyReason.NON_ENGLISH:
            return HandlerReply(
                ResponseKind.CLARIFICATION, templates.NON_ENGLISH, None, examples, reason
            )
        if reason is ReplyReason.EMPTY_MESSAGE:
            return HandlerReply(ResponseKind.HELP, templates.EMPTY, None, examples, reason)
        if reason is ReplyReason.NOT_UNDERSTOOD:
            return HandlerReply(ResponseKind.HELP, templates.NOT_UNDERSTOOD, None, examples, reason)
        reason = reason or ReplyReason.HELP_REQUEST
        return HandlerReply(ResponseKind.HELP, templates.HELP, None, examples, reason)
    if intent is Intent.SMALL_TALK:
        if reason is ReplyReason.THANKS:
            return HandlerReply(ResponseKind.HELP, templates.THANKS, reason=reason)
        if reason is ReplyReason.SYSTEM_QUESTION:
            return HandlerReply(ResponseKind.HELP, templates.SYSTEM_QUESTION, reason=reason)
        return HandlerReply(
            ResponseKind.HELP, templates.IDENTITY, None, examples, ReplyReason.IDENTITY
        )
    if intent is Intent.OUT_OF_SCOPE:
        return HandlerReply(
            ResponseKind.OUT_OF_SCOPE,
            templates.OUT_OF_SCOPE,
            None,
            templates.OUT_OF_SCOPE_EXAMPLES,
            ReplyReason.OFF_TOPIC,
        )
    if intent is Intent.MEDICAL_LEGAL:
        note = templates.INVALID_LICENSE_NOTE if mentions_credentials(text) else ""
        return HandlerReply(
            ResponseKind.REFUSAL,
            _with_note(templates.MEDICAL_LEGAL, note),
            reason=reason or ReplyReason.LEGAL_ADVICE,
        )
    if intent is Intent.ACTION_NOT_ALLOWED:
        note = templates.CREDENTIAL_UPDATE_NOTE if mentions_credentials(text) else ""
        return HandlerReply(
            ResponseKind.REFUSAL,
            _with_note(templates.ACTION_NOT_ALLOWED, note),
            reason=ReplyReason.ACTION_NOT_ALLOWED,
        )
    if intent is Intent.BUSINESS_SENSITIVE:
        reason = reason if reason in _BUSINESS else ReplyReason.PAY_OR_CONTRACT
        return HandlerReply(ResponseKind.REFUSAL, _BUSINESS[reason], reason=reason)
    if intent is Intent.BLOCKED:
        note = templates.ELIGIBILITY_RULES_NOTE if mentions_eligibility(text) else ""
        return HandlerReply(
            ResponseKind.BLOCKED, _with_note(templates.BLOCKED, note), reason=ReplyReason.BLOCKED
        )
    # Recognized questions without a handler yet (credential and single-nurse checks).
    unavailable = templates.not_available_yet(intent)
    return HandlerReply(
        ResponseKind.HELP,
        unavailable.message,
        None,
        unavailable.examples,
        ReplyReason.NOT_AVAILABLE_YET,
    )


def _with_note(text: str, note: str) -> str:
    return f"{text} {note}" if note else text


def _when(text: str, today: date) -> str | None:
    """'October 16' or 'next week' for a follow-up question, from the message itself."""
    requested = requested_dates(text, today)
    if len(requested.dates) == 1 and requested.window is None:
        return templates.long_date(next(iter(requested.dates)))
    if requested.window is not None and not requested.dates:
        return requested.window.phrase
    return None
