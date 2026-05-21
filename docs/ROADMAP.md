# AdvanDEB Cross-Repository Roadmap

## Status (as of 2026-05-18)

A consolidated snapshot of where each phase stands. The phase sections below carry
fine-grained `[STATUS: ...]` annotations where they can be judged credibly from
`docs/SYSTEM-OVERVIEW.md` and the running services; everything else is marked
`[STATUS: UNCERTAIN]`.

- **Phase 0 — Multi-Agent RAG-KG Foundation**: largely shipped. The five
  specialized agents (`retrieval_agent`, `graph_explorer_agent`,
  `synthesis_agent`, `query_planner_agent`, `curator_agent`) plus the
  `chatbot_agent` orchestrator are running inside `advandeb_kb`; the Rust MCP
  gateway is up; ArangoDB is the canonical KB store; ChromaDB powers vector
  retrieval; the ingestion pipeline is processing ~1300 papers; 1236 stylized
  facts are seeded into the `advandeb` MongoDB; the `sf_support` graph is at
  3373 nodes / 2243 edges.
- **Phase 0.5 — User Management & Authentication**: basics shipped. Google
  OAuth, JWT issuance/validation, role-based FastAPI dependencies, and the
  document/fact submission workflow are live. Reviewer status, capability
  request workflows, and full audit logs are only partially done.
- **Phase 1 / 1.5 — App Visualization & UX**: in progress. The Cosmograph WebGL
  canvas is live for graph rendering, the agent-activity panel streams live
  status, and the provenance trail panel is in place. Polish, schema-side
  filtering, and node-table interactions are still moving.
- **Outstanding work**: tracked in `docs/REVIEW-2026-05-18.md` §11 (the change
  plan). That document is the authoritative source for what remains for the
  current review cycle.

---

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

## Phase 0: Multi-Agent RAG-KG Foundation (PRIORITY - 12 weeks)  [STATUS: SHIPPED]

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

### Slice 1: Semantic RAG Foundation (Weeks 1-4)  [STATUS: SHIPPED]

**Deliverable**: Vector search eliminates basic hallucinations

- Week 1: Infrastructure (ChromaDB, ArangoDB, sentence-transformers)
- Week 2: Embedding service + document chunking
- Week 3: Vector search implementation
- Week 4: Integration with existing retrieval agent + basic testing

**Success Metric**: Retrieval MRR improves from ~0.45 (keyword) to >0.70 (vector)

### Slice 2: Multi-Agent Coordination (Weeks 5-8)  [STATUS: SHIPPED]

**Deliverable**: Multiple specialized agents verify and cross-check results

- Week 5: MCP agent server framework (Python)
- Week 6: Create 3 specialized agent MCP servers (Retrieval, Graph Explorer, Synthesis)
- Week 7: MCP Gateway routing (Rust enhancement)
- Week 8: Query Planner agent + agent coordination workflows

**Success Metric**: Multi-agent responses cite sources with full provenance, contradictions detected

### Slice 3: Graph-Augmented Retrieval (Weeks 9-11)  [STATUS: SHIPPED]

**Deliverable**: Graph structure expands context and improves relevance

- Week 9: ArangoDB graph schema + edge collections
- Week 10: Graph traversal tools + hybrid retrieval (vector + graph expansion)
- Week 11: Graph-augmented agent workflows

**Success Metric**: Graph expansion improves recall by 25%+, related facts discovered automatically

### Slice 4: Production Readiness (Week 12)  [STATUS: IN PROGRESS]

**Deliverable**: Stable, observable, debuggable multi-agent system

- Performance optimization (caching, indexing)
- Observability (agent activity logs, reasoning traces)
- Error handling and graceful degradation
- Documentation of architecture and workflows

**Success Metric**: No hallucinations in test scenarios, full citation trails, <5s response time

---

## Phase 0.5: User Management & Authentication (15 weeks)  [STATUS: IN PROGRESS]

**Foundation** (Weeks 1-3):  [STATUS: SHIPPED]
- Implement user database models with base_role + capabilities structure
- Google OAuth 2.0 integration
- JWT and API key authentication
- Capability-based permission system
- Audit logging infrastructure

**User Management** (Weeks 4-5):  [STATUS: IN PROGRESS]
- Base role request workflow (new users)
- Capability request workflow (existing curators)
- API key management with capability-based scopes
- Email notification system
- Administrator dashboard

**Frontend Integration** (Weeks 6-8):  [STATUS: IN PROGRESS]
- Login page and OAuth flow
- Auth state management (Pinia/Vuex)
- Role request form
- API key management UI
- Permission-based view rendering

