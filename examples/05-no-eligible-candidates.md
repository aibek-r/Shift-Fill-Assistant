# Staffing report

- **Request:** We need a NICU nurse at Bayview Children's for the October 19 day shift.
- **Status:** `no_eligible_candidates` (mode: `agent`)
- **Shift:** SHF-3002: NICU day shift at Bayview Children's Hospital (San Diego, CA), Mon, Oct 19, 2026, 7:00 AM to Mon, Oct 19, 2026, 7:00 PM (America/Los_Angeles), 1 position(s) open

## Summary

3 candidates evaluated, covering the shift's full candidate pool: 0 eligible, 3 excluded. Nobody is eligible, so no one was shortlisted.

**Agent notes:** The open NICU day shift at Bayview Children's Hospital in San Diego requires a California RN license, BLS, NRP, and at least 2 years of NICU experience. The clinicians found for this shift were not eligible: one had insufficient NICU experience, one had an expired NRP credential, and one had an expired RN license. Because of those blockers, no clinician can be recommended for this shift.

## Excluded candidates

| Clinician | Reasons |
| --- | --- |
| Ava Thompson (C-119) | `INSUFFICIENT_EXPERIENCE` 1 years of experience; NICU requires 2. |
| Isabella Garcia (C-116) | `CREDENTIAL_EXPIRED` NRP expires 2026-09-30, before the shift ends on 2026-10-19. |
| Lucas Moore (C-120) | `CREDENTIAL_EXPIRED` RN_LICENSE expires 2026-08-31, before the shift ends on 2026-10-19. |

## Verification

All references were verified against tool evidence.

## Trace

```text
[ 1] llm:model ok 970ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 1ms | {"facility": "Bayview Children's", "unit": "NICU", "start_date": "2026-10-19", "shift_id": null}
[ 3] llm:model ok 1257ms | Planned: search_facility_policies
[ 4] tool:search_facility_policies ok 24ms | {"facility_id": "FAC-003", "query": "NICU unit preferences and day shift arrival logistics or outreach rules", "top_k": 4}
[ 5] llm:model ok 1496ms | Planned: search_clinicians
[ 6] tool:search_clinicians ok 27ms | {"shift_id": "SHF-3002", "query": "NICU RN day shift California RN BLS NRP at least 2 years NICU experience", "limit": 10}
[ 7] llm:model ok 891ms | Planned: evaluate_candidates
[ 8] tool:evaluate_candidates ok 0ms | {"shift_id": "SHF-3002", "clinician_ids": ["C-119", "C-116", "C-120"]}
[ 9] llm:model ok 2781ms | Planned: submit_recommendation
[10] validation:submit_recommendation ok 0ms | Submission accepted.
[11] verification:grounding ok 0ms | 0 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 4 tool calls, 10508 tokens, 7.5s.
