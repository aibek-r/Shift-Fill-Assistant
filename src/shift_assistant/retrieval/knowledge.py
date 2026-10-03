"""Domain-specific retrieval: facility policy RAG and semantic ranking of clinician profiles."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from pathlib import Path

from shift_assistant.domain.models import Clinician
from shift_assistant.retrieval.embedder import Embedder
from shift_assistant.retrieval.vector_index import Document, SearchHit, VectorIndex

GLOBAL_SCOPE = "GLOBAL"
"""Policy documents with this scope apply to every facility."""


def chunk_policy_markdown(facility_id: str, markdown: str) -> list[Document]:
    """Split a policy handbook into one chunk per `## ` section.

    Section-level chunks keep each policy self-contained and give stable, human-readable
    citation IDs such as `FAC-001#night-shift-reporting`.
    """
    chunks: list[Document] = []
    sections = re.split(r"^## +", markdown, flags=re.MULTILINE)[1:]
    for section in sections:
        heading, _, body = section.partition("\n")
        heading, body = heading.strip(), body.strip()
        if not body:
            continue
        chunks.append(
            Document(
                id=f"{facility_id}#{_slugify(heading)}",
                text=f"{heading}\n{body}",
                metadata={"facility_id": facility_id, "section": heading},
            )
        )
    return chunks


class PolicyKnowledgeBase:
    def __init__(
        self, embedder: Embedder, documents: Sequence[Document], min_score: float = 0.0
    ) -> None:
        self._index = VectorIndex(embedder, documents)
        self._min_score = min_score

    @classmethod
    def from_directory(
        cls, embedder: Embedder, policy_dir: Path, min_score: float = 0.0
    ) -> PolicyKnowledgeBase:
        documents = [
            chunk
            for path in sorted(policy_dir.glob("*.md"))
            for chunk in chunk_policy_markdown(path.stem, path.read_text(encoding="utf-8"))
        ]
        return cls(embedder, documents, min_score)

    def search(self, facility_id: str, query: str, *, top_k: int = 4) -> list[SearchHit]:
        """Search only the facility's own handbook plus organisation-wide policies."""
        allowed_scopes = {facility_id, GLOBAL_SCOPE}
        return self._index.search(
            query,
            top_k=top_k,
            min_score=self._min_score,
            where=lambda d: d.metadata["facility_id"] in allowed_scopes,
        )


class ClinicianProfileIndex:
    """Semantic ranking over free-text clinician profiles (preferences, experience)."""

    def __init__(self, embedder: Embedder, clinicians: Sequence[Clinician]) -> None:
        self._index = VectorIndex(
            embedder,
            [
                Document(id=c.id, text=f"{', '.join(c.specialties)} nurse. {c.profile}")
                for c in clinicians
            ],
        )

    def rank(self, query: str, clinician_ids: Collection[str], top_k: int) -> list[SearchHit]:
        allowed = set(clinician_ids)
        return self._index.search(query, top_k=top_k, where=lambda d: d.id in allowed)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
