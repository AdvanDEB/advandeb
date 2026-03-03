from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from typing import List, Dict, Any
from advandeb_kb.models.knowledge import Fact, StylizedFact
from advandeb_kb.services.knowledge_service import KnowledgeService
from advandeb_kb.database.mongodb import get_database

router = APIRouter()

async def get_knowledge_service():
    db = await get_database()
    return KnowledgeService(db)

@router.get("/facts", response_model=List[Fact])
async def get_facts(
    skip: int = 0, 
    limit: int = 10,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Get all facts with pagination"""
    return await service.get_facts(skip=skip, limit=limit)

@router.post("/facts", response_model=Fact)
async def create_fact(
    fact: Fact,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Create a new fact"""
    return await service.create_fact(fact)

@router.get("/facts/{fact_id}", response_model=Fact)
async def get_fact(
    fact_id: str,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Get a specific fact by ID"""
    fact = await service.get_fact(fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    return fact

@router.get("/stylized-facts", response_model=List[StylizedFact])
async def get_stylized_facts(
    skip: int = 0,
    limit: int = 10,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Get all stylized facts with pagination"""
    return await service.get_stylized_facts(skip=skip, limit=limit)

@router.post("/stylized-facts", response_model=StylizedFact)
async def create_stylized_fact(
    stylized_fact: StylizedFact,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Create a new stylized fact"""
    return await service.create_stylized_fact(stylized_fact)


@router.post("/search")
async def search_knowledge(
    query: Dict[str, Any],
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Search knowledge base"""
    return await service.search_knowledge(query)