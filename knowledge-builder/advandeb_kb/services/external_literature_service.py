"""
ExternalLiteratureService — OpenAlex/CrossRef fallback for thin-evidence queries.

Called by ChatPipelineService when ReferenceVerifierService returns
verdict="need_external" and CHAT_ENABLE_EXTERNAL_FALLBACK is True.

Returns a list of chunk-shaped dicts (same schema as hybrid_search chunks)
so they can be merged into the EvidenceRegistry without any special handling.

Search strategy
---------------
1. OpenAlex full-text search on the query string (fast, broad coverage).
2. Filter by relevance_score > threshold and publication year >= 1990.
3. Convert each work to a chunk dict with source_type="external_document".
4. Cap at MAX_EXTERNAL_CHUNKS results to avoid flooding the context window.

Chunk format returned
---------------------
{
    "chunk_id":    "external:<openalex_id>",
    "document_id": "<openalex_id>",
    "text":        "<title>. <abstract_inverted_index reconstructed or empty>",
    "metadata": {
        "source":    "external_document",
        "title":     "...",
        "authors":   ["..."],
        "year":      2021,
        "journal":   "...",
        "doi":       "...",
        "url":       "...",
        "document_id": "<openalex_id>",
        "citation_id": "external:<openalex_id>",
    },
}
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from advandeb_kb.config.settings import settings

logger = logging.getLogger(__name__)

MAX_EXTERNAL_CHUNKS = 5
_OPENALEX_BASE = "https://api.openalex.org/works"
_SELECT_FIELDS = (
    "id,doi,title,display_name,publication_year,primary_location,"
    "authorships,abstract_inverted_index,cited_by_count,is_retracted"
)


class ExternalLiteratureService:
    """Search OpenAlex for relevant papers when local KB evidence is thin."""

    async def search(self, query: str) -> list[dict]:
        """
        Search OpenAlex and return up to MAX_EXTERNAL_CHUNKS chunk-shaped dicts.

        Gracefully returns [] on any error so the pipeline can continue.
        """
        try:
            works = await self._openalex_search(query)
        except Exception as exc:
            logger.warning("ExternalLiteratureService.search failed: %s", exc)
            return []

        chunks = []
        for work in works[:MAX_EXTERNAL_CHUNKS]:
            chunk = _work_to_chunk(work)
            if chunk:
                chunks.append(chunk)

        logger.info(
            "ExternalLiteratureService: query=%r → %d external chunks", query[:60], len(chunks)
        )
        return chunks

    # ------------------------------------------------------------------
    # OpenAlex search
    # ------------------------------------------------------------------

    async def _openalex_search(self, query: str) -> list[dict]:
        """
        Full-text search OpenAlex.  Returns raw work dicts.
        """
        params: Dict[str, Any] = {
            "search": query,
            "select": _SELECT_FIELDS,
            "per-page": MAX_EXTERNAL_CHUNKS + 3,  # fetch a few extra for filtering
            "filter": "publication_year:1990-2030,is_retracted:false",
            "sort": "relevance_score:desc",
            "mailto": settings.OPENALEX_EMAIL,
        }

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=15.0
                ) as client:
                    resp = await client.get(_OPENALEX_BASE, params=params)
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        "ExternalLiteratureService: OpenAlex returned %d", resp.status_code
                    )
                    return []
                return resp.json().get("results") or []
            except Exception as exc:
                logger.debug(
                    "ExternalLiteratureService: attempt %d failed: %s", attempt + 1, exc
                )
                if attempt < 2:
                    await asyncio.sleep(1.0)
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reconstruct_abstract(inverted_index: Optional[dict]) -> str:
    """
    Reconstruct plain text from OpenAlex abstract_inverted_index.

    The inverted index maps word → [position, ...].  We invert it back to
    position → word, then join in order.
    """
    if not inverted_index:
        return ""
    try:
        pos_word: list[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                pos_word.append((pos, word))
        pos_word.sort(key=lambda x: x[0])
        return " ".join(w for _, w in pos_word)
    except Exception:
        return ""


def _work_to_chunk(work: dict) -> Optional[dict]:
    """Convert an OpenAlex work dict to a chunk-shaped dict."""
    oa_id = work.get("id", "")
    # Strip URL prefix: "https://openalex.org/W1234" → "W1234"
    short_id = oa_id.rsplit("/", 1)[-1] if "/" in oa_id else oa_id
    if not short_id:
        return None

    title = work.get("display_name") or work.get("title") or ""
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    text = f"{title}. {abstract}".strip()
    if not text or text == ".":
        text = title

    year = work.get("publication_year")
    doi = work.get("doi") or ""

    # Primary location URL
    primary = work.get("primary_location") or {}
    url = primary.get("landing_page_url") or doi or f"https://openalex.org/{short_id}"

    # Journal name
    source = primary.get("source") or {}
    journal = source.get("display_name") or ""

    # Authors
    authorships = work.get("authorships") or []
    authors: list[str] = []
    for a in authorships[:5]:
        name = (a.get("author") or {}).get("display_name") or ""
        if name:
            authors.append(name)

    citation_id = f"external:{short_id}"

    return {
        "chunk_id": citation_id,
        "document_id": short_id,
        "text": text[:800],
        "metadata": {
            "source": "external_document",
            "citation_id": citation_id,
            "document_id": short_id,
            "title": title,
            "authors": authors,
            "year": year,
            "journal": journal,
            "doi": doi,
            "url": url,
        },
    }
