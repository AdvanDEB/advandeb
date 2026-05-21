from advandeb_kb.models.chat import make_citation_id, parse_citation_id, strip_collection_prefix


def test_strip_collection_prefix_handles_arango_ids():
    assert strip_collection_prefix("facts/abc123") == "abc123"
    assert strip_collection_prefix("abc123") == "abc123"


def test_make_citation_id_uses_canonical_prefixes():
    assert make_citation_id("chunk", "chunks/c1") == "chunk:c1"
    assert make_citation_id("fact", "facts/f1") == "fact:f1"
    assert make_citation_id("stylized_fact", "stylized_facts/s1") == "sf:s1"


def test_parse_citation_id_accepts_canonical_and_legacy_forms():
    assert parse_citation_id("chunk:c1") == ("chunk", "c1")
    assert parse_citation_id("fact:f1") == ("fact", "f1")
    assert parse_citation_id("sf:s1") == ("stylized_fact", "s1")
    assert parse_citation_id("gfact_facts/f2") == ("fact", "f2")
    assert parse_citation_id("gsf_stylized_facts/s2") == ("stylized_fact", "s2")
