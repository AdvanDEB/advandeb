# AdvanDEB System Overview

## Components

- **advandeb-shared-utils** (NEW)
  - Python package providing shared authentication and authorization utilities.
  - Eliminates code duplication between KB and MA backends.
  - Contains JWT validation, API key validation, permission checking, user models, and audit logging.
  - Both KB and MA import this package for consistent authentication behavior.
  - See `SHARED-UTILS-PLAN.md` for complete specification.

- **advandeb-knowledge-builder**
  - FastAPI + Vue-based system for building a biological knowledge base from literature, web, and text.
  - Stores facts, stylized facts, and knowledge graphs in MongoDB.
  - Provides agent-based workflows using local LLMs (Ollama).
  - **Primary Authentication Provider**: Hosts Google OAuth endpoints and user management for entire platform.
  - **Review Workflow**: Consensus-based validation for knowledge contributions.
  - Imports `advandeb-shared-utils` for authentication logic.

- **advandeb-modeling-assistant**
  - Planned component focused on knowledge retrieval and reasoning for individual-based modeling (IBM).
  - Shares authentication infrastructure with Knowledge Builder (same JWT tokens, same user database).
  - Users authenticated once can access both KB and MA with same credentials.
  - Imports `advandeb-shared-utils` for authentication logic.

## External Services

- **MongoDB** for persistent storage - **Shared database** for entire platform (knowledge + users + audit logs across KB and MA).
- **Ollama** for local LLM hosting.
- **Google OAuth 2.0** for platform-wide user authentication.
- **Redis** for rate limiting and session caching.

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
- Both Knowledge Builder and Modeling Assistant are components of a single **AdvanDEB Platform**
- They share the same MongoDB database for user management and authentication
- Users authenticate once (Single Sign-On) and access both components with the same JWT token
- No separate "service account" authentication - MA operates on behalf of the authenticated user

**Cross-Component Data Access**:
- Modeling Assistant can query Knowledge Builder data in two ways:
  1. **Direct database access**: MA backend queries KB collections directly (e.g., `facts`, `knowledge_graphs`)
  2. **Internal API calls**: MA calls KB API endpoints using user's JWT token for complex operations

**Example Workflow**:
1. User logs in via Google OAuth (receives JWT token)
2. User browses Knowledge Builder to explore biological facts
3. User navigates to Modeling Assistant to create a scenario
4. MA uses same JWT token to verify user has `knowledge_curator` role
5. MA queries KB database to include relevant facts in the model
6. Both KB and MA actions logged to shared audit trail

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

