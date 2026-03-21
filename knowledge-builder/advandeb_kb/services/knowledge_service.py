"""
KnowledgeService — CRUD and search for core knowledge entities.

Handles Documents, Facts, StylizedFacts, and FactSFRelations.
All methods are async (Motor / AsyncIOMotorDatabase).
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from advandeb_kb.models.knowledge import Document, Fact, StylizedFact, FactSFRelation
from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db = database
        self.documents = database.documents
        self.facts = database.facts
        self.stylized_facts = database.stylized_facts
        self.fact_sf_relations = database.fact_sf_relations

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    async def create_document(self, document: Document) -> Document:
        data = document.model_dump(by_alias=True)
        await self.documents.insert_one(data)
        graph_rebuild_queue.mark_dirty("citation")
        return document

    async def get_document(self, document_id: str) -> Optional[Document]:
        doc = await self.documents.find_one({"_id": ObjectId(document_id)})
        return Document(**doc) if doc else None

    async def list_documents(
        self,
        skip: int = 0,
        limit: int = 50,
        general_domain: Optional[str] = None,
        processing_status: Optional[str] = None,
    ) -> List[Document]:
        query: Dict[str, Any] = {}
        if general_domain:
            query["general_domain"] = general_domain
        if processing_status:
            query["processing_status"] = processing_status
        cursor = self.documents.find(query).sort("created_at", -1).skip(skip).limit(limit)
        return [Document(**d) async for d in cursor]

    async def update_document(self, document_id: str, fields: Dict[str, Any]) -> Optional[Document]:
        fields["updated_at"] = datetime.utcnow()
        doc = await self.documents.find_one_and_update(
            {"_id": ObjectId(document_id)},
            {"$set": fields},
            return_document=True,
        )
        # If DOI or references changed, citation graph needs rebuilding
        if fields.keys() & {"doi", "references", "title", "year", "authors"}:
            graph_rebuild_queue.mark_dirty("citation")
        return Document(**doc) if doc else None

    async def delete_document(self, document_id: str) -> bool:
        result = await self.documents.delete_one({"_id": ObjectId(document_id)})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------

    async def create_fact(self, fact: Fact) -> Fact:
        data = fact.model_dump(by_alias=True)
        await self.facts.insert_one(data)
        graph_rebuild_queue.mark_dirty("sf_support")
        return fact

    async def get_fact(self, fact_id: str) -> Optional[Fact]:
        doc = await self.facts.find_one({"_id": ObjectId(fact_id)})
        return Fact(**doc) if doc else None

    async def list_facts(
        self,
        skip: int = 0,
        limit: int = 50,
        document_id: Optional[str] = None,
        general_domain: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Fact]:
        query: Dict[str, Any] = {}
        if document_id:
            query["document_id"] = ObjectId(document_id)
        if general_domain:
            query["general_domain"] = general_domain
        if status:
            query["status"] = status
        cursor = self.facts.find(query).sort("created_at", -1).skip(skip).limit(limit)
        return [Fact(**d) async for d in cursor]

    async def update_fact(self, fact_id: str, fields: Dict[str, Any]) -> Optional[Fact]:
        fields["updated_at"] = datetime.utcnow()
        doc = await self.facts.find_one_and_update(
            {"_id": ObjectId(fact_id)},
            {"$set": fields},
            return_document=True,
        )
        return Fact(**doc) if doc else None

    async def delete_fact(self, fact_id: str) -> bool:
        result = await self.facts.delete_one({"_id": ObjectId(fact_id)})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Stylized Facts
    # ------------------------------------------------------------------

    async def create_stylized_fact(self, sf: StylizedFact) -> StylizedFact:
        data = sf.model_dump(by_alias=True)
        await self.stylized_facts.insert_one(data)
        return sf

    async def get_stylized_fact(self, sf_id: str) -> Optional[StylizedFact]:
        doc = await self.stylized_facts.find_one({"_id": ObjectId(sf_id)})
        return StylizedFact(**doc) if doc else None

    async def list_stylized_facts(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[StylizedFact]:
        query: Dict[str, Any] = {}
        if category:
            query["category"] = category
        if status:
            query["status"] = status
        cursor = self.stylized_facts.find(query).sort("sf_number", 1).skip(skip).limit(limit)
        return [StylizedFact(**d) async for d in cursor]

    async def update_stylized_fact(self, sf_id: str, fields: Dict[str, Any]) -> Optional[StylizedFact]:
        fields["updated_at"] = datetime.utcnow()
        doc = await self.stylized_facts.find_one_and_update(
            {"_id": ObjectId(sf_id)},
            {"$set": fields},
            return_document=True,
        )
        return StylizedFact(**doc) if doc else None

    async def delete_stylized_fact(self, sf_id: str) -> bool:
        result = await self.stylized_facts.delete_one({"_id": ObjectId(sf_id)})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Fact ↔ SF Relations
    # ------------------------------------------------------------------

    async def create_relation(self, relation: FactSFRelation) -> FactSFRelation:
        data = relation.model_dump(by_alias=True)
        await self.fact_sf_relations.insert_one(data)
        graph_rebuild_queue.mark_dirty("sf_support")
        return relation

    async def get_relation(self, relation_id: str) -> Optional[FactSFRelation]:
        doc = await self.fact_sf_relations.find_one({"_id": ObjectId(relation_id)})
        return FactSFRelation(**doc) if doc else None

    async def list_relations(
        self,
        fact_id: Optional[str] = None,
        sf_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[FactSFRelation]:
        query: Dict[str, Any] = {}
        if fact_id:
            query["fact_id"] = ObjectId(fact_id)
        if sf_id:
            query["sf_id"] = ObjectId(sf_id)
        if relation_type:
            query["relation_type"] = relation_type
        if status:
            query["status"] = status
        cursor = self.fact_sf_relations.find(query).skip(skip).limit(limit)
        return [FactSFRelation(**d) async for d in cursor]

    async def update_relation(self, relation_id: str, fields: Dict[str, Any]) -> Optional[FactSFRelation]:
        fields["updated_at"] = datetime.utcnow()
        doc = await self.fact_sf_relations.find_one_and_update(
            {"_id": ObjectId(relation_id)},
            {"$set": fields},
            return_document=True,
        )
        graph_rebuild_queue.mark_dirty("sf_support")
        return FactSFRelation(**doc) if doc else None

    async def delete_relation(self, relation_id: str) -> bool:
        result = await self.fact_sf_relations.delete_one({"_id": ObjectId(relation_id)})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_facts(
        self,
        query: str,
        general_domain: Optional[str] = None,
        limit: int = 20,
    ) -> List[Fact]:
        """Case-insensitive regex search over fact content and entities."""
        filter_: Dict[str, Any] = {
            "$or": [
                {"content": {"$regex": query, "$options": "i"}},
                {"entities": {"$regex": query, "$options": "i"}},
                {"tags": {"$regex": query, "$options": "i"}},
            ]
        }
        if general_domain:
            filter_["general_domain"] = general_domain
        cursor = self.facts.find(filter_).limit(limit)
        return [Fact(**d) async for d in cursor]

    async def search_stylized_facts(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[StylizedFact]:
        """Case-insensitive regex search over stylized fact statements."""
        filter_: Dict[str, Any] = {
            "statement": {"$regex": query, "$options": "i"}
        }
        if category:
            filter_["category"] = category
        cursor = self.stylized_facts.find(filter_).limit(limit)
        return [StylizedFact(**d) async for d in cursor]

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
