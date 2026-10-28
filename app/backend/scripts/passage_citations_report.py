#!/usr/bin/env python3
"""Report which elicitation evidence passages can carry a full citation.

Read-only. Writes ``passage_citations.json``, ``unresolved_citations.csv``,
``doi_check.csv``, ``citation_corrections.json`` and ``summary.txt`` to
``scripts/out/`` and nothing anywhere else; the corrections file is a list of
proposals and this script never applies it.

Why this exists. Experts in the elicitation see evidence passages, and each
passage should be shown with a full bibliographic citation (authors, year,
title, DOI). The frozen evidence-set artefact does not carry one: DEB passages
name their source only by Zotero folder number and PDF file name ("2801",
"Kooy93.pdf"), and reproduction passages carry an OpenAlex work id plus a
title and DOI but no authors. This script finds out how far the knowledge
base already closes that gap, and proposes candidates for the rest so the
team only has to confirm, not search.

How a passage is resolved. A DEB passage joins ``documents`` on
``source_type == 'pdf_local' AND source_path == "<document_id>/<file>"``
(``document_meta`` mirrors those rows under the same ``_key`` but has no
``source_path``, so it cannot be joined directly). When the folder differs,
the same file name elsewhere in the library is accepted only if its bytes
are identical. A reproduction passage joins ``documents`` on ``_key ==
document_id``; when that misses, on the DOI index. Every query filters on an
indexed field: ``documents`` holds ~3.9M OpenAlex stubs and must never be
scanned.

How candidates are found. For a DEB document that is not fully described,
the file name is parsed (the DEB bibliography convention "KooyNisb2000" =
Kooijman & Nisbet 2000, or Zotero's "Author et al. - 2007 - Title.pdf"), the
first page of the PDF is read for a DOI and for the title block, and
OpenAlex and Crossref are asked. A candidate is scored on author, year and
title agreement, and is marked as the best guess only when it is clearly
right; anything less is left for a person. No key-to-reference DEB
bibliography exists on disk; the methods paper's verified ``references.bib``
is used as an extra local source. Reproduction documents get their authors
(and missing DOIs) from OpenAlex by work id.

Why DOIs are checked. Some DOIs stored on curated papers are wrong — an IEEE
Transactions on Magnetics DOI on Kooijman's 1993 book, a junk "/c3" suffix on
another — and a wrong DOI link is worse than none. Every DEB record's DOI,
and a sample of reproduction DOIs, is resolved (Crossref, then OpenAlex,
then DataCite) and compared with the stored title, year and first author.
Stored values are normalised first: many fields hold the strings 'None',
'True' or "['A', 'B']" instead of null, booleans or lists.

External APIs are called sequentially, at most ~4 requests per second, with
retries, a plain User-Agent and no e-mail address. Responses are cached in
``scripts/out/http_cache.json`` so re-runs are fast and give the same output;
``--refresh-cache`` ignores the cache, ``--no-external`` skips the APIs and
reports what ArangoDB alone provides.

Usage (from app/backend/):

    conda run -n advandeb python scripts/passage_citations_report.py
    conda run -n advandeb python scripts/passage_citations_report.py --no-external
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
import warnings
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

EVIDENCE_PATH = Path("/home/adeb/dev/advandeb_methods/data/evidence/evidence_sets_v1.0.json")
DEB_LIBRARY = Path("/home/adeb/DEB_library")
METHODS_BIB = Path("/home/adeb/dev/advandeb_methods/paper/references.bib")
OUT_DIR = Path(__file__).resolve().parent / "out"
CACHE_PATH = OUT_DIR / "http_cache.json"

USER_AGENT = "advandeb-citation-report/1.0"
OPENALEX = "https://api.openalex.org"
CROSSREF = "https://api.crossref.org"
MIN_INTERVAL_S = 0.25  # ~4 requests per second, sequential
REP_SAMPLE = 50  # reproduction documents whose DOI is checked against Crossref
FAILED_DOI = ("doi_mismatch", "doi_unresolvable", "doi_malformed")
OA_SELECT = "id,doi,title,publication_year,authorships,primary_location,biblio,type"
CR_SELECT = "DOI,title,author,issued,container-title,volume,issue,page,type,publisher"

# OpenAlex/Crossref work types that are never the cited work itself.
BAD_TYPES = {"book-review", "erratum", "paratext", "peer-review", "retraction", "grant", "component"}
NAME_PARTICLES = {"van", "der", "den", "de", "von", "la", "le", "du", "da", "di",
                  "del", "dos", "das", "ten", "ter", "et", "al", "and"}

log = logging.getLogger("passage_citations")


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_NON_DECOMPOSING = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
                                   "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "ı": "i", "þ": "th"})


def fold(s: Optional[str]) -> str:
    """Lower-case, accent-free, HTML-tag-free text."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s).translate(_NON_DECOMPOSING)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def squash(s: Optional[str]) -> str:
    """Letters and digits only — robust to the spacing damage in PDF-extracted titles."""
    return re.sub(r"[^a-z0-9]", "", fold(s))


def bare_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = str(doi).strip()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", d, flags=re.I)
    return d.lower() or None


def clean_value(v: Any) -> Any:
    """Undo stringified Python values in Arango records ('None', 'True', "['a', 'b']")."""
    if isinstance(v, str):
        s = v.strip()
        if s in ("", "None", "null", "nan", "NaN"):
            return None
        if s in ("True", "true"):
            return True
        if s in ("False", "false"):
            return False
        if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
            try:
                return clean_value(ast.literal_eval(s))
            except Exception:
                return v
        return v
    if isinstance(v, list):
        return [x for x in (clean_value(x) for x in v) if x not in (None, "")]
    if isinstance(v, dict):
        return {k: clean_value(x) for k, x in v.items()}
    return v


def clean_record(r: dict) -> dict:
    out = clean_value(dict(r))
    if isinstance(out.get("authors"), str):
        out["authors"] = [out["authors"]]
    if isinstance(out.get("year"), str) and out["year"].isdigit():
        out["year"] = int(out["year"])
    return out


DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
JUNK_SUFFIX_RE = re.compile(
    r"(/(c\d+|abstract|full|pdf|epdf|html?|summary|fulltext|references|suppinfo)|\.(pdf|html?)|[.,;:>]+)$",
    re.I)


PII_RE = re.compile(r"^(S?)(\d{4}-\d{3}[\dX])\((\d{2})\)(\d{5}-[\dX])$", re.I)


def doi_shape(doi: str) -> tuple[str, list[str]]:
    """Return a repaired DOI (junk suffixes, stray spaces, Elsevier PIIs) and what was wrong."""
    d = bare_doi(doi) or ""
    problems = []
    if not DOI_RE.match(d):
        problems.append("fails ^10.\\d{4,9}/\\S+$")
    if re.search(r"\s", d):
        problems.append("whitespace inside")
        d = re.sub(r"\s+", "", d)
    pm = PII_RE.match(d)
    if pm:  # an Elsevier PII stored in place of its DOI
        problems.append("Elsevier PII, not a DOI")
        d = f"10.1016/s{pm.group(2)}({pm.group(3)}){pm.group(4)}".lower()
    c = d
    while c and JUNK_SUFFIX_RE.search(c):
        c2 = JUNK_SUFFIX_RE.sub("", c)
        if c2 == c:
            break
        problems.append(f"junk suffix '{c[len(c2):]}'")
        c = c2
    for o, cl in (("(", ")"), ("[", "]")):  # an unbalanced closing bracket is extraction debris
        while c.endswith(cl) and c.count(cl) > c.count(o):
            c = c[:-1]
            problems.append(f"unbalanced '{cl}'")
    return c, problems


def title_similarity(ref: Optional[str], cand: Optional[str], prefix: bool = False) -> float:
    """Similarity of a candidate title to a reference title, in [0, 1].

    ``prefix`` compares only the first len(ref) characters of the candidate —
    Zotero truncates titles in file names.
    """
    a, b = squash(ref), squash(cand)
    if not a or not b:
        return 0.0
    if prefix:
        b = b[: len(a)]
    r = SequenceMatcher(None, a, b, autojunk=False).ratio()
    if min(len(a), len(b)) >= 15 and (a in b or b in a):
        r = max(r, 0.95)
    return round(r, 3)


def head_containment(head_sq: str, cand: Optional[str]) -> float:
    """How much of a candidate title appears in the PDF's first page text."""
    t = squash(cand)
    if not t or not head_sq:
        return 0.0
    if len(t) >= 20 and t in head_sq:
        return 1.0
    words = [w for w in re.findall(r"[a-z0-9]+", fold(cand)) if len(w) >= 4]
    if not words:
        return 0.0
    frac = sum(1 for w in words if w in head_sq) / len(words)
    return round(min(frac, 0.8), 3)  # word overlap alone is never conclusive


def name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]+", fold(name)) if len(t) >= 2 and t not in NAME_PARTICLES]


def surname_of(name: str) -> str:
    """Best-effort family name of a display name ("S.A.L.M. Kooijman", "O, DIEKMANN")."""
    if "," in name:
        left = name.split(",", 1)[0]
        toks = name_tokens(left)
        if toks and len(toks[-1]) > 2:
            return toks[-1]
    toks = name_tokens(name)
    return toks[-1] if toks else ""


def name_matches(ref: str, kind: str, name: str) -> bool:
    """Does an author display name match a reference surname (``kind`` 'prefix' or 'full')?"""
    key = squash(ref)
    if not key:
        return False
    for tok in name_tokens(name):
        variants = {tok, tok.replace("ij", "y")}
        for v in variants:
            if kind == "prefix" and v.startswith(key):
                return True
            if kind == "full" and (v == key or (len(key) >= 4 and v.startswith(key))):
                return True
    # Compound surnames ("Flores Valiente", "Enriquez-Urzelai") squashed together.
    sq = squash(name)
    return kind == "full" and len(key) >= 5 and key in sq


def fmt_authors(authors: list[str]) -> str:
    if not authors:
        return "[authors missing]"
    if len(authors) > 3:
        return ", ".join(authors[:3]) + " et al."
    return ", ".join(authors)


def fmt_citation(c: dict) -> str:
    parts = [f"{fmt_authors(c.get('authors') or [])} ({c.get('year') or 'n.d.'}). "
             f"{(c.get('title') or '[title missing]').strip()}."]
    venue = c.get("journal") or c.get("publisher")
    if venue:
        v = venue
        if c.get("volume"):
            v += f" {c['volume']}"
            if c.get("issue"):
                v += f"({c['issue']})"
        if c.get("pages"):
            v += f": {c['pages']}"
        parts.append(v + ".")
    if c.get("doi"):
        parts.append(f"https://doi.org/{c['doi']}")
    return re.sub(r"<[^>]+>", "", " ".join(parts))


