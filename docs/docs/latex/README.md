# LaTeX documents — HISTORICAL

These documents are kept for the record. **They do not describe the current
system**; do not plan or set up from them. Banner added 2026-10-28.

| File | Dated | Content |
|---|---|---|
| `architecture-rationale-en.tex` / `-hr.tex` | 17 Dec 2024 | Architecture rationale, v12.24.2 (English / Croatian) |
| `development-plan-en.tex` / `-hr.tex` | 12 Dec 2025 | Development plan, v3.0 (English / Croatian) |
| `advandeb-architecture.tex` | undated (`\today`), Dec 2025 | System architecture |
| `advandeb-development-environment.tex` | undated (`\today`), Dec 2025 | Development environment |

The rendered `.pdf` beside each file is the same content.

**What has changed since they were written:**
- **Repository layout.** The three repositories they describe
  (`advandeb-modeling-assistant`, `advandeb-knowledge-builder`,
  `advandeb-MCP`) were merged into this monorepo in March 2026.
- **Storage.** They treat MongoDB as the knowledge and graph store. ArangoDB
  is now canonical for knowledge and ChromaDB holds the vectors; MongoDB keeps
  application state.
- **Sign-in.** They make Google OAuth the primary sign-in. Email and password
  is primary now; Google sign-in is implemented but hidden.
- **Language models.** They assume local Ollama models only. Chat now runs
  mostly on external models: a shared NVIDIA default, plus users' own keys.
- **Missing features.** They predate the tDEB simulator, expert elicitation
  and the capability gate.

For the current system, see `../../SYSTEM-OVERVIEW.md`, `../../../RUNNING.md`
and `../../ROADMAP.md`.
