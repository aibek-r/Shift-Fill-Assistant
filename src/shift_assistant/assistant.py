"""Public entry point: wires the components together and runs a request end to end."""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import ValidationError

from shift_assistant.agent.graph import AgentDependencies, build_agent_graph
from shift_assistant.agent.llm import ToolCallingModel, build_chat_model
from shift_assistant.agent.prompts import build_initial_messages
from shift_assistant.agent.state import AgentState, initial_state
from shift_assistant.agent.submission import submission_tool_schema
from shift_assistant.config import Settings
from shift_assistant.contracts import RunMetrics, StaffingReport, StaffingRequest, TraceEvent
from shift_assistant.domain.eligibility import EligibilityEngine
from shift_assistant.reliability.fallback import DeterministicFallback
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.embedder import Embedder, create_embedder
from shift_assistant.retrieval.knowledge import ClinicianProfileIndex, PolicyKnowledgeBase
from shift_assistant.tools.outreach import draft_id_for
from shift_assistant.tools.registry import build_tool_registry, describe_validation_error
from shift_assistant.tools.schemas import DraftOutreachArgs, OutreachDraft
from shift_assistant.tools.toolkit import StaffingToolkit

EventHandler = Callable[[TraceEvent], None]


class ShiftFillAssistant:
    def __init__(
        self,
        settings: Settings,
        repository: StaffingRepository,
        deps: AgentDependencies,
        toolkit: StaffingToolkit,
        retrieval_degraded: bool = False,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.toolkit = toolkit
        # True when the sentence-embedding model failed to load and keyword matching stands in.
        self.retrieval_degraded = retrieval_degraded
        self.llm_enabled = deps.model is not None
        self._graph = build_agent_graph(deps)
        # Each LLM call costs at most three graph steps (agent, tools or validate, verify).
        self._recursion_limit = settings.max_agent_steps * 3 + 10

    def run(self, request: StaffingRequest, on_event: EventHandler | None = None) -> StaffingReport:
        started = time.perf_counter()
        messages = build_initial_messages(
            request, self.settings.today, self.settings.max_recommendations
        )
        final: AgentState | None = None
        for mode, chunk in self._graph.stream(
            initial_state(request, messages),
            config={"recursion_limit": self._recursion_limit},
            stream_mode=["updates", "values"],
        ):
            if mode == "values":
                final = chunk  # type: ignore[assignment]
            elif on_event is not None:
                for node_update in chunk.values():  # type: ignore[union-attr]
                    for event in (node_update or {}).get("trace", []):
                        on_event(event)

        if final is None or final["report"] is None:
            raise RuntimeError("workflow finished without a report")  # unreachable by design
        trace = final["trace"]
        metrics = RunMetrics(
            llm_calls=final["llm_calls"],
            tool_calls=sum(1 for e in trace if e.kind == "tool"),
            input_tokens=sum(e.input_tokens or 0 for e in trace),
            output_tokens=sum(e.output_tokens or 0 for e in trace),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return final["report"].model_copy(update={"trace": trace, "metrics": metrics})

    def revise_outreach(
        self, shift_id: str, clinician_id: str, personal_note: str
    ) -> OutreachDraft:
        """Re-render a draft around a coordinator's edited note.

        Runs the same validation and eligibility checks as the draft_outreach tool, so the shift
        details and credential reminders still come from the system of record.
        Raises ValueError with a readable message when the note or clinician is rejected.
        """
        try:
            args = DraftOutreachArgs(
                shift_id=shift_id, clinician_id=clinician_id, personal_note=personal_note
            )
        except ValidationError as exc:
            raise ValueError(describe_validation_error(exc)) from exc
        output = self.toolkit.draft_outreach(args)
        return output.evidence.drafts[draft_id_for(shift_id, clinician_id)]


def build_assistant(
    settings: Settings | None = None,
    *,
    embedder: Embedder | None = None,
    chat_model: ToolCallingModel | None = None,
) -> ShiftFillAssistant:
    """Composition root. Pass `chat_model` / `embedder` to inject fakes in tests."""
    settings = settings or Settings()
    repository = StaffingRepository.from_directory(settings.data_dir)
    embedder = embedder or create_embedder(settings.embedding_model, settings.cache_dir)
    toolkit = StaffingToolkit(
        repository=repository,
        policies=PolicyKnowledgeBase.from_directory(
            embedder, settings.data_dir / "policies", policy_min_score(settings, embedder)
        ),
        profiles=ClinicianProfileIndex(embedder, repository.clinicians()),
        engine=EligibilityEngine(settings.expiry_warning_days),
    )
    tools = build_tool_registry(toolkit, settings.tool_output_char_limit)
    model = chat_model or build_chat_model(
        settings, [*tools.openai_schemas(), submission_tool_schema()]
    )
    deps = AgentDependencies(
        model=model,
        tools=tools,
        fallback=DeterministicFallback(repository, toolkit, settings.max_recommendations),
        settings=settings,
    )
    return ShiftFillAssistant(
        settings, repository, deps, toolkit, retrieval_degraded=not embedder.semantic
    )


def policy_min_score(settings: Settings, embedder: Embedder) -> float:
    """The relevance cut-off is tuned for sentence embeddings. Keyword-matching scores run much
    lower, so applying it there would silently drop every policy excerpt."""
    return settings.retrieval_min_score if embedder.semantic else 0.0
