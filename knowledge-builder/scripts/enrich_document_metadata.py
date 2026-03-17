"""
Enrich pdf_local documents with metadata (title, authors, year, doi, references).

Steps:
  1. Parse filename to extract year, authors, paper_title (best-effort)
  2. For docs with a parseable title: query CrossRef/OpenAlex to find DOI + references
  3. Write updates back to MongoDB (non-destructive: only sets fields that are None/empty)

Usage:
    # Dry-run first 20 docs
    conda run -n advandeb python scripts/enrich_document_metadata.py --dry-run --limit 20

    # Real run (all pdf_local docs)
    conda run -n advandeb python scripts/enrich_document_metadata.py

    # Force-overwrite existing metadata
    conda run -n advandeb python scripts/enrich_document_metadata.py --force

    # With higher concurrency
    conda run -n advandeb python scripts/enrich_document_metadata.py --concurrency 5
"""

import argparse
import asyncio
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

# "Author et al. - 2019 - Title fragment..."  (long Zotero-style names)
LONG_PATTERN = re.compile(
    r"^(.+?)\s*[-–—]\s*(19[6-9]\d|20[0-2]\d)\s*[-–—]\s*(.+?)$", re.I
)
# Short code: "DuttKooi2017", "Kooy86a", "RatsMaar96"
SHORT_YEAR_RE = re.compile(r"(?:^|[A-Za-z])(\d{2,4})[a-zA-Z]?$")
# Standalone 4-digit year anywhere
YEAR4_RE = re.compile(r"(19[6-9]\d|20[0-2]\d)")


def _normalize_year(y: str) -> int:
    """Convert 2-digit or 4-digit year string to int."""
    n = int(y)
    if n < 100:
        return 1900 + n if n >= 60 else 2000 + n
    return n


def parse_filename(filename: str) -> Dict[str, Any]:
    """Return dict with keys: year, authors_raw, paper_title (all may be None)."""
    base = filename
    for ext in (".pdf", ".PDF"):
        base = base.removesuffix(ext)
    base = base.strip()

    # Long Zotero-style
    m = LONG_PATTERN.match(base)
    if m:
        authors_raw = m.group(1).strip()
        year = _normalize_year(m.group(2))
        paper_title = m.group(3).strip()
        # Clean trailing dots or spaces from title truncation
        paper_title = paper_title.rstrip(". ")
        return {"year": year, "authors_raw": authors_raw, "paper_title": paper_title}

    # Short code – year only
    year = None
    m4 = YEAR4_RE.search(base)
    if m4:
        year = int(m4.group(1))
    else:
        ms = SHORT_YEAR_RE.search(base)
        if ms:
            year = _normalize_year(ms.group(1))

    # Title-only long name (no year) e.g. "Choudri et al. - Ecological and human..."
    # Split on " - " to get author and title
    parts = re.split(r"\s*[-–—]\s+", base, maxsplit=1)
    if len(parts) == 2:
        authors_raw = parts[0].strip()
        paper_title = parts[1].strip()
    else:
        authors_raw = None
        paper_title = None

    return {"year": year, "authors_raw": authors_raw, "paper_title": paper_title}


def _parse_authors(authors_raw: Optional[str]) -> List[str]:
    """Very rough author list from strings like 'Martin et al.', 'Baas en Berg'."""
    if not authors_raw:
        return []
    # Take everything before "et al", "e.a.", "en ", "and "
    first = re.split(r"\s+(et al|e\.a\.|en |and |&)", authors_raw, flags=re.I)[0]
    first = first.strip().rstrip(",")
    return [first] if first else []


# ---------------------------------------------------------------------------
# CrossRef / OpenAlex helpers
# ---------------------------------------------------------------------------

CROSSREF_BASE = "https://api.crossref.org/works"
OPENALEX_BASE = "https://api.openalex.org/works"
HEADERS = {
    "User-Agent": "advandeb-knowledge-builder/1.0 (mailto:admin@advandeb.org)",
}


