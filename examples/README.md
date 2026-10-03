# Example workflows

Each example has a readable report (`.md`) and the full structured output (`.json`). The JSON
includes the trace of every model and tool step. To regenerate them, run
`python scripts/run_examples.py`, which needs `OPENAI_API_KEY`. Model wording varies a little
between runs. Compliance verdicts do not.

1. **[ICU night shift](01-icu-night-shift.md).** This is the main path. The agent resolves the
   shift, retrieves the ICU profile, searches and vets all 9 ICU nurses, and drafts outreach. The
   compliance engine excludes 6 nurses, each with a reason code. Daniel Kim is eligible but has an
   expiring ACLS certificate, so the agent ranks him below two cleaner candidates. The report lists
   him under "Alternates", a list computed by code rather than by the model.
2. **[PICU shortlist with a warning](02-picu-shortlist-with-warning.md).** The coordinator asks
   for a shortlist of two for one opening. Liam Chen's PALS expires 22 days after the shift. The
   warning appears in his rationale, and his outreach draft gets an automatic renewal reminder.
   Emma Davis is excluded because California does not accept compact licenses.
3. **[Ambiguous request](03-ambiguous-request.md).** "An ICU nurse for St. Mary's next week"
   matches two shifts. Neither falls in the week after the pinned reference date. The agent asks
   instead of guessing.
4. **[Unknown facility](04-unknown-facility.md).** The tool error lists the known facilities, and
   the agent turns it into a clarifying question.
5. **[Nobody eligible](05-no-eligible-candidates.md).** All three NICU candidates fail. One has an
   expired NRP, one has too little experience, and one has an expired license. The agent says so
   plainly and does not stretch the rules.
6. **[LLM outage](06-llm-outage-fallback.md).** Every model call fails. The workflow degrades to
   the deterministic fallback, which applies the same compliance engine and templates. The report
   is labelled `mode: fallback`.

Hallucination repair, ungrounded-content stripping and step-budget exhaustion cannot be triggered
reliably with a live model. They are covered by the scripted tests in
`tests/test_agent_workflow.py`.
