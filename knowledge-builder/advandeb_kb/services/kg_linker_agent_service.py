"""
KGLinkerAgentService — links documents to taxonomy nodes via an Ollama LLM agent.

The agent reads each document's title + abstract and calls the lookup_taxon
tool for each organism it identifies. Results are written to
document_taxon_relations (same schema as KGBuilderService).

Usage:
    svc = KGLinkerAgentService(db)
    result = await svc.link_documents(model="mistral", limit=100)
"""
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


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
    def __init__(self, database):
        self.db = database

    async def link_documents(
        self,
        model: str = "mistral",
        limit: int = 100,
        skip: int = 0,
        overwrite: bool = False,
        max_tool_calls: int = 20,
    ) -> Dict[str, Any]:
        """Process documents and write document_taxon_relations."""
        exclude_ids: set = set()
        if not overwrite:
            async for rel in self.db.document_taxon_relations.find(
                {"created_by": "kg_linker_agent"}, {"document_id": 1}
            ):
                exclude_ids.add(str(rel["document_id"]))

        docs_processed = docs_linked = relations_written = 0
        now = datetime.utcnow()

        async for doc in self.db.documents.find({}, limit=limit, skip=skip):
            if not overwrite and str(doc["_id"]) in exclude_ids:
                continue
            docs_processed += 1
            relations = await self._link_document(doc, model, max_tool_calls, now)
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
        self, doc: Dict, model: str, max_tool_calls: int, now: datetime
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
                    logger.warning("Ollama call failed for doc %s: %s", doc.get("_id"), exc)
                    break

                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    break  # non-JSON → done

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
                    break  # unexpected JSON format → done

        doc_oid = doc["_id"]
        return [
            {
                "document_id": doc_oid,
                "tax_id": tax_id,
                "relation_type": "studies",
                "confidence": round(conf, 3),
                "evidence": evidence,
                "status": "suggested",
                "created_by": "kg_linker_agent",
                "created_at": now,
                "updated_at": now,
            }
            for tax_id, (conf, evidence) in matched.items()
        ]

    async def _lookup_taxon(self, name: str) -> Dict:
        if not name:
            return {"found": False}
        taxon = await self.db.taxonomy_nodes.find_one(
            {"$or": [
                {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
                {"synonyms": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
                {"common_names": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
            ]},
            {"tax_id": 1, "name": 1, "rank": 1}
        )
        if taxon:
            return {
                "found": True,
                "tax_id": taxon["tax_id"],
                "name": taxon["name"],
                "rank": taxon.get("rank", "no rank"),
            }
        return {"found": False, "name": name}

    async def _upsert_relations(self, relations: List[Dict]) -> None:
        from pymongo import UpdateOne
        ops = [
            UpdateOne(
                {"document_id": r["document_id"], "tax_id": r["tax_id"]},
                {"$setOnInsert": r},
                upsert=True,
            )
            for r in relations
        ]
        await self.db.document_taxon_relations.bulk_write(ops, ordered=False)
