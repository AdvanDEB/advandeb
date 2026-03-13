"""
KGBuilderService — links documents to taxonomy nodes.

Populates the `document_taxon_relations` collection, which the graph builder
reads to materialise `studies` edges in the `knowledge_graph` schema.

Matching strategy (fast, no LLM required):
  1. Title scanning — binomial / capitalized word-pair candidates (confidence 0.90)
  2. Concept / keyword / tag matching from OpenAlex metadata (confidence 0.85/0.75)

The name index is built once per service instance from `taxonomy_nodes`.
Re-instantiate the service (or call build_name_index) to pick up taxonomy
changes.

Usage:
    service = KGBuilderService(db)
    n = await service.build_name_index(root_taxid=40674)   # Mammalia subtree
    result = await service.link_documents(limit=1000)
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

logger = logging.getLogger(__name__)

# Minimum characters for a name to be included in the index
_MIN_NAME_LEN = 4

# Regex: capitalized word followed by one or two lowercase words
# catches "Mus musculus", "Homo sapiens domesticus", "Balaenoptera acutorostrata"
_BINOMIAL_RE = re.compile(r'\b([A-Z][a-z]{2,}(?:\s+[a-z]{3,}(?:\s+[a-z]{3,})?)?)\b')


def _normalize(name: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation."""
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', name.lower())).strip()


def _candidate_names(text: str) -> List[str]:
    """Return candidate taxon names from free text (binomial patterns)."""
    return _BINOMIAL_RE.findall(text or "")


# confidence multipliers by match source and rank
_CONF = {
    "title_species":    0.92,
    "title_genus":      0.80,
    "title_other":      0.72,
    "concept_species":  0.85,
    "concept_genus":    0.75,
    "concept_other":    0.68,
}


