from fastapi import APIRouter, Body, Depends, HTTPException, Query
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.core.database import get_kb_database as get_database
from app.core.dependencies import require_curator
from advandeb_kb.services.visualization_service import VisualizationService
from advandeb_kb.services.graph_builder_service import GraphBuilderService

router = APIRouter()


def _parse_schema_id(schema_id: str) -> ObjectId:
    if not ObjectId.is_valid(schema_id):
        raise HTTPException(status_code=400, detail=f"Invalid schema_id: {schema_id!r}")
    return ObjectId(schema_id)


@router.get("/schemas", summary="List all graph schemas")
async def list_schemas(
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return all graph schema definitions stored in the database."""
    db = get_database()
    return await VisualizationService(db).list_schemas()


@router.get("/schema/{schema_id}", summary="Get nodes and edges for a schema")
async def get_schema_graph(
    schema_id: str,
    layout: Optional[str] = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=5000),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return materialized graph data for a schema.

    If the schema has never been built (zero nodes), automatically triggers a
    rebuild so the first open of a schema always shows data.
    """
    oid = _parse_schema_id(schema_id)
    db = get_database()
    service = VisualizationService(db)

    # Auto-rebuild on first open: if the graph is empty, build it now.
    node_count = await db.graph_nodes.count_documents({"schema_id": oid})
    if node_count == 0:
        schema = await db.graph_schemas.find_one({"_id": oid})
        if schema:
            builder = GraphBuilderService(db)
            name = schema.get("name", "")
            if name == "sf_support":
                await builder.build_sf_graph(oid)
            elif name == "citation":
                await builder.build_citation_graph(oid)
            # taxonomical / knowledge_graph / physiological_process require
            # extra parameters, so skip auto-rebuild for those — user must
            # click "↺ Rebuild" manually.

    if layout is not None:
        return await service.get_graph_with_layout(oid, layout=layout, limit=limit)
    return await service.get_graph_data(oid, limit=limit)


@router.get("/schema/{schema_id}/stats", summary="Graph statistics for a schema")
async def get_schema_stats(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return node count, edge count, and density for the schema."""
    oid = _parse_schema_id(schema_id)
    db = get_database()
    return await VisualizationService(db).get_stats(oid)


@router.post("/schema/{schema_id}/rebuild", summary="Rebuild a graph schema")
async def rebuild_schema(
    schema_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Rebuild nodes and edges for a schema from source collections."""
    oid = _parse_schema_id(schema_id)
    db = get_database()

    schema = await db.graph_schemas.find_one({"_id": oid})
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    builder = GraphBuilderService(db, viz_service=VisualizationService(db))
    name = schema.get("name", "")

    if name == "sf_support":
        return await builder.build_sf_graph(oid)
    elif name == "taxonomical":
        root_taxid = int(body.get("root_taxid", 40674))
        max_nodes = int(body.get("max_nodes", 15000))
        return await builder.build_taxonomy_graph(oid, root_taxid=root_taxid, max_nodes=max_nodes)
    elif name == "citation":
        return await builder.build_citation_graph(oid)
    elif name == "knowledge_graph":
        root_taxid = int(body.get("root_taxid", 40674))
        max_nodes = int(body.get("max_nodes", 15000))
        return await builder.build_knowledge_graph(oid, root_taxid=root_taxid, max_nodes=max_nodes)
    elif name == "physiological_process":
        root_taxid_raw = body.get("root_taxid")
        root_taxid = int(root_taxid_raw) if root_taxid_raw is not None else None
        return await builder.build_physiological_graph(oid, root_taxid=root_taxid)
    else:
        raise HTTPException(status_code=400, detail=f"No rebuild strategy for schema: {name!r}")


@router.post("/seed", summary="Seed built-in graph schemas")
async def seed_schemas(
    current_user: dict = Depends(require_curator),
) -> Any:
    """Upsert all built-in schema definitions. Safe to call repeatedly."""
    db = get_database()
    builder = GraphBuilderService(db)
    seed_result = await builder.seed_schemas()
    schemas = await VisualizationService(db).list_schemas()
    return {"seed": seed_result, "schemas": schemas}


@router.get("/schema/{schema_id}/overview", summary="Get overview graph (top nodes by degree)")
async def get_schema_overview(
    schema_id: str,
    limit: int = Query(default=200, ge=1, le=5000),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return the top-N nodes by degree plus all edges between them.

    Useful for a fast first-load of large schemas — returns hub nodes that
    connect to the most other nodes, giving a representative overview without
    loading the full graph.
    """
    oid = _parse_schema_id(schema_id)
    db = get_database()
    return await VisualizationService(db).get_overview(oid, limit=limit)


@router.get("/schema/{schema_id}/edges", summary="Get all edges for a schema")
async def get_schema_edges(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return every edge for the schema.

    Called after all nodes have been loaded (e.g. via 'Load all nodes') so
    the full edge set can be rendered in a single request.
    """
    oid = _parse_schema_id(schema_id)
    db = get_database()
    return await VisualizationService(db).get_all_edges(oid)


@router.post("/schema/{schema_id}/expand/{node_id}", summary="Expand a node (load 1-hop neighbors)")
async def expand_node(
    schema_id: str,
    node_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return 1-hop neighbors of `node_id` not already in `loaded_node_ids`.

    Request body:
        { "loaded_node_ids": ["id1", "id2", ...] }

    Response includes the new neighbor nodes and all edges connecting them to
    `node_id` or to any already-loaded node.
    """
    oid = _parse_schema_id(schema_id)
    loaded_node_ids: List[str] = body.get("loaded_node_ids", [])
    db = get_database()
    return await VisualizationService(db).expand_node(oid, node_id=node_id, loaded_node_ids=loaded_node_ids)


@router.post("/schema/{schema_id}/type/{node_type}", summary="Load all nodes of a given type")
async def get_type_nodes(
    schema_id: str,
    node_type: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return all nodes of `node_type` not already in `loaded_node_ids`.

    Request body:
        { "loaded_node_ids": ["id1", "id2", ...] }

    Response includes the new nodes and all edges connecting them to any
    already-loaded node.
    """
    oid = _parse_schema_id(schema_id)
    loaded_node_ids: List[str] = body.get("loaded_node_ids", [])
    db = get_database()
    return await VisualizationService(db).get_type_nodes(oid, node_type=node_type, loaded_node_ids=loaded_node_ids)


@router.post("/schema/{schema_id}/layout", summary="Recompute and persist layout for a schema")
async def recompute_layout(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """Recompute and persist layout for an existing schema graph.

    Useful for adjusting layout parameters without running a full rebuild.
    """
    oid = _parse_schema_id(schema_id)
    db = get_database()
    schema_doc = await db.graph_schemas.find_one({"_id": oid})
    if not schema_doc:
        raise HTTPException(status_code=404, detail="Schema not found")
    schema_name = schema_doc.get("name", "")
    svc = VisualizationService(db)
    result = await svc.compute_and_store_layout(oid, schema_name)
    return result


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
    """Return a page of nodes of ``node_type``, with pagination metadata.

    Replaces the old ``POST /schema/{id}/type/{type}`` for new frontend code.
    Edges are not included — load them on demand via ``expand_node``.
    """
    oid = _parse_schema_id(schema_id)
    db = get_database()
    return await VisualizationService(db).get_type_nodes_paged(
        oid, node_type=node_type, page=page, page_size=page_size
    )


@router.get(
    "/schema/{schema_id}/stats/types",
    summary="Node and edge type counts for a schema",
)
async def get_type_counts(
    schema_id: str,
    current_user: dict = Depends(require_curator),
) -> Any:
    """Return ``{node_type: count}`` and ``{edge_type: count}`` for the schema.

    Lets the frontend render filter bars / expand buttons without loading any
    actual node documents.
    """
    oid = _parse_schema_id(schema_id)
    db = get_database()
    return await VisualizationService(db).get_type_counts(oid)
