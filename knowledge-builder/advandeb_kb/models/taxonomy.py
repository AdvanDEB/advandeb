"""
Taxonomy node model — backed by NCBI Taxonomy (primary) and GBIF (supplement).

Each node represents one taxon at any rank (domain, kingdom, phylum, class,
order, family, genus, species, ...). The parent-child tree is encoded via
parent_tax_id and a pre-materialized lineage array for fast ancestor queries.
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from advandeb_kb.models.common import PyObjectId


class TaxonomyNode(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: PyObjectId = Field(default_factory=lambda: __import__("bson").ObjectId(), alias="_id")

    # NCBI Taxonomy ID — primary key for lookups and cross-references
    tax_id: int

    # Scientific name (canonical name from NCBI names.dmp, name_class="scientific name")
    name: str

    # Taxonomic rank: "domain", "kingdom", "phylum", "class", "order",
    # "family", "genus", "species", "subspecies", "no rank", etc.
    rank: str

    # NCBI tax_id of the direct parent (None only for the root node, tax_id=1)
    parent_tax_id: Optional[int] = None

    # Pre-materialized list of ancestor tax_ids from root down to this node's
    # parent. Stored at import time for O(1) ancestor/descendant queries.
    # Example: Homo sapiens → [1, 131567, 2759, 33154, 9604, 9605]
    lineage: List[int] = []

    # All name variants from NCBI names.dmp (synonym, equivalent name, etc.)
    synonyms: List[str] = []

    # Common/vernacular names
    common_names: List[str] = []

    # GBIF backbone usageKey — stored as a cross-reference for species not in
    # NCBI (described but unsequenced). None if the node is NCBI-only.
    gbif_usage_key: Optional[int] = None

    # Whether this node was imported from NCBI (True) or added from GBIF only
    ncbi_sourced: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
