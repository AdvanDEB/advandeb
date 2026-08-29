"""
KG Builder API — document-taxon linking, stats, curation.

Document-taxon relations are stored as edges in the ArangoDB
`knowledge_graph` edge collection with relation_type='studies'.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from app.core.database import get_arango_db
from app.core.dependencies import require_curator
from app.kb.pipeline import run_kg_link_agent, run_kg_link_batch
from advandeb_kb.services.kg_builder_service import KGBuilderService
from advandeb_kb.services.kg_linker_agent_service import KGLinkerAgentService

router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kg-builder-route")


@router.get("/stats")
async def get_stats(current_user: dict = Depends(require_curator)) -> Any:
    arango = get_arango_db()
    return await KGBuilderService(arango).get_stats()


@router.post("/link")
async def link_async(
    background_tasks: BackgroundTasks,
    root_taxid: Optional[int] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=100_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    scope: str = Query(default="all", pattern="^(all|curated|with_facts)$"),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Enqueue batch document-taxon keyword linking (background).

    ``root_taxid`` narrows the taxonomy name index to one subtree. Leave it
    unset to index the whole taxonomy — it used to default to 40674 (Mammalia),
    which made the linker blind to every non-mammal in the corpus.
    """
    arango = get_arango_db()
    background_tasks.add_task(run_kg_link_batch, arango, root_taxid, limit, skip, overwrite, scope)
    return {"status": "queued",
            "params": {"root_taxid": root_taxid, "limit": limit, "skip": skip, "scope": scope}}


@router.post("/link/sync")
async def link_sync(
    root_taxid: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    scope: str = Query(default="all", pattern="^(all|curated|with_facts)$"),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Run document-taxon keyword linking synchronously (small batches)."""
    arango = get_arango_db()
    svc = KGBuilderService(arango)
    await svc.ensure_indexes()
    n_indexed = await svc.build_name_index(root_taxid=root_taxid)
    result = await svc.link_documents(limit=limit, skip=skip, overwrite=overwrite, scope=scope)
    result["index_entries"] = n_indexed
    result["root_taxid"] = root_taxid
    return result


@router.post("/link/agent")
async def link_agent_async(
    background_tasks: BackgroundTasks,
    model: str = Query(default="deepseek-r1:latest"),
    limit: int = Query(default=500, ge=1, le=100_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Enqueue LLM agent document-taxon linking (background)."""
    arango = get_arango_db()
    background_tasks.add_task(run_kg_link_agent, arango, model, limit, skip, overwrite)
    return {"status": "queued", "params": {"model": model, "limit": limit, "skip": skip}}


@router.post("/link/agent/sync")
async def link_agent_sync(
    model: str = Query(default="deepseek-r1:latest"),
    limit: int = Query(default=20, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Run LLM agent document-taxon linking synchronously (small batches)."""
    arango = get_arango_db()
    return await KGLinkerAgentService(arango).link_documents(
        model=model, limit=limit, skip=skip, overwrite=overwrite
    )


@router.put("/relations/{relation_key}")
async def update_relation(
    relation_key: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Update status of a document-taxon relation edge."""
    new_status: str = body.get("status", "")
    if new_status not in ("confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'confirmed' or 'rejected'")

    arango = get_arango_db()

    def _update():
        col = arango.db.collection("knowledge_graph")
        doc = col.get(relation_key)
        if doc is None:
            return None
        col.update({
            "_key": relation_key,
            "status": new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": body.get("curator_id", current_user.get("id", "curator")),
        })
        return True

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, _update)
    if result is None:
        raise HTTPException(status_code=404, detail="Relation not found")
    return {"updated": True, "status": new_status}


def _relation_filters(
    status: Optional[str],
    tax_id: Optional[int],
    min_confidence: Optional[float],
    max_confidence: Optional[float],
    created_by: Optional[str],
) -> tuple[str, Dict[str, Any]]:
    """Shared WHERE clause for listing and bulk-updating relations.

    Built once so the review table and the bulk action can never disagree about
    which rows they are talking about — the count shown next to "apply to all"
    has to be the exact set that gets written.
    """
    filters = ["e.relation_type == 'studies'"]
    bind: Dict[str, Any] = {}
    if status:
        filters.append("e.status == @status")
        bind["status"] = status
    if tax_id is not None:
        filters.append("e._to == @to_id")
        bind["to_id"] = f"taxa/{tax_id}"
    if min_confidence is not None:
        filters.append("(e.confidence || 0) >= @min_conf")
        bind["min_conf"] = min_confidence
    if max_confidence is not None:
        filters.append("(e.confidence || 0) <= @max_conf")
        bind["max_conf"] = max_confidence
    if created_by:
        filters.append("e.created_by == @created_by")
        bind["created_by"] = created_by
    return "FILTER " + " AND ".join(filters), bind


@router.get("/relations")
async def list_relations(
    status: Optional[str] = Query(default=None),
    tax_id: Optional[int] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    max_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    created_by: Optional[str] = Query(default=None),
    sample: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_curator),
) -> Any:
    """List document-taxon relation edges from ArangoDB knowledge_graph.

    ``sample=true`` returns a random draw rather than the first page. Reviewing
    the first N rows of 6,003 tells you about those N; a random sample supports
    an error-rate estimate for the whole filtered set, which is what makes a
    bulk decision defensible.
    """
    arango = get_arango_db()

    def _list():
        where, bind = _relation_filters(status, tax_id, min_confidence, max_confidence, created_by)
        bind = {**bind, "skip": skip, "limit": limit}
        # Resolving the document title and taxon name here is not cosmetic: a row
        # reading "document 69d8713f… → taxon 9715" cannot be reviewed by a human.
        order = "SORT RAND()" if sample else "SORT e.confidence DESC, e._key"

        rows = arango.aql(
            f"""
            FOR e IN knowledge_graph
                {where}
                {order}
                LIMIT @skip, @limit
                LET doc = DOCUMENT(e._from)
                LET taxon = DOCUMENT(e._to)
                RETURN {{
                    _key: e._key,
                    document_id: PARSE_IDENTIFIER(e._from).key,
                    document_title: doc.title,
                    document_domain_relevant: doc.domain_relevant,
                    tax_id: TO_NUMBER(PARSE_IDENTIFIER(e._to).key),
                    taxon_name: taxon.name,
                    taxon_rank: taxon.rank,
                    relation_type: e.relation_type,
                    confidence: e.confidence,
                    evidence: e.evidence,
                    status: e.status,
                    created_by: e.created_by,
                    created_at: e.created_at,
                    updated_at: e.updated_at
                }}
            """,
            bind,
        )

        count_bind = {k: v for k, v in bind.items() if k not in ("skip", "limit")}
        total_rows = arango.aql(
            f"RETURN LENGTH(FOR e IN knowledge_graph {where} RETURN 1)",
            count_bind,
        )
        total = total_rows[0] if total_rows else 0
        return {"total": total, "relations": rows}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _list)


