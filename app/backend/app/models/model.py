"""
DEB model specifications.

Split out of the former ``scenario.py`` when the Scenarios section was removed
in favour of Annotation: the Model classes are used by the live Models section
and had to survive that removal.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class ModelBase(BaseModel):
    """Base model specification."""
    model_config = {"protected_namespaces": ()}

    name: str
    scenario_id: str
    description: Optional[str] = None
    model_type: str  # ibm, agent_based, system_dynamics
    structure: Dict[str, Any] = {}
    parameters: Dict[str, Any] = {}
    assumptions: List[str] = []


class ModelCreate(ModelBase):
    """Model creation model."""
    pass


class Model(ModelBase):
    """Model with database fields."""
    id: str = Field(alias="_id")
    creator_id: str
    status: str = "draft"  # draft, validated, published
    version: int = 1
    provenance: List[str] = []  # Linked fact/knowledge IDs
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
