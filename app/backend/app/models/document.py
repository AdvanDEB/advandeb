"""
Document data models.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class DocumentBase(BaseModel):
    """Base document model."""
    title: str
    source_type: str  # pdf, url, text
    url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}


class DocumentCreate(DocumentBase):
    """Document creation model."""
    content: Optional[str] = None


class Document(DocumentBase):
    """Document model with database fields."""
    id: str = Field(alias="_id")
    uploader_id: str
    status: str = "pending"  # pending, processing, completed, failed
    content: Optional[str] = None
    extracted_facts_count: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        populate_by_name = True
