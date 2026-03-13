# AdvanDEB Cross-Repository Roadmap

## Critical Issue: Hallucinations & Wrong Document References

**Current Problem**: The system hallucinates facts and references wrong documents, undermining trust and usability for research work.

**Root Cause**: 
- Keyword-only search (regex) misses semantically similar content
- No vector embeddings or semantic retrieval
- Weak provenance tracking
- Single-agent system lacks verification steps
- No graph-based context expansion

**Solution**: Multi-Agent RAG-KG Hybrid System (detailed in component plans below)

---

## Phase 0: Multi-Agent RAG-KG Foundation (PRIORITY - 12 weeks)

**Goal**: Eliminate hallucinations by implementing semantic retrieval, multi-agent verification, and graph-augmented context with full provenance tracking.

### Architecture Overview

```
┌─────────────────────────────────────────────────┐
│         MULTI-AGENT COORDINATION                │
│    (Agents communicate via MCP protocol)        │
│                                                  │
│  Query Planner → Retrieval → Graph Explorer     │
│                      ↓              ↓            │
│                  Synthesis ← Curator             │
└─────────────────────┬───────────────────────────┘
                      │
        ┌─────────────┴──────────────┐
        │                            │
┌───────▼────────┐         ┌─────────▼────────┐
│  HYBRID RAG    │         │  KNOWLEDGE GRAPH │
│                │         │                  │
│ • ChromaDB     │◄────────┤  • ArangoDB      │
│   (vectors)    │ refs    │    (unified DB)  │
│ • Sentence     │         │  • Graph edges   │
│   Transformers │         │  • Documents     │
│ • Reranking    │         │  • Facts & Taxa  │
└────────────────┘         └──────────────────┘
```

### Implementation Strategy

**Approach**: Vertical slices with 2-person team (full-time)
- Build complete workflows end-to-end
- Start with highest-value features
- Build fresh in ArangoDB (no MongoDB migration initially)
- Focus on production code, minimal tests during development

### Slice 1: Semantic RAG Foundation (Weeks 1-4)

**Deliverable**: Vector search eliminates basic hallucinations

- Week 1: Infrastructure (ChromaDB, ArangoDB, sentence-transformers)
- Week 2: Embedding service + document chunking
- Week 3: Vector search implementation
- Week 4: Integration with existing retrieval agent + basic testing

**Success Metric**: Retrieval MRR improves from ~0.45 (keyword) to >0.70 (vector)

### Slice 2: Multi-Agent Coordination (Weeks 5-8)

**Deliverable**: Multiple specialized agents verify and cross-check results

- Week 5: MCP agent server framework (Python)
- Week 6: Create 3 specialized agent MCP servers (Retrieval, Graph Explorer, Synthesis)
- Week 7: MCP Gateway routing (Rust enhancement)
- Week 8: Query Planner agent + agent coordination workflows

**Success Metric**: Multi-agent responses cite sources with full provenance, contradictions detected

### Slice 3: Graph-Augmented Retrieval (Weeks 9-11)

**Deliverable**: Graph structure expands context and improves relevance

- Week 9: ArangoDB graph schema + edge collections
- Week 10: Graph traversal tools + hybrid retrieval (vector + graph expansion)
- Week 11: Graph-augmented agent workflows

**Success Metric**: Graph expansion improves recall by 25%+, related facts discovered automatically

### Slice 4: Production Readiness (Week 12)

**Deliverable**: Stable, observable, debuggable multi-agent system

- Performance optimization (caching, indexing)
- Observability (agent activity logs, reasoning traces)
- Error handling and graceful degradation
- Documentation of architecture and workflows

**Success Metric**: No hallucinations in test scenarios, full citation trails, <5s response time

---

## Phase 0.5: User Management & Authentication (15 weeks)

