"""Model execution budget: one deadline for every model call, retry and backoff.

A fake monotonic clock makes time explicit: each fake call advances it by a scripted duration,
and backoff advances it by the requested delay instead of sleeping.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx2
import openai
import pytest
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from shift_assistant.agent.llm import (
    ModelBudgetExceeded,
    RetryPolicy,
    build_chat_model,
    invoke_within_budget,
    is_transient,
)
from shift_assistant.assistant import ShiftFillAssistant, build_assistant
from shift_assistant.contracts import ReportStatus, RunMode, StaffingReport, StaffingRequest
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.tools.toolkit import StaffingToolkit
from tests.conftest import ai, make_settings, tool_call
from tests.test_agent_workflow import REQUEST, SUBMIT, rec, research_steps, submission

MESSAGES = [HumanMessage("Find an ICU nurse")]
OPENAI_URL = "https://api.openai.com/v1/responses"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TimedModel:
    """Replays (duration, response) steps; each call advances the fake clock by its duration."""

    def __init__(self, clock: FakeClock, steps: Sequence[tuple[float, AIMessage | Exception]]):
        self._clock = clock
        self._steps = list(steps)
        self.timeouts: list[float | None] = []

    def __call__(self, _: LanguageModelInput, timeout: float | None = None) -> BaseMessage:
        self.timeouts.append(timeout)
        duration, response = self._steps.pop(0)
        self._clock.now += duration
        if isinstance(response, Exception):
            raise response
        return response


def call(
    clock: FakeClock, model: TimedModel, deadline: float, retries: int = 3, timeout: float = 60.0
) -> tuple[BaseMessage, int]:
    return invoke_within_budget(
        RunnableLambda(model),
        MESSAGES,
        deadline=deadline,
        policy=RetryPolicy(max_retries=retries, call_timeout=timeout),
        clock=clock,
        sleep=clock.sleep,
    )


def rate_limited() -> ModelRateLimitError:
    return ModelRateLimitError("429 Too Many Requests")


def test_budget_exhausted_before_a_call() -> None:
    clock = FakeClock()
    clock.now = 10.0
    model = TimedModel(clock, [(1.0, ai())])

    with pytest.raises(ModelBudgetExceeded, match="no time left for a model call"):
        call(clock, model, deadline=10.0)
    assert model.timeouts == []  # never called


def test_each_call_timeout_is_capped_by_the_remaining_budget() -> None:
    clock = FakeClock()
    model = TimedModel(clock, [(2.0, rate_limited()), (1.0, ai())])

    _, retries = call(clock, model, deadline=21.0, timeout=20.0)

    assert retries == 1
    assert model.timeouts == [20.0, 18.0]  # min(20, 21 - 0), then min(20, 21 - 3) after backoff
    assert clock.sleeps == [1.0]


def test_retry_stops_at_the_deadline() -> None:
    clock = FakeClock()
    model = TimedModel(clock, [(2.0, rate_limited())] * 6)

    with pytest.raises(ModelBudgetExceeded, match="no time left to retry") as raised:
        call(clock, model, deadline=10.0, retries=5)

    # t=0 call, t=2 fail, wait 1; t=3 call, t=5 fail, wait 2; t=7 call, t=9 fail; a 4s wait
    # would end after the deadline, so no further retry starts.
    assert model.timeouts == [10.0, 7.0, 3.0]
    assert clock.sleeps == [1.0, 2.0]
    assert isinstance(raised.value.__cause__, ModelRateLimitError)


def test_backoff_never_sleeps_past_the_deadline() -> None:
    clock = FakeClock()
    model = TimedModel(clock, [(2.0, ModelTimeoutError("timed out"))])

    with pytest.raises(ModelBudgetExceeded):
        call(clock, model, deadline=2.5)  # 0.5s left, the first backoff is 1s

    assert clock.sleeps == []
    assert clock.now == 2.0


def test_a_call_that_returns_after_the_deadline_is_discarded() -> None:
    clock = FakeClock()
    model = TimedModel(clock, [(12.0, ai(tool_call(SUBMIT, **submission(rec("C-101")))))])

    with pytest.raises(ModelBudgetExceeded, match="answered after the deadline"):
        call(clock, model, deadline=10.0)


def test_retries_are_bounded_and_the_last_error_is_raised() -> None:
    clock = FakeClock()
    model = TimedModel(clock, [(0.1, rate_limited())] * 3)

    with pytest.raises(ModelRateLimitError):
        call(clock, model, deadline=1000.0, retries=2)

    assert len(model.timeouts) == 3 and clock.sleeps == [1.0, 2.0]


def test_non_transient_errors_are_not_retried() -> None:
    clock = FakeClock()
    model = TimedModel(clock, [(0.1, ValueError("bad request"))])

    with pytest.raises(ValueError, match="bad request"):
        call(clock, model, deadline=1000.0)

    assert len(model.timeouts) == 1 and clock.sleeps == []


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", OPENAI_URL)
    return cls("error", response=httpx2.Response(status, request=request), body=None)


@pytest.mark.parametrize(
    ("error", "transient"),
    [
        (_status_error(openai.RateLimitError, 429), True),
        (_status_error(openai.InternalServerError, 503), True),
        (_status_error(openai.InternalServerError, 501), False),  # not implemented: permanent
        (_status_error(openai.BadRequestError, 400), False),
        (_status_error(openai.AuthenticationError, 401), False),
        (openai.APITimeoutError(request=httpx2.Request("POST", OPENAI_URL)), True),
        (ModelTimeoutError("timed out"), True),
        (ConnectionError("simulated LLM outage"), False),  # not a provider error
        (ValueError("bug"), False),
    ],
)
def test_only_transient_provider_errors_are_retried(error: Exception, transient: bool) -> None:
    assert is_transient(error) is transient


# --- Through the workflow --------------------------------------------------------------------


def timed_assistant(
    clock: FakeClock, steps: Sequence[tuple[float, AIMessage | Exception]], **settings: Any
) -> tuple[ShiftFillAssistant, TimedModel]:
    model = TimedModel(clock, steps)
    assistant = build_assistant(
        make_settings(**settings),
        embedder=HashingEmbedder(),
        chat_model=RunnableLambda(model),
        clock=clock,
        sleep=clock.sleep,
    )
    return assistant, model


def assert_safely_recovered(
    report: StaffingReport, toolkit: StaffingToolkit, repository: StaffingRepository
) -> None:
    """Fallback output is still vetted by the engine and contains only grounded drafts."""
    assert report.mode is RunMode.FALLBACK
    assert report.coverage is not None and report.coverage.full_pool_evaluated
    excluded = {e.clinician_id for e in report.excluded}
    for recommendation in report.recommendations:
        assert recommendation.clinician_id not in excluded
        if recommendation.outreach is not None:
            assert recommendation.outreach.clinician_id == recommendation.clinician_id
    assert report.shift is not None
    shift = repository.shift(report.shift.shift_id)
    for recommendation in report.recommendations:
        clinician = repository.clinician(recommendation.clinician_id)
        assert shift is not None and clinician is not None
        assert toolkit.evaluate(shift, clinician).eligible


def test_a_late_valid_submission_is_discarded_for_safe_recovery(
    toolkit: StaffingToolkit, repository: StaffingRepository
) -> None:
    clock = FakeClock()
    late = ai(tool_call(SUBMIT, **submission(rec("C-104", rationale="ACLS expires soon."))))
    steps = [(1.0, step) for step in research_steps()] + [(200.0, late)]
    assistant, _ = timed_assistant(clock, steps, max_run_seconds=180.0)

    report = assistant.run(REQUEST)

    assert report.status is ReportStatus.READY
    assert "answered after the deadline" in report.issues[0].message
    # The rules shortlist, not the late answer (which picked Daniel Kim).
    assert [r.clinician_id for r in report.recommendations] == ["C-101", "C-107"]
    assert_safely_recovered(report, toolkit, repository)
    assert not any(e.kind == "validation" for e in report.trace)


def test_no_model_call_starts_once_the_budget_is_spent(
    toolkit: StaffingToolkit, repository: StaffingRepository
) -> None:
    clock = FakeClock()
    steps = [(100.0, step) for step in research_steps()]
    assistant, model = timed_assistant(clock, steps, max_run_seconds=150.0)

    report = assistant.run(StaffingRequest(text="Fill the ICU shift", shift_id="SHF-1001"))

    assert len(model.timeouts) == 2  # the third call would start after the deadline
    assert model.timeouts == [60.0, 50.0]  # min(LLM_TIMEOUT_SECONDS, time left)
    assert "model time budget of 150s used up" in report.issues[0].message
    assert_safely_recovered(report, toolkit, repository)


def test_a_transient_error_is_retried_within_the_workflow() -> None:
    clock = FakeClock()
    final = ai(tool_call(SUBMIT, **submission(rec("C-101"), rec("C-107"))))
    steps: list[tuple[float, AIMessage | Exception]] = [(1.0, s) for s in research_steps()]
    steps[1:1] = [(1.0, rate_limited())]
    assistant, _ = timed_assistant(clock, [*steps, (1.0, final)])

    report = assistant.run(REQUEST)

    assert (report.mode, report.status) == (RunMode.AGENT, ReportStatus.READY)
    assert clock.sleeps == [1.0]
    assert any("after 1 retry" in e.detail for e in report.trace if e.kind == "llm")


def test_the_openai_adapter_relies_on_budgeted_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK retries are off and each request carries the shortened timeout (no network used)."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")  # never a real endpoint
    monkeypatch.setenv("OPENAI_API_BASE", "http://127.0.0.1:9/v1")
    sent: list[httpx2.Request] = []

    def send(self: httpx2.Client, request: httpx2.Request, **_: Any) -> httpx2.Response:
        sent.append(request)
        clock.now += 2.0
        error = {"error": {"message": "overloaded", "type": "server_error"}}
        return httpx2.Response(503, json=error, request=request)

    monkeypatch.setattr(httpx2.Client, "send", send)  # the transport the OpenAI SDK uses
    clock = FakeClock()
    model = build_chat_model(make_settings(openai_api_key="test-key"), [])
    assert model is not None

    with pytest.raises(openai.InternalServerError):
        invoke_within_budget(
            model,
            MESSAGES,
            deadline=21.0,
            policy=RetryPolicy(max_retries=1, call_timeout=20.0),
            clock=clock,
            sleep=clock.sleep,
        )

    assert len(sent) == 2  # one SDK request per budgeted attempt: SDK retries are disabled
    assert [r.extensions["timeout"]["read"] for r in sent] == [20.0, 18.0]
