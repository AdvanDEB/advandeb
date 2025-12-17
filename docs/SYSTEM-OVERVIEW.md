# AdvanDEB System Overview

# AdvanDEB System Overview

## Components

- **advandeb-modeling-assistant** (Main Platform GUI)
  - Primary user interface for the entire AdvanDEB platform.
  - FastAPI backend + Vue.js frontend for chat, knowledge exploration, and modeling.
  - **Hosts all user authentication**: Google OAuth endpoints and user management.
  - Role-based access control determines which features users can access.
  - Integrates knowledge building tools from `advandeb-knowledge-builder` package.
  - Provides interactive GUI for: document ingestion, fact extraction, knowledge graph exploration, chat interface, modeling scenarios.
  - Users with appropriate roles can access both knowledge building and modeling features.
  - **The single entry point** for all platform users.
  - Imports `advandeb-knowledge-builder` as a toolkit/library.
  - May use `advandeb-shared-utils` for authentication logic.

- **advandeb-knowledge-builder** (Toolkit/Package)
  - Robust toolkit and package for knowledge operations.
  - Provides reusable modules for: fact extraction, stylized facts creation, document ingestion, knowledge graph building.
  - Separate repository due to complexity and robustness of knowledge processing routines.
  - Imported and used by `advandeb-modeling-assistant` backend.
  - Can be used independently for batch processing or standalone knowledge operations.
  - No user interface - pure backend logic and utilities.
  - MongoDB integration for knowledge storage (facts, documents, graphs).
  - Agent-based workflows using local LLMs (Ollama).
  - Review workflow logic for knowledge validation.

- **advandeb-MCP** (MCP Server - Rust)
  - Model Context Protocol server providing tool access for LLM agents.
  - Exposes platform tools via MCP: fact extraction, stylized fact generation, document ingestion, knowledge queries, modeling operations.
  - Handles both knowledge building tools AND modeling assistant tools.
  - Internal background service (no authentication required).
  - Used by modeling assistant for agent-powered features and chat interface.
  - Rust-based for high performance and resource efficiency.
  - Wraps `advandeb-knowledge-builder` operations and platform capabilities as MCP tools.
  - Direct access to Ollama for LLM inference and MongoDB for knowledge access.

- **advandeb-shared-utils** (Optional - Future)
  - Python package providing shared authentication and authorization utilities.
  - Can be used by modeling assistant for JWT validation, API key validation, permission checking.
  - User models and audit logging utilities.
  - See `SHARED-UTILS-PLAN.md` for complete specification.

## External Services

- **MongoDB** for persistent storage - knowledge base (facts, stylized facts, documents, graphs), user management, audit logs.
- **Ollama** for local LLM hosting (used by MCP server and knowledge builder agents).
- **Google OAuth 2.0** for user authentication (hosted by modeling assistant).
- **Redis** (optional) for rate limiting and session caching.

## User Roles

The **AdvanDEB Platform** uses a **simplified 3-tier role system** with optional specialized capabilities. These roles apply across all platform components (Knowledge Builder and Modeling Assistant):

**Core Roles:**
1. **Administrator** - System authority, user management, platform configuration across all components
2. **Knowledge Curator** - Create/edit knowledge in KB, create scenarios/models in MA (base content creator role)
3. **Knowledge Explorator** - Browse published knowledge (KB) and models (MA), read-only access

**Specialized Capabilities** (granted to Knowledge Curators upon request/approval):
- **Agent Access** - Permission to operate AI agents and custom tools in both KB and MA
- **Analytics Access** - Permission to run advanced queries, bulk exports, API access to platform data
- **Reviewer Status** - Permission to review and approve knowledge contributions from other curators

**Role Hierarchy:**
```
Administrator (all permissions)
├── Knowledge Curator (base content creator)
│   ├── + Agent Access (optional)
│   ├── + Analytics Access (optional)
│   └── + Reviewer Status (optional)
└── Knowledge Explorator (read-only)
```

Knowledge Curators can hold multiple specialized capabilities simultaneously (e.g., Curator + Agent Access + Analytics Access).

See `USER-MANAGEMENT-PLAN.md` for complete role definitions and component-specific permissions.

## Integration Concept
 
