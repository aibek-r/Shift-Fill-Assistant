"""Deterministic completion: mandatory work the model left undone is finished by code or reported.

Each test drives the real graph with a scripted model, so the model's (lazy) behavior is fixed
and the assertions check what code does afterwards.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from shift_assistant.agent.submission import AgentSubmission
from shift_assistant.assistant import build_assistant
from shift_assistant.contracts import (
    Origin,
    ReportStatus,
    RunMode,
    StaffingReport,
    StaffingRequest,
)
from shift_assistant.reliability.grounding import check_grounding
from shift_assistant.rendering import render_markdown
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.tools.facts import DEFAULT_NOTE
from shift_assistant.tools.schemas import EvaluateCandidatesArgs, FindOpenShiftsArgs
from shift_assistant.tools.toolkit import StaffingToolkit
from tests.conftest import AssistantFactory, ai, make_settings, tool_call
from tests.test_agent_workflow import (
    ICU_POOL,
    REQUEST,
    SUBMIT,
    clarification,
    rec,
    research_steps,
    submission,
)

CODE, MODEL = Origin.CODE, Origin.MODEL
WITH_OUTREACH = StaffingRequest(
    text="Find one ICU nurse for St. Mary's on Oct 14 and draft outreach"
)


def lazy_steps(*vetted: str, search: bool = True) -> list[AIMessage]:
    """The model resolves the shift but vets only some clinicians (and may skip the search)."""
    steps = [ai(tool_call("find_open_shifts", shift_id="SHF-1001"))]
    if search:
        steps.append(ai(tool_call("search_clinicians", shift_id="SHF-1001", limit=25)))
    steps.append(
        ai(tool_call("evaluate_candidates", shift_id="SHF-1001", clinician_ids=list(vetted)))
    )
    return steps


def picks(report: StaffingReport) -> list[tuple[str, Origin]]:
    return [(r.clinician_id, r.selected_by) for r in report.recommendations]


def fail_for(monkeypatch: pytest.MonkeyPatch, method: str, clinician_id: str) -> None:
    """Make one toolkit operation fail for one clinician, as a broken required check would."""
    original = getattr(StaffingToolkit, method)

    def patched(self: StaffingToolkit, shift: object, clinician: object, *args: object) -> object:
        if getattr(clinician, "id", None) == clinician_id:
            raise RuntimeError("check unavailable")
        return original(self, shift, clinician, *args)

    monkeypatch.setattr(StaffingToolkit, method, patched)


def test_incomplete_pool_with_no_eligible_candidate_so_far_is_completed(
    scripted_assistant: AssistantFactory,
) -> None:
    # Previously: no_eligible_candidates after vetting 1 of 9, with 8 never checked.
    assistant, _ = scripted_assistant(
        [*lazy_steps("C-102"), ai(tool_call(SUBMIT, **submission()))], max_repair_attempts=0
    )

    report = assistant.run(REQUEST)

    assert (report.mode, report.status) == (RunMode.AGENT, ReportStatus.READY)
    assert picks(report) == [("C-101", CODE), ("C-107", CODE)]  # fallback order
    assert report.coverage is not None and report.coverage.full_pool_evaluated
    assert report.completion is not None
    assert report.completion.evaluated_ids == [c for c in ICU_POOL if c != "C-102"]
    assert report.completion.selected_ids == ["C-101", "C-107"]
    assert report.issues == []
    assert "deterministic rules vetted 8 remaining pool clinicians and added 2" in report.summary


def test_incomplete_pool_with_one_eligible_recommendation_keeps_the_model_pick_first(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [*lazy_steps("C-107"), ai(tool_call(SUBMIT, **submission(rec("C-107"))))],
        max_repair_attempts=0,
    )

    report = assistant.run(REQUEST)

    assert report.status is ReportStatus.READY
    assert picks(report) == [("C-107", MODEL), ("C-101", CODE)]
    assert [a.clinician_id for a in report.alternates] == ["C-104"]


def test_markdown_and_json_identify_code_additions(scripted_assistant: AssistantFactory) -> None:
    assistant, _ = scripted_assistant(
        [*lazy_steps("C-107"), ai(tool_call(SUBMIT, **submission(rec("C-107"))))],
        max_repair_attempts=0,
    )

    report = assistant.run(WITH_OUTREACH.model_copy(update={"requested_count": 2}))
    markdown = render_markdown(report)
    exported = StaffingReport.model_validate_json(report.model_dump_json())

    assert "(mode: `agent` with deterministic completion)" in markdown
    assert "- **Selected by:** AI agent" in markdown
    assert "- **Selected by:** deterministic rules" in markdown
    assert "Outreach draft (drafted by deterministic rules):" in markdown
    assert "## Deterministic completion" in markdown
    assert "- Recommendations added by code: C-101" in markdown
    assert [r.selected_by for r in exported.recommendations] == [MODEL, CODE]
    assert exported.completion == report.completion


def test_pool_never_searched_is_computed_by_code_and_fully_evaluated(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [*lazy_steps("C-101", search=False), ai(tool_call(SUBMIT, **submission(rec("C-101"))))],
        max_repair_attempts=0,
    )

    report = assistant.run(REQUEST)

    assert report.completion is not None and report.completion.pool_determined_by_code
    assert report.coverage is not None
    assert (report.coverage.pool_size, report.coverage.evaluated) == (9, 9)
    assert report.status is ReportStatus.READY
    assert picks(report) == [("C-101", MODEL), ("C-107", CODE)]
    assert "determined the candidate pool" in report.summary
    assert [e.ok for e in report.trace if e.kind == "completion"] == [True]


def test_missing_requested_outreach_is_drafted_from_the_template(
    scripted_assistant: AssistantFactory, toolkit: StaffingToolkit
) -> None:
    # Previously: ready with INCOMPLETE_VETTING and MISSING_OUTREACH left as warnings.
    assistant, _ = scripted_assistant(
        [*lazy_steps("C-107"), ai(tool_call(SUBMIT, **submission(rec("C-107"))))],
        max_repair_attempts=0,
    )

    report = assistant.run(WITH_OUTREACH)

    assert report.status is ReportStatus.READY and report.issues == []
    (grace,) = report.recommendations
    assert (grace.selected_by, grace.outreach_by) == (MODEL, CODE)
    assert grace.outreach is not None and grace.outreach.personal_note == DEFAULT_NOTE
    assert grace.outreach.body.startswith("Hi Grace,")
    assert report.completion is not None and report.completion.drafted_ids == ["C-107"]
    others = [c for c in assistant.repository.clinicians() if c.id != "C-107"]
    for clinician in [*others, assistant.repository.clinician("C-107")]:
        assert clinician is not None
        assert clinician.email not in grace.outreach.body
        assert clinician.phone not in grace.outreach.body
    assert not any(c.name in grace.outreach.body for c in others)
    assert "$" not in grace.outreach.body


def test_invalid_model_draft_is_replaced_when_outreach_was_requested(
    scripted_assistant: AssistantFactory,
) -> None:
    final = submission(rec("C-101", draft="DRAFT-FAKE"))
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )

    report = assistant.run(WITH_OUTREACH)

    (maria,) = report.recommendations
    assert maria.outreach is not None and maria.outreach.draft_id == "DRAFT-SHF-1001-C-101"
    assert maria.outreach_by is CODE
    assert report.status is ReportStatus.READY


def test_explicit_no_outreach_request_creates_no_drafts(
    scripted_assistant: AssistantFactory,
) -> None:
    assistant, _ = scripted_assistant(
        [*lazy_steps("C-107"), ai(tool_call(SUBMIT, **submission(rec("C-107"))))],
        max_repair_attempts=0,
    )

    report = assistant.run(REQUEST)  # draft_outreach=False

    assert report.status is ReportStatus.READY
    assert all(r.outreach is None and r.outreach_by is None for r in report.recommendations)
    assert report.completion is not None and report.completion.drafted_ids == []


def test_completion_runs_once_repair_attempts_are_exhausted(
    scripted_assistant: AssistantFactory,
) -> None:
    lazy = [ai(tool_call(SUBMIT, **submission(rec("C-107")))) for _ in range(2)]
    assistant, model = scripted_assistant([*lazy_steps("C-107"), *lazy], max_repair_attempts=1)

    report = assistant.run(REQUEST)

    assert "were never vetted" in str(model.received[-1][-1].content)  # one repair was offered
    kinds = [e.kind for e in report.trace if e.kind in {"validation", "completion", "verification"}]
    assert kinds == ["validation", "validation", "completion", "verification"]
    assert report.mode is RunMode.AGENT and report.status is ReportStatus.READY
    assert picks(report) == [("C-107", MODEL), ("C-101", CODE)]


def test_mandatory_check_that_cannot_run_needs_review(
    scripted_assistant: AssistantFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_for(monkeypatch, "evaluate", "C-103")
    assistant, _ = scripted_assistant(
        [*lazy_steps("C-107"), ai(tool_call(SUBMIT, **submission(rec("C-107"))))],
        max_repair_attempts=0,
    )

    report = assistant.run(REQUEST)

    assert report.status is ReportStatus.NEEDS_REVIEW
    assert picks(report) == [("C-107", MODEL), ("C-101", CODE)]  # verified work is preserved
    assert report.coverage is not None and report.coverage.unevaluated_ids == ["C-103"]
    assert {i.code for i in report.issues} == {"INCOMPLETE_VETTING", "COMPLETION_UNRESOLVED"}
    assert "(1 not evaluated)" in report.summary
    assert [e.ok for e in report.trace if e.kind == "completion"] == [False]


def test_outreach_that_cannot_be_drafted_needs_review(
    scripted_assistant: AssistantFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_for(monkeypatch, "create_draft", "C-101")
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **submission(rec("C-101"))))],
        max_repair_attempts=0,
    )

    report = assistant.run(WITH_OUTREACH)

    assert report.status is ReportStatus.NEEDS_REVIEW
    assert [r.clinician_id for r in report.recommendations] == ["C-101"]
    assert report.recommendations[0].outreach is None
    assert {i.code for i in report.issues} == {"MISSING_OUTREACH", "COMPLETION_UNRESOLVED"}
    assert "Requested outreach is missing for 1 recommendation." in report.summary


def test_fully_evaluated_pool_with_nobody_eligible(scripted_assistant: AssistantFactory) -> None:
    steps = [
        ai(tool_call("find_open_shifts", shift_id="SHF-3002")),
        ai(tool_call("search_clinicians", shift_id="SHF-3002")),
        ai(
            tool_call(
                "evaluate_candidates",
                shift_id="SHF-3002",
                clinician_ids=["C-116", "C-119", "C-120"],
            )
        ),
    ]
    nobody = submission() | {"shift_id": "SHF-3002"}
    assistant, _ = scripted_assistant([*steps, ai(tool_call(SUBMIT, **nobody))])
    request = StaffingRequest(text="We need a NICU nurse at Bayview on October 19")

    agent = assistant.run(request)
    fallback = build_assistant(make_settings(), embedder=HashingEmbedder()).run(
        request.model_copy(update={"shift_id": "SHF-3002"})
    )

    for report in (agent, fallback):
        assert report.status is ReportStatus.NO_ELIGIBLE_CANDIDATES
        assert report.coverage is not None and report.coverage.full_pool_evaluated
        assert report.recommendations == []
    assert (agent.mode, fallback.mode) == (RunMode.AGENT, RunMode.FALLBACK)
    assert agent.completion is None and agent.issues == []


def test_fully_completed_answer_needs_no_completion(scripted_assistant: AssistantFactory) -> None:
    final = submission(
        rec("C-101", draft="DRAFT-SHF-1001-C-101"),
        rec("C-104", draft="DRAFT-SHF-1001-C-104", rationale="ACLS expires soon; needs renewal."),
    )
    assistant, _ = scripted_assistant(
        [*research_steps(outreach=True), ai(tool_call(SUBMIT, **final))]
    )

    report = assistant.run(REQUEST.model_copy(update={"draft_outreach": True}))

    assert report.status is ReportStatus.READY and report.completion is None
    assert [(r.selected_by, r.outreach_by) for r in report.recommendations] == [
        (MODEL, MODEL),
        (MODEL, MODEL),
    ]
    completion = [e for e in report.trace if e.kind == "completion"]
    assert [(e.ok, e.detail) for e in completion] == [(True, "Nothing to complete.")]


@pytest.mark.parametrize(
    ("max_recommendations", "expected", "status"),
    [
        (5, [("C-107", MODEL), ("C-101", CODE), ("C-104", CODE)], ReportStatus.READY),
        (2, [("C-107", MODEL), ("C-101", CODE)], ReportStatus.PARTIAL),  # configured limit
    ],
)
def test_code_additions_keep_model_order_avoid_duplicates_and_respect_the_target(
    scripted_assistant: AssistantFactory,
    max_recommendations: int,
    expected: list[tuple[str, Origin]],
    status: ReportStatus,
) -> None:
    final = submission(rec("C-107"), rec("C-107"))
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **final))],
        max_repair_attempts=0,
        max_recommendations=max_recommendations,
    )

    report = assistant.run(StaffingRequest(text="Find three ICU nurses without outreach"))

    assert picks(report) == expected
    assert len({r.clinician_id for r in report.recommendations}) == len(expected)
    assert report.status is status
    assert "DUPLICATE_CANDIDATE" in {i.code for i in report.issues}


def test_a_dropped_pick_does_not_displace_valid_ones(
    scripted_assistant: AssistantFactory, toolkit: StaffingToolkit
) -> None:
    final = submission(rec("C-102"), rec("C-107"), rec("C-101"))  # C-102 is ineligible
    ledger = toolkit.find_open_shifts(FindOpenShiftsArgs(shift_id="SHF-1001")).evidence.merge(
        toolkit.evaluate_candidates(
            EvaluateCandidatesArgs(shift_id="SHF-1001", clinician_ids=ICU_POOL)
        ).evidence
    )
    problems = check_grounding(AgentSubmission.model_validate(final), ledger, 5, REQUEST)
    assert [p.code for p in problems] == ["POOL_NOT_SEARCHED", "INELIGIBLE"]

    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **final))], max_repair_attempts=0
    )
    report = assistant.run(REQUEST)

    assert picks(report) == [("C-107", MODEL), ("C-101", MODEL)]
    assert [i.code for i in report.issues] == ["INELIGIBLE"]
    assert report.completion is None and report.status is ReportStatus.READY


def test_completion_never_runs_after_a_rejected_submission(
    scripted_assistant: AssistantFactory,
) -> None:
    wrong_shift = submission(rec("C-116")) | {"shift_id": "SHF-3001"}
    assistant, _ = scripted_assistant(
        [*research_steps(), ai(tool_call(SUBMIT, **wrong_shift))], max_repair_attempts=0
    )

    report = assistant.run(StaffingRequest(text="Fill the pinned ICU shift", shift_id="SHF-1001"))

    assert report.mode is RunMode.FALLBACK
    assert not any(e.kind == "completion" for e in report.trace)


def test_clarifications_skip_completion(scripted_assistant: AssistantFactory) -> None:
    assistant, _ = scripted_assistant(
        [
            ai(tool_call("find_open_shifts", facility="St. Mary's", unit="ICU")),
            ai(tool_call(SUBMIT, **clarification())),
        ]
    )

    report = assistant.run(StaffingRequest(text="An ICU nurse for St. Mary's please"))

    assert report.status is ReportStatus.NEEDS_CLARIFICATION
    assert report.completion is None
    assert not any(e.kind == "completion" for e in report.trace)