async def crossref_lookup(
    client: httpx.AsyncClient,
    title: str,
    year: Optional[int] = None,
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """Query CrossRef bibliographic search. Returns best match or None."""
    params: Dict[str, Any] = {
        "query.title": title,
        "rows": 3,
        "select": "DOI,title,author,published,reference",
    }
    if year:
        params["filter"] = f"from-pub-date:{year - 1},until-pub-date:{year + 1}"

    for attempt in range(max_retries):
        try:
            resp = await client.get(CROSSREF_BASE, params=params, timeout=20)
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                logger.debug("CrossRef HTTP %d for title=%r", resp.status_code, title[:60])
                return None
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            if not items:
                return None
            return items[0]
        except Exception as e:
            logger.debug("CrossRef error: %s", e)
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
    return None


def _title_similarity(a: str, b: str) -> float:
    """Very rough word-overlap similarity (0-1)."""
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def _extract_reference_dois(item: Dict[str, Any]) -> List[str]:
    """Pull DOI strings from CrossRef 'reference' list."""
    dois = []
    for ref in item.get("reference") or []:
        doi = ref.get("DOI")
        if doi and isinstance(doi, str):
            dois.append(doi.lower().strip())
    return dois


def _extract_authors(item: Dict[str, Any]) -> List[str]:
    """Extract author names from CrossRef item."""
    authors = []
    for a in item.get("author") or []:
        family = a.get("family", "")
        given = a.get("given", "")
        name = f"{given} {family}".strip() if given else family
        if name:
            authors.append(name)
    return authors


def _extract_year(item: Dict[str, Any]) -> Optional[int]:
    pub = item.get("published") or item.get("published-print") or item.get("published-online")
    if pub:
        dp = pub.get("date-parts", [[]])
        if dp and dp[0]:
            try:
                return int(dp[0][0])
            except (TypeError, ValueError):
                pass
    return None


# ---------------------------------------------------------------------------
# Per-document processing
# ---------------------------------------------------------------------------

SEM: asyncio.Semaphore  # set in main


async def enrich_one(
    doc: Dict[str, Any],
    http: httpx.AsyncClient,
    dry_run: bool,
    force: bool,
    db: Any,
) -> Tuple[str, str]:
    """
    Enrich a single document.
    Returns (doc_id_str, status) where status is one of:
      'updated', 'skipped', 'no_title', 'no_match', 'dry_run'
    """
    doc_id = doc["_id"]
    title_field: str = doc.get("title") or ""

    parsed = parse_filename(title_field)
    paper_title = parsed.get("paper_title")
    year_parsed = parsed.get("year")
    authors_raw = parsed.get("authors_raw")

    # Decide what we already have
    has_doi = bool(doc.get("doi"))
    has_year = doc.get("year") is not None
    has_authors = bool(doc.get("authors"))

    if not force and has_doi and has_year and has_authors:
        return str(doc_id), "skipped"

    update: Dict[str, Any] = {}

    # Always set year from filename if not present
    if (not has_year or force) and year_parsed:
        update["year"] = year_parsed

    # Always parse authors from filename if not present
    if (not has_authors or force) and authors_raw:
        update["authors"] = _parse_authors(authors_raw)

    # CrossRef lookup if we have a paper title
    if paper_title and (not has_doi or force):
        async with SEM:
            cr_item = await crossref_lookup(http, paper_title, year_parsed)
        if cr_item:
            # Verify title similarity to avoid false matches
            cr_titles = cr_item.get("title") or [""]
            cr_title = cr_titles[0] if cr_titles else ""
            sim = _title_similarity(paper_title, cr_title)
            if sim >= 0.35:
                doi = cr_item.get("DOI", "").lower().strip()
                if doi:
                    update["doi"] = doi
                # Authors from CrossRef are more precise
                cr_authors = _extract_authors(cr_item)
                if cr_authors and (not has_authors or force):
                    update["authors"] = cr_authors
                # Year
                cr_year = _extract_year(cr_item)
                if cr_year and (not has_year or force):
                    update["year"] = cr_year
                # References (DOI list)
                ref_dois = _extract_reference_dois(cr_item)
                if ref_dois:
                    update["references"] = ref_dois
                logger.debug(
                    "  %s sim=%.2f doi=%s refs=%d",
                    title_field[:50], sim, doi, len(ref_dois),
                )
            else:
                logger.debug(
                    "  %s — CrossRef title sim too low (%.2f): %r",
                    title_field[:50], sim, cr_title[:60],
                )

    if not update:
        return str(doc_id), "no_match"

    if dry_run:
        logger.info(
            "DRY-RUN %s: year=%s doi=%s authors=%s refs=%d",
            title_field[:60],
            update.get("year"),
            update.get("doi"),
            update.get("authors"),
            len(update.get("references", [])),
        )
        return str(doc_id), "dry_run"

    await db.documents.update_one({"_id": doc_id}, {"$set": update})
    return str(doc_id), "updated"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(
    limit: int,
    skip: int,
    concurrency: int,
    dry_run: bool,
    force: bool,
    mongodb_url: str,
    db_name: str,
) -> None:
    global SEM
    SEM = asyncio.Semaphore(concurrency)

    client = AsyncIOMotorClient(mongodb_url)
    db = client[db_name]

    query: Dict[str, Any] = {"source_type": "pdf_local"}
    if not force:
        # Only process docs that are missing at least one field
        query["$or"] = [
            {"doi": None},
            {"year": None},
            {"authors": {"$size": 0}},
        ]

    total = await db.documents.count_documents(query)
    logger.info(
        "Found %d pdf_local docs to enrich (limit=%d skip=%d force=%s dry_run=%s)",
        total, limit, skip, force, dry_run,
    )

    cursor = db.documents.find(query, skip=skip, limit=limit)
    docs = await cursor.to_list(length=limit or 10_000)

    counts = {"updated": 0, "skipped": 0, "no_title": 0, "no_match": 0, "dry_run": 0}
    start = time.time()

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as http:
        tasks = [enrich_one(doc, http, dry_run, force, db) for doc in docs]

        done = 0
        for coro in asyncio.as_completed(tasks):
            _, status = await coro
            counts[status] = counts.get(status, 0) + 1
            done += 1
            if done % 50 == 0:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                logger.info(
                    "  Progress: %d/%d (%.1f docs/s) updated=%d no_match=%d",
                    done, len(docs), rate, counts["updated"], counts["no_match"],
                )

    elapsed = time.time() - start
    logger.info(
        "Done in %.1fs — updated=%d skipped=%d no_match=%d dry_run=%d",
        elapsed, counts["updated"], counts["skipped"], counts["no_match"], counts["dry_run"],
    )
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich pdf_local document metadata via filename parsing + CrossRef"
    )
    parser.add_argument("--limit", type=int, default=0, help="Max docs to process (0=all)")
    parser.add_argument("--skip", type=int, default=0, help="Skip first N docs")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent CrossRef requests")
    parser.add_argument("--dry-run", action="store_true", help="Print updates without writing")
    parser.add_argument("--force", action="store_true", help="Overwrite existing metadata")
    parser.add_argument(
        "--mongodb-url", default="mongodb://localhost:27017", help="MongoDB connection URL"
    )
    parser.add_argument("--db-name", default="advandeb", help="MongoDB database name")
    args = parser.parse_args()

    asyncio.run(
        run(
            limit=args.limit,
            skip=args.skip,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
            force=args.force,
            mongodb_url=args.mongodb_url,
            db_name=args.db_name,
        )
    )


if __name__ == "__main__":
    main()
