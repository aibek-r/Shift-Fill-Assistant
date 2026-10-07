# Staffing report

- **Request:** Find two ICU nurses for the St. Mary's night shift on October 14 and draft outreach for each.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-1001: ICU night shift at St. Mary's Medical Center (Austin, TX), Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM (America/Chicago), 2 position(s) open

## Summary

9 candidates evaluated, covering the shift's full candidate pool: 3 eligible, 6 excluded. 2 eligible clinicians shortlisted for 2 open positions; 1 eligible alternate was not shortlisted. Requested shortlist: 2 of 2 clinicians.

## Recommendations

### 1. Maria Santos (C-101)

Passed the recorded compliance checks for this shift. Recorded experience: 6 years. Self-reported: prefers night shifts.

- **Selected by:** AI agent
- **Source:** `FAC-001#icu-unit-profile` (ICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft (requested by the AI agent): Open ICU night shift at St. Mary's Medical Center on Wed, Oct 14</summary>

```text
Hi Maria,

Hi Maria, we’d love to have you support this ICU shift. Your critical care background looks like a strong fit, and we’d be glad to have your help if you’re available.
Your recorded experience: 6 years.
Your profile says you prefer night shifts.

Shift details
- Facility: St. Mary's Medical Center (Austin, TX)
- Unit: ICU
- Time: Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM (America/Chicago)

Please reply by Mon, Oct 12, 2026, 7:00 PM (America/Chicago) to confirm your interest.

Thank you,
Staffing Operations Team
```
</details>

### 2. Grace Liu (C-107)

Passed the recorded compliance checks for this shift. Recorded experience: 5 years. Self-reported: is open to night shifts.

- **Selected by:** AI agent
- **Source:** `FAC-001#icu-unit-profile` (ICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft (requested by the AI agent): Open ICU night shift at St. Mary's Medical Center on Wed, Oct 14</summary>

```text
Hi Grace,

Hi Grace, we’d be glad to have you in mind for this ICU shift. Your critical care experience looks like a great match, and we hope you’ll consider it if available.
Your recorded experience: 5 years.
Your profile says you are open to night shifts.

Shift details
- Facility: St. Mary's Medical Center (Austin, TX)
- Unit: ICU
- Time: Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM (America/Chicago)

Please reply by Mon, Oct 12, 2026, 7:00 PM (America/Chicago) to confirm your interest.

Thank you,
Staffing Operations Team
```
</details>

## Alternates (eligible, not shortlisted)

- Daniel Kim (C-104); warning: ACLS expires 2026-11-01, 17 days after the shift. Request a renewal.

## Excluded candidates

| Clinician | Reasons |
| --- | --- |
| Sofia Martinez (C-109) | `SCHEDULE_CONFLICT` Already booked (ASG-502) 2026-10-14T19:00:00-05:00 to 2026-10-15T07:00:00-05:00, overlapping this shift. |
| James Okafor (C-102) | `CREDENTIAL_EXPIRED` ACLS expires 2026-10-10, before the shift ends on 2026-10-15. |
| Tom Brennan (C-106) | `LICENSE_NOT_VALID_IN_STATE` RN license jurisdiction (CA) is not valid in TX; needs TX or COMPACT. |
| Aisha Rahman (C-105) | `INSUFFICIENT_EXPERIENCE` 1 years of experience; ICU requires 2. |
| Priya Patel (C-103) | `INSUFFICIENT_REST` Only 0.0h between this shift and booking ASG-501; St. Mary's Medical Center requires 10h of rest. |
| Robert Diaz (C-108) | `INACTIVE` Clinician status is inactive. |

## Verification

All references were verified against tool evidence.

## Trace

```text
[ 1] llm:model ok 2871ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 0ms | {"facility": "St. Mary's", "unit": "ICU", "start_date": "2026-10-14", "shift_id": null}
[ 3] llm:model ok 1433ms | Planned: search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 20ms | {"facility_id": "FAC-001", "query": "ICU unit preferences and night shift arrival/outreach rules", "top_k": 5}
[ 5] tool:search_clinicians ok 29ms | {"shift_id": "SHF-1001", "query": "ICU RN night shift, critical care, prefers nights or open to nights, strong ICU experience", "limit": 10}
[ 6] llm:model ok 1141ms | Planned: evaluate_candidates
[ 7] tool:evaluate_candidates ok 2ms | {"shift_id": "SHF-1001", "clinician_ids": ["C-109", "C-102", "C-106", "C-105", "C-107", "C-104", "C-103", "C-101", "C-108"]}
[ 8] llm:model ok 2597ms | Planned: draft_outreach, draft_outreach
[ 9] tool:draft_outreach ok 6ms | {"shift_id": "SHF-1001", "clinician_id": "C-101", "personal_note": "Hi Maria, we\u2019d love to have you support this ICU shift. Your critical care background looks like a strong fit, and we\u2019d be...
[10] tool:draft_outreach ok 5ms | {"shift_id": "SHF-1001", "clinician_id": "C-107", "personal_note": "Hi Grace, we\u2019d be glad to have you in mind for this ICU shift. Your critical care experience looks like a great match, and we h...
[11] llm:model ok 3084ms | Planned: submit_recommendation
[12] validation:submit_recommendation ok 0ms | Submission accepted.
[13] completion:rules ok 0ms | Nothing to complete.
[14] verification:grounding ok 1ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 6 tool calls, 16422 tokens, 11.2s.
