"""
ArangoSearch views that give facts and stylized facts BM25 keyword search.

``KnowledgeService.search_facts`` / ``search_stylized_facts`` query these
views; ``knowledge-builder/scripts/setup_facts_search_views.py`` creates them.
They replace FULLTEXT indexes that never served those searches: the indexes were
declared on ``facts.text`` and ``stylized_facts.description``, attributes no
document has (the text is in ``facts.content`` and ``stylized_facts.statement``),
so every search fell back to an unranked LIKE scan. ArangoDB has deprecated
FULLTEXT indexes in favour of ArangoSearch anyway.

The analyzer is the one the chunks view (settings.RETRIEVAL_CHUNKS_VIEW) uses
for hybrid retrieval, settings.RETRIEVAL_TEXT_ANALYZER, and its definition
lives here for both setup scripts. Both check an existing analyzer against it
and refuse to proceed when it differs; analyzers cannot be changed in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from advandeb_kb.config.settings import settings

TEXT_ANALYZER = settings.RETRIEVAL_TEXT_ANALYZER

# Lucene's default English stop set (EnglishAnalyzer.ENGLISH_STOP_WORDS_SET).
STOPWORDS = [
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "if", "in",
    "into", "is", "it", "no", "not", "of", "on", "or", "such", "that", "the",
    "their", "then", "there", "these", "they", "this", "to", "was", "will", "with",
]

# English text: lower case, accents folded, stemmed, stop words dropped.
# frequency + norm is what BM25 needs; without positions there is no PHRASE(),
# and the index is smaller.
ANALYZER_TYPE = "text"
ANALYZER_PROPERTIES: Dict[str, Any] = {
    "locale": "en",
    "case": "lower",
    "accent": False,
    "stemming": True,
    "stopwords": STOPWORDS,
}
ANALYZER_FEATURES = ["frequency", "norm"]


@dataclass(frozen=True)
class TextSearchView:
    """A view over one collection: a BM25-searchable text field, plus fields
    indexed verbatim (identity analyzer) so equality filters can go in SEARCH."""

    name: str
    collection: str
    text_field: str
    filter_fields: Tuple[str, ...] = ()

    def link(self) -> Dict[str, Any]:
        fields: Dict[str, Any] = {self.text_field: {"analyzers": [TEXT_ANALYZER]}}
        for field in self.filter_fields:
            fields[field] = {"analyzers": ["identity"]}
        return {
            "includeAllFields": False,
            "storeValues": "none",
            "trackListPositions": False,
            # Build without locking the collection against writes.
            "inBackground": True,
            "fields": fields,
        }


FACTS_VIEW = TextSearchView(
    name=settings.FACTS_SEARCH_VIEW,
    collection="facts",
    text_field="content",
    filter_fields=("general_domain",),
)
STYLIZED_FACTS_VIEW = TextSearchView(
    name=settings.STYLIZED_FACTS_SEARCH_VIEW,
    collection="stylized_facts",
    text_field="statement",
    filter_fields=("category",),
)
VIEWS = (FACTS_VIEW, STYLIZED_FACTS_VIEW)


# ---------------------------------------------------------------------------
# State checks and changes (python-arango StandardDatabase)
# ---------------------------------------------------------------------------


def analyzer_state(db, name: str = TEXT_ANALYZER) -> str:
    """'missing', 'ok', or a description of how the existing analyzer differs."""
    try:
        existing = db.analyzer(name)
    except Exception:
        return "missing"
    props = existing.get("properties", {})
    diffs = [k for k, v in ANALYZER_PROPERTIES.items() if props.get(k) != v]
    if existing.get("type") != ANALYZER_TYPE:
        diffs.append("type")
    if sorted(existing.get("features", [])) != sorted(ANALYZER_FEATURES):
        diffs.append("features")
    return "ok" if not diffs else f"differs in {', '.join(diffs)}"


def link_state(link: Optional[Dict[str, Any]], fields: Dict[str, Any]) -> str:
    """'link missing', 'ok', or which of ``fields`` the link indexes differently.

    ``link`` is a view's link as ArangoDB returns it, ``fields`` the ``fields``
    of the link definition it was created from.
    """
    if not link:
        return "link missing"
    have = link.get("fields", {})
    # A field without its own analyzers uses the link's; ArangoDB stores
    # {"analyzers": ["identity"]} that way, as {}.
    inherited = link.get("analyzers", ["identity"])
    for field, spec in fields.items():
        if field not in have:
            return f"field {field!r} missing"
        if sorted(have[field].get("analyzers", inherited)) != sorted(spec["analyzers"]):
            return f"field {field!r} differs"
    return "ok"


def view_state(db, view: TextSearchView) -> str:
    """'missing', 'link missing', 'ok', or which field is indexed differently."""
    if not any(v["name"] == view.name for v in db.views()):
        return "missing"
    link = (db.view(view.name).get("links") or {}).get(view.collection)
    return link_state(link, view.link()["fields"])


def create_analyzer(db, name: str = TEXT_ANALYZER) -> None:
    db.create_analyzer(
        name,
        analyzer_type=ANALYZER_TYPE,
        properties=ANALYZER_PROPERTIES,
        features=ANALYZER_FEATURES,
    )


def create_or_update_view(db, view: TextSearchView, state: str) -> None:
    """Create the view, or replace its link for the collection (re-indexes it)."""
    links = {view.collection: view.link()}
    if state == "missing":
        db.create_arangosearch_view(view.name, properties={"links": links})
    else:
        db.update_arangosearch_view(view.name, properties={"links": links})


def count_indexed(db, view: TextSearchView) -> int:
    """Documents the view has committed so far (it lags inserts by ~1 s)."""
    cursor = db.aql.execute(
        "FOR d IN @@view SEARCH true OPTIONS {waitForSync: false} "
        "COLLECT WITH COUNT INTO n RETURN n",
        bind_vars={"@view": view.name},
    )
    return next(iter(cursor), 0)
