"""Entity keys that are not ObjectIds: OpenAlex-keyed documents and their facts.

Reproduction documents are keyed by OpenAlex work id ("W2810246872") or a
"doi_"/"rec_" hash, and their facts carry that key as document_id; sf_support
edges are keyed "<fact key>_<sf key>". The models type these as ObjectIdOrKey:
hex keys stay ObjectId (what the Mongo-era writers hand to pymongo), anything
else stays the string ArangoDB stores.
"""

import asyncio

import pytest
from bson import ObjectId
from pydantic import BaseModel, ValidationError

from advandeb_kb.database import text_search as ts
from advandeb_kb.models.common import ObjectIdOrKey
from advandeb_kb.models.knowledge import (
    Document,
    DocumentTaxonRelation,
    Fact,
    FactSFRelation,
    StylizedFact,
)
from advandeb_kb.services.knowledge_service import KnowledgeService, _doc_to_model

FACT_KEY = "69d43f10915338a7a9da7586"
LEGACY_DOC_KEY = "69d43eee915338a7a9da7585"
SF_KEY = "69a59b80fa961dd3552c21cd"
OPENALEX_KEY = "W2810246872"
DOI_KEY = "doi_3f2b9c1e0a7d4e5f6a7b"
REC_KEY = "rec_0a1b2c3d4e5f60718293"
EDGE_KEY = f"{FACT_KEY}_{SF_KEY}"


def fact_row(key=FACT_KEY, document_id=OPENALEX_KEY, **extra):
    # Shaped like a reproduction fact straight out of ArangoDB.
    return {
        "_id": f"facts/{key}", "_key": key, "_rev": "_lXBz8AO--c",
        "content": "Egg size increases with female body size.",
        "document_id": document_id, "additional_sources": [],
        "content_fingerprint": "egg size increases with female body size",
        "fact_type": "conclusion", "page_number": None, "entities": [],
        "tags": ["abstract", "conclusion"], "general_domain": "reproduction",
        "confidence": 0.7, "status": "pending",
        "created_at": "2026-10-01T12:00:00+00:00", "updated_at": "2026-10-01T12:00:00+00:00",
        **extra,
    }


def document_row(key=OPENALEX_KEY, **extra):
    # As import_reproduction_abstracts.py writes it, plus the fields
    # backfill_openalex_metadata.py adds; several are not on the model.
    return {
        "_id": f"documents/{key}", "_key": key, "_rev": "_lXBz8AO--d",
        "title": "Egg size and female body size in fishes", "doi": "10.1000/xyz",
        "authors": ["A. Author"], "year": 2018, "journal": "J. Fish Biol.",
        "abstract": "…", "content": "…", "source_type": "web",
        "source_path": f"https://openalex.org/{key}", "general_domain": "reproduction",
        "processing_status": "completed", "openalex_id": f"https://openalex.org/{key}",
        "tags": ["fish"], "cited_by_count": 12, "language": "en", "num_facts": 3,
        "openalex_enriched": True,
        "created_at": "2026-09-01T12:00:00+00:00", "updated_at": "2026-09-01T12:00:00+00:00",
        **extra,
    }


def edge_row(key=EDGE_KEY):
    return {
        "_id": f"sf_support/{key}", "_key": key, "_rev": "_x",
        "_from": f"facts/{FACT_KEY}", "_to": f"stylized_facts/{SF_KEY}",
        "relation_type": "supports", "confidence": 0.6, "status": "suggested",
        "created_by": "agent",
    }


class FakeArango:
    """ArangoDatabase stand-in: records calls, answers from fixed rows."""

    def __init__(self, rows=(), docs=None, views=()):
        self.rows = list(rows)
        self.docs = docs or {}
        self.views = set(views)
        self.queries = []
        self.inserted = []

    def aql(self, query, bind_vars=None):
        self.queries.append((query, dict(bind_vars or {})))
        return list(self.rows)

    def get(self, collection, key):
        return self.docs.get((collection, key))

    def insert(self, collection, doc):
        self.inserted.append((collection, doc))
        return {"_key": doc["_key"]}

    def has_view(self, name):
        return name in self.views


