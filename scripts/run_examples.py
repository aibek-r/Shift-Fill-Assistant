"""Regenerate the example workflows in examples/ from live runs.

Usage: python scripts/run_examples.py   (needs OPENAI_API_KEY; costs a few cents)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from shift_assistant.agent.llm import unavailable_model
from shift_assistant.assistant import build_assistant
from shift_assistant.config import PROJECT_ROOT, Settings
from shift_assistant.contracts import StaffingRequest
from shift_assistant.rendering import render_markdown
from shift_assistant.retrieval.embedder import create_embedder

# The mock shifts are in October 2026; pinning "today" keeps relative dates meaningful.
REFERENCE_DATE = date(2026, 10, 2)


@dataclass(frozen=True)
class Example:
    slug: str
    request: str
    shift_id: str | None = None
    simulate_outage: bool = False


EXAMPLES = [
    Example(
        "01-icu-night-shift",
        "Find two ICU nurses for the St. Mary's night shift on October 14 and draft outreach "
        "for each.",
    ),
    Example(
        "02-picu-shortlist-with-warning",
        "Who can cover the PICU night shift at Bayview on Oct 18? Give me a shortlist of two "
        "with outreach drafts.",
    ),
    Example("03-ambiguous-request", "Can you find an ICU nurse for St. Mary's next week?"),
    Example("04-unknown-facility", "Find a nurse for Mercy General tomorrow night."),
    Example(
        "05-no-eligible-candidates",
        "We need a NICU nurse at Bayview Children's for the October 19 day shift.",
    ),
    Example(
        "06-llm-outage-fallback",
        "Fill the Lakeside med-surg day shift on October 16.",
        shift_id="SHF-2001",
        simulate_outage=True,
    ),
]


def main() -> int:
    settings = Settings(reference_date=REFERENCE_DATE)
    if not settings.llm_enabled:
        print("Set OPENAI_API_KEY to regenerate the examples.", file=sys.stderr)
        return 1
    embedder = create_embedder(settings.embedding_model, settings.cache_dir)
    live = build_assistant(settings, embedder=embedder)
    outage = build_assistant(settings, embedder=embedder, chat_model=unavailable_model())

    out_dir = PROJECT_ROOT / "examples"
    for example in EXAMPLES:
        assistant = outage if example.simulate_outage else live
        report = assistant.run(StaffingRequest(text=example.request, shift_id=example.shift_id))
        (out_dir / f"{example.slug}.md").write_text(render_markdown(report), encoding="utf-8")
        (out_dir / f"{example.slug}.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"{example.slug}: {report.status} ({report.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
