"""
Smoke tests for all knowledge-builder data models.
Run with: conda run -n advandeb-modeling-assistant python3 tests/test_models.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from advandeb_kb.models.common import PyObjectId
from advandeb_kb.models.knowledge import Document, Fact, StylizedFact, FactSFRelation
from advandeb_kb.models.taxonomy import TaxonomyNode
from advandeb_kb.models.graph import (
    GraphSchema, GraphNode, GraphEdge, BUILTIN_SCHEMAS,
    NodeTypeDefinition, EdgeTypeDefinition,
)
from advandeb_kb.models.ingestion import IngestionBatch, IngestionJob


def test_pyobjectid():
    # Accepts ObjectId directly
    oid = ObjectId()
    assert PyObjectId.__class__  # type is defined

    # Validated via model field
    doc = Document(title="x", source_type="manual")
    assert isinstance(doc.id, ObjectId)

    # String input is coerced to ObjectId
    doc2 = Document(**{"_id": str(doc.id), "title": "x", "source_type": "manual"})
    assert doc2.id == doc.id

    # Serializes to string in JSON mode (by_alias=True to get "_id" key)
    j = doc.model_dump(mode="json", by_alias=True)
    assert isinstance(j["_id"], str)
    print("  PyObjectId OK")


def test_document():
    doc = Document(
        title="Test Paper",
        doi="10.1234/test",
        source_type="pdf_local",
        source_path="bio/paper.pdf",
        general_domain="reproduction",
    )
    assert doc.processing_status == "pending"
    assert doc.general_domain == "reproduction"
    assert doc.doi == "10.1234/test"

    # model_dump includes _id as ObjectId, json mode as string
    raw = doc.model_dump(by_alias=True)
    assert isinstance(raw["_id"], ObjectId)
    j = doc.model_dump(mode="json", by_alias=True)
    assert isinstance(j["_id"], str)
    print("  Document OK")


def test_fact():
    doc = Document(title="Source", source_type="pdf_upload")
    fact = Fact(
        content="Metabolic rate scales with body mass.",
        document_id=doc.id,
        general_domain="metabolism",
        entities=["metabolic rate", "body mass"],
        confidence=0.9,
    )
    assert str(fact.document_id) == str(doc.id)
    assert fact.status == "pending"
    assert fact.confidence == 0.9

    j = fact.model_dump(mode="json")
    assert isinstance(j["document_id"], str)
    assert j["document_id"] == str(doc.id)
    print("  Fact OK")


def test_stylized_fact():
    sf = StylizedFact(
        statement="All species trade off offspring size vs number.",
        category="reproductive_strategy",
        sf_number=302,
    )
    assert sf.sf_number == 302
    assert sf.status == "pending"
    assert sf.category == "reproductive_strategy"
    print("  StylizedFact OK")


def test_fact_sf_relation():
    doc = Document(title="Src", source_type="manual")
    fact = Fact(content="Evidence text.", document_id=doc.id)
    sf = StylizedFact(statement="Pattern X.", category="ecology")

    supports = FactSFRelation(
        fact_id=fact.id, sf_id=sf.id, relation_type="supports", confidence=0.85
    )
    opposes = FactSFRelation(
        fact_id=fact.id, sf_id=sf.id, relation_type="opposes", confidence=0.3,
        created_by="curator-123",
    )

    assert supports.status == "suggested"
    assert supports.relation_type == "supports"
    assert opposes.relation_type == "opposes"
    assert opposes.created_by == "curator-123"

    j = supports.model_dump(mode="json")
    assert isinstance(j["fact_id"], str)
    assert isinstance(j["sf_id"], str)
    print("  FactSFRelation OK")


def test_taxonomy_node():
    root = TaxonomyNode(tax_id=1, name="root", rank="no rank", parent_tax_id=None, lineage=[])
    assert root.parent_tax_id is None
    assert root.lineage == []

    species = TaxonomyNode(
        tax_id=9606,
        name="Homo sapiens",
        rank="species",
        parent_tax_id=9605,
        lineage=[1, 131567, 2759, 33154, 9604, 9605],
        synonyms=["Man"],
        common_names=["human"],
        gbif_usage_key=2436436,
    )
    assert species.lineage[-1] == 9605
    assert species.ncbi_sourced is True
    assert "human" in species.common_names
    print("  TaxonomyNode OK")


def test_builtin_schemas():
    assert len(BUILTIN_SCHEMAS) == 5
    names = {s["name"] for s in BUILTIN_SCHEMAS}
    assert names == {"citation", "sf_support", "taxonomical", "knowledge_graph", "physiological_process"}

    for raw in BUILTIN_SCHEMAS:
        schema = GraphSchema(**raw)
        assert schema.is_builtin
        assert len(schema.node_types) >= 1
        assert len(schema.edge_types) >= 1
        # Each edge type references valid node type names within this schema
        node_type_names = {nt.name for nt in schema.node_types}
        for et in schema.edge_types:
            assert et.source_node_type in node_type_names, (
                f"{schema.name}: edge '{et.name}' source '{et.source_node_type}' "
                f"not in node types {node_type_names}"
            )
            assert et.target_node_type in node_type_names, (
                f"{schema.name}: edge '{et.name}' target '{et.target_node_type}' "
                f"not in node types {node_type_names}"
            )
    print("  BUILTIN_SCHEMAS OK")


def test_graph_node_and_edge():
    schema = GraphSchema(**BUILTIN_SCHEMAS[1])  # sf_support
    sf = StylizedFact(statement="Pattern.", category="test")

    gnode = GraphNode(
        schema_id=schema.id,
        node_type="stylized_fact",
        entity_collection="stylized_facts",
        entity_id=str(sf.id),
        label=sf.statement,
        properties={"category": sf.category},
    )
    fact = Fact(content="Evidence.", document_id=ObjectId())
    gnode2 = GraphNode(
        schema_id=schema.id,
        node_type="fact",
        entity_collection="facts",
        entity_id=str(fact.id),
        label=fact.content,
    )
    edge = GraphEdge(
        schema_id=schema.id,
        edge_type="supports",
        source_node_id=gnode2.id,
        target_node_id=gnode.id,
        weight=0.85,
    )
    assert str(edge.source_node_id) == str(gnode2.id)
    assert edge.weight == 0.85
    print("  GraphNode / GraphEdge OK")


def test_ingestion_models():
    batch = IngestionBatch(
        source_root="/data/papers",
        folders=["reproduction", "metabolism"],
        general_domain="reproduction",
        name="Batch-001",
    )
    assert batch.status == "pending"
    assert batch.general_domain == "reproduction"

    job = IngestionJob(
        batch_id=batch.id,
        source_type="pdf_local",
        source_path_or_url="reproduction/paper.pdf",
    )
    assert job.stage == "pending"
    assert str(job.batch_id) == str(batch.id)

    j = job.model_dump(mode="json")
    assert isinstance(j["batch_id"], str)
    print("  IngestionBatch / IngestionJob OK")


if __name__ == "__main__":
    tests = [
        test_pyobjectid,
        test_document,
        test_fact,
        test_stylized_fact,
        test_fact_sf_relation,
        test_taxonomy_node,
        test_builtin_schemas,
        test_graph_node_and_edge,
        test_ingestion_models,
    ]
    print(f"Running {len(tests)} model tests...")
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")
