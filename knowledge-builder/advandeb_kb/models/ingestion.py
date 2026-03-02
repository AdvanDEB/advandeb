from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any, Annotated
from datetime import datetime
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")
        return field_schema


class IngestionBatch(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str},
    )

    id: Annotated[PyObjectId, Field(default_factory=PyObjectId, alias="_id")]
    name: Optional[str] = None
    source_root: str
    folders: List[str] = []
    num_files: int = 0
    status: str = "pending"  # pending, running, completed, failed, mixed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class IngestionJob(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str},
    )

    id: Annotated[PyObjectId, Field(default_factory=PyObjectId, alias="_id")]
    batch_id: PyObjectId
    source_type: str = "pdf_local"  # pdf_local, pdf_upload, web, text
    source_path_or_url: str
    document_id: Optional[PyObjectId] = None
    status: str = "pending"  # pending, queued, running, completed, failed, cancelled
    stage: str = "pending"  # pending, text_extraction, fact_extraction, graph_update
    progress: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
