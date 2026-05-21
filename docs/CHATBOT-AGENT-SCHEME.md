# Chatbot Agent — Utilisation Scheme

**Status: current implementation, as of 2026-04-14. Written to drive the review of three open issues:**

1. Chat does not finish if the user leaves the website
2. Citations are not visible / not reliably populated in responses
3. No graph exploration when building an answer

---

## 1. Architecture Overview

```
Browser (Vue 3)
    │  WebSocket  ws://.../ws/chat?token=JWT
    ▼
FastAPI  app/backend/app/api/routes/ws.py
    │  websockets.connect  ws://localhost:8086
    ▼
chatbot_agent.py  (port 8086)          ← owns the ReAct loop
    │  MCP WebSocket call (new conn per call)
    ├─► retrieval_agent   (port 8081)  ← hybrid_search
    ├─► graph_explorer    (port 8082)  ← expand_context, get_citation_chain,
    │                                     find_related_facts, find_taxa_for_document
    └─► synthesis_agent   (port 8083)  ← synthesize_answer (fallback only)
```

### Data stores

| Store | What it holds | Who writes | Who reads |
|---|---|---|---|
| MongoDB `advandeb_knowledge_builder_kb` | `chat_sessions`, `chat_messages`, `agent_memory`, `documents`, `facts`, `stylized_facts`, `taxonomy_nodes`, `chunks` | `chatbot_agent` | `chatbot_agent`, `ws.py` |
| ChromaDB | Vector embeddings of chunks | ingestion pipeline | `retrieval_agent` |
| ArangoDB | Named graphs: `chunk_graph`, `support_graph`, `citation_graph`, `knowledge_graph`, `taxonomy_graph` | ingestion/graph-builder pipeline | `graph_explorer` |
| MongoDB `graph_nodes` / `graph_edges` | Materialized layout-ready snapshot of the KB graph | `graph_builder_service` | visualization only (never by agents) |

---

## 2. Message Lifecycle — Step by Step

### 2.1 Request path (browser → agent)

1. Browser sends `{"action": "send_message", "content": "...", "session_id": "..."}` over WebSocket.
2. `ws.py` reads the JWT from `?token=`, resolves `user_id`, calls `chat_service.process_message_stream(user_id, session_id, content)`.
3. `chat_service` opens a WebSocket to `chatbot_agent:8086` and sends an MCP streaming tool call `stream_chat`.
4. `chatbot_agent._chat_stream()` is invoked; it creates an `asyncio.Queue` and fires `asyncio.create_task(run_engine())`.
5. The `_chat_stream` generator yields events from the queue; the MCP server sends each as a WebSocket frame to `chat_service`, which maps them to browser-facing events.

### 2.2 `run_engine()` internal flow

```
_ensure_session()          → upsert chat_sessions document
_load_memory()             → last 10 turns from agent_memory
_store_message(role=user)  → persist user message to chat_messages

ReactEngine.run(query, history)
  └─► ReAct loop (up to MAX_STEPS=10 iterations):
        LLM call (_ollama_chat → POST /api/chat to Ollama)
        parse output for Thought / Action / Final Answer
        if Action:
            call tool, receive Observation
            append to message list for next step
        if Final Answer:
            _extract_citations(answer_text, gathered_chunks)
            return

_enrich_citations()        → query MongoDB documents collection
_store_message(role=asst)  → persist assistant message + citations
_save_memory_turn()        → persist to agent_memory
_touch_session()           → update chat_sessions.updated_at
```

### 2.3 MongoDB write order

| # | When | Collection | What |
|---|---|---|---|
| 1 | Before loop | `chat_sessions` | Upsert session (insert if `session_id == "new"`) |
| 2 | Before loop | `chat_messages` | User message (`role: "user"`, `citations: []`) |
| 3 | After loop | `chat_messages` | Assistant message (`role: "assistant"`, `citations: [...]`, `thoughts: [...]`) |
| 4 | After loop | `agent_memory` | Compressed turn for future context injection |
| 5 | After loop | `chat_sessions` | Touch `updated_at` |

---

## 3. The ReAct Loop — Tool Usage

### 3.1 Tool inventory

| Tool | Agent | Transport | What it actually does |
|---|---|---|---|
| `hybrid_search` | `retrieval_agent:8081` | new WS per call | Vector search (ChromaDB) + keyword search (ArangoDB/MongoDB) → RRF fusion → returns ranked `chunks[]` |
| `expand_context` | `graph_explorer:8082` | new WS per call | ArangoDB AQL traversal: chunk → document → facts → stylized_facts → taxa |
| `get_citation_chain` | `graph_explorer:8082` | new WS per call | ArangoDB AQL traversal on `citation_graph` from a document ID |
| `find_related_facts` | `graph_explorer:8082` | new WS per call | ArangoDB AQL traversal on `support_graph` for a stylized_fact |
| `find_taxa_for_document` | `graph_explorer:8082` | new WS per call | ArangoDB AQL traversal on `knowledge_graph` for a document |
| `synthesize_answer` | `synthesis_agent:8083` | new WS per call | Ollama `/api/generate` with chunks+context; used only as a fallback when `MAX_STEPS` is exhausted |

