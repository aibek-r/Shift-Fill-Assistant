"""Coordinator review of outreach drafts: edit the personal note, then approve.

Framework-free so the approval rules are unit-tested; the UI keeps one instance per run. Delivery
is simulated: approving records the coordinator's decision and nothing is ever sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from shift_assistant.contracts import OutreachApproval, OutreachReviewSnapshot, StaffingReport
from shift_assistant.tools.schemas import OutreachDraft


class DraftStatus(StrEnum):
    PENDING = "pending"
    EDITING = "editing"
    APPROVED = "approved"


@dataclass
class DraftReview:
    draft: OutreachDraft
    status: DraftStatus = DraftStatus.PENDING
    problems: tuple[str, ...] = ()  # why the last edited note was rejected, one per violation


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

    def export_report(self, report: StaffingReport) -> StaffingReport:
        """Snapshot saved edits and approvals; unsaved editor text is never exported."""
        recommendations = []
        approvals = []
        for rec in report.recommendations:
            if rec.outreach is None:
                recommendations.append(rec)
                continue
            entry = self._entries[rec.outreach.draft_id]
            if (entry.draft.shift_id, entry.draft.clinician_id) != (
                rec.outreach.shift_id,
                rec.clinician_id,
            ):
                raise ValueError("Review draft does not belong to this recommendation.")
            recommendations.append(rec.model_copy(update={"outreach": entry.draft}))
            approvals.append(
                OutreachApproval(draft_id=entry.draft.draft_id, status=entry.status.value)
            )
        return report.model_copy(
            update={
                "recommendations": recommendations,
                "outreach_review": OutreachReviewSnapshot(run_id=self.run_id, approvals=approvals),
            }
        )

    def start_editing(self, draft_id: str) -> None:
        """Editing withdraws any earlier approval: the coordinator must approve the new text."""
        entry = self._entries[draft_id]
        entry.status, entry.problems = DraftStatus.EDITING, ()

    def cancel_editing(self, draft_id: str) -> None:
        """Discard the edit; the saved draft and its note stay as they were."""
        entry = self._entries[draft_id]
        entry.status, entry.problems = DraftStatus.PENDING, ()

    def save(self, draft_id: str, revised: OutreachDraft) -> None:
        """Store a draft re-rendered (and so revalidated) around the edited note."""
        previous = self._entries[draft_id].draft
        if revised.draft_id != draft_id or (revised.shift_id, revised.clinician_id) != (
            previous.shift_id,
            previous.clinician_id,
        ):
            raise ValueError(f"Revised draft {revised.draft_id} does not replace {draft_id}.")
        entry = self._entries[draft_id]
        entry.draft, entry.status, entry.problems = revised, DraftStatus.PENDING, ()

    def reject_edit(self, draft_id: str, problems: Sequence[str]) -> None:
        """Record why an edit was refused. The rejected text is never stored here."""
        self._entries[draft_id].problems = tuple(problems)

    def approve(self, draft_id: str) -> None:
        entry = self._entries[draft_id]
        if entry.status is DraftStatus.EDITING:
            raise ValueError("Save or cancel the edited note before approving.")
        entry.status = DraftStatus.APPROVED
