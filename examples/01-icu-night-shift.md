# Staffing report

- **Request:** Find two ICU nurses for the St. Mary's night shift on October 14 and draft outreach for each.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-1001: ICU night shift at St. Mary's Medical Center (Austin, TX), Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM (America/Chicago), 2 position(s) open

## Summary

9 candidates evaluated, covering the shift's full candidate pool: 3 eligible, 6 excluded. 2 eligible clinicians shortlisted for 2 open positions; 1 eligible alternate was not shortlisted. Requested shortlist: 2 of 2 clinicians.

## Recommendations

### 1. Maria Santos (C-101)

Passed the recorded compliance checks for this shift. Recorded experience: 6 years. Profile wording (self-reported): “Strongly prefers night shifts”.
- **Source:** `FAC-001#icu-unit-profile` (ICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open ICU night shift at St. Mary's Medical Center on Wed, Oct 14</summary>

```text
Hi Maria,

We would love to have you on this shift. Thank you for considering this opportunity.
Your recorded experience: 6 years.
Your profile states: “Strongly prefers night shifts”.

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

Passed the recorded compliance checks for this shift. Recorded experience: 5 years. Profile wording (self-reported): “Prefers day shifts but is open to occasional nights”.
- **Source:** `FAC-001#icu-unit-profile` (ICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open ICU night shift at St. Mary's Medical Center on Wed, Oct 14</summary>

```text
Hi Grace,

We would love to have you on this shift. We think you would fit this unit well.
Your recorded experience: 5 years.
Your profile states: “Prefers day shifts but is open to occasional nights”.

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
| Tom Brennan (C-106) | `LICENSE_NOT_VALID_IN_STATE` RN license jurisdiction (CA) is not valid in TX; needs TX or COMPACT. |
| James Okafor (C-102) | `CREDENTIAL_EXPIRED` ACLS expires 2026-10-10, before the shift ends on 2026-10-15. |
| Aisha Rahman (C-105) | `INSUFFICIENT_EXPERIENCE` 1 years of experience; ICU requires 2. |
| Sofia Martinez (C-109) | `SCHEDULE_CONFLICT` Already booked (ASG-502) 2026-10-14T19:00:00-05:00 to 2026-10-15T07:00:00-05:00, overlapping this shift. |
| Priya Patel (C-103) | `INSUFFICIENT_REST` Only 0.0h between this shift and booking ASG-501; St. Mary's Medical Center requires 10h of rest. |
| Robert Diaz (C-108) | `INACTIVE` Clinician status is inactive. |

## Verification

All references were verified against tool evidence.

## Trace

```text
[ 1] llm:model ok 2951ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 0ms | {"facility": "St. Mary's", "unit": "ICU", "start_date": "2026-10-14", "shift_id": null}
[ 3] llm:model ok 2210ms | Planned: search_facility_policies, search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 36ms | {"facility_id": "FAC-001", "query": "ICU unit preferences for St. Mary's Medical Center, including preferred experience, certifications, patient types, and any special unit needs", "top_k": 4}
[ 5] tool:search_facility_policies ok 24ms | {"facility_id": "FAC-001", "query": "night shift arrival logistics and outreach rules for clinicians at St. Mary's Medical Center", "top_k": 4}
[ 6] tool:search_clinicians ok 19ms | {"shift_id": "SHF-1001", "query": "ICU night shift RN, preferences for ICU, critical care, ventilators, CRRT, titratable drips, cardiac surgery, and night availability", "limit": 10}
[ 7] llm:model ok 1643ms | Planned: evaluate_candidates
[ 8] tool:evaluate_candidates ok 4ms | {"shift_id": "SHF-1001", "clinician_ids": ["C-106", "C-102", "C-105", "C-109", "C-107", "C-101", "C-103", "C-104", "C-108"]}
[ 9] llm:model ok 1983ms | Planned: draft_outreach, draft_outreach
[10] tool:draft_outreach ok 2ms | {"shift_id": "SHF-1001", "clinician_id": "C-107", "personal_note": "We would love to have you on this shift. We think you would fit this unit well."}
[11] tool:draft_outreach ok 1ms | {"shift_id": "SHF-1001", "clinician_id": "C-101", "personal_note": "We would love to have you on this shift. Thank you for considering this opportunity."}
[12] llm:model ok 2842ms | Planned: submit_recommendation
[13] validation:submit_recommendation ok 0ms | Submission accepted.
[14] verification:grounding ok 1ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 7 tool calls, 16609 tokens, 11.7s.
