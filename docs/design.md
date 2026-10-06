# Design notes

How the Shift Fill Assistant works, and the decisions and trade-offs behind it. The README keeps
the overview and setup.

Contents: [front door](#front-door-input-guard-and-intent-router) ·
[architecture and workflow](#architecture-and-workflow) ·
[boundaries](#what-code-decides-and-what-the-model-decides) ·
[statuses](#report-status-and-completion-conditions) ·
[completion and provenance](#deterministic-completion) ·
[model budget](#model-execution-budget) · [fallback resolution](#fallback-shift-resolution) ·
[preferences](#shift-preferences) · [outreach notes](#outreach-notes) ·
[evaluation](#offline-evaluation) · [limitations](#known-limitations-and-defects)

## Front door: input guard and intent router

`ShiftFillAssistant.ask(AssistantRequest) -> AssistantResponse` handles every coordinator
message: input guard, intent router, then exactly one handler. Before it existed, every message
was forced into the staffing workflow, whose model must finish with `submit_recommendation`
(`tool_choice="required"`), so "hi" or "what is the weather?" could only end in a staffing
clarification. The agent is unchanged; such messages no longer reach it.

1. **Input guard** (`guards/input_guard.py`). Folds Unicode compatibility forms (NFKC), turns
   `\r\n` into `\n`, and removes control, zero-width and text-direction characters, which can
   hide text from a reader while a model still reads it. Every later step sees only the cleaned
   text. Length is limited by the contract (2,000 characters). Injection, personal-data and
   rate-limit checks are not built yet; they will block from here.
2. **Intent router** (`router.py`), in order:
   - Fast rules, no AI: empty text, greetings, thanks and help questions ("what can you do") that
     make up the whole message. "Hi, find two ICU nurses ..." is not caught here.
   - The router model: one structured-output call (`RouterOutput`, strict JSON schema, no
     tools) returning an intent, a confidence, a reason and entities (facility, unit, shift
     date, clinician name, shift ID). The output is untrusted: the confidence is clamped, a
     reason that does not fit the intent is replaced by the intent's default, malformed dates and
     shift IDs are dropped, and facility, clinician and shift entities that do not appear in the
     message are dropped. It runs once with `ROUTER_TIMEOUT_SECONDS`; any failure or invalid
     output falls through to the keyword rules, and only the exception class is logged.
   - Keyword rules (`keyword_route`), used without an API key or after a router-model failure.
     Medical-advice and legal-advice patterns come first, then one pattern set per in-scope
     intent and an off-topic list. One clear match scores 0.85; several in-scope matches, or
     in-scope plus off-topic, score 0.5-0.6; no match scores 0.4. A pinned shift or typed shift
     details make a staffing request likely, but a message that names nothing about staffing
     ("x") still gets a question.
3. **Handler.** Below `ROUTER_MIN_CONFIDENCE` (0.7) the reply is one clarifying question.
   Otherwise:

| Intent | Reply (`kind`) |
| --- | --- |
| `help` | Help template: what the assistant can do, with working example requests (`help`) |
| `out_of_scope` | Polite refusal plus capabilities; medical and legal questions are referred to a clinician or the legal team (`refusal`) |
| `blocked` | Short refusal (`refusal`) |
| `fill_shift` | The staffing workflow below, unchanged; its `StaffingReport` is kept whole (`staffing_report`) |
| `credential_check`, `eligibility_check`, `shift_lookup`, `policy_question` | Recognized, answered with "not available yet" (`help`) until their read-only handlers exist |

Every reply other than a staffing report is a fixed template in `templates.py`. The router only
classifies: router entities are hints for future handlers, and the staffing workflow still
parses the original text and typed fields, so a routing mistake cannot change which shift is
staffed. Each response records the routing decision (`routing.method`, `confidence`,
`fallback_reason`) for evaluation. Logs carry the intent, method and confidence, never the
message text.

## Architecture and workflow

A request is a `StaffingRequest` (`contracts.py`): free text plus optional typed fields
(`shift_id`, `facility`, `unit`, `start_date`, `requested_count`, `draft_outreach`). Common
phrases in the text fill `requested_count` ("find two nurses") and `draft_outreach` ("without
outreach") when they are not set explicitly. The request runs through a LangGraph state machine
(`agent/graph.py`) and always ends in a typed `StaffingReport`.

| Node | Role |
| --- | --- |
| `agent` | Calls the model inside the model execution budget. The model must answer with tool calls (`tool_choice="required"`). |
| `tools` | Runs the tool calls through a registry that validates arguments and never raises, and records results in the run's `EvidenceLedger`. It enforces a pinned shift, refuses `draft_outreach` when no outreach was requested, rejects a submission mixed with other calls, and applies the outreach-note retry rule. |
| `validate` | Parses `submit_recommendation` into an `AgentSubmission` and runs `check_grounding`. Problems go back to the model as a tool error, up to `MAX_REPAIR_ATTEMPTS`. |
| `complete` | Deterministic completion of mandatory work the model left undone. |
| `verify` | Enforces grounding and builds the report from evidence. |
| `fallback` | Builds a rules-only report when the model is missing or fails, a step or time budget runs out, or submissions stay unusable. |

Routing: `agent` goes to `tools` for any non-submit or malformed call, and to `validate` for a
lone submission (or no tool call, which earns a nudge). `validate` goes back to `agent` while
fixable problems and repairs remain, to `complete` when the submission is accepted or usable
after repairs run out, and to `fallback` when it is rejected after repairs run out. `complete`
always continues to `verify`.

**Tools** (`tools/`): `find_open_shifts`; `search_facility_policies` (RAG over facility
handbooks, one chunk per `##` section, limited to the facility and global policies, with chunk
IDs as citations); `search_clinicians` (semantic ranking over profiles; it also records the
shift's whole role-and-specialty pool); `evaluate_candidates` (the eligibility engine); and
`draft_outreach` (eligible clinicians only, note rules, template). Search results omit contact
details and license numbers.

| Area | Modules |
| --- | --- |
| Front door | `guards/input_guard.py`, `router.py` (fast rules, router model, keyword rules), `templates.py` (help, refusals, questions, input errors) |
| Contracts and intent | `contracts.py` (assistant request and response, routing decision, staffing request and report, statuses, provenance), `intent.py` (counts, outreach intent, dates, units, shift period) |
| Domain and data | `domain/models.py`, `domain/eligibility.py`, `repository.py`, `data/` |
| Retrieval | `retrieval/embedder.py` (local `bge-small` via fastembed, with a keyword `HashingEmbedder` fallback), `vector_index.py`, `knowledge.py` |
| Tools | `tools/schemas.py`, `toolkit.py`, `registry.py`, `evidence.py`, `outreach.py` (draft template), `facts.py` (explanations, `period_fit`), `notes.py` (note rules) |
| Agent | `agent/graph.py`, `state.py`, `prompts.py`, `submission.py`, `llm.py` (model factory, budget, retries) |
| Reliability | `reliability/grounding.py`, `completion.py`, `verifier.py`, `reporting.py` (status rules, summaries, rule order), `resolution.py` (fallback shift matching), `fallback.py` |
| Interfaces | `app/streamlit_app.py`, `cli.py`, `review.py` (edit and approval state), `rendering.py` (Markdown) |
| Tooling | `evals/` (offline harness), `scripts/run_examples.py`, `tests/` |

**Interfaces.**

- **Streamlit UI:** a chat view (`st.chat_message`) above the message form, an optional shift
  selector, example requests, a "New conversation" button, a simulated-outage toggle (which also
  takes down the router model) and live progress. Help, refusal and clarification replies show
  their template text and clickable example requests. Only the newest staffing report is
  interactive; earlier ones collapse to a one-line summary, so no approval carries over. The
  report shows a status banner, action items, counts, and
  Recommendations / Alternates / Excluded tabs. Clarifications can offer facility cards. Each
  draft has an editor with one-click suggestions and approval. Technical details hold the
  verification issues, the trace and a JSON download that includes saved edits and approval
  states.
- **CLI:** `shift-assistant "<message>" [--shift --facility --unit --date --json --save]`
  answers through `ask`, prints Markdown or the `AssistantResponse` JSON, exits with 1 for a
  `failed` staffing report, and reports invalid input in plain English (exit code 2).
- **Report:** status, mode, a code-built summary, the shift, recommendations with provenance,
  alternates, exclusions with reason codes, coverage counts, a completion record, issues, a
  trace and metrics.

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
  policies. A pinned shift cannot be swapped, and a shift outside a supported relative-date
  window ("next week") is rejected. Other request details are **not** yet checked against the
  chosen shift (see [known defects](#known-defects-reproduced-offline)).
- **Rendering.** Names, warnings, credential badges, explanations, citation text and outreach
  facts come from recorded evidence, not model prose. Model rationales and summaries are never
  displayed. The only free text in an outreach draft is a short personal note, filtered by
  deterministic content rules ([below](#outreach-notes)). Pay rates, contact details, license
  numbers and other clinicians' information are never added, and editing an approved draft
  withdraws the approval.
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
| `needs_clarification` | The request does not identify one shift. |
| `failed` | No usable answer, for example a submission for the wrong pinned shift, or a pinned shift that does not exist. |

The "relevant pool" is the repository's role-and-specialty query for the shift
(`StaffingRepository.candidate_pool`), the same query `search_clinicians` records. The shortlist
size is the requested count, or the shift's open positions when none was requested.

## Deterministic completion

The graph runs a `complete` step after validation succeeds or repair attempts run out, and
before `verify`. It never runs after a rejected submission (wrong pinned shift, unknown shift,
dates outside a requested relative window); those go to the fallback. Clarifications skip it.

Completion reuses existing helpers rather than adding new logic:

1. If `search_clinicians` was never called, it computes the pool with the repository query and
   records `pool_determined_by_code`.
2. It vets every unvetted pool member with the same `EligibilityEngine` call the tools use.
3. It keeps valid model picks in the model's order. If the shortlist is short, it appends
   eligible clinicians in the fallback's rule order (fewest credential warnings, then
   experience), never duplicates anyone, and stops at `min(requested, MAX_RECOMMENDATIONS)`.
4. Only when outreach was requested, it drafts the standard template (the default friendly
   note plus recorded facts) for each verified recommendation without a valid draft.

Everything it produces goes into the `EvidenceLedger` and the submission, so `check_grounding`
and the verifier validate it exactly like model-produced evidence. If a required check or
draft cannot run, completion leaves it undone; the verifier then reports `INCOMPLETE_VETTING` or
`MISSING_OUTREACH` plus a `COMPLETION_UNRESOLVED` issue, and the status is `needs_review`. The
fallback handles a failed check or draft the same way.

`TOO_MANY_CANDIDATES` counts verified recommendations rather than list positions, so a
submission such as `[ineligible, A, B]` with a target of 2 keeps both A and B.

### Provenance

- `CandidateRecommendation.selected_by` is `model` or `code`; `outreach_by` says whether the
  draft came from the model's `draft_outreach` call or was drafted by code. In fallback mode
  everything is `code`.
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

`MAX_RUN_SECONDS` (default 180) is a **model execution budget**, not a deadline for the whole
workflow.

- At the start of a run, the assistant sets one deadline on a monotonic clock. Every model call,
  retry and backoff must start before it.
- SDK retries are disabled (`max_retries=0`). `agent/llm.py::invoke_within_budget` retries only
  transient errors the OpenAI adapter reports: rate limits (429), timeouts, dropped connections
  and server errors 500, 502, 503 and 504. Retries are capped by `LLM_MAX_RETRIES` (default 3),
  with exponential backoff of 1, 2, 4 and at most 8 seconds.
- Before each call or retry it computes the remaining budget. Each call's timeout is
  `min(LLM_TIMEOUT_SECONDS, remaining)` (default 60 seconds). A backoff that would end at or
  after the deadline is not taken.
- When a call returns, the deadline is checked again. An answer that arrives late is discarded,
  even if it is a valid submission.
- When the budget is spent, no further model work starts. The workflow hands over to the
  deterministic fallback, which applies the same eligibility engine and templates.
  `MAX_AGENT_STEPS` (default 12) separately caps the number of model calls.

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

When the fallback runs (no API key, or the agent failed), `reliability/resolution.py` resolves
the shift with rules, in this order:

1. A pinned shift (`shift_id`) always wins. A pinned shift that does not exist is `failed`.
2. Explicit typed request fields: `facility`, `unit` and `start_date`. Each overrides
   conflicting request text. A typed facility that matches no known facility is asked about.
3. Conservative parsing of the request text:
   - **Facility:** a facility ID, or a distinctive whole word of a known facility name
     ("Mary's", "Lakeside", "Bayview"). Prefixes and generic words such as "hospital" never
     count. A name that matches no known facility is not recognized at all, so the text counts
     as naming no facility.
   - **Unit:** a short synonym list: `ICU`/"intensive care", `PICU`/"pediatric ICU" or
     "pediatric intensive care", `NICU`/"neonatal ICU" or "neonatal intensive care",
     `ED`/`ER`/"emergency (department|room)" (uppercase `ED`/`ER` only, so the name "Ed" does
     not count), "tele"/"telemetry", "med-surg"/"medical-surgical". "Critical care" is ambiguous
     between adult and pediatric units and is not mapped. Other words, such as "oncology", are
     ignored, so the text counts as naming no unit.
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
   lists the known facilities when none was recognized.

Because unrecognized facility and unit words are ignored rather than rejected, a request that
names an unknown facility or unit can still match exactly one shift and be staffed. This is a
[known defect](#known-defects-reproduced-offline).

**Dates are facility-local shift start dates**, as in `find_open_shifts`. Relative dates use the
facility's own "today": the pinned `REFERENCE_DATE` when set, otherwise the current date in the
facility's time zone. The facility is resolved before relative dates are applied.

**Yearless dates** take the reference year. If that date has already passed, the report asks
for the date instead of moving it to next year: "Oct 14" on October 20 is a question, not a
request for October 2027. Impossible dates ("Oct 32", "2/31") are asked about as well.

**In agent mode** the model resolves the shift with `find_open_shifts`. Typed fields are passed
to it as overrides, and its prompt and `REQUESTED_DATE_MISMATCH` check use the server's date (or
`REFERENCE_DATE`) and the text's relative-date window. With the pinned reference date the two
paths agree on "today".

## Shift preferences

Clinician records have two validated, self-reported fields: `shift_preference` (`day`,
`night` or null) and `open_to` (a list of `day`/`night`). The fixtures were transcribed only from
what each profile states: "prefers", "eager for" and "looking for" became a preference; "open to",
"available for" and "comfortable with" became openness. Weekend availability is out of scope and
was not recorded. Profiles that mention neither have `null` and `[]`.

- The free-text profile is indexed for semantic search, but it is never quoted in explanations
  or outreach, and no preference is extracted from it by phrase matching.
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
keeps its conservative order: fewest credential warnings, then experience. A preference, then
openness, only **breaks ties** after both, so a self-reported preference never outranks
credential risk or recorded experience. The rule-based fallback, and the rule-based additions
from deterministic completion, therefore rank more by risk than by fit. The model's ordering is
advisory: code does not check it against the rubric.

## Outreach notes

The model and coordinators write the personal note in their own words: 1-4 sentences, at most
400 characters. Code adds everything factual around it (recorded experience, a matching shift
preference, shift details, credential reminders and the reply deadline).
`tools/notes.py::note_violations` blocks pay or money, numbers, dates and times, contact
details, other clinicians' names, credentials and qualifications, claims about the clinician
("you prefer nights"), logistics and promises. Each problem is reported with the exact text and
a reason, for example `Remove "$55/hour": pay can't appear in outreach.` The five suggested
sentences (`FRIENDLY_NOTES`) all pass, and the first is the default note.

- **One check, server-side.** `StaffingToolkit.create_draft` runs it for the model's
  `draft_outreach` calls and for coordinator edits (`revise_outreach`), so neither the model nor
  the UI is trusted to have filtered the note.
- **Model path.** A rejected note comes back as a tool error listing every violation, and the
  model may fix it once. A second rejection for the same clinician drafts with the default note
  instead. If the model never drafts, deterministic completion uses the default note. Rejected
  model text is kept out of the exported trace.
- **Coordinator path.** The editor offers the suggested sentences as one-click additions, lists
  violations under the text box and keeps the typed text for fixing. Rejected text is never
  saved or exported, Cancel restores the saved note, and editing withdraws approval.

**This filter is a guardrail, not a guarantee.** Fixed patterns catch common unsafe content but
can miss paraphrases ("ninety-ish an hour", an unlisted credential) and can occasionally block
harmless wording ("first-rate"). A coordinator's approval of each draft stays the final check;
nothing is sent automatically.

## Offline evaluation

`python -m evals.run` runs 10 cases (`evals/cases.py`) through up to two labelled execution
paths: the **agent with a scripted model** and the **rules-only fallback** (no API key). It
writes `evals/results/<timestamp>.md` and exits non-zero if any check fails. `--case` limits the
run to named cases, and `--show` also prints each run's full report.

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
  embedding model, and refuses to start without `OPENAI_API_KEY`. It makes paid API calls. Its
  report reuses the offline explanatory notes, including the note that latency is offline, so
  read its tables rather than that text.

**What it does not show.** Scripted runs validate orchestration and safeguards: tool routing,
validation, completion, verification, fallback and status logic. They do not measure live model
reasoning, ranking quality or real retrieval quality. The cases do not cover requests that name
an unknown facility or unit together with a specific date, or shifts that contradict explicit
request details, which is how the defects below went unnoticed. The injection case shows that
the safeguards hold when a scripted model obeys one malicious profile instruction; it is not
proof of general prompt-injection resistance.

## Known limitations and defects

### Known defects (reproduced offline)

These were reproduced without an API key, with the rules-only fallback or a scripted model:

1. **Fallback ignores unknown facility and unit words.** "Find two ICU nurses for Mercy General
   October 14 night shift without outreach" and "Find two oncology nurses at St. Mary's October
   14 without outreach" both return `ready` for St. Mary's SHF-1001 instead of asking. The
   resolver treats an unrecognized facility or unit as unspecified (`reliability/resolution.py`).
2. **Grounding does not check that the chosen shift matches the request.** A scripted model that
   submits SHF-1001 (October 14, night) for a request naming the October 16 day shift, or for
   typed fields naming Bayview, PICU and October 18, gets a `ready` agent report.
   `check_grounding` enforces only the pinned shift and supported relative-date windows.
3. **Typed `start_date` does not override relative text in agent mode.** With "tomorrow" in the
   text and a typed start date of October 14, the agent's correct submission for SHF-1001 is
   rejected as outside "tomorrow" (October 3), and the run recovers only through the fallback.
   The fallback honors the typed date.

### Limitations

- **The router model is untested live.** Offline tests use a fake that returns `RouterOutput`
  values; the strict schema was checked with the OpenAI SDK's converter, not against the API.
  Keyword routing is deliberately narrow: it asks rather than guesses, so unusual phrasing gets
  a question without an API key.
- **Live behavior of the current code is unverified here.** This repository contains no
  live-model results for the current code. Deterministic completion, the budget and retry
  policy, the preference rubric, the free-text note rules and the prompt changes were tested with
  a scripted model and keyword retrieval. The adapter test confirms only that SDK retries are
  off and that the shortened timeout reaches the HTTP request.
- **Saved agent examples predate the reliability changes** (see `examples/README.md`).
- **Ranking is advisory.** The model's order among eligible clinicians can vary between runs and
  is not checked against the rubric; eligibility and warnings are unaffected.
- **Retrieval quality** with the real `bge-small` model is not evaluated by the harness.
- **Text parsing is deliberately narrow.** Shortlist size, outreach intent, facility, unit and
  date extraction handle common phrasing only; callers can set typed fields for anything else.
  "M/D" dates are read month-first.
- **The budget is not a hard wall-clock limit.** A call in flight can overrun the deadline
  before it is discarded, and deterministic steps after the deadline are not time-limited.
- **The note filter is a guardrail**, not a guarantee; see [outreach notes](#outreach-notes).
- **Mock data only.** Credentials are not verified with an issuing authority. Free-text profiles
  still reach the model and would need PII redaction in production. Authentication, persistent
  audit records and real message delivery are out of scope.
- **Docker** is documented but was not verified in this environment (the Docker daemon was not
  running).
