from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


CitationSourceType = Literal[
    "chunk",
    "fact",
    "stylized_fact",
    "external_document",
    "platform_doc",
]

EvidenceMode = Literal[
    "local",
    "local_plus_external",
    "external_fallback_labeled",
]


def strip_collection_prefix(raw_id: str) -> str:
    """Return the document key portion of an Arango-style ``collection/key`` id."""
    value = str(raw_id or "").strip()
    if not value:
        return ""
    if "/" in value:
        return value.split("/", 1)[1]
    return value


def make_citation_id(source_type: CitationSourceType, raw_id: str) -> str:
    key = strip_collection_prefix(raw_id)
    if not key:
        return ""
    if source_type == "chunk":
        return f"chunk:{key}"
    if source_type == "fact":
        return f"fact:{key}"
    if source_type == "stylized_fact":
        return f"sf:{key}"
    if source_type == "platform_doc":
        return f"platformdoc:{key}"
    return f"external:{key}"


def parse_citation_id(citation_id: str) -> tuple[CitationSourceType, str]:
    """Parse canonical and legacy citation ids into ``(source_type, key)``."""
    value = str(citation_id or "").strip()
    if not value:
        return "chunk", ""

    if value.startswith("chunk:"):
        return "chunk", strip_collection_prefix(value[len("chunk:"):])
    if value.startswith("fact:"):
        return "fact", strip_collection_prefix(value[len("fact:"):])
    if value.startswith("sf:"):
        return "stylized_fact", strip_collection_prefix(value[len("sf:"):])
    if value.startswith("external:"):
        return "external_document", value[len("external:"):]
    if value.startswith("platformdoc:"):
        return "platform_doc", value[len("platformdoc:"):]
    if value.startswith("gfact_"):
        return "fact", strip_collection_prefix(value[len("gfact_"):])
    if value.startswith("gsf_"):
        return "stylized_fact", strip_collection_prefix(value[len("gsf_"):])
    return "chunk", strip_collection_prefix(value)


class CitationRef(BaseModel):
    citation_id: str
    marker: str
    source_type: CitationSourceType
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    fact_id: Optional[str] = None
    stylized_fact_id: Optional[str] = None
    evidence_text: str = ""
    title: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    year: Optional[int | str] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None


class ChatAnswerPayload(BaseModel):
    answer: str
    citations: list[CitationRef] = Field(default_factory=list)
    evidence_mode: EvidenceMode = "local"
    thoughts: list[str] = Field(default_factory=list)
    tool_calls_made: list[dict] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    session_id: str
    message_id: str
