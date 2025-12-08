# AdvandEB System Overview

## Components

- **advandeb-knowledge-builder**
  - FastAPI + Vue-based system for building a biological knowledge base from literature, web, and text.
  - Stores facts, stylized facts, and knowledge graphs in MongoDB.
  - Provides agent-based workflows using local LLMs (Ollama).

- **advandeb-modeling-assistant**
  - Planned component focused on knowledge retrieval and reasoning for individual-based modeling (IBM).
  - Will consume knowledge from `advandeb-knowledge-builder` via HTTP APIs and/or shared database.

## External Services

- MongoDB for persistent storage.
- Ollama for local LLM hosting.

## Integration Concept

- `advandeb-knowledge-builder` exposes knowledge and agent APIs.
- `advandeb-modeling-assistant` queries these APIs to: 
  - Retrieve relevant knowledge for modeling scenarios.
  - Use agents to synthesize and explain model structures and assumptions.
