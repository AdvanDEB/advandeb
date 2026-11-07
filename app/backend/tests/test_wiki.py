"""
The workshop wiki serves a bundle file, filtered by the caller's tier.

What must hold is that a note a caller may not open leaves no trace in what
they get back: it is not in the index, in a note's links or backlinks, in the
graph or in search, and a link to it inside a note's text is reduced to its
words. Hidden and absent notes both answer 404.

No database: the bundle is a temp file, the users come from the in-memory
stand-in in conftest.py.
"""
import json
import os
from urllib.parse import quote

import pytest

from app.services.wiki_service import CAP_WIKI_INTERNAL, fold, get_wiki_store


def _link(nid, text, lang="hr", cls="wl"):
    # The shape app/scripts/wiki/build_wiki.py emits (Vault.anchor).
    return f'<a class="{cls}" href="/wiki/{lang}/n/{quote(nid, safe="")}" data-id="{nid}">{text}</a>'


def _note(nid, section, tier, md_hr, md_en=None, out=(), inn=(), title_en=None):
    return {
        "id": nid, "section": section, "tier": tier, "type": "pojam", "tags": ["tema/tdeb"],
        "aliases": [], "created": "2026-11-03", "updated": "2026-11-04",
        "title": {"hr": nid, "en": title_en},
        "md": {"hr": md_hr, "en": md_en},
        "en_status": "ok" if md_en is not None else "missing",
        "badges": {"R": 1}, "out": list(out), "in": list(inn),
    }


BUNDLE = {
    "version": 1,
    "built": "2026-11-07T12:00",
    "sections": ["concepts", "drive"],
    "notes": {
        "Slaba homeostaza": _note(
            "Slaba homeostaza", "concepts", "open",
            "- `R` Vidi " + _link("Čovjek", "čovjeka") + " i " + _link("Interni izvještaj", "izvještaj C1")
            + ' · <span class="audio-embed">🎙 X' + " · " + _link("Tajna", "transkript", cls="wl wl-rec") + "</span>"
            + "\n- Ključna riječ kvazistacionarnost.",
            "- `R` See " + _link("Čovjek", "human", "en") + " and " + _link("Interni izvještaj", "report C1", "en"),
            out=["Čovjek", "Interni izvještaj", "Tajna"], title_en="Weak homeostasis"),
        "Čovjek": _note("Čovjek", "concepts", "open", "Organizam.", "Organism.",
                        inn=["Slaba homeostaza", "Interni izvještaj"], title_en="Human"),
        "Interni izvještaj": _note(
            "Interni izvještaj", "drive", "internal", "Tajni projektni podatak " + _link("Čovjek", "čovjek") + ".",
            out=["Čovjek"], inn=["Slaba homeostaza"]),
        "Tajna": _note("Tajna", "drive", "raw", "Sirova građa.", inn=["Slaba homeostaza"]),
    },
    "assets": {},
}


