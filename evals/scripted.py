"""A scripted stand-in for the chat model, so evaluation runs are offline and repeatable.

A script fixes what the "model" does. Runs therefore test orchestration and safeguards (tools,
validation, completion, verification, fallback), not live model reasoning.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, ToolCall
from langchain_core.runnables import RunnableLambda

from shift_assistant.agent.llm import ToolCallingModel

_ids = itertools.count(1)


class ScriptExhausted(RuntimeError):
    """The workflow asked for more model turns than the case scripted: a harness error."""


class ScriptedModel:
    def __init__(self, turns: Sequence[AIMessage | Exception]) -> None:
        self._turns = list(turns)
        self.exhausted = False

    def __call__(self, _: LanguageModelInput, timeout: float | None = None) -> BaseMessage:
        if not self._turns:
            self.exhausted = True
            raise ScriptExhausted("the workflow asked for an unscripted model turn")
        turn = self._turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn

    def runnable(self) -> ToolCallingModel:
        return RunnableLambda(self)


def call(name: str, **args: Any) -> ToolCall:
    return ToolCall(name=name, args=args, id=f"eval_call_{next(_ids)}", type="tool_call")


def ai(*calls: ToolCall) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))
