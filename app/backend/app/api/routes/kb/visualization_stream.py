"""SSE endpoint for streaming graph data in node batches.

Streams ``graph_nodes`` and ``graph_edges`` for a given schema as a series of
Server-Sent Events, BATCH_SIZE nodes per event.  This avoids the multi-second
browser freeze caused by receiving a single 20 MB+ JSON body from the full-graph
endpoint.

Event format
------------
Each SSE event carries a JSON object on the ``data:`` line:

``{"type": "nodes", "nodes": [...], "batch": N, "total_batches": M}``
    Node batch (repeated until all nodes sent).

``{"type": "edges", "edges": [...]}``
    Edge batch (repeated until all edges sent, only those whose both endpoints
    were emitted as nodes).

``{"type": "done", "node_count": N, "edge_count": E}``
    Final sentinel — the stream is complete.

``{"type": "error", "detail": "..."}``
    Sent once if a fatal error occurs (e.g. invalid ``schema_id``).

Auth note
---------
``EventSource`` in the browser cannot send custom headers, so the JWT is
accepted via the ``?token=`` query parameter (same pattern as the ingestion
SSE endpoints).  A ``Bearer`` ``Authorization`` header is also accepted for
non-browser callers.
"""
import asyncio
import json
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.auth import verify_token
from app.core.database import get_database, get_kb_database
from advandeb_kb.services.visualization_service import (
    NODE_PROJECTION,
    EDGE_PROJECTION,
    _serialize_node,
    _serialize_edge,
)

router = APIRouter()

BATCH_SIZE = 200  # nodes per SSE event


# SSE streams cannot send custom headers, so we accept the JWT as ?token= query param.
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
    db = get_database()  # users live in the main app DB, not the KB DB
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
    """Stream graph nodes and edges as Server-Sent Events, BATCH_SIZE nodes per event.

    The ``limit`` parameter caps how many nodes are streamed.  All edges whose
    both endpoints fall within the streamed node set are included.
    """
    if not ObjectId.is_valid(schema_id):
        async def _err():
            yield 'data: {"type":"error","detail":"invalid schema_id"}\n\n'
        return StreamingResponse(_err(), media_type="text/event-stream")

    oid = ObjectId(schema_id)
    db = get_kb_database()

    async def event_generator():
        # Defensive filter: match schema_id as ObjectId OR string (guards against
        # type mismatch when edge/node documents were inserted with schema_id as string)
        node_filter = {"$or": [{"schema_id": oid}, {"schema_id": str(oid)}]}
        edge_filter = {"$or": [{"schema_id": oid}, {"schema_id": str(oid)}]}

        # 1. Count for progress reporting (non-blocking)
        node_count = await db.graph_nodes.count_documents(node_filter)
        capped = min(node_count, limit)
        total_batches = max(1, -(-capped // BATCH_SIZE))  # ceiling division

        # 2. Stream nodes in batches
        batch: list = []
        batch_idx = 0
        emitted_node_ids: set = set()
        emitted_edge_count = 0

        async for doc in db.graph_nodes.find(node_filter, NODE_PROJECTION, limit=limit):
            s = _serialize_node(doc)
            emitted_node_ids.add(s["_id"])
            batch.append(s)
            if len(batch) >= BATCH_SIZE:
                payload = json.dumps({
                    "type": "nodes",
                    "nodes": batch,
                    "batch": batch_idx,
                    "total_batches": total_batches,
                })
                yield f"data: {payload}\n\n"
                batch = []
                batch_idx += 1
                await asyncio.sleep(0)  # yield control to the event loop

        # Flush remaining nodes
        if batch:
            payload = json.dumps({
                "type": "nodes",
                "nodes": batch,
                "batch": batch_idx,
                "total_batches": total_batches,
            })
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0)

        # 3. Stream edges in batches (only edges whose endpoints were emitted)
        edge_batch: list = []
        async for doc in db.graph_edges.find(edge_filter, EDGE_PROJECTION):
            s = _serialize_edge(doc)
            if (
                s.get("source_node_id") in emitted_node_ids
                and s.get("target_node_id") in emitted_node_ids
            ):
                edge_batch.append(s)
                emitted_edge_count += 1
                if len(edge_batch) >= BATCH_SIZE * 2:
                    yield f"data: {json.dumps({'type': 'edges', 'edges': edge_batch})}\n\n"
                    edge_batch = []
                    await asyncio.sleep(0)

        if edge_batch:
            yield f"data: {json.dumps({'type': 'edges', 'edges': edge_batch})}\n\n"

        # 4. Done sentinel
        yield f"data: {json.dumps({'type': 'done', 'node_count': len(emitted_node_ids), 'edge_count': emitted_edge_count})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
