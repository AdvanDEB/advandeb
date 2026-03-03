"""
TaxonomyService — query and traverse the taxonomy tree.

Requires the taxonomy_nodes collection to be populated by
scripts/import_taxonomy.py before use.
"""
import logging
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class TaxonomyService:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db = database
        self.col = database.taxonomy_nodes

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def get_by_taxid(self, tax_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single node by NCBI tax_id."""
        doc = await self.col.find_one({"tax_id": tax_id}, {"_id": 0})
        return doc

    async def get_by_name(self, name: str, exact: bool = True) -> List[Dict[str, Any]]:
        """Look up taxa by scientific name or synonym.

        exact=True  → case-insensitive exact match on `name` field
        exact=False → regex prefix / contains search
        """
        if exact:
            query = {"name": {"$regex": f"^{name}$", "$options": "i"}}
        else:
            query = {
                "$or": [
                    {"name": {"$regex": name, "$options": "i"}},
                    {"synonyms": {"$regex": name, "$options": "i"}},
                    {"common_names": {"$regex": name, "$options": "i"}},
                ]
            }
        cursor = self.col.find(query, {"_id": 0}).limit(20)
        return [doc async for doc in cursor]

    async def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search over name, synonyms, and common_names."""
        cursor = self.col.find(
            {"$text": {"$search": query}},
            {"_id": 0, "score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)
        return [doc async for doc in cursor]

    # ------------------------------------------------------------------
    # Tree traversal
    # ------------------------------------------------------------------

    async def get_lineage(self, tax_id: int) -> List[Dict[str, Any]]:
        """Return the full ancestor chain from root down to this node.

        Uses the pre-materialised `lineage` array — O(n) in lineage length.
        """
        node = await self.col.find_one({"tax_id": tax_id}, {"_id": 0})
        if not node:
            return []

        ancestor_ids: List[int] = node.get("lineage", [])
        if not ancestor_ids:
            return [node]

        # Fetch all ancestors in one query, then order them
        cursor = self.col.find(
            {"tax_id": {"$in": ancestor_ids}}, {"_id": 0}
        )
        by_id: Dict[int, Dict] = {}
        async for doc in cursor:
            by_id[doc["tax_id"]] = doc

        ordered = [by_id[tid] for tid in ancestor_ids if tid in by_id]
        ordered.append(node)
        return ordered

    async def get_children(
        self,
        tax_id: int,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return direct children of a node."""
        cursor = self.col.find(
            {"parent_tax_id": tax_id}, {"_id": 0}
        ).limit(limit)
        return [doc async for doc in cursor]

    async def get_subtree_ids(self, tax_id: int) -> List[int]:
        """Return tax_ids of all descendants (including the node itself).

        Uses the lineage array: any node whose lineage contains tax_id is
        a descendant.
        """
        cursor = self.col.find(
            {"$or": [
                {"tax_id": tax_id},
                {"lineage": tax_id},
            ]},
            {"tax_id": 1, "_id": 0},
        )
        return [doc["tax_id"] async for doc in cursor]

    async def get_rank_members(
        self,
        rank: str,
        ancestor_taxid: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List all nodes at a given rank, optionally restricted to a subtree."""
        query: Dict[str, Any] = {"rank": rank}
        if ancestor_taxid is not None:
            query["lineage"] = ancestor_taxid
        cursor = self.col.find(query, {"_id": 0}).limit(limit)
        return [doc async for doc in cursor]

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def count(self) -> int:
        return await self.col.count_documents({})

    async def is_populated(self) -> bool:
        """Return True if the taxonomy collection has at least one document."""
        doc = await self.col.find_one({}, {"_id": 1})
        return doc is not None
