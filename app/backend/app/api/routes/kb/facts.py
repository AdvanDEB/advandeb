"""
KB facts API — ArangoDB stylized_facts and facts collections.

GET /api/kb/stylized-facts/   — list stylized facts (paginated)
GET /api/kb/facts/            — list extracted KB facts (paginated)
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.database import get_arango_db

stylized_router = APIRouter()
facts_router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kb-facts-route")


# ---------------------------------------------------------------------------
# Stylized facts
# ---------------------------------------------------------------------------

@stylized_router.get("")
@stylized_router.get("/")
async def list_stylized_facts(
    search: str = "",
    category: str = "",
    limit: int = 50,
    skip: int = 0,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    arango = get_arango_db()

    filters: List[str] = []
    bind_vars: Dict[str, Any] = {"skip": skip, "limit": limit}

    if search:
        filters.append("CONTAINS(LOWER(doc.statement), LOWER(@search))")
        bind_vars["search"] = search

    if category:
        filters.append("doc.category == @category")
        bind_vars["category"] = category

    where = "\n".join(f"  FILTER {f}" for f in filters)

    aql_items = f"""
    FOR doc IN stylized_facts
      {where}
      SORT doc.sf_number ASC
      LIMIT @skip, @limit
      RETURN {{
        id: doc._key,
        sf_number: doc.sf_number,
        statement: doc.statement,
        category: doc.category,
        status: doc.status,
        created_at: doc.created_at
      }}
    """

    aql_count = f"""
    RETURN LENGTH(
      FOR doc IN stylized_facts
        {where}
        RETURN 1
    )
    """

    def _fetch():
        items = arango.aql(aql_items, bind_vars)
        count_bind = {k: v for k, v in bind_vars.items() if k not in ("skip", "limit")}
        total_result = arango.aql(aql_count, count_bind)
        total = total_result[0] if total_result else 0
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _fetch)


# ---------------------------------------------------------------------------
# Extracted KB facts
# ---------------------------------------------------------------------------

@facts_router.get("")
@facts_router.get("/")
async def list_kb_facts(
    search: str = "",
    domain: str = "",
    limit: int = 50,
    skip: int = 0,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    arango = get_arango_db()

    filters: List[str] = []
    bind_vars: Dict[str, Any] = {"skip": skip, "limit": limit}

    if search:
        filters.append("CONTAINS(LOWER(doc.content), LOWER(@search))")
        bind_vars["search"] = search

    if domain == "__none__":
        filters.append("(doc.general_domain == null OR doc.general_domain == '')")
    elif domain:
        filters.append("doc.general_domain == @domain")
        bind_vars["domain"] = domain

    where = "\n".join(f"  FILTER {f}" for f in filters)

    aql_items = f"""
    FOR doc IN facts
      {where}
      SORT doc._key DESC
      LIMIT @skip, @limit
      RETURN {{
        id: doc._key,
        content: doc.content,
        document_id: doc.document_id,
        page_number: doc.page_number,
        confidence: doc.confidence,
        tags: doc.tags,
        general_domain: doc.general_domain,
        status: doc.status,
        created_at: doc.created_at
      }}
    """

    aql_count = f"""
    RETURN LENGTH(
      FOR doc IN facts
        {where}
        RETURN 1
    )
    """

    def _fetch():
        items = arango.aql(aql_items, bind_vars)
        count_bind = {k: v for k, v in bind_vars.items() if k not in ("skip", "limit")}
        total_result = arango.aql(aql_count, count_bind)
        total = total_result[0] if total_result else 0
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _fetch)
