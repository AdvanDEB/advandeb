"""BM25 keyword search over facts / stylized facts, and the views behind it."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from advandeb_kb.database import text_search as ts
from advandeb_kb.database.arango_client import FULLTEXT_INDEXES
from advandeb_kb.services import knowledge_service as ks
from advandeb_kb.services.knowledge_service import KnowledgeService

FACT_KEY = "69d5a833915338a7a96a58d8"
DOC_KEY = "69b8471f915338a7a9000001"
SF_KEY = "69a59b80fa961dd3552c220e"


def fact_row(key=FACT_KEY, content="Metabolic rate scales with body size."):
    # Shaped like a document straight out of ArangoDB, _id included.
    return {"_key": key, "_id": f"facts/{key}", "_rev": "_x", "content": content,
            "document_id": DOC_KEY, "status": "pending"}


def sf_row(key=SF_KEY, statement="Metabolic rate scales with body mass."):
    return {"_key": key, "_id": f"stylized_facts/{key}", "_rev": "_x",
            "statement": statement, "category": "metabolism_and_environment",
            "status": "published"}


class FakeArango:
    """ArangoDatabase stand-in: records AQL, answers from a script."""

    def __init__(self, views=(), rows=None, fail_search=False):
        self.views = set(views)
        self.rows = rows or []
        self.fail_search = fail_search
        self.queries = []
        self.view_checks = 0

    def has_view(self, name):
        self.view_checks += 1
        return name in self.views

    def aql(self, query, bind_vars=None):
        self.queries.append((query, dict(bind_vars or {})))
        if "SEARCH" in query and self.fail_search:
            raise RuntimeError("view gone")
        return list(self.rows)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# KnowledgeService.search_facts / search_stylized_facts
# ---------------------------------------------------------------------------


def test_search_facts_ranks_by_bm25_over_the_view():
    db = FakeArango(views=[ts.FACTS_VIEW.name], rows=[fact_row()])
    facts = run(KnowledgeService(db).search_facts("metabolic rate", limit=7))

    assert [str(f.id) for f in facts] == [FACT_KEY]
    (query, bind), = db.queries
    assert "SEARCH ANALYZER(doc.content IN TOKENS(@query, @analyzer), @analyzer)" in query
    assert "SORT BM25(doc) DESC" in query
    assert "general_domain" not in query
    assert bind == {"@view": ts.FACTS_VIEW.name, "query": "metabolic rate",
                    "analyzer": ts.TEXT_ANALYZER, "limit": 7}


def test_search_facts_domain_filter_goes_into_search():
    db = FakeArango(views=[ts.FACTS_VIEW.name])
    run(KnowledgeService(db).search_facts("egg size", general_domain="reproduction"))

    (query, bind), = db.queries
    assert "AND doc.general_domain == @general_domain" in query
    assert bind["general_domain"] == "reproduction"


def test_search_facts_without_view_falls_back_to_like():
    db = FakeArango(views=[], rows=[fact_row()])
    facts = run(KnowledgeService(db).search_facts("kappa rule", general_domain="reproduction"))

    assert len(facts) == 1
    (query, bind), = db.queries
    assert "FOR doc IN facts" in query
    assert "LIKE(doc.content, @q, true)" in query
    assert "doc.general_domain == @general_domain" in query
    assert "SEARCH" not in query
    assert bind["q"] == "%kappa rule%"


def test_failing_view_query_falls_back_and_forgets_the_view():
    db = FakeArango(views=[ts.FACTS_VIEW.name], rows=[fact_row()], fail_search=True)
    svc = KnowledgeService(db)
    facts = run(svc.search_facts("temperature"))

    assert len(facts) == 1
    assert ["SEARCH" in q for q, _ in db.queries] == [True, False]
    run(svc.search_facts("temperature"))
    assert db.view_checks == 2  # looked for again, not trusted from cache


def test_view_presence_is_cached_and_absence_rechecked_later(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(ks.time, "monotonic", lambda: clock[0])
    db = FakeArango(views=[])
    svc = KnowledgeService(db)

    run(svc.search_facts("a query"))
    run(svc.search_facts("a query"))
    assert db.view_checks == 1

    db.views.add(ts.FACTS_VIEW.name)  # someone runs the setup script
    clock[0] += ks._VIEW_RECHECK_SECONDS + 1
    run(svc.search_facts("a query"))
    assert db.view_checks == 2
    assert "SEARCH" in db.queries[-1][0]

    run(svc.search_facts("a query"))
    assert db.view_checks == 2


def test_search_stylized_facts_over_its_view_with_category():
    db = FakeArango(views=[ts.STYLIZED_FACTS_VIEW.name], rows=[sf_row()])
    sfs = run(KnowledgeService(db).search_stylized_facts(
        "metabolic rate", category="metabolism_and_environment", limit=5))

    assert [str(s.id) for s in sfs] == [SF_KEY]
    (query, bind), = db.queries
    assert "SEARCH ANALYZER(doc.statement IN TOKENS(@query, @analyzer), @analyzer)" in query
    assert "AND doc.category == @category" in query
    assert bind["@view"] == ts.STYLIZED_FACTS_VIEW.name
    assert bind["category"] == "metabolism_and_environment"


def test_search_stylized_facts_without_view_falls_back_to_like():
    db = FakeArango(views=[ts.FACTS_VIEW.name], rows=[sf_row()])
    run(KnowledgeService(db).search_stylized_facts("body mass", category="x"))

    (query, bind), = db.queries
    assert "FOR doc IN stylized_facts" in query
    assert "LIKE(doc.statement, @q, true)" in query
    assert "doc.category == @category" in query


@pytest.mark.parametrize("method", ["search_facts", "search_stylized_facts"])
def test_blank_query_returns_nothing_without_a_query(method):
    db = FakeArango(views=[ts.FACTS_VIEW.name, ts.STYLIZED_FACTS_VIEW.name])
    assert run(getattr(KnowledgeService(db), method)("   ")) == []
    assert db.queries == [] and db.view_checks == 0


def test_filter_on_a_field_the_view_does_not_index_is_refused():
    db = FakeArango(views=[ts.FACTS_VIEW.name])
    with pytest.raises(ValueError, match="not indexed"):
        KnowledgeService(db)._bm25_search(ts.FACTS_VIEW, "q", {"category": "x"}, 5)


def test_arango_id_does_not_shadow_the_key():
    # ArangoDB's _id is "facts/<key>", not an ObjectId; the model's id is the key.
    fact = ks._doc_to_model(fact_row(), ks.Fact)
    assert str(fact.id) == FACT_KEY


def test_no_fulltext_index_on_fields_the_views_search():
    declared = set(FULLTEXT_INDEXES)
    for view in ts.VIEWS:
        assert (view.collection, view.text_field) not in declared
    assert ("facts", "text") not in declared
    assert ("stylized_facts", "description") not in declared


# ---------------------------------------------------------------------------
# text_search: state of the analyzer and views in a (fake) database
# ---------------------------------------------------------------------------


class FakeIndexes:
    def __init__(self, count, indexes=()):
        self._count = count
        self._indexes = list(indexes)
        self.deleted = []

    def count(self):
        return self._count

    def indexes(self):
        return list(self._indexes)

    def delete_index(self, index_id):
        self.deleted.append(index_id)
        self._indexes = [i for i in self._indexes if i["id"].split("/")[-1] != index_id]


class FakeCursorAQL:
    def __init__(self, db):
        self.db = db

    def execute(self, query, bind_vars=None):
        view = bind_vars["@view"]
        collection = next(v.collection for v in ts.VIEWS if v.name == view)
        return iter([self.db.collections[collection].count()])


class FakeRawDB:
    """python-arango StandardDatabase stand-in."""

    def __init__(self, analyzer=None, views=None, collections=None):
        self._analyzer = analyzer
        self._views = dict(views or {})
        self.collections = collections or {}
        self.aql = FakeCursorAQL(self)
        self.calls = []

    def analyzer(self, name):
        if self._analyzer is None:
            raise RuntimeError("analyzer not found")
        return self._analyzer

    def views(self):
        return [{"name": n, "type": "arangosearch"} for n in self._views]

    def view(self, name):
        return self._views[name]

    def has_collection(self, name):
        return name in self.collections

    def collection(self, name):
        return self.collections[name]

    def create_analyzer(self, name, analyzer_type, properties, features):
        self.calls.append(("create_analyzer", name))
        self._analyzer = {"type": analyzer_type, "properties": properties, "features": features}

    def create_arangosearch_view(self, name, properties):
        self.calls.append(("create_view", name))
        self._views[name] = {"name": name, "links": stored_links(properties["links"])}

    def update_arangosearch_view(self, name, properties):
        self.calls.append(("update_view", name))
        self._views[name]["links"].update(stored_links(properties["links"]))


def stored_links(links):
    """What ArangoDB hands back: identity-only fields stored as {}."""
    out = {}
    for collection, link in links.items():
        fields = {f: ({} if spec["analyzers"] == ["identity"] else spec)
                  for f, spec in link["fields"].items()}
        out[collection] = {"analyzers": ["identity"], "fields": fields}
    return out


def good_analyzer():
    return {"type": ts.ANALYZER_TYPE, "properties": dict(ts.ANALYZER_PROPERTIES),
            "features": list(ts.ANALYZER_FEATURES)}


def test_analyzer_state():
    assert ts.analyzer_state(FakeRawDB()) == "missing"
    assert ts.analyzer_state(FakeRawDB(analyzer=good_analyzer())) == "ok"
    other = good_analyzer()
    other["properties"]["stemming"] = False
    other["features"] = ["frequency", "norm", "position"]
    assert ts.analyzer_state(FakeRawDB(analyzer=other)) == "differs in stemming, features"


def test_view_state():
    view = ts.FACTS_VIEW
    assert ts.view_state(FakeRawDB(), view) == "missing"
    assert ts.view_state(FakeRawDB(views={view.name: {"links": {}}}), view) == "link missing"

    links = stored_links({view.collection: view.link()})
    db = FakeRawDB(views={view.name: {"links": links}})
    assert ts.view_state(db, view) == "ok"  # identity field stored as {} still matches

    links[view.collection]["fields"]["content"] = {"analyzers": ["text_en"]}
    assert ts.view_state(db, view) == "field 'content' differs"
    del links[view.collection]["fields"]["general_domain"]
    links[view.collection]["fields"]["content"] = {"analyzers": [ts.TEXT_ANALYZER]}
    assert ts.view_state(db, view) == "field 'general_domain' missing"


# ---------------------------------------------------------------------------
# scripts/setup_facts_search_views.py
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_facts_search_views.py"


@pytest.fixture
def setup_script():
    spec = importlib.util.spec_from_file_location("setup_facts_search_views", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fresh_db():
    stale = {"id": "facts/800", "type": "fulltext", "fields": ["text"]}
    return FakeRawDB(collections={
        "facts": FakeIndexes(109_395, [{"id": "facts/0", "type": "primary", "fields": ["_key"]}, stale]),
        "stylized_facts": FakeIndexes(1_236),
    })


def run_script(module, monkeypatch, db, *argv):
    monkeypatch.setattr(module, "connect", lambda name: db)
    monkeypatch.setattr("sys.argv", ["setup_facts_search_views.py", *argv])
    return module.main()


def test_dry_run_changes_nothing(setup_script, monkeypatch, capsys):
    db = fresh_db()
    assert run_script(setup_script, monkeypatch, db, "--db", "kb_scratch") == 0
    assert db.calls == []
    out = capsys.readouterr().out
    assert "Dry run" in out and "stale FULLTEXT index facts.text" in out


def test_apply_on_scratch_creates_everything_once(setup_script, monkeypatch, capsys):
    db = fresh_db()
    assert run_script(setup_script, monkeypatch, db, "--db", "kb_scratch", "--apply",
                      "--wait", "--drop-stale-fulltext") == 0
    assert db.calls == [("create_analyzer", ts.TEXT_ANALYZER),
                        ("create_view", ts.FACTS_VIEW.name),
                        ("create_view", ts.STYLIZED_FACTS_VIEW.name)]
    assert db.collections["facts"].deleted == ["800"]

    db.calls.clear()
    assert run_script(setup_script, monkeypatch, db, "--db", "kb_scratch", "--apply") == 0
    assert db.calls == []
    assert "Nothing to do." in capsys.readouterr().out


def test_production_needs_the_flag(setup_script, monkeypatch, capsys):
    db = fresh_db()
    assert run_script(setup_script, monkeypatch, db, "--db", "advandeb_kb", "--apply") == 2
    assert db.calls == []
    assert "Refusing: this is a production database" in capsys.readouterr().out


def test_production_needs_a_recent_backup(setup_script, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ADVANDEB_BACKUP_DIR", str(tmp_path / "no-backups"))
    db = fresh_db()
    assert run_script(setup_script, monkeypatch, db, "--db", "advandeb_kb",
                      "--production", "--apply") == 2
    assert db.calls == []
    assert "no successful backup" in capsys.readouterr().out


def test_existing_analyzer_with_other_settings_is_refused(setup_script, monkeypatch):
    db = fresh_db()
    db._analyzer = good_analyzer()
    db._analyzer["properties"]["stemming"] = False
    assert run_script(setup_script, monkeypatch, db, "--db", "kb_scratch", "--apply") == 2
    assert db.calls == []
