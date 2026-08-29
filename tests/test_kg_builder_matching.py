"""Unit tests for document→taxon name matching.

In-process only — no database. They pin the ambiguity guard, which is the part
of the linker most likely to regress silently: loosening it floods the graph
with false links, tightening it quietly drops real organisms.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "knowledge-builder"))

from advandeb_kb.services.kg_builder_service import (  # noqa: E402
    _match_document,
    _index_entries_for_single_token,
    _AMBIGUOUS_TAXON_NAMES,
    _SINGLE_TOKEN_RANKS,
)


# A stand-in name index: normalized name -> [(tax_id, rank), ...]
INDEX = {
    "danio rerio": [(7955, "species")],
    "zebrafish": [(7955, "species")],
    "mytilus edulis": [(6550, "species")],
    "daphnia": [(6668, "genus")],
    "drosophila": [(7215, "genus")],
    "cancer": [(6752, "genus")],          # the crab genus
    "data": [(1911170, "genus")],         # a real NCBI moth genus
    "animals": [(33208, "kingdom")],
    "fish": [(7898, "superclass")],
    "muridae": [(10066, "family")],
}


def taxa_of(edges):
    return {e["_to"] for e in edges}


def test_binomial_in_title_is_matched():
    edges = _match_document({"_key": "d1", "title": "Growth of Danio rerio under stress"}, INDEX, "now")
    assert taxa_of(edges) == {"taxa/7955"}
    assert edges[0]["relation_type"] == "studies"
    assert edges[0]["status"] == "suggested"


def test_common_name_survives_the_guard():
    """Zebrafish/Daphnia are exactly what the linker exists to find."""
    edges = _match_document({"_key": "d2", "title": "Zebrafish energetics"}, INDEX, "now")
    assert taxa_of(edges) == {"taxa/7955"}

    edges = _match_document({"_key": "d3", "title": "Daphnia population dynamics"}, INDEX, "now")
    assert taxa_of(edges) == {"taxa/6668"}


def test_english_homograph_genus_is_blocked():
    """The crab genus Cancer must not claim every oncology paper."""
    edges = _match_document({"_key": "d4", "title": "Cancer risk in aquatic mammals"}, INDEX, "now")
    assert taxa_of(edges) == set()

    edges = _match_document({"_key": "d5", "title": "Data driven modelling of growth"}, INDEX, "now")
    assert taxa_of(edges) == set()


def test_coarse_ranks_are_not_matched_from_a_lone_word():
    """"This paper studies Animalia" is true and useless."""
    for title in ("Animals in cold climates", "Fish physiology review", "Muridae diversity"):
        edges = _match_document({"_key": "d6", "title": title}, INDEX, "now")
        assert taxa_of(edges) == set(), title


def test_multiword_names_bypass_the_single_token_rules():
    """Binomials are unambiguous, so rank floor and blocklist don't apply."""
    edges = _match_document({"_key": "d7", "title": "Mytilus edulis filtration rates"}, INDEX, "now")
    assert taxa_of(edges) == {"taxa/6550"}


def test_abstract_matching_requires_a_binomial():
    """A lone capitalised word in prose is far too weak a signal."""
    edges = _match_document(
        {"_key": "d8", "title": "A model", "abstract": "We studied Daphnia in the lab."}, INDEX, "now"
    )
    assert taxa_of(edges) == set()

    edges = _match_document(
        {"_key": "d9", "title": "A model", "abstract": "We studied Danio rerio in the lab."}, INDEX, "now"
    )
    assert taxa_of(edges) == {"taxa/7955"}


def test_title_match_scores_above_abstract_match():
    title = _match_document({"_key": "a", "title": "Danio rerio growth"}, INDEX, "now")[0]
    abstract = _match_document(
        {"_key": "b", "title": "Growth", "abstract": "on Danio rerio"}, INDEX, "now"
    )[0]
    assert title["confidence"] > abstract["confidence"]


def test_single_token_helper_filters_by_rank_and_blocklist():
    assert _index_entries_for_single_token("daphnia", INDEX) == [(6668, "genus")]
    assert _index_entries_for_single_token("cancer", INDEX) == []
    assert _index_entries_for_single_token("animals", INDEX) == []
    # Unknown names simply resolve to nothing rather than raising.
    assert _index_entries_for_single_token("nonesuch", INDEX) == []


def test_guard_constants_are_coherent():
    assert _AMBIGUOUS_TAXON_NAMES == {n.lower() for n in _AMBIGUOUS_TAXON_NAMES}, "must be normalized"
    assert "species" in _SINGLE_TOKEN_RANKS and "genus" in _SINGLE_TOKEN_RANKS
    assert not {"family", "order", "class", "kingdom"} & _SINGLE_TOKEN_RANKS
