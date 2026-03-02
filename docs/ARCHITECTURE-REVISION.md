# Architecture Revision - December 17, 2024

## Overview

This document captures a significant architectural revision to clarify the roles and relationships between platform components.

## Revised Architecture Model

### Component Roles

**advandeb-modeling-assistant** - **Main Platform GUI**
- The primary and single entry point for all platform users
- Hosts the complete user interface: web frontend (Vue.js) + backend API (FastAPI)
- Provides all user-facing features:
  - Chat interface with AI agents
  - Knowledge exploration and browsing
  - Interactive document ingestion UI
  - Fact extraction and review workflows
  - Knowledge graph visualization
  - Modeling scenario creation and management
- **Hosts all authentication**: Google OAuth integration, user management, JWT tokens
- **Role-based access control**: Determines which features each user can access
- Imports `advandeb-knowledge-builder` as a toolkit/library for knowledge operations
- Calls `advandeb-MCP` for LLM-powered agent features

**advandeb-knowledge-builder** - **Toolkit/Package**
- Not a standalone application - a Python package/library
- Provides robust, reusable modules for knowledge operations:
  - Fact extraction algorithms
  - Stylized facts generation
  - Document ingestion pipelines
  - Knowledge graph building and querying
  - Review workflow logic
  - Agent-based processing with Ollama
- Separate repository because of the complexity and robustness of these operations
- No user interface - pure backend logic
- Can be used independently for batch processing or standalone operations
- Imported by `advandeb-modeling-assistant` backend
- Operations exposed as MCP tools by `advandeb-MCP` server

**advandeb-MCP** - **MCP Tool Server**
- Model Context Protocol server exposing platform tools to LLM agents
- Handles tools for BOTH knowledge building AND modeling operations:
  - Fact extraction tools
  - Stylized fact generation tools
  - Document ingestion tools
  - Knowledge graph query tools
  - Modeling scenario tools
  - Analysis and reasoning tools
- Internal background service (no authentication)
- Called by modeling assistant for agent-powered features
- Wraps `advandeb-knowledge-builder` operations as MCP tools
- Direct integration with Ollama for LLM inference
- Rust-based for performance

**advandeb-architecture** - **Documentation Repository**
- Not a code repository - documentation and planning only
- Contains:
  - System architecture and design documents
  - Cross-repository roadmaps and milestones
  - Development log and planning notes
  - Integration contracts and API specifications
  - Decision records and architectural diagrams

## Key Architectural Decisions

### 1. Single GUI Entry Point

**Decision**: Modeling Assistant is the single user-facing application.

**Rationale**:
- Simplifies user experience - one interface for all features
- Eliminates confusion about which application to use
- Easier authentication and session management
- Role-based features shown/hidden based on user permissions
- Single deployment for the web interface

**Implementation**:
- Users log in once to Modeling Assistant
- Interface adapts based on user role:
  - Administrators see everything
  - Knowledge Curators see knowledge building + modeling features
  - Explorers see read-only views
- Features powered by Knowledge Builder toolkit behind the scenes

### 2. Knowledge Builder as Toolkit

**Decision**: Knowledge Builder is a Python package, not a standalone application.

**Rationale**:
- Knowledge operations are complex and need to be robust
- Separating into a toolkit allows:
  - Independent testing and versioning
  - Reuse across different contexts
  - Batch processing without full web stack
  - Clear separation of concerns
- Avoids code duplication in Modeling Assistant
- Can be imported and used by other tools if needed

**Implementation**:
- Develop as a Python package with proper module structure
- Published to internal package repository or installed via path
- Modeling Assistant imports KB and calls its functions
- Clean API boundaries between GUI and toolkit

### 3. MCP for Agent Features

**Decision**: MCP server exposes platform tools for LLM agent workflows.

**Rationale**:
- Standardized way to expose tools to LLM agents
- Separates agent orchestration from web application logic
- Rust implementation for performance (agent tools can be compute-intensive)
- Can be scaled independently from web tier
- Provides unified interface to Ollama

