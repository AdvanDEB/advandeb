"""
BYOK chat synthesis — final-answer mode, entirely in-backend.

When a chat session is configured to use one of the user's own LLM keys
(Claude / ChatGPT / Gemini / GitHub Models), the answer is produced *here* in
the backend process rather than by the Ollama-backed chatbot_agent:

    retrieval (MCP retrieval_agent)  →  synthesis (user's provider, in-process)

This design is deliberate: the decrypted API key is fetched, used to mint a
single outbound provider call, and discarded — it never crosses a process
boundary to the internal (unauthenticated) agents. ReAct multi-step reasoning
is *not* offered over BYOK; sessions that ask for ``mode="react"`` with a
non-ollama provider transparently fall back to Ollama in ChatService.

Messages/sessions are written to the same ``chat_sessions`` / ``chat_messages``
collections the chatbot_agent uses, so the history UI is identical regardless
of which path produced an answer.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.clients.mcp_client import MCPClient
from app.core.database import get_database
from app.services.llm_key_service import LLMKeyService

logger = logging.getLogger(__name__)

# Mirrors synthesis_agent's prompt so BYOK answers read the same way and carry
# inline [N] citation markers we can map back to retrieved chunks.
_SYSTEM_PROMPT = (
    "You are a scientific knowledge assistant for Dynamic Energy Budget (DEB) "
    "theory and organism bioenergetics. Answer using ONLY the numbered sources "
    "provided. Cite sources inline as [1], [2], etc. matching the source "
    "numbers. If the sources do not contain the answer, say so explicitly "
    "rather than guessing."
)

# Conversation-memory window (turns) to include for continuity.
_MEMORY_WINDOW = 6


class ByokSynthesisError(RuntimeError):
    """Raised when BYOK synthesis cannot complete (bad key, provider error)."""


class ByokChatService:
    """In-backend retrieval + final-answer synthesis using a user's own key."""

    def __init__(self) -> None:
        db = get_database()
        self.sessions = db.chat_sessions
        self.messages = db.chat_messages
        self.memory = db.agent_memory
        self.keys = LLMKeyService()

    # ------------------------------------------------------------------ public

    async def answer(
        self,
        *,
        query: str,
        session_id: str,
        user_id: str,
        provider: str,
        key_id: str,
        model: Optional[str] = None,
        top_k: int = 8,
        max_tokens: int = 800,
    ) -> Dict[str, Any]:
        """Produce a cited answer for ``query`` using the user's BYOK provider.

        Returns the same shape ChatService callers already expect:
            {answer, citations, evidence_mode, session_id, message_id,
             suggested_questions}
        """
        from advandeb_kb.services.llm_providers import get_provider
        from advandeb_kb.services.llm_providers.base import ProviderError

        # Works for both pasted api keys and OAuth credentials (e.g. GitHub
        # Models via device flow); get_credential refreshes expired tokens.
        api_key = await self.keys.get_credential(user_id, key_id)
        if not api_key:
            raise ByokSynthesisError(
                "The selected LLM credential could not be found or decrypted."
            )

        sid = await self._ensure_session(session_id, user_id, query)
        history = await self._load_memory(sid)
        await self._store_message(sid, role="user", content=query)

        chunks = await self._retrieve(query, top_k)
        if not chunks:
            answer = (
                "I could not find any relevant sources in the knowledge base for "
                "that question."
            )
            message_id = await self._store_message(
                sid, role="assistant", content=answer, evidence_mode="local"
            )
            await self._touch_session(sid)
            return {
                "answer": answer,
                "citations": [],
                "evidence_mode": "local",
                "session_id": sid,
                "message_id": message_id,
                "suggested_questions": [],
            }

        messages = self._build_messages(query, chunks, history)
        chosen_model = model or self._default_model(provider)

        provider_instance = get_provider(provider, api_key=api_key)
        try:
            resp = await provider_instance.chat_completion(
                model=chosen_model,
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=max_tokens,
            )
        except ProviderError as exc:
            # Sanitised — provider errors never contain the plaintext key.
            raise ByokSynthesisError(f"{provider} request failed: {exc.message}") from None
        except Exception as exc:  # noqa: BLE001
            raise ByokSynthesisError(
                f"{provider} request failed: {type(exc).__name__}"
            ) from None
        finally:
            try:
                await provider_instance.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.debug("byok provider close raised", exc_info=True)

        answer = _extract_answer_text(resp)
        citations = self._extract_citations(answer, chunks)

        message_id = await self._store_message(
            sid, role="assistant", content=answer,
            citations=citations, evidence_mode="local",
        )
        await self._save_memory_turn(sid, query, answer, citations)
        await self._touch_session(sid)

        # Mark the key as used (best-effort — get_decrypted_key already bumped it).
        logger.info(
            "byok_chat: answered session=%s user=%s provider=%s model=%s sources=%d",
            sid, user_id, provider, chosen_model, len(chunks),
        )
        return {
            "answer": answer,
            "citations": citations,
            "evidence_mode": "local",
            "session_id": sid,
            "message_id": message_id,
            "suggested_questions": [],
        }

    # --------------------------------------------------------------- retrieval

    async def _retrieve(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Fetch relevant chunks via the MCP retrieval_agent (hybrid_search)."""
        mcp = MCPClient()
        try:
            result = await mcp.call_tool(
                tool_name="hybrid_search",
                arguments={"query": query, "top_k": top_k},
                agent="retrieval_agent",
            )
        except Exception as exc:  # noqa: BLE001
            raise ByokSynthesisError(f"Retrieval failed: {exc}") from None
        return result.get("chunks", []) or []

    # ------------------------------------------------------------ prompt build

    def _build_messages(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        history: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        context_text = _build_context(chunks)
        user_content = (
            f"Sources:\n{context_text}\n\n"
            f"Question: {query}\n\n"
            f"Answer (with inline [N] citations):"
        )
        messages: List[Dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        # Recent conversation context for continuity (already role/content pairs).
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        return messages

    @staticmethod
    def _default_model(provider: str) -> str:
        from advandeb_kb.services.llm_providers import PROVIDERS

        cls = PROVIDERS.get(provider)
        return getattr(cls, "default_model", "") if cls else ""

    # -------------------------------------------------------- citation mapping

    def _extract_citations(
        self, answer_text: str, chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Map [N] markers in the answer back to retrieved chunks."""
        from advandeb_kb.models.chat import (
            CitationRef,
            make_citation_id,
            strip_collection_prefix,
        )

        cited = {int(m) for m in re.findall(r"\[(\d+)\]", answer_text)}
        citations: List[Dict[str, Any]] = []
        for num in sorted(cited):
            idx = num - 1
            if not (0 <= idx < len(chunks)):
                continue
            chunk = chunks[idx]
            meta = chunk.get("metadata", {}) or {}
            chunk_id = strip_collection_prefix(
                str(chunk.get("chunk_id") or chunk.get("id") or chunk.get("_key") or "")
            )
            citations.append(
                CitationRef(
                    citation_id=make_citation_id("chunk", chunk_id),
                    marker=str(num),
                    source_type="chunk",
                    document_id=meta.get("document_id") or chunk.get("document_id") or None,
                    chunk_id=chunk_id or None,
                    evidence_text=chunk.get("text", "")[:200],
                ).model_dump()
            )
        return citations

    # ----------------------------------------------------- session / messages

    async def _ensure_session(
        self, session_id: str, user_id: str, first_message: str
    ) -> str:
        """Return an existing owned session id, or create a new session."""
        if session_id and session_id not in ("", "new"):
            try:
                doc = await self.sessions.find_one(
                    {"_id": ObjectId(session_id), "user_id": user_id}
                )
                if doc:
                    return session_id
            except Exception:
                pass
        now = datetime.now(timezone.utc)
        result = await self.sessions.insert_one(
            {
                "user_id": user_id,
                "title": first_message[:80].strip(),
                "created_at": now,
                "updated_at": now,
            }
        )
        return str(result.inserted_id)

    async def _store_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[list] = None,
        evidence_mode: Optional[str] = None,
        status: str = "done",
    ) -> str:
        now = datetime.now(timezone.utc)
        doc: Dict[str, Any] = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "thoughts": [],
            "status": status,
            "timestamp": now,
        }
        if evidence_mode is not None:
            doc["evidence_mode"] = evidence_mode
        result = await self.messages.insert_one(doc)
        return str(result.inserted_id)

    async def _touch_session(self, session_id: str) -> None:
        try:
            await self.sessions.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"updated_at": datetime.now(timezone.utc)}},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("byok_chat: touch_session failed: %s", exc)

    async def _load_memory(self, session_id: str) -> List[Dict[str, str]]:
        cursor = (
            self.memory.find({"session_id": session_id})
            .sort("turn_index", -1)
            .limit(_MEMORY_WINDOW)
        )
        turns = [doc async for doc in cursor]
        turns.reverse()
        history: List[Dict[str, str]] = []
        for turn in turns:
            history.append({"role": "user", "content": turn.get("user_message", "")})
            history.append({"role": "assistant", "content": turn.get("assistant_answer", "")})
        return history

    async def _save_memory_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_answer: str,
        citations: list,
    ) -> None:
        count = await self.memory.count_documents({"session_id": session_id})
        await self.memory.insert_one(
            {
                "session_id": session_id,
                "turn_index": count,
                "user_message": user_message,
                "assistant_answer": assistant_answer,
                "tool_calls_made": [],
                "citations": citations,
                "created_at": datetime.now(timezone.utc),
            }
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _build_context(chunks: List[Dict[str, Any]]) -> str:
    """Render retrieved chunks as a numbered source list (mirrors synthesis_agent)."""
    lines: List[str] = []
    for i, chunk in enumerate(chunks[:15]):
        text = chunk.get("text", "")
        meta = chunk.get("metadata", {}) or {}
        doc_id = str(meta.get("document_id", ""))
        prefix = f"(doc:{doc_id[:8]}...) " if doc_id else ""
        lines.append(f"[{i + 1}] {prefix}{text[:500]}")
    return "\n\n".join(lines)


def _extract_answer_text(resp: Dict[str, Any]) -> str:
    """Pull the assistant text out of an OpenAI-compatible completion dict."""
    try:
        choices = resp.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content
    except Exception:  # noqa: BLE001
        pass
    return "The model returned an empty response."