**Foundation** (Weeks 1-3):
- Implement user database models with base_role + capabilities structure
- Google OAuth 2.0 integration
- JWT and API key authentication
- Capability-based permission system
- Audit logging infrastructure

**User Management** (Weeks 4-5):
- Base role request workflow (new users)
- Capability request workflow (existing curators)
- API key management with capability-based scopes
- Email notification system
- Administrator dashboard

**Frontend Integration** (Weeks 6-8):
- Login page and OAuth flow
- Auth state management (Pinia/Vuex)
- Role request form
- API key management UI
- Permission-based view rendering

**Review Workflow** (Weeks 9-10):
- Knowledge review queue (backend + frontend)
- Approve/reject/request changes functionality
- Status-based visibility filtering
- Reviewer dashboard

**Day Zero & Migration** (Weeks 11-12):
- Day Zero knowledge seeding workflow
- Batch ingestion for foundational content
- Migration of existing 1,300 PDFs
- Legacy data attribution

**Modeling Assistant Integration & Polish** (Weeks 13-15):
- Configure MA backend to use shared authentication
- Implement JWT validation in MA using shared library
- Test cross-component authentication (same token works for KB and MA)
- End-to-end testing across all roles and components
- Security audit
- Documentation and deployment

**Deliverable**: Fully authenticated platform with 3 base roles + 3 capabilities, unified SSO across KB and MA, Google OAuth, API keys, review workflow, and Day Zero seeding

See `USER-MANAGEMENT-PLAN.md` for detailed implementation plan.

---

## Phase 1: Stabilize advandeb-knowledge-builder

- Finish hardening CRUD and data processing paths.
- Stabilize agent framework and logging.
- Add basic test coverage and CI.
- **Integration with authentication**: All endpoints protected, audit logging active

## Phase 1.5: App Visualization & UX (Parallel - 4 weeks)

**Goal**: User-facing graph visualization and enhanced chat interface

See `APP-VISUALIZATION-PLAN.md` for details.

- Interactive knowledge graph visualization (Cytoscape.js)
- Agent activity viewer (real-time multi-agent status)
- Provenance display (citation trails, reasoning traces)
- Enhanced chat interface with source cards

**Deliverable**: Rich UI showing how agents find and verify information

---

## Phase 1.75: Bootstrap advandeb-MCP Gateway (Integrated with Phase 0)

**Scope**: MCP Gateway enhancement integrated with Multi-Agent RAG-KG system

- WebSocket MCP protocol implementation
- Agent-to-agent routing and coordination
- Tool registry with dynamic loading
- Integration with Python MCP agent servers (from knowledge-builder)

**Status**: Integrated with Phase 0 (Multi-Agent RAG-KG Foundation)

See `MCP-MULTI-AGENT-COORDINATION-PLAN.md` for detailed implementation plan.

---

## Phase 2: Define and Prototype advandeb-modeling-assistant

- Finalize integration contracts with `advandeb-knowledge-builder`.
- Configure MA to use shared platform authentication (same JWT tokens and user database).
- Implement a thin prototype of the modeling assistant backend and basic UI.
- Validate end-to-end flow: from knowledge ingestion to modeling recommendations.
- **MCP Integration**: Use MCP server for LLM-based agent features in MA.

## Phase 3: Deepen Integration and UX

- Improve search and retrieval paths tailored for modeling use cases.
- Enhance visual and interactive exploration of the knowledge used in models.
- Add collaboration and sharing around scenarios and models.
- Implement multi-user contribution tracking (Phase 2 of USER-MANAGEMENT-PLAN).
- **MCP Expansion**: Enhanced MCP tools for complex knowledge graph queries and analysis.

## Phase 4: Extensions and Plugins

- Support project-specific tools and agents via a plugin mechanism.
- Extend modeling support to additional modeling paradigms as needed.
- Advanced collaboration features (workspaces, teams).
- Trust and reputation system for contributors.
- **MCP Extensions**: Custom tool development for specialized workflows.
