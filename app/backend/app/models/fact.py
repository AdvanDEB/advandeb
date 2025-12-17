"""
Fact data models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class FactBase(BaseModel):
    """Base fact model."""
    statement: str
    source_document_id: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Optional[float] = None
    tags: List[str] = []
    metadata: Optional[Dict[str, Any]] = {}


class FactCreate(FactBase):
    """Fact creation model."""
    pass


class Fact(FactBase):
    """Fact model with database fields."""
    id: str = Field(alias="_id")
    creator_id: str
    status: str = "pending_review"  # suggestion, pending_review, published, rejected
    review_status: Optional[str] = None
    reviewer_id: Optional[str] = None
    review_comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        populate_by_name = True


class StylizedFactBase(BaseModel):
    """Base stylized fact model."""
    summary: str
    supporting_fact_ids: List[str] = []
    description: Optional[str] = None
    tags: List[str] = []


class StylizedFactCreate(StylizedFactBase):
    """Stylized fact creation model."""
    pass


class StylizedFact(StylizedFactBase):
    """Stylized fact model with database fields."""
    id: str = Field(alias="_id")
    creator_id: str
    status: str = "pending_review"
    created_at: datetime
    updated_at: datetime
    
    class Config:
        populate_by_name = True
