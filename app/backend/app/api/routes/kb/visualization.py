"""Visualization API routes for graph snapshots and live graph helpers."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.database import get_arango_db, get_database, get_kb_database
from app.core.dependencies import require_curator
from app.core.config import settings
from advandeb_kb.services.graph_artifact_builder import GraphArtifactBuilder
from advandeb_kb.services.graph_query_service import GraphQueryService
from advandeb_kb.services.graph_artifact_store import GraphArtifactStore
from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue
from advandeb_kb.services.graph_snapshot_service import GraphSnapshotService

router = APIRouter()
logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="viz")

VALID_SCHEMAS = {
    "citation", "sf_support", "taxonomical",
    "knowledge_graph", "physiological_process", "chatbot",
    "reproduction",
}

LIVE_FALLBACK_LIMIT = 50_000


def _get_service() -> GraphQueryService:
    arango_db = get_arango_db()
    app_db = get_database()
    return GraphQueryService(arango_db, app_mongo_db=app_db)


def _get_snapshot_service() -> GraphSnapshotService:
    arango_db = get_arango_db()
    app_db = get_database()
    kb_db = get_kb_database()
    return GraphSnapshotService(arango_db, kb_mongo_db=kb_db, app_mongo_db=app_db)


def _get_artifact_builder() -> GraphArtifactBuilder:
    arango_db = get_arango_db()
    app_db = get_database()
    kb_db = get_kb_database()
    return GraphArtifactBuilder(arango_db, kb_mongo_db=kb_db, app_mongo_db=app_db)


def _get_artifact_store() -> GraphArtifactStore:
    return GraphArtifactStore(get_kb_database(), settings.GRAPH_ARTIFACT_DIR)


def _validate_schema(schema_id: str) -> str:
    """Schema IDs are now schema name strings — validate and return."""
    if schema_id not in VALID_SCHEMAS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown schema: {schema_id!r}. Valid schemas: {sorted(VALID_SCHEMAS)}",
        )
    return schema_id


def _compute_stats(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    node_count = len(nodes)
    edge_count = len(edges)
    density = 0.0
    if node_count > 1:
        max_edges = node_count * (node_count - 1)
        density = edge_count / max_edges if max_edges else 0.0
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "nodes": node_count,
        "edges": edge_count,
        "density": density,
    }


def _compute_type_counts(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    node_types: Dict[str, int] = {}
    edge_types: Dict[str, int] = {}
    for node in nodes:
        node_type = node.get("node_type", "unknown")
        node_types[node_type] = node_types.get(node_type, 0) + 1
    for edge in edges:
        edge_type = edge.get("edge_type", "related")
        edge_types[edge_type] = edge_types.get(edge_type, 0) + 1
    return {"node_types": node_types, "edge_types": edge_types}


def _snapshot_view_is_empty(view: Dict[str, Any]) -> bool:
    stats = view.get("stats") or {}
    node_count = int(stats.get("node_count") or stats.get("nodes") or 0)
    return node_count > 0 and len(view.get("nodes") or []) == 0


async def _build_live_snapshot_view(schema_name: str) -> Dict[str, Any]:
    svc = _get_service()
    data = await svc.get_graph_with_layout(schema_name, layout="force", limit=LIVE_FALLBACK_LIMIT)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    return {
        "schema": schema_name,
        "mode": "live_fallback",
        "expanded_cluster_id": None,
        "snapshot_version": 0,
        "built_at": None,
        "nodes": nodes,
        "edges": edges,
        "stats": _compute_stats(nodes, edges),
        "type_counts": _compute_type_counts(nodes, edges),
    }


@router.get("/schemas", summary="List all graph schemas")
async def list_schemas(
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return all graph schema definitions."""
    loop = asyncio.get_running_loop()
    svc = _get_service()
    schemas = await loop.run_in_executor(_executor, svc.list_schemas)
    artifact_builder = _get_artifact_builder()
    artifact_meta = await artifact_builder.list_public_meta_map()
    for schema in schemas:
        schema["artifact"] = artifact_meta.get(
            schema["_id"],
            _get_artifact_store().normalize_meta(schema["_id"], schema["name"], None),
        )
    return schemas


