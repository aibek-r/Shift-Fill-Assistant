# Demo guide (about 5 minutes)

Start the app with `streamlit run app/streamlit_app.py` and leave "Select a shift" on "Let the
agent find it". Agent mode needs your own `OPENAI_API_KEY` in `.env`. Without one, every step
below still runs in rule-based fallback mode, and the report says so.

**Opening line.** "The model plans, calls tools and ranks. Code decides eligibility, checks every
reference against tool evidence, finishes any mandatory work the model skipped, and labels what
it added."

## 1. A successful, completed request (90 seconds)

Click the **ICU night shift** example, then **Run assistant**.

- The status reads **Shortlist ready**. Open **Technical details → Trace**: the agent resolved
  the shift, searched policies and clinicians, vetted the whole pool, drafted outreach and
  submitted. Then `validation`, `completion` ("Nothing to complete." when the model did
  everything) and `verification` ran.
- Under **Recommendations**, each card says **Selected by the AI agent** or **Selected by
  rules**. Open a citation to show the retrieved policy text, then the outreach draft: shift
  logistics, credential reminders and a matching shift preference come from the record, never
  from profile free text.
- **Excluded** lists six reason codes from the eligibility engine. **Alternates** shows the
  eligible clinician who was not shortlisted, computed by code.
- Approve a draft, then edit its note: editing withdraws the approval. Type "It pays
  $55/hour" and save: the editor lists `Remove "$55/hour": pay can't appear in outreach.` and
  keeps your text. Add a suggested sentence with one click and save. Nothing is sent: delivery
  is simulated.

## 2. An ambiguous request (30 seconds)

Run **Ambiguous request** ("an ICU nurse for St. Mary's next week"). Next week (Oct 5-11 with
the pinned reference date) has no St. Mary's ICU shift. The report asks instead of guessing and
lists the Oct 14 and Oct 16 shifts as alternatives with exact dates. The rule-based path asks
the same way.

## 3. Model failure or exhausted budget, with safe recovery (60 seconds)

- Open **Demo controls**, turn on **Simulate LLM outage**, and rerun the ICU example with no
  shift selected. The mode reads **Rule-based fallback**. The rules match SHF-1001 from the
  request (facility, unit, night shift, date) and say so in the summary. The same eligibility
  engine and templates produce a compliant shortlist.
- Budget exhaustion from the CLI, without a model request:
  `MAX_RUN_SECONDS=0.000001 shift-assistant "Find two ICU nurses for the St. Mary's night shift on October 14"`.
  The trace shows `no time left for a model call`, then the fallback. Explain the boundary:
  the budget covers every model call, retry and backoff, and a late answer is discarded.
  Deterministic steps may finish afterwards.

## 4. Code-completed work and needs_review (60 seconds)

A live model cannot be made lazy on demand, so use the offline harness, which replays scripted
model turns:

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

Close with the results table in `evals/results/` and the limits in
[design.md](design.md#known-limitations-and-unverified-behavior): scripted runs test the
safeguards, not live model reasoning.
