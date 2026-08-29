"""
KGBuilderService — links documents to taxonomy nodes.

Writes document→taxon edges into the `knowledge_graph` edge collection
(same collection used by the named graph `knowledge_graph` in ArangoDB).

Each edge:
  _from        : "documents/<doc_key>"
  _to          : "taxa/<tax_id_str>"
  relation_type: "studies"
  confidence   : float
  evidence     : str
  status       : "suggested" | "confirmed" | "rejected"
  created_by   : "kg_builder" | user_id
  created_at   : ISO datetime string

Matching strategy (fast, no LLM required):
  1. Title scanning — binomial / capitalized word-pair candidates (confidence 0.90)
  2. Concept / keyword / tag matching from OpenAlex metadata (confidence 0.85/0.75)

The name index is built once per service instance from `taxa`.
Re-instantiate (or call build_name_index) to pick up taxonomy changes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from advandeb_kb.database.arango_client import ArangoDatabase

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kg-builder-svc")

# Minimum characters for a name to be included in the index
_MIN_NAME_LEN = 4

# Regex: capitalized word followed by one or two lowercase words
_BINOMIAL_RE = re.compile(r'\b([A-Z][a-z]{2,}(?:\s+[a-z]{3,}(?:\s+[a-z]{3,})?)?)\b')


def _normalize(name: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation."""
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', name.lower())).strip()


def _candidate_names(text: str) -> List[str]:
    """Return candidate taxon names from free text (binomial patterns).

    The regex is greedy — on "Growth of Danio rerio under stress" it captures
    "Danio rerio under", which matches no index key. Emitting every leading
    sub-phrase of each capture ("Danio", "Danio rerio", "Danio rerio under")
    means a name is found wherever it sits in the sentence, not only when it
    happens to fall at the end of a phrase. Longer candidates are still
    generated, so binomials keep winning over their bare genus via the
    confidence ranking in ``_match_document``.
    """
    seen: Dict[str, None] = {}
    for match in _BINOMIAL_RE.finditer(text or ""):
        words = match.group(1).split()
        for length in range(1, len(words) + 1):
            seen.setdefault(" ".join(words[:length]), None)
    return list(seen)


_CONF = {
    "title_species":    0.92,
    "title_genus":      0.80,
    "title_other":      0.72,
    "concept_species":  0.85,
    "concept_genus":    0.75,
    "concept_other":    0.68,
}

# Ranks a *single-token* match is allowed to resolve to.
#
# Multi-word names ("Danio rerio") are unambiguous and accepted at any rank. A
# bare capitalised word is not, and matching it against coarse ranks produces
# assertions that are technically true and useless: scanning 40,000 titles, the
# single word "Animals" hit Animalia 15 times, "Fish" hit three fish classes 88
# times, "Birds"/"Avian"/"Amphibians"/"Rodent" likewise. "This paper studies
# Animalia" is not knowledge. Genus and below is where a lone word carries
# enough information to be worth an edge.
_SINGLE_TOKEN_RANKS = frozenset({"species", "subspecies", "genus", "subgenus"})

# Single-token taxon names whose ordinary-English reading dominates in
# scientific prose. Without this the linker asserts that every oncology paper
# studies the crab genus *Cancer*.
#
# Derived empirically, not guessed: built the full 1.5M-entry name index and
# counted single-token title matches across 40,000 documents (2026-08-26). Each
# entry below is a real NCBI genus/species name that outscored its taxonomic
# reading in this corpus. Frequencies from that scan are noted so the cost of
# each exclusion is on the record.
#
# Deliberately NOT blocked, because their taxonomic reading is the common one
# and they are exactly the matches this linker exists to find: Mouse (910),
# Zebrafish (787), Human (627), Drosophila (932), Xenopus (471), Chicken (380),
# Bovine (325), Cattle (71), Rabbit (80), Sheep, Goat, Duck, Medaka, Artemia.
_AMBIGUOUS_TAXON_NAMES = frozenset({
    "cancer",     # 90 — crab genus vs. the disease
    "data",       # 27 — moth genus
    "axis",       # 53 — deer genus vs. anatomical/geometric axis
    "china",      # 41 — genus vs. the country
    "argentina",  # 13 — fish genus vs. the country
    "electron",   # 31 — genus vs. the particle
    "major",      # 25 — genus vs. the adjective
    "beta",       # 20 — genus vs. the Greek letter
    "meta",       # 20 — spider genus vs. the prefix
    "delta",      # 19 — genus vs. the Greek letter / river delta
    "lens",       # 20 — genus vs. the optical/ocular structure
    "helix",      # 15 — snail genus vs. the geometric form (DNA helix)
    # Same class, not seen in the sample but well-known homographs that would
    # behave identically on a larger corpus.
    "chaos", "aurora", "iris", "pandora", "basilica", "proxima",
})


