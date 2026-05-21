"""
Graph / provenance API routes.

Exposes:
  GET /api/graph/provenance/{citation_id}   — full provenance chain for a citation
  GET /api/graph/chunk/{chunk_id}/context   — neighboring chunks for context window
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any

from app.services.provenance_service import ProvenanceService

router = APIRouter()


@router.get("/provenance/{citation_id:path}")
async def get_provenance(citation_id: str) -> Dict[str, Any]:
    """
    Return the provenance chain for a citation.

    The citation_id should be one of:
      - "chunk:<id>"   — a real text chunk
      - "fact:<id>"    — a knowledge-graph fact
      - "sf:<id>"      — a stylized fact
      - legacy raw chunk ids / ``gfact_`` / ``gsf_`` forms

    Returns an object with keys:
      citation_id, answer, facts, chunks, documents
    """
    svc = ProvenanceService()
    data = await svc.get_provenance(citation_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No provenance found for citation '{citation_id}'")
    return data


@router.get("/chunk/{chunk_id}/context")
async def get_chunk_context(
    chunk_id: str,
    window: int = Query(default=2, ge=1, le=10),
) -> Dict[str, Any]:
    """
    Return a chunk and its neighboring chunks (within ±window positions).
    """
    svc = ProvenanceService()
    return await svc.get_chunk_context(chunk_id, window)
