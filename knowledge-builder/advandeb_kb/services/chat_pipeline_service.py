"""
ChatPipelineService — deterministic 4-step chat pipeline.

Replaces the open-loop ReAct engine as the DEFAULT chat path.
The ReAct engine is kept and used only when CHAT_MODE="react" or when the
caller explicitly sets mode="react" (e.g. deep-research mode).

Pipeline steps
--------------
1. RETRIEVE      hybrid_search via RetrievalAgent MCP tool
2. GRAPH ENRICH  expand_context via GraphExplorerAgent MCP tool (parallel with step 1 tail)
3. VERIFY        ReferenceVerifierService checks evidence coverage
                 → if verdict=="need_external": trigger ExternalLiteratureService
4. ANSWER        OllamaAnswerAgent constructs the final answer from the frozen
                 EvidenceRegistry using CHAT_ANSWER_MODEL
5. (async)       Follow-up suggestions via CHAT_FOLLOWUP_MODEL — OFF CRITICAL PATH
                 The final answer is yielded BEFORE follow-ups are computed.

Events emitted (async generator interface)
------------------------------------------
    {"type": "status",   "agent": "pipeline", "task": "..."}
    {"type": "thought",  "text": "..."}            (re-used from ReAct events)
    {"type": "tool_call","agent": "...", "tool": "...", "args": {...}}
    {"type": "observation","agent": "...", "tool": "...", "summary": "..."}
    {"type": "final_answer", "text": "..."}
    {"type": "done",     "_final": True, "answer": "...", "citations": [...], ...}

The streaming interface matches ChatbotAgent._chat_stream() so no changes are
needed to chat_service.py or ws.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncGenerator, Callable, Coroutine, Optional

import httpx

from advandeb_kb.config.settings import settings
from advandeb_kb.models.chat import CitationRef, EvidenceMode
from advandeb_kb.services.evidence_registry_service import EvidenceRegistry
from advandeb_kb.services.reference_verifier_service import (
    ReferenceVerifierService,
    VerificationResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Answer construction prompt
# ---------------------------------------------------------------------------

_ANSWER_SYSTEM_PROMPT = """\
You are a scientific research assistant for AdvanDEB, a bioenergetics research platform.
You will be given a QUESTION and a numbered list of EVIDENCE items (text chunks, \
knowledge-graph facts, and stylized facts).

Your task is to write a clear, accurate, and well-cited answer.

CITATION RULES (mandatory):
- Cite evidence inline using the markers shown in brackets: [1], [2], [G1], [SF1], etc.
- Every factual claim MUST carry at least one citation marker.
- Do NOT invent information not present in the evidence.
- Do NOT use marker numbers higher than those shown in the evidence list.

NO-EVIDENCE FALLBACK:
If the evidence list is empty or contains no relevant information, start your answer with:
  "Note: The knowledge base did not return relevant sources. The following is based \
on general bioenergetics knowledge:"
Then provide a substantive best-effort answer anyway — never refuse.

