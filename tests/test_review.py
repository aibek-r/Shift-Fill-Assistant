"""Outreach review: edited notes are revalidated and approvals are scoped to one run and draft."""

from __future__ import annotations

import pytest

from shift_assistant.assistant import ShiftFillAssistant, build_assistant
from shift_assistant.contracts import StaffingRequest
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.review import DraftStatus, OutreachReview
from shift_assistant.tools.schemas import OutreachDraft
from tests.conftest import make_settings

DANIEL_DRAFT = "DRAFT-SHF-1001-C-104"
NEW_NOTE = "Your ICU night experience would be a great help to this team."


@pytest.fixture(scope="module")
def assistant() -> ShiftFillAssistant:
    return build_assistant(make_settings(), embedder=HashingEmbedder())


@pytest.fixture
def daniel_draft(assistant: ShiftFillAssistant) -> OutreachDraft:
    return assistant.revise_outreach("SHF-1001", "C-104", "We think you would fit this unit well.")


def test_edited_note_keeps_verified_details_and_reminders(
    assistant: ShiftFillAssistant, daniel_draft: OutreachDraft
) -> None:
    revised = assistant.revise_outreach("SHF-1001", "C-104", NEW_NOTE)

    assert revised.draft_id == daniel_draft.draft_id
    assert revised.personal_note == NEW_NOTE
    assert NEW_NOTE in revised.body
    assert "St. Mary's Medical Center (Austin, TX)" in revised.body
    assert "Your ACLS expires soon" in revised.body
    assert revised.body.replace(NEW_NOTE, "") == daniel_draft.body.replace(
        daniel_draft.personal_note, ""
    )


@pytest.mark.parametrize(
    ("note", "reason"),
    [
        ("Call me at 512-555-0199 to talk about this shift.", "contact details or pay rates"),
        ("It pays $95 per hour, which is a great rate.", "contact details or pay rates"),
        ("Too short.", "at least 20 characters"),
    ],
)
def test_edited_note_is_revalidated(assistant: ShiftFillAssistant, note: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        assistant.revise_outreach("SHF-1001", "C-104", note)


def test_edit_is_refused_for_an_ineligible_clinician(assistant: ShiftFillAssistant) -> None:
    with pytest.raises(ValueError, match="not eligible"):
        assistant.revise_outreach("SHF-1001", "C-102", NEW_NOTE)


def test_editing_an_approved_draft_withdraws_the_approval(
    assistant: ShiftFillAssistant, daniel_draft: OutreachDraft
) -> None:
    review = OutreachReview([daniel_draft])
    review.approve(DANIEL_DRAFT)
    assert review[DANIEL_DRAFT].status is DraftStatus.APPROVED

    review.start_editing(DANIEL_DRAFT)
    assert review[DANIEL_DRAFT].status is DraftStatus.EDITING
    with pytest.raises(ValueError, match="before approving"):
        review.approve(DANIEL_DRAFT)

    review.save(DANIEL_DRAFT, assistant.revise_outreach("SHF-1001", "C-104", NEW_NOTE))
    assert review[DANIEL_DRAFT].status is DraftStatus.PENDING  # must be approved again
    assert review[DANIEL_DRAFT].draft.personal_note == NEW_NOTE


def test_rejected_note_keeps_the_previous_draft(daniel_draft: OutreachDraft) -> None:
    review = OutreachReview([daniel_draft])
    review.start_editing(DANIEL_DRAFT)

    review.reject_edit(DANIEL_DRAFT, "personal_note: too short")

    entry = review[DANIEL_DRAFT]
    assert (entry.status, entry.error, entry.draft) == (
        DraftStatus.EDITING,
        "personal_note: too short",
        daniel_draft,
    )


def test_approvals_do_not_carry_over_to_a_new_run(assistant: ShiftFillAssistant) -> None:
    request = StaffingRequest(text="Fill the ICU night shift", shift_id="SHF-1001")
    first_report, second_report = assistant.run(request), assistant.run(request)
    first = OutreachReview.for_report(first_report)
    draft_id = first_report.recommendations[0].outreach.draft_id  # type: ignore[union-attr]
    first.approve(draft_id)

    second = OutreachReview.for_report(second_report)

    assert second.run_id != first.run_id
    assert second[draft_id].status is DraftStatus.PENDING  # same draft ID, fresh decision


def test_a_revised_draft_cannot_replace_another_draft(
    assistant: ShiftFillAssistant, daniel_draft: OutreachDraft
) -> None:
    review = OutreachReview([daniel_draft])
    other = assistant.revise_outreach("SHF-1001", "C-101", NEW_NOTE)

    with pytest.raises(ValueError, match="does not replace"):
        review.save(DANIEL_DRAFT, other)
