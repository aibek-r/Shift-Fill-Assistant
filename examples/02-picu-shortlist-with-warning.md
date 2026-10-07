# Staffing report

- **Request:** Who can cover the PICU night shift at Bayview on Oct 18? Give me a shortlist of two with outreach drafts.
- **Status:** `ready` (mode: `agent`)
- **Shift:** SHF-3001: PICU night shift at Bayview Children's Hospital (San Diego, CA), Sun, Oct 18, 2026, 7:00 PM to Mon, Oct 19, 2026, 7:00 AM (America/Los_Angeles), 1 position(s) open

## Summary

3 candidates evaluated, covering the shift's full candidate pool: 2 eligible, 1 excluded. 2 eligible clinicians shortlisted for 1 open position. Requested shortlist: 2 of 2 clinicians.

## Recommendations

### 1. Isabella Garcia (C-116)

Passed the recorded compliance checks for this shift. Recorded experience: 6 years.

- **Selected by:** AI agent
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)

<details><summary>Outreach draft (requested by the AI agent): Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Isabella,

We’d be glad to have you support this PICU shift. Thank you for considering it, and we appreciate your interest in helping the team.
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

Passed the recorded compliance checks for this shift. Recorded experience: 2 years. Self-reported: is open to night shifts. PALS expires 2026-11-10, 22 days after the shift. Request a renewal.

- **Selected by:** AI agent
- **Warning:** PALS expires 2026-11-10, 22 days after the shift. Request a renewal.
- **Source:** `FAC-003#picu-unit-profile` (PICU unit profile)
- **Source:** `GLOBAL#candidate-prioritization` (Candidate prioritization)

<details><summary>Outreach draft (requested by the AI agent): Open PICU night shift at Bayview Children's Hospital on Sun, Oct 18</summary>

```text
Hi Liam,

We’d be glad to have you support this PICU shift. Thank you for considering it, and we appreciate your interest in helping the team.
Your recorded experience: 2 years.
Your profile says you are open to night shifts.

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
[ 1] llm:model ok 852ms | Planned: find_open_shifts
[ 2] tool:find_open_shifts ok 0ms | {"facility": "Bayview", "unit": "PICU", "start_date": "2026-10-18", "shift_id": null}
[ 3] llm:model ok 1692ms | Planned: search_facility_policies
[ 4] tool:search_facility_policies ok 28ms | {"facility_id": "FAC-003", "query": "PICU unit preferences and night shift arrival logistics for Bayview Children's Hospital", "top_k": 4}
[ 5] llm:model ok 3031ms | Planned: search_clinicians
[ 6] tool:search_clinicians ok 19ms | {"shift_id": "SHF-3001", "query": "PICU pediatric critical care ventilator night shift", "limit": 10}
[ 7] llm:model ok 1675ms | Planned: evaluate_candidates
[ 8] tool:evaluate_candidates ok 1ms | {"shift_id": "SHF-3001", "clinician_ids": ["C-116", "C-117", "C-118"]}
[ 9] llm:model ok 4093ms | Planned: draft_outreach, draft_outreach
[10] tool:draft_outreach ok 5ms | {"shift_id": "SHF-3001", "clinician_id": "C-116", "personal_note": "We\u2019d be glad to have you support this PICU shift. Thank you for considering it, and we appreciate your interest in helping the ...
[11] tool:draft_outreach ok 5ms | {"shift_id": "SHF-3001", "clinician_id": "C-117", "personal_note": "We\u2019d be glad to have you support this PICU shift. Thank you for considering it, and we appreciate your interest in helping the ...
[12] llm:model ok 4692ms | Planned: submit_recommendation
[13] validation:submit_recommendation ok 0ms | Submission accepted.
[14] completion:rules ok 0ms | Nothing to complete.
[15] verification:grounding ok 1ms | 2 recommendation(s) verified; 0 issue(s) enforced.
```

6 LLM calls, 6 tool calls, 16337 tokens, 16.1s.
