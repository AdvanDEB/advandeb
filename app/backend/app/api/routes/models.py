"""
Models API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from app.core.auth import get_current_user
from app.models.scenario import Model, ModelCreate
from app.services.model_service import ModelService


router = APIRouter()


@router.post("/", response_model=Model)
async def create_model(
    model: ModelCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new model."""
    model_service = ModelService()
    new_model = await model_service.create_model(model, current_user["id"])
    return new_model


@router.get("/", response_model=List[Model])
async def list_models(
    skip: int = 0,
    limit: int = 100,
    scenario_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    """List models."""
    model_service = ModelService()
    models = await model_service.list_models(
        skip=skip,
        limit=limit,
        scenario_id=scenario_id
    )
    return models


@router.get("/{model_id}", response_model=Model)
async def get_model(
    model_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get model by ID."""
    model_service = ModelService()
    model = await model_service.get_model(model_id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found"
        )
    return model


@router.put("/{model_id}", response_model=Model)
async def update_model(
    model_id: str,
    model_update: ModelCreate,
    current_user: dict = Depends(get_current_user)
):
    """Update model."""
    model_service = ModelService()
    model = await model_service.update_model(
        model_id,
        model_update,
        current_user["id"]
    )
    return model


@router.delete("/{model_id}")
async def delete_model(
    model_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete model."""
    model_service = ModelService()
    await model_service.delete_model(model_id, current_user["id"])
    return {"message": "Model deleted"}
