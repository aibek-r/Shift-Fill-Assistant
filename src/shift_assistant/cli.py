"""Command-line interface: `shift-assistant "Find two ICU nurses for ..."`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from shift_assistant.assistant import build_assistant
from shift_assistant.contracts import ReportStatus, StaffingRequest
from shift_assistant.rendering import format_event, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shift-assistant",
        description="Vet clinicians for an open shift and draft outreach.",
    )
    parser.add_argument("request", help="Staffing request in plain English.")
    parser.add_argument("--shift", dest="shift_id", help="Pin a specific shift ID, e.g. SHF-1001.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    parser.add_argument("--save", type=Path, help="Also write the JSON report to this file.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        request = StaffingRequest(text=args.request, shift_id=args.shift_id)
    except ValidationError as exc:
        parser.error(str(exc))

    assistant = build_assistant()
    if not assistant.llm_enabled:
        print("OPENAI_API_KEY is not set: running the deterministic fallback.", file=sys.stderr)
    report = assistant.run(request, on_event=lambda e: print(format_event(e), file=sys.stderr))

    print(report.model_dump_json(indent=2) if args.json else render_markdown(report))
    if args.save:
        args.save.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return 1 if report.status is ReportStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