**Unified Platform Architecture**:
- **advandeb-modeling-assistant** is the main platform GUI and single entry point for all users
- Users authenticate via Google OAuth through the modeling assistant
- Role-based access control determines which features are available (knowledge building, modeling, chat)
- Knowledge building features provided by importing `advandeb-knowledge-builder` toolkit
- MCP server provides LLM agent capabilities for chat and intelligent features

**Component Relationships**:
- **Modeling Assistant** (main GUI) imports **Knowledge Builder** (toolkit) as a Python package/library
- **Modeling Assistant** calls **MCP Server** for agent-powered features (chat, intelligent extraction)
- **MCP Server** wraps **Knowledge Builder** operations as MCP tools for LLM agents
- All components share the same **MongoDB** database for knowledge and users
- **Modeling Assistant** hosts authentication; other components are backend services

**Internal MCP Service**:
- The **advandeb-MCP** server provides a standardized Model Context Protocol interface
- Internal background service used by modeling assistant for LLM-based operations
- No authentication layer - operates within trusted platform boundary
- MA backend calls MCP server for agent workflows and tool execution
- Provides unified interface to Ollama and platform capabilities
- Exposes knowledge building tools (fact extraction, document ingestion) as MCP tools

**Example User Workflow**:
1. User logs in to **Modeling Assistant** GUI via Google OAuth (receives JWT token)
2. Based on user role, interface shows available features (knowledge building, modeling, chat)
3. User uploads a document → MA calls **Knowledge Builder** package for ingestion
4. User wants AI-assisted fact extraction → MA calls **MCP Server** which uses KB tools + Ollama
5. User explores knowledge graph → MA uses **Knowledge Builder** query functions
6. User chats with AI agent → MA sends to **MCP Server** for LLM inference
7. All actions logged by MA with user attribution

## Knowledge Builder Data Model (Conceptual)

At a high level, the Knowledge Builder organises information into the following conceptual collections:

**Knowledge Entities**:
- **Documents**: uploaded or ingested sources (e.g., PDFs, web pages) with metadata and uploader attribution.
- **Facts**: extracted statements linked back to documents, with creator, status (pending/published), and review information.
- **Stylized Facts**: higher-level summaries supported by sets of facts, with creator and review status.
- **Graph Nodes and Edges**: entities and relationships forming a knowledge graph.
- **Agent Sessions and Messages**: interaction traces between users, agents, and tools.

**User Management Entities** (Platform-Wide):
- **Users**: Google OAuth profiles with assigned roles, status, and metadata (shared across KB and MA).
- **Role Requests**: User requests for role assignments, pending administrator approval.
- **API Keys**: Authentication keys for programmatic access (Curators and Analysts) valid for entire platform.
- **Audit Logs**: Complete history of all user actions across all components (KB and MA).

**Additional Collections**:
- **Ingestion Batches**: Bulk document processing jobs with creator attribution.
- **Contributions** (Phase 2): Multi-user contribution tracking for knowledge items.

A dedicated PlantUML class diagram (`knowledge-builder-data-model.puml`) captures these entities and relationships for more detailed review.

## Authentication & Authorization

**Platform-Wide Unified Authentication**:
- Single authentication system shared across Knowledge Builder and Modeling Assistant
- Users authenticate once and access all platform components with the same credentials
- Knowledge Builder hosts the primary authentication endpoints (Google OAuth integration)
- Modeling Assistant validates JWT tokens against the same shared user database

**Authentication Methods**:
- **Google OAuth 2.0**: Primary method for web UI users (KB and MA frontends)
- **API Keys**: For programmatic access - valid across entire platform
- **JWT Tokens**: Access tokens (1 hour) + refresh tokens (30 days) - work for both KB and MA APIs

**Authorization Model**:
- **Role-Based Access Control (RBAC)**: Permissions determined by user roles
- **Multi-Role Support**: Users can have multiple roles simultaneously (union of permissions)
- **Resource-Level Permissions**: Ownership checks for editing/deleting own content
- **Status-Based Visibility**: Knowledge visibility based on review status (pending/published/rejected)

**Review Workflow**:
- Knowledge Curators submit content → status: "pending_review"
- Knowledge Reviewers approve/reject/request changes
- Approved content → status: "published" (visible to all)
- All decisions logged in audit trail

See `USER-MANAGEMENT-PLAN.md` for complete authentication architecture and workflows.

