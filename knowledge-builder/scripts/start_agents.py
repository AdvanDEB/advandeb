#!/usr/bin/env python3
"""
Agent process launcher — starts all 5 advandeb_kb agents as background processes.

Usage:
    # Start all agents
    python scripts/start_agents.py

    # Start specific agents
    python scripts/start_agents.py --agents retrieval graph_explorer synthesis

    # Check health of running agents
    python scripts/start_agents.py --health-check

    # Stop all agents (sends SIGTERM to saved PIDs)
    python scripts/start_agents.py --stop

Logs are written to ./logs/agents/<agent_name>.log
PIDs are saved to ./logs/agents/pids.json for --stop support.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("launcher")

# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------

AGENTS = {
    "retrieval": {
        "module": "advandeb_kb.agents.retrieval_agent",
        "port": 8081,
        "ws_url": "ws://localhost:8081",
        "description": "Semantic + hybrid search",
    },
    "graph_explorer": {
        "module": "advandeb_kb.agents.graph_explorer_agent",
        "port": 8082,
        "ws_url": "ws://localhost:8082",
        "description": "Knowledge graph traversal",
    },
    "synthesis": {
        "module": "advandeb_kb.agents.synthesis_agent",
        "port": 8083,
        "ws_url": "ws://localhost:8083",
        "description": "Answer synthesis with citations",
    },
    "query_planner": {
        "module": "advandeb_kb.agents.query_planner_agent",
        "port": 8084,
        "ws_url": "ws://localhost:8084",
        "description": "Multi-agent orchestration",
    },
    "curator": {
        "module": "advandeb_kb.agents.curator_agent",
        "port": 8085,
        "ws_url": "ws://localhost:8085",
        "description": "Fact extraction + curation",
    },
}

LOGS_DIR = Path(__file__).resolve().parents[1] / "logs" / "agents"
PIDS_FILE = LOGS_DIR / "pids.json"


# ---------------------------------------------------------------------------
# Start helpers
# ---------------------------------------------------------------------------

def start_agent(name: str, cfg: dict) -> subprocess.Popen:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{name}.log"
    log_file = open(log_path, "a")

    python = sys.executable
    cmd = [python, "-m", cfg["module"]]

    logger.info("Starting %s on port %d → log: %s", name, cfg["port"], log_path)
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return proc


def save_pids(pids: dict[str, int]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(PIDS_FILE, "w") as f:
        json.dump(pids, f, indent=2)


def load_pids() -> dict[str, int]:
    if not PIDS_FILE.exists():
        return {}
    with open(PIDS_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def ping_agent(name: str, cfg: dict, timeout: float = 5.0) -> bool:
    from advandeb_kb.mcp.protocol import MCPClient
    client = MCPClient(cfg["ws_url"])
    try:
        return await asyncio.wait_for(client.ping(), timeout=timeout)
    except Exception:
        return False


async def health_check_all(selected: list[str]) -> dict[str, bool]:
    results = {}
    tasks = {
        name: asyncio.create_task(ping_agent(name, AGENTS[name]))
        for name in selected
    }
    for name, task in tasks.items():
        try:
            results[name] = await task
        except Exception:
            results[name] = False
    return results


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

def stop_agents() -> None:
    pids = load_pids()
    if not pids:
        logger.info("No saved PIDs found in %s", PIDS_FILE)
        return
    for name, pid in pids.items():
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to %s (pid=%d)", name, pid)
        except ProcessLookupError:
            logger.info("%s (pid=%d) already stopped", name, pid)
        except Exception as exc:
            logger.warning("Could not stop %s: %s", name, exc)
    PIDS_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AdvanDEB agent launcher")
    parser.add_argument(
        "--agents",
        nargs="+",
        choices=list(AGENTS.keys()),
        default=list(AGENTS.keys()),
        help="Which agents to start (default: all)",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Check health of running agents and exit",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop all saved agent PIDs and exit",
    )
    parser.add_argument(
        "--wait-ready",
        type=int,
        default=5,
        help="Seconds to wait for agents to become ready (default: 5)",
    )
    args = parser.parse_args()

    if args.stop:
        stop_agents()
        return

    if args.health_check:
        results = asyncio.run(health_check_all(args.agents))
        print("\nAgent health:")
        all_ok = True
        for name, ok in results.items():
            status = "✓ OK" if ok else "✗ UNREACHABLE"
            port = AGENTS[name]["port"]
            print(f"  {name:20s} port={port}  {status}")
            if not ok:
                all_ok = False
        sys.exit(0 if all_ok else 1)

    # Start agents
    procs: dict[str, subprocess.Popen] = {}
    pids: dict[str, int] = {}

    for name in args.agents:
        cfg = AGENTS[name]
        proc = start_agent(name, cfg)
        procs[name] = proc
        pids[name] = proc.pid

    save_pids(pids)
    logger.info("Started %d agents. PIDs saved to %s", len(procs), PIDS_FILE)

    # Wait for agents to initialise, then health-check
    logger.info("Waiting %ds for agents to become ready...", args.wait_ready)
    time.sleep(args.wait_ready)

    results = asyncio.run(health_check_all(args.agents))
    print("\nStartup health check:")
    for name, ok in results.items():
        status = "✓ READY" if ok else "⚠ NOT READY (check logs)"
        log_path = LOGS_DIR / f"{name}.log"
        print(f"  {name:20s} port={AGENTS[name]['port']}  {status}")
        if not ok:
            print(f"    → tail {log_path}")

    # Keep running — forward SIGINT/SIGTERM to children
    def _shutdown(sig, _frame):
        logger.info("Received signal %s — stopping agents...", signal.Signals(sig).name)
        for proc in procs.values():
            proc.terminate()
        for proc in procs.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        PIDS_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("All agents running. Press Ctrl+C to stop.")
    while True:
        # Monitor for unexpected exits
        for name, proc in list(procs.items()):
            ret = proc.poll()
            if ret is not None:
                logger.error("Agent '%s' exited unexpectedly with code %d — restarting", name, ret)
                new_proc = start_agent(name, AGENTS[name])
                procs[name] = new_proc
                pids[name] = new_proc.pid
                save_pids(pids)
        time.sleep(10)


if __name__ == "__main__":
    main()