@pytest.fixture
def bundle_path(tmp_path, monkeypatch):
    from app.core.config import settings
    path = tmp_path / "wiki-bundle.json"
    path.write_text(json.dumps(BUNDLE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "WIKI_BUNDLE_PATH", str(path))
    return path


@pytest.fixture
def readers(make_user):
    return {
        "member": make_user("member@example.org", roles=["knowledge_explorator"]),
        "insider": make_user("insider@example.org", roles=["knowledge_explorator"],
                             capabilities=[CAP_WIKI_INTERNAL]),
        "admin": make_user("admin@example.org", roles=["administrator"]),
    }


def _get(client, auth_header, user, path, **params):
    return client.get(path, headers=auth_header(user), params=params)


def _ids(index):
    return {n["id"] for n in index["notes"]}


def test_index_follows_the_tier(client, auth_header, readers, bundle_path):
    seen = {who: _ids(_get(client, auth_header, u, "/api/wiki/index").json()) for who, u in readers.items()}
    assert seen["member"] == {"Slaba homeostaza", "Čovjek"}
    assert seen["insider"] == {"Slaba homeostaza", "Čovjek", "Interni izvještaj"}
    assert seen["admin"] == set(BUNDLE["notes"])


def test_a_member_sees_no_trace_of_hidden_notes(client, auth_header, readers, bundle_path):
    note = _get(client, auth_header, readers["member"], "/api/wiki/notes/" + quote("Slaba homeostaza")).json()
    assert note["out"] == ["Čovjek"]
    for md in note["md"].values():
        assert 'data-id="Interni izvještaj"' not in md
        assert "Tajna" not in md and "transkript" not in md
        assert 'data-id="Čovjek"' in md
    # The words of a hidden link stay, the link does not.
    assert '<span class="wl wl-hidden">izvještaj C1</span>' in note["md"]["hr"]

    human = _get(client, auth_header, readers["member"], "/api/wiki/notes/" + quote("Čovjek")).json()
    assert human["in"] == ["Slaba homeostaza"]

    graph = _get(client, auth_header, readers["member"], "/api/wiki/graph").json()
    assert {n["id"] for n in graph["nodes"]} == {"Slaba homeostaza", "Čovjek"}
    assert graph["edges"] == [["Slaba homeostaza", "Čovjek"]]


def test_hidden_and_absent_notes_both_404(client, auth_header, readers, bundle_path):
    for nid in ("Interni izvještaj", "Tajna", "Nema je"):
        r = _get(client, auth_header, readers["member"], "/api/wiki/notes/" + quote(nid))
        assert r.status_code == 404, nid
    r = _get(client, auth_header, readers["insider"], "/api/wiki/notes/" + quote("Tajna"))
    assert r.status_code == 404
    r = _get(client, auth_header, readers["insider"], "/api/wiki/notes/" + quote("Interni izvještaj"))
    assert r.status_code == 200
    assert r.json()["in"] == ["Slaba homeostaza"]


def test_search_ignores_diacritics_and_respects_the_tier(client, auth_header, readers, bundle_path):
    hits = _get(client, auth_header, readers["member"], "/api/wiki/search", q="kvazistacionarnost").json()["results"]
    assert [h["id"] for h in hits] == ["Slaba homeostaza"]
    # "covjek" finds "Čovjek" by its title.
    hits = _get(client, auth_header, readers["member"], "/api/wiki/search", q="covjek").json()["results"]
    assert hits[0]["id"] == "Čovjek"
    # The internal note's text is not searchable for a member …
    assert _get(client, auth_header, readers["member"], "/api/wiki/search", q="tajni").json()["results"] == []
    # … but is for someone who may read it.
    hits = _get(client, auth_header, readers["insider"], "/api/wiki/search", q="tajni").json()["results"]
    assert [h["id"] for h in hits] == ["Interni izvještaj"]


def test_english_falls_back_to_croatian(client, auth_header, readers, bundle_path):
    note = _get(client, auth_header, readers["admin"], "/api/wiki/notes/" + quote("Interni izvještaj")).json()
    assert note["md"]["en"] is None and note["en_status"] == "missing"
    hits = _get(client, auth_header, readers["admin"], "/api/wiki/search", q="projektni", lang="en").json()["results"]
    assert [h["id"] for h in hits] == ["Interni izvještaj"]


def test_a_replaced_bundle_is_picked_up(client, auth_header, readers, bundle_path):
    assert len(_get(client, auth_header, readers["member"], "/api/wiki/index").json()["notes"]) == 2
    changed = json.loads(json.dumps(BUNDLE))
    changed["notes"]["Novi pojam"] = _note("Novi pojam", "concepts", "open", "Novo.")
    bundle_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    st = os.stat(bundle_path)
    os.utime(bundle_path, (st.st_atime, st.st_mtime + 5))
    assert "Novi pojam" in _ids(_get(client, auth_header, readers["member"], "/api/wiki/index").json())


def test_no_bundle_is_a_clear_503(client, auth_header, readers, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "WIKI_BUNDLE_PATH", str(tmp_path / "missing.json"))
    r = _get(client, auth_header, readers["member"], "/api/wiki/index")
    assert r.status_code == 503
    assert "not been published" in r.json()["detail"]


def test_reload_is_for_administrators(client, auth_header, readers, bundle_path):
    r = client.post("/api/wiki/reload", headers=auth_header(readers["member"]))
    assert r.status_code == 403
    r = client.post("/api/wiki/reload", headers=auth_header(readers["admin"]))
    assert r.status_code == 200 and r.json()["notes"] == len(BUNDLE["notes"])


def test_fold_keeps_positions():
    text = "Đurđa čita Š-ž KAPPA κ"
    assert len(fold(text)) == len(text)
    assert fold(text).startswith("durda cita s-z kappa")


def test_one_store_per_path(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert get_wiki_store(str(a)) is get_wiki_store(str(a))
    assert get_wiki_store(str(a)) is not get_wiki_store(str(b))