FORMAT:
Write a flowing prose answer. No JSON, no bullet lists unless the question asks for them.
"""


class ChatPipelineService:
    """
    Deterministic 4-step pipeline for a single chat turn.

    Parameters
    ----------
    tool_dispatch:
        Mapping tool_name → async callable(args: dict) → dict.
        Must include at minimum "hybrid_search" and "expand_context".
    on_event:
        Optional async callback for streaming events.
    conversation_history:
        Prior turns as [{role, content}] for prompt context.
    """

    def __init__(
        self,
        tool_dispatch: dict[str, Callable[..., Coroutine]],
        on_event: Optional[Callable[[dict], Coroutine]] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> None:
        self._tools = tool_dispatch
        self._on_event = on_event or _noop_event
        self._history = conversation_history or []
        self._verifier = ReferenceVerifierService()
        self._ollama_url = settings.OLLAMA_BASE_URL
        self._answer_model = settings.CHAT_ANSWER_MODEL
        self._answer_num_ctx = settings.CHAT_ANSWER_NUM_CTX

    # ------------------------------------------------------------------
    # Public streaming API
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        query: str,
        top_k: int = settings.CHAT_DEFAULT_TOP_K,
    ) -> AsyncGenerator[dict, None]:
        """
        Run the pipeline and yield event dicts.  The final dict has
        ``_final=True`` and contains the complete answer payload.

        Usage::

            async for event in pipeline.run_stream(query):
                if event.get("_final"):
                    answer = event["answer"]
                else:
                    # stream to frontend
                    ...
        """
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def _run() -> None:
            try:
                result = await self._run_pipeline(query, top_k, queue)
                await queue.put({**result, "_final": True})
            except Exception as exc:
                logger.error("ChatPipelineService._run_pipeline failed: %s", exc)
                await queue.put({
                    "_final": True,
                    "answer": f"An error occurred while processing your question: {exc}",
                    "citations": [],
                    "evidence_mode": "local",
                    "thoughts": [],
                    "tool_calls_made": [],
                    "suggested_questions": [],
                })

        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("_final"):
                    break
        finally:
            try:
                await task
            except Exception:
                pass

    async def run(
        self,
        query: str,
        top_k: int = settings.CHAT_DEFAULT_TOP_K,
    ) -> dict:
        """Non-streaming convenience wrapper — awaits the full result."""
        result: dict = {}
        async for event in self.run_stream(query, top_k):
            if event.get("_final"):
                result = event
        return result

    # ------------------------------------------------------------------
    # Pipeline implementation
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self, query: str, top_k: int, queue: asyncio.Queue
    ) -> dict:
        tool_calls_made: list[dict] = []

        # ── Step 1: Retrieve ──────────────────────────────────────────
        await self._emit_and_queue(queue, {
            "type": "status", "agent": "pipeline",
            "task": "Searching knowledge base…",
        })
        await self._emit_and_queue(queue, {
            "type": "tool_call", "agent": "retrieval_agent",
            "tool": "hybrid_search", "args": {"query": query, "top_k": top_k},
        })

        retrieval_result = await self._call_tool("hybrid_search", {
            "query": query, "top_k": top_k,
        })
        chunks = retrieval_result.get("chunks", [])
        tool_calls_made.append({
            "tool": "hybrid_search",
            "agent": "retrieval_agent",
            "args": {"query": query, "top_k": top_k},
            "result_summary": f"{len(chunks)} chunks retrieved",
        })

        obs_summary = _summarize_chunks(chunks)
        await self._emit_and_queue(queue, {
            "type": "observation", "agent": "retrieval_agent",
            "tool": "hybrid_search", "summary": obs_summary,
        })

        # ── Step 2: Graph enrich ──────────────────────────────────────
        graph_result: dict = {}
        chunk_ids = [
            c.get("chunk_id") or c.get("id") or c.get("_key")
            for c in chunks[:10]
            if c.get("chunk_id") or c.get("id") or c.get("_key")
        ]

        if chunk_ids and "expand_context" in self._tools:
            await self._emit_and_queue(queue, {
                "type": "status", "agent": "pipeline",
                "task": "Expanding knowledge graph context…",
            })
            await self._emit_and_queue(queue, {
                "type": "tool_call", "agent": "graph_explorer",
                "tool": "expand_context",
                "args": {"chunk_ids": chunk_ids, "max_hops": 2},
            })

            graph_result = await self._call_tool("expand_context", {
                "chunk_ids": chunk_ids, "max_hops": 2,
            })
            facts = graph_result.get("facts", [])
            sfs = graph_result.get("stylized_facts", [])
            graph_summary = (
                f"Graph expansion: {len(facts)} facts, {len(sfs)} stylized facts"
            )
            tool_calls_made.append({
                "tool": "expand_context",
                "agent": "graph_explorer",
                "args": {"chunk_ids": chunk_ids[:5], "max_hops": 2},
                "result_summary": graph_summary,
            })
            await self._emit_and_queue(queue, {
                "type": "observation", "agent": "graph_explorer",
                "tool": "expand_context", "summary": graph_summary,
            })

        # ── Build evidence registry ───────────────────────────────────
        registry = EvidenceRegistry.from_retrieval(chunks, graph_result)

        # ── Step 3: Verify ────────────────────────────────────────────
        await self._emit_and_queue(queue, {
            "type": "status", "agent": "pipeline",
            "task": "Verifying evidence coverage…",
        })

        # We do a preliminary answer generation first so the verifier has
        # something concrete to check. If verification fails we regenerate.
        draft_answer = await self._generate_answer(query, registry, fallback_label=False)

        verification: VerificationResult = await self._verifier.verify(
            query, draft_answer, registry
        )
        evidence_mode: EvidenceMode = verification.evidence_mode or "local"  # type: ignore[assignment]

        if verification.verdict == "need_external" and settings.CHAT_ENABLE_EXTERNAL_FALLBACK:
            await self._emit_and_queue(queue, {
                "type": "status", "agent": "pipeline",
                "task": "Searching external literature (OpenAlex/CrossRef)…",
            })
            external_chunks = await self._external_fallback(query)
            if external_chunks:
                # Merge external chunks into registry and regenerate
                registry = EvidenceRegistry.from_retrieval(
                    chunks + external_chunks, graph_result
                )
                evidence_mode = "local_plus_external"  # type: ignore[assignment]
                draft_answer = await self._generate_answer(
                    query, registry, fallback_label=False
                )
            else:
                evidence_mode = "external_fallback_labeled"  # type: ignore[assignment]
                draft_answer = await self._generate_answer(
                    query, registry, fallback_label=True
                )

        elif verification.verdict == "reject":
            # Hard reject: regenerate with explicit instruction to cite
            await self._emit_and_queue(queue, {
                "type": "status", "agent": "pipeline",
                "task": "Regenerating answer with stricter citation requirements…",
            })
            draft_answer = await self._generate_answer(
                query, registry,
                fallback_label=not bool(registry),
                extra_instruction=(
                    "IMPORTANT: your previous draft was rejected because it contained "
                    "uncited factual claims or used invalid citation markers. "
                    "Every factual sentence MUST carry a citation marker from the list above."
                ),
            )

        # ── Step 4: Emit final answer ─────────────────────────────────
        await self._emit_and_queue(queue, {
            "type": "final_answer", "text": draft_answer,
        })

        # Extract citations from the final answer using the registry
        citation_refs = registry.extract_citations(draft_answer)
        citations = [c.model_dump() for c in citation_refs]

        # Add suggestion prefix if verifier produced one
        if verification.suggestion:
            final_answer = verification.suggestion.rstrip() + "\n\n" + draft_answer
        else:
            final_answer = draft_answer

        # ── Step 5 (off critical path): Follow-up suggestions ─────────
        # Start follow-up generation as a background task, yield the answer
        # payload immediately, and let the task complete asynchronously.
        # The final "done" event includes suggested_questions once ready.
        followup_task = asyncio.create_task(
            self._suggest_followups(query, final_answer)
        )

        # Yield an intermediate "done" without follow-ups so the frontend
        # can display the answer immediately.
        immediate_payload = {
            "answer": final_answer,
            "citations": citations,
            "evidence_mode": evidence_mode,
            "thoughts": [],
            "tool_calls_made": tool_calls_made,
            "suggested_questions": [],  # filled in once followup_task completes
        }

        # We return this to the caller (not queue.put — caller does that).
        # But we also want to send a pre-final event so the WS sends the answer
        # before waiting for follow-ups.
        await queue.put({**immediate_payload, "_answer_ready": True})

        try:
            suggested_questions = await asyncio.wait_for(followup_task, timeout=30)
        except asyncio.TimeoutError:
            logger.warning("ChatPipelineService: follow-up generation timed out")
            suggested_questions = []
        except Exception as exc:
            logger.warning("ChatPipelineService: follow-up generation failed: %s", exc)
            suggested_questions = []

        return {
            **immediate_payload,
            "suggested_questions": suggested_questions,
        }

    # ------------------------------------------------------------------
    # Answer generation
    # ------------------------------------------------------------------

    async def _generate_answer(
        self,
        query: str,
        registry: EvidenceRegistry,
        fallback_label: bool = False,
        extra_instruction: str = "",
    ) -> str:
        """Call CHAT_ANSWER_MODEL to generate a cited answer from the registry."""
        evidence_block = registry.render_observation_block()

        history_block = ""
        if self._history:
            history_lines = []
            for turn in self._history[-6:]:
                role = turn.get("role", "user").capitalize()
                content = turn.get("content", "")[:300]
                history_lines.append(f"{role}: {content}")
            history_block = (
                "CONVERSATION HISTORY (most recent turns):\n"
                + "\n".join(history_lines)
                + "\n\n"
            )

        user_content = (
            f"{history_block}"
            f"EVIDENCE:\n{evidence_block}\n\n"
            f"QUESTION: {query}"
        )
        if fallback_label:
            user_content = (
                "Note: The local knowledge base returned no relevant sources. "
                "Please answer from general bioenergetics knowledge with a clear disclaimer.\n\n"
                + user_content
            )
        if extra_instruction:
            user_content += f"\n\n{extra_instruction}"

        messages = [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            tokens: list[str] = []
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self._ollama_url}/api/chat",
                    json={
                        "model": self._answer_model,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "num_predict": 1200,
                            "temperature": 0.3,
                            "num_ctx": self._answer_num_ctx,
                        },
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            tokens.append(token)
                        if chunk.get("done"):
                            break
            raw = "".join(tokens).strip()
            # Strip DeepSeek <think> block if present
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return raw or "I was unable to generate an answer for this question."
        except Exception as exc:
            logger.error("ChatPipelineService answer generation failed: %s", exc)
            return f"An error occurred while generating the answer: {exc}"

    # ------------------------------------------------------------------
    # Follow-up suggestions
    # ------------------------------------------------------------------

    async def _suggest_followups(self, query: str, answer: str) -> list[str]:
        """Generate 3 follow-up questions using CHAT_FOLLOWUP_MODEL."""
        prompt = (
            "You are a bioenergetics research assistant. Based on the question and "
            "answer below, suggest exactly 3 short, specific follow-up questions.\n\n"
            f"Question: {query}\n\nAnswer (excerpt): {answer[:500]}\n\n"
            "Output ONLY a numbered list:\n1. ...\n2. ...\n3. ..."
        )
        try:
            tokens: list[str] = []
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self._ollama_url}/api/chat",
                    json={
                        "model": settings.CHAT_FOLLOWUP_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True,
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
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            tokens.append(token)
                        if chunk.get("done"):
                            break
            raw = "".join(tokens).strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            numbered = re.findall(r"^\s*\d+[.)]\s*(.+)", raw, re.MULTILINE)
            if numbered:
                return [q.strip() for q in numbered[:3] if q.strip()]
            lines = [ln.strip(" -•") for ln in raw.splitlines() if len(ln.strip()) > 10]
            return lines[:3]
        except Exception as exc:
            logger.warning("ChatPipelineService: follow-up generation failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # External fallback stub (calls ExternalLiteratureService if available)
    # ------------------------------------------------------------------

    async def _external_fallback(self, query: str) -> list[dict]:
        """
        Attempt an external literature search via ExternalLiteratureService.
        Returns a list of chunk-shaped dicts (may be empty if unavailable).
        """
        try:
            from advandeb_kb.services.external_literature_service import (
                ExternalLiteratureService,
            )
            svc = ExternalLiteratureService()
            return await svc.search(query)
        except ImportError:
            logger.debug("ExternalLiteratureService not available yet")
            return []
        except Exception as exc:
            logger.warning("External fallback failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _call_tool(self, tool_name: str, args: dict) -> dict:
        tool = self._tools.get(tool_name)
        if not tool:
            logger.warning("ChatPipelineService: tool %r not in dispatch table", tool_name)
            return {}
        try:
            return await tool(args)
        except Exception as exc:
            logger.warning("ChatPipelineService: tool %r raised: %s", tool_name, exc)
            return {}

    async def _emit_and_queue(self, queue: asyncio.Queue, event: dict) -> None:
        await queue.put(event)
        try:
            await self._on_event(event)
        except Exception as exc:
            logger.warning("on_event callback raised: %s", exc)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

async def _noop_event(_: dict) -> None:
    pass


def _summarize_chunks(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant chunks found."
    lines = [f"Found {len(chunks)} relevant text chunk(s):"]
    for i, c in enumerate(chunks[:8]):
        meta = c.get("metadata", {})
        doc_id = meta.get("document_id", "?")
        text = c.get("text", "")[:200]
        lines.append(f"  [{i+1}] [doc:{doc_id[:8]}] {text}")
    return "\n".join(lines)
