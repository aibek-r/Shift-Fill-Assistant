# Staffing report

- **Request:** Who can cover the PICU night shift at Bayview on Oct 18? Give me a shortlist of two with outreach drafts.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-3001: PICU night shift at Bayview Children's Hospital (San Diego, CA), Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles), 1 position(s) open

## Summary

3 candidates evaluated, covering the shift's full candidate pool: 2 eligible, 1 excluded. 2 eligible clinicians shortlisted for 1 open position.

**Agent notes:** I ranked Isabella Garcia first because her PICU/NICU background and pediatric ventilator management most closely match the unit's stated PICU preferences, and she has no credential warnings. Liam Chen follows because he is a fit for the PICU night shift and is available for nights, but his PALS is expiring soon, which lowers him behind Isabella. Emma Davis was not shortlisted because her RN license is not valid in California.

## Recommendations

### 1. Isabella Garcia (C-116)

Isabella Garcia is the strongest match for Bayview Children's Hospital PICU because she has 6 years across PICU and NICU, and her profile specifically includes pediatric ventilator management. She has no credential warnings on the shift and meets the unit's PICU experience and pediatric critical care fit well.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Isabella,

You look like a strong fit for Bayview Children's Hospital PICU night shift on Oct 18 because of your 6 years across PICU and NICU and your experience with pediatric ventilator management. Your background in pediatric critical care aligns well with the unit's PICU needs.

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

Liam Chen fits the PICU night shift with 2 years of PICU experience and availability for nights, plus comfort with post-operative pediatric patients. He is eligible, but he has a credential warning because PALS expires 22 days after the shift, so he ranks behind Isabella.
- **Warning:** PALS expires 2026-11-10, 22 days after the shift. Request a renewal.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Liam,

You look like a good fit for Bayview Children's Hospital PICU night shift on Oct 18 because you have 2 years of PICU experience and are available for nights. Your comfort with post-operative pediatric patients also matches the PICU setting.

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
[ 1] llm:model ok 1132ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 1ms | {"facility": "Bayview", "unit": "PICU", "start_date": "2026-10-18", "shift_id": null}
[ 3] llm:model ok 2150ms | Planned: search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 23ms | {"facility_id": "FAC-003", "query": "PICU unit preferences and night shift arrival/outreach rules", "top_k": 4}
[ 5] tool:search_clinicians ok 20ms | {"shift_id": "SHF-3001", "query": "PICU night, pediatric critical care, Bayview preferences", "limit": 10}
[ 6] llm:model ok 947ms | Planned: evaluate_candidates
[ 7] tool:evaluate_candidates ok 1ms | {"shift_id": "SHF-3001", "clinician_ids": ["C-117", "C-116", "C-118"]}
[ 8] llm:model ok 1774ms | Planned: draft_outreach, draft_outreach
[ 9] tool:draft_outreach ok 0ms | {"shift_id": "SHF-3001", "clinician_id": "C-116", "personal_note": "You look like a strong fit for Bayview Children's Hospital PICU night shift on Oct 18 because of your 6 years across PICU and NICU a...
[10] tool:draft_outreach ok 0ms | {"shift_id": "SHF-3001", "clinician_id": "C-117", "personal_note": "You look like a good fit for Bayview Children's Hospital PICU night shift on Oct 18 because you have 2 years of PICU experience and ...
[11] llm:model ok 3129ms | Planned: submit_recommendation
[12] validation:submit_recommendation ok 0ms | Submission accepted.
[13] verification:grounding ok 0ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 6 tool calls, 12875 tokens, 9.2s.
