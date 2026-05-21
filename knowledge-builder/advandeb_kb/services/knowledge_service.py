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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.models.knowledge import Document, Fact, StylizedFact, FactSFRelation
from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="knowledge-svc")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_to_model(raw: dict, model_cls):
    """Map ArangoDB _key → _id (ObjectId alias) and return a pydantic model."""
    if raw is None:
        return None
    # ArangoDB uses _key; our models use _id as the ObjectId alias
    raw = dict(raw)
    if "_key" in raw and "_id" not in raw:
        raw["_id"] = raw["_key"]
    return model_cls(**raw)


class KnowledgeService:
    def __init__(self, database: ArangoDatabase):
        self.db = database

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
        # Serialise datetime fields
        for f in ("created_at", "updated_at"):
            if isinstance(data.get(f), datetime):
                data[f] = data[f].isoformat()
        await self._run(self.db.insert, "documents", data)
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
            col = self.db.db.collection("documents")
            col.update({"_key": document_id, **fields})
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
        """Full-text search over fact content via ArangoDB FULLTEXT index."""
        # Build FULLTEXT-compatible query — prefix search on each word
        ft_terms = ",".join(f"prefix:{w}" for w in query.split() if len(w) > 2)
        if not ft_terms:
            return []
        bind: Dict[str, Any] = {"query": ft_terms, "limit": limit, "domain": general_domain}
        aql = """
        FOR doc IN FULLTEXT('facts', 'content', @query)
            FILTER @domain == null OR doc.general_domain == @domain
            LIMIT @limit
            RETURN doc
        """
        # Fall back to LIKE search if fulltext index not on 'content'
        try:
            rows = await self._run(self.db.aql, aql, bind)
        except Exception:
            # Fallback: substring filter (slower but always works)
            bind2: Dict[str, Any] = {"q": f"%{query}%", "limit": limit}
            f = "FILTER @domain == null OR doc.general_domain == @domain\n" if general_domain else ""
            if general_domain:
                bind2["domain"] = general_domain
            aql2 = f"""
            FOR doc IN facts
                FILTER LIKE(doc.content, @q, true)
                {f}
                LIMIT @limit
                RETURN doc
            """
            rows = await self._run(self.db.aql, aql2, bind2)
        return [_doc_to_model(r, Fact) for r in rows]

    async def search_stylized_facts(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[StylizedFact]:
        """Case-insensitive substring search over stylized fact statements."""
        bind: Dict[str, Any] = {"q": f"%{query}%", "limit": limit}
        filters = ["LIKE(doc.statement, @q, true)"]
        if category:
            filters.append("doc.category == @category")
            bind["category"] = category
        aql = f"""
        FOR doc IN stylized_facts
            FILTER {' AND '.join(filters)}
            LIMIT @limit
            RETURN doc
        """
        rows = await self._run(self.db.aql, aql, bind)
        return [_doc_to_model(r, StylizedFact) for r in rows]

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