### 3.2 Typical call sequence the LLM actually produces

In practice, the LLM almost never calls `expand_context`, `get_citation_chain`, or `find_related_facts` unprompted. The observed pattern is:

```
Step 1:  Thought: I should search for information about <topic>
         Action: hybrid_search  {"query": "..."}
         Observation: [1] chunk text ... [2] chunk text ...

Step 2:  Thought: I have enough context to answer.
         Final Answer: ... [1] ... [2] ...
```

The graph exploration tools (`expand_context`, `get_citation_chain`, `find_related_facts`, `find_taxa_for_document`) are available to the LLM but are **not prompted for** and are rarely (if ever) called in practice. The system prompt does not instruct the LLM to use them in a defined order.

### 3.3 System prompt to LLM (what it is told)

The system prompt (`react_engine.py`) tells the LLM:

- It is a bioenergetics expert
- It must follow Thought/Action/Observation/Final Answer format
- It has 6 tools (listed by name + short description)
- It should call `hybrid_search` first, then optionally use graph tools
- It must cite sources as `[1]`, `[2]` etc. matching the Observation numbering
- It has a memory of the last 10 turns injected

The LLM is **not given a mandatory sequence** like "always call expand_context after hybrid_search". It decides autonomously. With a 70B reasoning model that is not fine-tuned on this task, the result is inconsistent tool usage.

---

## 4. Citation Pipeline — Current State

### 4.1 How citations are supposed to work

```
hybrid_search returns chunks  (chunk has: text, chunk_id, document_id in metadata)
       │
       ▼
LLM writes Final Answer with [N] markers (e.g. "... as shown in [1] and [2]")
       │
       ▼
_extract_citations():
  - finds all [N] in the answer text
  - maps N → index N-1 in gathered_chunks list
  - extracts: chunk_id, document_id, text_snippet
       │
       ▼
_enrich_citations():
  - queries MongoDB documents collection by ObjectId
  - attaches: title, authors, year, journal, doi
       │
       ▼
stored in chat_messages.citations[]
       │
       ▼
sent to browser in final WebSocket event
       │
       ▼
ChatInterface.vue maps to Citation objects
MessageList.vue renders clickable badges
```

### 4.2 Where it breaks

| # | Failure mode | Root cause |
|---|---|---|
| A | `[N]` in answer but `N > len(gathered_chunks)` | Out-of-bounds → citation silently dropped |
| B | LLM does not write `[N]` at all | No explicit instruction to use numeric markers; LLM sometimes writes "(Smith 2020)" instead |
| C | `document_id` missing from chunk metadata | Ingestion did not store `document_id` in the chunk's metadata field; `_enrich_citations` finds nothing |
| D | `document_id` is a string but MongoDB expects ObjectId | `ObjectId.is_valid()` fails; fallback query by `document_id` string field may also miss |
| E | LLM calls `hybrid_search` multiple times | Only the **last** call's chunks are kept; citations from earlier searches are lost |
| F | LLM answers from memory without calling `hybrid_search` | `gathered_chunks = []`; no citations at all |
| G | `expand_context` returns additional context but no new chunks | The extra graph context never enters the `gathered_chunks` list used for citation extraction |

---

## 5. Disconnect Behaviour — Current State

### 5.1 What happens now

When the browser WebSocket disconnects (user closes tab, navigates away, network drop):

1. FastAPI `ws.py` catches `WebSocketDisconnect` and exits the handler (`pass`).
2. The `async for event in chat_service.process_message_stream(...)` generator is abandoned.
3. `chat_service`'s `websockets.connect` context to `chatbot_agent:8086` is closed.
4. The MCP server in `chatbot_agent` sees `ConnectionClosed`; it exits the event-send loop.
5. **The `run_engine()` asyncio Task is already running** (`asyncio.create_task`). It continues uninterrupted.
6. The `finally: await task` block in `_chat_stream` ensures the task is awaited even after the consumer is gone.
7. **All MongoDB writes (steps 3-5 from §2.3) complete** regardless of browser state.

### 5.2 The real problem

The `run_engine()` task continues but its **result is never delivered to the user**. When the browser reconnects (automatic 2s retry or manual reload):

- The `chat_sessions` list re-loads; the session is there.
- The conversation history loads — including the assistant message **if the LLM finished** before the user reloaded.
- If the user reloads before the LLM finishes, they see the user message but no assistant response yet. There is no loading indicator or "generating..." state on reload.
- There is no mechanism to "resume" streaming a response that is still in progress.

### 5.3 What is missing

- No in-progress flag on `chat_messages` or `chat_sessions` to indicate generation is ongoing.
- No way for the reconnecting browser to know whether to wait for a response or whether one already exists.
- Events emitted during `run_engine()` while no consumer is connected are dropped (queue fills, generator yields into void).

---

## 6. Issues Summary

