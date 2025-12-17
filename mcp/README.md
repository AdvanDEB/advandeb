# advandeb-MCP (Rust)

Model Context Protocol server for the AdvanDEB platform, written in Rust for speed and efficiency. The server wraps local Ollama models and will expose tools for Knowledge Builder and Modeling Assistant.

## Goals
- Fast, resource-efficient MCP server backed by local Ollama models
- Surface platform tools (knowledge queries, audit logging) via a consistent API
- Reuse shared authentication utilities when they become available

## Repo Layout
- `src/lib.rs`: Shared application wiring and Axum router
- `src/main.rs`: Binary entrypoint
- `src/config.rs`: Environment-driven settings
- `src/ollama.rs`: Thin async Ollama client
- `tests/`: Basic health-check test

## Requirements
- Rust toolchain with `cargo` (https://rustup.rs)
- Running Ollama daemon (`ollama serve`) reachable at `OLLAMA_HOST`

## Quickstart
```bash
cd advandeb-MCP
cargo build
cargo run
# in another shell
curl http://localhost:8080/health
```

## Testing
```bash
cargo test
```

Environment overrides (prefix `ADVANDEB_MCP_`): `BIND` (default `0.0.0.0:8080`), `OLLAMA_HOST` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `llama2`), `REQUEST_TIMEOUT_SECONDS` (default `30`).

## Next Steps
- Wire shared authentication utilities once published
- Implement MCP WebSocket endpoints and tool surface for KB/MA data
- Add Docker/devcontainer for predictable local runs