def run(coro):
    return asyncio.run(coro)


class _Keyed(BaseModel):
    key: ObjectIdOrKey


# ---------------------------------------------------------------------------
# ObjectIdOrKey
# ---------------------------------------------------------------------------


def test_object_id_is_kept_as_is():
    oid = ObjectId()
    assert _Keyed(key=oid).key is oid


def test_hex_string_becomes_object_id_not_str():
    # A smart-mode Union[ObjectId, str] would keep this a str.
    key = _Keyed(key=FACT_KEY).key
    assert isinstance(key, ObjectId)
    assert key == ObjectId(FACT_KEY)


@pytest.mark.parametrize("key", [OPENALEX_KEY, DOI_KEY, REC_KEY, EDGE_KEY])
def test_other_arango_keys_stay_strings(key):
    value = _Keyed(key=key).key
    assert type(value) is str and value == key


def test_uppercase_hex_stays_the_string_it_is():
    # ObjectId() would lowercase it, and the key would no longer match its row.
    key = FACT_KEY.upper()
    assert _Keyed(key=key).key == key


@pytest.mark.parametrize("bad", [
    "",
    f"facts/{FACT_KEY}",          # a full _id, not a key
    "has space",
    "x" * 255,
    123,
    None,
    ObjectId().binary,            # 12 raw bytes: PyObjectId never took those either
])
def test_non_keys_are_rejected(bad):
    with pytest.raises(ValidationError):
        _Keyed(key=bad)


@pytest.mark.parametrize("key", [ObjectId(FACT_KEY), OPENALEX_KEY])
def test_dumps_keep_python_types_and_give_strings_in_json(key):
    m = _Keyed(key=key)
    assert m.model_dump()["key"] is m.key
    assert m.model_dump(mode="json")["key"] == str(key)
    assert m.model_dump_json() == f'{{"key":"{key}"}}'


# ---------------------------------------------------------------------------
# Arango rows → models
# ---------------------------------------------------------------------------


def test_reproduction_fact_row_validates():
    fact = _doc_to_model(fact_row(), Fact)
    assert fact.id == ObjectId(FACT_KEY)          # from _key, not "facts/<key>"
    assert fact.document_id == OPENALEX_KEY
    j = fact.model_dump(mode="json", by_alias=True)
    assert j["_id"] == FACT_KEY and j["document_id"] == OPENALEX_KEY


def test_legacy_fact_row_still_gives_object_ids():
    fact = _doc_to_model(fact_row(document_id=LEGACY_DOC_KEY, general_domain=None), Fact)
    assert fact.document_id == ObjectId(LEGACY_DOC_KEY)


def test_additional_sources_mix_key_kinds():
    row = fact_row(additional_sources=[LEGACY_DOC_KEY, DOI_KEY])
    fact = _doc_to_model(row, Fact)
    assert fact.additional_sources == [ObjectId(LEGACY_DOC_KEY), DOI_KEY]
    assert [str(s) for s in fact.additional_sources] == row["additional_sources"]


@pytest.mark.parametrize("key", [OPENALEX_KEY, DOI_KEY, REC_KEY])
def test_openalex_document_row_validates(key):
    doc = _doc_to_model(document_row(key), Document)
    assert doc.id == key
    assert doc.model_dump(mode="json", by_alias=True)["_id"] == key


def test_document_taxon_relation_takes_an_openalex_document():
    rel = DocumentTaxonRelation(document_id=OPENALEX_KEY, tax_id=8030)
    assert rel.document_id == OPENALEX_KEY


# ---------------------------------------------------------------------------
# KnowledgeService over such rows
# ---------------------------------------------------------------------------


