"""Chat model factory and the model execution budget.

The budget is one monotonic deadline for all model work in a run: every call, retry and backoff
must start before it, and an answer that arrives after it is discarded. Deterministic steps
(tools, completion, verification, fallback) are not limited by it. Calls are synchronous, so a
call in flight is only stopped by its transport timeout, which bounds idle network waits rather
than total elapsed time; the deadline is therefore enforced around calls, not strictly within one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import openai
from langchain_core.exceptions import ModelConnectionError, ModelRateLimitError, ModelTimeoutError
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI

from shift_assistant.config import Settings

ToolCallingModel = Runnable[LanguageModelInput, BaseMessage]
Clock = Callable[[], float]  # monotonic seconds, e.g. time.monotonic
Sleep = Callable[[float], None]

# Transient failures the OpenAI adapter reports: rate limits, timeouts, dropped connections
# (openai.APITimeoutError is an APIConnectionError) and these server statuses.
_TRANSIENT_ERRORS = (
    openai.RateLimitError,
    openai.APIConnectionError,
    ModelRateLimitError,
    ModelConnectionError,
    ModelTimeoutError,
)
_RETRYABLE_SERVER_STATUSES = frozenset({500, 502, 503, 504})


class ModelBudgetExceeded(Exception):
    """The model execution budget ran out: no model work may start, and late output is dropped."""


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int
    call_timeout: float  # upper bound for each call; shortened to the time left in the budget
    backoff_seconds: float = 1.0  # doubles per retry, capped below
    max_backoff_seconds: float = 8.0

    def backoff(self, retry: int) -> float:
        return min(self.max_backoff_seconds, self.backoff_seconds * 2.0**retry)


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(exc, openai.APIStatusError) and status in _RETRYABLE_SERVER_STATUSES


def invoke_within_budget(
    model: ToolCallingModel,
    messages: Sequence[BaseMessage],
    *,
    deadline: float,
    policy: RetryPolicy,
    clock: Clock,
    sleep: Sleep,
) -> tuple[BaseMessage, int]:
    """Call the model with bounded retries, never starting work after `deadline`.

    Returns the response and the number of retries used. Raises ModelBudgetExceeded when the
    budget runs out before a call, before a retry, or while a call was running; non-transient
    errors and the last transient error are re-raised unchanged.
    """
    retries = 0
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise ModelBudgetExceeded("no time left for a model call")
        try:
            response = model.invoke(list(messages), timeout=min(policy.call_timeout, remaining))
        except Exception as exc:
            if not is_transient(exc) or retries >= policy.max_retries:
                raise
            delay = policy.backoff(retries)
            if clock() + delay >= deadline:  # never back off past the deadline
                raise ModelBudgetExceeded(
                    f"no time left to retry after {type(exc).__name__}"
                ) from exc
            sleep(delay)
            retries += 1
            continue
        if clock() > deadline:
            raise ModelBudgetExceeded("the model answered after the deadline; answer discarded")
        return response, retries


def build_chat_model(
    settings: Settings, tool_schemas: Sequence[dict[str, Any]]
) -> ToolCallingModel | None:
    """Return a tool-bound model, or None when no API key is configured (fallback mode)."""
    if not settings.llm_enabled:
        return None
    reasoning: dict[str, Any] = {}
    if settings.openai_reasoning_effort:
        # OpenAI supports reasoning together with function tools only on the Responses API.
        reasoning = {
            "use_responses_api": True,
            "reasoning": {"effort": settings.openai_reasoning_effort},
        }
    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,  # retries run in invoke_within_budget, so backoff counts against the budget
        **reasoning,
    )
    # tool_choice="required": every turn is a tool call, and the run ends via the submit tool.
    return model.bind_tools(list(tool_schemas), tool_choice="required", parallel_tool_calls=True)


def unavailable_model(reason: str = "simulated LLM outage") -> ToolCallingModel:
    """A model that always fails. Used to demonstrate the deterministic fallback path."""

    def fail(_: LanguageModelInput, **__: Any) -> BaseMessage:
        raise ConnectionError(reason)  # not a provider error, so it is not retried

    return RunnableLambda(fail)
