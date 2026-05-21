"""SSE endpoint for streaming graph data in node batches.

Streams graph nodes and edges for a given schema as Server-Sent Events,
BATCH_SIZE nodes per event.  Data is fetched live from ArangoDB via
GraphQueryService — no materialized collections needed.

Schema IDs are now schema name strings (e.g. "sf_support", "citation").

Event format
------------
``{"type": "nodes", "nodes": [...], "batch": N, "total_batches": M}``
``{"type": "edges", "edges": [...]}``
``{"type": "done", "node_count": N, "edge_count": E}``
``{"type": "error", "detail": "..."}``

Auth note
---------
EventSource in the browser cannot send custom headers, so the JWT is
accepted via the ``?token=`` query parameter.  A Bearer Authorization
header is also accepted for non-browser callers.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.auth import verify_token
from app.core.database import get_arango_db, get_database
from advandeb_kb.services.graph_query_service import GraphQueryService

router = APIRouter()

BATCH_SIZE = 200
VALID_SCHEMAS = {
    "citation", "sf_support", "taxonomical",
    "knowledge_graph", "physiological_process", "chatbot",
}


async def _require_curator_sse(
    token: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    jwt_token = token
    if not jwt_token and authorization and authorization.startswith("Bearer "):
        jwt_token = authorization[7:]
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(jwt_token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    from bson import ObjectId as ObjId
    db = get_database()
    user_doc = await db.users.find_one({"_id": ObjId(user_id)})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    roles = user_doc.get("roles", [])
    if not any(r in roles for r in ["administrator", "knowledge_curator"]):
        raise HTTPException(status_code=403, detail="Curator access required")
    return {"id": str(user_doc["_id"]), "roles": roles}


@router.get("/schema/{schema_id}/stream", summary="Stream graph data as SSE events")
async def stream_graph(
    schema_id: str,
    limit: int = Query(default=5000, ge=1, le=50_000),
    current_user: dict = Depends(_require_curator_sse),
):
    """Stream graph nodes and edges as Server-Sent Events, BATCH_SIZE nodes per event."""
    if schema_id not in VALID_SCHEMAS:
        async def _err():
            yield f'data: {json.dumps({"type": "error", "detail": f"unknown schema: {schema_id}"})}\n\n'
        return StreamingResponse(_err(), media_type="text/event-stream")

    arango_db = get_arango_db()
    app_db = get_database()
    svc = GraphQueryService(arango_db, app_mongo_db=app_db)

    async def event_generator():
        async for event_type, payload in svc.iter_graph_stream(
            schema_id, limit=limit, batch_size=BATCH_SIZE
        ):
            yield f"data: {json.dumps({'type': event_type, **payload})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
