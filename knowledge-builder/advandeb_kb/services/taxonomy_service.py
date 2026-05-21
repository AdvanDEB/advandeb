"""
TaxonomyService — query and traverse the taxonomy tree via ArangoDB.

The `taxa` collection holds NCBI taxonomy nodes.  Each document has:
  - _key        : str(tax_id)  e.g. "9606"
  - tax_id      : int          e.g. 9606
  - name        : str          scientific name
  - rank        : str          e.g. "species", "genus", "family"
  - parent_tax_id : int
  - lineage     : List[int]    ancestor tax_ids from root to parent (pre-materialised)
  - synonyms    : List[str]
  - common_names: List[str]
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from advandeb_kb.database.arango_client import ArangoDatabase

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="taxonomy-svc")


class TaxonomyService:
    def __init__(self, database: ArangoDatabase):
        self.db = database

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def get_by_taxid(self, tax_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single node by NCBI tax_id."""
        def _get():
            col = self.db.db.collection("taxa")
            doc = col.get(str(tax_id))
            if doc:
                doc.pop("_rev", None)
            return doc
        return await self._run(_get)

    async def get_by_name(self, name: str, exact: bool = True) -> List[Dict[str, Any]]:
        """Look up taxa by scientific name or synonym.

        exact=True  → case-insensitive exact match on `name` field
        exact=False → LIKE contains on name, synonyms, and common_names
        """
        if exact:
            aql = """
            FOR doc IN taxa
                FILTER LOWER(doc.name) == LOWER(@name)
                LIMIT 20
                RETURN UNSET(doc, '_rev')
            """
            bind: Dict[str, Any] = {"name": name}
        else:
            aql = """
            FOR doc IN taxa
                FILTER LIKE(doc.name, @pat, true)
                    OR (doc.synonyms != null AND @name IN doc.synonyms)
                    OR (doc.common_names != null AND @name IN doc.common_names)
                LIMIT 20
                RETURN UNSET(doc, '_rev')
            """
            bind = {"pat": f"%{name}%", "name": name}
        return await self._run(self.db.aql, aql, bind)

    async def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search over name, synonyms, and common_names via AQL LIKE."""
        aql = """
        FOR doc IN taxa
            FILTER LIKE(doc.name, @pat, true)
            LIMIT @limit
            RETURN UNSET(doc, '_rev')
        """
        rows = await self._run(self.db.aql, aql, {"pat": f"%{query}%", "limit": limit})
        return rows

    # ------------------------------------------------------------------
    # Tree traversal
    # ------------------------------------------------------------------

    async def get_lineage(self, tax_id: int) -> List[Dict[str, Any]]:
        """Return the full ancestor chain from root down to this node.

        Uses the pre-materialised `lineage` array — O(n) in lineage length.
        """
        node = await self.get_by_taxid(tax_id)
        if not node:
            return []

        ancestor_ids: List[int] = node.get("lineage", [])
        if not ancestor_ids:
            return [node]

        def _fetch_ancestors():
            str_keys = [str(tid) for tid in ancestor_ids]
            aql = """
            FOR doc IN taxa
                FILTER doc._key IN @keys
                RETURN UNSET(doc, '_rev')
            """
            rows = self.db.aql(aql, {"keys": str_keys})
            by_id = {r["tax_id"]: r for r in rows}
            ordered = [by_id[tid] for tid in ancestor_ids if tid in by_id]
            return ordered

        ordered = await self._run(_fetch_ancestors)
        ordered.append(node)
        return ordered

    async def get_children(
        self,
        tax_id: int,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return direct children of a node."""
        aql = """
        FOR doc IN taxa
            FILTER doc.parent_tax_id == @tax_id
            LIMIT @limit
            RETURN UNSET(doc, '_rev')
        """
        return await self._run(self.db.aql, aql, {"tax_id": tax_id, "limit": limit})

    async def get_subtree_ids(self, tax_id: int) -> List[int]:
        """Return tax_ids of all descendants (including the node itself).

        Uses the lineage array: any node whose lineage contains tax_id is
        a descendant.
        """
        aql = """
        FOR doc IN taxa
            FILTER doc.tax_id == @tax_id OR @tax_id IN doc.lineage
            RETURN doc.tax_id
        """
        return await self._run(self.db.aql, aql, {"tax_id": tax_id})

    async def get_rank_members(
        self,
        rank: str,
        ancestor_taxid: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List all nodes at a given rank, optionally restricted to a subtree."""
        bind: Dict[str, Any] = {"rank": rank, "limit": limit}
        ancestor_filter = ""
        if ancestor_taxid is not None:
            ancestor_filter = "FILTER @ancestor_taxid IN doc.lineage OR doc.tax_id == @ancestor_taxid"
            bind["ancestor_taxid"] = ancestor_taxid
        aql = f"""
        FOR doc IN taxa
            FILTER doc.rank == @rank
            {ancestor_filter}
            LIMIT @limit
            RETURN UNSET(doc, '_rev')
        """
        return await self._run(self.db.aql, aql, bind)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def count(self) -> int:
        def _count():
            return self.db.db.collection("taxa").count()
        return await self._run(_count)

    async def is_populated(self) -> bool:
        """Return True if the taxa collection has at least one document."""
        def _check():
            return self.db.db.collection("taxa").count() > 0
        return await self._run(_check)
