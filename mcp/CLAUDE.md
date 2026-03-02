# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role in the Platform

`mcp/` is an **internal HTTP server** (Rust/Axum) that exposes platform capabilities as Model Context Protocol tools for LLM agent workflows. It is called only by `app/` — never directly by users or external systems. It has **no authentication** by design; `app/` authenticates users before forwarding requests here.

## Current State

Early implementation. Working endpoints:
- `GET /health` — returns `{ "status": "ok", "ollama_model": "..." }`
- `POST /chat` — proxies messages to Ollama; body: `{ "messages": [...], "model": "optional" }`

Planned but not yet implemented: MCP WebSocket endpoints, knowledge query tools, fact extraction tools, document ingestion tools, modeling scenario tools.

## Build & Run

**Prerequisites**: Rust toolchain (`rustup`), Ollama running on `:11434`.

```bash
cargo build
cargo run
cargo test
```

Health check: `curl http://localhost:8080/health`

## Configuration

Settings are loaded from environment variables with prefix `ADVANDEB_MCP_` via the `envy` crate. All have defaults and none are required:

| Env var | Default | Purpose |
|---------|---------|---------|
| `ADVANDEB_MCP_BIND` | `0.0.0.0:8080` | Listen address |
| `ADVANDEB_MCP_OLLAMA_HOST` | `http://localhost:11434` | Ollama API base URL |
| `ADVANDEB_MCP_OLLAMA_MODEL` | `llama2` | Default model for chat |
| `ADVANDEB_MCP_KB_API_BASE` | `http://localhost:8000` | Knowledge Builder base URL |
| `ADVANDEB_MCP_MA_API_BASE` | `http://localhost:9000` | Modeling Assistant base URL |
| `ADVANDEB_MCP_REQUEST_TIMEOUT_SECONDS` | `30` | HTTP client timeout |

## Source Layout

```
src/
├── main.rs      # Entry point: loads Settings, calls serve()
├── lib.rs       # Axum router, AppState, handler functions, serve()
├── config.rs    # Settings struct (deserialized from env via envy)
└── ollama.rs    # Async Ollama HTTP client (OllamaClient)
tests/           # Integration test for /health endpoint
```

`AppState` holds `Settings` and an `OllamaClient` behind `Arc` for shared use across handlers.

## Extending with New Tools

To add a new MCP tool:
1. Add a handler function in `lib.rs` (or a new module)
2. Register the route in `build_router()`
3. Use `state.ollama` for LLM calls and `reqwest` for calls to KB or MA APIs (bases available in `state.settings`)

The `OllamaClient` in `src/ollama.rs` is the only HTTP client abstraction currently in place. For KB API calls, create a similar thin client or use `reqwest` directly.
