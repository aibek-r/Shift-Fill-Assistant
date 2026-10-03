"""Minimal in-memory vector index with metadata pre-filtering and cosine similarity."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from shift_assistant.retrieval.embedder import Embedder, Matrix


@dataclass(frozen=True)
class Document:
    id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    document: Document
    score: float


DocumentFilter = Callable[[Document], bool]


class VectorIndex:
    """Brute-force cosine search: ample for hundreds of documents; use pgvector/FAISS at scale."""

    def __init__(self, embedder: Embedder, documents: Sequence[Document]) -> None:
        ids = [d.id for d in documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document ids must be unique")
        self._embedder = embedder
        self._documents = list(documents)
        self._by_id = {d.id: d for d in self._documents}
        self._matrix: Matrix = (
            _normalize_rows(embedder.embed_documents([d.text for d in self._documents]))
            if self._documents
            else np.zeros((0, 0), dtype=np.float32)
        )

    def get(self, document_id: str) -> Document | None:
        return self._by_id.get(document_id)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        where: DocumentFilter | None = None,
        min_score: float = 0.0,
    ) -> list[SearchHit]:
        """Filter first (context filtering), then rank only the allowed documents."""
        candidates = [i for i, d in enumerate(self._documents) if where is None or where(d)]
        if not candidates or top_k <= 0:
            return []
        query_vector = _normalize_rows(self._embedder.embed_query(query)[np.newaxis, :])[0]
        scores = self._matrix[candidates] @ query_vector
        ranked = sorted(zip(candidates, scores.tolist(), strict=True), key=lambda p: -p[1])
        return [
            SearchHit(document=self._documents[i], score=round(score, 4))
            for i, score in ranked[:top_k]
            if score >= min_score
        ]


def _normalize_rows(matrix: Matrix) -> Matrix:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.where(norms == 0, 1.0, norms)).astype(np.float32)
