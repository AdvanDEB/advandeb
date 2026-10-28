# advandeb_kb

**advandeb_kb** is a Python package providing knowledge-base operations for the AdvanDEB platform. The main AdvanDEB app consumes it as a library (`pip install -e ../../knowledge-builder`, run from `app/backend/`). It is not a standalone service and has no UI.

*Reconciled with the code 2026-10-28.*

The package aggregates knowledge on physiology, morphology, anatomy, and bioenergetics of organisms, and exposes services for fact storage, ingestion, semantic retrieval, and knowledge-graph construction.

## Overview

`advandeb_kb` provides the building blocks for the platform's knowledge layer:

- **Knowledge base management**: Store and organize facts, stylized facts, and knowledge graphs
- **AI-powered extraction**: fact extraction with locally hosted Ollama models
- **LLM providers**: one provider interface (`services/llm_providers/`) over Ollama, Anthropic, OpenAI, Gemini, GitHub Models and NVIDIA. The app uses it for its default and BYOK chat.
- **Evidence registry**: `EvidenceRegistry` freezes retrieved evidence into stable citation markers (`[n]`, `[G]`, `[SF]`, `[D]`) before an answer is generated
- **Data processing**: Ingest PDFs, browse web content, and process raw text
- **Semantic search**: Discover relationships and connections in the knowledge base
- **Graph construction**: Build and update ArangoDB-backed knowledge graphs

All user-facing UI (chat, visualization, document library, etc.) lives in the main `app/` of the AdvanDEB monorepo; this package only exposes Python services.

## Architecture

### Components

- **Storage**:
  - **ArangoDB** — canonical store for documents, chunks, facts, stylized facts,
    taxa, and the graph edges between them
  - **ChromaDB** — canonical store for chunk embeddings
  - **MongoDB** — application state, ingestion workflow state, and the
    *materialized* graphs the host app renders

  Full ownership rules: `../docs/STORAGE-CONTRACT.md`.
- **AI integration**: Ollama for local models — agents, extraction, reranking,
  follow-up suggestions. External providers through `llm_providers`: the host
  app's default chat runs on NVIDIA's API, and users may bring their own keys.
- **Agents**: six websocket agents launched by the host app's stack service —
  `retrieval_agent` (8081), `graph_explorer_agent` (8082), `synthesis_agent`
  (8083), `query_planner_agent` (8084), `curator_agent` (8085),
  `chatbot_agent` (8086)
- **Environment management**: Conda (or venv) for Python

## Features

### Core functionality

- ArangoDB-backed knowledge storage, with hybrid vector + full-text retrieval
- Ollama support (localhost/remote), plus the external providers above
- Web browsing capabilities
- PDF document ingestion
- Stylized fact extraction
- Network analysis and community detection (programmatic; rendering is done by the host app)

### Data processing

- **PDF ingestion**: Extract facts from scientific documents
- **Web browsing**: Collect content from web sources
- **Text processing**: Extract entities and facts from raw text
- **Entity recognition**: Identify biological terms and concepts

### Knowledge organization

- **Facts**: Individual pieces of information with confidence scores
- **Stylized facts**: Enhanced facts with importance ratings and relationships
- **Knowledge graphs**: Networks of concepts and relations stored in ArangoDB
- **Search and discovery**: Programmatic APIs for related-information lookup

### AI integration

- **Fact extraction**: Automated extraction using LLM models
- **Content stylization**: Convert raw facts to structured knowledge
- **Model support**: any Ollama-hosted model for local work. Defaults:
  `deepseek-r1:latest` for answers and extraction; `gemma3:latest` for graph
  and follow-up prompts. The reproduction pipeline has been run with
  `gemma2:2b`.

## Library usage

The package is imported by the main app. Canonical imports:

```python
from advandeb_kb import KnowledgeService, IngestionService
```

Other services available from the package (see `advandeb_kb/__init__.py` for the authoritative list):

```python
from advandeb_kb.services import (
    KnowledgeService,
    IngestionService,
)
```

A typical embedded use, from the main app's backend:

```python
from advandeb_kb import KnowledgeService

knowledge = KnowledgeService()
facts = await knowledge.search_facts(query="...")
```

The main app wires these services into its FastAPI routes; `advandeb_kb` itself does not register HTTP routes or start a server.

## Development setup

Prerequisites:

- **Conda/Miniforge**: For Python environment management (https://github.com/conda-forge/miniforge)
- **MongoDB**: for application and transitional storage (https://www.mongodb.com/docs/manual/installation/)
- **ArangoDB**: For graph storage (installed locally via OS package manager, no Docker)
- **Ollama**: For LLM services (https://ollama.ai)

Steps:

```bash
# 1. Clone the AdvanDEB monorepo
git clone https://github.com/AdvanDEB/advandeb.git
cd advandeb/knowledge-builder

# 2. Activate the shared conda environment
conda activate advandeb

# 3. Install the package in editable mode
pip install -e .
```

To use it from the main app's backend:

```bash
cd ../app/backend
pip install -e ../../knowledge-builder
```

### Supporting services

```bash
# MongoDB (system service)
sudo systemctl start mongod

# Ollama
ollama serve
ollama pull deepseek-r1:latest
ollama pull gemma3:latest
```

## Configuration

`advandeb_kb` reads configuration from environment variables (loaded via `advandeb_kb.config.settings`). The host application is responsible for setting these; defaults are sensible for a local dev install.

```bash
# MongoDB — note DATABASE_NAME defaults to the *transitional* KB database
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb
CHAT_STORE_DB_NAME=advandeb

# ArangoDB — canonical knowledge store
ARANGO_URL=http://localhost:8529
ARANGO_DB_NAME=advandeb_kb
ARANGO_USERNAME=root
ARANGO_PASSWORD=...

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=deepseek-r1:latest

# ChromaDB (embedded mode) and embeddings
CHROMA_PERSIST_DIR=<repo>/data/chromadb   # default is hard-coded to the production checkout's path
CHROMA_COLLECTION=advandeb_chunks
EMBEDDING_MODEL=all-MiniLM-L6-v2

# File upload (used by ingestion service)
MAX_FILE_SIZE=50000000
UPLOAD_DIR=uploads
```

The `CHAT_*` variables (models, context sizes, `CHAT_MODE`, reranking) are
listed in `app/backend/.env.example` and defined in `config/settings.py`.

The app and this package each have their own settings object. Reconciling the
two is an open item in `../docs/STORAGE-CONTRACT.md` §7.

### AI model configuration

Local work needs only Ollama. External providers need keys, which the host
app supplies: an operator default key, or a user's own.

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
ollama serve

# Pull the default models
ollama pull deepseek-r1:latest
ollama pull gemma3:latest
```

## Project structure

```
knowledge-builder/
├── advandeb_kb/             # Installable Python package
│   ├── __init__.py          # Public API surface
│   ├── config/              # Settings (env-driven)
│   ├── database/            # ArangoDB client (the Mongo client was removed in the migration)
│   ├── models/              # Pydantic models, incl. BUILTIN_SCHEMAS (graph.py)
│   ├── services/            # Knowledge, ingestion, retrieval, graph queries/artifacts,
│   │                        #   evidence registry, llm_providers/, …
│   └── agents/              # The six websocket agents + ReAct engine
├── scripts/                 # Batch jobs: imports, backfills, reproduction pipeline, start_agents.py
├── tests/                   # pytest — currently red; see ../docs/PLAN-2026-08-26.md C1
├── pyproject.toml
└── environment.yml
```

## Repository

This package is part of the AdvanDEB monorepo at https://github.com/AdvanDEB/advandeb.
No licence has been granted; see the root `README.md`.
