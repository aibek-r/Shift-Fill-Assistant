# Staffing report

- **Request:** We need a NICU nurse at Bayview Children's for the October 19 day shift.
- **Status:** `no_eligible_candidates` (mode: `agent`)
- **Shift:** SHF-3002: NICU day shift at Bayview Children's Hospital (San Diego, CA), Mon, Oct 19, 2026, 7:00 AM to Mon, Oct 19, 2026, 7:00 PM (America/Los_Angeles), 1 position(s) open

## Summary

3 candidates evaluated, covering the shift's full candidate pool: 0 eligible, 3 excluded. Nobody is eligible, so no one was shortlisted.

## Excluded candidates

| Clinician | Reasons |
| --- | --- |
| Isabella Garcia (C-116) | `CREDENTIAL_EXPIRED` NRP expires 2026-09-30, before the shift ends on 2026-10-19. |
| Ava Thompson (C-119) | `INSUFFICIENT_EXPERIENCE` 1 years of experience; NICU requires 2. |
| Lucas Moore (C-120) | `CREDENTIAL_EXPIRED` RN_LICENSE expires 2026-08-31, before the shift ends on 2026-10-19. |

## Verification

All references were verified against tool evidence.

## Trace

```text
[ 1] llm:model ok 972ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 1ms | {"facility": "Bayview Children's", "unit": "NICU", "start_date": "2026-10-19", "shift_id": null}
[ 3] llm:model ok 1371ms | Planned: search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 23ms | {"facility_id": "FAC-003", "query": "NICU unit preferences and day shift arrival logistics", "top_k": 5}
[ 5] tool:search_clinicians ok 28ms | {"shift_id": "SHF-3002", "query": "NICU RN, day shift, neonatal experience, NICU certifications, Bayview Children's preferences", "limit": 10}
[ 6] llm:model ok 1199ms | Planned: evaluate_candidates
[ 7] tool:evaluate_candidates ok 0ms | {"shift_id": "SHF-3002", "clinician_ids": ["C-116", "C-119", "C-120"]}
[ 8] llm:model ok 1414ms | Planned: submit_recommendation
[ 9] validation:submit_recommendation ok 0ms | Submission accepted.
[10] completion:rules ok 0ms | Nothing to complete.
[11] verification:grounding ok 0ms | 0 recommendation(s) verified; 0 issue(s) enforced.
```

4 LLM calls, 4 tool calls, 9375 tokens, 5.0s.
