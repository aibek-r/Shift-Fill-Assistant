# Staffing report

- **Request:** Who can cover the PICU night shift at Bayview on Oct 18? Give me a shortlist of two with outreach drafts.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-3001: PICU night shift at Bayview Children's Hospital (San Diego, CA), Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles), 1 position(s) open

## Summary

Isabella Garcia and Liam Chen are the two eligible clinicians for this Bayview PICU night shift. Isabella is the stronger match because her profile includes pediatric ventilator management experience, which is a stated unit preference. Liam is also eligible, but he has a PALS expiration warning to track. Emma Davis was not recommended because her RN license is not valid in California.

## Recommendations

### 1. Isabella Garcia (C-116)

Best fit for Bayview PICU night shift: Isabella Garcia has 6 years in PICU/NICU, pediatric ventilator management experience, and family-centered care experience, which aligns with the unit's preference for pediatric ventilator management and its family-centered environment. She is eligible with no credential warnings.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Isabella,

Your PICU and NICU background fits Bayview's PICU, especially given your pediatric ventilator management experience and family-centered care experience. You also bring the strongest experience level among the eligible clinicians for this night shift.

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

Liam Chen is eligible and matches the minimum PICU experience requirement with 2 years in pediatric critical care and availability for nights. He is a strong second choice, though his PALS expires 2026-11-10, so a renewal should be requested.
- **Warning:** PALS expires 2026-11-10, 22 days after the shift. Request a renewal.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Liam,

Your PICU experience matches Bayview's PICU needs, and your profile notes availability for nights. You also meet the minimum 2 years of pediatric critical care experience called for on this unit.

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
[ 1] llm:model ok 1526ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 1ms | {"facility": "Bayview", "unit": "PICU", "start_date": "2026-10-18", "shift_id": null}
[ 3] llm:model ok 3898ms | Planned: search_facility_policies, search_facility_policies
[ 4] tool:search_facility_policies ok 38ms | {"facility_id": "FAC-003", "query": "PICU unit preferences, required certifications, patient acuity, and clinician traits preferred for Bayview Children's Hospital PICU night shifts", "top_k": 4}
[ 5] tool:search_facility_policies ok 18ms | {"facility_id": "FAC-003", "query": "night shift arrival logistics and outreach rules for Bayview Children's Hospital", "top_k": 4}
[ 6] llm:model ok 1357ms | Planned: search_clinicians
[ 7] tool:search_clinicians ok 34ms | {"shift_id": "SHF-3001", "query": "PICU night shift pediatric critical care, ventilator experience, California RN, BLS, PALS", "limit": 10}
[ 8] llm:model ok 1425ms | Planned: evaluate_candidates
[ 9] tool:evaluate_candidates ok 1ms | {"shift_id": "SHF-3001", "clinician_ids": ["C-117", "C-116", "C-118"]}
[10] llm:model ok 3877ms | Planned: draft_outreach, draft_outreach
[11] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-116", "personal_note": "Your PICU and NICU background fits Bayview's PICU, especially given your pediatric ventilator management experience and family-cente...
[12] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-117", "personal_note": "Your PICU experience matches Bayview's PICU needs, and your profile notes availability for nights. You also meet the minimum 2 years...
[13] llm:model ok 3558ms | Planned: submit_recommendation
[14] validation:submit_recommendation ok 0ms | Submission accepted.
[15] verification:grounding ok 0ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

6 LLM calls, 7 tool calls, 14951 tokens, 15.8s.
