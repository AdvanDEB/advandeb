from typing import List, Dict, Any, Optional
from advandeb_kb.models.knowledge import Fact, StylizedFact, KnowledgeGraph
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class KnowledgeService:
    def __init__(self, database):
        self.db = database
        self.facts_collection = database.facts
        self.stylized_facts_collection = database.stylized_facts
        self.graphs_collection = database.knowledge_graphs

    async def create_fact(self, fact: Fact) -> Fact:
        """Create a new fact"""
        fact_dict = fact.dict(by_alias=True, exclude_unset=True)
        if "_id" not in fact_dict:
            fact_dict["_id"] = ObjectId()
        
        result = await self.facts_collection.insert_one(fact_dict)
        fact_dict["_id"] = result.inserted_id
        return Fact(**fact_dict)

    async def get_fact(self, fact_id: str) -> Optional[Fact]:
        """Get a fact by ID"""
        fact_data = await self.facts_collection.find_one({"_id": ObjectId(fact_id)})
        if fact_data:
            return Fact(**fact_data)
        return None

    async def get_facts(self, skip: int = 0, limit: int = 10) -> List[Fact]:
        """Get facts with pagination"""
        cursor = self.facts_collection.find().skip(skip).limit(limit)
        facts = []
        async for fact_data in cursor:
            facts.append(Fact(**fact_data))
        return facts

    async def create_stylized_fact(self, stylized_fact: StylizedFact) -> StylizedFact:
        """Create a new stylized fact"""
        stylized_fact_dict = stylized_fact.dict(by_alias=True, exclude_unset=True)
        if "_id" not in stylized_fact_dict:
            stylized_fact_dict["_id"] = ObjectId()
        
        result = await self.stylized_facts_collection.insert_one(stylized_fact_dict)
        stylized_fact_dict["_id"] = result.inserted_id
        return StylizedFact(**stylized_fact_dict)

    async def get_stylized_facts(self, skip: int = 0, limit: int = 10) -> List[StylizedFact]:
        """Get stylized facts with pagination"""
        cursor = self.stylized_facts_collection.find().skip(skip).limit(limit)
        stylized_facts = []
        async for fact_data in cursor:
            stylized_facts.append(StylizedFact(**fact_data))
        return stylized_facts

    async def create_knowledge_graph(self, graph: KnowledgeGraph) -> KnowledgeGraph:
        """Create a new knowledge graph"""
        graph_dict = graph.dict(by_alias=True, exclude_unset=True)
        if "_id" not in graph_dict:
            graph_dict["_id"] = ObjectId()
        
        result = await self.graphs_collection.insert_one(graph_dict)
        graph_dict["_id"] = result.inserted_id
        return KnowledgeGraph(**graph_dict)

    async def get_knowledge_graph(self, graph_id: str) -> Optional[KnowledgeGraph]:
        """Get a knowledge graph by ID"""
        graph_data = await self.graphs_collection.find_one({"_id": ObjectId(graph_id)})
        if graph_data:
            return KnowledgeGraph(**graph_data)
        return None

    async def get_knowledge_graphs(self, skip: int = 0, limit: int = 10) -> List[KnowledgeGraph]:
        """Get knowledge graphs with pagination"""
        cursor = self.graphs_collection.find().skip(skip).limit(limit)
        graphs = []
        async for graph_data in cursor:
            graphs.append(KnowledgeGraph(**graph_data))
        return graphs

    async def search_knowledge(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """Search knowledge base"""
        results = {
            "facts": [],
            "stylized_facts": [],
            "graphs": []
        }
        
        # Search in facts
        if "text" in query:
            text_query = {"$text": {"$search": query["text"]}}
            cursor = self.facts_collection.find(text_query).limit(10)
            async for fact_data in cursor:
                results["facts"].append(Fact(**fact_data))
        
        # Search by tags
        if "tags" in query:
            tag_query = {"tags": {"$in": query["tags"]}}
            cursor = self.facts_collection.find(tag_query).limit(10)
            async for fact_data in cursor:
                results["facts"].append(Fact(**fact_data))
        
        return results

    async def update_fact(self, fact_id: str, update_data: Dict[str, Any]) -> Optional[Fact]:
        """Update a fact"""
        update_data["updated_at"] = datetime.utcnow()
        result = await self.facts_collection.find_one_and_update(
            {"_id": ObjectId(fact_id)},
            {"$set": update_data},
            return_document=True
        )
        if result:
            return Fact(**result)
        return None

    async def delete_fact(self, fact_id: str) -> bool:
        """Delete a fact"""
        result = await self.facts_collection.delete_one({"_id": ObjectId(fact_id)})
        return result.deleted_count > 0