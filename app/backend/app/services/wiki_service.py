"""
The workshop wiki: the results of the AdvanDEB workshop of November 2026 in
Croatian and English, as built by ``app/scripts/wiki/build_wiki.py``. It is the
reader's edition. The builder leaves out recordings, transcripts and the vault's
housekeeping notes, and cites workshop sessions instead of recordings.

The bundle lives outside the repository (``settings.WIKI_BUNDLE_PATH``). It
carries summaries of internal project documents, and the repository is public. The store re-reads the file whenever its mtime changes, so
publishing means replacing the file; the builder writes it atomically.

Every note has a tier:

* ``open`` notes are for any signed-in member;
* ``internal`` notes (summaries of project documents) need the
  ``workshop_wiki_internal`` capability;
* ``raw`` notes are for administrators only. The current builder emits none,
  but the tier stays reserved so that raw material can never fall through to
  ``open``.

Administrators see everything. The filtering happens here, before anything is
serialised. The index, a note's links and backlinks, the graph and search all
drop what the caller may not open, and a link inside a note's text to such a
note becomes plain text. Without that, a backlink list or a link title would
still say that a hidden document exists and what it is called.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import unicodedata
from functools import lru_cache
from typing import Optional

CAP_WIKI_INTERNAL = "workshop_wiki_internal"
LANGS = ("hr", "en")

# The link shapes build_wiki.py emits (Vault.anchor); keep the two in step.
# A transcript link inside an audio embed is dropped with its separator; any
# other link to a hidden note keeps its text and loses the link.
_REC_LINK = re.compile(r' · <a class="wl wl-rec" href="[^"]*" data-id="([^"]*)">.*?</a>')
_LINK = re.compile(r'<a class="wl" href="[^"]*" data-id="([^"]*)">(.*?)</a>')
_TAG = re.compile(r"<[^>]+>")
_MD_SYMBOLS = re.compile(r"[#*_`>|]+|^\s*[-+]\s+", re.M)
_SPACE = re.compile(r"\s+")

# Transcripts are long and noisy; they should not crowd out the notes that
# summarise them.
_SECTION_WEIGHT = {"transcripts": 0.4}


class WikiUnavailable(Exception):
    """No bundle has been published on this server (or it is unreadable)."""


def tiers_for(user: dict) -> frozenset:
    roles = user.get("roles", []) or []
    caps = user.get("capabilities", []) or []
    if "administrator" in roles:
        return frozenset({"open", "internal", "raw"})
    if CAP_WIKI_INTERNAL in caps:
        return frozenset({"open", "internal"})
    return frozenset({"open"})


@lru_cache(maxsize=4096)
def _fold_char(ch: str) -> str:
    if ch in "đĐ":
        return "d"
    base = unicodedata.normalize("NFD", ch)[0].lower()
    return base[:1] or ch


def fold(text: str) -> str:
    """Lower case without diacritics, one character per character, so an index
    into the folded text is an index into the original."""
    return "".join(_fold_char(c) for c in text)


def plain_text(md: str) -> str:
    text = html.unescape(_TAG.sub(" ", md))
    return _SPACE.sub(" ", _MD_SYMBOLS.sub(" ", text)).strip()


def _hide_links(md: Optional[str], visible: set) -> Optional[str]:
    if md is None:
        return None
    md = _REC_LINK.sub(lambda m: m.group(0) if html.unescape(m.group(1)) in visible else "", md)
    return _LINK.sub(
        lambda m: m.group(0) if html.unescape(m.group(1)) in visible
        else f'<span class="wl wl-hidden">{m.group(2)}</span>',
        md,
    )


class WikiStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._mtime: Optional[float] = None
        self._bundle: Optional[dict] = None
        self._search: dict = {}

    # -- loading ----------------------------------------------------------- #

    def bundle(self) -> dict:
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            raise WikiUnavailable(self.path)
        if mtime != self._mtime:
            with self._lock:
                if mtime != self._mtime:
                    self._load(mtime)
        return self._bundle

    def _load(self, mtime: float) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                bundle = json.load(fh)
            notes = bundle["notes"]
        except (OSError, ValueError, KeyError) as exc:
            raise WikiUnavailable(f"{self.path}: {exc}")
        search = {}
        for nid, n in notes.items():
            titles = " ".join([n["title"]["hr"], n["title"].get("en") or "", *n.get("aliases", [])])
            entry = {"title": fold(titles)}
            for lang in LANGS:
                md = n["md"].get(lang)
                if md is None:
                    md = n["md"]["hr"]
                text = plain_text(md)
                entry[lang] = (text, fold(text))
            search[nid] = entry
        self._bundle, self._search, self._mtime = bundle, search, mtime

    # -- views ------------------------------------------------------------- #

    def _visible(self, user: dict) -> set:
        tiers = tiers_for(user)
        return {nid for nid, n in self.bundle()["notes"].items() if n.get("tier", "open") in tiers}

    def index(self, user: dict) -> dict:
        bundle = self.bundle()
        visible = self._visible(user)
        notes = []
        for nid in visible:
            n = bundle["notes"][nid]
            notes.append({
                "id": nid,
                "section": n["section"],
                "type": n["type"],
                "tags": n.get("tags", []),
                "aliases": n.get("aliases", []),
                "title": n["title"],
                "en_status": n["en_status"],
                "updated": n.get("updated"),
                "badges": n.get("badges", {}),
                "n_links": len([x for x in n["out"] if x in visible]),
            })
        return {
            "built": bundle.get("built"),
            "sections": bundle.get("sections", []),
            "tiers": sorted(tiers_for(user)),
            "notes": notes,
        }

    def note(self, user: dict, note_id: str) -> Optional[dict]:
        bundle = self.bundle()
        visible = self._visible(user)
        if note_id not in visible:
            # Hidden and absent look the same: a 404 either way.
            return None
        n = bundle["notes"][note_id]
        md = {lang: _hide_links(n["md"].get(lang), visible) for lang in LANGS}
        assets = {}
        for name, uri in bundle.get("assets", {}).items():
            if any(f'data-asset="{html.escape(name)}"' in (m or "") for m in md.values()):
                assets[name] = uri
        return {
            "id": note_id,
            "section": n["section"],
            "tier": n.get("tier", "open"),
            "type": n["type"],
            "tags": n.get("tags", []),
            "aliases": n.get("aliases", []),
            "created": n.get("created"),
            "updated": n.get("updated"),
            "title": n["title"],
            "en_status": n["en_status"],
            "badges": n.get("badges", {}),
            "md": md,
            "out": [x for x in n["out"] if x in visible],
            "in": [x for x in n["in"] if x in visible],
            "assets": assets,
        }

    def graph(self, user: dict) -> dict:
        notes = self.bundle()["notes"]
        visible = self._visible(user)
        edges = [[a, b] for a in sorted(visible) for b in notes[a]["out"] if b in visible]
        degree = {nid: 0 for nid in visible}
        for a, b in edges:
            degree[a] += 1
            degree[b] += 1
        return {
            "nodes": [{"id": nid, "section": notes[nid]["section"], "degree": degree[nid]}
                      for nid in sorted(visible)],
            "edges": edges,
        }

    def search(self, user: dict, q: str, lang: str, limit: int = 40) -> list:
        notes = self.bundle()["notes"]
        terms = [t for t in fold(q).split() if t]
        if not terms:
            return []
        results = []
        for nid in self._visible(user):
            entry = self._search[nid]
            text, folded = entry[lang]
            score = 0.0
            for term in terms:
                in_title = term in entry["title"]
                hits = folded.count(term)
                if not in_title and not hits:
                    break
                score += (10 if in_title else 0) + min(5, hits)
            else:
                score *= _SECTION_WEIGHT.get(notes[nid]["section"], 1.0)
                pos = folded.find(terms[0])
                start = max(0, pos - 70) if pos >= 0 else 0
                snippet = text[start:start + 220]
                results.append({
                    "id": nid,
                    "section": notes[nid]["section"],
                    "title": notes[nid]["title"],
                    "snippet": ("…" if start else "") + snippet + ("…" if start + 220 < len(text) else ""),
                    "score": round(score, 2),
                })
        results.sort(key=lambda r: (-r["score"], r["id"]))
        return results[:limit]


_stores: dict = {}


def get_wiki_store(path: str) -> WikiStore:
    """One store per bundle path (tests point the setting at a temp file)."""
    store = _stores.get(path)
    if store is None:
        store = _stores[path] = WikiStore(path)
    return store