### Issue 1 — Chat shall finish its work even if user leaves

**Current state:** `run_engine()` already runs to completion and persists all MongoDB writes even on disconnect. The LLM generation is not interrupted.

**What is actually broken:** The result is silently dropped. On reconnect there is no "still generating" indicator, no push of the completed message, and no catch-up mechanism.

**What needs to be built:**
- Add `status: "generating" | "done" | "failed"` field to `chat_messages` (assistant row inserted before loop, updated after).
- On WebSocket reconnect, the client should check the latest message for `status: "generating"` and show a spinner.
- A Server-Sent Event or a polling endpoint (`GET /api/chat/sessions/{id}/latest`) would let the client catch the completed message after reconnect.

### Issue 2 — Citations not visible / not reliably populated

**Current state:** The citation pipeline exists but has 7 known failure modes (see §4.2). The most common in practice:
- LLM does not consistently use `[N]` markers.
- `document_id` is missing or mismatched in chunk metadata.
- Only the last `hybrid_search` result contributes citations.
- Graph context from `expand_context` never contributes citations.

**What needs to be built:**
- Post-process the Final Answer: if `gathered_chunks` is non-empty but `[N]` markers are absent, rewrite the answer with forced citation injection (second LLM call or rule-based sentence → chunk matching).
- Unify citation source: track `(chunk_id, document_id)` across **all** tool calls, not just the last `hybrid_search`.
- Validate `document_id` at chunk ingestion time so `_enrich_citations` always finds a match.
- Use graph context from `expand_context` to add KB-level citations (facts, SFs) that are not just raw document citations.

### Issue 3 — No graph exploration when building an answer

**Current state:** The 4 graph traversal tools exist and are exposed to the LLM, but:
- The system prompt does not mandate their use.
- The LLM (deepseek-r1:70b) does not spontaneously call them in practice.
- `expand_context` and `get_citation_chain` return data that feeds into the observation but does not affect the citation list.
- There is no concept of a "reasoning chain" that traces document → fact → stylized_fact → taxon and exposes that chain in the answer.

**What needs to be built:**
- Make `expand_context` mandatory after every `hybrid_search`: inject it as a fixed second step in the ReAct loop rather than leaving it to LLM discretion.
- Or: call `expand_context` automatically inside `hybrid_search` and return the enriched result in a single observation.
- Add KB-level citations: when `expand_context` returns facts or SFs, include them in `gathered_chunks` so they can be cited in the answer.
- Expose `graph_nodes`/`graph_edges` traversal as an additional tool that lets the agent explore the materialized MongoDB graph (e.g. "given taxon X, find all stylized facts that are exhibited by it").

---

## 7. Proposed Correct Flow (Target State)

```
User message
    │
    ▼
[persist user msg to chat_messages with status="pending"]
    │
    ▼
Step 1 — Semantic retrieval
    hybrid_search(query)                     → top-K chunks + document_ids
    accumulate ALL chunks across all calls   ← fix: don't replace, append
    │
    ▼
Step 2 — Graph enrichment (MANDATORY, not optional)
    expand_context(chunk_ids from step 1)    → documents, facts, SFs, taxa
    merge facts/SFs into citation pool       ← fix: add to gathered context
    │
    ▼
Step 3 — Optionally deepen (LLM decides)
    get_citation_chain(document_id)          → upstream citations
    find_related_facts(sf_id)                → evidence chain
    find_taxa_for_document(document_id)      → organism context
    │
    ▼
Step 4 — Synthesise answer
    LLM writes Final Answer citing [N]
    fallback: forced post-processing if [N] absent
    │
    ▼
Step 5 — Citation resolution
    map [N] → unified chunk/fact/SF pool     ← fix: all sources, not just chunks
    enrich with MongoDB documents metadata
    │
    ▼
[update chat_messages: content + citations + thoughts, status="done"]
    │
    ▼
[if consumer still connected: stream final event]
[if consumer gone: message retrievable on reconnect via status check]
```

---

## 8. File Reference

| File | Role |
|---|---|
| `knowledge-builder/advandeb_kb/agents/chatbot_agent.py` | Owns `_chat_stream`, `run_engine`, `_enrich_citations`, `_store_message`, `_ensure_session` |
| `knowledge-builder/advandeb_kb/agents/react_engine.py` | Owns `ReactEngine.run()`, `_parse_output`, `_extract_citations`, `_summarize_result`, system prompt |
| `knowledge-builder/advandeb_kb/mcp/protocol.py` | MCP WebSocket server/client; streaming tool call protocol |
| `app/backend/app/api/routes/ws.py` | FastAPI WebSocket endpoint; disconnect handling |
| `app/backend/app/services/chat_service.py` | Bridges FastAPI ↔ chatbot_agent WebSocket; event mapping |
| `app/frontend/src/components/chat/ChatInterface.vue` | WebSocket client; citation object mapping; reconnect logic |
| `app/frontend/src/components/chat/MessageList.vue` | Citation badge rendering; provenance panel trigger |
