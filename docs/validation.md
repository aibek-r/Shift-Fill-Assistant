# Main issue fixes and validation

Validated on October 3, 2026 with Python 3.13.15, Streamlit 1.65.0 and
`gpt-5.4-mini`. All staffing data used in paid calls was mocked.

## Changes

| Review finding | Result |
| --- | --- |
| Requested PICU shortlist of two returned one | Explicit count becomes typed request intent; incomplete submissions receive repair feedback. Fallback uses the same target. |
| One clinician for two positions was partial; three for a request of four was ready | Completion compares the shortlist with the requested count. Open positions are reported separately. |
| JSON kept the original outreach after editing | Export snapshots saved text, run ID and current approval status. Editing withdraws approval. |
| Final answer could reference a different pinned shift | Tool execution and final verification enforce the pin. A resolved pin cannot be replaced by a question about switching shifts. |
| Explanations changed preferences or invented qualifications | Final candidate explanations come from evaluation facts. Recognized preference clauses are quoted exactly and labelled self-reported. Unverified model notes are omitted. |
| Edited notes admitted unsupported pay, logistics, qualifications and other clinicians | Generated and edited notes use approved friendly sentences; recorded facts and logistics are added separately. Arbitrary factual note edits are rejected. |
| Old results survived invalid submissions or shift changes; missing policies were silent | Invalid submissions and shift/mode changes clear reports and approvals. Missing or empty facility/global policy documents produce a visible report warning. |

The six example JSON and Markdown reports were refreshed from the updated implementation.

## Checks

- 108 offline tests pass, including actual Streamlit widgets, callbacks, saved edits,
  approvals, export payloads, rejected edits, stale result clearing and fresh run state.
- Ruff lint, Ruff formatting and strict mypy checks pass for source, app, scripts and tests.
- The six refreshed example reports passed 85 independent checks against mock shift records,
  eligibility verdicts, warnings, source-backed explanations and re-rendered outreach.
- Paid model checks with real local `bge-small` embeddings passed: ICU shortlist,
  PICU shortlist with PALS warning, ambiguous request, unknown facility, no eligible NICU
  candidates, one clinician without outreach, four requested with only three eligible,
  conflicting pinned shift, missing policies, and a headless Streamlit PICU run with edit,
  approval and JSON export. A simulated outage also passed with the rules-only fallback.
- During live testing, the first conflicting-pin run asked to switch shifts. A new
  deterministic guard was added; the repeated live run completed the pinned ICU shift.
- Additional fix validation used an estimated **$0.127224**. Including the earlier review,
  estimated uncached API cost was **$0.453783**, below the authorized **$2 total cap**.
  This is a token-based estimate, not an invoice reconciliation.

## Limits

The browser connection was unavailable. Streamlit was checked through headless `AppTest`;
visual layout and a browser's actual file-download interaction remain unverified.

Count extraction intentionally handles common explicit phrases, rather than arbitrary language.
Callers can set typed request fields directly. Preference extraction omits unknown conditional
or negated wording instead of guessing. Outreach editing is intentionally restricted to the
suggested friendly sentences.

Ranking among eligible clinicians still varies with the model. The mock credentials and
profiles are not independently verified with an issuing authority. Production authentication,
persistent audit records, free-text PII redaction and real message delivery remain future work.
