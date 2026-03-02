from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, List, Optional
from advandeb_kb.services.visualization_service import VisualizationService
from advandeb_kb.database.mongodb import get_database

router = APIRouter()

async def get_visualization_service():
    db = await get_database()
    return VisualizationService(db)

@router.get("/graph/{graph_id}")
async def get_graph_visualization(
    graph_id: str,
    layout: str = "spring",
    service: VisualizationService = Depends(get_visualization_service)
):
    """Get graph visualization data"""
    try:
        graph_data = await service.get_graph_visualization(graph_id, layout)
        return graph_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/graph/create")
async def create_graph_from_facts(
    fact_ids: List[str],
    graph_name: str,
    description: str = "",
    service: VisualizationService = Depends(get_visualization_service)
):
    """Create a knowledge graph from selected facts"""
    try:
        graph = await service.create_graph_from_facts(fact_ids, graph_name, description)
        return graph
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/network-stats/{graph_id}")
async def get_network_statistics(
    graph_id: str,
    service: VisualizationService = Depends(get_visualization_service)
):
    """Get network analysis statistics for a graph"""
    try:
        stats = await service.get_network_statistics(graph_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/layout/{graph_id}")
async def update_graph_layout(
    graph_id: str,
    layout_type: str,
    layout_params: Optional[Dict[str, Any]] = None,
    service: VisualizationService = Depends(get_visualization_service)
):
    """Update graph layout"""
    try:
        updated_graph = await service.update_graph_layout(graph_id, layout_type, layout_params)
        return updated_graph
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/relationships/{entity}")
async def get_entity_relationships(
    entity: str,
    depth: int = 2,
    service: VisualizationService = Depends(get_visualization_service)
):
    """Get relationships for a specific entity"""
    try:
        relationships = await service.get_entity_relationships(entity, depth)
        return {"entity": entity, "relationships": relationships}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cluster/{graph_id}")
async def detect_communities(
    graph_id: str,
    algorithm: str = "louvain",
    service: VisualizationService = Depends(get_visualization_service)
):
    """Detect communities/clusters in the knowledge graph"""
    try:
        communities = await service.detect_communities(graph_id, algorithm)
        return {"communities": communities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export/{graph_id}")
async def export_graph(
    graph_id: str,
    format: str = "json",
    service: VisualizationService = Depends(get_visualization_service)
):
    """Export graph in various formats"""
    try:
        exported_data = await service.export_graph(graph_id, format)
        return JSONResponse(content=exported_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))