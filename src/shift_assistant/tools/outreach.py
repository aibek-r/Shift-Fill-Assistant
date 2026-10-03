"""Outreach rendering: facts come from the system of record, only the personal note from the LLM."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from shift_assistant.domain.eligibility import CheckCode, Finding
from shift_assistant.domain.models import Clinician, Unit
from shift_assistant.tools.schemas import OutreachDraft, ShiftSummary

RESPONSE_WINDOW_BEFORE_SHIFT = timedelta(hours=48)

_UNIT_LABELS = {Unit.MED_SURG: "Med-Surg", Unit.TELEMETRY: "Telemetry"}


def draft_id_for(shift_id: str, clinician_id: str) -> str:
    return f"DRAFT-{shift_id}-{clinician_id}"


def render_outreach(
    shift: ShiftSummary,
    clinician: Clinician,
    personal_note: str,
    warnings: Sequence[Finding] = (),
) -> OutreachDraft:
    unit = unit_label(shift.unit)
    subject = (
        f"Open {unit} {shift.period} shift at {shift.facility_name} on {_short_date(shift.start)}"
    )
    starts, ends = format_local_datetime(shift.start), format_local_datetime(shift.end)
    lines = [
        f"Hi {clinician.first_name},",
        "",
        personal_note.strip(),
        "",
        "Shift details",
        f"- Facility: {shift.facility_name} ({shift.location})",
        f"- Unit: {unit}",
        f"- Time: {starts} to {ends} ({shift.timezone})",
    ]
    reminders = [
        f"- Your {w.credential} expires soon. Please upload your renewal so you stay eligible."
        for w in warnings
        if w.code is CheckCode.CREDENTIAL_EXPIRING_SOON and w.credential is not None
    ]
    if reminders:
        lines += ["", "Credential reminder", *reminders]
    reply_by = format_local_datetime(shift.start - RESPONSE_WINDOW_BEFORE_SHIFT)
    lines += [
        "",
        f"Please reply by {reply_by} ({shift.timezone}) to confirm your interest.",
        "",
        "Thank you,",
        "Staffing Operations Team",
    ]
    return OutreachDraft(
        draft_id=draft_id_for(shift.shift_id, clinician.id),
        shift_id=shift.shift_id,
        clinician_id=clinician.id,
        subject=subject,
        body="\n".join(lines),
    )


def unit_label(unit: Unit) -> str:
    return _UNIT_LABELS.get(unit, unit.value)


def _short_date(moment: datetime) -> str:
    return f"{moment:%a, %b} {moment.day}"


def format_local_datetime(moment: datetime) -> str:
    """E.g. 'Wed, Oct 14, 2026, 7:00 PM' in the moment's own (facility-local) offset."""
    clock = f"{moment:%I:%M %p}".lstrip("0")
    return f"{_short_date(moment)}, {moment.year}, {clock}"
