"""
Ingestion pipeline models: batch jobs for bulk PDF processing.
"""
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from advandeb_kb.models.common import PyObjectId


_BASE_CONFIG = ConfigDict(
    populate_by_name=True,
    arbitrary_types_allowed=True,
)


class IngestionBatch(BaseModel):
    """A batch of documents to ingest from a local folder tree."""

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")

    # Human-readable name for the batch (optional)
    name: Optional[str] = None

    # Root directory that all relative folder paths are resolved against
    source_root: str

    # Relative folder paths under source_root to scan for PDFs
    folders: List[str] = []

    # Total number of PDF files discovered (filled in after scanning)
    num_files: int = 0

    # Optional general domain tag applied to all documents in this batch
    general_domain: Optional[str] = None

    status: Literal["pending", "running", "completed", "failed", "mixed"] = "pending"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class IngestionJob(BaseModel):
    """A single file or URL ingestion job within a batch."""

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")

    batch_id: PyObjectId

    source_type: Literal["pdf_local", "pdf_upload", "web", "text"] = "pdf_local"

    # Relative path (pdf_local), filename (pdf_upload), or URL (web/text)
    source_path_or_url: str

    # Set once the Document record has been created for this job
    document_id: Optional[PyObjectId] = None

    status: Literal["pending", "queued", "running", "completed", "failed", "cancelled"] = "pending"
    stage: Literal["pending", "text_extraction", "fact_extraction", "sf_matching", "completed", "failed"] = "pending"

    progress: int = Field(default=0, ge=0, le=100)
    error_message: Optional[str] = None

    metadata: Dict[str, Any] = {}

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
