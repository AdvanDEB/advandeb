"""
Knowledge graph API routes.
"""
from fastapi import APIRouter, Depends
from typing import Dict, Any

from app.core.auth import get_current_user
from app.services.graph_service import GraphService


router = APIRouter()


@router.get("/")
async def get_knowledge_graph(
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get knowledge graph."""
    graph_service = GraphService()
    graph = await graph_service.get_graph()
    return graph


@router.get("/query")
async def query_graph(
    query: str,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Query knowledge graph."""
    graph_service = GraphService()
    results = await graph_service.query_graph(query)
    return results
