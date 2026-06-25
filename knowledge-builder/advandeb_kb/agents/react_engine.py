"""
ReactEngine — a reusable ReAct (Reason + Act) loop for bioenergetics research.

Design
------
Each call to ``run()`` executes up to MAX_STEPS iterations of:

    Thought:      <LLM reasoning about what to do next>
    Action:       <tool_name>
    Action Input: <JSON argument dict>

followed by an ``Observation:`` block containing the tool result, which is
appended to the growing prompt context so the LLM can build on it.

When the LLM produces a ``Final Answer:`` block the loop terminates and that
text is returned.

If MAX_STEPS is reached without a Final Answer the engine calls
``synthesize_answer`` with all gathered context and marks the answer as
synthesized-from-context rather than LLM-generated.

Events
------
The engine is instrumented via an optional async callback ``on_event``:

    on_event({"type": "thought",       "text": "..."})
    on_event({"type": "tool_call",     "agent": "retrieval_agent",
              "tool": "hybrid_search", "args": {...}})
    on_event({"type": "observation",   "tool": "...", "summary": "..."})
    on_event({"type": "final_answer",  "text": "..."})
    on_event({"type": "error",         "message": "..."})

The callback is always awaited; pass an ``async def`` coroutine.

System prompt
-------------
Broad bioenergetics framing — no bias toward any single framework.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Coroutine, Optional

import httpx

from advandeb_kb.models.chat import CitationRef, make_citation_id, strip_collection_prefix

logger = logging.getLogger(__name__)

MAX_STEPS = 10

# ---------------------------------------------------------------------------
# System prompt — bioenergetics, framework-agnostic
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a scientific research assistant for AdvanDEB, a platform for bioenergetics \
research. You have access to a knowledge base of scientific literature and structured \
facts covering all major frameworks for quantitative organism energetics — Dynamic \
Energy Budget (DEB) theory, Net Energy Theory (NET), Specific Dynamic Action (SDA), \
allometric scaling laws, Metabolic Theory of Ecology (MTE), von Bertalanffy growth \
models, scope-for-growth models, and mechanistic bioenergetics models.

CONVERSATIONAL QUERIES: For greetings, introductions, or questions about who you are, \
respond directly and warmly without calling any tools. Introduce yourself as a \
bioenergetics research assistant and briefly describe what you can help with.

RESEARCH QUERIES: For any factual or scientific question, you MUST call hybrid_search \
at least once before writing a Final Answer. Never answer a research question from \
memory alone — always search the knowledge base first. For questions about general \
principles, patterns, or "what is known about …", ALSO call search_stylized_facts to \
pull in curated, vetted stylized facts, and cite them as [SF1], [SF2], … in your answer.

SUPPORT / CONTRADICT / CONSENSUS: When the user asks which references support or \
contradict a statement, or asks for the consensus on a claim, call claim_consensus \
with that claim FIRST. It returns vetted supporting and opposing references (with \
authors/year/journal/doi) from the curated evidence graph — build the requested table \
or list from its supports[] and opposes[] rows, then optionally run hybrid_search to \
add any references the curated graph missed.

TAXON SCOPING: When a question is restricted to a taxonomic group ("within the \
family/class/genus X", "in <organism>"), call find_by_taxon(name) first to get that \
group's member organism names, then include those names in your hybrid_search queries \
so results stay within the clade. For "across all animal phyla", do not scope.

THOROUGH EXPLORATION: For non-trivial questions, do not stop after a single search. \
Run several hybrid_search calls covering distinct facets of the question (different key \
terms, mechanisms, taxa, or modeling frameworks), and use search_stylized_facts for \
curated principles. Prefer gathering broad, specific evidence over answering quickly.

GROUNDING (TRUE TO THE SOURCES): Base every factual claim on the Observations and cite \
the supporting source for it. Do not generalize beyond what the sources actually say; \
when the evidence is thin, mixed, or absent, state that explicitly rather than \
overstating certainty.

GRAPH CONTEXT (AUTOMATIC): After every hybrid_search the system automatically runs \
expand_context on the retrieved chunks and injects the results as an additional \
"Graph Context" observation. This graph context contains numbered knowledge-graph \
facts [G1], [G2], … and stylized facts [SF1], [SF2], … that you MUST cite alongside \
the text chunks [1], [2], … when they support your answer. Do NOT call expand_context \
yourself — it is already done for you.

NO-RESULTS RULE (CRITICAL): If hybrid_search returns no relevant chunks, or all \
observations say "No relevant chunks found", you MUST still provide a helpful answer. \
Do NOT say "I cannot answer", "I don't have information", or "I'm unable to help". \
Instead, draw on your general scientific knowledge of bioenergetics and CLEARLY label \
the answer: start your Final Answer with "Note: The knowledge base did not return \
relevant sources for this query. The following is based on general bioenergetics \
knowledge:" — then give a substantive answer anyway.

STRICT OUTPUT FORMAT — choose exactly one of the three formats below:

Format A (for greetings / "who are you" / conversational queries — no tool needed):
  Thought: <brief reasoning that this is conversational>
  Final Answer: <warm, helpful reply>

Format B (to call a tool — for research questions):
  Thought: <your reasoning about what to search for>
  Action: <tool_name>
  Action Input: <valid JSON object of arguments>

Format C (after receiving at least one Observation — research answer):
  Thought: <your synthesis reasoning based on the Observations>
  Final Answer: <your answer — cite text chunks as [1], [2], … and graph facts as \
[G1], [G2], … matching the Observation numbering; if no relevant sources were found, \
follow the NO-RESULTS RULE above and provide a general-knowledge answer with a clear \
disclaimer>

Rules:
- Action Input must be valid JSON — no trailing commas, no comments.
- Do not invent facts and present them as coming from the knowledge base.
- NEVER refuse to answer — always provide a best-effort response.
- Do NOT call expand_context — it is called automatically after hybrid_search.
- MANDATORY CITATIONS: Every Final Answer that is based on retrieved Observations \
MUST include at least one inline citation marker [1], [2], [G1], etc. matching the \
numbered chunks shown in the Observations. Citations are pre-resolved from all \
retrieved chunks — use markers to indicate which sources support each claim.
"""

