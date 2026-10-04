"""Shared fixtures. Tests run offline: hashing embedder, scripted chat model, no API key."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import pytest
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from shift_assistant.assistant import ShiftFillAssistant, build_assistant
from shift_assistant.config import PROJECT_ROOT, Settings
from shift_assistant.domain.eligibility import EligibilityEngine
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.retrieval.knowledge import ClinicianProfileIndex, PolicyKnowledgeBase
from shift_assistant.tools.registry import ToolRegistry, build_tool_registry
from shift_assistant.tools.toolkit import StaffingToolkit

DATA_DIR = PROJECT_ROOT / "data"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "openai_api_key": None,
        "reference_date": date(2026, 10, 2),
        "retrieval_min_score": 0.0,
        "data_dir": DATA_DIR,
    }
    return Settings(_env_file=None, **{**base, **overrides})


@pytest.fixture(scope="session")
def repository() -> StaffingRepository:
    return StaffingRepository.from_directory(DATA_DIR)


@pytest.fixture(scope="session")
def toolkit(repository: StaffingRepository) -> StaffingToolkit:
    embedder = HashingEmbedder()
    return StaffingToolkit(
        repository=repository,
        policies=PolicyKnowledgeBase.from_directory(embedder, DATA_DIR / "policies"),
        profiles=ClinicianProfileIndex(embedder, repository.clinicians()),
        engine=EligibilityEngine(expiry_warning_days=30),
    )


@pytest.fixture(scope="session")
def registry(toolkit: StaffingToolkit) -> ToolRegistry:
    return build_tool_registry(toolkit, output_char_limit=6000)


# --- Scripted chat model ---------------------------------------------------------------------

_ids = itertools.count(1)


def tool_call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args, "id": f"call_{next(_ids)}", "type": "tool_call"}


def ai(*calls: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))


class ScriptedModel:
    """Replays a fixed list of responses (or raises scripted exceptions) and records its inputs."""

    def __init__(self, responses: Sequence[AIMessage | Exception]) -> None:
        self._responses = list(responses)
        self.received: list[list[BaseMessage]] = []
        self.timeouts: list[float | None] = []  # per-call timeout the workflow passed

    def __call__(self, messages: LanguageModelInput, timeout: float | None = None) -> BaseMessage:
        assert isinstance(messages, list), "the workflow always sends a message list"
        self.received.append([m for m in messages if isinstance(m, BaseMessage)])
        self.timeouts.append(timeout)
        if not self._responses:
            raise AssertionError("ScriptedModel ran out of responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


AssistantFactory = Callable[..., tuple[ShiftFillAssistant, ScriptedModel]]


@pytest.fixture
def scripted_assistant() -> AssistantFactory:
    def factory(
        responses: Sequence[AIMessage | Exception], **settings_overrides: Any
    ) -> tuple[ShiftFillAssistant, ScriptedModel]:
        model = ScriptedModel(responses)
        assistant = build_assistant(
            make_settings(**settings_overrides),
            embedder=HashingEmbedder(),
            chat_model=RunnableLambda(model),
        )
        return assistant, model

    return factory
