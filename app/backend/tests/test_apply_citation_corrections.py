"""The citation-correction plan: what would be written to ArangoDB.

No database. The script is a production write, so what it decides to change
is tested on its own: only high-confidence corrections, only the fields asked
for, and never a value that changed since the report computed the fix.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_citation_corrections.py"


def _mod():
    spec = importlib.util.spec_from_file_location("apply_citation_corrections", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CORRECTIONS = {
    "k1": {"collections": ["documents", "document_meta"], "corpus": "deb",
           "n_passages": 30, "fields": {
               "doi": {"old": "10.1109/20.280868", "new": None, "confidence": "high"},
               "journal": {"old": "None", "new": "CUP", "confidence": "high"}}},
    "k2": {"collections": ["documents"], "corpus": "deb", "n_passages": 2,
           "fields": {"doi": {"old": "x", "new": "10.1/y", "confidence": "medium"}}},
    "k3": {"collections": ["documents"], "corpus": "reproduction", "n_passages": 1,
           "fields": {"doi": {"old": "10.1/a", "new": "10.1/b", "confidence": "high"}}},
}
STORED = {
    ("documents", "k1"): {"doi": "10.1109/20.280868", "journal": "None"},
    ("document_meta", "k1"): {"doi": "10.1109/20.280868", "journal": "None"},
    ("documents", "k2"): {"doi": "x"},
    ("documents", "k3"): {"doi": "10.1/changed-since"},
}


def test_only_high_confidence_and_requested_fields_are_planned():
    updates, skipped = _mod().plan(CORRECTIONS, ("doi",),
                                   lambda c, k: STORED.get((c, k)))
    assert [(u["collection"], u["key"], u["set"]) for u in updates] == [
        ("documents", "k1", {"doi": None}), ("document_meta", "k1", {"doi": None})]
    assert updates[0]["previous"] == {"doi": "10.1109/20.280868"}
    # k2 is medium confidence; k3 changed since the report and is not touched.
    assert skipped == ["documents/k3.doi: stored value changed since the report"]


def test_all_fields_and_a_missing_record():
    updates, skipped = _mod().plan(CORRECTIONS, ("doi", "journal"),
                                   lambda c, k: None if c == "document_meta" else STORED.get((c, k)))
    assert updates[0]["set"] == {"doi": None, "journal": "CUP"}
    assert "document_meta/k1: not found" in skipped
