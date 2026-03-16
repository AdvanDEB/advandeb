"""
Core knowledge entities: Document, Fact, StylizedFact, FactSFRelation.
"""
from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from advandeb_kb.models.common import PyObjectId


_BASE_CONFIG = ConfigDict(
    populate_by_name=True,
    arbitrary_types_allowed=True,
)


class Document(BaseModel):
    """An ingested source: PDF paper, web page, or manually entered text."""

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")
    title: Optional[str] = None
    doi: Optional[str] = None
    authors: List[str] = []
    year: Optional[int] = None
    journal: Optional[str] = None
    abstract: Optional[str] = None
    content: Optional[str] = None  # full extracted text

    # Where the document came from
    source_type: Literal["pdf_local", "pdf_upload", "web", "text", "manual"] = "manual"
    source_path: Optional[str] = None  # relative path (batch), filename (upload), or URL (web)

    # Scope tag for development / domain-limited testing (e.g. "reproduction")
    general_domain: Optional[str] = None

    processing_status: Literal["pending", "processing", "completed", "failed"] = "pending"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Fact(BaseModel):
    """A specific factual observation extracted from a document.

    A fact is always traceable to its source document and optionally to a
    page number. It may support or oppose one or more stylized facts via
    FactSFRelation.
    """

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")
    content: str
    document_id: PyObjectId           # primary source
    additional_sources: List[PyObjectId] = []   # cross-linked documents reporting the same fact
    content_fingerprint: Optional[str] = None  # normalized for deduplication
    page_number: Optional[int] = None

    # Named entities mentioned in the fact (organism names, process names, etc.)
    entities: List[str] = []
    tags: List[str] = []

    # Scope tag inherited from parent document or set explicitly
    general_domain: Optional[str] = None

    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    status: Literal["pending", "reviewed", "published", "rejected"] = "pending"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StylizedFact(BaseModel):
    """A general biological principle or pattern.

    Stylized facts are high-level claims supported (or opposed) by multiple
    raw facts. They are organized into categories (corresponding to the CSV
    source files) which are independent of the general_domain tagging on
    documents and facts.
    """

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")
    statement: str

    # Category from source CSV filename, e.g. "reproductive_strategy",
    # "metabolism_and_environment", "universal_laws_of_biological_organization"
    category: str

    # Sequential number from the CSV (e.g. 301, 302 ...) — None for user-created SFs
    sf_number: Optional[int] = None

    status: Literal["pending", "published", "rejected"] = "pending"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentTaxonRelation(BaseModel):
    """Agent-determined link between a Document and a TaxonomyNode.

    Created by the knowledge-graph-building agent when it determines that a
    document studies or discusses a particular organism/taxon.  Curators can
    confirm or reject agent suggestions.

    The graph builder reads confirmed + suggested relations to materialise
    `studies` edges in the `knowledge_graph` schema.
    """

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")

    # References
    document_id: PyObjectId        # → documents collection
    tax_id: int                    # NCBI taxonomy ID (for fast lookup without join)

    # Semantics of the link
    relation_type: Literal["studies"] = "studies"

    # Confidence score assigned by the agent (0.0–1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # Agent's reasoning or the text span that triggered this relation
    evidence: str = ""

    # Lifecycle: suggested by agent, then confirmed or rejected by curator
    status: Literal["suggested", "confirmed", "rejected"] = "suggested"

    # "agent" or a user_id string
    created_by: str = "agent"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FactSFRelation(BaseModel):
    """Evidence relationship between a Fact and a StylizedFact.

    A fact may support or oppose a stylized fact. Relations are first
    created as 'suggested' (by the ingestion agent), and then confirmed
    or rejected by a curator.
    """

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")
    fact_id: PyObjectId
    sf_id: PyObjectId

    relation_type: Literal["supports", "opposes"]

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # 'suggested' = produced by agent; 'confirmed'/'rejected' = curator decision
    status: Literal["suggested", "confirmed", "rejected"] = "suggested"

    # user_id string or the literal "agent" for automated suggestions
    created_by: str = "agent"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