# Projection shared by every scan. `content` is only pulled when there is no
# abstract to read — it is the largest field in the collection and fetching 8 KB
# of it per document across 3.9M rows is the difference between a scan that
# finishes and one that does not.
_DOC_PROJECTION = """
    RETURN {_key: doc._key, title: doc.title, abstract: doc.abstract,
            content: doc.abstract ? null : LEFT(doc.content, 8000),
            tags: doc.tags}
"""

# Paged scans sort by _key so paging is stable: the previous query had no SORT,
# so `LIMIT skip, limit` walked an arbitrary order and successive pages could
# repeat or miss documents.
_SCOPE_QUERIES = {
    "all": f"""
    FOR doc IN documents
        FILTER doc.title != null OR doc.abstract != null
        SORT doc._key
        LIMIT @skip, @limit
        {_DOC_PROJECTION}
    """,
    "curated": f"""
    FOR meta IN document_meta
        SORT meta._key
        LIMIT @skip, @limit
        LET doc = DOCUMENT(CONCAT('documents/', meta._key))
        FILTER doc != null
        {_DOC_PROJECTION}
    """,
    # Documents that facts were extracted from — the set that actually feeds the
    # sf_support and physiological_process graphs, so linking these first is what
    # makes those views useful soonest.
    "with_facts": f"""
    LET keys = (FOR f IN facts FILTER f.document_id != null RETURN DISTINCT f.document_id)
    FOR key IN keys
        SORT key
        LIMIT @skip, @limit
        LET doc = DOCUMENT(CONCAT('documents/', key))
        FILTER doc != null
        {_DOC_PROJECTION}
    """,
}

_DOCS_BY_KEY_AQL = f"""
FOR key IN @keys
    LET doc = DOCUMENT(CONCAT('documents/', key))
    FILTER doc != null
    {_DOC_PROJECTION}
"""


def _index_entries_for_single_token(
    key: str,
    index: Dict[str, List[Tuple[int, str]]],
) -> List[Tuple[int, str]]:
    """Index entries a lone capitalised word may resolve to (may be empty)."""
    if key in _AMBIGUOUS_TAXON_NAMES:
        return []
    return [(tax_id, rank) for tax_id, rank in index.get(key, ()) if rank in _SINGLE_TOKEN_RANKS]


