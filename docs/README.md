# AdvanDEB documentation

This directory holds the system-level documentation for the AdvanDEB monorepo:
the app (`app/`), the `advandeb_kb` library (`knowledge-builder/`), and the
MCP gateway (`mcp/`). Start with the root [`README.md`](../README.md) and
[`RUNNING.md`](../RUNNING.md).

*Index rewritten 2026-10-28. The previous version, from December 2025,
described three separate repositories; they were merged into this monorepo in
March 2026.*

## Current

These are kept true to the code. Each one says when it was last reconciled.

| Document | What it answers |
|---|---|
| [`SYSTEM-OVERVIEW.md`](SYSTEM-OVERVIEW.md) | Components, frontend routes, chat paths (KAG, EvidenceRegistry, BYOK), auth, roles and capabilities. |
| [`STORAGE-CONTRACT.md`](STORAGE-CONTRACT.md) | Which store owns which entity; how graph artifacts are built; how stale copies may be. |
| [`knowledge_graph_scheme_descriptions.md`](knowledge_graph_scheme_descriptions.md) | Arango collections and named graphs; the seven graph schemas, including `reproduction`. |
| [`ELICITATION.md`](ELICITATION.md) | Expert elicitation: tasks, tiers, calibration gate, enrolment, DOI references and retrieval recall. |
| [`ROADMAP.md`](ROADMAP.md) | Phase status and the quarter. |
| [`PLAN-2026-08-26.md`](PLAN-2026-08-26.md) | Open and closed items C1–C25, with a status table as of 2026-10-28. |

## Historical — do not plan from these

Kept for the record. Each carries a banner saying what changed.

| Document | Date | Why it is historical |
|---|---|---|
| [`REVIEW-2026-05-18.md`](REVIEW-2026-05-18.md) (+ `.pdf`) | 2026-05-18 | Superseded by the plan. It praises `ARCHITECTURE-REVISION.md`, which no longer exists. |
| [`CHATBOT-AGENT-SCHEME.md`](CHATBOT-AGENT-SCHEME.md) | 2026-04-14 | Describes chat when every turn went through `chatbot_agent`. Most turns now run in the backend's own KAG pipeline. |
| [`docs/latex/`](docs/latex/README.md) | Dec 2024 – Dec 2025 | Architecture rationale, development plan and environment, in English and Croatian. They predate the monorepo and the ArangoDB move, and treat MongoDB as the graph store and Google OAuth as the primary sign-in. |
| [`diagrams/`](diagrams/) | Dec 2025 | PlantUML set. It predates the Mongo→Arango migration and has not been re-verified. |

Elsewhere in the repo, also historical: `app/DEPLOYMENT.md`,
`app/MONITORING.md`, and `knowledge-builder/INGESTION-SETUP.md`.

## Other files here

- `environment.yml` — an early (2025) definition of the shared `advandeb`
  conda environment. It is not the source of truth; the app installs from
  `app/backend/requirements.txt` and `knowledge-builder/pyproject.toml`.
- `plantuml.jar` — the PlantUML renderer used for `diagrams/`.
