# AdvanDEB Development Environment

This document describes the **shared development environment** for all AdvanDEB services.

- Single Conda environment: `advandeb`
- Repositories:
  - `advandeb-knowledge-builder`
  - `advandeb-modeling-assistant`
  - `advandeb-architecture`

## 1. Conda Environment

### 1.1 Create the Environment

From the `advandeb-architecture` repository root:

```bash
conda env create -f environment.yml
```

If the environment already exists and you have updated `environment.yml`:

```bash
conda env update -f environment.yml --prune
```

### 1.2 Activate the Environment

```bash
conda activate advandeb
```

This is the **only** Conda environment used for all AdvanDEB services.

## 2. Core Services

### 2.1 MongoDB

- Install and run MongoDB locally (e.g., `mongod` on default port 27017).
- Default connection string:

```bash
MONGODB_URL=mongodb://localhost:27017
```

### 2.2 Ollama (Local LLM Host)

- Install Ollama following its official instructions.
- Ensure it runs on the default port `11434`.
- Default base URL:

```bash
OLLAMA_BASE_URL=http://localhost:11434
```

## 3. Running advandeb-knowledge-builder

### 3.1 Backend

From `advandeb-knowledge-builder/backend`:

```bash
conda activate advandeb
cp .env.example .env  # edit as needed
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Key environment variables in `backend/.env`:

```bash
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb
OLLAMA_BASE_URL=http://localhost:11434
```

### 3.2 Frontend

From `advandeb-knowledge-builder/frontend`:

```bash
npm install
npm run dev
```

Frontend dev server: `http://localhost:3000` (Vite default).

## 4. Running advandeb-modeling-assistant (Planned)

The modeling assistant will also use the shared `advandeb` environment.

Expected pattern (subject to change as the repo is implemented):

```bash
conda activate advandeb
# from advandeb-modeling-assistant/backend (future):
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

It will connect to:

- `advandeb-knowledge-builder` HTTP APIs for knowledge and agents
- MongoDB for its own collections (e.g., scenarios, models, runs)

## 5. Diagram Tooling

Architecture diagrams live in `advandeb-architecture/diagrams` and are written in PlantUML.

To render diagrams:

```bash
conda activate advandeb
cd advandeb-architecture/diagrams
plantuml *.puml
```

This will generate image files (`.png` or `.svg`) alongside the `.puml` sources.

## 6. Repository Overview

- `advandeb-knowledge-builder` – Knowledge ingestion, processing, and exploration.
- `advandeb-modeling-assistant` – Modeling-oriented retrieval and reasoning (planned).
- `advandeb-architecture` – System-level docs, diagrams, and shared environment definition.
