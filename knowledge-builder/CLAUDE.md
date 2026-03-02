# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in `knowledge-builder/`.

## Role in the Platform

`knowledge-builder` is a **pure Python library** (`advandeb_kb`) with no UI. All UI lives in `app/`. The `dev-server/` subdirectory is a standalone FastAPI+Vue prototype for development and testing — it is not part of the deployable system.

When adding new features, implement them as importable classes/functions in `advandeb_kb/services/` — not as new API endpoints or frontend views.

## Install as Library

```bash
cd knowledge-builder
pip install -e .
# or with conda:
conda env create -f environment.yml
conda activate advandeb-knowledge-builder-backend
pip install -e .
```

## Dev Server (standalone prototyping only)

**Prerequisites**: MongoDB on `:27017`, Ollama on `:11434` (`ollama serve`), Redis on `:6379` (batch ingestion only).

**Backend:**
```bash
cd knowledge-builder/dev-server
cp .env.example .env                     # configure before first run
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd knowledge-builder/dev-server/frontend
npm install
npm run dev     # http://localhost:3000
npm run build   # always run after changes to validate
```

**Validate backend changes**: `python3 -m py_compile <file.py>`

## Environment Variables (`dev-server/.env`)

```
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb
OLLAMA_BASE_URL=http://localhost:11434
API_HOST=0.0.0.0
API_PORT=8000
MAX_FILE_SIZE=50000000
UPLOAD_DIR=uploads
```

## Code Structure

```
knowledge-builder/
├── advandeb_kb/             # Installable Python package
│   ├── __init__.py          # Public API exports
│   ├── config/settings.py   # Settings (env vars)
│   ├── database/mongodb.py  # Motor async MongoDB client
│   ├── models/              # Pydantic models: knowledge, ingestion, agent_models
│   └── services/            # Business logic (library surface)
│       ├── knowledge_service.py
│       ├── ingestion_service.py
│       ├── agent_service.py
│       ├── agent_framework.py
│       ├── agent_tools.py
│       ├── data_processing_service.py
│       ├── local_model_provider.py
│       └── visualization_service.py
├── dev-server/              # Standalone FastAPI+Vue prototype
│   ├── main.py              # FastAPI app entry point
│   ├── routers/             # HTTP route handlers (imports from advandeb_kb)
│   ├── tasks/               # Celery tasks for batch ingestion
│   ├── celery_app.py        # Celery worker config
│   └── frontend/            # Vue 3 dev UI
├── tests/
├── pyproject.toml           # Package definition (pip install -e .)
└── environment.yml          # Conda environment
```

## Dev Server API Modules

| Prefix | Router file | Purpose |
|--------|-------------|---------|
| `/api/knowledge` | `routers/knowledge.py` | Facts, stylized facts, knowledge graphs, search |
| `/api/data` | `routers/data_processing.py` | PDF upload, URL browsing, text processing |
| `/api/agents` | `routers/agents.py` | Ollama chat, fact extraction, stylization |
| `/api/viz` | `routers/visualization.py` | Graph visualization, network analysis |
| `/api/ingestion` | `routers/ingestion.py` | Batch PDF ingestion (Celery jobs) |

Interactive API docs: `http://localhost:8000/docs`

## Batch Ingestion (Celery)

The ingestion pipeline processes PDFs asynchronously via Celery + Redis. Redis must be running. See `INGESTION-SETUP.md` for setup details.

## pip SSL Troubleshooting

If `pip install` fails with SSL errors:
```bash
pip install --timeout 60 --retries 5 \
  --trusted-host pypi.org --trusted-host files.pythonhosted.org \
  -e .
```
Fall back to conda (`environment.yml`) as the primary source.
