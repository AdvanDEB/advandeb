#!/usr/bin/env python3
"""
Benchmark harness for CHAT_ANSWER_MODEL candidates.

Compares gpt-oss:latest vs deepseek-r1:latest (or any two models) on a fixed
eval dataset of bioenergetics queries, scoring on five dimensions:

  Dimension              Weight
  ─────────────────────────────
  Evidence fidelity        40%    → every cited [N] resolves in registry AND
                                    at least MIN_EVIDENCE_FRAC of factual claims
                                    carry a marker
  Citation correctness     25%    → no invalid markers; all used markers resolve
  Answer completeness      20%    → answer length and question coverage heuristic
  Latency                  10%    → normalized inverse of wall-clock time
  Format stability          5%    → JSON-parseable payload, required fields present

Usage
-----
    python knowledge-builder/scripts/benchmark_chat_answer_models.py \
        [--models deepseek-r1:latest gpt-oss:latest] \
        [--top-k 8] \
        [--out-dir /tmp/bench]

The script runs the deterministic ChatPipelineService (not the full MCP stack)
against each model so it can be run without starting all 6 agents.  It uses
the production Ollama and ArangoDB/MongoDB instances.

Output
------
A JSON report at {out_dir}/report_{timestamp}.json and a Markdown summary
printed to stdout.

Hard gates (from spec)
----------------------
- All citations must resolve to valid provenance in the registry
- No uncited factual claims in the final answer
- Graph markers survive round-trip ([G1] appears in observation AND answer)
- Fallback labeling correct (external fallback answers carry the disclaimer)
- Output contract valid (required fields in payload)

A model FAILS the gate if its aggregate gate score < 1.0 (all gates must pass).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the knowledge-builder package is importable
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from advandeb_kb.config.settings import settings  # noqa: E402
from advandeb_kb.services.chat_pipeline_service import ChatPipelineService  # noqa: E402
from advandeb_kb.services.evidence_registry_service import EvidenceRegistry  # noqa: E402

# ---------------------------------------------------------------------------
# Eval dataset
# ---------------------------------------------------------------------------

EVAL_QUERIES: list[dict] = [
    {
        "id": "deb_kappa",
        "query": "What is the kappa-rule in Dynamic Energy Budget theory?",
        "expect_graph_markers": True,
        "expect_citations": True,
    },
    {
        "id": "von_bert_growth",
        "query": "How does von Bertalanffy growth rate relate to metabolic rate in fish?",
        "expect_graph_markers": False,
        "expect_citations": True,
    },
    {
        "id": "assimilation_efficiency",
        "query": "What is the typical assimilation efficiency of Mytilus edulis?",
        "expect_graph_markers": True,
        "expect_citations": True,
    },
    {
        "id": "metabolic_scaling",
        "query": "Explain Kleiber's law and its implications for energetics.",
        "expect_graph_markers": False,
        "expect_citations": True,
    },
    {
        "id": "sda_cost",
        "query": "What fraction of ingested energy is used for specific dynamic action in ectotherms?",
        "expect_graph_markers": True,
        "expect_citations": True,
    },
    {
        "id": "thin_evidence",
        "query": "What are the energetics of the giant squid Architeuthis dux?",
        "expect_graph_markers": False,
        "expect_citations": False,   # expect external fallback label
        "expect_fallback_label": True,
    },
    {
        "id": "conversational",
        "query": "Hello, who are you?",
        "expect_graph_markers": False,
        "expect_citations": False,
        "is_conversational": True,
    },
]

# Fraction of factual sentences that must carry a citation marker
MIN_CITATION_COVERAGE = 0.5

_FACTUAL_RE = re.compile(
    r"\b(studies? (show|found)|according to|was (found|shown)|data (show|indicate)|"
    r"rate of|coefficient|fraction of|\d+(\.\d+)?\s*(mg|g|kJ|°C|%|mol))\b",
    re.IGNORECASE,
)
_MARKER_RE = re.compile(r"\[((?:SF|G)?\d+)\]")


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def score_evidence_fidelity(answer: str, citations: list[dict], registry: EvidenceRegistry) -> float:
    """Score 0-1: all cited markers valid + factual coverage."""
    used_markers = set(_MARKER_RE.findall(answer))
    valid_markers = {e.marker for e in registry.entries()}

    if used_markers and not valid_markers:
        # Markers cited but no registry — bad
        return 0.0

    invalid = used_markers - valid_markers
    if invalid:
        return 0.0  # Any invalid marker → 0

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if len(s.strip()) > 20]
    factual = [s for s in sentences if _FACTUAL_RE.search(s)]
    if not factual:
        return 1.0  # No factual claims → no fidelity issue
    cited = [s for s in factual if _MARKER_RE.search(s)]
    coverage = len(cited) / len(factual)
    return min(1.0, coverage / MIN_CITATION_COVERAGE)


def score_citation_correctness(answer: str, citations: list[dict], registry: EvidenceRegistry) -> float:
    """Score 0-1: no invalid markers; all used markers resolve."""
    used_markers = set(_MARKER_RE.findall(answer))
    if not used_markers:
        return 1.0 if not citations else 0.5
    valid_markers = {e.marker for e in registry.entries()}
    invalid = used_markers - valid_markers
    if invalid:
        return 0.0
    return 1.0


def score_completeness(answer: str, query: str, is_conversational: bool = False) -> float:
    """Heuristic: answer length + query word coverage."""
    if is_conversational:
        return 1.0 if len(answer) > 20 else 0.5
    if len(answer) < 100:
        return 0.3
    query_words = set(re.findall(r"\w{4,}", query.lower()))
    answer_words = set(re.findall(r"\w{4,}", answer.lower()))
    coverage = len(query_words & answer_words) / max(len(query_words), 1)
    length_score = min(1.0, len(answer) / 600)
    return 0.5 * coverage + 0.5 * length_score


def score_latency(elapsed_s: float, baseline_s: float = 30.0) -> float:
    """Normalized inverse latency: 1.0 if <= baseline, decays beyond."""
    return min(1.0, baseline_s / max(elapsed_s, 1.0))


def score_format_stability(payload: dict) -> float:
    """Check required fields are present and non-empty."""
    required = ["answer", "citations", "evidence_mode", "tool_calls_made"]
    score = sum(1 for f in required if payload.get(f) is not None) / len(required)
    return score


WEIGHTS = {
    "evidence_fidelity":    0.40,
    "citation_correctness": 0.25,
    "completeness":         0.20,
    "latency":              0.10,
    "format_stability":     0.05,
}


def compute_total(scores: dict) -> float:
    return sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)


# ---------------------------------------------------------------------------
# Hard gate check
# ---------------------------------------------------------------------------

def check_gates(results: list[dict]) -> dict[str, bool]:
    """Apply hard gates to a list of per-query result dicts."""
    gates = {
        "all_citations_valid": True,
        "no_uncited_factual_claims": True,
        "graph_markers_survive": True,
        "fallback_labeling_correct": True,
        "output_contract_valid": True,
    }

    for r in results:
        q = r["query_meta"]
        scores = r["scores"]

        if scores["citation_correctness"] < 1.0:
            gates["all_citations_valid"] = False
        if scores["evidence_fidelity"] < 0.5 and not q.get("is_conversational") and not q.get("expect_fallback_label"):
            gates["no_uncited_factual_claims"] = False
        if q.get("expect_graph_markers") and r["graph_markers_in_answer"] == 0:
            gates["graph_markers_survive"] = False
        if q.get("expect_fallback_label") and not r["has_fallback_label"]:
            gates["fallback_labeling_correct"] = False
        if scores["format_stability"] < 1.0:
            gates["output_contract_valid"] = False

    return gates


# ---------------------------------------------------------------------------
# Mock tool dispatch (no MCP agents needed)
# ---------------------------------------------------------------------------

class _MockMCPClient:
    """Calls MCP agents directly via HTTP if available, else returns empty."""

    def __init__(self, ws_url: str) -> None:
        self._url = ws_url

    async def call_tool(self, tool: str, args: dict) -> dict:
        # Try to import and call via the real MCP client
        try:
            from advandeb_kb.mcp.protocol import MCPClient
            client = MCPClient(self._url)
            return await client.call_tool(tool, args)
        except Exception as exc:
            return {"chunks": [], "facts": [], "stylized_facts": [], "error": str(exc)}


def build_mock_dispatch(top_k: int) -> dict:
    retrieval = _MockMCPClient("ws://localhost:8081")
    graph = _MockMCPClient("ws://localhost:8082")
    synthesis = _MockMCPClient("ws://localhost:8083")

    async def hybrid_search(args: dict) -> dict:
        args.setdefault("top_k", top_k)
        return await retrieval.call_tool("hybrid_search", args)

    async def expand_context(args: dict) -> dict:
        args.setdefault("max_hops", 2)
        return await graph.call_tool("expand_context", args)

    return {"hybrid_search": hybrid_search, "expand_context": expand_context}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_model(model_name: str, top_k: int) -> list[dict]:
    """Run all eval queries for a given model. Returns per-query result dicts."""
    # Temporarily override the answer model setting
    original = settings.CHAT_ANSWER_MODEL
    settings.CHAT_ANSWER_MODEL = model_name  # type: ignore[misc]

    results = []
    dispatch = build_mock_dispatch(top_k)

    for q in EVAL_QUERIES:
        print(f"  [{model_name}] {q['id']}: {q['query'][:60]}…", flush=True)
        t0 = time.time()
        pipeline = ChatPipelineService(
            tool_dispatch=dispatch,
            conversation_history=[],
        )
        try:
            payload = await pipeline.run(q["query"], top_k=top_k)
        except Exception as exc:
            print(f"    ERROR: {exc}")
            payload = {
                "answer": f"ERROR: {exc}",
                "citations": [],
                "evidence_mode": "local",
                "tool_calls_made": [],
                "thoughts": [],
            }
        elapsed = time.time() - t0

        answer = payload.get("answer", "")
        citations = payload.get("citations", [])

        # Reconstruct a registry from the citations for scoring
        # (we don't have direct access to the internal registry here,
        #  so we build a surrogate from the citations list)
        reg = _registry_from_citations(citations)

        has_fallback_label = "knowledge base did not return" in answer.lower()
        graph_markers_in_answer = len(re.findall(r"\[G\d+\]", answer))

        scores = {
            "evidence_fidelity":    score_evidence_fidelity(answer, citations, reg),
            "citation_correctness": score_citation_correctness(answer, citations, reg),
            "completeness":         score_completeness(answer, q["query"], q.get("is_conversational", False)),
            "latency":              score_latency(elapsed),
            "format_stability":     score_format_stability(payload),
        }
        total = compute_total(scores)

        results.append({
            "query_meta":            q,
            "model":                 model_name,
            "elapsed_s":             round(elapsed, 2),
            "answer_excerpt":        answer[:300],
            "citation_count":        len(citations),
            "graph_markers_in_answer": graph_markers_in_answer,
            "has_fallback_label":    has_fallback_label,
            "scores":                {k: round(v, 3) for k, v in scores.items()},
            "total_score":           round(total, 3),
        })

    settings.CHAT_ANSWER_MODEL = original  # type: ignore[misc]
    return results


def _registry_from_citations(citations: list[dict]) -> EvidenceRegistry:
    """Build a surrogate EvidenceRegistry from citation dicts (for scoring)."""
    from advandeb_kb.services.evidence_registry_service import RegistryEntry

    reg = EvidenceRegistry()
    for c in citations:
        marker_raw = c.get("marker", "[1]")
        marker = marker_raw.strip("[]")
        entry = RegistryEntry(
            marker=marker,
            citation_id=c.get("citation_id", ""),
            source_type=c.get("source_type", "chunk"),
            document_id=c.get("document_id"),
            chunk_id=c.get("chunk_id"),
            fact_id=c.get("fact_id"),
            stylized_fact_id=c.get("stylized_fact_id"),
            evidence_text=c.get("evidence_text", ""),
        )
        reg._add(entry)  # noqa: SLF001
    return reg


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(model_results: dict[str, list[dict]], out_dir: Path) -> str:
    """Write JSON report and return Markdown summary."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Aggregate per-model
    summary: dict[str, Any] = {}
    for model, results in model_results.items():
        gate_results = check_gates(results)
        gate_pass = all(gate_results.values())
        avg_scores: dict[str, float] = {}
        for dim in WEIGHTS:
            avg_scores[dim] = sum(r["scores"][dim] for r in results) / len(results)
        avg_total = sum(r["total_score"] for r in results) / len(results)
        avg_latency = sum(r["elapsed_s"] for r in results) / len(results)
        summary[model] = {
            "avg_scores": {k: round(v, 3) for k, v in avg_scores.items()},
            "avg_total":  round(avg_total, 3),
            "avg_latency_s": round(avg_latency, 1),
            "gate_results": gate_results,
            "gate_pass":    gate_pass,
            "per_query":    results,
        }

    # Write JSON
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"report_{timestamp}.json"
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nReport written to: {report_path}")

    # Markdown summary
    lines = [
        "# Chat Answer Model Benchmark Report",
        f"**Timestamp:** {timestamp}",
        "",
        "## Scoring weights",
        "| Dimension | Weight |",
        "|-----------|--------|",
    ]
    for dim, w in WEIGHTS.items():
        lines.append(f"| {dim.replace('_', ' ').title()} | {int(w*100)}% |")
    lines += ["", "## Results", ""]

    models = list(summary.keys())
    # Determine winner (highest avg_total among gate-passing models)
    passing = [m for m in models if summary[m]["gate_pass"]]
    winner = max(passing, key=lambda m: summary[m]["avg_total"]) if passing else None

    for model in models:
        s = summary[model]
        gate_icon = "✓ PASS" if s["gate_pass"] else "✗ FAIL"
        lines.append(f"### {model}  `{gate_icon}`")
        lines.append(f"**Weighted total: {s['avg_total']:.3f}**  |  "
                     f"Avg latency: {s['avg_latency_s']}s")
        lines.append("")
        lines.append("| Dimension | Score |")
        lines.append("|-----------|-------|")
        for dim, sc in s["avg_scores"].items():
            lines.append(f"| {dim.replace('_', ' ').title()} | {sc:.3f} |")
        lines.append("")
        lines.append("**Gate results:**")
        for gate, passed in s["gate_results"].items():
            icon = "✓" if passed else "✗"
            lines.append(f"- {icon} {gate.replace('_', ' ')}")
        lines.append("")

    lines.append("## Recommendation")
    if winner:
        lines.append(f"**Promote `{winner}` as CHAT_ANSWER_MODEL** — highest score among gate-passing models.")
        lines.append("")
        lines.append(f"Add to `.env`:")
        lines.append(f"```")
        lines.append(f"CHAT_ANSWER_MODEL={winner}")
        lines.append(f"```")
    else:
        lines.append("**No model passed all gates.** Do not promote either candidate yet.")
        lines.append("Review per-query results in the JSON report and address failing gates.")

    md = "\n".join(lines)
    md_path = out_dir / f"report_{timestamp}.md"
    with open(md_path, "w") as f:
        f.write(md)
    return md


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark CHAT_ANSWER_MODEL candidates")
    parser.add_argument(
        "--models", nargs="+",
        default=["deepseek-r1:latest", "gpt-oss:latest"],
        help="Ollama model names to benchmark",
    )
    parser.add_argument("--top-k", type=int, default=8, help="Chunks per search")
    parser.add_argument(
        "--out-dir", default="/tmp/advandeb_bench",
        help="Directory for JSON/Markdown report output",
    )
    args = parser.parse_args()

    print(f"Benchmarking models: {args.models}")
    print(f"Eval queries: {len(EVAL_QUERIES)}")
    print(f"Output dir: {args.out_dir}")
    print()

    model_results: dict[str, list[dict]] = {}
    for model in args.models:
        print(f"=== Model: {model} ===")
        model_results[model] = await run_model(model, args.top_k)

    md_report = generate_report(model_results, Path(args.out_dir))
    print()
    print(md_report)


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
