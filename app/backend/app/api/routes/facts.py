"""
Facts API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from app.core.auth import get_current_user
from app.core.dependencies import require_curator
from app.models.fact import Fact, FactCreate, StylizedFact, StylizedFactCreate
from app.services.fact_service import FactService


router = APIRouter()


@router.post("/", response_model=Fact)
async def create_fact(
    fact: FactCreate,
    current_user: dict = Depends(require_curator)
):
    """Create a new fact."""
    fact_service = FactService()
    new_fact = await fact_service.create_fact(fact, current_user["id"])
    return new_fact


@router.get("/", response_model=List[Fact])
async def list_facts(
    skip: int = 0,
    limit: int = 100,
    status_filter: str = None,
    current_user: dict = Depends(get_current_user)
):
    """List facts."""
    fact_service = FactService()
    facts = await fact_service.list_facts(
        skip=skip,
        limit=limit,
        status_filter=status_filter
    )
    return facts


@router.get("/{fact_id}", response_model=Fact)
async def get_fact(
    fact_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get fact by ID."""
    fact_service = FactService()
    fact = await fact_service.get_fact(fact_id)
    if not fact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fact not found"
        )
    return fact


@router.post("/stylized", response_model=StylizedFact)
async def create_stylized_fact(
    stylized_fact: StylizedFactCreate,
    current_user: dict = Depends(require_curator)
):
    """Create a stylized fact."""
    fact_service = FactService()
    new_sf = await fact_service.create_stylized_fact(stylized_fact, current_user["id"])
    return new_sf


@router.get("/stylized/", response_model=List[StylizedFact])
async def list_stylized_facts(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """List stylized facts."""
    fact_service = FactService()
    stylized_facts = await fact_service.list_stylized_facts(skip=skip, limit=limit)
    return stylized_facts
