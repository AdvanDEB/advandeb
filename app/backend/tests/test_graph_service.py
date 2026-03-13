"""
Unit tests for GraphService — Cytoscape.js output format.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_node(nid: str, label: str, node_type: str = "concept"):
    node = {
        "_id": nid,
        "label": label,
        "type": node_type,
    }
    return node


def make_edge(eid: str, source: str, target: str, edge_type: str = "related"):
    return {
        "_id": eid,
        "source": source,
        "target": target,
        "type": edge_type,
        "weight": 1.0,
    }


@pytest.fixture
def graph_service():
    mock_db = MagicMock()
    mock_db.graph_nodes = MagicMock()
    mock_db.graph_edges = MagicMock()

    with patch("app.services.graph_service.get_database", return_value=mock_db):
        from app.services.graph_service import GraphService
        svc = GraphService()

    return svc, mock_db


def make_async_iter(items):
    async def _iter(self):
        for item in items:
            yield item
    mock = MagicMock()
    mock.__aiter__ = _iter
    return mock


# ── get_cytoscape_graph ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_cytoscape_graph_empty(graph_service):
    svc, db = graph_service
    db.graph_nodes.find = MagicMock(return_value=make_async_iter([]))
    db.graph_edges.find = MagicMock(return_value=make_async_iter([]))

    result = await svc.get_cytoscape_graph()

    assert "elements" in result
    assert result["elements"]["nodes"] == []
    assert result["elements"]["edges"] == []


@pytest.mark.asyncio
async def test_get_cytoscape_graph_nodes_have_required_fields(graph_service):
    svc, db = graph_service
    db.graph_nodes.find = MagicMock(return_value=make_async_iter([
        make_node("n1", "Assimilation", "concept"),
    ]))
    db.graph_edges.find = MagicMock(return_value=make_async_iter([]))

    result = await svc.get_cytoscape_graph()
    node_data = result["elements"]["nodes"][0]["data"]

    assert node_data["id"] == "n1"
    assert node_data["label"] == "Assimilation"
    assert "color" in node_data
    assert "size" in node_data


@pytest.mark.asyncio
async def test_node_size_scales_with_degree(graph_service):
    svc, db = graph_service
    db.graph_nodes.find = MagicMock(return_value=make_async_iter([
        make_node("n1", "Hub"),
        make_node("n2", "Leaf"),
    ]))
    db.graph_edges.find = MagicMock(return_value=make_async_iter([
        make_edge("e1", "n1", "n2"),
        make_edge("e2", "n1", "n2"),
    ]))

    result = await svc.get_cytoscape_graph()
    nodes_by_id = {n["data"]["id"]: n["data"] for n in result["elements"]["nodes"]}

    assert nodes_by_id["n1"]["size"] > nodes_by_id["n2"]["size"]


@pytest.mark.asyncio
async def test_get_cytoscape_graph_edges_have_source_target(graph_service):
    svc, db = graph_service
    db.graph_nodes.find = MagicMock(return_value=make_async_iter([
        make_node("n1", "A"), make_node("n2", "B"),
    ]))
    db.graph_edges.find = MagicMock(return_value=make_async_iter([
        make_edge("e1", "n1", "n2"),
    ]))

    result = await svc.get_cytoscape_graph()
    edge_data = result["elements"]["edges"][0]["data"]

    assert edge_data["source"] == "n1"
    assert edge_data["target"] == "n2"
    assert edge_data["type"] == "related"


# ── query_graph ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_graph_returns_results(graph_service):
    svc, db = graph_service
    mock_cursor = make_async_iter([
        make_node("n1", "Assimilation"),
    ])
    mock_cursor.find = MagicMock(return_value=mock_cursor)
    db.graph_nodes.find = MagicMock(return_value=mock_cursor)

    result = await svc.query_graph("Assimilation")

    assert result["query"] == "Assimilation"
    assert isinstance(result["results"], list)