# Deterministic rules that resolve a document–taxon link without a human.
#
# Most of this queue does not need judgement: an exact match of a complete
# binomial ("Thunnus albacares") in the title of a domain-relevant paper is a
# string identity, not an opinion. Measured over the 6,003 suggested links,
# these three rules settle 4,415 of them and leave ~1,585 that actually turn on
# a judgement call — bare genus names on in-domain papers.
#
# Auto-decisions are stamped `reviewed_by: "auto:<rule>"` so they never
# masquerade as human review and can be filtered out or reverted wholesale.
_AUTO_RULES: Dict[str, Dict[str, str]] = {
    "off_domain": {
        "status": "rejected",
        "description": "source document was judged off-domain by the relevance gate",
        "filter": """
            LET d = DOCUMENT(e._from)
            FILTER d != null AND d.domain_relevant == false
        """,
    },
    "binomial_species": {
        "status": "confirmed",
        "description": "full binomial matched in a domain-relevant document",
        "filter": """
            LET d = DOCUMENT(e._from)
            LET t = DOCUMENT(e._to)
            LET term = TRIM(SUBSTRING(e.evidence, FIND_FIRST(e.evidence, ':') + 1))
            FILTER d != null AND t != null
               AND d.domain_relevant == true
               AND LENGTH(SPLIT(term, ' ')) > 1
               AND t.rank IN ['species', 'subspecies']
        """,
    },
    "redundant_genus": {
        "status": "rejected",
        "description": "bare genus name where the same document already links a species in that genus",
        "filter": """
            LET t = DOCUMENT(e._to)
            LET term = TRIM(SUBSTRING(e.evidence, FIND_FIRST(e.evidence, ':') + 1))
            FILTER t != null AND t.rank == 'genus' AND LENGTH(SPLIT(term, ' ')) == 1
            FILTER LENGTH(
                FOR e2 IN knowledge_graph
                    FILTER e2._from == e._from
                       AND e2.relation_type == 'studies'
                       AND e2._key != e._key
                    LET t2 = DOCUMENT(e2._to)
                    FILTER t2 != null AND t2.rank == 'species' AND t2.parent_tax_id == t.tax_id
                    RETURN 1
            ) > 0
        """,
    },
}