class KGBuilderService:
    """Links documents to taxonomy nodes via name-index matching."""

    def __init__(self, database: ArangoDatabase):
        self.db = database
        # normalized_name → list of (tax_id: int, rank: str, tax_key: str)
        self._index: Dict[str, List[Tuple[int, str]]] = {}
        self._index_root_taxid: Optional[int] = None
        self._index_size: int = 0

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    async def build_name_index(self, root_taxid: Optional[int] = None) -> int:
        """Build in-memory taxonomy name index from ArangoDB taxa collection.

        If root_taxid is given, only loads that subtree (fast).
        Returns the number of name entries indexed.
        """
        def _build():
            index: Dict[str, List[Tuple[int, str]]] = {}
            bind: Dict[str, Any] = {}
            if root_taxid is not None:
                aql = """
                FOR doc IN taxa
                    FILTER doc.tax_id == @root OR @root IN doc.lineage
                    RETURN {tax_id: doc.tax_id, name: doc.name,
                            synonyms: doc.synonyms, common_names: doc.common_names,
                            rank: doc.rank}
                """
                bind["root"] = root_taxid
            else:
                aql = """
                FOR doc IN taxa
                    RETURN {tax_id: doc.tax_id, name: doc.name,
                            synonyms: doc.synonyms, common_names: doc.common_names,
                            rank: doc.rank}
                """
            count = 0
            for taxon in self.db.aql(aql, bind):
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
                    index.setdefault(key, []).append((tax_id, rank))
                    count += 1
            return index, count

        self._index, self._index_size = await self._run(_build)
        self._index_root_taxid = root_taxid
        logger.info(
            "KGBuilderService: name index built — %d entries, root_taxid=%s",
            self._index_size, root_taxid,
        )
        return self._index_size

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
        scope: str = "all",
        doc_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Match documents to taxa and write edges to knowledge_graph.

        Args:
            limit:     Number of documents to process in this call.
            skip:      Offset into the document set (ignored when doc_keys given).
            overwrite: If False (default), skip documents already linked.
                       If True, upsert relations (refresh existing).
            scope:     Which documents to walk:
                       "curated"    — the ``document_meta`` set (fully ingested papers)
                       "with_facts" — documents facts were extracted from
                       "all"        — every document with a title or abstract
            doc_keys:  Link exactly these documents, ignoring scope/skip/limit.
                       Used by the ingestion hook to link a document on arrival.

        Returns summary dict.
        """
        if not self._index:
            raise RuntimeError("Call build_name_index() before link_documents()")
        if scope not in _SCOPE_QUERIES:
            raise ValueError(f"Unknown scope {scope!r}; expected one of {sorted(_SCOPE_QUERIES)}")

        def _link():
            # Fetch existing linked doc keys (to skip)
            exclude_keys: set = set()
            if not overwrite:
                existing = self.db.aql(
                    "FOR e IN knowledge_graph FILTER e.relation_type == 'studies' "
                    "RETURN DISTINCT PARSE_IDENTIFIER(e._from).key"
                )
                exclude_keys = {r for r in existing}

            if doc_keys is not None:
                docs = self.db.aql(_DOCS_BY_KEY_AQL, {"keys": list(doc_keys)})
            else:
                docs = self.db.aql(_SCOPE_QUERIES[scope], {"skip": skip, "limit": limit})

            now_iso = datetime.now(timezone.utc).isoformat()
            docs_processed = 0
            docs_linked = 0
            relations_written = 0

            for doc in docs:
                doc_key = doc["_key"]
                if not overwrite and doc_key in exclude_keys:
                    continue

                docs_processed += 1
                relations = _match_document(doc, self._index, now_iso)

                if relations:
                    _upsert_edges(self.db, doc_key, relations, overwrite)
                    docs_linked += 1
                    relations_written += len(relations)

            return {
                "documents_processed": docs_processed,
                "documents_linked": docs_linked,
                "relations_written": relations_written,
            }

        result = await self._run(_link)
        logger.info(
            "link_documents — processed: %(documents_processed)d, "
            "linked: %(documents_linked)d, relations: %(relations_written)d",
            result,
        )
        return result

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """Return counts useful for monitoring progress."""
        def _stats():
            total_docs = self.db.db.collection("documents").count()
            aql_rel = """
            LET total = LENGTH(FOR e IN knowledge_graph FILTER e.relation_type == 'studies' RETURN 1)
            LET linked = LENGTH(FOR e IN knowledge_graph FILTER e.relation_type == 'studies'
                                RETURN DISTINCT PARSE_IDENTIFIER(e._from).key)
            LET confirmed = LENGTH(FOR e IN knowledge_graph
                                   FILTER e.relation_type == 'studies' AND e.status == 'confirmed'
                                   RETURN 1)
            LET suggested = LENGTH(FOR e IN knowledge_graph
                                   FILTER e.relation_type == 'studies' AND e.status == 'suggested'
                                   RETURN 1)
            RETURN {total, linked, confirmed, suggested}
            """
            r = self.db.aql(aql_rel)[0]
            return {
                "total_documents": total_docs,
                "linked_documents": r["linked"],
                "unlinked_documents": total_docs - r["linked"],
                "total_relations": r["total"],
                "confirmed_relations": r["confirmed"],
                "suggested_relations": r["suggested"],
                "index_entries": self._index_size,
                "index_root_taxid": self._index_root_taxid,
            }
        return await self._run(_stats)

    async def ensure_indexes(self) -> None:
        """ArangoDB persistent indexes on knowledge_graph edge collection."""
        def _idx():
            col = self.db.db.collection("knowledge_graph")
            existing = [idx["fields"] for idx in col.indexes()]
            for fields in [["relation_type"], ["status"], ["created_by"]]:
                if fields not in existing:
                    col.add_persistent_index(fields=fields)
            logger.info("Indexes ensured on knowledge_graph")
        await self._run(_idx)


# ------------------------------------------------------------------
# Module-level helpers (called from within thread pool)
# ------------------------------------------------------------------

def _match_document(
    doc: Dict[str, Any],
    index: Dict[str, List[Tuple[int, str]]],
    now_iso: str,
) -> List[Dict[str, Any]]:
    """Return edge dicts for one document."""
    matched: Dict[int, Tuple[float, str]] = {}

    def _update(tax_id: int, rank: str, conf_key: str, evidence: str) -> None:
        rank_key = "species" if rank == "species" else ("genus" if rank == "genus" else "other")
        full_key = f"{conf_key}_{rank_key}"
        conf = _CONF.get(full_key, 0.60)
        if tax_id not in matched or matched[tax_id][0] < conf:
            matched[tax_id] = (conf, evidence)

    # 1. Title candidates. Multi-word names are unambiguous; a lone capitalised
    #    word has to clear the ambiguity guard first.
    for candidate in _candidate_names(doc.get("title", "") or ""):
        key = _normalize(candidate)
        entries = index.get(key, ()) if " " in candidate else _index_entries_for_single_token(key, index)
        for tax_id, rank in entries:
            _update(tax_id, rank, "title", f"title: {candidate}")

    # 2. Tags — same rule; OpenAlex concept tags are often single words.
    for tag in (doc.get("tags") or []):
        key = _normalize(tag)
        entries = index.get(key, ()) if " " in key else _index_entries_for_single_token(key, index)
        for tax_id, rank in entries:
            _update(tax_id, rank, "concept", f"tag: {tag}")

    # 3. Abstract (multi-word binomials only)
    for candidate in _candidate_names(doc.get("abstract", "") or ""):
        if " " not in candidate:
            continue
        key = _normalize(candidate)
        if key in index:
            for tax_id, rank in index[key]:
                _update(tax_id, rank, "concept", f"abstract: {candidate}")

    # 4. Content snippet (when abstract absent)
    if not doc.get("abstract"):
        content_snippet = (doc.get("content") or "")[:8000]
        for candidate in _candidate_names(content_snippet):
            if " " not in candidate:
                continue
            key = _normalize(candidate)
            if key in index:
                for tax_id, rank in index[key]:
                    _update(tax_id, rank, "concept", f"content: {candidate}")

    if not matched:
        return []

    doc_key = doc["_key"]
    return [
        {
            "_from": f"documents/{doc_key}",
            "_to": f"taxa/{tax_id}",
            "relation_type": "studies",
            "confidence": round(conf, 3),
            "evidence": evidence,
            "status": "suggested",
            "created_by": "kg_builder",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        for tax_id, (conf, evidence) in matched.items()
    ]


def _upsert_edges(
    db: ArangoDatabase,
    doc_key: str,
    relations: List[Dict[str, Any]],
    overwrite: bool,
) -> None:
    """Upsert knowledge_graph edges for a document.

    Uses AQL UPSERT so each (document, taxon) pair is unique.
    """
    col = db.db.collection("knowledge_graph")
    for rel in relations:
        # UPSERT by (_from, _to, relation_type) — unique per document-taxon pair
        db.db.aql.execute(
            """
            UPSERT {_from: @from, _to: @to, relation_type: @rtype}
            INSERT @doc
            UPDATE ((@overwrite) ? @doc : {})
            IN knowledge_graph
            """,
            bind_vars={
                "from": rel["_from"],
                "to": rel["_to"],
                "rtype": rel["relation_type"],
                "doc": rel,
                "overwrite": overwrite,
            },
        )
