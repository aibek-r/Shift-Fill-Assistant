"""Plain-text renderings of reports and trace events (CLI output and saved examples)."""

from __future__ import annotations

from shift_assistant.contracts import StaffingReport, TraceEvent
from shift_assistant.tools.outreach import format_local_datetime, unit_label
from shift_assistant.tools.schemas import ShiftSummary


def format_event(event: TraceEvent) -> str:
    status = "ok" if event.ok else "FAILED"
    timing = f" {event.duration_ms}ms" if event.duration_ms is not None else ""
    detail = f" | {event.detail}" if event.detail else ""
    return f"[{event.step:>2}] {event.kind}:{event.name} {status}{timing}{detail}"


def describe_shift(shift: ShiftSummary) -> str:
    return (
        f"{shift.shift_id}: {unit_label(shift.unit)} {shift.period} shift at "
        f"{shift.facility_name} ({shift.location}), {format_local_datetime(shift.start)} to "
        f"{format_local_datetime(shift.end)} ({shift.timezone}), "
        f"{shift.positions_open} position(s) open"
    )


def render_markdown(report: StaffingReport) -> str:
    lines = [
        "# Staffing report",
        "",
        f"- **Request:** {report.request.text}",
        f"- **Status:** `{report.status}` (mode: `{report.mode}`)",
    ]
    if report.shift:
        lines.append(f"- **Shift:** {describe_shift(report.shift)}")
    lines += ["", "## Summary", "", report.summary]
    if report.clarification_question:
        lines += ["", f"**Question for the coordinator:** {report.clarification_question}"]

    if report.recommendations:
        lines += ["", "## Recommendations"]
    for rec in report.recommendations:
        lines += [
            "",
            f"### {rec.rank}. {rec.clinician_name} ({rec.clinician_id})",
            "",
            rec.rationale,
        ]
        lines += [f"- **Warning:** {w.message}" for w in rec.warnings]
        lines += [f"- **Source:** `{c.chunk_id}` ({c.section})" for c in rec.citations]
        if rec.outreach:
            lines += [
                "",
                f"<details><summary>Outreach draft: {rec.outreach.subject}</summary>",
                "",
                "```text",
                rec.outreach.body,
                "```",
                "</details>",
            ]

    if report.alternates:
        lines += ["", "## Other eligible candidates (not shortlisted)", ""]
        lines += [
            f"- {a.clinician_name} ({a.clinician_id})"
            + "".join(f"; warning: {w.message}" for w in a.warnings)
            for a in report.alternates
        ]

    if report.excluded:
        lines += ["", "## Excluded candidates", "", "| Clinician | Reasons |", "| --- | --- |"]
        lines += [
            f"| {e.clinician_name} ({e.clinician_id}) | "
            f"{'; '.join(f'`{r.code}` {r.message}' for r in e.reasons)} |"
            for e in report.excluded
        ]

    lines += ["", "## Verification", ""]
    if report.issues:
        lines += [f"- `{i.severity}` `{i.code}`: {i.message}" for i in report.issues]
    else:
        lines.append("All references were verified against tool evidence.")

    m = report.metrics
    lines += [
        "",
        "## Trace",
        "",
        "```text",
        *(format_event(e) for e in report.trace),
        "```",
        "",
        f"{m.llm_calls} LLM calls, {m.tool_calls} tool calls, "
        f"{m.input_tokens + m.output_tokens} tokens, {m.duration_ms / 1000:.1f}s.",
    ]
    return "\n".join(lines) + "\n"
