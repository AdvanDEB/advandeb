"""
KGLinkerAgentService — links documents to taxonomy nodes via an Ollama LLM agent.

The agent reads each document's title + abstract and calls the lookup_taxon
tool for each organism it identifies. Results are written to the
`knowledge_graph` edge collection in ArangoDB (same as KGBuilderService).

Usage:
    svc = KGLinkerAgentService(arango_db)
    result = await svc.link_documents(model="mistral", limit=100)
"""
import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List

from advandeb_kb.database.arango_client import ArangoDatabase

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kg-linker-agent")

_SYSTEM_PROMPT = """\
You are a taxonomy expert analysing biology and ecology papers.
Given a document title and abstract, identify every organism mentioned — animals, plants, fungi, bacteria, protists — whether by scientific name, common name, or informal reference.

For each organism, call the lookup_taxon tool:
  {"tool": "lookup_taxon", "arguments": {"name": "<name>"}}

Use the most specific name available (binomial > genus > common name).
After you have called lookup_taxon for every organism, respond with exactly:
  {"done": true}

If no organisms are mentioned, respond immediately with:
  {"done": true}

Do not produce any other output. Only JSON.
"""

_CONF = {"species": 0.82, "genus": 0.72, "default": 0.62}


class KGLinkerAgentService:
    def __init__(self, database: ArangoDatabase):
        self.db = database

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))

    async def link_documents(
        self,
        model: str = "mistral",
        limit: int = 100,
        skip: int = 0,
        overwrite: bool = False,
        max_tool_calls: int = 20,
    ) -> Dict[str, Any]:
        """Process documents and write knowledge_graph edges."""
        def _fetch_excluded():
            if overwrite:
                return set()
            rows = self.db.aql(
                "FOR e IN knowledge_graph "
                "FILTER e.created_by == 'kg_linker_agent' "
                "RETURN DISTINCT PARSE_IDENTIFIER(e._from).key"
            )
            return {r for r in rows}

        def _fetch_docs():
            return self.db.aql(
                "FOR doc IN documents LIMIT @skip, @limit "
                "RETURN {_key: doc._key, title: doc.title, abstract: doc.abstract}",
                {"skip": skip, "limit": limit},
            )

        exclude_keys = await self._run(_fetch_excluded)
        docs = await self._run(_fetch_docs)

        docs_processed = docs_linked = relations_written = 0
        now_iso = datetime.utcnow().isoformat()

        for doc in docs:
            if not overwrite and doc["_key"] in exclude_keys:
                continue
            docs_processed += 1
            relations = await self._link_document(doc, model, max_tool_calls, now_iso)
            if relations:
                await self._upsert_relations(relations)
                docs_linked += 1
                relations_written += len(relations)

        logger.info(
            "KGLinkerAgentService — processed: %d, linked: %d, relations: %d",
            docs_processed, docs_linked, relations_written,
        )
        return {
            "documents_processed": docs_processed,
            "documents_linked": docs_linked,
            "relations_written": relations_written,
        }

    async def _link_document(
        self, doc: Dict, model: str, max_tool_calls: int, now_iso: str
    ) -> List[Dict]:
        from advandeb_kb.services.local_model_provider import LocalModelClient

        title = doc.get("title") or ""
        abstract = doc.get("abstract") or ""
        if not title and not abstract:
            return []

        user_msg = f"Title: {title}\n\nAbstract: {abstract[:2000]}"
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        matched: Dict[int, tuple] = {}  # tax_id → (confidence, evidence)

        async with LocalModelClient() as client:
            for _ in range(max_tool_calls):
                try:
                    resp = await client.chat.create(
                        model=model, messages=messages, temperature=0.1
                    )
                    content = resp["choices"][0]["message"]["content"].strip()
                except Exception as exc:
                    logger.warning("Ollama call failed for doc %s: %s", doc.get("_key"), exc)
                    break

                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    break

                if data.get("done"):
                    break

                if data.get("tool") == "lookup_taxon":
                    name = (data.get("arguments") or {}).get("name", "")
                    result = await self._lookup_taxon(name)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "tool",
                        "content": f"lookup_taxon result: {json.dumps(result)}",
                    })
                    if result.get("found"):
                        tax_id = result["tax_id"]
                        rank = result.get("rank", "no rank")
                        conf = _CONF.get(rank, _CONF["default"])
                        if tax_id not in matched or matched[tax_id][0] < conf:
                            matched[tax_id] = (conf, f"agent: {name}")
                else:
                    break

        doc_key = doc["_key"]
        return [
            {
                "_from": f"documents/{doc_key}",
                "_to": f"taxa/{tax_id}",
                "relation_type": "studies",
                "confidence": round(conf, 3),
                "evidence": evidence,
                "status": "suggested",
                "created_by": "kg_linker_agent",
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            for tax_id, (conf, evidence) in matched.items()
        ]

    async def _lookup_taxon(self, name: str) -> Dict:
        if not name:
            return {"found": False}

        def _query():
            escaped = re.escape(name)
            rows = self.db.aql(
                """
                FOR doc IN taxa
                    FILTER LOWER(doc.name) == LOWER(@name)
                    LIMIT 1
                    RETURN {tax_id: doc.tax_id, name: doc.name, rank: doc.rank}
                """,
                {"name": name},
            )
            return rows[0] if rows else None

        taxon = await self._run(_query)
        if taxon:
            return {
                "found": True,
                "tax_id": taxon["tax_id"],
                "name": taxon["name"],
                "rank": taxon.get("rank", "no rank"),
            }
        return {"found": False, "name": name}

    async def _upsert_relations(self, relations: List[Dict]) -> None:
        def _upsert():
            for rel in relations:
                self.db.db.aql.execute(
                    """
                    UPSERT {_from: @from, _to: @to, relation_type: @rtype}
                    INSERT @doc
                    UPDATE {}
                    IN knowledge_graph
                    """,
                    bind_vars={
                        "from": rel["_from"],
                        "to": rel["_to"],
                        "rtype": rel["relation_type"],
                        "doc": rel,
                    },
                )
        await self._run(_upsert)
