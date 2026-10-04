"""Outreach notes in the writer's own words, filtered by deterministic content rules.

The same rules run for model-written notes (draft_outreach) and coordinator edits.
"""

from __future__ import annotations

import itertools

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from shift_assistant.assistant import ShiftFillAssistant, build_assistant
from shift_assistant.contracts import Origin, StaffingRequest
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.tools.notes import DEFAULT_NOTE, FRIENDLY_NOTES, note_violations
from shift_assistant.tools.registry import ToolRegistry
from shift_assistant.tools.toolkit import NoteRejected
from tests.conftest import AssistantFactory, ai, make_settings, tool_call
from tests.test_agent_workflow import SUBMIT, rec, research_steps, submission

OTHERS = ["Maria Santos", "Daniel Kim", "James Okafor"]  # Grace Liu (C-107) is the recipient
PAY = "pay can't appear in outreach"
NUMBERS = "numbers, dates and times come from the shift record, not the note"
CONTACT = "contact details can't appear in outreach"
NAMES = "outreach can't mention other clinicians"
CREDENTIALS = "credentials and qualifications come from verified records, not the note"
CLAIMS = "claims about the clinician can't be verified"
LOGISTICS = "shift logistics come from the facility record, not the note"
PROMISES = "outreach can't promise bookings, pay or outcomes"
REQUEST = StaffingRequest(text="Find one ICU nurse for St. Mary's on Oct 14 and draft outreach")
BAD_NOTE = "It pays $55/hour and you're booked."


def problems(note: str) -> list[str]:
    return [v.message for v in note_violations(note, OTHERS, recipient="Grace Liu")]


def removal(text: str, reason: str) -> str:
    return f'Remove "{text}": {reason}.'


@pytest.mark.parametrize(
    "note",
    [
        *FRIENDLY_NOTES,
        *(" ".join(combo) for combo in itertools.combinations(FRIENDLY_NOTES, 4)),
    ],
)
def test_every_suggested_sentence_still_passes(note: str) -> None:
    assert problems(note) == []


@pytest.mark.parametrize(
    "note",
    [
        "We would like to have you on this shift.",  # "like" instead of "love"
        "Hope you're doing well! Would you like to pick up this shift?",
        "If you are interested, please reply to this message.",
        "Thanks so much for considering this opportunity; we'd be glad to have you.",
        "Have you worked with us before? We'd love to have you back.",
        "Hi Grace, we would really like you to join the team for this one.",
    ],
)
def test_notes_in_your_own_words_are_allowed(note: str) -> None:
    assert problems(note) == []


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("It is $55/hour.", removal("$55/hour", PAY)),
        ("A bonus is included.", removal("bonus", PAY)),
        ("See you on Oct 14.", removal("Oct 14", NUMBERS)),
        ("It starts at 7:00 PM.", removal("7:00 PM", NUMBERS)),
        ("Join us tomorrow.", removal("tomorrow", NUMBERS)),
        ("We need 3 nurses.", removal("3", NUMBERS)),
        ("Email jobs@example.com with questions.", removal("jobs@example.com", CONTACT)),
        ("Call 512-555-0199 with questions.", removal("512-555-0199", CONTACT)),
        ("Details are at https://example.com/jobs.", removal("https://example.com/jobs", CONTACT)),
        ("Maria Santos will join you.", removal("Maria Santos", NAMES)),
        ("Daniel will be there as well.", removal("Daniel", NAMES)),
        ("Your ACLS covers it.", removal("ACLS", CREDENTIALS)),
        ("We value the licensed staff we hire.", removal("licensed", CREDENTIALS)),
        ("We need six years of experience.", removal("six years of experience", CREDENTIALS)),
        ("We know you prefer nights.", removal("you prefer nights", CLAIMS)),
        ("You are available that week.", removal("You are available that week", CLAIMS)),
        ("Parking is free.", removal("Parking", LOGISTICS)),
        ("Pick up your badge first.", removal("badge", LOGISTICS)),
        ("Please report to the front desk.", removal("report to", LOGISTICS)),
        ("The shift is guaranteed.", removal("guaranteed", PROMISES)),
        ("Good news, you're booked.", removal("booked", PROMISES)),
    ],
)
def test_each_category_is_blocked_with_the_exact_text(note: str, expected: str) -> None:
    assert expected in problems(note)


