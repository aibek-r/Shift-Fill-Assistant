# Validation methods

How the project is checked, and what each method can and cannot show.

## Offline tests (`pytest`)

All tests run offline. A scripted chat model replays fixed tool calls and submissions, and a
hashing embedder stands in for the sentence-embedding model, so no API key or download is
needed. They cover:

- **Eligibility:** every blocker type, credential warnings and the expiry boundary on the
  shift's last day.
- **Retrieval:** chunking, ranking, facility-scoped policy search and the keyword fallback.
- **Tools:** argument validation, readable errors, contained exceptions, privacy of search
  results, outreach refusal for ineligible clinicians and output truncation.
- **Workflow:** the ReAct loop, repair feedback, enforcement when repairs run out, deterministic
  completion, needs_review outcomes, fallbacks, pinned shifts and relative dates.
- **Model budget:** a fake monotonic clock covers budget exhaustion before a call, retries
  stopping at the deadline, backoff limits, late answers and safe recovery. An adapter test
  intercepts the HTTP transport to confirm that SDK retries are disabled and that each request
  carries the shortened timeout. No request leaves the machine.
- **Fallback shift resolution:** unique and multiple matches, unknown facilities, typed fields
  overriding text, yearless future and past dates, relative dates and facility time zones.
- **Structured preferences:** absent, matching, conflicting and explicitly flexible preferences.
- **Outreach notes:** every suggested sentence passes, notes in the writer's own words pass,
  each blocked category is reported with the exact text, several violations in one note are
  all listed, and both the model path (fix once, then the default note) and the coordinator
  path use the same check.
- **Reporting and review:** counts match the report lists, status completion conditions, edits
  revalidated, approval withdrawn on edit, and JSON exports matching saved state.
- **UI:** headless Streamlit `AppTest` runs real widgets and callbacks, including needs_review
  rendering and provenance labels. Visual layout and browser file downloads are not checked.

Scripted tests prove control flow and safeguards, not the live model's judgement.

## Offline evaluation (`python -m evals.run`)

Ten cases run through the scripted agent and the rules-only fallback, scored against
expectations derived from the mock records. See [design.md](design.md#offline-evaluation) for
what is scored and what the results do not show. Results are written to `evals/results/`.

## Static checks

```bash
ruff check src app scripts tests evals
ruff format --check src app scripts tests evals
mypy --strict src app scripts tests evals
```

## Live model checks

`scripts/run_examples.py` regenerates the saved examples with the live model, and
`python -m evals.run --live` runs the evaluation cases against it. Both make paid API calls and
need `OPENAI_API_KEY`. The saved agent examples were produced before the latest changes, and the
current code has not been run against the live model (see `examples/README.md`).
`python scripts/run_examples.py --offline` regenerates only the rules-only outage example.

## Not verified here

- Live model behavior with the current prompts, completion step and retry policy.
- Retrieval quality with the real embedding model.
- The Docker image (the Docker daemon was not running).
- Visual layout in a browser.