# ---------------------------------------------------------------------------
# Tool catalogue shown to the LLM
# ---------------------------------------------------------------------------

TOOL_DESCRIPTIONS = """\
Available tools:

1. hybrid_search
   Search the knowledge base for relevant text chunks using semantic + keyword \
search. Use this first for any factual question.
   Arguments: {"query": "<string>", "top_k": <int, default 8>}
   NOTE: After this tool returns, the system automatically runs expand_context \
on the retrieved chunks and injects a numbered "Graph Context" observation — \
do NOT call expand_context yourself.

2. get_citation_chain
   Walk the citation graph outward from a document ID. Useful for finding \
related work.
   Arguments: {"document_id": "<string>", "max_depth": <int, default 3>}

3. find_related_facts
   Find raw facts that support or oppose a stylized-fact principle (by its ID).
   Arguments: {"stylized_fact_id": "<string>", "direction": "INBOUND|OUTBOUND|ANY", \
"limit": <int, default 20>}

4. find_taxa_for_document
   Return organisms (taxa) studied in a given document.
   Arguments: {"document_id": "<string>"}

5. search_stylized_facts
   Keyword-search curated stylized facts (high-level, vetted bioenergetics/DEB \
principles) by query. Use alongside hybrid_search for principle/pattern questions \
to surface curated facts directly. Cite returned facts as [SF1], [SF2], ….
   Arguments: {"query": "<string>", "limit": <int, default 10>}

6. claim_consensus
   For a free-text CLAIM, return vetted support-vs-challenge evidence: the closest \
curated stylized fact(s) plus supporting and opposing facts, each with its source \
document (title, authors, year, journal, doi) AND citation signals \
(cited_by_count, citations_per_year, retracted, low_impact). USE THIS FIRST for "list \
references that support/contradict …", "consensus on …", support/challenge tables, and \
citation-decay / "zombie theory" questions — build the table from supports[]/opposes[], \
and for decay/zombie questions report retracted_refs, low_impact_refs and \
per-reference citations_per_year.
   Arguments: {"claim": "<string>", "sf_top": <int, default 3>, "limit_facts": <int, default 60>}

7. find_by_taxon
   Resolve a taxonomic group name (family, class, order, genus, species, or common \
name) to its member organism names. Use to scope a question to a clade — take the \
returned names and add them to your hybrid_search queries.
   Arguments: {"name": "<string>", "max_names": <int, default 150>, "ranks": ["species","genus"]}

8. synthesize_answer
   Generate a cited answer from chunks and graph context. Use this as the \
final step when you have gathered enough context via the other tools.
   Arguments: {"query": "<string>", "chunks": [<chunk dicts>], \
"graph_context": {<expand_context result>}}
"""


# ---------------------------------------------------------------------------
# ReactEngine
# ---------------------------------------------------------------------------

