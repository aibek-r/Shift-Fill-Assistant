# Design notes

Detailed design decisions and trade-offs. The README keeps the overview and setup.

Contents: [boundaries](#what-code-decides-and-what-the-model-decides) ·
[statuses](#report-status-and-completion-conditions) ·
[completion and provenance](#deterministic-completion) ·
[model budget](#model-execution-budget) · [fallback resolution](#fallback-shift-resolution) ·
[preferences](#shift-preferences) · [evaluation](#offline-evaluation) ·
[limitations](#known-limitations-and-unverified-behavior)

## What code decides and what the model decides

The model plans the workflow, chooses tool calls, and ranks eligible clinicians. Code decides
everything a coordinator must be able to trust:

- **Eligibility.** `EligibilityEngine` (`domain/eligibility.py`) is the only authority:
  licensure for the facility state, required certifications valid through the shift end,
  experience, double booking and rest time. The model cannot override it. `draft_outreach`
  refuses ineligible clinicians, and the verifier drops any ineligible clinician who reaches the
  answer, so ineligible clinicians never appear in recommendations or receive drafts.
- **Grounding.** Every shift, clinician, citation and draft in an answer must exist in this
  run's `EvidenceLedger`. `check_grounding` runs twice: once as repair feedback to the model,
  then enforced by the verifier. Citations must belong to the shift's facility or the global
  policies, and a pinned shift cannot be swapped.
- **Rendering.** Names, warnings, credential badges, explanations, citation text and outreach
  facts come from recorded evidence, not model prose. Model rationales and summaries are never
  displayed. Outreach notes are limited to five approved friendly sentences. Pay rates, contact
  details, license numbers and other clinicians' information are never added, and editing an
  approved draft withdraws the approval.
- **Status, counts and completion.** Code computes coverage counts, the summary and the status
  (below), and finishes mandatory work the model skipped.
- **Delivery.** Nothing is sent. Approving a draft records the coordinator's decision; no
  delivery integration exists, so nothing is ever reported as sent.

## Report status and completion conditions

`reliability/reporting.py::fill_status` decides the status of every staffing report, in both
agent and fallback mode. Counts alone are not enough: a status may only rule something out after
the relevant work has been done.

| Status | Condition |
| --- | --- |
| `ready` | The shift's whole candidate pool is known and vetted, the shortlist reaches the requested size, and every recommendation has a verified draft when outreach was requested. |
| `partial` | The pool is fully vetted, but fewer clinicians are eligible than requested, or the configured `MAX_RECOMMENDATIONS` is below the request. |
| `no_eligible_candidates` | The pool is known and fully vetted, and nobody is eligible. |
| `needs_review` | Mandatory work is unresolved: the pool is unknown, a pool member was never vetted, requested outreach is missing, or eligible clinicians were left off a short shortlist. Verified recommendations are kept. |
| `needs_clarification` | The request does not identify one shift (unchanged). |
| `failed` | No usable answer, for example a submission for the wrong pinned shift (unchanged). |

The "relevant pool" is the repository's role-and-specialty query for the shift
(`StaffingRepository.candidate_pool`), the same query `search_clinicians` records.

## Deterministic completion

The graph runs a `complete` step after validation succeeds or repair attempts run out, and
before `verify`. It never runs after a rejected submission (wrong shift, unknown shift, dates
outside the requested window); those still go to the fallback.

Completion reuses existing helpers rather than adding new logic:

1. If `search_clinicians` was never called, it computes the pool with the repository query and
   records `pool_determined_by_code`.
2. It vets every unvetted pool member with the same `EligibilityEngine` call the tools use.
3. It keeps valid model picks in the model's order. If the shortlist is short, it appends
   eligible clinicians in the fallback's rule order (fewest credential warnings, then
   experience), never duplicates anyone, and stops at `min(requested, MAX_RECOMMENDATIONS)`.
4. Only when outreach was requested, it drafts the standard template (approved friendly note
   plus recorded facts) for each verified recommendation without a valid draft.

Everything it produces goes into the `EvidenceLedger` and the submission, so `check_grounding`
and the verifier validate it exactly like model-produced evidence. If a required check or
draft cannot run, completion leaves it undone; the verifier then reports `INCOMPLETE_VETTING` or
`MISSING_OUTREACH` plus a `COMPLETION_UNRESOLVED` issue, and the status is `needs_review`.

`TOO_MANY_CANDIDATES` now counts verified recommendations rather than list positions, so a
submission such as `[ineligible, A, B]` with a target of 2 keeps both A and B.

### Provenance

- `CandidateRecommendation.selected_by` is `model` or `code`; `outreach_by` says whether the
  draft came from the model's `draft_outreach` call or was drafted by code.
- `StaffingReport.completion` lists what code completed (pool, vetted IDs, added IDs, drafted
  IDs). It is only present when completion did something. Problems completion repaired are not
  repeated as active issues; unresolved problems stay in `issues`.
- A mixed result keeps `mode: agent` because each deterministic addition is labelled in the
  JSON, the Markdown report and the UI ("Selected by rules", "Completed by rules").

### Trade-offs

- **The model gets the first chance to repair.** Incomplete vetting, missing drafts and short
  shortlists are still sent back as repair feedback. Completion only covers what is left after
  the repair budget, so a lazy model costs extra LLM calls before code steps in. The model may
  rank better than the rules, which is why it is asked first.
- **Code-appended clinicians are ranked by rules, not judgment.** They follow the fallback's
  order and are labelled, so a coordinator can tell them apart from the model's picks.
- **A model pick it never vetted can survive.** If the model recommends a pool member without
  calling `evaluate_candidates`, completion vets the whole pool and the verifier then accepts
  the pick, because the engine has now decided eligibility. Hallucinated IDs and clinicians
  outside the pool are still removed.
- **The model's "nobody is eligible" claim can be overridden.** Its summary is never shown;
  the report is built from verified evidence, including code additions.

## Model execution budget

`MAX_RUN_SECONDS` is a **model execution budget**, not a deadline for the whole workflow.

- At the start of a run, the assistant sets one deadline on a monotonic clock. Every model call,
  retry and backoff must start before it.
- SDK retries are disabled (`max_retries=0`). `agent/llm.py::invoke_within_budget` retries only
  transient errors the OpenAI adapter reports: rate limits (429), timeouts, dropped connections
  and server errors 500, 502, 503 and 504. Retries are capped by `LLM_MAX_RETRIES`, with
  exponential backoff of 1, 2, 4 and at most 8 seconds.
- Before each call or retry it computes the remaining budget. Each call's timeout is
  `min(LLM_TIMEOUT_SECONDS, remaining)`. A backoff that would end at or after the deadline is not
  taken.
- When a call returns, the deadline is checked again. An answer that arrives late is discarded,
  even if it is a valid submission.
- When the budget is spent, no further model work starts. The workflow hands over to the
  deterministic fallback, which applies the same eligibility engine and templates.

Tool execution between model calls counts toward elapsed time but is not interrupted.
Deterministic completion, verification and the fallback may run after the deadline; they are
local and fast, but they are not time-limited.

**Limits of the guarantee.** Model calls are synchronous. A call in flight can only be stopped by
its transport timeout, and HTTP timeouts bound individual connect, read and write waits rather
than total elapsed time. A slow, trickling response can therefore run somewhat past the deadline
before it is discarded. The deadline is strict about *starting* model work and about *accepting*
its output, not about wall-clock time inside one call.

**Trade-off: late answers are discarded.** A valid submission that arrives after the deadline is
thrown away in favor of the rules-only fallback. Keeping it would make the budget meaningless
under load, and the fallback is compliant (same engine, same templates), only less nuanced in
its ranking. The cost is that a slow but correct model answer is wasted.

## Fallback shift resolution

When the fallback runs without a pinned shift (no API key, or the agent failed),
`reliability/resolution.py` resolves the shift with rules, in this order:

1. A pinned shift (`shift_id`) always wins.
2. Explicit typed request fields: `facility`, `unit` and `start_date`. Each overrides
   conflicting request text. An unknown typed facility asks which facility to use.
3. Conservative parsing of the request text:
   - **Facility:** a facility ID, or a distinctive whole word of a facility name ("Mary's",
     "Lakeside", "Bayview"). Prefixes and generic words such as "hospital" never count.
   - **Unit:** a short synonym list: `ICU`/"intensive care", `PICU`/"pediatric ICU" or
     "pediatric intensive care", `NICU`/"neonatal ICU" or "neonatal intensive care",
     `ED`/`ER`/"emergency (department|room)" (uppercase `ED`/`ER` only, so the name "Ed" does
     not count), "tele"/"telemetry", "med-surg"/"medical-surgical". "Critical care" is ambiguous
     between adult and pediatric units and is not mapped.
   - **Period:** "day shift" or "night shift", only when exactly one appears.
   - **Dates:** today, tomorrow, this week and next week (Monday-Sunday weeks), plus explicit
     dates such as "Oct 14", "October 14th", "14 October", "10/14", "10/14/2026" and
     "2026-10-14". "May" must be capitalized, so the verb is not read as a month, and pairs such
     as "24/7" are not dates. Several dates or units are alternatives: a shift matching any of
     them qualifies.
4. If exactly one shift matches, it is staffed and the summary says what it was matched on. If
   the agent had narrowed the request to one of several matches before it failed, that shift is
   used. If several match, the report asks which one, listing them. If none match, the report
   says which details did not match, lists alternatives that differ only in date or period, and
   lists the known facilities when none was named. Missing details are never filled in.

**Dates are facility-local shift start dates**, as in `find_open_shifts`. Relative dates use the
facility's own "today": the pinned `REFERENCE_DATE` when set, otherwise the current date in the
facility's time zone. The facility is resolved before relative dates are applied.

**Yearless dates** take the reference year. If that date has already passed, the report asks
for the date instead of moving it to next year: "Oct 14" on October 20 is a question, not a
request for October 2027. Impossible dates ("Oct 32", "2/31") are asked about as well.

The agent path still uses the server's date (or `REFERENCE_DATE`) for its prompt and for the
`REQUESTED_DATE_MISMATCH` check; with the pinned reference date the two paths agree.

## Shift preferences

Clinician records have two validated, self-reported fields: `shift_preference` (`day`,
`night` or null) and `open_to` (a list of `day`/`night`). The fixtures were transcribed only from
what each profile states: "prefers", "eager for" and "looking for" became a preference; "open to",
"available for" and "comfortable with" became openness. Weekend availability is out of scope and
was not recorded. Profiles that mention neither have `null` and `[]`.

- The free-text profile is still indexed for semantic search, but it is never quoted in
  explanations or outreach. The old phrase-matching extraction is gone.
- Code computes `period_fit` for the offered shift: a matching preference (`prefers_night`),
  explicit openness to the offered period (`open_to_night`), or nothing. A preference for the
  other period produces nothing, so it is never presented as support. Grace Liu prefers days but
  is open to nights; for a night shift she is described only as "open to night shifts".
- Explanations and outreach mention only `period_fit`. The model sees the structured fields in
  `search_clinicians` and `period_fit` in `evaluate_candidates`, and its rubric uses them.
- Preferences never affect eligibility.

**The agent and the fallback weigh preferences differently, on purpose.** The agent's rubric
ranks by unit fit, then `period_fit`, then credential warnings, then experience. It can combine
soft signals with the facility's policy context, and a coordinator reviews its picks. The fallback
keeps its existing conservative order: fewest credential warnings, then experience. A preference,
then openness, only **breaks ties** after both, so a self-reported preference never outranks
credential risk or recorded experience. The rule-based fallback, and the rule-based additions
from deterministic completion, therefore rank more by risk than by fit.

## Offline evaluation

`python -m evals.run` runs 10 cases (`evals/cases.py`) through up to two labelled execution
paths: the **agent with a scripted model** and the **rules-only fallback** (no API key). It
writes `evals/results/<timestamp>.md` and exits non-zero if any check fails.

- **Expectations are independent of the scripts.** Each case states, from the mock records, the
  status, the shift, the full pool's eligible clinicians, the accepted shortlist orders (several
  when the evidence does not establish one order) and the outreach intent. Scripts only fix what
  the "model" does, including lazy and compromised turns.
- **Scored per run:** status, shift resolution, eligibility (recommendations within the eligible
  set, and the eligible set matched exactly only when the whole pool was vetted, so an evaluated
  subset is never mistaken for the pool), ranking, outreach, surfaced credential warnings, and
  privacy (no contact details, license numbers, forbidden text, or other clinicians' names in a
  draft).
- **Reported per path:** grounding issues, submissions failing validation (repairs),
  deterministic completion, fallback rate, median latency and token usage. Scripted and rules-only
  runs report no token usage, so it is shown as unavailable, not zero.
- **Frozen inputs:** each case pins its reference date, and runs use the `HashingEmbedder`.
  Offline runs never read `.env` or the API key.
- `python -m evals.run --live` runs the agent path against the real model and the local
  embedding model, and refuses to start without `OPENAI_API_KEY`. It has not been run.

**What it does not show.** Scripted runs validate orchestration and safeguards: tool routing,
validation, completion, verification, fallback and status logic. They do not measure live model
reasoning, ranking quality or real retrieval quality. The injection case shows that the
safeguards hold when a scripted model obeys one malicious profile instruction; it is not proof of
general prompt-injection resistance. Offline latency says nothing about live latency.

## Known limitations and unverified behavior

- **Live behavior after these changes is unverified.** Deterministic completion, the budget and
  retry policy, the structured-preference rubric and the prompt changes were tested only with a
  scripted model and keyword (`HashingEmbedder`) retrieval. How often the real model leaves work
  for completion, how it ranks with the new rubric, and real retry and timeout behavior have not
  been measured. The adapter test confirms only that SDK retries are off and that the shortened
  timeout reaches the HTTP request.
- **Saved agent examples predate these changes** (see `examples/README.md`).
- **Retrieval quality** with the real `bge-small` model is not evaluated by the harness.
- **Text parsing is deliberately narrow.** Shortlist size, outreach intent, facility, unit and
  date extraction handle common phrasing only; callers can set typed fields for anything else.
  "M/D" dates are read month-first.
- **The budget is not a hard wall-clock limit.** A call in flight can overrun the deadline
  before it is discarded, and deterministic steps after the deadline are not time-limited.
- **Mock data only.** Credentials are not verified with an issuing authority. Free-text profiles
  still reach the model and would need PII redaction in production. Authentication, persistent
  audit records and real message delivery are out of scope.
- **Docker** is documented but was not verified in this environment (the Docker daemon was not
  running).