**Implementation**:
- MCP server wraps KB toolkit operations as MCP tools
- Modeling Assistant calls MCP for chat and agent features
- No authentication between MA and MCP (internal trusted calls)
- MCP handles LLM inference and tool execution

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                     PLATFORM USERS                      │
│              (authenticate via Google OAuth)             │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────▼─────────────┐
        │  advandeb-modeling-      │
        │  assistant (Main GUI)    │ ◄── Single Entry Point
        │  ├─ Vue.js Frontend      │
        │  ├─ FastAPI Backend      │
        │  └─ Google OAuth         │
        └───┬────────────────┬─────┘
            │                │
            │                │
   ┌────────▼───────┐   ┌───▼──────────────┐
   │  advandeb-     │   │  advandeb-MCP    │
   │  knowledge-    │   │  (Rust/Axum)     │
   │  builder       │   │                  │
   │  (Toolkit)     │   │  Tool Server     │
   │                │◄──┤  for LLM Agents  │
   │  Python Package│   │                  │
   └───┬────────────┘   └───┬──────────────┘
       │                    │
       │                    │
   ┌───▼────────────────────▼──────┐
   │         MongoDB               │
   │  (Knowledge + Users + Audit)  │
   └───────────────────────────────┘
   
   ┌───────────────────────────────┐
   │         Ollama (LLMs)         │
   │  Used by KB agents and MCP    │
   └───────────────────────────────┘