**Review Workflow** (Weeks 9-10):  [STATUS: IN PROGRESS]
- Knowledge review queue (backend + frontend)
- Approve/reject/request changes functionality
- Status-based visibility filtering
- Reviewer dashboard

**Day Zero & Migration** (Weeks 11-12):  [STATUS: IN PROGRESS]
- Day Zero knowledge seeding workflow
- Batch ingestion for foundational content
- Migration of existing 1,300 PDFs
- Legacy data attribution

**Modeling Assistant Integration & Polish** (Weeks 13-15):  [STATUS: NOT STARTED]
- Configure MA backend to use shared authentication
- Implement JWT validation in MA using shared library
- Test cross-component authentication (same token works for KB and MA)
- End-to-end testing across all roles and components
- Security audit
- Documentation and deployment

**Deliverable**: Fully authenticated platform with 3 base roles + 3 capabilities, unified SSO across KB and MA, Google OAuth, API keys, review workflow, and Day Zero seeding

See `USER-MANAGEMENT-PLAN.md` for detailed implementation plan.

---

## Phase 1: Stabilize advandeb-knowledge-builder  [STATUS: IN PROGRESS]

- Finish hardening CRUD and data processing paths.
- Stabilize agent framework and logging.
- Add basic test coverage and CI.
- **Integration with authentication**: All endpoints protected, audit logging active

## Phase 1.5: App Visualization & UX (Parallel - 4 weeks)  [STATUS: IN PROGRESS]

**Goal**: User-facing graph visualization and enhanced chat interface

See `APP-VISUALIZATION-PLAN.md` for details.

- Interactive knowledge graph visualization (Cosmograph WebGL canvas)  [STATUS: SHIPPED]
- Agent activity viewer (real-time multi-agent status)  [STATUS: SHIPPED]
- Provenance display (citation trails, reasoning traces)  [STATUS: SHIPPED]
- Enhanced chat interface with source cards  [STATUS: IN PROGRESS]

**Deliverable**: Rich UI showing how agents find and verify information

---

## Phase 1.75: Bootstrap advandeb-MCP Gateway (Integrated with Phase 0)  [STATUS: SHIPPED]

**Scope**: MCP Gateway enhancement integrated with Multi-Agent RAG-KG system

- WebSocket MCP protocol implementation
- Agent-to-agent routing and coordination
- Tool registry with dynamic loading
- Integration with Python MCP agent servers (from knowledge-builder)

**Status**: Integrated with Phase 0 (Multi-Agent RAG-KG Foundation)

See `MCP-MULTI-AGENT-COORDINATION-PLAN.md` for detailed implementation plan.

---

## Phase 2: Define and Prototype advandeb-modeling-assistant  [STATUS: NOT STARTED]

- Finalize integration contracts with `advandeb-knowledge-builder`.
- Configure MA to use shared platform authentication (same JWT tokens and user database).
- Implement a thin prototype of the modeling assistant backend and basic UI.
- Validate end-to-end flow: from knowledge ingestion to modeling recommendations.
- **MCP Integration**: Use MCP server for LLM-based agent features in MA.

## Phase 3: Deepen Integration and UX  [STATUS: NOT STARTED]

- Improve search and retrieval paths tailored for modeling use cases.
- Enhance visual and interactive exploration of the knowledge used in models.
- Add collaboration and sharing around scenarios and models.
- Implement multi-user contribution tracking (Phase 2 of USER-MANAGEMENT-PLAN).
- **MCP Expansion**: Enhanced MCP tools for complex knowledge graph queries and analysis.

## Phase 4: Extensions and Plugins  [STATUS: NOT STARTED]

- Support project-specific tools and agents via a plugin mechanism.
- Extend modeling support to additional modeling paradigms as needed.
- Advanced collaboration features (workspaces, teams).
- Trust and reputation system for contributors.
- **MCP Extensions**: Custom tool development for specialized workflows.

---

## Performance targets

The previous `app/README.md` published a set of performance numbers (initial
load, bundle size, Lighthouse score) as "achieved." Those numbers were
aspirational and have not been re-measured against the current build. Track
them here as targets until they can be re-measured against `frontend/dist/`
served by the FastAPI backend on :8400.

- **Frontend initial load**: target <3s
- **Bundle size**: target <1MB gzipped
- **Build time**: target <10s
- **Lighthouse score**: target >90
- **Backend health check**: target <100ms

Performance is yet to be re-measured against the current build.