# ---------------------------------------------------------------------------
# HTTP with polite pacing and a response cache
# ---------------------------------------------------------------------------

_CR_KEEP = ("DOI", "title", "author", "issued", "published-print", "published-online", "created",
            "container-title", "volume", "issue", "page", "type", "publisher")


def _shrink_crossref(it: dict) -> dict:
    out = {k: it[k] for k in _CR_KEEP if k in it}
    if "author" in out:
        out["author"] = [{k: a[k] for k in ("given", "family", "name") if k in a} for a in out["author"]]
    return out


def _shrink_openalex(w: dict) -> dict:
    out = dict(w)
    out["authorships"] = [{"author": {"display_name": (a.get("author") or {}).get("display_name")},
                           "raw_author_name": a.get("raw_author_name")} for a in w.get("authorships") or []]
    src = ((w.get("primary_location") or {}).get("source") or {})
    out["primary_location"] = {"source": {"display_name": src.get("display_name"),
                                          "host_organization_name": src.get("host_organization_name")}}
    return out


def shrink(url: str, data: Any) -> Any:
    """Keep only the fields this script reads, so the response cache stays small."""
    if not isinstance(data, dict):
        return data
    if url.startswith(CROSSREF):
        msg = data.get("message")
        if isinstance(msg, dict) and "items" in msg:
            return {"message": {"items": [_shrink_crossref(i) for i in msg["items"]]}}
        if isinstance(msg, dict):
            return {"message": _shrink_crossref(msg)}
    if url.startswith(OPENALEX):
        if "results" in data:
            return {"results": [_shrink_openalex(w) for w in data["results"]]}
        if "id" in data:
            return _shrink_openalex(data)
    if "api.datacite.org" in url and isinstance(data.get("data"), dict):
        a = data["data"].get("attributes") or {}
        return {"data": {"attributes": {k: a.get(k) for k in
                                        ("doi", "titles", "creators", "publicationYear", "publisher", "types")}}}
    return data


def _long_wait(r) -> bool:
    ra = r.headers.get("Retry-After") or ""
    return (ra.isdigit() and int(ra) > 120) or "budget" in r.text.lower()


class Http:
    """Sequential, paced, retrying JSON client; caches trimmed responses on disk."""

    def __init__(self, enabled: bool, refresh: bool):
        self.enabled = enabled
        self.cache: dict[str, Any] = {}
        if enabled and not refresh and CACHE_PATH.exists():
            try:
                self.cache = {k: shrink(k, v) for k, v in json.loads(CACHE_PATH.read_text()).items()}
            except Exception:
                self.cache = {}
        self.client = None
        self.last = 0.0
        self.n_requests = 0
        self.n_failures = 0
        self.n_skipped = 0
        self.disabled: set[str] = set()
        if enabled:
            import httpx
            self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=40,
                                       follow_redirects=True)

    def get(self, url: str, params: Optional[dict] = None) -> Any:
        """Return parsed JSON, ``None`` for 404, or raise after exhausted retries."""
        if not self.enabled:
            return None
        key = url + ("?" + urlencode(sorted((params or {}).items())) if params else "")
        if key in self.cache:
            return self.cache[key]
        if url in self.disabled:
            self.n_skipped += 1
            return None
        delay = 1.0
        for attempt in range(6):
            wait = MIN_INTERVAL_S - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.n_requests += 1
            try:
                r = self.client.get(url, params=params)
            except Exception as exc:  # network error: back off and retry
                log.warning("GET %s failed (%s), retry in %.0fs", url, type(exc).__name__, delay)
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if r.status_code == 200:
                data = shrink(url, r.json())
                self.cache[key] = data
                return data
            if r.status_code == 404:
                self.cache[key] = None
                return None
            if r.status_code == 429 and _long_wait(r):
                # A daily budget is used up (OpenAlex without a key): stop asking this
                # endpoint for the rest of the run; nothing is cached, a later re-run fills it.
                if url not in self.disabled:
                    log.warning("GET %s -> 429 with a long Retry-After: budget exhausted, "
                                "skipping this endpoint for the rest of the run", url)
                self.disabled.add(url)
                self.n_skipped += 1
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                ra = r.headers.get("Retry-After")
                pause = float(ra) if ra and ra.isdigit() else delay
                log.warning("GET %s -> %s, retry in %.0fs", url, r.status_code, pause)
                time.sleep(min(pause, 60))
                delay = min(delay * 2, 30)
                continue
            log.warning("GET %s -> %s (not retried)", url, r.status_code)
            self.n_failures += 1
            return None
        self.n_failures += 1
        log.warning("GET %s gave up after retries", url)
        return None

    def save(self) -> None:
        if not self.enabled:
            return
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, sort_keys=True))
        os.replace(tmp, CACHE_PATH)


# --- normalizers ------------------------------------------------------------

def norm_openalex(w: dict) -> dict:
    b = w.get("biblio") or {}
    pl = w.get("primary_location") or {}
    src = pl.get("source") or {}
    pages = None
    if b.get("first_page"):
        pages = b["first_page"] + (f"-{b['last_page']}" if b.get("last_page") and b["last_page"] != b["first_page"] else "")
    return {
        "source": "openalex",
        "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1] or None,
        "doi": bare_doi(w.get("doi")),
        "title": w.get("title"),
        "authors": [a.get("author", {}).get("display_name") or a.get("raw_author_name") or ""
                    for a in (w.get("authorships") or [])],
        "year": w.get("publication_year"),
        "journal": src.get("display_name"),
        "publisher": src.get("host_organization_name"),
        "volume": b.get("volume"),
        "issue": b.get("issue"),
        "pages": pages,
        "type": w.get("type"),
    }


def norm_crossref(it: dict) -> dict:
    year = None
    for k in ("issued", "published-print", "published-online", "created"):
        dp = (it.get(k) or {}).get("date-parts") or []
        if dp and dp[0] and dp[0][0]:
            year = dp[0][0]
            break
    authors = []
    for a in it.get("author") or []:
        nm = " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name") or ""
        authors.append(nm)
    ct = it.get("container-title") or []
    return {
        "source": "crossref",
        "openalex_id": None,
        "doi": bare_doi(it.get("DOI")),
        "title": (it.get("title") or [None])[0],
        "authors": authors,
        "year": year,
        "journal": ct[0] if ct else None,
        "publisher": it.get("publisher"),
        "volume": it.get("volume"),
        "issue": it.get("issue"),
        "pages": it.get("page"),
        "type": it.get("type"),
    }


class Lookup:
    """OpenAlex / Crossref queries returning normalized work dicts."""

    def __init__(self, http: Http):
        self.http = http

    # Single-work OpenAlex lookups are free; list and search queries draw on a small
    # daily budget shared by the whole IP address, so they are used only for search.
    def openalex_by_ids(self, ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for n_done, wid in enumerate(ids, 1):
            w = self.http.get(f"{OPENALEX}/works/{wid}", {"select": OA_SELECT})
            if w and w.get("id"):
                n = norm_openalex(w)
                if n["openalex_id"] != wid:
                    n["redirected_from"] = wid
                out[wid] = n
            if n_done % 100 == 0:
                self.http.save()
                print(f"  openalex ids {n_done}/{len(ids)}", file=sys.stderr)
        return out

    def by_dois(self, dois: list[str]) -> dict[str, dict]:
        """OpenAlex single-work lookups; Crossref for DOIs OpenAlex does not know."""
        out: dict[str, dict] = {}
        for d in dois:
            w = self.http.get(f"{OPENALEX}/works/doi:{quote(d, safe='/')}", {"select": OA_SELECT})
            if w and w.get("id"):
                out[d] = norm_openalex(w)
                continue
            data = self.http.get(f"{CROSSREF}/works/{quote(d, safe='/')}")
            if data and data.get("message"):
                out[d] = norm_crossref(data["message"])
        return out

    def crossref_author_year(self, surname: str, year: int, text: str, rows: int = 10) -> list[dict]:
        params = {"query.author": surname, "rows": rows, "select": CR_SELECT,
                  "filter": f"from-pub-date:{year - 1},until-pub-date:{year + 1}"}
        q = " ".join(text.split()[:30])
        if q:
            params["query.bibliographic"] = q
        data = self.http.get(f"{CROSSREF}/works", params)
        return [norm_crossref(it) for it in ((data or {}).get("message") or {}).get("items", [])]

    def resolve_doi(self, doi: str) -> Optional[dict]:
        """Crossref first, then OpenAlex, then DataCite; ``None`` when no agency knows the DOI."""
        data = self.http.get(f"{CROSSREF}/works/{quote(doi, safe='/')}")
        if data and data.get("message"):
            return norm_crossref(data["message"])
        w = self.http.get(f"{OPENALEX}/works/doi:{quote(doi, safe='/')}", {"select": OA_SELECT})
        if w and w.get("id"):
            return norm_openalex(w)
        dc = self.http.get(f"https://api.datacite.org/dois/{quote(doi, safe='/')}")
        if dc and dc.get("data"):
            a = dc["data"].get("attributes") or {}
            return {"source": "datacite", "openalex_id": None, "doi": bare_doi(a.get("doi")),
                    "title": ((a.get("titles") or [{}])[0]).get("title"),
                    "authors": [c.get("name") or "" for c in a.get("creators") or []],
                    "year": a.get("publicationYear"), "journal": a.get("publisher"),
                    "publisher": a.get("publisher"), "volume": None, "issue": None, "pages": None,
                    "type": ((a.get("types") or {}).get("resourceTypeGeneral") or "").lower()}
        return None

    def openalex_author_year(self, surname: str, year: int) -> list[dict]:
        data = self.http.get(f"{OPENALEX}/works", {
            "filter": f"raw_author_name.search:{surname},publication_year:{year - 1}-{year + 1}",
            "per-page": 50, "select": OA_SELECT})
        return [norm_openalex(w) for w in (data or {}).get("results", [])]

    def openalex_search(self, text: str, n: int = 5) -> list[dict]:
        q = re.sub(r"[^\w\s-]", " ", text)
        q = " ".join(q.split()[:30])
        if not q:
            return []
        data = self.http.get(f"{OPENALEX}/works", {"search": q, "per-page": n, "select": OA_SELECT})
        return [norm_openalex(w) for w in (data or {}).get("results", [])]

    def crossref_search(self, text: str, rows: int = 3) -> list[dict]:
        q = " ".join(text.split()[:40])
        if not q:
            return []
        data = self.http.get(f"{CROSSREF}/works", {
            "query.bibliographic": q, "rows": rows, "select": CR_SELECT})
        return [norm_crossref(it) for it in ((data or {}).get("message") or {}).get("items", [])]


# ---------------------------------------------------------------------------
# Local sources: file names, PDFs, the methods-paper bibliography
# ---------------------------------------------------------------------------

KEY_RE = re.compile(r"^(?P<alpha>[A-Za-z]+?)(?P<year>\d{4}|\d{2})(?P<letter>[a-z]?)(?:_(?P<part>[A-Za-z0-9]+))?\.pdf$")
ZOTERO_RE = re.compile(r"^(?P<authors>.+?) - (?P<year>\d{4}) - (?P<title>.+?)\.pdf$")


def parse_filename(fname: str) -> dict:
    """Read author/year/title hints from a DEB library file name."""
    m = KEY_RE.match(fname)
    if m:
        alpha = m["alpha"]
        if len(alpha) % 4 == 0:
            parts = [alpha[i:i + 4] for i in range(0, len(alpha), 4)]
        else:
            parts = re.findall(r"[A-Z][a-z]*", alpha) or [alpha]
        y = int(m["year"])
        if y < 100:
            y += 1900 if y >= 30 else 2000
        return {"style": "deb_key", "surnames": parts, "surname_kind": "prefix", "year": y,
                "title_prefix": None, "part": m["part"], "letter": m["letter"] or None}
    m = ZOTERO_RE.match(fname)
    if m:
        auth = re.sub(r"\s+(et al|e\.\s?a)\.?", "", m["authors"])
        names = [a.strip() for a in re.split(r"\s(?:and|og|en|und|et|y|i)\s|&|,", auth) if a.strip()]
        return {"style": "zotero", "surnames": names, "surname_kind": "full", "year": int(m["year"]),
                "title_prefix": m["title"], "part": None, "letter": None}
    ym = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", fname)
    words = [w for w in re.split(r"[_\-\s.]+", fname[:-4]) if w.isalpha() and len(w) >= 3]
    caps = [w.capitalize() for w in words if w.isupper()]
    return {"style": "other", "surnames": [" ".join(caps)] if caps else [], "surname_kind": "full",
            "year": int(ym.group(0)) if ym else None, "title_prefix": None, "part": None, "letter": None}


def read_pdf_head(path: Path) -> tuple[str, list[str]]:
    """First-page text (second page too when the first is a cover) and DOIs on page 1."""
    try:
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = PdfReader(str(path))
            p1 = reader.pages[0].extract_text() or "" if reader.pages else ""
            text = p1
            if len(p1) < 400 and len(reader.pages) > 1:
                text += "\n" + (reader.pages[1].extract_text() or "")
    except Exception as exc:
        log.warning("could not read %s: %s", path.name, type(exc).__name__)
        return "", []
    dois = []
    for d in re.findall(r"10\.\d{4,9}/[^\s\"<>]+", text):
        d = d.rstrip(".,;:)]}").lower()
        if d not in dois:
            dois.append(d)
    return re.sub(r"\s+", " ", text)[:4000], dois[:3]


def full_surname_from_text(prefix: str, *texts: str) -> Optional[str]:
    """Find the capitalised word that a 4-letter DEB key prefix abbreviates ("Kooy" -> "Kooijman")."""
    key = prefix.lower()
    counts: Counter = Counter()
    for text in texts:
        for w in re.findall(r"[A-Za-zÀ-ÿ'-]{3,}", text or ""):
            if not w[0].isupper():
                continue
            f = fold(w)
            if f.startswith(key) or f.replace("ij", "y").startswith(key):
                counts[w if not w.isupper() else w.capitalize()] += 1
    return counts.most_common(1)[0][0] if counts else None


def _strip_latex(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = re.sub(r"\\.", "", s)
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "")).strip()