@router.post("/relations/auto-resolve")
async def auto_resolve_relations(
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Apply the deterministic rules to the suggested-link queue.

    ``dry_run`` (default) reports per-rule counts and writes nothing. Rules are
    applied in order and each only touches links still ``suggested``, so they
    cannot fight over the same row.
    """
    dry_run = bool(body.get("dry_run", True))
    only = body.get("rules") or list(_AUTO_RULES)
    unknown = [r for r in only if r not in _AUTO_RULES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown rules: {unknown}")

    arango = get_arango_db()

    def _apply():
        now = datetime.now(timezone.utc).isoformat()
        results = []
        for name in only:
            rule = _AUTO_RULES[name]
            base = (
                "FOR e IN knowledge_graph\n"
                "  FILTER e.relation_type == 'studies' AND e.status == 'suggested'\n"
                f"  {rule['filter']}\n"
            )
            matched = arango.aql(f"{base} RETURN 1", {})
            count = len(matched)
            if count and not dry_run:
                arango.aql(
                    f"""{base}
                    UPDATE e WITH {{
                        status: @status,
                        updated_at: @now,
                        reviewed_by: @reviewer
                    }} IN knowledge_graph
                    """,
                    {"status": rule["status"], "now": now, "reviewer": f"auto:{name}"},
                )
            results.append({
                "rule": name,
                "action": rule["status"],
                "description": rule["description"],
                "matched": count,
                "applied": 0 if dry_run else count,
            })

        remaining = arango.aql(
            "RETURN LENGTH(FOR e IN knowledge_graph "
            "FILTER e.relation_type == 'studies' AND e.status == 'suggested' RETURN 1)",
            {},
        )
        return {
            "dry_run": dry_run,
            "rules": results,
            "total": sum(r["matched"] for r in results),
            "remaining_suggested": remaining[0] if remaining else 0,
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _apply)


@router.post("/relations/bulk")
async def bulk_update_relations(
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Confirm or reject every relation matching a filter.

    Takes the same filter shape as ``GET /relations`` rather than a list of
    keys, so a decision can cover thousands of rows without the client shipping
    them all back.

    ``dry_run`` (the default) reports how many rows *would* change and writes
    nothing. A bulk status change is not reversible from the UI, so the count
    has to be visible before it is applied, not after.
    """
    new_status: str = body.get("status", "")
    if new_status not in ("confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'confirmed' or 'rejected'")

    dry_run = bool(body.get("dry_run", True))
    flt = body.get("filter") or {}
    arango = get_arango_db()

    def _bulk():
        where, bind = _relation_filters(
            flt.get("status"),
            flt.get("tax_id"),
            flt.get("min_confidence"),
            flt.get("max_confidence"),
            flt.get("created_by"),
        )
        matched = arango.aql(
            f"RETURN LENGTH(FOR e IN knowledge_graph {where} RETURN 1)", bind
        )
        matched_count = matched[0] if matched else 0
        if dry_run or not matched_count:
            return {"matched": matched_count, "updated": 0, "dry_run": True}

        arango.aql(
            f"""
            FOR e IN knowledge_graph
                {where}
                UPDATE e WITH {{
                    status: @new_status,
                    updated_at: @now,
                    reviewed_by: @reviewer
                }} IN knowledge_graph
            """,
            {
                **bind,
                "new_status": new_status,
                "now": datetime.now(timezone.utc).isoformat(),
                "reviewer": body.get("curator_id", current_user.get("id", "curator")),
            },
        )
        return {"matched": matched_count, "updated": matched_count, "dry_run": False}

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, _bulk)
    return {**result, "status": new_status}
