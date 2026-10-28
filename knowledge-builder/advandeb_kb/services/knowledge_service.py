"""
KnowledgeService — CRUD and search for core knowledge entities.

Handles Documents, Facts, StylizedFacts, and FactSFRelations (sf_support edges).

Uses the synchronous ArangoDatabase client, dispatched to a thread pool from
async callers via asyncio.get_running_loop().run_in_executor().

ID conventions:
  - Document / Fact / StylizedFact _key  = hex ObjectId string (e.g. "69b8471f…")
  - FactSFRelation _key                  = hex ObjectId string (edge in sf_support)
  - ArangoDB full vertex ID              = "<collection>/<_key>"
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.database.text_search import (
    FACTS_VIEW,
    STYLIZED_FACTS_VIEW,
    TEXT_ANALYZER,
    TextSearchView,
)
from advandeb_kb.models.knowledge import Document, Fact, StylizedFact, FactSFRelation
from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="knowledge-svc")

# How long a missing search view is remembered before looking for it again.
_VIEW_RECHECK_SECONDS = 60.0
# Views whose absence has been logged (once per process, not per instance).
_fallback_warned: set = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_to_model(raw: dict, model_cls):
    """Map ArangoDB _key → _id (ObjectId alias) and return a pydantic model."""
    if raw is None:
        return None
    # Our models use _id as the ObjectId alias, which is the ArangoDB _key.
    # ArangoDB's own _id ("facts/<key>") is always present and must not win.
    raw = dict(raw)
    if "_key" in raw:
        raw["_id"] = raw["_key"]
    return model_cls(**raw)


class KnowledgeService:
    def __init__(self, database: ArangoDatabase):
        self.db = database
        # view name -> (exists, time.monotonic() of the check)
        self._view_checks: Dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Internal: run synchronous ArangoDB calls in thread pool
    # ------------------------------------------------------------------

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    async def create_document(self, document: Document) -> Document:
        data = document.model_dump(by_alias=True)
        key = str(data.pop("_id"))
        data["_key"] = key
        for f in ("created_at", "updated_at"):
            if isinstance(data.get(f), datetime):
                data[f] = data[f].isoformat()
        await self._run(self.db.insert, "documents", data)
        # Mirror pipeline docs into document_meta for fast UI queries
        _WEB_TYPES = {"web"}
        if data.get("source_type") not in _WEB_TYPES:
            try:
                await self._run(self.db.insert, "document_meta", data)
            except Exception:
                pass
        graph_rebuild_queue.mark_dirty("citation")
        return document

    async def get_document(self, document_id: str) -> Optional[Document]:
        raw = await self._run(self.db.get, "documents", document_id)
        return _doc_to_model(raw, Document)

    async def list_documents(
        self,
        skip: int = 0,
        limit: int = 50,
        general_domain: Optional[str] = None,
        processing_status: Optional[str] = None,
    ) -> List[Document]:
        filters = []
        bind: Dict[str, Any] = {"skip": skip, "limit": limit}
        if general_domain:
            filters.append("doc.general_domain == @general_domain")
            bind["general_domain"] = general_domain
        if processing_status:
            filters.append("doc.processing_status == @processing_status")
            bind["processing_status"] = processing_status
        where = ("FILTER " + " AND ".join(filters)) if filters else ""
        aql = f"""
        FOR doc IN documents
            {where}
            SORT doc.created_at DESC
            LIMIT @skip, @limit
            RETURN doc
        """
        rows = await self._run(self.db.aql, aql, bind)
        return [_doc_to_model(r, Document) for r in rows]

    async def update_document(self, document_id: str, fields: Dict[str, Any]) -> Optional[Document]:
        fields["updated_at"] = _now_iso()
        def _update():
            patch = {"_key": document_id, **fields}
            col = self.db.db.collection("documents")
            col.update(patch)
            # Mirror update into document_meta if the doc lives there
            try:
                meta_col = self.db.db.collection("document_meta")
                if meta_col.has(document_id):
                    meta_col.update(patch)
            except Exception:
                pass
            return col.get(document_id)
        raw = await self._run(_update)
        if fields.keys() & {"doi", "references", "title", "year", "authors"}:
            graph_rebuild_queue.mark_dirty("citation")
        return _doc_to_model(raw, Document)

    async def delete_document(self, document_id: str) -> bool:
        def _delete():
            try:
                self.db.delete("documents", document_id)
                return True
            except Exception:
                return False
        return await self._run(_delete)

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------

    async def create_fact(self, fact: Fact) -> Fact:
        data = fact.model_dump(by_alias=True)
        key = str(data.pop("_id"))
        data["_key"] = key
        # Store document_id as plain string key
        if hasattr(data.get("document_id"), "__str__"):
            data["document_id"] = str(data["document_id"])
        data["additional_sources"] = [str(s) for s in data.get("additional_sources", [])]
        for f in ("created_at", "updated_at"):
            if isinstance(data.get(f), datetime):
                data[f] = data[f].isoformat()
        await self._run(self.db.insert, "facts", data)
        graph_rebuild_queue.mark_dirty("sf_support")
        return fact

    async def get_fact(self, fact_id: str) -> Optional[Fact]:
        raw = await self._run(self.db.get, "facts", fact_id)
        return _doc_to_model(raw, Fact)

    async def list_facts(
        self,
        skip: int = 0,
        limit: int = 50,
        document_id: Optional[str] = None,
        general_domain: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Fact]:
        filters = []
        bind: Dict[str, Any] = {"skip": skip, "limit": limit}
        if document_id:
            filters.append("doc.document_id == @document_id")
            bind["document_id"] = document_id
        if general_domain:
            filters.append("doc.general_domain == @general_domain")
            bind["general_domain"] = general_domain
        if status:
            filters.append("doc.status == @status")
            bind["status"] = status
        where = ("FILTER " + " AND ".join(filters)) if filters else ""
        aql = f"""
        FOR doc IN facts
            {where}
            SORT doc.created_at DESC
            LIMIT @skip, @limit
            RETURN doc
        """
        rows = await self._run(self.db.aql, aql, bind)
        return [_doc_to_model(r, Fact) for r in rows]

    async def update_fact(self, fact_id: str, fields: Dict[str, Any]) -> Optional[Fact]:
        fields["updated_at"] = _now_iso()
        def _update():
            col = self.db.db.collection("facts")
            col.update({"_key": fact_id, **fields})
            return col.get(fact_id)
        raw = await self._run(_update)
        return _doc_to_model(raw, Fact)

    async def delete_fact(self, fact_id: str) -> bool:
        def _delete():
            try:
                self.db.delete("facts", fact_id)
                return True
            except Exception:
                return False
        return await self._run(_delete)

    # ------------------------------------------------------------------
    # Stylized Facts
    # ------------------------------------------------------------------

    async def create_stylized_fact(self, sf: StylizedFact) -> StylizedFact:
        data = sf.model_dump(by_alias=True)
        key = str(data.pop("_id"))
        data["_key"] = key
        for f in ("created_at", "updated_at"):
            if isinstance(data.get(f), datetime):
                data[f] = data[f].isoformat()
        await self._run(self.db.insert, "stylized_facts", data)
        return sf

    async def get_stylized_fact(self, sf_id: str) -> Optional[StylizedFact]:
        raw = await self._run(self.db.get, "stylized_facts", sf_id)
        return _doc_to_model(raw, StylizedFact)

    async def list_stylized_facts(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[StylizedFact]:
        filters = []
        bind: Dict[str, Any] = {"skip": skip, "limit": limit}
        if category:
            filters.append("doc.category == @category")
            bind["category"] = category
        if status:
            filters.append("doc.status == @status")
            bind["status"] = status
        where = ("FILTER " + " AND ".join(filters)) if filters else ""
        aql = f"""
        FOR doc IN stylized_facts
            {where}
            SORT doc.sf_number ASC
            LIMIT @skip, @limit
            RETURN doc
        """
        rows = await self._run(self.db.aql, aql, bind)
        return [_doc_to_model(r, StylizedFact) for r in rows]

    async def update_stylized_fact(self, sf_id: str, fields: Dict[str, Any]) -> Optional[StylizedFact]:
        fields["updated_at"] = _now_iso()
        def _update():
            col = self.db.db.collection("stylized_facts")
            col.update({"_key": sf_id, **fields})
            return col.get(sf_id)
        raw = await self._run(_update)
        return _doc_to_model(raw, StylizedFact)

    async def delete_stylized_fact(self, sf_id: str) -> bool:
        def _delete():
            try:
                self.db.delete("stylized_facts", sf_id)
                return True
            except Exception:
                return False
        return await self._run(_delete)

    # ------------------------------------------------------------------
    # Fact ↔ SF Relations  (edge collection: sf_support)
    # ------------------------------------------------------------------

    async def create_relation(self, relation: FactSFRelation) -> FactSFRelation:
        data = relation.model_dump(by_alias=True)
        key = str(data.pop("_id"))
        fact_id = str(data.pop("fact_id"))
        sf_id = str(data.pop("sf_id"))
        data["_key"] = key
        data["_from"] = f"facts/{fact_id}"
        data["_to"] = f"stylized_facts/{sf_id}"
        for f in ("created_at", "updated_at"):
            if isinstance(data.get(f), datetime):
                data[f] = data[f].isoformat()
        await self._run(self.db.insert, "sf_support", data)
        graph_rebuild_queue.mark_dirty("sf_support")
        return relation

    async def get_relation(self, relation_id: str) -> Optional[FactSFRelation]:
        raw = await self._run(self.db.get, "sf_support", relation_id)
        if raw is None:
            return None
        raw = dict(raw)
        raw["_id"] = raw.get("_key", relation_id)
        # Reconstruct fact_id / sf_id from _from / _to
        if "_from" in raw:
            raw["fact_id"] = raw["_from"].split("/")[-1]
        if "_to" in raw:
            raw["sf_id"] = raw["_to"].split("/")[-1]
        return FactSFRelation(**raw)

    async def list_relations(
        self,
        fact_id: Optional[str] = None,
        sf_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[FactSFRelation]:
        filters = []
        bind: Dict[str, Any] = {"skip": skip, "limit": limit}
        if fact_id:
            filters.append("e._from == @fact_from")
            bind["fact_from"] = f"facts/{fact_id}"
        if sf_id:
            filters.append("e._to == @sf_to")
            bind["sf_to"] = f"stylized_facts/{sf_id}"
        if relation_type:
            filters.append("e.relation_type == @relation_type")
            bind["relation_type"] = relation_type
        if status:
            filters.append("e.status == @status")
            bind["status"] = status
        where = ("FILTER " + " AND ".join(filters)) if filters else ""
        aql = f"""
        FOR e IN sf_support
            {where}
            LIMIT @skip, @limit
            RETURN e
        """
        rows = await self._run(self.db.aql, aql, bind)
        results = []
        for r in rows:
            r = dict(r)
            r["_id"] = r.get("_key")
            r["fact_id"] = r["_from"].split("/")[-1]
            r["sf_id"] = r["_to"].split("/")[-1]
            results.append(FactSFRelation(**r))
        return results

    async def update_relation(self, relation_id: str, fields: Dict[str, Any]) -> Optional[FactSFRelation]:
        fields["updated_at"] = _now_iso()
        def _update():
            col = self.db.db.collection("sf_support")
            col.update({"_key": relation_id, **fields})
            return col.get(relation_id)
        raw = await self._run(_update)
        graph_rebuild_queue.mark_dirty("sf_support")
        if raw is None:
            return None
        raw = dict(raw)
        raw["_id"] = raw.get("_key")
        raw["fact_id"] = raw["_from"].split("/")[-1]
        raw["sf_id"] = raw["_to"].split("/")[-1]
        return FactSFRelation(**raw)

    async def delete_relation(self, relation_id: str) -> bool:
        def _delete():
            try:
                self.db.delete("sf_support", relation_id)
                return True
            except Exception:
                return False
        return await self._run(_delete)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_facts(
        self,
        query: str,
        general_domain: Optional[str] = None,
        limit: int = 20,
    ) -> List[Fact]:
        """Keyword search over fact content, best matches first.

        BM25 over the ArangoSearch view on ``facts.content``: the query is
        stemmed and stop words dropped, any term may match, and facts with more
        and rarer query terms rank higher. Without the view, falls back to an
        unranked case-insensitive substring scan of every fact.
        """
        if not query.strip():
            return []

        def _search():
            rows = self._bm25_search(
                FACTS_VIEW, query, {"general_domain": general_domain}, limit
            )
            if rows is None:
                rows = self._like_search(
                    "facts", "content", query, {"general_domain": general_domain}, limit
                )
            return rows

        rows = await self._run(_search)
        return [_doc_to_model(r, Fact) for r in rows]

    async def search_stylized_facts(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[StylizedFact]:
        """Keyword search over stylized fact statements, best matches first.

        Same as :meth:`search_facts`, over the view on ``stylized_facts.statement``.
        """
        if not query.strip():
            return []

        def _search():
            rows = self._bm25_search(
                STYLIZED_FACTS_VIEW, query, {"category": category}, limit
            )
            if rows is None:
                rows = self._like_search(
                    "stylized_facts", "statement", query, {"category": category}, limit
                )
            return rows

        rows = await self._run(_search)
        return [_doc_to_model(r, StylizedFact) for r in rows]

    def _view_ready(self, view: str) -> bool:
        # A view, once seen, is assumed to stay; a failing query forgets it.
        # A missing one is looked for again after _VIEW_RECHECK_SECONDS, so
        # creating it takes effect without a restart.
        exists, checked_at = self._view_checks.get(view, (False, None))
        now = time.monotonic()
        if exists or (checked_at is not None and now - checked_at < _VIEW_RECHECK_SECONDS):
            return exists
        try:
            exists = self.db.has_view(view)
        except Exception as exc:
            logger.warning("Keyword search: could not check view %r: %s", view, exc)
            exists = False
        self._view_checks[view] = (exists, now)
        return exists

    def _bm25_search(
        self,
        view: TextSearchView,
        query: str,
        filters: Dict[str, Optional[str]],
        limit: int,
    ) -> Optional[List[dict]]:
        """BM25-ranked rows from ``view``, or None when the view is unusable."""
        if not self._view_ready(view.name):
            if view.name not in _fallback_warned:
                _fallback_warned.add(view.name)
                logger.warning(
                    "Keyword search: ArangoSearch view %r not found; falling back to "
                    "an unranked LIKE scan of %s. Create it with "
                    "knowledge-builder/scripts/setup_facts_search_views.py.",
                    view.name, view.collection,
                )
            return None
        bind: Dict[str, Any] = {
            "@view": view.name,
            "query": query,
            "analyzer": TEXT_ANALYZER,
            "limit": limit,
        }
        clauses = ""
        for field, value in filters.items():
            if not value:
                continue
            # Equality in SEARCH on a field the view does not index matches
            # nothing, silently.
            if field not in view.filter_fields:
                raise ValueError(f"{field!r} is not indexed in view {view.name!r}")
            clauses += f" AND doc.{field} == @{field}"
            bind[field] = value
        aql = f"""
        FOR doc IN @@view
            SEARCH ANALYZER(doc.{view.text_field} IN TOKENS(@query, @analyzer), @analyzer){clauses}
            SORT BM25(doc) DESC
            LIMIT @limit
            RETURN doc
        """
        try:
            return self.db.aql(aql, bind)
        except Exception as exc:
            logger.warning(
                "Keyword search over view %r failed, falling back to LIKE: %s", view.name, exc
            )
            self._view_checks.pop(view.name, None)
            return None

    def _like_search(
        self,
        collection: str,
        field: str,
        query: str,
        filters: Dict[str, Optional[str]],
        limit: int,
    ) -> List[dict]:
        """Case-insensitive substring match on ``field``: a full scan, unranked."""
        bind: Dict[str, Any] = {"q": f"%{query}%", "limit": limit}
        conditions = [f"LIKE(doc.{field}, @q, true)"]
        for name, value in filters.items():
            if value:
                conditions.append(f"doc.{name} == @{name}")
                bind[name] = value
        aql = f"""
        FOR doc IN {collection}
            FILTER {' AND '.join(conditions)}
            LIMIT @limit
            RETURN doc
        """
        return self.db.aql(aql, bind)

    async def search(
        self,
        query: str,
        general_domain: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Combined search across facts and stylized facts."""
        facts = await self.search_facts(query, general_domain=general_domain, limit=limit)
        sfs = await self.search_stylized_facts(query, limit=limit)
        return {
            "facts": facts,
            "stylized_facts": sfs,
            "total": len(facts) + len(sfs),
        }
