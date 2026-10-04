# Design notes

Detailed design decisions and trade-offs. The README keeps the overview and setup.

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