class ReactEngine:
    """
    Runs a ReAct loop against Ollama using the bioenergetics system prompt.

    Parameters
    ----------
    ollama_url:
        Base URL of the Ollama HTTP API (e.g. ``http://localhost:11434``).
    model:
        Ollama model name to use (e.g. ``deepseek-r1:70b``).
    tool_dispatch:
        Mapping from tool_name → async callable(arguments: dict) → dict.
    on_event:
        Optional async callback for streaming intermediate events.
    conversation_history:
        List of prior turns: [{"role": "user"|"assistant", "content": "..."}].
    max_steps:
        Maximum ReAct iterations before forcing synthesis (default 10).
    num_ctx:
        Ollama context window size.  Defaults to 8192.  Large models like
        deepseek-r1:70b require a small num_ctx to fit in available VRAM.
    """

    def __init__(
        self,
        ollama_url: str,
        model: str,
        tool_dispatch: dict[str, Callable[..., Coroutine]],
        on_event: Optional[Callable[[dict], Coroutine]] = None,
        conversation_history: Optional[list[dict]] = None,
        max_steps: int = MAX_STEPS,
        num_ctx: int = 8192,
        provider: Optional[Any] = None,
        answer_max_tokens: int = 1200,
    ):
        self._ollama_url = ollama_url
        self._model = model
        self._tools = tool_dispatch
        self._on_event = on_event or self._noop_event
        self._history = conversation_history or []
        self._max_steps = max_steps
        self._num_ctx = num_ctx
        # Per-LLM-call output cap. Each ReAct step (Thought/Action and the Final
        # Answer) uses this — raise it to allow longer final answers. Intermediate
        # steps naturally stop after emitting an action, so a higher cap mostly
        # benefits the final answer.
        self._answer_max_tokens = answer_max_tokens
        # Optional BYOK provider (advandeb_kb.services.llm_providers.BaseLLMProvider).
        # When set, the reasoning LLM calls go to this provider instead of Ollama,
        # so the user's own Claude/OpenAI/Gemini/GitHub model drives the multi-step
        # ReAct loop. The OpenAI-compatible message shape is identical to Ollama's
        # /api/chat, so no message translation is needed here.
        self._provider = provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, query: str, top_k: int = 8) -> dict:
        """
        Run the ReAct loop for a single user query.

        Returns
        -------
        dict with keys:
          answer           str   — final answer text
          citations        list  — citation dicts from synthesize_answer
          thoughts         list  — all Thought strings emitted
          tool_calls_made  list  — [{tool, args, result_summary}, ...]
          steps_taken      int
        """
        thoughts: list[str] = []
        tool_calls_made: list[dict] = []
        gathered_chunks: list[dict] = []
        gathered_graph_context: dict = {}

        # Background task: expand_context fires concurrently with the next LLM call
        # after every hybrid_search. Resolved at the top of the next iteration so
        # its graph observation is injected before the LLM writes a Final Answer.
        pending_expand_task: asyncio.Task | None = None
        pending_expand_chunks_snapshot: list[dict] = []

        # Build the chat messages list (system + history + current query)
        messages = self._build_messages(query)

        for step in range(1, self._max_steps + 1):
            logger.debug("ReactEngine step %d/%d", step, self._max_steps)

            # Resolve any pending expand_context task from the previous step.
            # This ran concurrently with the LLM's last generation — by the time
            # we reach here the graph DB query is almost certainly done.
            if pending_expand_task is not None:
                try:
                    graph_result = await pending_expand_task
                except Exception as gexc:
                    logger.warning("Auto expand_context failed: %s", gexc)
                    graph_result = {}
                pending_expand_task = None

                gathered_graph_context = graph_result
                base_idx = len(pending_expand_chunks_snapshot)
                synthetic = _graph_result_to_chunks(graph_result, base_idx)
                gathered_chunks.extend(synthetic)

                graph_obs = _summarize_result(
                    "expand_context", graph_result,
                    start_index=base_idx + 1,
                )
                await self._emit({
                    "type": "observation",
                    "agent": "graph_explorer",
                    "tool": "expand_context",
                    "summary": graph_obs,
                    "step": step,
                    "auto": True,
                })
                messages.append({"role": "user",
                                 "content": f"Graph Context (automatic):\n{graph_obs}"})

            raw = await self._ollama_chat(messages)
            if not raw:
                await self._emit({"type": "error", "message": "Empty LLM response"})
                break

            # --- Parse the LLM output ---
            parsed = self._parse_output(raw)

            thought = parsed.get("thought", "")
            if thought:
                thoughts.append(thought)
                await self._emit({"type": "thought", "text": thought, "step": step})

            # --- Final Answer ---
            if "final_answer" in parsed:
                # Only enforce tool-call requirement for research queries.
                # Conversational queries (greetings, identity questions) may
                # answer directly without searching.
                if not tool_calls_made and not _is_conversational(query):
                    # Inject a nudge as an assistant message + user observation
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": (
                        "Observation: [This looks like a research question. "
                        "You must call hybrid_search at least once before writing "
                        "a Final Answer. Please search the knowledge base now.]"
                    )})
                    logger.debug(
                        "ReactEngine: premature Final Answer at step %d — nudging", step
                    )
                    continue

                final_text = parsed["final_answer"]

                # Post-processing: if the answer is a refusal, nudge toward a
                # best-effort general-knowledge answer.
                if tool_calls_made and _is_refusal(final_text):
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": (
                        "Observation: [Your previous response refused to answer. "
                        "This is not acceptable. You MUST provide a substantive answer. "
                        "Draw on your general scientific knowledge of bioenergetics. "
                        "Start your Final Answer with: 'Note: The knowledge base did not "
                        "return relevant sources. The following is based on general "
                        "bioenergetics knowledge:' and then give a real answer.]"
                    )})
                    logger.debug(
                        "ReactEngine: refusal detected at step %d — forcing answer", step
                    )
                    continue

                # Faithfulness check: flag (non-destructively) an answer that
                # cites none of the retrieved sources.
                final_text = self._with_grounding_note(
                    final_text, gathered_chunks, tool_calls_made
                )
                await self._emit({"type": "final_answer", "text": final_text})
                # Citations are built deterministically from all gathered chunks.
                # Inline markers ([1], [G2], …) promote cited chunks to the front
                # of the list but citations are present even without markers.
                citations = self._extract_citations(final_text, gathered_chunks)
                return {
                    "answer": final_text,
                    "citations": citations,
                    "evidence_mode": "local",
                    "thoughts": thoughts,
                    "tool_calls_made": tool_calls_made,
                    "steps_taken": step,
                }

            # --- Tool call ---
            if "action" not in parsed:
                # LLM produced neither a tool call nor a final answer.
                # Check if it produced a freeform answer without the format markers
                stripped = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                if stripped and len(stripped) > 50:
                    # Treat it as a Final Answer if tool calls have been made or
                    # it's a conversational query.
                    if tool_calls_made or _is_conversational(query):
                        logger.debug(
                            "ReactEngine: unformatted response at step %d — treating as Final Answer", step
                        )
                        await self._emit({"type": "final_answer", "text": stripped})
                        citations = self._extract_citations(stripped, gathered_chunks)
                        return {
                            "answer": stripped,
                            "citations": citations,
                            "evidence_mode": "local",
                            "thoughts": thoughts,
                            "tool_calls_made": tool_calls_made,
                            "steps_taken": step,
                        }
                # Otherwise nudge
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": (
                    "Observation: [No action was taken and no Final Answer was given. "
                    "Please output either:\n"
                    "  Thought: ...\n  Action: <tool_name>\n  Action Input: <json>\n"
                    "OR:\n"
                    "  Thought: ...\n  Final Answer: <answer>]"
                )})
                continue

            tool_name = parsed["action"]
            tool_args = parsed.get("action_input", {})

            # Validate tool name
            if tool_name not in self._tools:
                observation = (
                    f"Error: unknown tool '{tool_name}'. "
                    f"Available tools: {', '.join(self._tools)}"
                )
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": f"Observation: {observation}"})
                continue

            # Determine which agent owns this tool
            agent_name = _TOOL_AGENT_MAP.get(tool_name, "knowledge_agent")
            await self._emit({
                "type": "tool_call",
                "agent": agent_name,
                "tool": tool_name,
                "args": tool_args,
                "step": step,
            })

            # Execute the tool
            try:
                result = await self._tools[tool_name](tool_args)
            except Exception as exc:
                logger.warning("Tool %s failed: %s", tool_name, exc)
                result = {"error": str(exc)}

            # Accumulate retrieved context for fallback synthesis
            if tool_name == "hybrid_search":
                # Accumulate across multiple hybrid_search calls, dedup by chunk_id.
                new_chunks = result.get("chunks", [])
                seen_ids = {
                    c.get("chunk_id") or c.get("id")
                    for c in gathered_chunks
                    if c.get("chunk_id") or c.get("id")
                }
                for c in new_chunks:
                    cid = c.get("chunk_id") or c.get("id")
                    if cid not in seen_ids:
                        gathered_chunks.append(c)
                        if cid:
                            seen_ids.add(cid)
                    elif not cid:
                        gathered_chunks.append(c)

                # Fire expand_context as a background task so it runs concurrently
                # with the next LLM call. The graph result is injected into messages
                # before the LLM sees it (awaited at the top of the next iteration).
                pending_expand_task: asyncio.Task | None = None
                pending_expand_chunks_snapshot: list[dict] = list(gathered_chunks)

                if new_chunks and "expand_context" in self._tools:
                    chunk_ids = [
                        c.get("chunk_id") or c.get("id")
                        for c in new_chunks[:20]
                        if c.get("chunk_id") or c.get("id")
                    ]
                    if chunk_ids:
                        await self._emit({
                            "type": "observation",
                            "agent": "graph_explorer",
                            "tool": "expand_context",
                            "summary": "Graph context expansion running in parallel…",
                            "step": step,
                            "auto": True,
                        })
                        pending_expand_task = asyncio.create_task(
                            self._tools["expand_context"]({"chunk_ids": chunk_ids, "max_hops": 2})
                        )

            elif tool_name == "expand_context":
                gathered_graph_context = result

            # Build observation summary for the prompt.
            # For hybrid_search the graph context was already injected into messages
            # at line 400-401 above, so we skip the second Observation append to
            # avoid feeding the LLM two redundant observations for the same call.
            if tool_name == "hybrid_search":
                # Compute start index so chunk numbers match gathered_chunks positions.
                new_chunks = result.get("chunks", [])
                hs_start = len(gathered_chunks) - len(new_chunks) + 1
                obs_summary = _summarize_result(tool_name, result, start_index=hs_start)
            else:
                obs_summary = _summarize_result(tool_name, result)

            tool_calls_made.append({
                "tool": tool_name,
                "agent": agent_name,
                "args": tool_args,
                "result_summary": obs_summary,
            })

            # Append assistant turn to messages (always needed).
            messages.append({"role": "assistant", "content": raw})

            if tool_name == "hybrid_search":
                # Graph context already appended; emit a lightweight observation
                # event for the UI and keep the retrieval observation in the
                # prompt so the LLM can ground later reasoning in the chunk text.
                await self._emit({
                    "type": "observation",
                    "agent": agent_name,
                    "tool": tool_name,
                    "summary": obs_summary,
                    "step": step,
                })
                messages.append({"role": "user", "content": f"Observation: {obs_summary}"})
            else:
                # All other tools: emit observation and append to prompt normally.
                await self._emit({
                    "type": "observation",
                    "agent": agent_name,
                    "tool": tool_name,
                    "summary": obs_summary,
                    "step": step,
                })
                messages.append({"role": "user", "content": f"Observation: {obs_summary}"})

        # --- Max steps reached: force synthesis ---
        logger.warning("ReactEngine: max steps reached — forcing synthesis")
        if gathered_chunks:
            try:
                synthesis = await self._tools["synthesize_answer"]({
                    "query": query,
                    "chunks": gathered_chunks,
                    "graph_context": gathered_graph_context,
                })
                answer = synthesis.get("answer", "Could not generate a complete answer.")
                citations = synthesis.get("citations", [])
            except Exception as exc:
                answer = f"I gathered relevant sources but could not synthesize a complete answer. Error: {exc}"
                citations = []
        else:
            answer = (
                "I was unable to find relevant sources in the knowledge base "
                "to answer this question."
            )
            citations = []

        await self._emit({"type": "final_answer", "text": answer})
        return {
            "answer": answer,
            "citations": citations,
            "evidence_mode": "local",
            "thoughts": thoughts,
            "tool_calls_made": tool_calls_made,
            "steps_taken": self._max_steps,
        }

    # ------------------------------------------------------------------
    # Chat messages construction
    # ------------------------------------------------------------------

    def _build_messages(self, query: str) -> list[dict]:
        """
        Build the initial messages list for the /api/chat endpoint.

        Returns a list of {role, content} dicts:
          [system_prompt, (history turns...), user_query]
        """
        system_content = SYSTEM_PROMPT + "\n\n" + TOOL_DESCRIPTIONS
        messages: list[dict] = [{"role": "system", "content": system_content}]

        # Inject last N conversation turns as prior context
        for turn in self._history[-10:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": query})
        return messages

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_output(self, raw: str) -> dict:
        """
        Parse LLM output into structured fields.

        Handles DeepSeek-R1's <think>...</think> wrapper by stripping it first,
        then looks for Thought/Action/Action Input/Final Answer markers.
        """
        # Strip DeepSeek <think> wrapper if present
        text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        result: dict[str, Any] = {}

        # Extract Thought
        thought_m = re.search(r"Thought:\s*(.*?)(?=\nAction:|\nFinal Answer:|$)", text, re.DOTALL | re.IGNORECASE)
        if thought_m:
            result["thought"] = thought_m.group(1).strip()

        # Extract Final Answer
        fa_m = re.search(r"Final Answer:\s*(.*?)$", text, re.DOTALL | re.IGNORECASE)
        if fa_m:
            result["final_answer"] = fa_m.group(1).strip()
            return result

        # Extract Action
        action_m = re.search(r"Action:\s*(\w+)", text, re.IGNORECASE)
        if action_m:
            result["action"] = action_m.group(1).strip()

        # Extract Action Input (JSON) — use brace-balanced extraction so nested
        # objects and multi-line JSON are captured correctly.
        ai_start = re.search(r"Action Input:\s*\{", text, re.IGNORECASE)
        if ai_start:
            brace_start = ai_start.end() - 1  # position of opening '{'
            depth = 0
            end_idx = brace_start
            for i, ch in enumerate(text[brace_start:], start=brace_start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break
            raw_json = text[brace_start:end_idx]
            try:
                result["action_input"] = json.loads(raw_json)
            except json.JSONDecodeError:
                # Try to fix common LLM JSON mistakes (trailing commas, etc.)
                fixed = re.sub(r",\s*([}\]])", r"\1", raw_json)
                try:
                    result["action_input"] = json.loads(fixed)
                except json.JSONDecodeError:
                    logger.warning("Could not parse Action Input JSON: %s", raw_json[:200])
                    result["action_input"] = {}
        elif "action" in result:
            result["action_input"] = {}

        return result

    # ------------------------------------------------------------------
    # Citation extraction
    # ------------------------------------------------------------------

    def _extract_citations(self, answer_text: str, chunks: list[dict]) -> list[dict]:
        """Build citations from retrieved chunks.

        Primary source: ALL gathered chunks become citations (deterministic).
        The answer_text marker scan ([1], [G2], etc.) is used only to promote
        cited chunks to the front of the list so the most-relevant sources
        appear first in the UI.  Uncited chunks are appended after.

        This guarantees citations are always present whenever chunks were
        retrieved, regardless of whether the LLM used inline markers.
        """
        if not chunks:
            return []

        # Scan the answer for cited markers — these come first
        cited_markers = re.findall(r"\[((?:SF|G)?\d+)\]", answer_text)
        seen_idx: set[int] = set()
        citations: list[dict] = []

        for marker in dict.fromkeys(cited_markers):  # deduplicate, preserve order
            idx = _marker_to_index(marker)
            if idx < 0 or idx >= len(chunks):
                continue
            seen_idx.add(idx)
            citations.append(_citation_from_chunk(marker, chunks[idx]))

        # Append any retrieved chunks NOT referenced by a marker
        for idx, chunk in enumerate(chunks):
            if idx in seen_idx:
                continue
            marker = f"G{idx+1}" if chunk.get("metadata", {}).get("source") in ("fact", "stylized_fact") else str(idx + 1)
            citations.append(_citation_from_chunk(marker, chunk))

        return citations

    # ------------------------------------------------------------------
    # Ollama helper
    # ------------------------------------------------------------------

    @staticmethod
    def _with_grounding_note(
        text: str, gathered_chunks: list[dict], tool_calls_made: list
    ) -> str:
        """Append a transparency note when a research answer cites no sources.

        Non-destructive: if tool calls were made and chunks were retrieved but the
        answer carries no [1]/[G1]/[SF1] markers, flag that uncited statements are
        not verified against the knowledge base. Leaves grounded (or explicitly
        general-knowledge) answers untouched.
        """
        if not tool_calls_made or not gathered_chunks:
            return text
        if re.search(r"\[(?:SF|G)?\d+\]", text):
            return text
        if "general bioenergetics knowledge" in text.lower():
            return text
        return text.rstrip() + (
            "\n\n_⚠️ Grounding note: this answer cites none of the retrieved "
            "sources — treat uncited statements as not verified against the "
            "knowledge base._"
        )

    async def _ollama_chat(self, messages: list[dict], max_tokens: Optional[int] = None) -> str:
        """Call Ollama /api/chat with streaming so tokens are logged as they arrive.

        Using /api/chat (rather than /api/generate) ensures that the system
        prompt is delivered as a proper role:system message, which causes
        deepseek-r1:70b to reliably follow the Thought/Action/Final Answer
        format instead of producing free-form markdown.

        Streaming means:
          - No arbitrary timeout — the connection stays alive as long as Ollama
            is producing tokens.
          - Each chunk is logged at DEBUG level so the agent logs show live
            progress even for very slow 70B generation.
        """
        if max_tokens is None:
            max_tokens = self._answer_max_tokens
        # BYOK path: drive the reasoning step with the user's own provider.
        if self._provider is not None:
            try:
                resp = await self._provider.chat_completion(
                    model=self._model,
                    messages=messages,
                    stream=False,
                    temperature=0.3,
                    max_tokens=max_tokens,
                )
                choices = resp.get("choices") or []
                if choices:
                    content = (choices[0].get("message") or {}).get("content", "")
                    return (content or "").strip()
                return ""
            except Exception as exc:
                logger.error("BYOK provider chat failed: %s", exc)
                return ""

        try:
            tokens: list[str] = []
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self._ollama_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": 0.3,
                            "num_ctx": self._num_ctx,
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
                            logger.debug("react_engine token: %s", token)
                        if chunk.get("done"):
                            break
            return "".join(tokens).strip()
        except Exception as exc:
            logger.error("Ollama chat failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    async def _emit(self, event: dict) -> None:
        try:
            await self._on_event(event)
        except Exception as exc:
            logger.warning("on_event callback raised: %s", exc)

    @staticmethod
    async def _noop_event(_: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Map tool name → agent name (for agent_activity events in the frontend)
_TOOL_AGENT_MAP: dict[str, str] = {
    "hybrid_search": "retrieval_agent",
    "expand_context": "graph_explorer",
    "get_citation_chain": "graph_explorer",
    "find_related_facts": "graph_explorer",
    "find_taxa_for_document": "graph_explorer",
    "synthesize_answer": "synthesis_agent",
}

# Patterns that identify conversational / identity queries that do not require
# a knowledge base search before answering.
_CONVERSATIONAL_PATTERNS = re.compile(
    r"^\s*("
    r"hi+|hello+|hey+|howdy|greetings|good\s+(morning|afternoon|evening)|"
    r"what('s| is) up|how are you(\s+\w+)*|how('s| is) it going|"
    r"who are you|what are you|what can you do|what do you (do|know)|"
    r"introduce yourself|tell me about yourself|"
    r"help|thanks|thank you|bye|goodbye"
    r")\W*$",
    re.IGNORECASE,
)


def _is_conversational(query: str) -> bool:
    """Return True if the query is a greeting or identity question, not a research query."""
    return bool(_CONVERSATIONAL_PATTERNS.match(query.strip()))


# Patterns that indicate the LLM refused to answer instead of giving a best-effort response.
_REFUSAL_PATTERNS = re.compile(
    r"(i (cannot|can't|am unable to|don't have enough|do not have enough)|"
    r"no (information|data|sources|results|relevant)|"
    r"unable to (provide|answer|help|give)|"
    r"i('m| am) (not able|sorry|afraid) (to|i)|"
    r"insufficient (information|data|context)|"
    r"the knowledge base (does not|didn't|did not) (contain|return|have|find))",
    re.IGNORECASE,
)


def _is_refusal(answer: str) -> bool:
    """Return True if the answer is a refusal or 'no information' response."""
    # Only flag as refusal if the answer is short and mostly a refusal
    # (not a full answer that mentions it found nothing but still answers)
    if len(answer) > 600:
        return False  # Long answers are probably real answers even if they disclaim
    return bool(_REFUSAL_PATTERNS.search(answer))


def _citation_sort_key(marker: str) -> tuple[int, str]:
    return (_marker_to_index(marker), marker)


def _marker_to_index(marker: str) -> int:
    match = re.search(r"(\d+)$", marker)
    if not match:
        return -1
    return int(match.group(1)) - 1


def _citation_from_chunk(marker: str, chunk: dict) -> dict:
    meta = chunk.get("metadata", {})
    source = meta.get("source") or "chunk"
    doc_id = chunk.get("document_id") or meta.get("document_id") or ""
    text = chunk.get("text", "")[:200]

    if source == "fact":
        fact_id = strip_collection_prefix(
            str(meta.get("fact_id") or chunk.get("chunk_id") or chunk.get("id") or "")
        )
        return CitationRef(
            citation_id=make_citation_id("fact", fact_id),
            marker=marker,
            source_type="fact",
            document_id=doc_id or None,
            fact_id=fact_id or None,
            evidence_text=text,
        ).model_dump()

    if source == "stylized_fact":
        sf_id = strip_collection_prefix(
            str(meta.get("stylized_fact_id") or chunk.get("chunk_id") or chunk.get("id") or "")
        )
        return CitationRef(
            citation_id=make_citation_id("stylized_fact", sf_id),
            marker=marker,
            source_type="stylized_fact",
            document_id=doc_id or None,
            stylized_fact_id=sf_id or None,
            evidence_text=text,
        ).model_dump()

    chunk_id = strip_collection_prefix(
        str(chunk.get("chunk_id") or chunk.get("id") or chunk.get("_key") or "")
    )
    return CitationRef(
        citation_id=make_citation_id("chunk", chunk_id),
        marker=marker,
        source_type="chunk",
        document_id=doc_id or None,
        chunk_id=chunk_id or None,
        evidence_text=text,
    ).model_dump()


def _graph_result_to_chunks(graph_result: dict, current_pool_size: int) -> list[dict]:
    """Convert expand_context facts and stylized facts into synthetic chunk dicts.

    Each synthetic chunk has the same shape as a real retrieval chunk so that
    ``_extract_citations`` can resolve [N] markers that point into the graph-
    derived portion of gathered_chunks.

    Numbering starts at ``current_pool_size + 1`` so it is contiguous with the
    text chunks already accumulated.
    """
    synthetic: list[dict] = []
    n = current_pool_size  # will be incremented before each append

    for fact in graph_result.get("facts", [])[:8]:
        n += 1
        fid = strip_collection_prefix(
            str(fact.get("_key") or fact.get("_id") or fact.get("id") or f"graph_fact_{n}")
        )
        doc_id = str(fact.get("document_id", ""))
        synthetic.append({
            "chunk_id": make_citation_id("fact", fid),
            "document_id": doc_id,
            "text": fact.get("content", ""),
            "metadata": {
                "document_id": doc_id,
                "source": "fact",
                "fact_id": fid,
                "citation_id": make_citation_id("fact", fid),
            },
        })

    for sf in graph_result.get("stylized_facts", [])[:5]:
        n += 1
        sfid = strip_collection_prefix(
            str(sf.get("_key") or sf.get("_id") or sf.get("id") or f"graph_sf_{n}")
        )
        doc_id = str(sf.get("document_id", ""))
        synthetic.append({
            "chunk_id": make_citation_id("stylized_fact", sfid),
            "document_id": doc_id,
            "text": sf.get("statement", ""),
            "metadata": {
                "document_id": doc_id,
                "source": "stylized_fact",
                "stylized_fact_id": sfid,
                "citation_id": make_citation_id("stylized_fact", sfid),
            },
        })

    return synthetic


def _summarize_result(tool_name: str, result: dict, start_index: int = 1) -> str:
    """Produce a concise Observation string from a tool result dict.

    ``start_index`` is used by the expand_context formatter so that graph-derived
    items are numbered starting after the text chunks already in gathered_chunks,
    making it possible for the LLM to cite them as [N].
    """
    if "error" in result:
        return f"Error: {result['error']}"

    if tool_name == "hybrid_search":
        chunks = result.get("chunks", [])
        count = len(chunks)
        if not chunks:
            return "No relevant chunks found."
        # Show numbered snippet of each chunk for citation tracking.
        # start_index ensures numbers match gathered_chunks positions when there
        # have been multiple hybrid_search calls in the same session.
        lines = [f"Found {count} relevant text chunk(s):"]
        for i, c in enumerate(chunks[:10]):
            text = c.get("text", "")[:300]
            meta = c.get("metadata", {})
            doc_id = meta.get("document_id", "?")
            title = meta.get("title", "")
            src = f" [{title}]" if title else f" [doc:{doc_id[:8]}]"
            lines.append(f"  [{start_index + i}]{src} {text}")
        return "\n".join(lines)

    if tool_name == "expand_context":
        facts = result.get("facts", [])
        docs = result.get("documents", [])
        taxa = result.get("taxa", [])
        sfs = result.get("stylized_facts", [])
        parts = []
        n = start_index
        if docs:
            parts.append(f"{len(docs)} related document(s): " +
                         ", ".join(d.get("title", str(d))[:60] for d in docs[:5]))
        if facts:
            fact_lines = []
            for f in facts[:8]:
                fact_lines.append(f"  [G{n}] {f.get('content', '')[:200]}")
                n += 1
            parts.append(f"{len(facts)} knowledge-graph fact(s):\n" + "\n".join(fact_lines))
        if taxa:
            taxa_names = [t.get("name", "") for t in taxa[:5]]
            parts.append(f"Taxa: {', '.join(taxa_names)}")
        if sfs:
            sf_lines = []
            for s in sfs[:5]:
                sf_lines.append(f"  [SF{n}] {s.get('statement', '')[:200]}")
                n += 1
            parts.append(f"{len(sfs)} stylized fact(s):\n" + "\n".join(sf_lines))
        return "\n".join(parts) if parts else "Graph expansion returned no additional context."

    if tool_name == "get_citation_chain":
        chain = result.get("chain", [])
        return f"Citation chain: {len(chain)} document(s) found." if chain else "No citation chain found."

    if tool_name == "find_related_facts":
        facts = result.get("facts", [])
        if not facts:
            return "No related facts found."
        lines = [f"Found {len(facts)} related fact(s):"]
        for f in facts[:8]:
            lines.append(f"  - {f.get('content', '')[:150]}")
        return "\n".join(lines)

    if tool_name == "find_taxa_for_document":
        taxa = result.get("taxa", [])
        if not taxa:
            return "No taxa linked to this document."
        names = [t.get("name", str(t)) for t in taxa[:10]]
        return f"Taxa: {', '.join(names)}"

    if tool_name == "synthesize_answer":
        return result.get("answer", "")[:400]

    # Generic fallback
    return json.dumps(result)[:500]
