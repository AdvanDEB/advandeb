"""
EmbeddingService — local sentence-transformers embeddings.

Uses all-MiniLM-L6-v2 by default (~80MB, ~100 texts/sec on CPU).
The model is loaded once and reused across calls (singleton pattern).
"""

from __future__ import annotations

import logging
from typing import Optional

from advandeb_kb.config.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates text embeddings using a local sentence-transformers model.

    Usage:
        svc = EmbeddingService()
        vec = svc.embed_text("DEB energy allocation in fish")
        vecs = svc.embed_batch(["text1", "text2", ...])
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._model = None

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded. Dimension: %d", self.dimension)

    @property
    def dimension(self) -> int:
        self._load()
        return self._model.get_sentence_embedding_dimension()

    # ------------------------------------------------------------------
    # Embedding API
    # ------------------------------------------------------------------

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text string."""
        self._load()
        return self._model.encode(text, convert_to_tensor=False).tolist()

    def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 64,
        show_progress: bool = False,
    ) -> list[list[float]]:
        """
        Batch embed a list of texts.

        Returns a list of float vectors in the same order as input.
        """
        self._load()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_tensor=False,
        )
        # Ensure plain Python floats — ChromaDB rejects numpy.float32
        return [[float(v) for v in e] for e in embeddings]

    def embed_query(self, query: str) -> list[float]:
        """Alias for embed_text — semantic clarity for retrieval queries."""
        return self.embed_text(query)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Cosine similarity between two embedding vectors."""
        import math

        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
