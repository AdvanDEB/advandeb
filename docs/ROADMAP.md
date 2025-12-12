# AdvandEB Cross-Repository Roadmap

## Phase 0: User Management & Authentication (NEW - 15 weeks)

**Foundation** (Weeks 1-3):
- Implement user database models and authentication system
- Google OAuth 2.0 integration
- JWT and API key authentication
- Role-based permission system
- Audit logging infrastructure

**User Management** (Weeks 4-5):
- Role request and approval workflow
- API key management for Curators and Analysts
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

**Deliverable**: Fully authenticated platform with 6 roles, unified SSO across KB and MA, Google OAuth, API keys, review workflow, and Day Zero seeding

See `USER-MANAGEMENT-PLAN.md` for detailed implementation plan.

---

## Phase 1: Stabilize advandeb-knowledge-builder

- Finish hardening CRUD and data processing paths.
- Stabilize agent framework and logging.
- Add basic test coverage and CI.
- **Integration with authentication**: All endpoints protected, audit logging active

## Phase 2: Define and Prototype advandeb-modeling-assistant

- Finalize integration contracts with `advandeb-knowledge-builder`.
- Configure MA to use shared platform authentication (same JWT tokens and user database).
- Implement a thin prototype of the modeling assistant backend and basic UI.
- Validate end-to-end flow: from knowledge ingestion to modeling recommendations.

## Phase 3: Deepen Integration and UX

- Improve search and retrieval paths tailored for modeling use cases.
- Enhance visual and interactive exploration of the knowledge used in models.
- Add collaboration and sharing around scenarios and models.
- Implement multi-user contribution tracking (Phase 2 of USER-MANAGEMENT-PLAN).

## Phase 4: Extensions and Plugins

- Support project-specific tools and agents via a plugin mechanism.
- Extend modeling support to additional modeling paradigms as needed.
- Advanced collaboration features (workspaces, teams).
- Trust and reputation system for contributors.