@router.get("/schema/{schema_id}", summary="Get nodes and edges for a schema")
async def get_schema_graph(
    schema_id: str,
    layout: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return graph data for a schema, queried live from ArangoDB."""
    name = _validate_schema(schema_id)
    svc = _get_service()
    if layout is not None:
        return await svc.get_graph_with_layout(name, layout=layout, limit=limit)
    return await svc.get_graph_data(name, limit=limit)


@router.get("/schema/{schema_id}/status", summary="Get artifact status for a schema")
async def get_schema_artifact_status(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    name = _validate_schema(schema_id)
    builder = _get_artifact_builder()
    return await builder.get_public_meta(name, name)


@router.get("/schema/{schema_id}/artifact", summary="Download the current full graph artifact")
async def get_schema_artifact(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    name = _validate_schema(schema_id)
    store = _get_artifact_store()
    meta = await store.get_public_meta(name, name)
    storage_path = meta.get("storage_path") or ""
    if not storage_path:
        raise HTTPException(
            status_code=404,
            detail=f"No graph artifact is available for schema {name!r}. Trigger a rebuild first.",
        )

    file_path = store.resolve_storage_path(storage_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact file missing for schema {name!r}")

    headers = {
        "Content-Encoding": "gzip",
        "ETag": meta.get("sha256", ""),
        "X-Graph-Build-Id": meta.get("build_id", ""),
        # This URL is stable per schema but its content changes on every
        # rebuild. Without an explicit directive the response is heuristically
        # cacheable (FileResponse sends Last-Modified), so browsers kept serving
        # a months-old artifact and rebuilds never reached anyone. no-cache
        # still allows the cache to be used — it just has to revalidate first,
        # and the ETag makes that a cheap 304.
        "Cache-Control": "no-cache, must-revalidate",
    }
    return FileResponse(
        Path(file_path),
        media_type="application/json",
        filename=f"{name}-{meta.get('build_id', 'artifact')}.json.gz",
        headers=headers,
    )


@router.get("/schema/{schema_id}/snapshot", summary="Get stable graph snapshot view")
async def get_schema_snapshot(
    schema_id: str,
    expand_cluster: Optional[str] = Query(default=None),
    rebuild: bool = Query(default=False),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return the materialized root graph or one expanded cluster view."""
    name = _validate_schema(schema_id)
    svc = _get_snapshot_service()
    view = await svc.get_view(name, expanded_cluster_id=expand_cluster, force_rebuild=rebuild)
    if _snapshot_view_is_empty(view):
        logger.warning("Empty snapshot view for schema=%s expand_cluster=%s; using live fallback", name, expand_cluster)
        return await _build_live_snapshot_view(name)
    return view


@router.get("/schema/{schema_id}/stats", summary="Graph statistics for a schema")
async def get_schema_stats(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return node count, edge count, and density for the schema."""
    name = _validate_schema(schema_id)
    artifact_builder = _get_artifact_builder()
    meta = await artifact_builder.get_public_meta(name, name)
    if meta.get("status") == "ready" and meta.get("node_count", 0) >= 0:
        return {
            "node_count": meta.get("node_count", 0),
            "edge_count": meta.get("edge_count", 0),
            "nodes": meta.get("node_count", 0),
            "edges": meta.get("edge_count", 0),
            "density": meta.get("density", 0.0),
        }
    svc = _get_service()
    return await svc.get_stats(name)


@router.post("/schema/{schema_id}/rebuild", summary="Queue a full graph artifact rebuild")
async def rebuild_schema(
    schema_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Queue a background rebuild of the full graph artifact for a schema."""
    name = _validate_schema(schema_id)
    await graph_rebuild_queue.enqueue_rebuild(name)
    return {
        "schema": name,
        "message": "Graph artifact rebuild queued.",
        "status": "queued",
    }


@router.post("/seed", summary="No-op (schemas are static)")
async def seed_schemas(
    current_user: dict = Depends(require_curator),
) -> Any:
    """
    Graph schemas are now statically defined — no database seeding needed.
    Returns the list of available schemas.
    """
    loop = asyncio.get_running_loop()
    svc = _get_service()
    schemas = await loop.run_in_executor(_executor, svc.list_schemas)
    return {"seed": {"seeded": 0, "skipped": len(schemas)}, "schemas": schemas}


@router.get("/schema/{schema_id}/overview", summary="Get overview graph (top nodes by degree)")
async def get_schema_overview(
    schema_id: str,
    limit: int = Query(default=200, ge=1, le=5000),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return the top-N nodes by degree plus all edges between them."""
    name = _validate_schema(schema_id)
    svc = _get_service()
    return await svc.get_overview(name, limit=limit)


@router.get("/schema/{schema_id}/edges", summary="Get all edges for a schema")
async def get_schema_edges(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return every edge for the schema."""
    name = _validate_schema(schema_id)
    svc = _get_service()
    return await svc.get_all_edges(name)


@router.post("/schema/{schema_id}/expand/{node_id}", summary="Expand a node (load 1-hop neighbors)")
async def expand_node(
    schema_id: str,
    node_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return 1-hop neighbors of node_id not already in loaded_node_ids."""
    name = _validate_schema(schema_id)
    loaded_node_ids: List[str] = body.get("loaded_node_ids", [])
    svc = _get_service()
    return await svc.expand_node(name, node_id=node_id, loaded_node_ids=loaded_node_ids)


@router.post("/schema/{schema_id}/type/{node_type}", summary="Load all nodes of a given type")
async def get_type_nodes(
    schema_id: str,
    node_type: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return all nodes of node_type not already in loaded_node_ids."""
    name = _validate_schema(schema_id)
    loaded_node_ids: List[str] = body.get("loaded_node_ids", [])
    svc = _get_service()
    return await svc.get_type_nodes(name, node_type=node_type, loaded_node_ids=loaded_node_ids)


@router.post("/schema/{schema_id}/layout", summary="No-op (layout is on-demand)")
async def recompute_layout(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """
    Layout is now computed on-demand per request — no persistent storage.
    Use GET /schema/{id}?layout=force to get data with layout applied.
    """
    name = _validate_schema(schema_id)
    return {"schema": name, "message": "Layout is computed on-demand. Use ?layout=force on the graph endpoint."}


@router.get(
    "/schema/{schema_id}/type/{node_type}/page",
    summary="Paginated node-type loader",
)
async def get_type_nodes_paged(
    schema_id: str,
    node_type: str,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=500, ge=1, le=2000),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return a page of nodes of node_type, with pagination metadata."""
    name = _validate_schema(schema_id)
    svc = _get_service()
    return await svc.get_type_nodes_paged(
        name, node_type=node_type, page=page, page_size=page_size
    )


@router.get(
    "/schema/{schema_id}/stats/types",
    summary="Node and edge type counts for a schema",
)
async def get_type_counts(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return {node_type: count} and {edge_type: count} for the schema."""
    name = _validate_schema(schema_id)
    artifact_builder = _get_artifact_builder()
    meta = await artifact_builder.get_public_meta(name, name)
    type_counts = meta.get("type_counts") or {}
    if type_counts.get("node_types") or type_counts.get("edge_types"):
        return type_counts
    svc = _get_service()
    return await svc.get_type_counts(name)