```

## Data Flow Examples

### Example 1: User Uploads Document

1. User logs into **Modeling Assistant** GUI
2. User navigates to "Document Ingestion" (if they have curator role)
3. User uploads PDF file via web interface
4. MA backend receives file, calls **Knowledge Builder** package function:
   ```python
   from advandeb_knowledge_builder import ingest_document
   result = await ingest_document(file_path, user_id)
   ```
5. KB package processes document, extracts text, stores in MongoDB
6. MA backend returns success response to frontend
7. Frontend shows ingestion status and extracted facts

### Example 2: User Chats with AI Agent

1. User opens chat interface in **Modeling Assistant**
2. User types: "What do we know about species X?"
3. MA backend sends request to **MCP Server**:
   ```json
   {
     "method": "tools/call",
     "params": {
       "name": "search_knowledge",
       "arguments": {"query": "species X"}
     }
   }
   ```
4. MCP server invokes `search_knowledge` tool which uses **KB** functions
5. MCP calls Ollama to generate natural language response
6. MCP returns formatted response to MA
7. MA displays chat response to user

### Example 3: User Explores Knowledge Graph

1. User clicks "Knowledge Graph" in **Modeling Assistant**
2. MA backend calls **Knowledge Builder** graph query functions:
   ```python
   from advandeb_knowledge_builder import get_knowledge_graph
   graph_data = await get_knowledge_graph(filters={...})
   ```
3. KB queries MongoDB for nodes and edges
4. MA backend transforms data for visualization
5. Frontend renders interactive graph

## Repository Structure

### advandeb-modeling-assistant
```
advandeb-modeling-assistant/
├── frontend/              # Vue.js web UI
│   ├── src/
│   │   ├── components/   # UI components
│   │   ├── views/        # Main views (chat, knowledge, modeling)
│   │   ├── router/       # Vue router config
│   │   └── store/        # State management
│   └── package.json
├── backend/               # FastAPI backend
│   ├── app/
│   │   ├── api/          # API routes
│   │   ├── auth/         # Authentication (Google OAuth)
│   │   ├── models/       # Pydantic models
│   │   └── services/     # Business logic
│   ├── requirements.txt
│   └── main.py
└── README.md
```

### advandeb-knowledge-builder
```
advandeb-knowledge-builder/
├── advandeb_kb/           # Main package
│   ├── __init__.py
│   ├── ingestion/        # Document ingestion
│   ├── extraction/       # Fact extraction
│   ├── stylization/      # Stylized facts
│   ├── graph/            # Knowledge graph
│   ├── agents/           # Agent workflows
│   ├── review/           # Review logic
│   └── database/         # MongoDB interface
├── tests/                # Unit tests
├── setup.py              # Package setup
├── requirements.txt
└── README.md
```

### advandeb-MCP
```
advandeb-MCP/
├── src/
│   ├── main.rs           # Entry point
│   ├── lib.rs            # App wiring
│   ├── config.rs         # Configuration
│   ├── ollama.rs         # Ollama client
│   ├── tools/            # MCP tool implementations
│   │   ├── mod.rs
│   │   ├── knowledge.rs  # KB tools
│   │   └── modeling.rs   # MA tools
│   └── mcp/              # MCP protocol
│       ├── mod.rs
│       └── server.rs
├── Cargo.toml
└── README.md
```

## Migration from Old Architecture

### Changes from Previous Model

**Old Model**:
- Knowledge Builder: Standalone FastAPI + Vue application
- Modeling Assistant: Separate FastAPI + Vue application
- Both had their own frontends and backends
- Shared authentication library between them

**New Model**:
- Modeling Assistant: Main GUI application (single frontend + backend)
- Knowledge Builder: Toolkit/package (no UI, just logic)
- MCP: Tool server for agents (exposes KB and MA tools)

### Benefits of New Model

1. **Simpler for Users**
   - One application to learn and use
   - Single login, consistent interface
   - Features shown/hidden based on role

2. **Cleaner Architecture**
   - Clear separation: GUI vs toolkit vs agent services
   - Knowledge Builder becomes more reusable
   - Easier to understand component responsibilities

3. **Easier Development**
   - Single frontend codebase to maintain
   - KB toolkit can be versioned and tested independently
   - MCP can be developed in parallel without affecting GUI

4. **Better Deployment**
   - One web application to deploy (Modeling Assistant)
   - KB package installed as dependency
   - MCP as separate internal service

## Implementation Roadmap

### Phase 1: Modeling Assistant Foundation (Weeks 1-4)
- Set up Modeling Assistant repository structure
- Implement authentication (Google OAuth)
- Create basic frontend (Vue.js) with routing
- Set up FastAPI backend with user management
- Role-based access control

### Phase 2: Knowledge Builder as Package (Weeks 5-8)
- Restructure Knowledge Builder as Python package
- Create clean module boundaries
- Extract all UI code (will be rebuilt in MA)
- Publish package for MA to import
- Document package API

### Phase 3: Integrate KB into MA (Weeks 9-12)
- Install KB package in MA backend
- Build knowledge UIs in MA frontend
- Implement document ingestion UI
- Add fact extraction and review workflows
- Knowledge graph visualization

### Phase 4: MCP Server Tools (Weeks 13-16)
- MCP protocol implementation (WebSocket)
- Wrap KB operations as MCP tools
- Integrate with Ollama
- Test tool execution

### Phase 5: Chat Interface (Weeks 17-20)
- Build chat UI in MA frontend
- Connect to MCP server
- Implement agent workflows
- Testing and refinement

### Phase 6: Modeling Features (Weeks 21-24)
- Scenario creation UI
- Model building interface
- Integration with knowledge base
- Testing and deployment

## Open Questions

1. **Knowledge Builder Package Distribution**: Internal package repo or Git submodule?
2. **KB API Stability**: How to version KB package API as it evolves?
3. **MCP Tool Discovery**: Static or dynamic tool registration?
4. **Shared Components**: UI component library between frontend modules?
5. **Testing Strategy**: How to test MA ↔ KB ↔ MCP integration end-to-end?

## Success Criteria

The architecture revision is successful when:

- [ ] Users access all features through single Modeling Assistant interface
- [ ] Knowledge Builder functions as importable Python package
- [ ] MCP server exposes tools and handles agent workflows
- [ ] Role-based access control works correctly
- [ ] Clean separation between GUI, toolkit, and agent layers
- [ ] Documentation reflects actual implementation

## Conclusion

This architectural revision provides a clearer, more maintainable structure for the AdvanDEB platform. By positioning Modeling Assistant as the main GUI, Knowledge Builder as a toolkit, and MCP as an agent service, we achieve better separation of concerns and a simpler user experience.

The revised architecture:
- ✅ Simplifies user experience (one application)
- ✅ Clarifies component responsibilities
- ✅ Enables independent development and testing
- ✅ Provides clean integration points
- ✅ Supports future extensibility

All documentation in this repository will be updated to reflect this new architectural model.
