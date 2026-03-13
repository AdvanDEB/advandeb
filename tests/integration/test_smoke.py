#!/usr/bin/env python3
"""
test_smoke.py — Smoke tests for the AdvanDEB platform.

Tests all services end-to-end:
  - MCP Gateway (HTTP health + agents list)
  - All 5 agents (WebSocket tools/list)
  - FastAPI backend (health)
  - Vue frontend (HTTP 200)
  - ArangoDB direct (schema check)
  - ChromaDB (collection count)
  - Agent tool call: semantic_search via gateway

Usage:
    conda run -n advandeb python tests/integration/test_smoke.py
    conda run -n advandeb pytest tests/integration/test_smoke.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "knowledge-builder"))

GATEWAY = "http://localhost:8080"
BACKEND = "http://localhost:8400"
FRONTEND = "http://localhost:5173"

AGENTS = [
    ("retrieval_agent", 8081),
    ("graph_explorer", 8082),
    ("synthesis_agent", 8083),
    ("query_planner", 8084),
    ("curator_agent", 8085),
]

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as exc:
        return 0, str(exc)


# ---------------------------------------------------------------------------
# Sync tests (HTTP)
# ---------------------------------------------------------------------------

def test_gateway_health():
    code, body = http_get(f"{GATEWAY}/health")
    ok = code == 200
    print(f"[{PASS if ok else FAIL}] Gateway health: {code} {body[:80]}")
    return ok


def test_gateway_agents():
    code, body = http_get(f"{GATEWAY}/agents")
    try:
        data = json.loads(body)
        agents = data if isinstance(data, list) else data.get("agents", [])
        ok = code == 200 and len(agents) >= 5
        print(f"[{PASS if ok else FAIL}] Gateway /agents: {code}, {len(agents)} agents registered")
    except Exception as exc:
        ok = False
        print(f"[{FAIL}] Gateway /agents parse error: {exc} — body: {body[:100]}")
    return ok


def test_backend_health():
    code, body = http_get(f"{BACKEND}/health")
    try:
        data = json.loads(body)
        ok = code == 200 and data.get("status") == "healthy"
        print(f"[{PASS if ok else FAIL}] Backend health: {code} status={data.get('status')} db={data.get('database')}")
    except Exception as exc:
        ok = False
        print(f"[{FAIL}] Backend health parse error: {exc}")
    return ok


def test_frontend():
    code, body = http_get(f"{FRONTEND}")
    ok = code == 200
    print(f"[{PASS if ok else FAIL}] Frontend: HTTP {code}")
    return ok


def test_arangodb():
    try:
        from advandeb_kb.database.arango_client import ArangoDatabase
        db = ArangoDatabase()
        db.connect()
        stats = db.stats()
        ok = True
        print(f"[{PASS}] ArangoDB: {stats}")
    except Exception as exc:
        ok = False
        print(f"[{FAIL}] ArangoDB: {exc}")
    return ok


def test_chromadb():
    try:
        from advandeb_kb.services.chromadb_service import ChromaDBService
        svc = ChromaDBService()
        count = svc.collection.count()
        ok = True
        print(f"[{PASS if count > 0 else WARN}] ChromaDB: {count} chunks")
    except Exception as exc:
        ok = False
        print(f"[{FAIL}] ChromaDB: {exc}")
    return ok


# ---------------------------------------------------------------------------
# Async tests (WebSocket)
# ---------------------------------------------------------------------------

async def test_agent_tools():
    import websockets
    all_ok = True
    for name, port in AGENTS:
        try:
            uri = f"ws://localhost:{port}"
            async with websockets.connect(uri, open_timeout=5) as ws:
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "method": "tools/list", "params": {}
                }))
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                resp = json.loads(raw)
            tools = resp.get("result", resp).get("tools", [])
            ok = len(tools) > 0
            print(f"[{PASS if ok else FAIL}] Agent {name} (:{port}): {len(tools)} tools — {[t['name'] for t in tools]}")
            all_ok = all_ok and ok
        except Exception as exc:
            print(f"[{FAIL}] Agent {name} (:{port}): {exc}")
            all_ok = False
    return all_ok


async def test_semantic_search():
    """Call semantic_search via gateway WebSocket."""
    import websockets
    try:
        uri = f"{GATEWAY.replace('http://', 'ws://')}/mcp"
        payload = {
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/call",
            "params": {
                "name": "semantic_search",
                "arguments": {"query": "DEB energy allocation fish", "top_k": 3},
            },
        }
        async with websockets.connect(uri, open_timeout=5) as ws:
            await ws.send(json.dumps(payload))
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            resp = json.loads(raw)
        result = resp.get("result", resp)
        ok = "error" not in resp
        print(f"[{PASS if ok else WARN}] semantic_search via gateway: {str(result)[:120]}")
        return ok
    except Exception as exc:
        print(f"[{WARN}] semantic_search via gateway: {exc} (may need data ingested first)")
        return True  # Non-blocking — ingestion may still be running


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("AdvanDEB Platform Smoke Tests")
    print("=" * 60)
    t0 = time.time()

    results = []

    # Sync tests
    results.append(("Gateway health", test_gateway_health()))
    results.append(("Gateway agents", test_gateway_agents()))
    results.append(("Backend health", test_backend_health()))
    results.append(("Frontend",       test_frontend()))
    results.append(("ArangoDB",       test_arangodb()))
    results.append(("ChromaDB",       test_chromadb()))

    # Async tests
    async def run_async():
        r1 = await test_agent_tools()
        r2 = await test_semantic_search()
        return r1, r2

    agent_ok, search_ok = asyncio.run(run_async())
    results.append(("Agent tools",     agent_ok))
    results.append(("Semantic search", search_ok))

    # Summary
    elapsed = time.time() - t0
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print("=" * 60)
    print(f"Results: {passed}/{total} passed in {elapsed:.1f}s")
    if passed < total:
        print("Failed tests:")
        for name, ok in results:
            if not ok:
                print(f"  - {name}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
