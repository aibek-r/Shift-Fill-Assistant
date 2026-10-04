# Staffing report

- **Request:** Find two ICU nurses for the St. Mary's night shift on October 14 and draft outreach for each.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-1001: ICU night shift at St. Mary's Medical Center (Austin, TX), Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM (America/Chicago), 2 position(s) open

## Summary

9 candidates evaluated, covering the shift's full candidate pool: 3 eligible, 6 excluded. 2 eligible clinicians shortlisted for 2 open positions; 1 eligible alternate was not shortlisted.

**Agent notes:** The shortlisted clinicians were ordered by how closely their ICU experience matches the unit's preferred skill set, then by how well their stated day/night stance fits this night shift, and finally by the absence of credential warnings. C-101 comes first because the profile explicitly matches the unit's high-value CRRT and post-cardiac-surgery experience and strongly prefers night shifts. C-107 ranks next because the clinician has relevant ICU experience and is open to occasional nights, but the profile does not show the same depth of unit-preferred specialty fit; other eligible candidates ranked lower for having a credential warning or a less direct match to the ICU's preferred experience.

## Recommendations

### 1. Maria Santos (C-101)

Strongest overall match for the ICU night shift: 6 years of critical care experience, CCRN certification, and experience with CRRT and post-cardiac-surgery patients align closely with the unit's stated preferences. Also strongly prefers night shifts. No credential warnings were reported.
- **Source:** `FAC-001#icu-unit-profile` (ICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open ICU night shift at St. Mary's Medical Center on Wed, Oct 14</summary>

```text
Hi Maria,

You look like a strong fit for this ICU night shift because you have 6 years in critical care, CCRN certification, and experience with CRRT and post-cardiac-surgery patients. You also strongly prefer night shifts, which aligns well with this opening.

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

Solid ICU fit with 5 years of cardiovascular ICU experience and no credential warnings. The profile shows a day-shift preference but also openness to occasional nights, making the clinician a reasonable second choice for this night shift.
- **Source:** `FAC-001#icu-unit-profile` (ICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open ICU night shift at St. Mary's Medical Center on Wed, Oct 14</summary>

```text
Hi Grace,

Your cardiovascular ICU background and 5 years of ICU experience fit this St. Mary’s ICU night shift well. You prefer day shifts but are open to occasional nights, which may make this a good match for your schedule.

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
| James Okafor (C-102) | `CREDENTIAL_EXPIRED` ACLS expires 2026-10-10, before the shift ends on 2026-10-15. |
| Sofia Martinez (C-109) | `SCHEDULE_CONFLICT` Already booked (ASG-502) 2026-10-14T19:00:00-05:00 to 2026-10-15T07:00:00-05:00, overlapping this shift. |
| Tom Brennan (C-106) | `LICENSE_NOT_VALID_IN_STATE` RN license jurisdiction (CA) is not valid in TX; needs TX or COMPACT. |
| Aisha Rahman (C-105) | `INSUFFICIENT_EXPERIENCE` 1 years of experience; ICU requires 2. |
| Robert Diaz (C-108) | `INACTIVE` Clinician status is inactive. |
| Priya Patel (C-103) | `INSUFFICIENT_REST` Only 0.0h between this shift and booking ASG-501; St. Mary's Medical Center requires 10h of rest. |

## Verification

All references were verified against tool evidence.

## Trace

```text
[ 1] llm:model ok 1802ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 0ms | {"facility": "St. Mary's", "unit": "ICU", "start_date": "2026-10-14", "shift_id": null}
[ 3] llm:model ok 1011ms | Planned: search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 10ms | {"facility_id": "FAC-001", "query": "ICU unit preferences, night shift arrival logistics, outreach rules", "top_k": 5}
[ 5] tool:search_clinicians ok 10ms | {"shift_id": "SHF-1001", "query": "ICU RN night shift, critical care experience, night availability", "limit": 10}
[ 6] llm:model ok 1370ms | Planned: evaluate_candidates
[ 7] tool:evaluate_candidates ok 2ms | {"shift_id": "SHF-1001", "clinician_ids": ["C-102", "C-109", "C-106", "C-105", "C-104", "C-107", "C-101", "C-108", "C-103"]}
[ 8] llm:model ok 2046ms | Planned: draft_outreach, draft_outreach
[ 9] tool:draft_outreach ok 1ms | {"shift_id": "SHF-1001", "clinician_id": "C-101", "personal_note": "You look like a strong fit for this ICU night shift because you have 6 years in critical care, CCRN certification, and experience wi...
[10] tool:draft_outreach ok 1ms | {"shift_id": "SHF-1001", "clinician_id": "C-107", "personal_note": "Your cardiovascular ICU background and 5 years of ICU experience fit this St. Mary\u2019s ICU night shift well. You prefer day shift...
[11] llm:model ok 2677ms | Planned: submit_recommendation
[12] validation:submit_recommendation ok 0ms | Submission accepted.
[13] verification:grounding ok 1ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 6 tool calls, 15293 tokens, 9.0s.
