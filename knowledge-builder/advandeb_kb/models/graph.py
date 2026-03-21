"""
Graph schema system — materialized multigraph knowledge representation.

A GraphSchema defines a named view over the knowledge base by specifying:
- which node types exist (and which underlying collection they draw from)
- which edge types connect those nodes

Multiple schemas can share the same underlying entities (taxonomy nodes,
stylized facts, documents, ...) — nodes in different schemas that reference
the same underlying entity are intentionally overlapping for explainability.

Graphs are materialized: GraphNode and GraphEdge documents are computed and
stored; they are not assembled on-the-fly at query time.

Built-in schemas (seeded at startup if absent):
  - citation              : documents citing other documents
  - sf_support            : facts supporting/opposing stylized facts
  - taxonomical           : pure organism taxonomy tree (backbone)
  - physiological_process : process relationships between SFs / entities
  - knowledge_graph       : taxonomy backbone + documents connected by agent-
                            determined 'studies' edges; node type = taxon rank
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from advandeb_kb.models.common import PyObjectId


_BASE_CONFIG = ConfigDict(
    populate_by_name=True,
    arbitrary_types_allowed=True,
)


# ---------------------------------------------------------------------------
# Schema definition models
# ---------------------------------------------------------------------------

class NodeTypeDefinition(BaseModel):
    """Definition of one node type within a graph schema."""

    # Unique name within the schema, e.g. "document", "stylized_fact", "species"
    name: str

    # MongoDB collection that provides the underlying data for this node type
    source_collection: str

    # Field in the source document to use as the human-readable node label
    label_field: str

    # Source document fields to copy into the materialized GraphNode.properties
    properties: List[str] = []

    description: str = ""


class EdgeTypeDefinition(BaseModel):
    """Definition of one directed edge type within a graph schema."""

    # Unique name within the schema, e.g. "cites", "supports", "is_child_of"
    name: str

    source_node_type: str
    target_node_type: str

    # Human-readable label shown on the edge in visualisations
    label: str

    # Extra fields to store on the materialized GraphEdge.properties
    properties: List[str] = []

    description: str = ""


class GraphSchema(BaseModel):
    """A named graph schema — defines the structure of one graph view."""

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")

    # Unique machine-readable name, e.g. "taxonomical", "sf_support"
    name: str

    description: str = ""

    node_types: List[NodeTypeDefinition] = []
    edge_types: List[EdgeTypeDefinition] = []

    # Whether this schema was created by the system (True) or by a user (False)
    is_builtin: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Materialized graph documents
# ---------------------------------------------------------------------------

class GraphNode(BaseModel):
    """A materialized node in a specific graph schema instance."""

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")

    schema_id: PyObjectId
    node_type: str

    # Reference back to the underlying entity — collection + entity _id as string
    entity_collection: str
    entity_id: str

    # Denormalised label and selected properties for fast graph queries
    label: str
    properties: Dict[str, Any] = {}

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GraphEdge(BaseModel):
    """A materialized directed edge between two GraphNodes."""

    model_config = _BASE_CONFIG

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")

    schema_id: PyObjectId
    edge_type: str

    source_node_id: PyObjectId
    target_node_id: PyObjectId

    # Optional weight / confidence for edges derived from probabilistic sources
    weight: float = 1.0

    properties: Dict[str, Any] = {}

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Built-in schema definitions (used by the graph schema seeder)
# ---------------------------------------------------------------------------

BUILTIN_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "citation",
        "description": "Citation relationships between scientific documents.",
        "is_builtin": True,
        "node_types": [
            {
                "name": "document",
                "source_collection": "documents",
                "label_field": "title",
                "properties": ["doi", "year", "authors", "journal"],
                "description": "A scientific paper or other ingested source.",
            }
        ],
        "edge_types": [
            {
                "name": "cites",
                "source_node_type": "document",
                "target_node_type": "document",
                "label": "cites",
                "description": "Document A cites document B.",
            }
        ],
    },
    {
        "name": "sf_support",
        "description": (
            "Evidence network: facts extracted from documents that support or "
            "oppose stylized facts."
        ),
        "is_builtin": True,
        "node_types": [
            {
                "name": "document",
                "source_collection": "documents",
                "label_field": "title",
                "properties": ["doi", "year", "general_domain"],
                "description": "Source document.",
            },
            {
                "name": "fact",
                "source_collection": "facts",
                "label_field": "content",
                "properties": ["general_domain", "confidence", "status"],
                "description": "Extracted factual observation.",
            },
            {
                "name": "stylized_fact",
                "source_collection": "stylized_facts",
                "label_field": "statement",
                "properties": ["category", "status"],
                "description": "General biological principle or pattern.",
            },
        ],
        "edge_types": [
            {
                "name": "extracted_from",
                "source_node_type": "fact",
                "target_node_type": "document",
                "label": "extracted from",
                "description": "Fact was extracted from this document.",
            },
            {
                "name": "supports",
                "source_node_type": "fact",
                "target_node_type": "stylized_fact",
                "label": "supports",
                "description": "Fact provides supporting evidence for the stylized fact.",
            },
            {
                "name": "opposes",
                "source_node_type": "fact",
                "target_node_type": "stylized_fact",
                "label": "opposes",
                "description": "Fact contradicts or provides counter-evidence for the stylized fact.",
            },
        ],
    },
    {
        "name": "taxonomical",
        "description": "Taxonomic parent-child hierarchy of organisms (NCBI + GBIF).",
        "is_builtin": True,
        "node_types": [
            {
                "name": "taxon",
                "source_collection": "taxonomy_nodes",
                "label_field": "name",
                "properties": ["rank", "tax_id", "gbif_usage_key", "common_names"],
                "description": "A taxonomic node at any rank.",
            }
        ],
        "edge_types": [
            {
                "name": "is_child_of",
                "source_node_type": "taxon",
                "target_node_type": "taxon",
                "label": "is child of",
                "description": "Child taxon → parent taxon (e.g. species → genus).",
            }
        ],
    },
    {
        "name": "knowledge_graph",
        "description": (
            "Full integrated knowledge graph: all domain knowledge in one schema. "
            "Taxonomy backbone (taxon nodes typed by rank) overlaid with stylized "
            "facts, extracted facts, and documents. All evidence edges (extracted_from, "
            "supports, opposes), document links (studies, cites), process relations "
            "(regulates, depends_on, exhibited_by) are materialized. Every node carries "
            "a cluster_id for frontend coloring."
        ),
        "is_builtin": True,
        "node_types": [
            {
                "name": "taxon",  # node_type is overridden to rank at build time
                "source_collection": "taxonomy_nodes",
                "label_field": "name",
                "properties": ["rank", "tax_id", "gbif_usage_key", "common_names", "cluster_id"],
                "description": (
                    "Taxonomic node — materialized node_type is the rank "
                    "(species, genus, family, …) for visual differentiation. "
                    "cluster_id = 'taxon:<rank>'."
                ),
            },
            {
                "name": "stylized_fact",
                "source_collection": "stylized_facts",
                "label_field": "statement",
                "properties": ["category", "status", "sf_number", "cluster_id"],
                "description": (
                    "General biological principle. cluster_id = 'sf:<category>'."
                ),
            },
            {
                "name": "fact",
                "source_collection": "facts",
                "label_field": "content",
                "properties": ["confidence", "status", "entities", "cluster_id"],
                "description": (
                    "Extracted factual observation. cluster_id = 'fact' (all facts same cluster)."
                ),
            },
            {
                "name": "document",
                "source_collection": "documents",
                "label_field": "title",
                "properties": ["doi", "year", "authors", "journal", "general_domain", "cluster_id"],
                "description": (
                    "Scientific document. cluster_id = 'doc:<general_domain>'."
                ),
            },
        ],
        "edge_types": [
            {
                "name": "is_child_of",
                "source_node_type": "taxon",
                "target_node_type": "taxon",
                "label": "is child of",
                "description": "Child taxon → parent taxon (phylogenetic tree backbone).",
            },
            {
                "name": "studies",
                "source_node_type": "document",
                "target_node_type": "taxon",
                "label": "studies",
                "description": (
                    "Document discusses or studies this organism — determined by "
                    "the knowledge-graph-building agent via document_taxon_relations."
                ),
            },
            {
                "name": "extracted_from",
                "source_node_type": "fact",
                "target_node_type": "document",
                "label": "extracted from",
                "description": "Fact was extracted from this document.",
            },
            {
                "name": "supports",
                "source_node_type": "fact",
                "target_node_type": "stylized_fact",
                "label": "supports",
                "description": "Fact provides supporting evidence for the stylized fact.",
            },
            {
                "name": "opposes",
                "source_node_type": "fact",
                "target_node_type": "stylized_fact",
                "label": "opposes",
                "description": "Fact contradicts or provides counter-evidence for the stylized fact.",
            },
            {
                "name": "cites",
                "source_node_type": "document",
                "target_node_type": "document",
                "label": "cites",
                "description": "Document A cites document B (via doc.references DOI list).",
            },
            {
                "name": "regulates",
                "source_node_type": "stylized_fact",
                "target_node_type": "stylized_fact",
                "label": "regulates",
                "description": "One process/principle regulates another (via sf_sf_relations if present).",
            },
            {
                "name": "depends_on",
                "source_node_type": "stylized_fact",
                "target_node_type": "stylized_fact",
                "label": "depends on",
                "description": "One process/principle depends on another (via sf_sf_relations if present).",
            },
            {
                "name": "exhibited_by",
                "source_node_type": "stylized_fact",
                "target_node_type": "taxon",
                "label": "exhibited by",
                "description": (
                    "Stylized fact is exhibited by this taxon (via sf_taxon_relations if present)."
                ),
            },
        ],
    },
    {
        "name": "physiological_process",
        "description": (
            "Relationships between biological processes and the stylized facts "
            "and organisms that describe them."
        ),
        "is_builtin": True,
        "node_types": [
            {
                "name": "stylized_fact",
                "source_collection": "stylized_facts",
                "label_field": "statement",
                "properties": ["category", "status"],
                "description": "A general biological principle acting as a process node.",
            },
            {
                "name": "taxon",
                "source_collection": "taxonomy_nodes",
                "label_field": "name",
                "properties": ["rank", "tax_id"],
                "description": "An organism involved in the process.",
            },
        ],
        "edge_types": [
            {
                "name": "regulates",
                "source_node_type": "stylized_fact",
                "target_node_type": "stylized_fact",
                "label": "regulates",
                "description": "One process/principle regulates another.",
            },
            {
                "name": "depends_on",
                "source_node_type": "stylized_fact",
                "target_node_type": "stylized_fact",
                "label": "depends on",
                "description": "One process/principle depends on another.",
            },
            {
                "name": "exhibited_by",
                "source_node_type": "stylized_fact",
                "target_node_type": "taxon",
                "label": "exhibited by",
                "description": "A process/principle is exhibited by this taxon.",
            },
        ],
    },
]
