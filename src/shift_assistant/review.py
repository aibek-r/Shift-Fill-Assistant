"""Coordinator review of outreach drafts: edit the personal note, then approve.

Framework-free so the approval rules are unit-tested; the UI keeps one instance per run. Delivery
is simulated: approving records the coordinator's decision and nothing is ever sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from shift_assistant.contracts import StaffingReport
from shift_assistant.tools.schemas import OutreachDraft


class DraftStatus(StrEnum):
    PENDING = "pending"
    EDITING = "editing"
    APPROVED = "approved"


@dataclass
class DraftReview:
    draft: OutreachDraft
    status: DraftStatus = DraftStatus.PENDING
    error: str | None = None  # why the last edited note was rejected


class OutreachReview:
    """Review state for the drafts of one run. Each run gets a fresh instance and run_id."""

    def __init__(self, drafts: Iterable[OutreachDraft]) -> None:
        self.run_id = uuid.uuid4().hex
        self._entries = {d.draft_id: DraftReview(d) for d in drafts}

    @classmethod
    def for_report(cls, report: StaffingReport) -> OutreachReview:
        return cls(r.outreach for r in report.recommendations if r.outreach is not None)

    def __getitem__(self, draft_id: str) -> DraftReview:
        return self._entries[draft_id]

    def start_editing(self, draft_id: str) -> None:
        """Editing withdraws any earlier approval: the coordinator must approve the new text."""
        entry = self._entries[draft_id]
        entry.status, entry.error = DraftStatus.EDITING, None

    def cancel_editing(self, draft_id: str) -> None:
        entry = self._entries[draft_id]
        entry.status, entry.error = DraftStatus.PENDING, None

    def save(self, draft_id: str, revised: OutreachDraft) -> None:
        """Store a draft re-rendered (and so revalidated) around the edited note."""
        if revised.draft_id != draft_id:
            raise ValueError(f"Revised draft {revised.draft_id} does not replace {draft_id}.")
        entry = self._entries[draft_id]
        entry.draft, entry.status, entry.error = revised, DraftStatus.PENDING, None

    def reject_edit(self, draft_id: str, error: str) -> None:
        self._entries[draft_id].error = error

    def approve(self, draft_id: str) -> None:
        entry = self._entries[draft_id]
        if entry.status is DraftStatus.EDITING:
            raise ValueError("Save or cancel the edited note before approving.")
        entry.status = DraftStatus.APPROVED
