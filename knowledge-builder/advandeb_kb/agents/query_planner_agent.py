"""
QueryPlannerAgent — multi-agent orchestration agent (port 8084).

Tools exposed via MCP:
    plan_query     — decompose a query into a multi-agent execution plan
    execute_plan   — run a plan by calling agents in order
    full_pipeline  — convenience: plan + execute in one call

The planner knows about the other agents:
    retrieval_agent   (port 8081) — semantic/hybrid search
    graph_explorer    (port 8082) — graph traversal + citation chains
    synthesis_agent   (port 8083) — answer generation with citations

Run as standalone process:
    python -m advandeb_kb.agents.query_planner_agent
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.config.settings import settings
from advandeb_kb.mcp.protocol import MCPClient

logger = logging.getLogger(__name__)

AGENT_PORT = 8084

_OLLAMA_MODEL = "llama2"

# Agent registry: name → default WebSocket URL
AGENT_REGISTRY: dict[str, str] = {
    "retrieval_agent": "ws://localhost:8081",
    "graph_explorer": "ws://localhost:8082",
    "synthesis_agent": "ws://localhost:8083",
    "curator_agent": "ws://localhost:8085",
}

# ------------------------------------------------------------------
# Hardcoded plan templates for common query patterns
# (fallback when LLM planning fails or Ollama is unavailable)
# ------------------------------------------------------------------

_DEFAULT_PLAN = [
    {
        "step": 1,
        "agent": "retrieval_agent",
        "tool": "hybrid_search",
        "args_from_query": True,
        "description": "Find relevant text chunks",
    },
    {
        "step": 2,
        "agent": "graph_explorer",
        "tool": "expand_context",
        "args_from_step": 1,
        "description": "Expand context via knowledge graph",
    },
    {
        "step": 3,
        "agent": "synthesis_agent",
        "tool": "synthesize_answer",
        "args_from_steps": [1, 2],
        "description": "Generate cited answer",
    },
]


class QueryPlannerAgent(BaseAgent):
    """
    Orchestrator agent: decomposes user queries into multi-agent plans
    and coordinates execution across the agent network.
    """

    def __init__(self, port: int = AGENT_PORT, host: str = "localhost"):
        super().__init__(name="query_planner", port=port, host=host)
        self._ollama_url = settings.OLLAMA_BASE_URL
        self._agent_clients: dict[str, MCPClient] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        # Pre-create MCPClient instances for each known agent
        for agent_name, ws_url in AGENT_REGISTRY.items():
            self._agent_clients[agent_name] = MCPClient(ws_url)
        logger.info("QueryPlannerAgent initialized — known agents: %s", list(AGENT_REGISTRY))

    def register_tools(self) -> None:
        self.server.register_tool(
            name="plan_query",
            handler=self._plan_query,
            description=(
                "Decompose a user query into a step-by-step multi-agent execution plan. "
                "Returns a plan dict with ordered steps, each specifying which agent "
                "and tool to call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "use_llm_planning": {
                        "type": "boolean",
                        "default": True,
                        "description": "Use Ollama to generate the plan (vs. template fallback)",
                    },
                    "top_k": {"type": "integer", "default": 10},
                    "domain_filter": {"type": "string"},
                },
                "required": ["query"],
            },
        )
        self.server.register_tool(
            name="execute_plan",
            handler=self._execute_plan,
            description="Execute a multi-agent plan returned by plan_query.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "plan": {
                        "type": "object",
                        "description": "Plan dict from plan_query",
                    },
                },
                "required": ["query", "plan"],
            },
        )
        self.server.register_tool(
            name="full_pipeline",
            handler=self._full_pipeline,
            description=(
                "End-to-end: plan + execute. Runs retrieval → graph expansion → "
                "synthesis and returns a cited answer with provenance."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 10},
                    "domain_filter": {"type": "string"},
                    "use_reranking": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        )

    # ------------------------------------------------------------------
    # Tool: plan_query
    # ------------------------------------------------------------------

    async def _plan_query(
        self,
        query: str,
        use_llm_planning: bool = True,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
    ) -> dict:
        if use_llm_planning:
            plan = await self._llm_plan(query, top_k, domain_filter)
            if plan:
                return {"query": query, "source": "llm", "steps": plan}

        # Template fallback
        steps = self._template_plan(query, top_k, domain_filter)
        return {"query": query, "source": "template", "steps": steps}

    def _template_plan(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
    ) -> list[dict]:
        """Standard 3-step plan: retrieve → expand → synthesize."""
        return [
            {
                "step": 1,
                "agent": "retrieval_agent",
                "tool": "hybrid_search",
                "args": {
                    "query": query,
                    "top_k": top_k,
                    **({"domain_filter": domain_filter} if domain_filter else {}),
                },
                "description": "Hybrid retrieval (vector + keyword + RRF)",
            },
            {
                "step": 2,
                "agent": "graph_explorer",
                "tool": "expand_context",
                "args": {"chunk_ids": "__from_step_1_chunk_ids__", "max_hops": 2},
                "description": "Graph expansion from retrieved chunks",
                "depends_on": 1,
            },
            {
                "step": 3,
                "agent": "synthesis_agent",
                "tool": "synthesize_answer",
                "args": {
                    "query": query,
                    "chunks": "__from_step_1_chunks__",
                    "graph_context": "__from_step_2__",
                },
                "description": "Cited answer synthesis",
                "depends_on": [1, 2],
            },
        ]

    async def _llm_plan(
        self,
        query: str,
        top_k: int,
        domain_filter: Optional[str],
    ) -> Optional[list[dict]]:
        """Ask Ollama to generate a JSON execution plan."""
        agent_descriptions = "\n".join(
            f"  - {name}: {url}" for name, url in AGENT_REGISTRY.items()
        )
        prompt = (
            f"You are a query planner for a scientific knowledge system about DEB (Dynamic Energy Budget) theory.\n\n"
            f"Available agents:\n{agent_descriptions}\n\n"
            f"Agent tools:\n"
            f"  retrieval_agent: hybrid_search(query, top_k), semantic_search(query, top_k)\n"
            f"  graph_explorer: expand_context(chunk_ids), get_citation_chain(document_id), find_related_facts(stylized_fact_id)\n"
            f"  synthesis_agent: synthesize_answer(query, chunks, graph_context), summarize_context(chunks)\n\n"
            f"User query: \"{query}\"\n\n"
            f"Generate a minimal execution plan as JSON:\n"
            f"{{\"steps\": ["
            f"{{\"step\": 1, \"agent\": \"retrieval_agent\", \"tool\": \"hybrid_search\", \"args\": {{\"query\": \"{query}\", \"top_k\": {top_k}}}}}, ..."
            f"]}}\n\n"
            f"Return ONLY valid JSON. Keep it to 2-3 steps."
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._ollama_url}/api/generate",
                    json={
                        "model": _OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "{}")
                parsed = json.loads(raw)
                steps = parsed.get("steps", [])
                if steps and isinstance(steps, list):
                    return steps
        except Exception as exc:
            logger.warning("LLM planning failed: %s — using template", exc)
        return None

    # ------------------------------------------------------------------
    # Tool: execute_plan
    # ------------------------------------------------------------------

    async def _execute_plan(self, query: str, plan: dict) -> dict:
        steps = plan.get("steps", [])
        results: dict[int, Any] = {}

        for step in sorted(steps, key=lambda s: s.get("step", 0)):
            step_num = step.get("step", 0)
            agent_name = step.get("agent", "")
            tool_name = step.get("tool", "")
            args: dict = dict(step.get("args", {}))

            # Resolve __from_step_N__ placeholders
            args = self._resolve_args(args, results, query)

            client = self._agent_clients.get(agent_name)
            if not client:
                logger.warning("Unknown agent: %s, skipping step %d", agent_name, step_num)
                results[step_num] = {"error": f"Unknown agent: {agent_name}"}
                continue

            try:
                result = await client.call_tool(tool_name, args)
                results[step_num] = result
                logger.info(
                    "Step %d (%s/%s): OK — keys=%s",
                    step_num,
                    agent_name,
                    tool_name,
                    list(result.keys()) if isinstance(result, dict) else type(result).__name__,
                )
            except Exception as exc:
                logger.error(
                    "Step %d (%s/%s) failed: %s", step_num, agent_name, tool_name, exc
                )
                results[step_num] = {"error": str(exc)}

        return {"query": query, "step_count": len(steps), "results": results}

    # ------------------------------------------------------------------
    # Tool: full_pipeline (convenience)
    # ------------------------------------------------------------------

    async def _full_pipeline(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
        use_reranking: bool = False,
    ) -> dict:
        """Hardwired optimal pipeline: retrieve → graph expand → synthesize."""
        # Step 1: hybrid retrieval
        retrieval_result: dict = {}
        try:
            retrieval_result = await self._agent_clients["retrieval_agent"].call_tool(
                "hybrid_search",
                {
                    "query": query,
                    "top_k": top_k,
                    **({"domain_filter": domain_filter} if domain_filter else {}),
                    "use_reranking": use_reranking,
                },
            )
        except Exception as exc:
            logger.error("Retrieval step failed: %s", exc)
            return {"error": f"Retrieval failed: {exc}"}

        chunks = retrieval_result.get("chunks", [])
        if not chunks:
            return {
                "answer": "No relevant sources found.",
                "citations": [],
                "provenance": None,
                "retrieval_count": 0,
            }

        # Step 2: graph expansion
        graph_context: dict = {}
        chunk_ids = [c.get("chunk_id", c.get("id", "")) for c in chunks]
        try:
            graph_context = await self._agent_clients["graph_explorer"].call_tool(
                "expand_context",
                {"chunk_ids": chunk_ids, "max_hops": 2},
            )
        except Exception as exc:
            logger.warning("Graph expansion failed (non-fatal): %s", exc)

        # Step 3: synthesis
        try:
            synthesis = await self._agent_clients["synthesis_agent"].call_tool(
                "synthesize_answer",
                {"query": query, "chunks": chunks, "graph_context": graph_context},
            )
        except Exception as exc:
            logger.error("Synthesis step failed: %s", exc)
            return {"error": f"Synthesis failed: {exc}"}

        return {
            "query": query,
            "answer": synthesis.get("answer", ""),
            "citations": synthesis.get("citations", []),
            "provenance": synthesis.get("provenance"),
            "retrieval_count": len(chunks),
            "graph_facts": len(graph_context.get("facts", [])),
            "graph_taxa": len(graph_context.get("taxa", [])),
        }

    # ------------------------------------------------------------------
    # Argument resolver
    # ------------------------------------------------------------------

    def _resolve_args(
        self, args: dict, results: dict[int, Any], query: str
    ) -> dict:
        """Replace __from_step_N_*__ placeholders with actual step results."""
        resolved = {}
        for key, val in args.items():
            if not isinstance(val, str) or not val.startswith("__from_step_"):
                resolved[key] = val
                continue

            # Parse: __from_step_1_chunk_ids__ or __from_step_2__
            parts = val.strip("_").split("_")
            # parts[2] = step number, parts[3:] = sub-field path
            try:
                step_num = int(parts[2])
            except (IndexError, ValueError):
                resolved[key] = val
                continue

            step_result = results.get(step_num, {})
            if not isinstance(step_result, dict):
                resolved[key] = step_result
                continue

            # Optional sub-field: __from_step_1_chunks__ → step_result["chunks"]
            sub_field = parts[3] if len(parts) > 3 else None
            if sub_field:
                resolved[key] = step_result.get(sub_field, [])
            else:
                resolved[key] = step_result

        return resolved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = QueryPlannerAgent()
    agent.run()
