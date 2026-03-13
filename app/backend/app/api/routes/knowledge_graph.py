"""
Knowledge graph API routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional

from app.core.auth import get_current_user
from app.services.graph_service import GraphService
from app.services.provenance_service import ProvenanceService


router = APIRouter()


@router.get("/")
async def get_knowledge_graph(
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get knowledge graph in Cytoscape.js format."""
    graph_service = GraphService()
    return await graph_service.get_cytoscape_graph(graph_type="knowledge")


@router.get("/{graph_type}")
async def get_graph_by_type(
    graph_type: str,
    depth: int = 2,
    center_node: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get graph by type (citation, knowledge, taxonomy) in Cytoscape.js format."""
    if graph_type not in ("citation", "knowledge", "taxonomy"):
        raise HTTPException(status_code=400, detail=f"Unknown graph type: {graph_type}")
    graph_service = GraphService()
    return await graph_service.get_cytoscape_graph(
        graph_type=graph_type, depth=depth, center_node=center_node
    )


@router.get("/expand")
async def expand_node(
    node: str,
    hops: int = 1,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return neighboring nodes/edges for incremental graph expansion."""
    graph_service = GraphService()
    return await graph_service.expand_node(node_id=node, hops=hops)


@router.get("/query")
async def query_graph(
    query: str,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Query knowledge graph."""
    graph_service = GraphService()
    return await graph_service.query_graph(query)


@router.get("/provenance/{citation_id}")
async def get_provenance(
    citation_id: str,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get the provenance chain for a citation (Answer → Facts → Chunks → Documents)."""
    provenance_service = ProvenanceService()
    result = await provenance_service.get_provenance(citation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Provenance not found")
    return result


@router.get("/chunk/{chunk_id}/context")
async def get_chunk_context(
    chunk_id: str,
    window: int = 2,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return a chunk with surrounding context chunks."""
    provenance_service = ProvenanceService()
    return await provenance_service.get_chunk_context(chunk_id, window=window)
