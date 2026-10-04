# Staffing report

- **Request:** Who can cover the PICU night shift at Bayview on Oct 18? Give me a shortlist of two with outreach drafts.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-3001: PICU night shift at Bayview Children's Hospital (San Diego, CA), Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles), 1 position(s) open

## Summary

3 candidates evaluated, covering the shift's full candidate pool: 2 eligible, 1 excluded. 2 eligible clinicians shortlisted for 1 open position.

**Agent notes:** Bayview Children's Hospital has one open PICU night shift on Oct 18, 2026, from 7:00 PM to 7:00 AM in America/Los_Angeles. Isabella Garcia ranks first because her pediatric ventilator management experience directly matches the PICU unit's strong preference, while Liam Chen ranks second because he meets the PICU experience requirement and is available for nights but has a soon-to-expire PALS warning. Emma Davis ranks lower because her RN license is not valid in California, so she is not eligible.

## Recommendations

### 1. Isabella Garcia (C-116)

Strongest match for the PICU unit because Isabella Garcia has 6 years across PICU and NICU and pediatric ventilator management experience, which aligns with the unit's strongly preferred ventilator background. She is eligible with no warnings and fits the night shift context.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Isabella,

You look like a strong fit for Bayview Children's Hospital's PICU night shift because you have 6 years across PICU and NICU and experience with pediatric ventilator management. Your background aligns well with the unit's pediatric critical care needs.

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

Liam Chen meets the PICU experience floor with 2 years in PICU and is available for nights, which supports the shift period. He is eligible, but his PALS is expiring soon, so he ranks behind the cleaner credential profile.
- **Warning:** PALS expires 2026-11-10, 22 days after the shift. Request a renewal.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft: Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Liam,

You look like a solid fit for Bayview Children's Hospital's PICU night shift because you have 2 years of PICU experience and you are available for nights. That matches the unit's pediatric critical care needs.

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
[ 1] llm:model ok 843ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 1ms | {"facility": "Bayview", "unit": "PICU", "start_date": "2026-10-18", "shift_id": null}
[ 3] llm:model ok 1087ms | Planned: search_facility_policies, search_clinicians
[ 4] tool:search_facility_policies ok 19ms | {"facility_id": "FAC-003", "query": "PICU unit preferences and night shift arrival logistics or outreach rules", "top_k": 5}
[ 5] tool:search_clinicians ok 24ms | {"shift_id": "SHF-3001", "query": "PICU night shift, pediatric critical care, night availability, preferences", "limit": 10}
[ 6] llm:model ok 838ms | Planned: evaluate_candidates
[ 7] tool:evaluate_candidates ok 1ms | {"shift_id": "SHF-3001", "clinician_ids": ["C-117", "C-116", "C-118"]}
[ 8] llm:model ok 1481ms | Planned: draft_outreach, draft_outreach
[ 9] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-116", "personal_note": "You look like a strong fit for Bayview Children's Hospital's PICU night shift because you have 6 years across PICU and NICU and expe...
[10] tool:draft_outreach ok 1ms | {"shift_id": "SHF-3001", "clinician_id": "C-117", "personal_note": "You look like a solid fit for Bayview Children's Hospital's PICU night shift because you have 2 years of PICU experience and you are...
[11] llm:model ok 3199ms | Planned: submit_recommendation
[12] validation:submit_recommendation ok 0ms | Submission accepted.
[13] verification:grounding ok 0ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

5 LLM calls, 6 tool calls, 12869 tokens, 7.5s.
