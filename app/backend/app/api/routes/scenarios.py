"""
Scenarios API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from app.core.auth import get_current_user
from app.models.scenario import Scenario, ScenarioCreate
from app.services.scenario_service import ScenarioService


router = APIRouter()


@router.post("/", response_model=Scenario)
async def create_scenario(
    scenario: ScenarioCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new modeling scenario."""
    scenario_service = ScenarioService()
    new_scenario = await scenario_service.create_scenario(scenario, current_user["id"])
    return new_scenario


@router.get("/", response_model=List[Scenario])
async def list_scenarios(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """List scenarios."""
    scenario_service = ScenarioService()
    scenarios = await scenario_service.list_scenarios(skip=skip, limit=limit)
    return scenarios


@router.get("/{scenario_id}", response_model=Scenario)
async def get_scenario(
    scenario_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get scenario by ID."""
    scenario_service = ScenarioService()
    scenario = await scenario_service.get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found"
        )
    return scenario


@router.put("/{scenario_id}", response_model=Scenario)
async def update_scenario(
    scenario_id: str,
    scenario_update: ScenarioCreate,
    current_user: dict = Depends(get_current_user)
):
    """Update scenario."""
    scenario_service = ScenarioService()
    scenario = await scenario_service.update_scenario(
        scenario_id,
        scenario_update,
        current_user["id"]
    )
    return scenario


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete scenario."""
    scenario_service = ScenarioService()
    await scenario_service.delete_scenario(scenario_id, current_user["id"])
    return {"message": "Scenario deleted"}
