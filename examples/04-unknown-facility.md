# Staffing report

- **Request:** Find a nurse for Mercy General tomorrow night.
- **Status:** `needs_clarification` (mode: `agent`)

## Summary

No open shift matched the request.

**Question for the coordinator:** Which facility did you mean for tomorrow night: St. Mary’s Medical Center, Lakeside Community Hospital, or Bayview Children’s Hospital?

## Verification

All references were verified against tool evidence.

## Trace

```text
[ 1] llm:model ok 1131ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts FAILED 0ms | ERROR: No facility matches 'Mercy General'. Known facilities: St. Mary's Medical Center (FAC-001); Lakeside Community Hospital (FAC-002); Bayview Children's Hospital (FAC-003).
[ 3] llm:model ok 2344ms | Planned: submit_recommendation
[ 4] validation:submit_recommendation ok 0ms | Submission accepted.
[ 5] verification:grounding ok 0ms | 0 recommendation(s) verified; 0 issue(s) enforced.
```

2 LLM calls, 1 tool calls, 3634 tokens, 3.5s.
