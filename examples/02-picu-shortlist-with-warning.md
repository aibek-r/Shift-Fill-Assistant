# Staffing report

- **Request:** Who can cover the PICU night shift at Bayview on Oct 18? Give me a shortlist of two with outreach drafts.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-3001: PICU night shift at Bayview Children's Hospital (San Diego, CA), Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles), 1 position(s) open

## Summary

3 candidates evaluated, covering the shift's full candidate pool: 2 eligible, 1 excluded. 2 eligible clinicians shortlisted for 1 open position.

**Agent notes:** For this Bayview PICU night shift, Isabella Garcia ranks first because she most closely matches the unit’s preferred pediatric critical care profile and has the strongest ventilator-management background without any credential warnings. Liam Chen is next because he meets the PICU experience requirement and has night availability, but his PALS renewal is coming due shortly after the shift. Emma Davis was not shortlisted because she is not eligible for California coverage for this assignment.

## Recommendations

### 1. Isabella Garcia (C-116)

Isabella Garcia is the strongest match: she has 6 years across PICU and NICU, which aligns well with Bayview’s PICU preference for at least 2 years of pediatric critical care experience and strongly preferred pediatric ventilator management. She is eligible with no credential warnings, and her profile directly mentions pediatric ventilator management. Policy support: FAC-003#picu-unit-profile, GLOBAL#candidate-prioritization.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Isabella,

You stand out for this PICU assignment because you have 6 years across PICU and NICU and strong pediatric ventilator management experience. Your background fits the unit’s medical, surgical, and cardiac pediatric population well.

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

Liam Chen is eligible and fits the shift well with 2 years of PICU experience and stated night availability, which matches the unit’s night coverage need. He meets the baseline PICU experience requirement, but he ranks behind Isabella because he has a credential warning: PALS expires 22 days after the shift. Policy support: FAC-003#picu-unit-profile, GLOBAL#candidate-prioritization.
- **Warning:** PALS expires 2026-11-10, 22 days after the shift. Request a renewal.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Liam,

You’re a strong fit for this PICU night assignment with 2 years of PICU experience and comfort caring for post-operative pediatric patients. Your night availability also matches the shift.

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
[ 1] llm:model ok 1555ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 1ms | {"facility": "Bayview", "unit": "PICU", "start_date": "2026-10-18", "shift_id": null}
[ 3] llm:model ok 2699ms | Planned: search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 33ms | {"facility_id": "FAC-003", "query": "PICU unit preferences, night shift arrival logistics, outreach rules, pediatric critical care certifications or experience preferences", "top_k": 5}
[ 5] tool:search_clinicians ok 24ms | {"shift_id": "SHF-3001", "query": "PICU night shift, pediatric critical care, night availability, RN", "limit": 10}
[ 6] llm:model ok 1534ms | Planned: evaluate_candidates
[ 7] tool:evaluate_candidates ok 1ms | {"shift_id": "SHF-3001", "clinician_ids": ["C-117", "C-116", "C-118"]}
[ 8] llm:model ok 2159ms | Planned: draft_outreach, draft_outreach
[ 9] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-116", "personal_note": "You stand out for this PICU assignment because you have 6 years across PICU and NICU and strong pediatric ventilator management expe...
[10] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-117", "personal_note": "You\u2019re a strong fit for this PICU night assignment with 2 years of PICU experience and comfort caring for post-operative pediat...
[11] llm:model ok 2531ms | Planned: submit_recommendation
[12] validation:submit_recommendation ok 0ms | Submission accepted.
[13] verification:grounding ok 0ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 6 tool calls, 11973 tokens, 10.6s.