class KGBuilderService:
    """Links documents to taxonomy nodes via name-index matching."""

    def __init__(self, database):
        self.db = database
        # normalized_name → list of (tax_id: int, rank: str)
        self._index: Dict[str, List[Tuple[int, str]]] = {}
        self._index_root_taxid: Optional[int] = None
        self._index_size: int = 0

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    async def build_name_index(self, root_taxid: Optional[int] = None) -> int:
        """Build in-memory taxonomy name index.

        If root_taxid is given, only loads that subtree (fast).
        Indexes scientific names and synonyms.
        Returns the number of name entries indexed.
        """
        self._index = {}
        self._index_root_taxid = root_taxid

        query: Dict[str, Any] = {}
        if root_taxid is not None:
            query = {"$or": [{"tax_id": root_taxid}, {"lineage": root_taxid}]}

        count = 0
        async for taxon in self.db.taxonomy_nodes.find(
            query,
            {"tax_id": 1, "name": 1, "synonyms": 1, "common_names": 1, "rank": 1},
        ):
            tax_id = taxon["tax_id"]
            rank = taxon.get("rank", "no rank")
            names = (
                [taxon.get("name") or ""]
                + (taxon.get("synonyms") or [])
                + (taxon.get("common_names") or [])
            )
            for raw in names:
                if not raw or len(raw) < _MIN_NAME_LEN:
                    continue
                key = _normalize(raw)
                if not key:
                    continue
                self._index.setdefault(key, []).append((tax_id, rank))
                count += 1

        self._index_size = count
        logger.info(
            "KGBuilderService: name index built — %d entries, root_taxid=%s",
            count, root_taxid,
        )
        return count

    def index_ready(self) -> bool:
        return bool(self._index)

    # ------------------------------------------------------------------
    # Document linking
    # ------------------------------------------------------------------

    async def link_documents(
        self,
        limit: int = 1000,
        skip: int = 0,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Match documents to taxa and write document_taxon_relations.

        Args:
            limit:     Number of documents to process in this call.
            skip:      Offset into the documents collection.
            overwrite: If False (default), skip documents already linked.
                       If True, upsert relations (refresh existing).

        Returns summary dict.
        """
        if not self._index:
            raise RuntimeError("Call build_name_index() before link_documents()")

        # Optionally restrict to documents not yet linked
        exclude_ids: set = set()
        if not overwrite:
            async for rel in self.db.document_taxon_relations.find(
                {}, {"document_id": 1}
            ):
                exclude_ids.add(str(rel["document_id"]))

        docs_processed = 0
        docs_linked = 0
        relations_written = 0
        now = datetime.utcnow()

        query: Dict[str, Any] = {}
        async for doc in self.db.documents.find(query, limit=limit, skip=skip):
            doc_id_str = str(doc["_id"])
            if not overwrite and doc_id_str in exclude_ids:
                continue

            docs_processed += 1
            relations = self._match_document(doc, now)

            if relations:
                await self._upsert_relations(relations)
                docs_linked += 1
                relations_written += len(relations)

        logger.info(
            "link_documents — processed: %d, linked: %d, relations: %d",
            docs_processed, docs_linked, relations_written,
        )
        return {
            "documents_processed": docs_processed,
            "documents_linked": docs_linked,
            "relations_written": relations_written,
        }

    def _match_document(
        self,
        doc: Dict[str, Any],
        now: datetime,
    ) -> List[Dict[str, Any]]:
        """Return DocumentTaxonRelation dicts for one document."""
        # matched_taxids: tax_id → (confidence, evidence_text)
        matched: Dict[int, Tuple[float, str]] = {}

        def _update(tax_id: int, rank: str, conf_key: str, evidence: str) -> None:
            rank_key = "species" if rank == "species" else ("genus" if rank == "genus" else "other")
            full_key = f"{conf_key}_{rank_key}"
            conf = _CONF.get(full_key, 0.60)
            if tax_id not in matched or matched[tax_id][0] < conf:
                matched[tax_id] = (conf, evidence)

        # 1. Title candidates
        for candidate in _candidate_names(doc.get("title", "") or ""):
            key = _normalize(candidate)
            if key in self._index:
                for tax_id, rank in self._index[key]:
                    _update(tax_id, rank, "title", f"title: {candidate}")

        # 2. Concept / keyword / tag list (stored as `tags` by the importer)
        for tag in (doc.get("tags") or []):
            key = _normalize(tag)
            if key in self._index:
                for tax_id, rank in self._index[key]:
                    _update(tax_id, rank, "concept", f"tag: {tag}")

        # 3. Abstract — scan for binomial names (lower confidence than title)
        # Require ≥2 words to avoid matching common English words that are
        # also single-word genus names (e.g. "Data", "This", "Electron").
        for candidate in _candidate_names(doc.get("abstract", "") or ""):
            if " " not in candidate:
                continue
            key = _normalize(candidate)
            if key in self._index:
                for tax_id, rank in self._index[key]:
                    _update(tax_id, rank, "concept", f"abstract: {candidate}")

        if not matched:
            return []

        doc_oid = doc["_id"]
        return [
            {
                "document_id": doc_oid,
                "tax_id": tax_id,
                "relation_type": "studies",
                "confidence": round(conf, 3),
                "evidence": evidence,
                "status": "suggested",
                "created_by": "kg_builder",
                "created_at": now,
                "updated_at": now,
            }
            for tax_id, (conf, evidence) in matched.items()
        ]

    async def _upsert_relations(self, relations: List[Dict[str, Any]]) -> None:
        """Upsert relations by (document_id, tax_id)."""
        from pymongo import UpdateOne
        ops = [
            UpdateOne(
                {"document_id": r["document_id"], "tax_id": r["tax_id"]},
                {"$setOnInsert": r},
                upsert=True,
            )
            for r in relations
        ]
        await self.db.document_taxon_relations.bulk_write(ops, ordered=False)

    # ------------------------------------------------------------------
    # Index maintenance
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> None:
        """Create MongoDB indexes on document_taxon_relations."""
        col = self.db.document_taxon_relations
        await col.create_index([("document_id", 1), ("tax_id", 1)], unique=True)
        await col.create_index("tax_id")
        await col.create_index("status")
        await col.create_index("created_by")
        logger.info("Indexes ensured on document_taxon_relations")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """Return counts useful for monitoring progress."""
        total_docs = await self.db.documents.count_documents({})
        total_relations = await self.db.document_taxon_relations.count_documents({})
        linked_docs = len(
            await self.db.document_taxon_relations.distinct("document_id")
        )
        confirmed = await self.db.document_taxon_relations.count_documents(
            {"status": "confirmed"}
        )
        suggested = await self.db.document_taxon_relations.count_documents(
            {"status": "suggested"}
        )
        return {
            "total_documents": total_docs,
            "linked_documents": linked_docs,
            "unlinked_documents": total_docs - linked_docs,
            "total_relations": total_relations,
            "confirmed_relations": confirmed,
            "suggested_relations": suggested,
            "index_entries": self._index_size,
            "index_root_taxid": self._index_root_taxid,
        }
