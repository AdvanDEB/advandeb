"""
Provenance and retrieval context models.

ProvenanceTrace:
    Full citation trail for one answer — from generated text back to
    source chunks, facts, and documents.

RetrievalContext:
    Captures the complete state of one retrieval operation (all three
    retrieval legs + fusion result) for debugging and evaluation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from advandeb_kb.models.common import PyObjectId


# ---------------------------------------------------------------------------
# Graph path element
# ---------------------------------------------------------------------------

class GraphPathStep(BaseModel):
    """One hop in a graph traversal path."""

    from_id: str       # ArangoDB vertex ID, e.g. "chunks/abc123"
    to_id: str         # ArangoDB vertex ID, e.g. "documents/def456"
    edge_type: str     # Edge collection or relationship label
    edge_attrs: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# ProvenanceTrace
# ---------------------------------------------------------------------------

class ProvenanceTrace(BaseModel):
    """
    Full citation trail from an answer back to its sources.

    Created after a retrieval+synthesis cycle and stored in the
    provenance_traces collection for later inspection.
    """

    id: PyObjectId = Field(
        default_factory=lambda: __import__("bson").ObjectId(), alias="_id"
    )

    # Optional link to the chat session that triggered this retrieval
    session_id: Optional[str] = None

    # The original user query
    query: str

    # IDs of the facts used to build the answer context
    facts_used: list[str] = []

    # ChromaDB chunk IDs retrieved
    chunks_retrieved: list[str] = []

    # MongoDB/ArangoDB document IDs cited
    documents_cited: list[str] = []

    # ArangoDB graph traversal steps (chunk → fact → document → taxon etc.)
    graph_path: list[GraphPathStep] = []

    # Overall confidence of the retrieval (e.g. top RRF score or LLM score)
    confidence_score: float = 0.0

    # Which retrieval methods contributed
    retrieval_methods: list[Literal["vector", "keyword", "graph"]] = []

    # If LLM reranking was used
    reranked: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


# ---------------------------------------------------------------------------
# RetrievalContext
# ---------------------------------------------------------------------------

class RetrievalContext(BaseModel):
    """
    Full snapshot of one retrieval operation — all legs + fusion result.

    Used for debugging retrieval quality and offline evaluation.
    Not stored by default (too verbose); call .store() to persist.
    """

    query: str

    # Raw results from each retrieval leg (before fusion)
    vector_results: list[dict[str, Any]] = []
    keyword_results: list[dict[str, Any]] = []
    graph_expansion: list[dict[str, Any]] = []

    # Chunk IDs in final fused ranking order
    final_ranking: list[str] = []

    # How many vector / keyword hits were combined
    vector_hit_count: int = 0
    keyword_hit_count: int = 0

    # Fusion method used
    fusion_method: Literal["rrf", "linear", "none"] = "rrf"

    # Whether LLM reranking was applied
    reranking_method: Literal["llm", "none"] = "none"

    # Wall-clock time for the full retrieval in ms
    latency_ms: Optional[float] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_provenance_trace(
        self,
        session_id: Optional[str] = None,
        confidence_score: float = 0.0,
        facts_used: Optional[list[str]] = None,
        documents_cited: Optional[list[str]] = None,
        graph_path: Optional[list[GraphPathStep]] = None,
    ) -> ProvenanceTrace:
        """Convert this context into a storable ProvenanceTrace."""
        methods: list[Literal["vector", "keyword", "graph"]] = []
        if self.vector_results:
            methods.append("vector")
        if self.keyword_results:
            methods.append("keyword")
        if self.graph_expansion:
            methods.append("graph")

        return ProvenanceTrace(
            session_id=session_id,
            query=self.query,
            facts_used=facts_used or [],
            chunks_retrieved=self.final_ranking,
            documents_cited=documents_cited or [],
            graph_path=graph_path or [],
            confidence_score=confidence_score,
            retrieval_methods=methods,
            reranked=(self.reranking_method == "llm"),
        )
