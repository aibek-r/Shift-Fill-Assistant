# Staffing report

- **Request:** Who can cover the PICU night shift at Bayview on Oct 18? Give me a shortlist of two with outreach drafts.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-3001: PICU night shift at Bayview Children's Hospital (San Diego, CA), Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles), 1 position(s) open

## Summary

3 candidates evaluated, covering the shift's full candidate pool: 2 eligible, 1 excluded. 2 eligible clinicians shortlisted for 1 open position. Requested shortlist: 2 of 2 clinicians.

## Recommendations

### 1. Isabella Garcia (C-116)

Passed the recorded compliance checks for this shift. Recorded experience: 6 years.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Isabella,

We would love to have you on this shift. We think you would fit this unit well.
Your recorded experience: 6 years.

Shift details
- Facility: Bayview Children's Hospital (San Diego, CA)
- Unit: PICU
- Time: Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles)

Please reply by Fri, Oct 16, 2026, 7:00 PM (America/Los_Angeles) to confirm your interest.

Thank you,
Staffing Operations Team
```
</details>

### 2. Liam Chen (C-117)

Passed the recorded compliance checks for this shift. Recorded experience: 2 years. Profile wording (self-reported): “available for nights”. PALS expires 2026-11-10, 22 days after the shift. Request a renewal.
- **Warning:** PALS expires 2026-11-10, 22 days after the shift. Request a renewal.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Liam,

Would you be interested in this shift? Thank you for considering this opportunity.
Your recorded experience: 2 years.
Your profile states: “available for nights”.

Shift details
- Facility: Bayview Children's Hospital (San Diego, CA)
- Unit: PICU
- Time: Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles)

Credential reminder
- Your PALS expires soon. Please upload your renewal so you stay eligible.

Please reply by Fri, Oct 16, 2026, 7:00 PM (America/Los_Angeles) to confirm your interest.

Thank you,
Staffing Operations Team
```
</details>

## Excluded candidates

| Clinician | Reasons |
| --- | --- |
| Emma Davis (C-118) | `LICENSE_NOT_VALID_IN_STATE` RN license jurisdiction (COMPACT) is not valid in CA; needs CA. |

## Verification

All references were verified against tool evidence.

## Trace

```text
[ 1] llm:model ok 1312ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 1ms | {"facility": "Bayview", "unit": "PICU", "start_date": "2026-10-18", "shift_id": null}
[ 3] llm:model ok 3077ms | Planned: search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 26ms | {"facility_id": "FAC-003", "query": "PICU unit preferences and night shift arrival logistics for Bayview Children's Hospital", "top_k": 4}
[ 5] tool:search_clinicians ok 31ms | {"shift_id": "SHF-3001", "query": "PICU night shift, pediatric critical care, night availability, ventilator or ICU experience", "limit": 10}
[ 6] llm:model ok 1368ms | Planned: evaluate_candidates
[ 7] tool:evaluate_candidates ok 1ms | {"shift_id": "SHF-3001", "clinician_ids": ["C-117", "C-116", "C-118"]}
[ 8] llm:model ok 2191ms | Planned: draft_outreach, draft_outreach
[ 9] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-116", "personal_note": "We would love to have you on this shift. We think you would fit this unit well."}
[10] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-117", "personal_note": "Would you be interested in this shift? Thank you for considering this opportunity."}
[11] llm:model ok 3348ms | Planned: submit_recommendation
[12] validation:submit_recommendation ok 0ms | Submission accepted.
[13] verification:grounding ok 1ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 6 tool calls, 13264 tokens, 11.4s.
