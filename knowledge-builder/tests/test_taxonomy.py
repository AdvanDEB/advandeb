"""
Tests for the NCBI taxonomy importer (parser + lineage builder).
No network calls, no MongoDB required.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.import_taxonomy import (
    parse_nodes,
    parse_names,
    build_lineages,
    iter_documents,
)


def _nodes_dmp(rows: list[tuple]) -> io.BytesIO:
    """Build a minimal nodes.dmp byte stream from (tax_id, parent_id, rank) tuples."""
    lines = []
    for tax_id, parent_id, rank in rows:
        # nodes.dmp format: tax_id\t|\tparent_tax_id\t|\trank\t|\t...\t|
        lines.append(f"{tax_id}\t|\t{parent_id}\t|\t{rank}\t|\t\t|\n")
    return io.BytesIO("".join(lines).encode())


def _names_dmp(rows: list[tuple]) -> io.BytesIO:
    """Build a minimal names.dmp byte stream from (tax_id, name, name_class) tuples."""
    lines = []
    for tax_id, name, name_class in rows:
        lines.append(f"{tax_id}\t|\t{name}\t|\t\t|\t{name_class}\t|\n")
    return io.BytesIO("".join(lines).encode())


# ------------------------------------------------------------------
# parse_nodes
# ------------------------------------------------------------------

def test_parse_nodes_basic():
    dmp = _nodes_dmp([
        (1, 1, "no rank"),        # root — parent == self
        (2, 1, "domain"),
        (9606, 9605, "species"),
        (9605, 9604, "genus"),
        (9604, 9443, "family"),
    ])
    nodes = parse_nodes(dmp)
    assert len(nodes) == 5
    assert nodes[1]["parent_tax_id"] is None   # root: parent_id == self → None
    assert nodes[2]["parent_tax_id"] == 1
    assert nodes[9606]["rank"] == "species"
    assert nodes[9606]["parent_tax_id"] == 9605
    print("  parse_nodes basic OK")


def test_parse_nodes_skips_short_lines():
    raw = b"9606\t|\t9605\n"   # only 2 fields, should be skipped
    nodes = parse_nodes(io.BytesIO(raw))
    assert len(nodes) == 0
    print("  parse_nodes skips short lines OK")


# ------------------------------------------------------------------
# parse_names
# ------------------------------------------------------------------

def test_parse_names_classes():
    dmp = _names_dmp([
        (9606, "Homo sapiens", "scientific name"),
        (9606, "Man",          "common name"),
        (9606, "human",        "genbank common name"),
        (9606, "Homo sapiens Linnaeus", "synonym"),
        (9606, "H. sapiens",   "equivalent name"),
        (9606, "ignored",      "blast name"),   # unknown class → ignored
    ])
    names = parse_names(dmp)
    assert names[9606]["name"] == "Homo sapiens"
    assert "Man" in names[9606]["common_names"]
    assert "human" in names[9606]["common_names"]
    assert "Homo sapiens Linnaeus" in names[9606]["synonyms"]
    assert "H. sapiens" in names[9606]["synonyms"]
    assert "ignored" not in names[9606]["synonyms"]
    assert "ignored" not in names[9606]["common_names"]
    print("  parse_names classes OK")


# ------------------------------------------------------------------
# build_lineages
# ------------------------------------------------------------------

def _small_tree():
    """
    Root(1) → Domain(2) → Family(3) → Genus(4) → Species(5)
    """
    nodes = {
        1: {"parent_tax_id": None, "rank": "no rank"},
        2: {"parent_tax_id": 1,    "rank": "domain"},
        3: {"parent_tax_id": 2,    "rank": "family"},
        4: {"parent_tax_id": 3,    "rank": "genus"},
        5: {"parent_tax_id": 4,    "rank": "species"},
    }
    return nodes


def test_build_lineages_full():
    nodes = _small_tree()
    lineages = build_lineages(nodes)
    assert lineages[1] == []           # root has no ancestors
    assert lineages[2] == [1]
    assert lineages[5] == [1, 2, 3, 4]
    print("  build_lineages full OK")


def test_build_lineages_subtree():
    nodes = _small_tree()
    lineages = build_lineages(nodes, root_taxid=3)
    # Only family(3), genus(4), species(5) should be in the subtree
    assert set(lineages.keys()) == {3, 4, 5}
    assert lineages[3] == [1, 2]       # ancestors still included in lineage
    assert lineages[5] == [1, 2, 3, 4]
    print("  build_lineages subtree OK")


def test_build_lineages_no_cycle():
    """A self-referencing root should not produce an infinite loop."""
    nodes = {
        1: {"parent_tax_id": None, "rank": "no rank"},
        2: {"parent_tax_id": 1,    "rank": "species"},
    }
    lineages = build_lineages(nodes)
    assert lineages[1] == []
    assert lineages[2] == [1]
    print("  build_lineages no cycle OK")


# ------------------------------------------------------------------
# iter_documents
# ------------------------------------------------------------------

def test_iter_documents_fields():
    nodes = _small_tree()
    names = {
        1: {"name": "root",         "synonyms": [],      "common_names": []},
        2: {"name": "Eukaryota",    "synonyms": [],      "common_names": ["eukaryotes"]},
        3: {"name": "Hominidae",    "synonyms": ["apes"], "common_names": []},
        4: {"name": "Homo",         "synonyms": [],      "common_names": []},
        5: {"name": "Homo sapiens", "synonyms": ["Man"], "common_names": ["human"]},
    }
    lineages = build_lineages(nodes)
    docs = list(iter_documents(nodes, names, lineages))
    assert len(docs) == 5

    species_doc = next(d for d in docs if d["tax_id"] == 5)
    assert species_doc["name"] == "Homo sapiens"
    assert species_doc["rank"] == "species"
    assert species_doc["parent_tax_id"] == 4
    assert species_doc["lineage"] == [1, 2, 3, 4]
    assert "Man" in species_doc["synonyms"]
    assert "human" in species_doc["common_names"]
    assert species_doc["ncbi_sourced"] is True
    assert species_doc["gbif_usage_key"] is None
    assert "created_at" in species_doc
    print("  iter_documents fields OK")


def test_iter_documents_missing_name_fallback():
    """Nodes with no entry in names dict get a fallback name."""
    nodes = {1: {"parent_tax_id": None, "rank": "no rank"}}
    names = {}   # empty
    lineages = build_lineages(nodes)
    docs = list(iter_documents(nodes, names, lineages))
    assert docs[0]["name"] == "taxon:1"
    print("  iter_documents missing name fallback OK")


if __name__ == "__main__":
    tests = [
        test_parse_nodes_basic,
        test_parse_nodes_skips_short_lines,
        test_parse_names_classes,
        test_build_lineages_full,
        test_build_lineages_subtree,
        test_build_lineages_no_cycle,
        test_iter_documents_fields,
        test_iter_documents_missing_name_fallback,
    ]
    print(f"Running {len(tests)} taxonomy importer tests...")
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")
