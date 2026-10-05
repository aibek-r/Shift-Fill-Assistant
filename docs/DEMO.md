# Demo guide (about 5 minutes)

## Before you start

- Keep `REFERENCE_DATE=2026-10-02` in `.env` so relative dates line up with the October 2026
  mock shifts.
- Start the app from the project directory, so it loads the theme:
  `streamlit run app/streamlit_app.py`. Leave "Select a shift" on "Let the agent find it".
- **Agent mode needs your own `OPENAI_API_KEY` in `.env`** and makes paid API calls. Without a
  key, every step below still runs in rule-based fallback mode, and the report says so. In that
  mode there are no policy citations, the trace shows the fallback instead of model and tool
  steps, and every card says **Selected by rules**.
- Use the sidebar examples. Avoid improvising requests that name an unknown facility or unit
  together with a specific date: the rule-based path currently ignores unknown names and can
  staff a different facility's shift (see
  [design.md](design.md#known-defects-reproduced-offline)).

**Opening line.** "The model plans, calls tools and ranks. Code decides eligibility, checks every
reference against tool evidence, finishes any mandatory work the model skipped, and labels what
it added."

## 1. A successful, completed request (90 seconds)

Click the **ICU night shift** example, then **Run assistant**.

- The status reads **Shortlist ready**. In agent mode, open **Technical details → Trace**: the
  agent resolved the shift, searched policies and clinicians, vetted the whole pool, drafted
  outreach and submitted. Then `validation`, `completion` ("Nothing to complete." when the model
  did everything) and `verification` ran.
- Under **Recommendations**, each card says **Selected by the AI agent** or **Selected by
  rules**. In agent mode, open a citation to show the retrieved policy text. Open the outreach
  draft: shift logistics, the reply deadline, credential reminders and a matching shift
  preference come from the record, never from profile free text.
- **Excluded** lists six clinicians with reason codes from the eligibility engine.
  **Alternates** shows the eligible clinician who was not shortlisted, computed by code.
- Approve a draft, then click **Edit note**: editing withdraws the approval. Type
  "It pays $55/hour." and save. The note is not saved; the editor lists each problem under the
  text box (for example `Remove "$55/hour": pay can't appear in outreach.`) and keeps your text.
  Replace it with your own friendly sentence, or add a suggested sentence with one click, and
  save. **Cancel** would have restored the saved note. The JSON download in **Technical
  details** contains only saved text and the current approval state. Nothing is sent: delivery
  is simulated.

## 2. An ambiguous request (30 seconds)

Run **Ambiguous request** ("Can you find an ICU nurse for St. Mary's next week?"). Next week
(October 5-11 with the pinned reference date) has no St. Mary's ICU shift. The report asks
instead of guessing and lists the October 14 and October 16 shifts as alternatives, with exact
dates. The rule-based path asks the same way. **Unknown facility** ("Mercy General tomorrow
night") is a second example: it asks which known facility to use and offers facility cards.

## 3. Model failure or exhausted budget, with safe recovery (60 seconds)

- Open **Demo controls**, turn on **Simulate LLM outage**, and rerun the ICU example with no
  shift selected. The mode reads **Rule-based fallback**. The summary says the rules matched
  SHF-1001 to the request (facility, unit, night shift, date). The same eligibility engine and
  templates produce a compliant shortlist.
- Budget exhaustion from the CLI, without a model request. In Git Bash:
  `MAX_RUN_SECONDS=0.000001 shift-assistant "Find two ICU nurses for the St. Mary's night shift on October 14"`.
  In PowerShell, set `$env:MAX_RUN_SECONDS = "0.000001"` first, run the same command, then
  `Remove-Item Env:MAX_RUN_SECONDS`. The trace shows `no time left for a model call`, then the
  fallback. Explain the boundary: the budget covers every model call, retry and backoff, and a
  late answer is discarded. Deterministic steps may finish afterwards.

## 4. Code-completed work and needs_review (60 seconds)

A live model cannot be made lazy on demand, so use the offline harness, which replays scripted
model turns and needs no API key:

```bash
python -m evals.run --case lazy-agent-completed-by-code --case required-check-fails-needs-review --show
```

- **lazy-agent-completed-by-code:** the scripted model vets one ineligible nurse, never searches
  the pool and claims nobody qualifies. The report is `ready` in `agent` mode "with deterministic
  completion". Code determined the pool, vetted the other 8 nurses, added 2 recommendations
  (**Selected by: deterministic rules**) and drafted their outreach. The **Deterministic
  completion** section lists each addition.
- **required-check-fails-needs-review:** one compliance check is made to fail. Code cannot
  finish the vetting, so the status is **needs_review**. The verified recommendations are kept,
  the summary says one pool member was not evaluated, and the issues say why.

The command also writes a results file to `evals/results/`. Close with the full results table
from `python -m evals.run` and the limits in
[design.md](design.md#known-limitations-and-defects): scripted runs test the safeguards, not
live model reasoning, and the known request-matching defects are listed there.

## If you are asked

- **"Is it production-ready?"** No. It is a prototype on mock data; authentication, audit
  storage, PII controls and real delivery are out of scope.
- **"Can the model recommend an ineligible nurse?"** No. Eligibility is decided by code, the
  verifier removes anyone the engine marks ineligible, and nobody is booked or contacted.
- **"Is the ranking reliable?"** The order among eligible clinicians is the model's judgement
  and can vary between runs; code does not enforce it.
