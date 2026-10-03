# Demo video script (about 4 minutes)

Start the app first with `streamlit run app/streamlit_app.py`. Leave "Pin a shift" on
"Let the agent find it".

1. **Problem and approach (30 seconds).** "Coordinators fill open shifts by hand. They check
   licenses, certifications, schedules and facility preferences, then write outreach. I built one
   capability, a Shift Fill Assistant. The LLM plans, ranks and writes. Plain code makes every
   compliance decision. Every claim is checked against tool evidence before anyone sees it."
2. **Happy path (90 seconds).** Click the **ICU night shift** example, then **Run assistant**.
   - Narrate the progress label as it changes. Then open the **Trace** tab. The agent resolved
     the shift, searched policies and clinicians in parallel, vetted the whole pool, drafted
     outreach, then submitted.
   - Open **Recommendations**. Point at the citation expander, which shows the real policy text,
     and the outreach draft. The logistics and the reply deadline come from the record, not the
     model.
   - Open **Excluded**. There are six reason codes: an expired ACLS, a California license in
     Texas, a double booking, too little rest, too little experience, and an inactive profile.
   - Open **Other eligible**. Daniel Kim qualifies but has an expiring ACLS. Code computes this
     list, so nobody gets lost silently.
3. **Clarification (30 seconds).** Run **Ambiguous request**. The agent asks which shift instead
   of guessing.
4. **Reliability (60 seconds).**
   - Turn on **Simulate LLM outage** and pin shift **SHF-1001** in the sidebar, then rerun the
     ICU example. The report shows `Fallback mode`, and the same engine still produces a
     compliant shortlist. Without a pinned shift, the fallback cannot tell which shift was
     meant, so it reports that it could not complete.
   - Show the test names in `tests/test_agent_workflow.py`. They cover a hallucinated candidate
     sent back for repair, ungrounded citations stripped, and incomplete vetting caught.
5. **Close (20 seconds).** Walk through the architecture diagram in the README and the next
   steps: an evaluation harness, pgvector, persisted audit and tracing, and approve-and-send.