def load_methods_bib() -> list[dict]:
    """Parse the methods paper's verified BibTeX into normalized works (tiny ad-hoc parser)."""
    if not METHODS_BIB.exists():
        return []
    text = METHODS_BIB.read_text(errors="ignore")
    works = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        i, depth, start = m.end(), 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        body = text[start:i - 1]
        fields: dict[str, str] = {}
        for fm in re.finditer(r"(\w+)\s*=\s*", body):
            j = fm.end()
            if j < len(body) and body[j] == "{":
                d, k = 1, j + 1
                while k < len(body) and d:
                    d += {"{": 1, "}": -1}.get(body[k], 0)
                    k += 1
                fields.setdefault(fm.group(1).lower(), _strip_latex(body[j + 1:k - 1]))
            else:
                vm = re.match(r"\"([^\"]*)\"|(\d+)", body[j:])
                if vm:
                    fields.setdefault(fm.group(1).lower(), vm.group(1) or vm.group(2))
        if "title" not in fields:
            continue
        yr = re.search(r"\d{4}", fields.get("year", ""))
        works.append({
            "source": "methods_bib", "bib_key": m.group(2), "openalex_id": None,
            "doi": bare_doi(fields.get("doi")), "title": fields["title"],
            "authors": [a.strip() for a in fields.get("author", "").split(" and ") if a.strip()],
            "year": int(yr.group(0)) if yr else None,
            "journal": fields.get("journal") or fields.get("booktitle"),
            "publisher": fields.get("publisher"), "volume": fields.get("volume"),
            "issue": fields.get("number"), "pages": fields.get("pages"),
            "type": m.group(1).lower(),
        })
    return works


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Classification and scoring
# ---------------------------------------------------------------------------

def is_real_title(title: Optional[str], fname: Optional[str]) -> bool:
    if not title or not title.strip():
        return False
    t = title.strip()
    if t.lower().endswith(".pdf"):
        return False
    if fname and squash(t) == squash(fname[:-4] if fname.lower().endswith(".pdf") else fname):
        return False
    return len(squash(t)) >= 8


def classify(rec: Optional[dict], fname: Optional[str] = None) -> tuple[str, list[str]]:
    """full / partial / unresolved, plus the list of missing fields."""
    if not rec:
        return "unresolved", ["record"]
    missing = [f for f in ("authors", "year", "doi") if not rec.get(f)]
    if not is_real_title(rec.get("title"), fname):
        return "unresolved", ["title"] + missing
    if not missing:
        return "full", []
    if rec.get("year") or rec.get("authors"):
        return "partial", missing
    return "unresolved", missing


def score_candidate(c: dict, ref: dict) -> dict:
    """Score a candidate work against what is known about a document."""
    # author
    a = None
    sn, kind = ref.get("surnames") or [], ref.get("surname_kind")
    authors = [x for x in (c.get("authors") or []) if x]
    if sn and authors:
        first = name_matches(sn[0], kind, authors[0])
        anywhere = any(name_matches(sn[0], kind, x) for x in authors)
        a = 1.0 if first else (0.6 if anywhere else 0.0)
        if len(sn) > 1 and a > 0 and not any(name_matches(sn[1], kind, x) for x in authors[1:]):
            a -= 0.2
    elif authors and ref.get("head_sq"):
        a = 0.8 if surname_of(authors[0]) and squash(surname_of(authors[0])) in ref["head_sq"] else 0.0
    # year
    y = None
    if ref.get("year") and c.get("year"):
        dy = abs(int(ref["year"]) - int(c["year"]))
        y = 1.0 if dy == 0 else (0.5 if dy == 1 else 0.0)
    # title
    ts = []
    if ref.get("title"):
        ts.append(title_similarity(ref["title"], c.get("title")))
    if ref.get("title_prefix"):
        ts.append(title_similarity(ref["title_prefix"], c.get("title"), prefix=True))
    if ref.get("head_sq") and not ts:
        # Only without a stored title: a thesis's front matter lists its papers' titles.
        ts.append(head_containment(ref["head_sq"], c.get("title")))
    t = max(ts) if ts else None
    doi_hit = bool(c.get("doi") and c["doi"] in (ref.get("known_dois") or []))

    weights = {"author": 0.35, "year": 0.2, "title": 0.45}
    vals = {"author": a, "year": y, "title": t}
    num = sum(weights[k] * v for k, v in vals.items() if v is not None)
    den = sum(weights[k] for k, v in vals.items() if v is not None)
    score = num / den if den else 0.0
    if doi_hit:
        score = min(1.0, score + 0.15)
    bad_type = (c.get("type") or "") in BAD_TYPES
    if bad_type:
        score *= 0.5

    high = not bad_type and (
        (t is not None and t >= 0.85 and (a is None or a >= 0.6) and (y is None or y >= 0.5)
         and not (a is None and y is None))
        or (doi_hit and (a or 0) >= 0.6 and (y or 0) >= 0.5)
    )
    if high and ref.get("companion"):
        high = False  # derivative documents (comments, notation, ...) are never auto-matched
    conf = "high" if high else ("medium" if score >= 0.6 and (t is None or t >= 0.6) else "low")
    return {"author": a, "year": y, "title": t, "doi_match": doi_hit,
            "score": round(score, 3), "confidence": conf}


def brief(w: Optional[dict]) -> Optional[dict]:
    if not w:
        return None
    return {"source": w.get("source"), "doi": w.get("doi"), "title": w.get("title"), "year": w.get("year"),
            "first_author": (w.get("authors") or [None])[0], "type": w.get("type")}


def judge_work(w: dict, ref: dict) -> dict:
    """Does a resolved DOI describe the document? Compares title, year and first author."""
    sim = title_similarity(ref["title"], w.get("title")) if ref.get("title") else None
    ydiff = abs(int(ref["year"]) - int(w["year"])) if ref.get("year") and w.get("year") else None
    authors = [a for a in (w.get("authors") or []) if a]
    amatch = None
    if ref.get("surnames") and authors:
        amatch = any(name_matches(ref["surnames"][0], ref["surname_kind"], a) for a in authors[:3])
    if sim is not None:
        ok = sim >= 0.75 or (sim >= 0.5 and (ydiff is None or ydiff <= 1) and amatch is not False)
    elif amatch is not None or ydiff is not None:
        ok = amatch is not False and (ydiff is None or ydiff <= 1)
    else:
        ok = None
    # The file name is independent evidence: a DOI whose work contradicts it on both
    # author and year is wrong even when the stored title agrees with it.
    fp = ref.get("file")
    file_note = None
    if ok and fp and fp.get("surnames") and fp.get("year") and authors and fp["style"] != "other":
        fa = any(name_matches(fp["surnames"][0], fp["surname_kind"], a) for a in authors[:3])
        fy = w.get("year") and abs(int(fp["year"]) - int(w["year"])) <= 1
        if not fa and not fy:
            ok = False
            file_note = "resolved work contradicts the file name (author and year)"
    return {"ok": ok, "title_similarity": sim, "year_diff": ydiff, "author_match": amatch, "note": file_note}