def test_every_violation_in_one_note_is_reported_in_order() -> None:
    note = (
        "You're booked! It pays $55/hour, call 512-555-0199 and report to the badge office "
        "on Oct 14."
    )

    assert problems(note) == [
        removal("booked", PROMISES),
        removal("pays", PAY),
        removal("$55/hour", PAY),
        removal("512-555-0199", CONTACT),
        removal("report to", LOGISTICS),
        removal("badge", LOGISTICS),
        removal("Oct 14", NUMBERS),
    ]


def test_length_and_sentence_count_are_limited() -> None:
    assert problems("") == ["Write a short note of 1 to 4 sentences."]
    assert problems("x" * 401) == ["Shorten the note to 400 characters or fewer (it has 401)."]
    five = " ".join(FRIENDLY_NOTES)
    assert problems(five) == ["Use at most 4 sentences (the note has 5)."]


def test_the_recipient_may_be_greeted_by_name() -> None:
    assert problems("Hi Grace, we would like to have you on this shift.") == []
    assert removal("Grace", NAMES) in [
        v.message for v in note_violations("Hi Grace!", ["Grace Liu"], recipient="Maria Santos")
    ]


# --- Coordinator path ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def assistant() -> ShiftFillAssistant:
    return build_assistant(make_settings(), embedder=HashingEmbedder())


def test_coordinator_note_in_own_words_is_saved_with_code_added_facts(
    assistant: ShiftFillAssistant,
) -> None:
    note = "We would like to have you on this shift. Hope to hear from you soon!"

    draft = assistant.revise_outreach("SHF-1001", "C-107", note)

    assert draft.personal_note == note
    assert note in draft.body
    assert "Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM" in draft.body  # by code
    assert "Please reply by" in draft.body


def test_coordinator_note_is_rejected_with_every_problem(assistant: ShiftFillAssistant) -> None:
    with pytest.raises(NoteRejected) as rejected:
        assistant.revise_outreach("SHF-1001", "C-107", BAD_NOTE)

    assert [v.message for v in rejected.value.violations] == [
        removal("pays", PAY),
        removal("$55/hour", PAY),
        removal("booked", PROMISES),
    ]


def test_the_tool_rejects_the_same_note_for_the_model(registry: ToolRegistry) -> None:
    result = registry.execute(
        "draft_outreach",
        {"shift_id": "SHF-1001", "clinician_id": "C-107", "personal_note": BAD_NOTE},
    )

    assert not result.ok and not result.evidence.drafts
    assert result.note_violations == (
        removal("pays", PAY),
        removal("$55/hour", PAY),
        removal("booked", PROMISES),
    )
    assert "call draft_outreach again" in result.content


# --- Model path ---------------------------------------------------------------------------------


def draft_call(note: str) -> dict[str, object]:
    return tool_call(
        "draft_outreach", shift_id="SHF-1001", clinician_id="C-101", personal_note=note
    )


def final_submission() -> AIMessage:
    return ai(tool_call(SUBMIT, **submission(rec("C-101", draft="DRAFT-SHF-1001-C-101"))))


def test_the_model_gets_violations_back_and_can_fix_its_note(
    scripted_assistant: AssistantFactory,
) -> None:
    fixed = "We would like to have you on this shift."
    assistant, model = scripted_assistant(
        [*research_steps(), ai(draft_call(BAD_NOTE)), ai(draft_call(fixed)), final_submission()]
    )

    report = assistant.run(REQUEST)

    error = model.received[4][-1]
    assert isinstance(error, ToolMessage) and error.status == "error"
    assert removal("$55/hour", PAY) in str(error.content)
    assert "the default note is used instead" in str(error.content)
    (maria,) = report.recommendations
    assert maria.outreach is not None and maria.outreach.personal_note == fixed
    assert maria.outreach_by is Origin.MODEL


def test_a_second_rejected_note_falls_back_to_the_default_note(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, model = scripted_assistant(
        [
            *research_steps(),
            ai(draft_call(BAD_NOTE)),
            ai(draft_call("Call 512-555-0199 for the details.")),
            final_submission(),
        ]
    )

    report = assistant.run(REQUEST)

    fallback = model.received[5][-1]
    assert isinstance(fallback, ToolMessage) and fallback.status == "success"
    assert str(fallback.content).startswith("Default note used.")
    assert removal("512-555-0199", CONTACT) in str(fallback.content)
    (maria,) = report.recommendations
    assert maria.outreach is not None and maria.outreach.personal_note == DEFAULT_NOTE
    assert report.issues == []
    # Rejected note text is not kept in the exported trace.
    assert "$55" not in report.model_dump_json() and "555-0199" not in report.model_dump_json()
