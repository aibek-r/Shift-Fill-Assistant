"""Text embedders behind a small protocol so retrieval does not depend on one provider."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

Vector = NDArray[np.float32]
Matrix = NDArray[np.float32]


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def semantic(self) -> bool:
        """True for sentence embeddings; False for keyword matching, whose scores run lower."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> Matrix: ...

    def embed_query(self, text: str) -> Vector: ...


class FastEmbedEmbedder:
    """Local ONNX sentence embeddings (no API key, no data leaves the machine)."""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from fastembed import TextEmbedding  # heavy import, deferred until needed

        self._name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))

    @property
    def name(self) -> str:
        return self._name

    @property
    def semantic(self) -> bool:
        return True

    def embed_documents(self, texts: Sequence[str]) -> Matrix:
        return np.asarray(list(self._model.passage_embed(list(texts))), dtype=np.float32)

    def embed_query(self, text: str) -> Vector:
        return np.asarray(next(iter(self._model.query_embed(text))), dtype=np.float32)


class HashingEmbedder:
    """Deterministic bag-of-words embedder.

    Used by tests (fast, no model download) and as an offline fallback when the
    sentence-embedding model cannot be loaded.
    """

    def __init__(self, dimensions: int = 512) -> None:
        self._dimensions = dimensions

    @property
    def name(self) -> str:
        return f"hashing-{self._dimensions}"

    @property
    def semantic(self) -> bool:
        return False

    def embed_documents(self, texts: Sequence[str]) -> Matrix:
        return np.stack([self.embed_query(text) for text in texts]).astype(np.float32)

    def embed_query(self, text: str) -> Vector:
        vector = np.zeros(self._dimensions, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            vector[int.from_bytes(digest, "big") % self._dimensions] += 1.0
        return vector


def create_embedder(model_name: str, cache_dir: Path) -> Embedder:
    try:
        return FastEmbedEmbedder(model_name, cache_dir / "fastembed")
    except Exception:  # model download or ONNX runtime failure: degrade, don't crash
        logger.warning(
            "Could not load %s; using HashingEmbedder instead.", model_name, exc_info=True
        )
        return HashingEmbedder()