def check_doi(look: "Lookup", stored_doi: Any, ref: dict) -> dict:
    """Classify a stored DOI: doi_ok / doi_mismatch / doi_unresolvable / doi_malformed / doi_unverified."""
    raw = bare_doi(str(stored_doi)) or ""
    cleaned, problems = doi_shape(raw)
    out: dict[str, Any] = {"stored_doi": stored_doi, "problems": problems, "resolved": None,
                           "judgement": None, "status": None, "proposed_doi": None,
                           "proposal_confidence": None, "proposal_note": None}
    w = look.resolve_doi(raw) if DOI_RE.match(raw) else None
    out["resolved"] = brief(w)
    out["work"] = w
    j = judge_work(w, ref) if w else None
    out["judgement"] = j
    if problems:
        out["status"] = "doi_malformed"
        if cleaned and cleaned != raw and DOI_RE.match(cleaned):
            wc = look.resolve_doi(cleaned)
            jc = judge_work(wc, ref) if wc else None
            out["resolved_cleaned"] = brief(wc)
            if jc and jc["ok"]:
                out["proposed_doi"], out["proposal_confidence"] = cleaned, "high"
                out["proposal_note"] = "stored DOI with the junk suffix removed; resolves to this work"
    elif w is None:
        out["status"] = "doi_unresolvable"
    elif j["ok"] is None:
        out["status"] = "doi_unverified"
    else:
        out["status"] = "doi_ok" if j["ok"] else "doi_mismatch"
    return out


