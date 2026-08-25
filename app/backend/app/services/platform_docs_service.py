"""
PlatformDocsService — keyword search over AdvanDEB's own in-app documentation
and tutorials, so the chat assistant can answer questions about the platform
itself (e.g. "what is AdvanDEB", "how do citations work") instead of guessing
from the LLM's general training knowledge.

The corpus (``app/data/platform_docs.json``) mirrors the user-facing sections
of ``DocumentationView.vue`` and deliberately excludes the "Administrator
notes" section — role assignment, account management, and reset controls are
never exposed to chat.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "platform_docs.json"
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=1)
def _load_docs() -> List[Dict[str, str]]:
    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("platform_docs: failed to load %s: %s", _DATA_PATH, exc)
        return []


def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


def search_platform_docs(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Score every doc section by query-term overlap in title+text; return top matches.

    No vector index needed — the corpus is a couple dozen short sections, so a
    simple term-overlap score (weighted toward title hits) is enough to
    reliably surface the right section for "what is X" / "how do I do Y"
    questions about the app itself.
    """
    terms = _tokenize(query)
    if not terms:
        return []

    scored = []
    for doc in _load_docs():
        title_terms = _tokenize(doc.get("title", ""))
        text_terms = _tokenize(doc.get("text", ""))
        score = 2 * len(terms & title_terms) + len(terms & text_terms)
        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [doc for _, doc in scored[:limit]]


def get_platform_doc(doc_id: str) -> Dict[str, Any] | None:
    """Look up a single doc section by id (used for provenance lookups)."""
    for doc in _load_docs():
        if doc.get("id") == doc_id:
            return doc
    return None
