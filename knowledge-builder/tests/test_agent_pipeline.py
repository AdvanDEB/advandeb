"""
Integration tests for the multi-agent RAG pipeline.

Tests are designed to run without external services (MongoDB, ArangoDB,
ChromaDB, Ollama) by using mocks and in-memory stubs.

Run:
    conda run -n advandeb pytest tests/test_agent_pipeline.py -v
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make package importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# MCPServer — dispatch tests
# ---------------------------------------------------------------------------

class TestMCPServer:
    def setup_method(self):
        from advandeb_kb.mcp.protocol import MCPServer
        self.server = MCPServer(port=9999)

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_tools_list_empty(self):
        resp = json.loads(self._run(
            self.server.handle_message(json.dumps({"id": "1", "method": "tools/list"}))
        ))
        assert resp["result"]["tools"] == []

    def test_register_and_list_tool(self):
        self.server.register_tool("add", lambda a, b: {"sum": a + b},
                                   description="Add two ints")
        resp = json.loads(self._run(
            self.server.handle_message(json.dumps({"id": "1", "method": "tools/list"}))
        ))
        names = [t["name"] for t in resp["result"]["tools"]]
        assert "add" in names

    def test_call_sync_tool(self):
        self.server.register_tool("mul", lambda x, y: {"product": x * y})
        resp = json.loads(self._run(self.server.handle_message(json.dumps({
            "id": "2", "method": "tools/call",
            "params": {"name": "mul", "arguments": {"x": 3, "y": 4}}
        }))))
        assert resp["result"]["product"] == 12

    def test_call_async_tool(self):
        async def async_add(a, b):
            return {"sum": a + b}
        self.server.register_tool("async_add", async_add)
        resp = json.loads(self._run(self.server.handle_message(json.dumps({
            "id": "3", "method": "tools/call",
            "params": {"name": "async_add", "arguments": {"a": 7, "b": 8}}
        }))))
        assert resp["result"]["sum"] == 15

    def test_unknown_tool_returns_error(self):
        resp = json.loads(self._run(self.server.handle_message(json.dumps({
            "id": "4", "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}}
        }))))
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_ping(self):
        resp = json.loads(self._run(
            self.server.handle_message(json.dumps({"id": "5", "method": "ping"}))
        ))
        assert resp["result"]["pong"] is True

    def test_parse_error(self):
        resp = json.loads(self._run(self.server.handle_message("not json")))
        assert resp["error"]["code"] == -32700

    def test_unknown_method(self):
        resp = json.loads(self._run(
            self.server.handle_message(json.dumps({"id": "6", "method": "unknown/method"}))
        ))
        assert "error" in resp


# ---------------------------------------------------------------------------
# ChunkingService tests
# ---------------------------------------------------------------------------

class TestChunkingService:
    def setup_method(self):
        from advandeb_kb.services.chunking_service import ChunkingService
        self.svc = ChunkingService(chunk_size=200, overlap=50, min_chunk=10)

    def test_empty_text_returns_no_chunks(self):
        assert self.svc.chunk_document("", "doc1") == []
        assert self.svc.chunk_text("") == []

    def test_short_text_is_single_chunk(self):
        text = "This is a short sentence about DEB theory."
        chunks = self.svc.chunk_document(text, "doc1")
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].document_id == "doc1"
        assert chunks[0].chunk_id == "doc1_chunk_0"

    def test_long_text_produces_multiple_chunks(self):
        text = ("Dynamic Energy Budget theory. " * 20).strip()
        chunks = self.svc.chunk_document(text, "doc2")
        assert len(chunks) >= 2

    def test_overlap_present(self):
        # With overlap, consecutive chunks should share some content
        svc = __import__("advandeb_kb.services.chunking_service",
                          fromlist=["ChunkingService"]).ChunkingService(
            chunk_size=100, overlap=30, min_chunk=5
        )
        text = "A" * 90 + " B" * 45 + " C" * 45
        chunks = svc.chunk_text(text)
        if len(chunks) >= 2:
            # Second chunk should start with tail of first
            tail = chunks[0][-30:]
            assert chunks[1].startswith(tail) or len(tail) == 0

    def test_chunk_ids_unique(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three.\n\nParagraph four."
        svc = __import__("advandeb_kb.services.chunking_service",
                          fromlist=["ChunkingService"]).ChunkingService(
            chunk_size=30, overlap=5, min_chunk=5
        )
        chunks = svc.chunk_document(text, "doc3")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "Chunk IDs must be unique"

    def test_chromadb_metadata_keys(self):
        text = "Energy allocation in fish larvae follows the kappa rule."
        chunks = self.svc.chunk_document(text, "doc4")
        assert len(chunks) >= 1
        meta = chunks[0].to_chromadb_metadata()
        assert "document_id" in meta
        assert "chunk_index" in meta
        assert "char_start" in meta
        assert "char_end" in meta


# ---------------------------------------------------------------------------
# CacheService tests
# ---------------------------------------------------------------------------

class TestCacheService:
    def setup_method(self):
        from advandeb_kb.services.cache_service import CacheService
        self.cache = CacheService(max_size=10, ttl_seconds=60)

    def test_miss_on_empty_cache(self):
        assert self.cache.get("never seen query") is None

    def test_set_then_get(self):
        self.cache.set("deb theory", top_k=5, value=["result1", "result2"])
        val = self.cache.get("deb theory", top_k=5)
        assert val == ["result1", "result2"]

    def test_different_top_k_is_different_key(self):
        self.cache.set("energy allocation", top_k=5, value=["r1"])
        self.cache.set("energy allocation", top_k=10, value=["r1", "r2"])
        assert len(self.cache.get("energy allocation", top_k=5)) == 1
        assert len(self.cache.get("energy allocation", top_k=10)) == 2

    def test_domain_filter_in_key(self):
        self.cache.set("query", top_k=5, domain_filter="reproduction", value=["a"])
        self.cache.set("query", top_k=5, domain_filter=None, value=["b"])
        assert self.cache.get("query", top_k=5, domain_filter="reproduction") == ["a"]
        assert self.cache.get("query", top_k=5, domain_filter=None) == ["b"]

    def test_lru_eviction(self):
        cache = __import__("advandeb_kb.services.cache_service",
                            fromlist=["CacheService"]).CacheService(max_size=3, ttl_seconds=60)
        for i in range(4):
            cache.set(f"query{i}", value=i)
        # query0 should have been evicted
        assert cache.get("query0") is None
        assert cache.get("query3") == 3

    def test_invalidate(self):
        self.cache.set("test query", value="data")
        self.cache.invalidate("test query")
        assert self.cache.get("test query") is None

    def test_stats(self):
        self.cache.set("q1", value="v1")
        self.cache.get("q1")  # hit
        self.cache.get("q2")  # miss
        s = self.cache.stats()
        assert s["hits"] == 1
        assert s["misses"] == 1
        assert s["hit_rate"] == 0.5


# ---------------------------------------------------------------------------
# HybridRetrievalService — RRF logic tests (no external services)
# ---------------------------------------------------------------------------

class TestRRFFusion:
    def setup_method(self):
        from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService
        # Minimal stubs — only testing RRF math, no real services
        emb = MagicMock()
        chroma = MagicMock()
        self.svc = HybridRetrievalService(emb, chroma, rrf_k=60)

    def test_rrf_single_list(self):
        vector = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        keyword = []
        scores = self.svc._reciprocal_rank_fusion(vector, keyword)
        # a should score highest (rank 0)
        ids_ordered = list(scores.keys())
        assert ids_ordered[0] == "a"

    def test_rrf_boosts_items_in_both_lists(self):
        # "b" appears in both → should outscore "a" (only in vector) and "c" (only in keyword)
        vector  = [{"id": "a"}, {"id": "b"}]
        keyword = [{"id": "c"}, {"id": "b"}]
        scores = self.svc._reciprocal_rank_fusion(vector, keyword)
        assert scores["b"] > scores["a"]
        assert scores["b"] > scores["c"]

    def test_rrf_scores_sum_correctly(self):
        # With k=60, rank 0 → 1/61; verify
        vector  = [{"id": "x"}]
        keyword = [{"id": "x"}]
        scores = self.svc._reciprocal_rank_fusion(vector, keyword)
        expected = 1 / 61 + 1 / 61
        assert abs(scores["x"] - expected) < 1e-9


# ---------------------------------------------------------------------------
# SynthesisAgent — citation extraction tests
# ---------------------------------------------------------------------------

class TestSynthesisAgentCitations:
    def setup_method(self):
        from advandeb_kb.agents.synthesis_agent import SynthesisAgent
        self.agent = SynthesisAgent()

    def _chunks(self, n):
        return [
            {"chunk_id": f"doc_chunk_{i}", "text": f"text {i}", "metadata": {"document_id": f"doc{i}"}}
            for i in range(n)
        ]

    def test_no_citations(self):
        result = self.agent._extract_citations("No markers here.", self._chunks(3))
        assert result == []

    def test_single_citation(self):
        result = self.agent._extract_citations("Energy [1] is key.", self._chunks(3))
        assert len(result) == 1
        assert result[0]["number"] == 1
        assert result[0]["chunk_id"] == "doc_chunk_0"

    def test_multiple_citations(self):
        result = self.agent._extract_citations("[1] and [3] confirm [2].", self._chunks(3))
        nums = {c["number"] for c in result}
        assert nums == {1, 2, 3}

    def test_out_of_range_citation_ignored(self):
        result = self.agent._extract_citations("[5] is out of range.", self._chunks(3))
        assert result == []

    def test_duplicate_citations_deduplicated(self):
        result = self.agent._extract_citations("[1] then [1] again.", self._chunks(3))
        assert len(result) == 1

    def test_document_id_in_citation(self):
        result = self.agent._extract_citations("See [2].", self._chunks(3))
        assert result[0]["document_id"] == "doc1"


# ---------------------------------------------------------------------------
# QueryPlannerAgent — plan + arg resolver tests
# ---------------------------------------------------------------------------

class TestQueryPlannerAgent:
    def setup_method(self):
        from advandeb_kb.agents.query_planner_agent import QueryPlannerAgent
        self.agent = QueryPlannerAgent()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_template_plan_has_3_steps(self):
        plan = self._run(self.agent._plan_query(
            "energy allocation in fish", use_llm_planning=False
        ))
        assert plan["source"] == "template"
        assert len(plan["steps"]) == 3

    def test_template_plan_step_agents(self):
        plan = self._run(self.agent._plan_query("test", use_llm_planning=False))
        steps_by_num = {s["step"]: s for s in plan["steps"]}
        assert steps_by_num[1]["agent"] == "retrieval_agent"
        assert steps_by_num[2]["agent"] == "graph_explorer"
        assert steps_by_num[3]["agent"] == "synthesis_agent"

    def test_template_plan_carries_query(self):
        plan = self._run(self.agent._plan_query("kappa rule", use_llm_planning=False))
        step1 = next(s for s in plan["steps"] if s["step"] == 1)
        assert step1["args"]["query"] == "kappa rule"

    def test_resolve_args_literal(self):
        args = {"query": "test", "top_k": 5}
        resolved = self.agent._resolve_args(args, {}, "test")
        assert resolved == args

    def test_resolve_args_from_step(self):
        results = {1: {"chunks": [{"id": "c1"}], "count": 1}}
        args = {"chunks": "__from_step_1_chunks__"}
        resolved = self.agent._resolve_args(args, results, "q")
        assert resolved["chunks"] == [{"id": "c1"}]

    def test_resolve_args_full_step_result(self):
        results = {2: {"documents": ["d1"], "facts": ["f1"]}}
        args = {"graph_context": "__from_step_2__"}
        resolved = self.agent._resolve_args(args, results, "q")
        assert resolved["graph_context"] == results[2]

    def test_domain_filter_in_template(self):
        plan = self._run(self.agent._plan_query(
            "test", use_llm_planning=False, domain_filter="reproduction"
        ))
        step1 = next(s for s in plan["steps"] if s["step"] == 1)
        assert step1["args"].get("domain_filter") == "reproduction"


# ---------------------------------------------------------------------------
# ProvenanceTrace model tests
# ---------------------------------------------------------------------------

class TestProvenanceModel:
    def test_basic_construction(self):
        from advandeb_kb.models.provenance import ProvenanceTrace
        trace = ProvenanceTrace(
            query="How does kappa rule work?",
            facts_used=["f1", "f2"],
            chunks_retrieved=["c1", "c2", "c3"],
            documents_cited=["d1"],
            confidence_score=0.82,
            retrieval_methods=["vector", "keyword"],
        )
        assert trace.query == "How does kappa rule work?"
        assert len(trace.chunks_retrieved) == 3
        assert trace.confidence_score == 0.82

    def test_retrieval_context_to_provenance(self):
        from advandeb_kb.models.provenance import RetrievalContext
        ctx = RetrievalContext(
            query="reserves in fish",
            vector_results=[{"id": "c1"}],
            keyword_results=[{"id": "c2"}],
            final_ranking=["c1", "c2"],
            fusion_method="rrf",
        )
        trace = ctx.to_provenance_trace(confidence_score=0.7)
        assert "vector" in trace.retrieval_methods
        assert "keyword" in trace.retrieval_methods
        assert trace.query == "reserves in fish"
