"""
ChatbotAgent — agentic bioenergetics research assistant (port 8086).

This is the 6th MCP agent in the advandeb_kb system. It exposes a single
``chat`` tool to the MCP gateway, which runs a full ReAct (Reason + Act) loop
powered by Ollama and backed by the knowledge base.

Key features
------------
- Broad bioenergetics scope — no bias toward any single modeling framework
  (DEB, NET, allometric, MTE, SDA, von Bertalanffy, etc.)
- Conversation memory persisted in the app chat database (``agent_memory`` collection)
- Follow-up question generation after each answer
- Full audit trail: thoughts, tool calls, and citations stored per turn
- Chat sessions and messages stored in the app chat DB (``chat_sessions``, ``chat_messages``)

Port layout
-----------
  WebSocket MCP server:  ws://localhost:8086
  HTTP health endpoint:  http://localhost:8186/health

Run as standalone process:
    python -m advandeb_kb.agents.chatbot_agent
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

# Load .env so settings are populated when running under systemd
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[4] / "app" / "backend" / ".env")
except Exception:
    pass

from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.agents.react_engine import ReactEngine
from advandeb_kb.config.settings import settings
from advandeb_kb.mcp.protocol import MCPClient
from advandeb_kb.services.chat_pipeline_service import ChatPipelineService

logger = logging.getLogger(__name__)

AGENT_PORT = 8086

# How many prior turns to inject into the ReAct prompt
MEMORY_WINDOW = 10

# Agents the chatbot calls directly (bypassing the gateway to avoid routing overhead)
_RETRIEVAL_URL = "ws://localhost:8081"
_GRAPH_URL = "ws://localhost:8082"
_SYNTHESIS_URL = "ws://localhost:8083"


class ChatbotAgent(BaseAgent):
    """
    Agentic bioenergetics chatbot — 6th MCP agent.

    Orchestrates the ReAct loop and manages conversation memory in the KB
    database.  Internally calls retrieval_agent, graph_explorer, and
    synthesis_agent directly via MCPClient (not through the gateway) to avoid
    circular routing.
    """

    def __init__(self, port: int = AGENT_PORT, host: str = "localhost"):
        super().__init__(name="chatbot_agent", port=port, host=host)

        self._ollama_url = settings.OLLAMA_BASE_URL
        self._model = settings.CHAT_ANSWER_MODEL
        self._followup_model = settings.CHAT_FOLLOWUP_MODEL

        # Direct MCP clients to the three specialist agents
        self._retrieval_client = MCPClient(_RETRIEVAL_URL)
        self._graph_client = MCPClient(_GRAPH_URL)
        self._synthesis_client = MCPClient(_SYNTHESIS_URL)

        # Motor async DB connection. Chat state lives in the app DB while
        # legacy document metadata is still read from the KB MongoDB.
        self._mongo_client: Optional[AsyncIOMotorClient] = None
        self._chat_db = None  # AsyncIOMotorDatabase
        self._kb_db = None  # AsyncIOMotorDatabase

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect to MongoDB and ensure indexes exist."""
        self._mongo_client = AsyncIOMotorClient(settings.MONGODB_URL)
        self._chat_db = self._mongo_client[settings.CHAT_STORE_DB_NAME]
        self._kb_db = self._mongo_client[settings.DATABASE_NAME]

        await self._ensure_indexes()
        logger.info(
            "ChatbotAgent initialized — model=%s ollama=%s chat_db=%s kb_db=%s",
            self._model,
            self._ollama_url,
            settings.CHAT_STORE_DB_NAME,
            settings.DATABASE_NAME,
        )

    async def _ensure_indexes(self) -> None:
        """Create indexes on the three chat collections."""
        db = self._chat_db

        # chat_sessions
        await db.chat_sessions.create_index(
            [("user_id", 1), ("updated_at", -1)],
            background=True,
            name="chat_sessions_user_updated",
        )

        # chat_messages
        await db.chat_messages.create_index(
            [("session_id", 1), ("timestamp", 1)],
            background=True,
            name="chat_messages_session_time",
        )
        # Index for reconnect catch-up: quickly find in-progress messages
        await db.chat_messages.create_index(
            [("session_id", 1), ("status", 1)],
            background=True,
            name="chat_messages_session_status",
        )

        # agent_memory
        await db.agent_memory.create_index(
            [("session_id", 1), ("turn_index", -1)],
            background=True,
            name="agent_memory_session_turn",
        )

        logger.info("ChatbotAgent: chat indexes verified")

    def register_tools(self) -> None:
        _schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's question or request",
                },
                "session_id": {
                    "type": "string",
                    "description": "Chat session ID (used for memory retrieval)",
                },
                "user_id": {
                    "type": "string",
                    "description": "User ID (for session ownership)",
                    "default": "anonymous",
                },
                "top_k": {
                    "type": "integer",
                    "default": settings.CHAT_DEFAULT_TOP_K,
                    "description": "Max chunks to retrieve per search",
                },
                "llm_provider": {
                    "type": "string",
                    "description": "BYOK provider slug (anthropic/openai/gemini/"
                                   "github_models). Omit or 'ollama' for the local model.",
                },
                "llm_model": {
                    "type": "string",
                    "description": "Model name for the BYOK provider (optional).",
                },
                "llm_key_id": {
                    "type": "string",
                    "description": "Stored user_llm_keys _id; the agent decrypts it "
                                   "to drive reasoning with the user's own model.",
                },
            },
            "required": ["query", "session_id"],
        }
        _description = (
            "Agentic bioenergetics research assistant. "
            "Runs a ReAct loop over the knowledge base to answer questions "
            "about organism energy modeling across all frameworks. "
            "Returns a cited answer, reasoning trace, and follow-up suggestions."
        )

        # Standard (non-streaming) tool — kept for MCP gateway compatibility
        self.server.register_tool(
            name="chat",
            handler=self._chat,
            description=_description,
            input_schema=_schema,
        )

        # Streaming tool — used by chat_service for real-time event delivery
        self.server.register_streaming_tool(
            name="chat_stream",
            handler=self._chat_stream,
            description=_description + " (streaming variant)",
            input_schema=_schema,
        )

    # ------------------------------------------------------------------
    # Tool: chat
    # ------------------------------------------------------------------

    async def _chat(
        self,
        query: str,
        session_id: str,
        user_id: str = "anonymous",
        top_k: int = settings.CHAT_DEFAULT_TOP_K,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_key_id: Optional[str] = None,
    ) -> dict:
        """
        Main chat tool — runs the ReAct loop and returns a full result dict.

        Returns
        -------
        {
          "answer":            str,
          "citations":         list[dict],
          "thoughts":          list[str],
          "tool_calls_made":   list[dict],
          "suggested_questions": list[str],
          "session_id":        str,
          "message_id":        str,
        }
        """
        # 1. Ensure session exists in the app chat DB
        session_id = await self._ensure_session(session_id, user_id, query)

        # 2. Load conversation memory (last N turns)
        history = await self._load_memory(session_id)

        # 3. Store the incoming user message
        await self._store_message(session_id, role="user", content=query)

        # 3b. Insert assistant placeholder with status="generating" so that
        #     a reconnecting browser can detect the in-progress generation.
        placeholder_id = await self._store_message(
            session_id, role="assistant", content="", status="generating"
        )

        # 4. Collect events during the ReAct loop
        events: list[dict] = []

        async def on_event(event: dict) -> None:
            events.append(event)

        # 5. Build tool dispatch table
        tool_dispatch = self._build_tool_dispatch(top_k)

        # 5b. Resolve a BYOK provider (None → local Ollama model).
        provider = await self._build_byok_provider(llm_provider, llm_key_id, user_id)
        model = (
            (llm_model or getattr(provider, "default_model", self._model))
            if provider is not None
            else self._model
        )

        # 6. Run the ReAct loop (driven by the BYOK provider when present)
        engine = ReactEngine(
            ollama_url=self._ollama_url,
            model=model,
            tool_dispatch=tool_dispatch,
            on_event=on_event,
            conversation_history=history,
            num_ctx=settings.CHAT_ANSWER_NUM_CTX,
            provider=provider,
        )

        final_status = "done"
        try:
            result = await engine.run(query=query, top_k=top_k)
        except Exception as exc:
            logger.error("ReactEngine failed: %s", exc)
            result = {
                "answer": f"I encountered an error while processing your question: {exc}",
                "citations": [],
                "thoughts": [],
                "tool_calls_made": [],
                "steps_taken": 0,
            }
            final_status = "failed"
        finally:
            await self._close_provider(provider)

        answer = result["answer"]
        citations = result["citations"]
        thoughts = result["thoughts"]
        tool_calls_made = result["tool_calls_made"]
        evidence_mode = result.get("evidence_mode", "local")

        # Enrich citations and generate follow-up questions in parallel —
        # the two tasks are completely independent of each other.
        citations, suggested_questions = await asyncio.gather(
            self._enrich_citations(citations),
            self._suggest_followups(query, answer),
        )

        # Warn if the ReAct loop made tool calls but produced no citations —
        # this means the LLM answered without citing retrieved chunks.
        if tool_calls_made and not citations:
            logger.warning(
                "chatbot_agent: tool calls were made for session=%s query=%r "
                "but final answer contains no citations — LLM may have ignored "
                "retrieved chunks. Check react_engine logs for details.",
                session_id, query[:80],
            )

        # 8. Finalise the placeholder assistant message in the app chat DB
        message_id = await self._store_message(
            session_id,
            role="assistant",
            content=answer,
            citations=citations,
            thoughts=thoughts,
            evidence_mode=evidence_mode,
            status=final_status,
            message_id=placeholder_id,
        )

        # 9. Persist turn in agent_memory
        await self._save_memory_turn(
            session_id=session_id,
            user_message=query,
            assistant_answer=answer,
            tool_calls_made=tool_calls_made,
            citations=citations,
        )

        # 10. Touch session timestamp
        await self._touch_session(session_id)

        return {
            "answer": answer,
            "citations": citations,
            "thoughts": thoughts,
            "tool_calls_made": tool_calls_made,
            "evidence_mode": evidence_mode,
            "suggested_questions": suggested_questions,
            "session_id": session_id,
            "message_id": str(message_id),
        }

    # ------------------------------------------------------------------
    # Streaming tool: chat_stream
    # ------------------------------------------------------------------

    async def _chat_stream(
        self,
        query: str,
        session_id: str,
        user_id: str = "anonymous",
        top_k: int = settings.CHAT_DEFAULT_TOP_K,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_key_id: Optional[str] = None,
    ):
        """
        Async generator version of _chat that yields intermediate events in
        real-time followed by a final ``{"_final": True, ...}`` dict.

        Event shapes yielded:
          {"type": "thought",    "text": "...", "step": N}
          {"type": "tool_call",  "agent": "...", "tool": "...", "args": {...}, "step": N}
          {"type": "observation","tool": "...", "summary": "...", "step": N}
          {"type": "final_answer","text": "..."}
          {"_final": True, "answer": "...", "citations": [...], ...}
        """
        import asyncio

        # Use an async queue to bridge the ReactEngine callback with this generator
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(("event", event))

        async def run_engine():
            import asyncio as _aio

            async def emit(event: dict) -> None:
                await queue.put(("event", event))

            # ── Step 0: session setup ──────────────────────────────────────
            await emit({"type": "status", "agent": "chatbot",
                        "status": "working", "task": "Setting up session…"})
            sid = await self._ensure_session(session_id, user_id, query)
            history = await self._load_memory(sid)
            await self._store_message(sid, role="user", content=query)
            placeholder_id = await self._store_message(
                sid, role="assistant", content="", status="generating"
            )

            # ── Step 1: LLM warm-up probe ──────────────────────────────────
            # Check if Ollama already has the model loaded by hitting /api/tags.
            # Emit a clear "loading model" event so the user knows what is slow.
            await emit({"type": "status", "agent": "chatbot",
                        "status": "working",
                        "task": f"Checking LLM ({self._model})…"})
            model_ready = await self._probe_ollama_model()
            if not model_ready:
                await emit({"type": "status", "agent": "chatbot",
                            "status": "working",
                            "task": f"Loading model {self._model} into GPU — this may take 1–2 min on first use…"})
            else:
                await emit({"type": "status", "agent": "chatbot",
                            "status": "working",
                            "task": f"Model {self._model} ready"})

            # ── Step 2: Run pipeline or ReAct ─────────────────────────────
            tool_dispatch = self._build_tool_dispatch(top_k)

            # Resolve a BYOK provider. When the user brings their own model we
            # always run the multi-step ReAct loop on it (the deterministic
            # pipeline delegates synthesis to the Ollama-only synthesis_agent).
            provider = await self._build_byok_provider(llm_provider, llm_key_id, user_id)
            byok_model = (
                (llm_model or getattr(provider, "default_model", self._model))
                if provider is not None
                else self._model
            )

            use_pipeline = settings.CHAT_MODE != "react" and provider is None
            final_status = "done"

            if use_pipeline:
                await emit({"type": "status", "agent": "chatbot",
                            "status": "working", "task": "Running deterministic pipeline…"})
                pipeline = ChatPipelineService(
                    tool_dispatch=tool_dispatch,
                    on_event=on_event,
                    conversation_history=history,
                )
                engine_result = {}
                engine_exc = None
                async for evt in pipeline.run_stream(query=query, top_k=top_k):
                    if evt.get("_final"):
                        engine_result = {k: v for k, v in evt.items() if k != "_final"}
                    elif evt.get("_answer_ready"):
                        # Final answer is ready — emit it immediately to the WS
                        # before follow-ups are generated.
                        await emit({"type": "final_answer",
                                    "text": evt.get("answer", "")})
                    else:
                        await emit(evt)
                if not engine_result:
                    engine_result = {
                        "answer": "Pipeline produced no result.",
                        "citations": [],
                        "thoughts": [],
                        "tool_calls_made": [],
                        "evidence_mode": "local",
                        "suggested_questions": [],
                    }
            else:
                loop_label = (
                    f"Starting reasoning loop on your {llm_provider} model…"
                    if provider is not None
                    else "Starting reasoning loop…"
                )
                await emit({"type": "status", "agent": "chatbot",
                            "status": "working", "task": loop_label})
                engine = ReactEngine(
                    ollama_url=self._ollama_url,
                    model=byok_model,
                    tool_dispatch=tool_dispatch,
                    on_event=on_event,
                    conversation_history=history,
                    num_ctx=settings.CHAT_ANSWER_NUM_CTX,
                    provider=provider,
                )

                engine_result = {}
                engine_exc = None

                async def _run():
                    nonlocal engine_result, engine_exc
                    try:
                        engine_result = await engine.run(query=query, top_k=top_k)
                    except Exception as exc:
                        engine_exc = exc

                engine_task = _aio.create_task(_run())

                heartbeat_interval = 15
                elapsed = 0
                while not engine_task.done():
                    try:
                        await _aio.wait_for(_aio.shield(engine_task), timeout=heartbeat_interval)
                    except _aio.TimeoutError:
                        elapsed += heartbeat_interval
                        await emit({"type": "status", "agent": "chatbot",
                                    "status": "working",
                                    "task": f"LLM reasoning… ({elapsed}s elapsed)"})

                if engine_exc:
                    logger.error("ReactEngine (stream) failed: %s", engine_exc)
                    engine_result = {
                        "answer": f"I encountered an error: {engine_exc}",
                        "citations": [],
                        "thoughts": [],
                        "tool_calls_made": [],
                        "steps_taken": 0,
                    }
                    final_status = "failed"

            await self._close_provider(provider)

            result = engine_result
            answer = result["answer"]
            citations = result["citations"]
            thoughts = result.get("thoughts", [])
            tool_calls_made = result["tool_calls_made"]
            evidence_mode = result.get("evidence_mode", "local")
            # Pipeline already generated follow-ups off the critical path;
            # ReAct mode needs them generated here.
            if use_pipeline:
                suggested_questions = result.get("suggested_questions", [])
                citations = await self._enrich_citations(citations)
            else:
                # ── Step 3: post-processing — citations + follow-ups in parallel ──
                await emit({"type": "status", "agent": "chatbot",
                            "status": "working",
                            "task": "Enriching citations and generating follow-up suggestions…"})
                citations, suggested_questions = await asyncio.gather(
                    self._enrich_citations(citations),
                    self._suggest_followups(query, answer),
                )

            # Warn if tool calls were made but no citations came back
            if tool_calls_made and not citations:
                logger.warning(
                    "chatbot_agent (stream): tool calls made for session=%s query=%r "
                    "but final answer contains no citations — LLM may have ignored "
                    "retrieved chunks. Check react_engine logs for details.",
                    sid, query[:80],
                )

            message_id = await self._store_message(
                sid, role="assistant", content=answer,
                citations=citations, thoughts=thoughts,
                evidence_mode=evidence_mode,
                status=final_status, message_id=placeholder_id,
            )
            await self._save_memory_turn(
                session_id=sid,
                user_message=query,
                assistant_answer=answer,
                tool_calls_made=tool_calls_made,
                citations=citations,
            )
            await self._touch_session(sid)

            await queue.put(("done", {
                "_final": True,
                "answer": answer,
                "citations": citations,
                "thoughts": thoughts,
                "tool_calls_made": tool_calls_made,
                "evidence_mode": evidence_mode,
                "suggested_questions": suggested_questions,
                "session_id": sid,
                "message_id": str(message_id),
            }))

        # Start the engine task; consume queue while it runs
        task = asyncio.create_task(run_engine())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "event":
                    yield payload
                else:  # "done"
                    yield payload
                    break
        finally:
            # Ensure the engine task is awaited even if the consumer disconnects
            try:
                await task
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Tool dispatch table
    # ------------------------------------------------------------------

    def _build_tool_dispatch(self, top_k: int) -> dict:
        """Return a mapping of tool_name → async callable(args_dict)."""

        async def hybrid_search(args: dict) -> dict:
            if not args.get("query"):
                return {"error": "hybrid_search requires a 'query' argument", "chunks": []}
            args.setdefault("top_k", top_k)
            return await self._retrieval_client.call_tool("hybrid_search", args)

        async def expand_context(args: dict) -> dict:
            args.setdefault("max_hops", 2)
            return await self._graph_client.call_tool("expand_context", args)

        async def get_citation_chain(args: dict) -> dict:
            args.setdefault("max_depth", 3)
            return await self._graph_client.call_tool("get_citation_chain", args)

        async def find_related_facts(args: dict) -> dict:
            args.setdefault("direction", "INBOUND")
            args.setdefault("limit", 20)
            return await self._graph_client.call_tool("find_related_facts", args)

        async def find_taxa_for_document(args: dict) -> dict:
            return await self._graph_client.call_tool("find_taxa_for_document", args)

        async def synthesize_answer(args: dict) -> dict:
            return await self._synthesis_client.call_tool("synthesize_answer", args)

        return {
            "hybrid_search": hybrid_search,
            "expand_context": expand_context,
            "get_citation_chain": get_citation_chain,
            "find_related_facts": find_related_facts,
            "find_taxa_for_document": find_taxa_for_document,
            "synthesize_answer": synthesize_answer,
        }

    # ------------------------------------------------------------------
    # Ollama helpers
    # ------------------------------------------------------------------

    async def _probe_ollama_model(self) -> bool:
        """Return True if the model is currently loaded (warm) in Ollama.

        Uses GET /api/ps which lists models that are actively loaded in GPU/RAM.
        Falls back to True on error so we never block the chat with a false alarm.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._ollama_url}/api/ps")
                resp.raise_for_status()
                data = resp.json()
                loaded = [m.get("name", "") for m in data.get("models", [])]
                return any(self._model in m for m in loaded)
        except Exception:
            return True  # Can't tell — assume ready, don't alarm user

    # ------------------------------------------------------------------
    # Follow-up question generation
    # ------------------------------------------------------------------

    async def _suggest_followups(self, query: str, answer: str) -> list[str]:
        """Generate 3 follow-up question suggestions via Ollama.

        DeepSeek-R1 does not reliably honour ``format: "json"``, so we ask for
        a plain numbered list and parse it ourselves, with a JSON-array regex
        as a secondary fallback.
        """
        import json as _json
        import re as _re

        prompt = (
            "You are a bioenergetics research assistant. Based on the question and "
            "answer below, suggest exactly 3 short, specific follow-up questions a "
            "researcher might ask next.\n\n"
            f"Question: {query}\n\n"
            f"Answer (excerpt): {answer[:600]}\n\n"
            "Output ONLY a numbered list, one question per line, like:\n"
            "1. <question>\n"
            "2. <question>\n"
            "3. <question>"
        )
        try:
            tokens: list[str] = []
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self._ollama_url}/api/chat",
                    json={
                        "model": self._followup_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True,
                        "think": False,       # suppress <think> chain — not needed for follow-ups
                        "options": {
                            "num_predict": 150,
                            "temperature": 0.5,
                            "num_ctx": settings.CHAT_FOLLOWUP_NUM_CTX,
                        },
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            tokens.append(token)
                            logger.debug("followup token: %s", token)
                        if chunk.get("done"):
                            break
            raw = "".join(tokens).strip()

            # Strip DeepSeek <think>...</think> blocks
            raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()

            # --- Attempt 1: numbered list (preferred output format) ---
            numbered = _re.findall(r"^\s*\d+[.)]\s*(.+)", raw, _re.MULTILINE)
            if numbered:
                return [q.strip() for q in numbered[:3] if q.strip()]

            # --- Attempt 2: JSON array anywhere in the output ---
            json_match = _re.search(r"\[.*?\]", raw, _re.DOTALL)
            if json_match:
                try:
                    parsed = _json.loads(json_match.group(0))
                    if isinstance(parsed, list):
                        return [str(q) for q in parsed[:3] if q]
                except _json.JSONDecodeError:
                    pass

            # --- Attempt 3: JSON object with a known key ---
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, list):
                    return [str(q) for q in parsed[:3] if q]
                if isinstance(parsed, dict):
                    for key in ("questions", "follow_up_questions", "followups"):
                        val = parsed.get(key)
                        if isinstance(val, list):
                            return [str(q) for q in val[:3] if q]
            except _json.JSONDecodeError:
                pass

            # --- Attempt 4: plain non-empty lines ---
            lines = [ln.strip(" -•") for ln in raw.splitlines() if ln.strip()]
            if lines:
                return lines[:3]

            return []

        except Exception as exc:
            logger.warning("Follow-up generation failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # MongoDB helpers
    # ------------------------------------------------------------------

    async def _enrich_citations(self, citations: list[dict]) -> list[dict]:
        """Look up document metadata for each citation and attach it inline.

        Adds ``title``, ``authors``, ``year``, and ``journal`` from the
        ``documents`` collection so the frontend can render proper source cards.
        """
        if not citations:
            return citations

        # Collect unique document IDs
        doc_ids_raw = [c.get("document_id", "") for c in citations if c.get("document_id")]
        if not doc_ids_raw:
            return citations

        # Try to convert to ObjectId (MongoDB _id is stored as ObjectId)
        from bson import ObjectId as OID
        oid_ids = []
        str_ids = []
        for d in set(doc_ids_raw):
            try:
                oid_ids.append(OID(d))
            except Exception:
                str_ids.append(d)

        doc_map: dict[str, dict] = {}

        # Query by ObjectId _id
        if oid_ids:
            cursor = self._kb_db.documents.find(
                {"_id": {"$in": oid_ids}},
                {"_id": 1, "title": 1, "authors": 1, "year": 1, "journal": 1, "doi": 1},
            )
            async for doc in cursor:
                doc_id = str(doc["_id"])
                doc_map[doc_id] = {
                    "title":   doc.get("title", ""),
                    "authors": doc.get("authors", []),
                    "year":    doc.get("year", ""),
                    "journal": doc.get("journal", ""),
                    "doi":     doc.get("doi", ""),
                }

        # Fallback: legacy string IDs (e.g. "doc_xxxx") — try ArangoDB documents collection
        if str_ids:
            from advandeb_kb.config.settings import settings as _settings
            import httpx as _httpx

            arango_url = _settings.ARANGO_URL
            arango_db  = _settings.ARANGO_DB_NAME
            arango_user = _settings.ARANGO_USERNAME
            arango_pass = _settings.ARANGO_PASSWORD

            aql = (
                "FOR d IN documents "
                "FILTER d.document_id IN @ids "
                "RETURN {document_id: d.document_id, title: d.title, "
                "authors: d.authors, year: d.year, journal: d.journal, doi: d.doi}"
            )
            try:
                async with _httpx.AsyncClient(timeout=5.0) as hc:
                    resp = await hc.post(
                        f"{arango_url}/_db/{arango_db}/_api/cursor",
                        auth=(arango_user, arango_pass),
                        json={"query": aql, "bindVars": {"ids": str_ids}},
                    )
                    if resp.status_code == 201:
                        for doc in resp.json().get("result", []):
                            doc_id = doc.get("document_id", "")
                            if doc_id:
                                doc_map[doc_id] = {
                                    "title":   doc.get("title", ""),
                                    "authors": doc.get("authors", []),
                                    "year":    doc.get("year", ""),
                                    "journal": doc.get("journal", ""),
                                    "doi":     doc.get("doi", ""),
                                }
            except Exception as exc:
                logger.warning("_enrich_citations ArangoDB fallback failed: %s", exc)

        # Attach metadata to each citation
        enriched = []
        for c in citations:
            doc_id = c.get("document_id", "")
            info = doc_map.get(doc_id, {})
            enriched.append({**c, **info})
        return enriched

    # ------------------------------------------------------------------
    # BYOK provider resolution
    # ------------------------------------------------------------------

    def _decrypt_llm_key(self, encrypted: str) -> Optional[str]:
        """Decrypt a stored BYOK key using LLM_KEY_ENCRYPTION_KEY from the env.

        The agent stack sources app/backend/.env, so the same Fernet key the
        backend uses is available here. The plaintext lives only for the life
        of one request and is never logged.
        """
        import os

        key = os.getenv("LLM_KEY_ENCRYPTION_KEY")
        if not key or not encrypted:
            if not key:
                logger.warning(
                    "LLM_KEY_ENCRYPTION_KEY not set in agent env — BYOK disabled"
                )
            return None
        try:
            from cryptography.fernet import Fernet

            return Fernet(key.encode()).decrypt(encrypted.encode()).decode()
        except Exception as exc:  # noqa: BLE001
            logger.warning("BYOK key decrypt failed: %s", exc)
            return None

    async def _build_byok_provider(
        self, llm_provider: Optional[str], llm_key_id: Optional[str], user_id: str
    ):
        """Return an instantiated BYOK provider for this request, or None.

        Looks up the encrypted key in user_llm_keys (scoped to user_id),
        decrypts it, and builds the provider via the registry. Any failure
        falls back to None so the caller uses the local Ollama model.
        """
        if not llm_key_id or llm_provider in (None, "", "ollama"):
            return None
        try:
            doc = await self._chat_db.user_llm_keys.find_one(
                {"_id": ObjectId(llm_key_id), "user_id": user_id}
            )
        except Exception:
            doc = None
        if not doc:
            logger.warning(
                "BYOK key %s not found for user %s — using local model",
                llm_key_id, user_id,
            )
            return None
        plaintext = self._decrypt_llm_key(doc.get("encrypted_key", ""))
        if not plaintext:
            return None
        try:
            from advandeb_kb.services.llm_providers import get_provider

            provider = get_provider(doc.get("provider", llm_provider), api_key=plaintext)
            logger.info(
                "BYOK: using provider=%s for user=%s (key=%s)",
                doc.get("provider", llm_provider), user_id, llm_key_id,
            )
            return provider
        except Exception as exc:  # noqa: BLE001
            logger.warning("BYOK provider build failed: %s — using local model", exc)
            return None

    @staticmethod
    async def _close_provider(provider) -> None:
        if provider is None:
            return
        try:
            await provider.close()
        except Exception:  # noqa: BLE001
            logger.debug("BYOK provider close raised", exc_info=True)

    async def _ensure_session(
        self, session_id: str, user_id: str, first_message: str
    ) -> str:
        """
        Return the session_id if the session already exists in the chat DB,
        or create a new one.  If session_id is empty/None/``new`` a new
        session is always created.
        """
        db = self._chat_db
        if session_id and session_id not in ("", "new"):
            try:
                doc = await db.chat_sessions.find_one({
                    "_id": ObjectId(session_id),
                    "user_id": user_id,
                })
                if doc:
                    return session_id
            except Exception:
                pass  # Invalid ObjectId or not found — create new

        # Create a new session
        title = first_message[:80].strip()
        now = datetime.now(timezone.utc)
        result = await db.chat_sessions.insert_one({
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        })
        new_id = str(result.inserted_id)
        logger.info("ChatbotAgent: created new chat session %s", new_id)
        return new_id

    async def _touch_session(self, session_id: str) -> None:
        try:
            await self._chat_db.chat_sessions.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"updated_at": datetime.now(timezone.utc)}},
            )
        except Exception as exc:
            logger.warning("touch_session failed: %s", exc)

    async def _store_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[list] = None,
        thoughts: Optional[list] = None,
        evidence_mode: Optional[str] = None,
        status: str = "done",
        message_id: Optional[str] = None,
    ) -> str:
        """Insert or update a chat message in the chat DB and return its _id as str.

        If ``message_id`` is provided the existing document is updated in-place
        (used to finalise a placeholder inserted with ``status="generating"``).
        Otherwise a new document is inserted.

        The ``status`` field enables reconnect catch-up: a browser that reconnects
        while the ReAct loop is still running will find any ``status="generating"``
        messages and show a spinner.
        """
        now = datetime.now(timezone.utc)
        if message_id:
            update_doc = {
                "content": content,
                "citations": citations or [],
                "thoughts": thoughts or [],
                "status": status,
                "finished_at": now,
            }
            if evidence_mode is not None:
                update_doc["evidence_mode"] = evidence_mode
            try:
                await self._chat_db.chat_messages.update_one(
                    {"_id": ObjectId(message_id)},
                    {"$set": update_doc},
                )
            except Exception as exc:
                logger.warning("_store_message update failed: %s", exc)
            return message_id

        doc = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "thoughts": thoughts or [],
            "status": status,
            "timestamp": now,
        }
        if evidence_mode is not None:
            doc["evidence_mode"] = evidence_mode
        result = await self._chat_db.chat_messages.insert_one(doc)
        return str(result.inserted_id)

    async def _load_memory(self, session_id: str) -> list[dict]:
        """Load the last MEMORY_WINDOW turns from agent_memory for this session."""
        cursor = (
            self._chat_db.agent_memory
            .find({"session_id": session_id})
            .sort("turn_index", -1)
            .limit(MEMORY_WINDOW)
        )
        turns = []
        async for doc in cursor:
            turns.append(doc)
        # Reverse so oldest turn is first
        turns.reverse()

        # Flatten to {role, content} pairs for the prompt
        history: list[dict] = []
        for turn in turns:
            history.append({"role": "user", "content": turn.get("user_message", "")})
            history.append({"role": "assistant", "content": turn.get("assistant_answer", "")})
        return history

    async def _save_memory_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_answer: str,
        tool_calls_made: list,
        citations: list,
    ) -> None:
        """Persist one ReAct turn to the agent_memory collection."""
        # Get current turn count
        count = await self._chat_db.agent_memory.count_documents(
            {"session_id": session_id}
        )
        await self._chat_db.agent_memory.insert_one({
            "session_id": session_id,
            "turn_index": count,
            "user_message": user_message,
            "assistant_answer": assistant_answer,
            "tool_calls_made": tool_calls_made,
            "citations": citations,
            "created_at": datetime.now(timezone.utc),
        })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    agent = ChatbotAgent()
    agent.run()
