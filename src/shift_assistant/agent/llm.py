"""Chat model factory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI

from shift_assistant.config import Settings

ToolCallingModel = Runnable[LanguageModelInput, BaseMessage]


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
        max_retries=settings.llm_max_retries,  # exponential backoff on 429/5xx/timeouts
        **reasoning,
    )
    # tool_choice="required": every turn is a tool call, and the run ends via the submit tool.
    return model.bind_tools(list(tool_schemas), tool_choice="required", parallel_tool_calls=True)


def unavailable_model(reason: str = "simulated LLM outage") -> ToolCallingModel:
    """A model that always fails. Used to demonstrate the deterministic fallback path."""

    def fail(_: LanguageModelInput) -> BaseMessage:
        raise ConnectionError(reason)

    return RunnableLambda(fail)