def test_search_facts_returns_reproduction_facts():
    db = FakeArango(rows=[fact_row(), fact_row("69d43f10915338a7a9da7587", LEGACY_DOC_KEY)],
                    views=[ts.FACTS_VIEW.name])
    facts = run(KnowledgeService(db).search_facts("egg size", general_domain="reproduction"))
    assert [f.document_id for f in facts] == [OPENALEX_KEY, ObjectId(LEGACY_DOC_KEY)]


def test_list_facts_by_openalex_document():
    db = FakeArango(rows=[fact_row()])
    facts = run(KnowledgeService(db).list_facts(document_id=OPENALEX_KEY))
    assert [str(f.id) for f in facts] == [FACT_KEY]
    (_, bind), = db.queries
    assert bind["document_id"] == OPENALEX_KEY


def test_get_fact_and_get_document():
    db = FakeArango(docs={("facts", FACT_KEY): fact_row(),
                          ("documents", OPENALEX_KEY): document_row()})
    svc = KnowledgeService(db)
    fact = run(svc.get_fact(FACT_KEY))
    doc = run(svc.get_document(str(fact.document_id)))
    assert doc.id == OPENALEX_KEY


def test_list_documents_of_the_reproduction_domain():
    db = FakeArango(rows=[document_row(), document_row(DOI_KEY)])
    docs = run(KnowledgeService(db).list_documents(general_domain="reproduction"))
    assert [d.id for d in docs] == [OPENALEX_KEY, DOI_KEY]


def test_relations_with_composite_edge_keys():
    db = FakeArango(rows=[edge_row()], docs={("sf_support", EDGE_KEY): edge_row()})
    svc = KnowledgeService(db)
    (listed,) = run(svc.list_relations(fact_id=FACT_KEY))
    got = run(svc.get_relation(EDGE_KEY))
    for rel in (listed, got):
        assert rel.id == EDGE_KEY
        assert rel.fact_id == ObjectId(FACT_KEY) and rel.sf_id == ObjectId(SF_KEY)


def test_create_fact_stores_document_id_as_the_document_key():
    db = FakeArango()
    fact = Fact(content="Egg size increases with female body size.",
                document_id=OPENALEX_KEY, additional_sources=[ObjectId(LEGACY_DOC_KEY)])
    run(KnowledgeService(db).create_fact(fact))
    ((collection, stored),) = db.inserted
    assert collection == "facts"
    assert stored["_key"] == str(fact.id) and "_id" not in stored
    assert stored["document_id"] == OPENALEX_KEY
    assert stored["additional_sources"] == [LEGACY_DOC_KEY]


def test_create_document_keeps_an_openalex_key():
    db = FakeArango()
    run(KnowledgeService(db).create_document(Document(id=OPENALEX_KEY, source_type="web")))
    assert [(c, d["_key"]) for c, d in db.inserted] == [("documents", OPENALEX_KEY)]


# ---------------------------------------------------------------------------
# Mongo-era writers (pipeline.py, curator_agent, DataProcessingService)
# ---------------------------------------------------------------------------


def test_mongo_writers_still_get_object_ids_from_model_dump():
    # They insert model_dump(by_alias=True) with pymongo and later query by
    # {"_id": document.id}: the ids must stay ObjectId, not become strings.
    document = Document(title="x", source_type="pdf_local")
    fact = Fact(content="c", document_id=document.id)
    sf = StylizedFact(statement="s", category="c")
    relation = FactSFRelation(fact_id=fact.id, sf_id=sf.id, relation_type="supports")

    assert isinstance(document.model_dump(by_alias=True)["_id"], ObjectId)
    fact_raw = fact.model_dump(by_alias=True)
    assert isinstance(fact_raw["_id"], ObjectId)
    assert fact_raw["document_id"] is document.id
    rel_raw = relation.model_dump(by_alias=True)
    assert rel_raw["fact_id"] is fact.id and rel_raw["sf_id"] is sf.id
