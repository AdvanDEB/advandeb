"""
CuratorAgent — knowledge curation and validation agent (port 8085).

Tools exposed via MCP:
    extract_facts        — extract structured facts from a document
    stylize_fact         — suggest FactSFRelation links for a fact
    build_knowledge_graph — trigger graph materialization for a schema
    get_curation_queue   — list pending facts/relations awaiting review
    confirm_relation     — curator action: confirm a suggested FactSFRelation
    reject_relation      — curator action: reject a suggested FactSFRelation

Bridges the existing advandeb_kb AgentService + KnowledgeService into
the new MCP protocol, so the agent network can invoke curation logic.

Run as standalone process:
    python -m advandeb_kb.agents.curator_agent
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.config.settings import settings

logger = logging.getLogger(__name__)

AGENT_PORT = 8085
_executor = ThreadPoolExecutor(max_workers=2)


class CuratorAgent(BaseAgent):
    """
    Agent for knowledge curation: fact extraction, stylization, KG building.

    Uses the existing advandeb_kb service stack (MongoDB-backed) via async
    Motor client, bridging it to the MCP WebSocket protocol.
    """

    def __init__(self, port: int = AGENT_PORT, host: str = "localhost"):
        super().__init__(name="curator_agent", port=port, host=host)
        self._db = None
        self._knowledge_svc = None
        self._agent_svc = None
        self._graph_builder_svc = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        from motor.motor_asyncio import AsyncIOMotorClient
        from advandeb_kb.services.knowledge_service import KnowledgeService
        from advandeb_kb.services.agent_service import AgentService
        from advandeb_kb.services.graph_builder_service import GraphBuilderService

        client = AsyncIOMotorClient(settings.MONGODB_URL)
        self._db = client[settings.DATABASE_NAME]

        self._knowledge_svc = KnowledgeService(self._db)
        self._agent_svc = AgentService(self._db)
        self._graph_builder_svc = GraphBuilderService(self._db)

        # Ensure builtin graph schemas are seeded
        await self._graph_builder_svc.seed_schemas()

        doc_count = await self._db.documents.count_documents({})
        fact_count = await self._db.facts.count_documents({})
        sf_count = await self._db.stylized_facts.count_documents({})
        logger.info(
            "CuratorAgent initialized — docs=%d facts=%d sfs=%d",
            doc_count,
            fact_count,
            sf_count,
        )

    def register_tools(self) -> None:
        self.server.register_tool(
            name="extract_facts",
            handler=self._extract_facts,
            description=(
                "Extract structured scientific facts from a document's text content. "
                "Creates Fact records in MongoDB linked to the document."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "MongoDB ObjectId of the document",
                    },
                    "model": {"type": "string", "default": settings.OLLAMA_MODEL},
                },
                "required": ["document_id"],
            },
        )
        self.server.register_tool(
            name="stylize_fact",
            handler=self._stylize_fact,
            description=(
                "Suggest FactSFRelation links for a fact — find stylized facts "
                "that the given fact supports or opposes."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "fact_id": {"type": "string"},
                    "max_suggestions": {"type": "integer", "default": 5},
                },
                "required": ["fact_id"],
            },
        )
        self.server.register_tool(
            name="build_knowledge_graph",
            handler=self._build_knowledge_graph,
            description="Trigger materialization of a named knowledge graph schema.",
            input_schema={
                "type": "object",
                "properties": {
                    "schema_name": {
                        "type": "string",
                        "enum": [
                            "sf_support",
                            "taxonomical",
                            "knowledge_graph",
                            "citation",
                            "physiological_process",
                        ],
                    },
                    "clear_existing": {"type": "boolean", "default": False},
                },
                "required": ["schema_name"],
            },
        )
        self.server.register_tool(
            name="get_curation_queue",
            handler=self._get_curation_queue,
            description=(
                "Return pending facts and FactSFRelations awaiting curator review."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["facts", "relations", "both"],
                        "default": "both",
                    },
                    "limit": {"type": "integer", "default": 20},
                },
            },
        )
        self.server.register_tool(
            name="confirm_relation",
            handler=self._confirm_relation,
            description="Confirm a suggested FactSFRelation (curator decision).",
            input_schema={
                "type": "object",
                "properties": {
                    "relation_id": {"type": "string"},
                    "confirmed_by": {"type": "string", "default": "curator"},
                },
                "required": ["relation_id"],
            },
        )
        self.server.register_tool(
            name="reject_relation",
            handler=self._reject_relation,
            description="Reject a suggested FactSFRelation (curator decision).",
            input_schema={
                "type": "object",
                "properties": {
                    "relation_id": {"type": "string"},
                    "rejected_by": {"type": "string", "default": "curator"},
                },
                "required": ["relation_id"],
            },
        )

    # ------------------------------------------------------------------
    # Tool: extract_facts
    # ------------------------------------------------------------------

    async def _extract_facts(
        self, document_id: str, model: str = ""
    ) -> dict:
        if not model:
            model = settings.OLLAMA_MODEL
        from bson import ObjectId

        doc = await self._db.documents.find_one({"_id": ObjectId(document_id)})
        if not doc:
            return {"error": f"Document not found: {document_id}", "facts": []}

        text = doc.get("content") or doc.get("abstract") or ""
        if not text.strip():
            return {"error": "Document has no text content", "facts": []}

        # Delegate to existing AgentService (uses agent framework + Ollama)
        try:
            fact_texts = await self._agent_svc.extract_facts(text, model=model)
        except Exception as exc:
            logger.error("extract_facts AgentService error: %s", exc)
            return {"error": str(exc), "facts": []}

        # Persist extracted facts to MongoDB
        from advandeb_kb.models.knowledge import Fact
        from datetime import datetime
        from bson import ObjectId as ObjId

        created_ids: list[str] = []
        for fact_text in fact_texts:
            if not fact_text or len(fact_text.strip()) < 10:
                continue
            fact = Fact(
                content=fact_text.strip(),
                document_id=ObjId(document_id),
                confidence=0.8,
                tags=["extracted", "agent"],
                status="pending",
                general_domain=doc.get("general_domain"),
            )
            await self._db.facts.insert_one(fact.model_dump(by_alias=True))
            created_ids.append(str(fact.id))

        return {
            "document_id": document_id,
            "extracted_count": len(created_ids),
            "fact_ids": created_ids,
        }

    # ------------------------------------------------------------------
    # Tool: stylize_fact
    # ------------------------------------------------------------------

    async def _stylize_fact(
        self, fact_id: str, max_suggestions: int = 5
    ) -> dict:
        from bson import ObjectId
        import re

        fact_doc = await self._db.facts.find_one({"_id": ObjectId(fact_id)})
        if not fact_doc:
            return {"error": f"Fact not found: {fact_id}", "suggestions": []}

        fact_content = fact_doc.get("content", "")

        # Keyword overlap matching (same logic as ingestion_tasks)
        _STOPWORDS = {
            "that", "with", "from", "this", "have", "been", "which",
            "their", "there", "they", "when", "where", "than", "more",
        }
        fact_words = {
            w.lower().strip(".,;:()")
            for w in fact_content.split()
            if len(w) > 4 and w.lower() not in _STOPWORDS
        }

        suggestions: list[dict] = []
        if fact_words:
            pattern = "|".join(re.escape(w) for w in sorted(fact_words))
            cursor = self._db.stylized_facts.find(
                {
                    "statement": {"$regex": pattern, "$options": "i"},
                    "status": "published",
                },
                {"_id": 1, "statement": 1, "category": 1},
            ).limit(max_suggestions * 3)

            async for sf in cursor:
                sf_words = {
                    w.lower().strip(".,;:()")
                    for w in sf["statement"].split()
                    if len(w) > 4 and w.lower() not in _STOPWORDS
                }
                overlap = len(fact_words & sf_words)
                if overlap < 2:
                    continue
                confidence = round(
                    min(0.6, overlap / max(len(fact_words), len(sf_words))), 2
                )
                suggestions.append({
                    "sf_id": str(sf["_id"]),
                    "statement": sf["statement"],
                    "category": sf.get("category", ""),
                    "confidence": confidence,
                    "relation_type": "supports",
                })

            # Sort by confidence, keep top N
            suggestions = sorted(suggestions, key=lambda x: -x["confidence"])[:max_suggestions]

        return {
            "fact_id": fact_id,
            "fact_content": fact_content[:200],
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
        }

    # ------------------------------------------------------------------
    # Tool: build_knowledge_graph
    # ------------------------------------------------------------------

    async def _build_knowledge_graph(
        self, schema_name: str, clear_existing: bool = False
    ) -> dict:
        BUILD_MAP = {
            "sf_support": self._graph_builder_svc.build_sf_graph,
            "taxonomical": self._graph_builder_svc.build_taxonomy_graph,
            "knowledge_graph": self._graph_builder_svc.build_knowledge_graph,
            "citation": self._graph_builder_svc.build_citation_graph,
        }

        if schema_name not in BUILD_MAP and schema_name != "physiological_process":
            return {"error": f"Unknown schema: {schema_name}"}

        if clear_existing:
            await self._graph_builder_svc.clear_graph(schema_name)

        try:
            if schema_name in BUILD_MAP:
                stats = await BUILD_MAP[schema_name]()
            else:
                # physiological_process — no dedicated builder yet
                stats = {"message": "physiological_process schema seeded but not built"}
        except Exception as exc:
            logger.error("build_knowledge_graph %s failed: %s", schema_name, exc)
            return {"error": str(exc), "schema": schema_name}

        return {"schema": schema_name, "stats": stats}

    # ------------------------------------------------------------------
    # Tool: get_curation_queue
    # ------------------------------------------------------------------

    async def _get_curation_queue(
        self, entity_type: str = "both", limit: int = 20
    ) -> dict:
        result: dict[str, Any] = {}

        if entity_type in ("facts", "both"):
            cursor = self._db.facts.find({"status": "pending"}).limit(limit)
            facts = []
            async for f in cursor:
                facts.append({
                    "id": str(f["_id"]),
                    "content": f.get("content", "")[:200],
                    "document_id": str(f.get("document_id", "")),
                    "confidence": f.get("confidence", 0.0),
                    "created_at": str(f.get("created_at", "")),
                })
            result["facts"] = facts
            result["pending_facts"] = len(facts)

        if entity_type in ("relations", "both"):
            cursor = self._db.fact_sf_relations.find({"status": "suggested"}).limit(limit)
            relations = []
            async for r in cursor:
                relations.append({
                    "id": str(r["_id"]),
                    "fact_id": str(r.get("fact_id", "")),
                    "sf_id": str(r.get("sf_id", "")),
                    "relation_type": r.get("relation_type", ""),
                    "confidence": r.get("confidence", 0.0),
                })
            result["relations"] = relations
            result["pending_relations"] = len(relations)

        return result

    # ------------------------------------------------------------------
    # Tools: confirm_relation / reject_relation
    # ------------------------------------------------------------------

    async def _confirm_relation(
        self, relation_id: str, confirmed_by: str = "curator"
    ) -> dict:
        from bson import ObjectId
        from datetime import datetime

        result = await self._db.fact_sf_relations.update_one(
            {"_id": ObjectId(relation_id)},
            {
                "$set": {
                    "status": "confirmed",
                    "confirmed_by": confirmed_by,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        return {
            "relation_id": relation_id,
            "status": "confirmed" if result.modified_count else "not_found",
        }

    async def _reject_relation(
        self, relation_id: str, rejected_by: str = "curator"
    ) -> dict:
        from bson import ObjectId
        from datetime import datetime

        result = await self._db.fact_sf_relations.update_one(
            {"_id": ObjectId(relation_id)},
            {
                "$set": {
                    "status": "rejected",
                    "rejected_by": rejected_by,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        return {
            "relation_id": relation_id,
            "status": "rejected" if result.modified_count else "not_found",
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = CuratorAgent()
    agent.run()