def dedup(cands: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for c in cands:
        k = c.get("doi") or f"{squash(c.get('title'))[:80]}|{c.get('year')}"
        if k in seen:
            srcs = seen[k].setdefault("also_from", [])
            if c["source"] != seen[k]["source"] and c["source"] not in srcs:
                srcs.append(c["source"])
            for f in ("authors", "journal", "volume", "issue", "pages", "publisher", "openalex_id"):
                if not seen[k].get(f) and c.get(f):
                    seen[k][f] = c[f]
        else:
            seen[k] = dict(c)
    return list(seen.values())


def pick_best(cands: list[dict]) -> Optional[dict]:
    """Best guess only when one work is clearly right."""
    highs = [c for c in cands if c["scores"]["confidence"] == "high"]
    if not highs:
        return None
    highs.sort(key=lambda c: (-c["scores"]["score"], c.get("doi") is None))
    top = highs[0]
    for other in highs[1:]:
        if other["scores"]["score"] < top["scores"]["score"] - 0.05:
            break
        a, b = squash(top.get("title")), squash(other.get("title"))
        same_work = a and b and (a in b or b in a) and top.get("year") == other.get("year")
        if not same_work and (other.get("doi") != top.get("doi") or not top.get("doi")):
            return None  # two different works fit equally well
    # Among duplicates of the same work prefer one carrying a DOI.
    if not top.get("doi"):
        for other in highs[1:]:
            a, b = squash(top.get("title")), squash(other.get("title"))
            if other.get("doi") and a and b and (a in b or b in a):
                return other
    return top


CAND_FIELDS = ("source", "also_from", "doi", "openalex_id", "bib_key", "title", "authors", "year",
               "journal", "publisher", "volume", "issue", "pages", "type")


def slim(c: dict) -> dict:
    out = {k: c.get(k) for k in CAND_FIELDS if c.get(k) not in (None, [], "")}
    out["citation"] = fmt_citation(c)
    out["scores"] = c["scores"]
    return out


# ---------------------------------------------------------------------------
# Main work
# ---------------------------------------------------------------------------

def load_passages() -> tuple[dict, dict]:
    data = json.loads(EVIDENCE_PATH.read_text())
    docs: dict[tuple, dict] = {}
    totals: Counter = Counter()
    for s in data["sets"]:
        if s["corpus_id"] == "combined":
            continue
        for p in s["passages"]:
            corpus = p["corpus"]
            totals[corpus] += 1
            k = (corpus, p["document_id"])
            d = docs.setdefault(k, {"corpus": corpus, "document_id": p["document_id"],
                                    "stored_title": p.get("title"), "stored_doi": p.get("doi"),
                                    "stored_year": p.get("year"), "n_passages": 0, "_sets": set(),
                                    "_texts": []})
            d["n_passages"] += 1
            d["_sets"].add(s["evidence_set_id"])
            if len(d["_texts"]) < 3:
                d["_texts"].append(p.get("text") or "")
    meta = {"manifest": data.get("manifest", {}), "totals": dict(totals),
            "artefact_sha256": sha256_file(EVIDENCE_PATH)}
    return docs, meta


DOC_FIELDS = """{_key: d._key, title: d.title, authors: d.authors, year: d.year, journal: d.journal,
  doi: d.doi, openalex_id: d.openalex_id, volume: d.volume, issue: d.issue, pages: d.pages,
  pmid: d.pmid, source_type: d.source_type, source_path: d.source_path}"""


def arango_fetch(arango, docs: list[dict]) -> None:
    """Attach the matching Arango record (and the join rule that found it) to each doc."""
    deb = [d for d in docs if d["corpus"] == "deb"]
    rep = [d for d in docs if d["corpus"] == "reproduction"]

    # --- DEB: exact source_path ------------------------------------------------
    paths = {f"{d['document_id']}/{d['stored_title']}": d for d in deb}
    rows = arango.aql(f"""FOR d IN documents FILTER d.source_type == 'pdf_local'
        AND d.source_path IN @paths RETURN {DOC_FIELDS}""", {"paths": list(paths)})
    for r in rows:
        paths[r["source_path"]]["arango"] = r
        paths[r["source_path"]]["join_rule"] = "documents.source_path == '<document_id>/<file>' (source_type 'pdf_local')"
    # --- DEB fallback 1: any file in the same folder ---------------------------
    for d in deb:
        if d.get("arango"):
            continue
        rows = arango.aql(f"""FOR d IN documents FILTER d.source_type == 'pdf_local'
            AND STARTS_WITH(d.source_path, CONCAT(@id, '/')) RETURN {DOC_FIELDS}""",
                          {"id": d["document_id"]})
        if len(rows) == 1:
            d["arango"] = rows[0]
            d["join_rule"] = "documents.source_path folder prefix '<document_id>/'"
    # --- DEB fallback 2: same file name in another folder, identical bytes ------
    missing = [d for d in deb if not d.get("arango")]
    if missing:
        allp = arango.aql(f"""FOR d IN documents FILTER d.source_type == 'pdf_local'
            RETURN {DOC_FIELDS}""")
        by_name = defaultdict(list)
        for r in allp:
            by_name[(r["source_path"] or "").split("/", 1)[-1]].append(r)
        for d in missing:
            mine = DEB_LIBRARY / d["document_id"] / d["stored_title"]
            for r in by_name.get(d["stored_title"], []):
                other = DEB_LIBRARY / r["source_path"]
                if mine.exists() and other.exists() and sha256_file(mine) == sha256_file(other):
                    d["arango"] = r
                    d["join_rule"] = "documents.source_path same file name in another folder (identical sha256)"
                    d["notes"].append(f"duplicate PDF: ingested as {r['source_path']}")
                    break

    # --- document_meta mirror check (same _key) --------------------------------
    keys = [d["arango"]["_key"] for d in deb if d.get("arango")]
    metas = arango.aql("""FOR k IN @keys LET m = DOCUMENT('document_meta', k) FILTER m != null
        RETURN {_key: m._key, title: m.title, authors: m.authors, year: m.year, journal: m.journal, doi: m.doi}""",
                       {"keys": keys})
    mby = {m["_key"]: m for m in metas}
    for d in deb:
        if d.get("arango"):
            m = mby.get(d["arango"]["_key"])
            d["document_meta"] = ("absent" if m is None else
                                  "identical" if all(m.get(f) == d["arango"].get(f) for f in
                                                     ("title", "authors", "year", "journal", "doi"))
                                  else "differs")

    # --- reproduction: _key, then DOI index ------------------------------------
    rows = arango.aql(f"""FOR k IN @keys LET d = DOCUMENT('documents', k) FILTER d != null
        RETURN MERGE({DOC_FIELDS}, {{abstract: LEFT(d.abstract, 6000), content: LEFT(d.content, 6000)}})""",
                      {"keys": [d["document_id"] for d in rep]})
    byk = {r["_key"]: r for r in rows}
    for d in rep:
        r = byk.get(d["document_id"])
        if r:
            d["arango"] = r
            d["join_rule"] = "documents._key == document_id"
    miss = [d for d in rep if not d.get("arango") and bare_doi(d["stored_doi"])]
    if miss:
        variants = []
        for d in miss:
            b = bare_doi(d["stored_doi"])
            variants += [b, "https://doi.org/" + b]
        rows = arango.aql(f"""FOR d IN documents FILTER d.doi IN @dois
            RETURN MERGE({DOC_FIELDS}, {{abstract: LEFT(d.abstract, 6000), content: LEFT(d.content, 6000)}})""",
                          {"dois": variants})
        bydoi: dict[str, list] = defaultdict(list)
        for r in rows:
            bydoi[bare_doi(r["doi"])].append(r)
        for d in miss:
            hits = bydoi.get(bare_doi(d["stored_doi"]), [])
            if hits:
                hits.sort(key=lambda r: r["source_type"] != "pdf_local")
                d["arango"] = hits[0]
                d["join_rule"] = "documents.doi == passage doi (document_id not a documents._key)"
                if len(hits) > 1:
                    d["notes"].append(f"{len(hits)} documents share this DOI")

    # Stored values such as 'None', 'True' or "['A', 'B']" are strings; keep the raw
    # record for the old/new values of corrections and work on a cleaned copy.
    for d in docs:
        if d.get("arango"):
            d["arango_raw"] = d["arango"]
            d["arango"] = clean_record(d["arango"])
            stringly = sorted(k for k in ("authors", "doi", "year", "journal", "title", "openalex_id", "pages",
                                          "volume", "issue", "pmid")
                              if isinstance(d["arango_raw"].get(k), str) and d["arango"].get(k) != d["arango_raw"][k])
            if stringly:
                d["notes"].append("stringified values in record: " + ", ".join(stringly))


def passage_in_record(d: dict) -> Optional[bool]:
    """Is the passage text found in the record's abstract/content? (reproduction only)"""
    r = d.get("arango") or {}
    body = squash((r.get("abstract") or "") + " " + (r.get("content") or ""))
    if not body:
        return None
    hits = tries = 0
    for t in d["_texts"]:
        sq = squash(t)
        if len(sq) < 120:
            continue
        for off in (20, len(sq) // 2, len(sq) - 70):
            tries += 1
            hits += sq[off:off + 40] in body
    return None if not tries else hits / tries >= 0.5


def process_deb(d: dict, look: Optional[Lookup], bib: list[dict], http_on: bool) -> None:
    fname = d["stored_title"]
    r = d.get("arango")
    d["filename_parse"] = fp = parse_filename(fname)
    status, missing = classify(r, fname)
    d["status_arango"], d["missing_arango"] = status, missing

    # Consistency of the Arango record with the file name it was found by.
    if r:
        if fp["year"] and r.get("year") and abs(int(fp["year"]) - int(r["year"])) > 1:
            d["flags"].append(f"year mismatch: file name {fp['year']}, record {r['year']}")
        if fp["surnames"] and r.get("authors") and fp["style"] != "other":
            if not any(name_matches(fp["surnames"][0], fp["surname_kind"], a) for a in r["authors"][:2]):
                d["flags"].append(f"first author mismatch: file name '{fp['surnames'][0]}', record {r['authors'][:2]}")

    if status == "full" and not d["flags"] and not d.get("doi_check_failed"):
        return

    # ---- gather reference info -------------------------------------------------
    pdf = DEB_LIBRARY / d["document_id"] / fname
    if not pdf.exists() and r and r.get("source_path"):
        pdf = DEB_LIBRARY / r["source_path"]
    head, pdf_dois = read_pdf_head(pdf) if pdf.exists() else ("", [])
    d["pdf_dois"] = pdf_dois
    d["pdf_head"] = head[:300]
    real_title = r.get("title") if r and is_real_title(r.get("title"), fname) else None
    surnames, kind = list(fp["surnames"]), fp["surname_kind"]
    if not surnames and r and r.get("authors"):
        surnames, kind = [surname_of(a) for a in r["authors"][:2]], "full"
    ref = {"surnames": surnames, "surname_kind": kind,
           "year": fp["year"] or (r or {}).get("year"),
           "title": real_title, "title_prefix": fp["title_prefix"],
           "head_sq": squash(head), "known_dois": list(pdf_dois) + ([bare_doi(r["doi"])] if r and r.get("doi")
                                            and not d.get("doi_check_failed") else []),
           "companion": bool(fp.get("part"))}
    if fp.get("part"):
        d["notes"].append(f"file-name suffix '_{fp['part']}' marks a companion document; never auto-matched")

    full_surname = None
    if surnames:
        if kind == "full":
            full_surname = surnames[0].split()[-1] if fp["style"] != "other" else surnames[0]
        else:
            if r and r.get("authors"):
                for a in r["authors"]:
                    if name_matches(surnames[0], "prefix", a):
                        full_surname = surname_of(a).capitalize()
                        break
            full_surname = full_surname or full_surname_from_text(surnames[0], head)
    d["surname_used"] = full_surname

    cands: list[dict] = []
    # Local: methods-paper bibliography.
    for w in bib:
        if surnames and w["authors"] and ref["year"] and w["year"] == ref["year"] \
                and name_matches(surnames[0], kind, w["authors"][0]):
            cands.append(dict(w))
    if look and http_on:
        dois = [x for x in ref["known_dois"] if x]
        if dois:
            cands += list(look.by_dois(list(dict.fromkeys(dois))).values())
        title_q = real_title or fp["title_prefix"]
        if full_surname and ref["year"]:
            cands += look.crossref_author_year(full_surname, int(ref["year"]),
                                               title_q or " ".join(head.split()[:30]))
            cands += look.openalex_author_year(fold(full_surname).replace("'", ""), int(ref["year"]))
        if title_q:
            cands += look.openalex_search(f"{title_q}", 5)
        cr_q = " ".join(x for x in [title_q or " ".join(head.split()[:30]),
                                     full_surname or "", str(ref["year"] or "")] if x)
        cands += look.crossref_search(cr_q, 3)

    cands = dedup(cands)
    for c in cands:
        c["scores"] = score_candidate(c, ref)
    cands.sort(key=lambda c: -c["scores"]["score"])
    keep = [c for c in cands if c["scores"]["confidence"] != "low"][:3] or cands[:3]
    d["candidates"] = [slim(c) for c in keep]
    best = pick_best(cands)
    d["best_candidate"] = slim(best) if best else None


def merge_citation(base: Optional[dict], extra: Optional[dict]) -> dict:
    out = {}
    for f in ("title", "authors", "year", "journal", "doi", "openalex_id", "volume", "issue", "pages", "publisher"):
        v = (base or {}).get(f)
        if f == "doi":
            v = bare_doi(v)
        if f == "openalex_id" and v:
            v = str(v).rsplit("/", 1)[-1]
        if v in (None, [], "") and extra:
            v = extra.get(f)
        out[f] = v
    return out


def process_reproduction(d: dict, oa_by_id: dict, oa_by_doi: dict, look: Optional[Lookup], http_on: bool) -> None:
    r = d.get("arango")
    status, missing = classify(r)
    d["status_arango"], d["missing_arango"] = status, missing
    stored_doi = bare_doi(d["stored_doi"])
    rec_doi = bare_doi((r or {}).get("doi")) or stored_doi

    if r and r.get("title") and d["stored_title"] and title_similarity(d["stored_title"], r["title"]) < 0.6:
        d["flags"].append(f"passage title differs from record: '{d['stored_title'][:70]}' vs '{r['title'][:70]}'")
    pin = passage_in_record(d)
    d["passage_text_in_record"] = pin

    if not http_on:
        return
    oa = oa_by_id.get(d["document_id"])
    d["openalex_by_id"] = {k: oa.get(k) for k in ("openalex_id", "doi", "title", "year")} if oa else None
    id_conflict = False
    if oa and rec_doi and oa.get("doi") != rec_doi:
        sim = title_similarity((r or {}).get("title") or d["stored_title"], oa.get("title"))
        if oa.get("redirected_from"):
            # OpenAlex merged this work (typically a preprint) into another (its published version).
            d["notes"].append(f"OpenAlex merged {d['document_id']} into {oa['openalex_id']}"
                              + (f"; published version doi {oa['doi']}" if oa.get("doi") else ""))
        elif sim >= 0.85:
            d["notes"].append(f"OpenAlex gives another DOI for the same work: {oa.get('doi')}" if oa.get("doi")
                              else "OpenAlex has no DOI for this work id; the stored DOI came from elsewhere")
        elif sim < 0.6:
            id_conflict = True
        else:
            d["flags"].append(f"OpenAlex work for this id has DOI {oa.get('doi')} and a similar title "
                              f"'{(oa.get('title') or '')[:60]}' (similarity {sim})")
    if oa and oa.get("type") in ("peer-review", "paratext", "erratum") and not id_conflict:
        d["flags"].append(f"OpenAlex type '{oa['type']}': not a research paper (e.g. a referee report "
                          f"or decision letter)")
    if id_conflict:
        d["flags"].append(f"document_id {d['document_id']} is an unrelated OpenAlex work "
                          f"('{(oa.get('title') or '')[:60]}', doi {oa.get('doi')}); the DOI is the reliable link")

    # Enrichment source: the record the DOI resolves to, else the OpenAlex work for the id.
    enrich = None
    if rec_doi and rec_doi in oa_by_doi:
        enrich = oa_by_doi[rec_doi]
    elif oa and not id_conflict:
        enrich = oa
    if rec_doi and enrich and enrich.get("doi") == rec_doi and r and r.get("title") \
            and title_similarity(r["title"], enrich.get("title")) < 0.6:
        d["flags"].append(f"stored DOI resolves to a different title: '{(enrich.get('title') or '')[:70]}'")
    if enrich:
        d["enrichment_source"] = "openalex by DOI" if rec_doi and enrich.get("doi") == rec_doi else "openalex by id"

    # No DOI anywhere: ask Crossref by title.
    cands = []
    have_doi = rec_doi or (enrich or {}).get("doi")
    if not have_doi and look:
        title = (r or {}).get("title") or d["stored_title"]
        year = (r or {}).get("year") or d["stored_year"]
        first = ((r or {}).get("authors") or (enrich or {}).get("authors") or [None])[0]
        if title:
            q = " ".join(x for x in [title, surname_of(first) if first else "", str(year or "")] if x)
            ref = {"surnames": [surname_of(first)] if first else [], "surname_kind": "full",
                   "year": year, "title": title, "head_sq": "", "known_dois": []}
            for c in dedup(look.crossref_search(q, 3) + look.openalex_search(title, 3)):
                c["scores"] = score_candidate(c, ref)
                if c.get("doi"):
                    cands.append(c)
            cands.sort(key=lambda c: -c["scores"]["score"])
            # A DOI from title search must be near-identical in title and exact in year.
            for c in cands:
                s = c["scores"]
                if s["confidence"] == "high" and not ((s["title"] or 0) >= 0.9 and s["year"] == 1.0):
                    s["confidence"] = "medium"
            d["candidates"] = [slim(c) for c in cands[:3]]
            best = pick_best(cands)
            d["best_candidate"] = slim(best) if best else None
    d["_enrich"] = enrich


def finalize(d: dict) -> None:
    """Final status after candidates/enrichment, and whether a person must look."""
    r = d.get("arango")
    dc = d.get("doi_check") or {}
    failed = bool(d.get("doi_check_failed"))
    fixed_doi = None
    if failed and dc.get("proposal_confidence") == "high" and dc.get("proposed_doi") not in (None, "no DOI"):
        fixed_doi = dc["proposed_doi"]
    if d["corpus"] == "deb":
        best = d.get("best_candidate")
        base = dict(r) if r and is_real_title(r.get("title"), d["stored_title"]) else None
        if base and failed:
            base["doi"] = fixed_doi  # never carry a DOI known to be wrong
        if best and base and best.get("doi") and bare_doi(base.get("doi")) and best["doi"] != bare_doi(base.get("doi")):
            d["flags"].append(f"record DOI {bare_doi(base.get('doi'))} differs from best candidate {best['doi']}")
        if best:
            # Trust the candidate fully; it was matched against file name and PDF.
            cit = merge_citation(best, base)
            d["resolution"] = "candidate"
        else:
            cit = merge_citation(base, None)
            d["resolution"] = "arango" if base else "none"
    else:
        enrich = d.get("_enrich")
        if failed and d.get("enrichment_source") == "openalex by DOI":
            enrich = None  # metadata of the wrong work
        base = dict(r) if r else None
        if base and failed:
            base["doi"] = fixed_doi
        tw = d.get("title_wrong_work")
        if base and tw:
            base.update({k: tw.get(k) for k in ("title", "authors", "year", "journal", "volume", "issue", "pages")})
            enrich = None
        cit = merge_citation(base, enrich)
        if not cit.get("title"):
            cit["title"] = d["stored_title"]
        if not cit.get("doi") and d.get("best_candidate"):
            cit["doi"] = d["best_candidate"]["doi"]
            d["resolution"] = "arango+crossref"
        else:
            d["resolution"] = "arango+openalex" if enrich else ("arango" if r else "passage")
    d["citation"] = cit
    d["citation_text"] = fmt_citation(cit)
    st, miss = classify(cit, d["stored_title"] if d["corpus"] == "deb" else None)
    d["status_final"], d["missing_final"] = st, miss
    confirmed_without_doi = bool(st == "partial" and miss == ["doi"] and d.get("best_candidate")
                                 and d["best_candidate"]["scores"]["confidence"] == "high")
    if d["corpus"] == "reproduction" and st == "partial" and miss == ["doi"] \
            and d.get("enrichment_source") == "openalex by id" \
            and not any(c["scores"]["confidence"] in ("high", "medium") for c in d.get("candidates") or []):
        # The OpenAlex work is the passage's own identity and has no DOI; Crossref has no near match.
        confirmed_without_doi = True
        d["notes"].append("complete citation from the OpenAlex work; no DOI registered or found")
    doi_joined = (d.get("join_rule") or "").startswith("documents.doi")
    doi_fixed = failed and dc.get("proposal_confidence") == "high"
    doi_ok = dc.get("status") == "doi_ok"
    serious = [f for f in d["flags"] if not f.startswith(("passage title differs", "record title belongs"))
               and not (doi_ok and f.startswith(("first author mismatch", "year mismatch")))
               and not (doi_joined and f.startswith("document_id"))
               and not (doi_fixed and f.startswith(FAILED_DOI + ("record DOI",)))]
    d["needs_manual"] = not ((st == "full" or confirmed_without_doi) and not serious)


def text_support(title: Optional[str], texts: list[str]) -> float:
    """Share of a title's content words (5+ letters) that occur in the passage texts."""
    words = set(re.findall(r"[a-z]{5,}", fold(title)))
    if not words:
        return 0.0
    body = fold(" ".join(texts))
    return round(sum(1 for w in words if w in body) / len(words), 3)


def reconcile_title_vs_doi(d: dict) -> None:
    """A reproduction DOI that 'mismatches' its record may be right while the title is wrong.

    The passage text decides: when it is about the DOI's work and not about the stored
    title, the record's title (and work id) belong to another work and the DOI stays.
    """
    dc = d.get("doi_check") or {}
    w = dc.get("work")
    if dc.get("status") != "doi_mismatch" or not w:
        return
    r = d.get("arango") or {}
    s_doi = text_support(w.get("title"), d["_texts"])
    s_rec = text_support(r.get("title") or d["stored_title"], d["_texts"])
    dc["text_support"] = {"doi_work_title": s_doi, "stored_title": s_rec}
    if s_doi >= 0.5 and s_doi >= s_rec + 0.2:
        dc["status"] = "doi_ok"
        dc["proposal_note"] = "the DOI is right; the record's title belongs to another work"
        d["doi_check_failed"] = False
        d["flags"] = [f for f in d["flags"] if not f.startswith(("doi_mismatch", "stored DOI resolves"))]
        d["flags"].append(f"record title belongs to another work: passage text matches the DOI's work "
                          f"'{(w.get('title') or '')[:70]}' (support {s_doi} vs {s_rec})")
        d["title_wrong_work"] = w


def doi_ref(d: dict) -> dict:
    """What the stored metadata says about a document, for judging its DOI."""
    r = d.get("arango") or {}
    if d["corpus"] == "deb":
        fp = parse_filename(d["stored_title"])
        title = r.get("title") if is_real_title(r.get("title"), d["stored_title"]) else None
    else:
        fp = None
        title = r.get("title") or d["stored_title"]
    authors = [a for a in (r.get("authors") or []) if a]
    if authors:
        surnames, kind = [surname_of(a) for a in authors[:2]], "full"
    elif fp and fp["surnames"]:
        surnames, kind = fp["surnames"], fp["surname_kind"]
    else:
        surnames, kind = [], "full"
    return {"title": title, "year": r.get("year") or (fp or {}).get("year") or d.get("stored_year"),
            "surnames": [x for x in surnames if x], "surname_kind": kind, "file": fp}


def note_doi_check(d: dict) -> None:
    dc = d["doi_check"]
    st = dc["status"]
    if st not in FAILED_DOI:
        return
    d["doi_check_failed"] = True
    res = dc.get("resolved") or {}
    what = {"doi_mismatch": f"resolves to '{(res.get('title') or '')[:70]}' ({res.get('year')})",
            "doi_unresolvable": "is unknown to Crossref, OpenAlex and DataCite",
            "doi_malformed": "; ".join(dc["problems"])}[st]
    d["flags"].append(f"{st}: stored DOI {bare_doi(str(dc['stored_doi']))} {what}")
    if (dc.get("judgement") or {}).get("note"):
        d["flags"].append(f"{st}: {dc['judgement']['note']}")


def propose_for_deb(d: dict) -> None:
    """Turn the file-name/PDF/title candidate search into a DOI proposal for a failed DOI."""
    dc = d.get("doi_check")
    if not dc or not d.get("doi_check_failed") or dc.get("proposed_doi"):
        return
    stored = bare_doi(str(dc["stored_doi"]))
    best = d.get("best_candidate")
    top = best or (d.get("candidates") or [None])[0]
    if best:
        if best.get("doi") and best["doi"] != stored:
            dc.update(proposed_doi=best["doi"], proposal_confidence="high",
                      proposal_note=f"best candidate: {best['citation'][:160]}")
        elif not best.get("doi"):
            dc.update(proposed_doi="no DOI", proposal_confidence="high",
                      proposal_note=f"the matching work has no DOI in OpenAlex/Crossref: {best['citation'][:160]}")
        else:
            dc.update(proposal_confidence="low", proposal_note="the best candidate carries the stored DOI; check by hand")
    elif top and top.get("doi") and top["doi"] != stored:
        conf = top["scores"]["confidence"]
        dc.update(proposed_doi=top["doi"], proposal_confidence="ambiguous" if conf == "high" else conf,
                  proposal_note=f"top candidate, not certain: {top['citation'][:160]}")
    else:
        dc.update(proposal_confidence="none", proposal_note="no candidate found; needs a person")


def propose_by_search(look: "Lookup", d: dict) -> None:
    """Title + first author + year search for a reproduction document whose DOI failed."""
    r = d.get("arango") or {}
    title = r.get("title") or d["stored_title"]
    year = r.get("year") or d["stored_year"]
    authors = [a for a in (r.get("authors") or []) if a]
    first = surname_of(authors[0]) if authors else ""
    dc = d["doi_check"]
    if not title:
        dc.update(proposal_confidence="none", proposal_note="no title to search with")
        return
    ref = {"surnames": [first] if first else [], "surname_kind": "full", "year": year, "title": title,
           "head_sq": "", "known_dois": []}
    q = " ".join(x for x in [title, first, str(year or "")] if x)
    cands = dedup(look.crossref_search(q, 5) + look.openalex_search(title, 3))
    good = []
    for c in cands:
        c["scores"] = score_candidate(c, ref)
        sc = c["scores"]
        if (sc["title"] or 0) >= 0.9 and (sc["year"] is None or sc["year"] >= 0.5) and sc["author"] != 0.0:
            good.append(c)
    good.sort(key=lambda c: -c["scores"]["score"])
    d["doi_proposal_candidates"] = [slim(c) for c in good[:3]]
    stored = bare_doi(str(dc["stored_doi"]))
    dois = {c.get("doi") for c in good}
    if len(dois) == 1 and good:
        c = good[0]
        if c.get("doi") and c["doi"] != stored:
            dc.update(proposed_doi=c["doi"], proposal_confidence="high",
                      proposal_note=f"title+author+year search: {fmt_citation(c)[:160]}")
        elif not c.get("doi"):
            dc.update(proposed_doi="no DOI", proposal_confidence="medium",
                      proposal_note=f"matching work found without a DOI: {fmt_citation(c)[:160]}")
        else:
            dc.update(proposal_confidence="low", proposal_note="search returns the stored DOI itself")
    elif good:
        c = good[0]
        dc.update(proposed_doi=c.get("doi"), proposal_confidence="medium",
                  proposal_note=f"several works match the title: {fmt_citation(c)[:160]}")
    else:
        dc.update(proposal_confidence="none", proposal_note="no clear match by title+author+year")


CORRECTION_FIELDS = ("title", "authors", "year", "journal", "doi")


def build_corrections(docs: list[dict]) -> dict:
    """High-confidence fills and fixes per Arango ``_key``. Proposals only; nothing is applied."""
    out: dict[str, dict] = {}
    for d in sorted(docs, key=lambda d: (d["corpus"], d["document_id"])):
        r, raw = d.get("arango"), d.get("arango_raw")
        if not r:
            continue
        fixes: dict[str, dict] = {}

        def put(field: str, new: Any, reason: str) -> None:
            old = raw.get(field)
            if old == new or new in (None, [], "") and old in (None, [], "", "None", "[]"):
                return
            fixes[field] = {"old": old, "new": new, "confidence": "high", "reason": reason}

        for f in CORRECTION_FIELDS:
            if isinstance(raw.get(f), str) and r.get(f) != raw.get(f):
                put(f, r.get(f), "stored as a string; normalise the type")

        src, src_name = None, None
        if d["corpus"] == "deb":
            best = d.get("best_candidate")
            if best and best["scores"]["confidence"] == "high" and not any(
                    f.startswith("record DOI") and "differs from best candidate" in f for f in d["flags"]):
                src, src_name = best, f"best candidate ({best['source']}), matched to file name/PDF"
        else:
            enrich = d.get("_enrich")
            bad = any(f.startswith(("document_id", "stored DOI resolves")) for f in d["flags"])
            if enrich and not bad and not d.get("doi_check_failed"):
                same_doi = bool(enrich.get("doi") and enrich["doi"] == bare_doi(r.get("doi")))
                if same_doi or title_similarity(r.get("title"), enrich.get("title")) >= 0.9:
                    src, src_name = dict(enrich), d.get("enrichment_source") or "openalex"
                    if not same_doi:  # another version of the work: its venue is not this record's
                        src.update(journal=None, publisher=None)

        tw = d.get("title_wrong_work")
        if tw:
            put("title", tw.get("title"), "fix: the record's title belongs to another work; the passage text "
                                          "and the DOI agree on this one")
            if tw.get("authors"):
                put("authors", tw["authors"], "fix: authors of the DOI's work")
            if tw.get("year") and tw.get("year") != r.get("year"):
                put("year", tw["year"], "fix: year of the DOI's work")
            if tw.get("journal") or tw.get("publisher"):
                put("journal", tw.get("journal") or tw.get("publisher"), "fix: venue of the DOI's work")
        dc = d.get("doi_check") or {}
        if dc.get("status") in FAILED_DOI and dc.get("proposal_confidence") == "high":
            new = None if dc.get("proposed_doi") == "no DOI" else dc.get("proposed_doi")
            put("doi", new, f"{dc['status']}: " + (dc.get("proposal_note") or ""))
        elif dc.get("status") in FAILED_DOI and dc.get("status") != "doi_malformed":
            pass  # wrong but no certain replacement: listed in doi_check.csv, not here

        # A verified DOI (title agrees) is a reliable source for what the record lacks or gets wrong.
        w = dc.get("work")
        if dc.get("status") == "doi_ok" and w and d["corpus"] == "deb" and not src:
            fp = parse_filename(d["stored_title"])
            wa, ra = w.get("authors") or [], r.get("authors") or []
            if wa and not ra:
                put("authors", wa, f"fill: from the verified DOI ({w['source']})")
            elif wa and ra and fp["style"] != "other" and fp["surnames"] \
                    and name_matches(fp["surnames"][0], fp["surname_kind"], wa[0]) \
                    and not name_matches(fp["surnames"][0], fp["surname_kind"], ra[0]):
                put("authors", wa, "fix: record authors disagree with the file name; the verified DOI's agree")
            if fp["year"] and w.get("year") and r.get("year") and int(fp["year"]) == int(w["year"]) \
                    and abs(int(r["year"]) - int(w["year"])) > 1:
                put("year", w["year"], "fix: record year disagrees with the file name and the verified DOI")
            if not r.get("year") and w.get("year"):
                put("year", w["year"], f"fill: from the verified DOI ({w['source']})")
            if not r.get("journal") and (w.get("journal") or w.get("publisher")):
                put("journal", w.get("journal") or w.get("publisher"), f"fill: from the verified DOI ({w['source']})")

        if src and not tw:
            fname = d["stored_title"] if d["corpus"] == "deb" else None
            if not is_real_title(r.get("title"), fname) and src.get("title"):
                put("title", src["title"], f"fill: record has no real title; from {src_name}")
            if src.get("authors") and (not r.get("authors") or
                                       (len(r["authors"]) == 1 and "et al" in r["authors"][0])):
                put("authors", src["authors"], f"fill: from {src_name}")
            if src.get("year") and not r.get("year"):
                put("year", src["year"], f"fill: from {src_name}")
            elif src.get("year") and r.get("year") and abs(int(r["year"]) - int(src["year"])) > 1 and (
                    d["corpus"] != "deb" or parse_filename(d["stored_title"])["year"] == src["year"]):
                put("year", src["year"], f"fix: record year differs by more than one from {src_name}")
            venue = src.get("journal") or src.get("publisher")
            if venue and not r.get("journal"):
                put("journal", venue, f"fill: from {src_name}")
            if src.get("doi") and not r.get("doi") and "doi" not in fixes:
                put("doi", src["doi"], f"fill: from {src_name}")
        if fixes:
            out[r["_key"]] = {
                "collections": ["documents", "document_meta"] if r.get("source_type") == "pdf_local"
                else ["documents"],
                "corpus": d["corpus"], "evidence_document_id": d["document_id"],
                "source_path": r.get("source_path") if r.get("source_type") == "pdf_local" else None,
                "n_passages": d["n_passages"], "fields": fixes,
            }
    return out


def summarize(docs: list[dict], meta: dict, mode: str, http: Http) -> str:
    totals = meta["totals"]
    lines = [f"Passage citation report — evidence_sets v{meta['manifest'].get('version')} "
             f"(sha256 {meta['artefact_sha256'][:16]}…), mode: {mode}", ""]
    lines.append("Scope: deb and reproduction evidence sets (combined sets ignored; they repeat the same passages).")
    lines.append(f"Passages: deb {totals.get('deb', 0)}, reproduction {totals.get('reproduction', 0)}, "
                 f"total {sum(totals.values())}.")
    lines.append("")

    def block(title: str, key: str) -> None:
        lines.append(title)
        for corpus in ("deb", "reproduction", "all"):
            sel = [d for d in docs if corpus == "all" or d["corpus"] == corpus]
            tp = sum(d["n_passages"] for d in sel)
            parts = []
            for st in ("full", "partial", "unresolved"):
                s2 = [d for d in sel if d[key] == st]
                np_ = sum(d["n_passages"] for d in s2)
                parts.append(f"{st} {len(s2)} docs / {np_} passages ({100 * np_ / tp:.1f}%)")
            lines.append(f"  {corpus:<12} {len(sel)} docs, {tp} passages: " + "; ".join(parts))
        lines.append("")

    block("1. From ArangoDB alone (full = authors + year + real title + DOI):", "status_arango")
    if mode == "full":
        block("2. After OpenAlex/Crossref (high-confidence candidates and OpenAlex-by-id enrichment only):",
              "status_final")
        gained = [d for d in docs if d["status_arango"] != "full" and d["status_final"] == "full"]
        lines.append(f"   Newly full: {len(gained)} docs / {sum(d['n_passages'] for d in gained)} passages "
                     f"(deb {sum(1 for d in gained if d['corpus'] == 'deb')}, "
                     f"reproduction {sum(1 for d in gained if d['corpus'] == 'reproduction')}).")
        nodoi = [d for d in docs if d["status_final"] == "partial" and d["missing_final"] == ["doi"]
                 and not d["needs_manual"]]
        lines.append(f"   Complete citation confirmed but no DOI exists in OpenAlex/Crossref (books, theses): "
                     f"{len(nodoi)} docs / {sum(d['n_passages'] for d in nodoi)} passages.")
        lines.append("")
    man = [d for d in docs if d["needs_manual"]]
    lines.append(f"3. Needs manual work: {len(man)} docs / {sum(d['n_passages'] for d in man)} passages "
                 f"(deb {sum(1 for d in man if d['corpus'] == 'deb')} docs / "
                 f"{sum(d['n_passages'] for d in man if d['corpus'] == 'deb')} passages; reproduction "
                 f"{sum(1 for d in man if d['corpus'] == 'reproduction')} docs / "
                 f"{sum(d['n_passages'] for d in man if d['corpus'] == 'reproduction')} passages).")
    with_guess = [d for d in man if d.get("candidates")]
    lines.append(f"   Of these, {len(with_guess)} have at least one scored candidate in unresolved_citations.csv.")
    lines.append("")
    lines.append("4. DOI check (Crossref, then OpenAlex, then DataCite; title fuzzy ratio + year + first author):")
    for corpus, label in (("deb", "deb, every record with a DOI"),
                          ("reproduction", f"reproduction, sample of {REP_SAMPLE} + OpenAlex-screening flags")):
        sel = [d for d in docs if d["corpus"] == corpus and d.get("doi_check")]
        c = Counter(d["doi_check"]["status"] for d in sel)
        lines.append(f"  {label}: {len(sel)} checked: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
        bad = [d for d in sel if d["doi_check"]["status"] in FAILED_DOI]
        lines.append(f"    wrong DOI shown today: {len(bad)} docs / {sum(d['n_passages'] for d in bad)} passages"
                     + (f" (of {sum(d['n_passages'] for d in docs if d['corpus'] == corpus)})" if corpus == "deb" else ""))
        if corpus == "reproduction":
            samp = [d for d in sel if d.get("doi_check_scope") == "sample"]
            sbad = [d for d in samp if d["doi_check"]["status"] in FAILED_DOI]
            lines.append(f"    sample alone: {len(sbad)}/{len(samp)} wrong")
            scr = [d for d in docs if d["corpus"] == corpus and any(
                f.startswith("stored DOI resolves") for f in d["flags"])]
            lines.append(f"    OpenAlex screening of all {sum(1 for d in docs if d['corpus'] == corpus)} docs "
                         f"(stored DOI -> title): {len(scr)} disagree")
        hi = [d for d in bad if d["doi_check"].get("proposal_confidence") == "high"]
        lines.append(f"    high-confidence proposals: {len(hi)} "
                     f"({sum(1 for d in hi if d['doi_check'].get('proposed_doi') == 'no DOI')} of them 'no DOI')")
    lines.append(f"  citation_corrections.json: {meta.get('n_corrections', 0)} documents, field changes "
                 f"{dict(meta.get('correction_fields') or {})}")
    lines.append("")
    lines.append("5. Join rules that matched:")
    for rule, n in Counter(d.get("join_rule") or "no match" for d in docs).most_common():
        lines.append(f"  {n:5d}  {rule}")
    lines.append("")
    lines.append("6. Data-quality flags (see passage_citations.json 'flags'):")
    fl = Counter()
    for d in docs:
        for f in d["flags"]:
            fl[re.sub(r"\bW\d+\b", "W…", re.split(r"[:'(\[]", f)[0]).strip()[:60]] += 1
    for f, n in fl.most_common():
        lines.append(f"  {n:5d}  {f}")
    nt = Counter()
    for d in docs:
        for f in d["notes"]:
            nt[re.sub(r"\bW\d+\b", "W…", re.split(r"[:;'(\[]|\binto\b", f)[0]).strip()[:60]] += 1
    lines.append("  notes (informational):")
    for f, n in nt.most_common():
        lines.append(f"  {n:5d}  {f}")
    dm = Counter(d.get("document_meta") for d in docs if d["corpus"] == "deb" and d.get("arango"))
    lines.append(f"  document_meta vs documents for matched deb records: {dict(dm)}")
    pin = Counter(str(d.get("passage_text_in_record")) for d in docs if d["corpus"] == "reproduction")
    lines.append(f"  reproduction passage text found in the record's abstract/content: {dict(pin)}")
    lines.append("")
    if mode == "full":
        lines.append(f"External requests this run: {http.n_requests} (cache entries: {len(http.cache)}), "
                     f"failures: {http.n_failures}, skipped for an exhausted budget: {http.n_skipped}.")
        if http.disabled:
            lines.append("  Budget exhausted (OpenAlex list/search without an API key; resets 00:00 UTC) for: "
                         + ", ".join(sorted(http.disabled))
                         + ". Re-run later to add those candidates; cached answers are reused.")
    lines.append("Bibliography on disk: no DEB key-to-reference bibliography was found under "
                 "/home/adeb/DEB_library, advandeb_auxiliary or advandeb_methods; the methods paper's "
                 f"verified references.bib ({METHODS_BIB}) is used as a local candidate source.")
    return "\n".join(lines) + "\n"


def write_outputs(docs: list[dict], meta: dict, mode: str, http: Http) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    order = sorted(docs, key=lambda d: (d["corpus"], -d["n_passages"], d["document_id"]))
    out_docs = []
    for d in order:
        r = d.get("arango")
        out_docs.append({
            "corpus": d["corpus"], "document_id": d["document_id"],
            "stored_title": d["stored_title"], "stored_doi": d.get("stored_doi"),
            "n_passages": d["n_passages"], "n_evidence_sets": len(d["_sets"]),
            "join_rule": d.get("join_rule"),
            "arango_record": None if not r else {k: r.get(k) for k in (
                "_key", "source_type", "source_path", "title", "authors", "year", "journal", "doi",
                "openalex_id", "volume", "issue", "pages", "pmid")},
            "document_meta": d.get("document_meta"),
            "status_arango": d["status_arango"], "missing_arango": d["missing_arango"],
            "status_final": d["status_final"], "missing_final": d["missing_final"],
            "resolution": d.get("resolution"), "citation": d["citation"], "citation_text": d["citation_text"],
            "needs_manual": d["needs_manual"],
            "flags": d["flags"], "notes": d["notes"],
            "doi_check": d.get("doi_check"), "doi_check_scope": d.get("doi_check_scope"),
            "doi_proposal_candidates": d.get("doi_proposal_candidates"),
            **({"filename_parse": d.get("filename_parse"), "surname_used": d.get("surname_used"),
                "pdf_dois": d.get("pdf_dois"), "pdf_head": d.get("pdf_head")} if d["corpus"] == "deb" else
               {"openalex_by_id": d.get("openalex_by_id"), "enrichment_source": d.get("enrichment_source"),
                "passage_text_in_record": d.get("passage_text_in_record")}),
            "candidates": d.get("candidates") or [], "best_candidate": d.get("best_candidate"),
        })
    payload = {"generated_from": str(EVIDENCE_PATH), "artefact_sha256": meta["artefact_sha256"],
               "mode": mode, "passage_totals": meta["totals"], "documents": out_docs}
    (OUT_DIR / "passage_citations.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    rows = []
    for d in docs:
        if d["status_arango"] == "full" and not d["needs_manual"]:
            continue
        best = d.get("best_candidate")
        top = best or (d.get("candidates") or [None])[0]
        if best:
            conf = best["scores"]["confidence"]
            cit, cdoi, src = best["citation"], best.get("doi") or "", best["source"]
        elif d["corpus"] == "reproduction" and d.get("_enrich") and d["status_final"] == "full":
            conf, cit, cdoi, src = "high", d["citation_text"], d["citation"].get("doi") or "", d.get("enrichment_source")
        elif top:
            conf = top["scores"]["confidence"]
            cit, cdoi, src = top["citation"], top.get("doi") or "", top["source"]
        else:
            conf, cit, cdoi, src = "none", "", "", ""
        if not best and top and top is not None and conf == "high":
            conf = "ambiguous"
        rows.append({
            "corpus": d["corpus"], "document_id": d["document_id"], "stored_title": d["stored_title"],
            "n_passages": d["n_passages"], "status_arango": d["status_arango"],
            "missing_arango": ",".join(d["missing_arango"]), "status_final": d["status_final"],
            "best_candidate_doi": cdoi, "candidate_citation": cit, "confidence": conf,
            "candidate_source": src or "", "needs_manual": "yes" if d["needs_manual"] else "no",
            "flags": " | ".join(d["flags"] + d["notes"]),
        })
    rows.sort(key=lambda x: (-x["n_passages"], x["needs_manual"] != "yes", x["corpus"], x["document_id"]))
    with open(OUT_DIR / "unresolved_citations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["corpus"])
        w.writeheader()
        w.writerows(rows)
    # DOI check table: every checked DOI, failures first, by passages affected.
    drows = []
    for d in docs:
        dc = d.get("doi_check")
        if not dc:
            continue
        res = dc.get("resolved") or dc.get("resolved_cleaned") or {}
        j = dc.get("judgement") or {}
        drows.append({
            "corpus": d["corpus"], "document_id": d["document_id"], "file": d["stored_title"],
            "arango_key": (d.get("arango") or {}).get("_key"), "scope": d.get("doi_check_scope", "all deb"),
            "stored_doi": dc["stored_doi"], "status": dc["status"],
            "crossref_title": res.get("title") or "",
            "resolved_source": (res.get("source") or "") + (" (repaired DOI)" if not dc.get("resolved") and res else ""),
            "resolved_year": res.get("year") or "",
            "title_similarity": j.get("title_similarity") if j.get("title_similarity") is not None else "",
            "proposed_doi": dc.get("proposed_doi") or "", "confidence": dc.get("proposal_confidence") or "",
            "proposal_note": dc.get("proposal_note") or "", "n_passages": d["n_passages"],
        })
    drows.sort(key=lambda x: (x["status"] not in FAILED_DOI, -x["n_passages"], x["corpus"], x["document_id"]))
    with open(OUT_DIR / "doi_check.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(drows[0].keys()) if drows else ["corpus"])
        w.writeheader()
        w.writerows(drows)

    corrections = build_corrections(docs) if mode == "full" else {}
    (OUT_DIR / "citation_corrections.json").write_text(json.dumps({
        "generated_from": str(EVIDENCE_PATH), "artefact_sha256": meta["artefact_sha256"],
        "note": ("Proposals only: nothing has been applied. High-confidence changes only, per ArangoDB "
                 "documents._key; pdf_local rows are mirrored in document_meta under the same _key. "
                 "'old' is the raw stored value (strings such as 'None' included); a 'new' of null "
                 "means the stored value is wrong and no replacement exists."),
        "n_documents": len(corrections),
        "n_field_changes": dict(Counter(f for c in corrections.values() for f in c["fields"])),
        "corrections": corrections,
    }, indent=1, ensure_ascii=False) + "\n")
    meta["n_corrections"] = len(corrections)
    meta["correction_fields"] = Counter(f for c in corrections.values() for f in c["fields"])
    (OUT_DIR / "summary.txt").write_text(summarize(docs, meta, mode, http))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-external", action="store_true", help="ArangoDB only; no OpenAlex/Crossref")
    ap.add_argument("--refresh-cache", action="store_true", help="ignore scripts/out/http_cache.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("app", "advandeb_kb", "httpx", "urllib3", "pypdf"):
        logging.getLogger(noisy).setLevel(logging.WARNING if noisy != "pypdf" else logging.ERROR)

    from app.core.database import get_arango_db  # reads the app's .env

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    http_on = not args.no_external
    http = Http(enabled=http_on, refresh=args.refresh_cache)
    look = Lookup(http) if http_on else None

    docs_map, meta = load_passages()
    docs = list(docs_map.values())
    for d in docs:
        d["flags"], d["notes"] = [], []
    print(f"{len(docs)} distinct documents "
          f"({sum(1 for d in docs if d['corpus'] == 'deb')} deb, "
          f"{sum(1 for d in docs if d['corpus'] == 'reproduction')} reproduction)", file=sys.stderr)

    arango = get_arango_db()
    arango_fetch(arango, docs)

    deb = sorted([d for d in docs if d["corpus"] == "deb"], key=lambda d: d["document_id"])
    rep = sorted([d for d in docs if d["corpus"] == "reproduction"], key=lambda d: d["document_id"])

    # Check every DOI a deb record carries: does it resolve, and to this work?
    for i, d in enumerate(deb, 1):
        r = d.get("arango")
        if not r or not r.get("doi"):
            continue
        if http_on:
            d["doi_check"] = check_doi(look, r["doi"], doi_ref(d))
        else:
            _, problems = doi_shape(r["doi"])
            d["doi_check"] = {"stored_doi": r["doi"], "problems": problems, "resolved": None,
                              "judgement": None, "proposed_doi": None, "proposal_confidence": None,
                              "proposal_note": None,
                              "status": "doi_malformed" if problems else "not_checked (--no-external)"}
        note_doi_check(d)
        if http_on and i % 25 == 0:
            http.save()
            print(f"  doi check deb {i}/{len(deb)}", file=sys.stderr)

    # Duplicate DOIs across curated PDFs make a DOI ambiguous.
    by_doi = defaultdict(list)
    for x in arango.aql("""FOR d IN documents FILTER d.source_type == 'pdf_local'
            RETURN {doi: d.doi, sp: d.source_path}"""):
        b = bare_doi(clean_value(x["doi"]))
        if b:
            by_doi[b].append(x["sp"])
    for d in deb:
        r = d.get("arango")
        if r and r.get("doi") and len(by_doi.get(bare_doi(r["doi"]), [])) > 1:
            others = [p for p in by_doi[bare_doi(r["doi"])] if p != r.get("source_path")]
            d["flags"].append(f"DOI shared with other curated PDFs: {others[:3]}")

    bib = load_methods_bib()
    for i, d in enumerate(deb, 1):
        process_deb(d, look, bib, http_on)
        if http_on and i % 10 == 0:
            http.save()
            print(f"  deb {i}/{len(deb)}", file=sys.stderr)

    oa_by_id, oa_by_doi = {}, {}
    if http_on:
        oa_by_id = look.openalex_by_ids([d["document_id"] for d in rep])
        http.save()
        # The DOI only adds information where the work id does not stand for it: the id
        # is unknown, its work carries another or no DOI, or the record was DOI-joined.
        need = []
        for d in rep:
            dd = bare_doi((d.get("arango") or {}).get("doi")) or bare_doi(d["stored_doi"])
            w = oa_by_id.get(d["document_id"])
            if dd and (not w or w.get("doi") != dd or (d.get("join_rule") or "").startswith("documents.doi")):
                need.append(dd)
        oa_by_doi = look.by_dois(sorted(set(need)))
        http.save()
    for i, d in enumerate(rep, 1):
        process_reproduction(d, oa_by_id, oa_by_doi, look, http_on)
        if http_on and i % 50 == 0:
            http.save()
    # DOI check for reproduction: a deterministic sample, plus every document the
    # OpenAlex screening above flagged.
    if http_on:
        with_doi = [d for d in rep if bare_doi((d.get("arango") or {}).get("doi")) or bare_doi(d["stored_doi"])]
        sample = sorted(with_doi, key=lambda d: hashlib.sha256(d["document_id"].encode()).hexdigest())[:REP_SAMPLE]
        flagged = [d for d in with_doi if d["flags"]]
        for d in {id(x): x for x in sample + flagged}.values():
            d["doi_check_scope"] = "sample" if d in sample else "flagged by OpenAlex screening"
            stored = (d.get("arango") or {}).get("doi") or d["stored_doi"]
            d["doi_check"] = check_doi(look, stored, doi_ref(d))
            note_doi_check(d)
            reconcile_title_vs_doi(d)
        http.save()

    for d in deb:
        propose_for_deb(d)
    if http_on:
        for d in rep:
            if d.get("doi_check_failed") and not d["doi_check"].get("proposed_doi"):
                propose_by_search(look, d)
        http.save()

    for d in docs:
        finalize(d)

    # The same curated paper cited from both corpora.
    by_key = defaultdict(list)
    for d in docs:
        if d.get("arango"):
            by_key[d["arango"]["_key"]].append(d)
    for k, ds in by_key.items():
        if len({x["corpus"] for x in ds}) > 1:
            for x in ds:
                x["notes"].append("same Arango document is cited from the other corpus too: " +
                                  ", ".join(f"{y['corpus']}:{y['document_id']}" for y in ds if y is not x))

    http.save()
    write_outputs(docs, meta, "full" if http_on else "arango-only (--no-external)", http)
    print((OUT_DIR / "summary.txt").read_text(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
