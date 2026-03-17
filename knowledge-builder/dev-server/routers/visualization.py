from fastapi import APIRouter, Body, HTTPException, Query
from typing import Any, Dict, Optional

from advandeb_kb.database.mongodb import get_database
from advandeb_kb.services.visualization_service import VisualizationService
from advandeb_kb.services.graph_builder_service import GraphBuilderService
from bson import ObjectId

router = APIRouter()


async def _get_service() -> VisualizationService:
    db = await get_database()
    return VisualizationService(db)


def _parse_schema_id(schema_id: str) -> ObjectId:
    if not ObjectId.is_valid(schema_id):
        raise HTTPException(status_code=400, detail=f"Invalid schema_id: {schema_id!r}")
    return ObjectId(schema_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/schemas", summary="List all graph schemas")
async def list_schemas() -> Any:
    """Return all graph schema definitions stored in the database."""
    service = await _get_service()
    return await service.list_schemas()


@router.get("/schema/{schema_id}", summary="Get nodes and edges for a schema")
async def get_schema_graph(
    schema_id: str,
    layout: Optional[str] = Query(default=None, description="Layout algorithm: force, circular, random, shell"),
    limit: int = Query(default=300, ge=1, le=100_000, description="Max number of nodes to return"),
) -> Any:
    """Return materialized graph data for a schema.

    If *layout* is provided, x/y positions are computed server-side via NetworkX.
    If omitted, raw nodes/edges are returned without position data.
    """
    oid = _parse_schema_id(schema_id)
    service = await _get_service()

    if layout is not None:
        data = await service.get_graph_with_layout(oid, layout=layout, limit=limit)
    else:
        data = await service.get_graph_data(oid, limit=limit)

    return data


@router.get("/schema/{schema_id}/stats", summary="Graph statistics for a schema")
async def get_schema_stats(schema_id: str) -> Any:
    """Return node count, edge count, and density for the schema."""
    oid = _parse_schema_id(schema_id)
    service = await _get_service()
    return await service.get_stats(oid)


@router.post("/schema/{schema_id}/rebuild", summary="Rebuild a graph schema")
async def rebuild_schema(
    schema_id: str,
    body: Dict[str, Any] = Body(default={}),
) -> Any:
    """Rebuild nodes and edges for a schema from source collections.

    - sf_support: rebuilds from stylized_facts
    - taxonomical: rebuilds from taxonomy_nodes; accepts root_taxid and max_nodes in body
    """
    oid = _parse_schema_id(schema_id)
    db = await get_database()

    schema = await db.graph_schemas.find_one({"_id": oid})
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    builder = GraphBuilderService(db)
    name = schema.get("name", "")

    if name == "sf_support":
        result = await builder.build_sf_graph(oid)
    elif name == "taxonomical":
        root_taxid = int(body.get("root_taxid", 40674))  # default: Mammalia
        max_nodes = int(body.get("max_nodes", 15000))
        result = await builder.build_taxonomy_graph(oid, root_taxid=root_taxid, max_nodes=max_nodes)
    elif name == "citation":
        result = await builder.build_citation_graph(oid)
    elif name == "knowledge_graph":
        root_taxid = int(body.get("root_taxid", 40674))  # default: Mammalia
        max_nodes = int(body.get("max_nodes", 15000))
        result = await builder.build_knowledge_graph(oid, root_taxid=root_taxid, max_nodes=max_nodes)
    else:
        raise HTTPException(status_code=400, detail=f"No rebuild strategy for schema: {name!r}")

    return result


@router.post("/seed", summary="Seed built-in graph schemas")
async def seed_schemas() -> Any:
    """Upsert all built-in schema definitions into graph_schemas collection.

    Safe to call repeatedly — uses upsert on schema name.
    Returns seed summary and the full list of schemas after seeding.
    """
    db = await get_database()
    builder = GraphBuilderService(db)
    seed_result = await builder.seed_schemas()
    service = VisualizationService(db)
    schemas = await service.list_schemas()
    return {"seed": seed_result, "schemas": schemas}
