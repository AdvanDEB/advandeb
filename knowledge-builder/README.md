# advandeb_kb

**advandeb_kb** is a Python package providing knowledge-base operations for the AdvanDEB platform. It is consumed as a library by the main AdvanDEB app (`pip install -e ../knowledge-builder`) — it is not a standalone service and has no UI.

The package aggregates knowledge on physiology, morphology, anatomy, and bioenergetics of organisms, and exposes services for fact storage, ingestion, semantic retrieval, and knowledge-graph construction.

## Overview

`advandeb_kb` provides the building blocks for the platform's knowledge layer:

- **Knowledge base management**: Store and organize facts, stylized facts, and knowledge graphs
- **AI-powered extraction**: Leverage locally hosted Ollama LLM models for fact extraction
- **Data processing**: Ingest PDFs, browse web content, and process raw text
- **Semantic search**: Discover relationships and connections in the knowledge base
- **Graph construction**: Build and update ArangoDB-backed knowledge graphs

All user-facing UI (chat, visualization, document library, etc.) lives in the main `app/` of the AdvanDEB monorepo; this package only exposes Python services.

## Architecture

### Components

- **Storage**: MongoDB for facts and metadata; ArangoDB for graph data; ChromaDB for vector embeddings
- **AI integration**: Ollama LLM hosting (native, in-house only)
- **Environment management**: Conda (or venv) for Python

## Features

### Core functionality

- MongoDB-based knowledge storage
- Ollama LLM hosting support (localhost/remote)
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
- **Model support**: Any Ollama-hosted local model

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
- **MongoDB**: For data storage (https://docs.mongodb.com/manual/installation/)
- **ArangoDB**: For graph storage (installed locally via OS package manager, no Docker)
- **Ollama**: For LLM services (https://ollama.ai)

Steps:

```bash
# 1. Clone the AdvanDEB monorepo
git clone <advandeb-monorepo-url>
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
ollama pull llama2
```

## Configuration

`advandeb_kb` reads configuration from environment variables (loaded via `advandeb_kb.config.settings`). The host application is responsible for setting these; defaults are sensible for a local dev install.

```bash
# MongoDB
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb

# Ollama
OLLAMA_BASE_URL=http://localhost:11434

# ChromaDB (embedded mode)
CHROMA_PERSIST_DIR=./chroma_data

# File upload (used by ingestion service)
MAX_FILE_SIZE=50000000
UPLOAD_DIR=uploads
```

### AI model configuration

Install and run Ollama locally (no external API keys required):

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service
ollama serve

# Pull required models
ollama pull llama2
ollama pull codellama
```

## Project structure

```
knowledge-builder/
├── advandeb_kb/             # Installable Python package
│   ├── __init__.py          # Public API surface
│   ├── config/              # Settings (env-driven)
│   ├── database/            # MongoDB / ArangoDB / ChromaDB clients
│   ├── models/              # Pydantic models
│   ├── services/            # KnowledgeService, IngestionService, etc.
│   └── agents/              # Multi-agent LLM workers
├── pyproject.toml
└── environment.yml
```

## Repository

This package is part of the AdvanDEB monorepo at https://github.com/AdvanDEB (placeholder).
