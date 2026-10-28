"""
PassageCitationService — a readable citation for every evidence passage.

Experts judge each stylized fact from retrieved passages, and a passage is
only as useful as the expert's knowledge of where it comes from. The frozen
evidence sets record very little of that: every DEB-corpus passage carries a
library FILE NAME as its title ("Kooy93.pdf") and nothing else, so before this
service an expert was asked to weigh "Kooy93.pdf" against a stylized fact.

The citation is resolved **when the item is served**, by a join, and never
stored on the passage. The evidence sets are a frozen measurement instrument —
the agent panel read exactly that text, and `content_hash`, `text_sha256` and
`statement_sha256` are what make "both panels read the same evidence" a
checkable claim (ADR 0003). A citation is a label on a passage, not part of
it, so it lives outside the instrument and improves without touching it.

The join:

  deb           passage `document_id` is the folder in the DEB library
                (/home/adeb/DEB_library/<id>/<file>.pdf); the curated papers are
                the ArangoDB `documents` with `source_type == "pdf_local"`,
                whose `source_path` is "<id>/<file>". 1,253 records, so they
                are loaded once and cached rather than queried per item.
  reproduction  passage `document_id` is an OpenAlex work id, which is the
                `documents` `_key`; looked up per item by primary key.

ArangoDB is canonical for document metadata (docs/STORAGE-CONTRACT.md), so
corrections to a citation are made there and show up here on the next cache
refresh. When ArangoDB cannot be reached the passage is still served, marked
unresolved: a missing citation must never stop an expert from working.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional

from app.models.elicitation import EvidencePassage, PassageCitation

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="passage-cite")

# The curated library changes rarely; a correction made in ArangoDB reaches
# experts within this many seconds.
CACHE_TTL_S = 900
# After a failed load, how long to serve unresolved citations before trying
# again, so an unreachable ArangoDB costs one timeout, not one per request.
FAILURE_BACKOFF_S = 60

DEB_CORPUS = "deb"

_FIELDS = ["source_path", "title", "authors", "year", "journal", "doi",
           "pages", "volume", "issue"]

# Imported metadata stores absence as text as often as as null.
_ABSENT = {"", "none", "null", "nan", "[]", "n/a"}

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _ABSENT else text


def normalise_doi(raw: Any) -> Optional[str]:
    """The bare DOI, or None when there is no well-formed one.

    Reproduction passages store a full https://doi.org/ URL; the DEB records
    store the bare form or the string "None". The client builds the link, so
    it gets one shape — a link built from the URL form pointed at
    https://doi.org/https://doi.org/….
    """
    d = _clean(raw)
    if not d:
        return None
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I).strip()
    return d if _DOI_RE.match(d) else None


def _authors(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(a).strip() for a in value if _clean(a)]
    text = _clean(value)
    if not text:
        return []
    if text.startswith("["):
        # Some records hold a stringified Python list.
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple)):
                return [str(a).strip() for a in parsed if _clean(a)]
        except (ValueError, SyntaxError):
            pass
    return [text]


def _year(value: Any) -> Optional[int]:
    text = _clean(value)
    if not text:
        return None
    m = re.match(r"^(\d{4})", text)
    return int(m.group(1)) if m else None


def _is_real_title(title: Optional[str], file_name: Optional[str]) -> bool:
    """A title that is the file name, or any *.pdf, says where the bytes are
    and nothing about the work."""
    if not title:
        return False
    if file_name and title.strip() == file_name.strip():
        return False
    return not title.lower().endswith(".pdf")


def citation_from(doc: Optional[Dict[str, Any]], *, file_name: Optional[str],
                  library_id: Optional[str],
                  fallback: Optional[Dict[str, Any]] = None) -> PassageCitation:
    """Build a citation from a document record, falling back to what the
    passage itself recorded where the record is missing or thinner."""
    doc = doc or {}
    fallback = fallback or {}
    title = _clean(doc.get("title"))
    if not _is_real_title(title, file_name):
        title = _clean(fallback.get("title"))
        if not _is_real_title(title, file_name):
            title = None
    authors = _authors(doc.get("authors")) or _authors(fallback.get("authors"))
    year = _year(doc.get("year")) or _year(fallback.get("year"))
    doi = normalise_doi(doc.get("doi")) or normalise_doi(fallback.get("doi"))
    journal = _clean(doc.get("journal"))
    pages = _clean(doc.get("pages"))

    if title and authors and year:
        status = "resolved"
    elif title:
        status = "partial"
    else:
        status = "unresolved"
    return PassageCitation(
        status=status, authors=authors, year=year, title=title,
        journal=journal, doi=doi, pages=pages,
        file_name=file_name if status == "unresolved" else None,
        library_id=library_id)


# --------------------------------------------------------------------------- #
# Loaders — the only code that talks to ArangoDB. Module-level so a test can   #
# replace them without a database.                                             #
# --------------------------------------------------------------------------- #

def _load_deb_documents() -> List[Dict[str, Any]]:
    """Every curated DEB-library document, by the indexed `source_type`.

    Never an unfiltered scan: `documents` holds ~3.9M OpenAlex records.
    """
    from app.core.database import get_arango_db
    return get_arango_db().aql(
        "FOR d IN documents FILTER d.source_type == 'pdf_local' "
        "RETURN KEEP(d, @fields)", {"fields": _FIELDS})


def _load_documents_by_key(keys: List[str]) -> List[Dict[str, Any]]:
    from app.core.database import get_arango_db
    return get_arango_db().aql(
        "FOR d IN documents FILTER d._key IN @keys "
        "RETURN MERGE(KEEP(d, @fields), {_key: d._key})",
        {"keys": keys, "fields": _FIELDS})


# While ArangoDB is unreachable, every lookup is skipped until this moment
# (time.monotonic()). The client retries a refused connection with back-off,
# so without this each served item would wait out those retries again.
_store_down_until = 0.0


def _store_down() -> bool:
    return time.monotonic() < _store_down_until


def _mark_store_down(exc: Exception) -> None:
    global _store_down_until
    _store_down_until = time.monotonic() + FAILURE_BACKOFF_S
    logger.warning("passage citations: ArangoDB unavailable (%s); serving "
                   "unresolved citations for %ds", exc, FAILURE_BACKOFF_S)


class _DebLibrary:
    """The curated library, indexed by path and by folder, with a TTL."""

    def __init__(self) -> None:
        self.by_path: Dict[str, Dict[str, Any]] = {}
        self.by_folder: Dict[str, List[Dict[str, Any]]] = {}
        self.loaded_at = 0.0
        self.lock = asyncio.Lock()

    def fresh(self, now: float) -> bool:
        return bool(self.by_path) and now - self.loaded_at < CACHE_TTL_S

    async def ensure(self) -> None:
        if self.fresh(time.monotonic()) or _store_down():
            return
        async with self.lock:
            now = time.monotonic()
            if self.fresh(now) or _store_down():
                return
            try:
                loop = asyncio.get_running_loop()
                docs = await loop.run_in_executor(_executor, _load_deb_documents)
            except Exception as exc:
                _mark_store_down(exc)
                return
            by_path: Dict[str, Dict[str, Any]] = {}
            by_folder: Dict[str, List[Dict[str, Any]]] = {}
            for d in docs or []:
                path = _clean(d.get("source_path"))
                if not path:
                    continue
                by_path[path] = d
                by_folder.setdefault(path.split("/", 1)[0], []).append(d)
            self.by_path, self.by_folder = by_path, by_folder
            self.loaded_at = now

    def lookup(self, library_id: Optional[str],
               file_name: Optional[str]) -> Optional[Dict[str, Any]]:
        if not library_id:
            return None
        if file_name:
            hit = self.by_path.get(f"{library_id}/{file_name}")
            if hit:
                return hit
        # A folder holds one paper in the DEB library; when the file was
        # renamed after the evidence sets were frozen, the folder still
        # identifies it. More than one candidate is ambiguous, so no match.
        in_folder = self.by_folder.get(str(library_id)) or []
        return in_folder[0] if len(in_folder) == 1 else None


_deb_library = _DebLibrary()


def reset_cache() -> None:
    """Forget the cached library and any recorded outage (tests, and after a
    metadata correction)."""
    global _deb_library, _store_down_until
    _deb_library = _DebLibrary()
    _store_down_until = 0.0


async def cite_passages(corpus_id: Optional[str],
                        passages: Iterable[EvidencePassage]
                        ) -> List[EvidencePassage]:
    """Return the passages with `citation` filled. Never raises."""
    passages = list(passages)
    try:
        if corpus_id == DEB_CORPUS:
            await _deb_library.ensure()
            for p in passages:
                doc = _deb_library.lookup(p.document_id, p.title)
                p.citation = citation_from(
                    doc, file_name=p.title, library_id=p.document_id)
            return passages

        keys = sorted({p.document_id for p in passages if p.document_id})
        docs: Dict[str, Dict[str, Any]] = {}
        if keys and not _store_down():
            try:
                loop = asyncio.get_running_loop()
                rows = await loop.run_in_executor(
                    _executor, _load_documents_by_key, keys)
                docs = {r.get("_key"): r for r in rows or []}
            except Exception as exc:
                _mark_store_down(exc)
        for p in passages:
            p.citation = citation_from(
                docs.get(p.document_id), file_name=None,
                library_id=p.document_id,
                fallback={"title": p.title, "year": p.year, "doi": p.doi})
    except Exception as exc:  # a citation must never block an item
        logger.warning("passage citations failed: %s", exc)
    return passages
