# AdvanDEB User Management & Authentication - Documentation Update Summary

**Date:** December 12, 2025  
**Status:** Complete - Ready for Implementation  
**Last Updated:** December 12, 2025 (Simplified to 3-tier role + capability system)

---

## ⚠️ Important Architectural Evolution

**Initial Design (v1.0)**: Originally designed authentication separately for Knowledge Builder and Modeling Assistant, with a "Service Account" role for MA to call KB.

**Corrected Design (v2.0)**: Authentication unified across the entire AdvanDEB platform with 6 distinct roles:
- ✅ Single Sign-On (SSO) - Users authenticate once for entire platform
- ✅ Shared user database (MongoDB) - Same `users` collection for KB and MA
- ✅ Same JWT tokens - Valid for both Knowledge Builder and Modeling Assistant APIs
- ✅ No "Service Account" role - Removed as unnecessary with unified authentication
- ✅ 6 user roles - Administrator, Curator, Reviewer, Agent Operator, Analyst, Explorator

**Simplified Design (v3.0)**: Role system simplified to capability-based model:
- ✅ **3 base roles** - Administrator, Knowledge Curator, Knowledge Explorator
- ✅ **3 optional capabilities** for Curators - Agent Access, Analytics Access, Reviewer Status
- ✅ **Capability request workflow** - Curators can request additional permissions as needed
- ✅ **Eliminates role redundancy** - Agent Operator, Data Analyst, and Reviewer are now capabilities, not separate roles
- ✅ **Hierarchical permissions** - Curators gain specialized access through approved capabilities

All documentation has been updated to reflect the simplified capability-based authentication model.

---

## Version 3.0 Changes (December 12, 2025)

**Major Simplification**: Role system consolidated from 6 roles to 3 base roles + 3 capabilities

### What Changed:

**Before (v2.0)**: 6 distinct roles
- Administrator
- Knowledge Curator
- Knowledge Reviewer
- Agent Operator
- Data Analyst
- Knowledge Explorator

**After (v3.0)**: 3 base roles + optional capabilities
- **Administrator** (unchanged)
- **Knowledge Curator** (base content creator)
  - Can request: Agent Access, Analytics Access, Reviewer Status
- **Knowledge Explorator** (unchanged, read-only)

### Rationale:

The v2.0 design had significant overlap between Knowledge Curator, Agent Operator, and Data Analyst roles. In practice, these are the same type of user (domain expert creating content) who may need different specialized capabilities at different times. The v3.0 design:

- ✅ Eliminates role redundancy
- ✅ Simplifies permission model
- ✅ Makes capabilities more flexible (curators can request as needed)
- ✅ Reduces administrative overhead
- ✅ Maintains all functionality from v2.0

### Database Impact:

```python
# OLD (v2.0)
{
  "roles": ["knowledge_curator", "agent_operator", "data_analyst"]
}

# NEW (v3.0)
{
  "base_role": "knowledge_curator",
  "capabilities": ["agent_access", "analytics_access"]
}
```

---

## Overview

This document summarizes all updates made to the AdvanDEB architecture documentation to incorporate the comprehensive user management, authentication, and authorization system.

---

## Files Created

### 1. **USER-MANAGEMENT-PLAN.md** (NEW - 24KB)
**Location:** `/advandeb-architecture/USER-MANAGEMENT-PLAN.md`

**Contents:**
- Complete **platform-wide** user management architecture (not KB-specific)
- 6 role definitions with hierarchical structure (Service Account role removed)
- Detailed permissions matrix for both Knowledge Builder and Modeling Assistant
- Google OAuth 2.0 authentication flow (platform-wide SSO)
- API key authentication system (valid across entire platform)
- Database schema for all user-related entities (shared across components)
- Role request workflow specification
- Knowledge review/validation workflow
- Day Zero seeding workflow
- 15-week implementation roadmap (7 phases)
- Component integration architecture (KB ↔ MA without service accounts)
- Security considerations and best practices
- Frontend integration specifications
- Migration strategy for existing data

This is the **primary reference document** for implementing the unified platform authentication system.

### 2. **diagrams/authentication-flow.puml** (NEW - 2.6KB)
**Location:** `/advandeb-architecture/diagrams/authentication-flow.puml`

**Contents:**
- Google OAuth 2.0 flow (user sign-in)
- JWT authentication flow (access token + refresh token)
- API key authentication flow (generation + usage)
- Token validation and refresh logic
- Rate limiting checks

**Sequence diagram** showing all authentication mechanisms.

### 3. **diagrams/role-request-workflow.puml** (NEW - 3.6KB)
**Location:** `/advandeb-architecture/diagrams/role-request-workflow.puml`

**Contents:**
- New user registration process
- Role request form submission
- Administrator review and approval workflow
- Email notifications
- User receiving approved roles
- Complete end-to-end flow

**Sequence diagram** for the role request and approval process.

### 4. **diagrams/review-workflow.puml** (NEW - 5.6KB)
**Location:** `/advandeb-architecture/diagrams/review-workflow.puml`

**Contents:**
- Knowledge Curator creates fact/document
- Content enters "pending_review" status
- Knowledge Reviewer examines and decides
- Approve/Reject/Request Changes actions
- Status transitions
- Visibility to different roles
- Administrator override capabilities

**Sequence diagram** for the consensus validation workflow.

---

## Files Updated

### 5. **diagrams/system-context.puml** (UPDATED - v2.0)
**Location:** `/advandeb-architecture/diagrams/system-context.puml`

**Changes:**
- Added 6 user roles as actors (Service Account removed):
  - Administrator (System Authority)
  - Knowledge Curator (Expert Authority)
  - Knowledge Reviewer (Quality Control)
  - Agent Operator (AI Specialist)
  - Data Analyst (Research User)
  - Knowledge Explorator (Knowledge User)
- **Platform Authentication** shown at platform level (not component-specific)
- Added Google OAuth 2.0 integration (platform-wide SSO)
- Updated MongoDB to show shared user/audit database
- Clarified that same users access both KB and MA with same authentication

**System-level view** showing unified platform authentication across components.

### 6. **diagrams/knowledge-builder-container.puml** (UPDATED)
**Location:** `/advandeb-architecture/diagrams/knowledge-builder-container.puml`

**Changes:**
- Added **Auth Layer** package:
  - auth.py router
  - AuthService
  - GoogleOAuthClient
  - JWTManager
  - APIKeyValidator
  - PermissionChecker
- Added **Middleware** package:
  - AuthMiddleware
  - RateLimiter
  - AuditLogger
- Added **New Routers**:
  - users.py
  - role_requests.py
  - api_keys.py
  - reviews.py
- Added **New Services**:
  - UserService
  - RoleService
  - ReviewService
  - AuditService
- Added **New Models**:
  - User Models
  - Auth Models
- Updated **Database Collections**:
  - users, role_requests, api_keys, audit_logs, contributions
- Added **Auth Views** in Frontend:
  - Login View
  - Profile View
  - Role Request View
  - Admin Dashboard
  - Review Queue
  - API Key Management
- Added **State Management**:
  - Auth Store
  - API interceptors
- Added **Redis** for rate limiting and session caching
- Added **Google OAuth 2.0** external service

**Container-level architecture** showing all authentication and authorization components.

### 7. **diagrams/knowledge-builder-data-model.puml** (UPDATED)
**Location:** `/advandeb-architecture/diagrams/knowledge-builder-data-model.puml`

**Changes:**
- Added **User Management Entities**:
  - User (with google_id, email, roles, status)
  - RoleRequest (pending approval workflow)
  - APIKey (with scopes, expiration, rate limits)
  - AuditLog (complete action history)
- Updated **Knowledge Entities** with new fields:
  - Document: `uploaded_by`, `is_day_zero`, `batch_id`
  - Fact: `created_by`, `status`, `review_status`, `is_day_zero`
  - StylizedFact: `created_by`, `status`, `review_status`, `is_day_zero`
  - KnowledgeGraph: `created_by`, `status`, `collaborators`, `is_day_zero`
- Updated **Ingestion Entities**:
  - IngestionBatch: `created_by`, `is_day_zero`
- Updated **Agent Entities**:
  - AgentSession: `user_id`, `session_type`
- Added **Phase 2 Entity**:
  - Contribution (multi-user contribution tracking)
- Added **Relationships**:
  - User → RoleRequest (requests)
  - User → APIKey (owns)
  - User → AuditLog (performs)
  - User → all knowledge entities (creates/owns)
  - User → User (reviews role requests)

**Complete data model** with all user management and knowledge entities.

### 8. **SYSTEM-OVERVIEW.md** (UPDATED - v2.0)
**Location:** `/advandeb-architecture/SYSTEM-OVERVIEW.md`

**Changes:**
- Updated Knowledge Builder description to emphasize it's the **primary authentication provider**
- Updated Modeling Assistant description to clarify **shared authentication** (no service account)
- Updated **External Services** section:
  - MongoDB emphasized as **shared database** for entire platform
  - Google OAuth 2.0 marked as **platform-wide** authentication
  - Redis for platform-wide rate limiting
- Updated **User Roles** section:
  - Listed 6 roles (Service Account removed)
  - Clarified roles apply to **entire platform** (not just KB)
- Completely rewrote **Integration Concept**:
  - Explained unified platform architecture
  - Single Sign-On (SSO) across components
  - No service-to-service authentication needed
  - Cross-component data access patterns
- Expanded **Data Model** section:
  - User Management Entities marked as **platform-wide**
  - API keys valid across all components
  - Audit logs track actions across KB and MA
- Updated **Authentication & Authorization** section:
  - Emphasized platform-wide unified authentication
  - KB hosts primary auth endpoints
  - MA validates tokens against shared database
  - Same JWT tokens work for both components

**High-level system overview** now correctly reflects unified platform authentication.

### 9. **ROADMAP.md** (UPDATED)
**Location:** `/advandeb-architecture/ROADMAP.md`

**Changes:**
- Added **Phase 0: User Management & Authentication (NEW - 15 weeks)**:
  - Foundation (Weeks 1-3): Backend auth system (platform-wide)
  - User Management (Weeks 4-5): Role requests and API keys
  - Frontend Integration (Weeks 6-8): UI and auth flows
  - Review Workflow (Weeks 9-10): Knowledge validation
  - Day Zero & Migration (Weeks 11-12): Seeding and data migration
  - MA Integration & Polish (Weeks 13-15): Unified authentication testing
- Updated **Phase 1**: Added note about authentication integration
- Updated **Phase 2**: Updated MA integration to use shared authentication (not service accounts)
- Updated **Phase 3**: Added multi-user contribution tracking
- Updated **Phase 4**: Added trust/reputation system

**Development roadmap** now starts with platform-wide user management implementation.

### 10. **diagrams/modeling-assistant-container.puml** (UPDATED - v2.0)
**Location:** `/advandeb-architecture/diagrams/modeling-assistant-container.puml`

**Changes:**
- Added **Platform Authentication** reference (not component-specific auth)
- Shows JWT tokens passed from MA backend to KB backend
- Notes explain shared authentication model
- MA validates tokens using same JWT secret and user database as KB
- No service account authentication shown

**Container-level architecture** for Modeling Assistant with unified platform authentication.

---

## Diagram Summary

### ✅ Updated Diagrams (PNG regenerated - v2.0)

The following diagrams have been updated to reflect **platform-wide unified authentication**:
- `system-context.puml` / `system-context.png` - Platform-level authentication, 6 roles (not 7)
- `modeling-assistant-container.puml` / `modeling-assistant-container.png` - Shared auth model, no service accounts

### Diagrams Updated (PNG outdated - need regeneration)

The following PlantUML files were updated but PNG files need regeneration:
- `knowledge-builder-container.png` - Has auth components but predates unified auth model
- `knowledge-builder-data-model.png` - Has user entities but predates unified auth model

### New Diagrams (PNG generated)

- `authentication-flow.png` - OAuth + JWT + API key authentication flows
- `role-request-workflow.png` - Role request and approval process
- `review-workflow.png` - Knowledge review and validation workflow

### Unchanged Diagrams (still valid)

- `document-ingestion-sequence.png` - Document ingestion flow (no changes needed)

---

## Key Concepts Documented

### 1. Simplified Role + Capability System (v3.0)
- **3 base roles** - Administrator, Knowledge Curator, Knowledge Explorator
- **3 optional capabilities** for Curators - Agent Access, Analytics Access, Reviewer Status
- **Capability-based permissions** - Curators request specialized access as needed
- **Eliminates redundancy** - Previous 6-role system consolidated into flexible capability model
- **Platform-wide**: Same roles and capabilities apply to Knowledge Builder and Modeling Assistant
- **Hierarchical access** - Capabilities add permissions on top of base role

### 2. Authentication Methods
- **Google OAuth 2.0**: Platform-wide SSO for all components (not component-specific)
- **API Keys**: Programmatic access valid across entire platform (KB and MA)
- **JWT Tokens**: Access (1 hour) + Refresh (30 days) - work for both KB and MA APIs

### 3. Authorization Model
- **Role-Based Access Control (RBAC)**: Permissions by role
- **Resource-Level Permissions**: Ownership checks
- **Status-Based Visibility**: Knowledge visibility by review status

### 4. Workflows
- **Base Role Request**: New users request base role → Admin approves → Role granted
- **Capability Request**: Existing Curators request capabilities → Admin approves → Capabilities added
- **Knowledge Review**: Curator creates → Curator with Reviewer Status approves → Published
- **Day Zero Seeding**: Admin creates foundational knowledge batch

### 5. Database Schema (v3.0 Updates)
- **Platform-wide shared database**: Single MongoDB database for entire platform
- **4 new collections**: users (with base_role + capabilities), capability_requests, api_keys, audit_logs (shared across KB and MA)
- **User model changes**: `roles: List[str]` replaced with `base_role: str` + `capabilities: List[str]`
- **Request model changes**: role_requests renamed to capability_requests with support for both base role and capability requests
- **Updated existing collections**: All knowledge entities have `created_by`, `status`, `review_status`
- **Complete audit trail**: All actions logged with user attribution and component tracking

### 6. Implementation Plan
- **15-week roadmap** across 7 phases
- **Incremental milestones**: Each phase has clear deliverable
- **Backward compatible**: Existing data migrated with proper attribution

---

## Next Steps

### 1. Review and Approval
- [x] Design complete
- [ ] Review by team/stakeholders
- [ ] Approve implementation plan

### 2. Google OAuth Setup
- [ ] Create Google Cloud Project
- [ ] Configure OAuth 2.0 Client (Client ID + Secret)
- [ ] Set authorized redirect URIs
- [ ] Add credentials to .env file

### 3. Environment Variables
Add to `advandeb-knowledge-builder/backend/.env`:
```bash
# Google OAuth Configuration
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback

# JWT Configuration
JWT_SECRET_KEY=generate_256_bit_random_key_here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# First Administrator (auto-promote on first login)
ADMIN_EMAILS=admin@example.com,admin2@example.com

# Email Configuration (Phase 2)
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USERNAME=...
# SMTP_PASSWORD=...
```

### 4. Begin Implementation
Start Phase 1 (Week 1):
- Create user database models
- Implement authentication endpoints
- Set up Google OAuth integration

Refer to `USER-MANAGEMENT-PLAN.md` Section 8 for detailed week-by-week tasks.

### 5. Regenerate Diagram PNGs (Optional)
Once PlantUML is available, regenerate all PNG diagrams for documentation.

---

## Documentation Files Reference

All documentation is located in `/home/adeb/dev/advandeb/advandeb-architecture/`:

| File | Size | Purpose |
|------|------|---------|
| `USER-MANAGEMENT-PLAN.md` | 24KB | Complete user management specification |
| `SYSTEM-OVERVIEW.md` | 4.2KB | High-level system overview (updated) |
| `ROADMAP.md` | 2.6KB | Development roadmap (updated with Phase 0) |
| `KNOWLEDGE-BUILDER-PLAN.md` | 775B | KB development plan |
| `MODELING-ASSISTANT-PLAN.md` | 936B | MA development plan |
| `diagrams/system-context.puml` | 1.8KB | System context with 7 roles |
| `diagrams/knowledge-builder-container.puml` | 2.5KB | KB container with auth modules |
| `diagrams/knowledge-builder-data-model.puml` | 4.8KB | Complete data model with users |
| `diagrams/authentication-flow.puml` | 2.6KB | OAuth + JWT + API key flows |
| `diagrams/role-request-workflow.puml` | 3.6KB | Role request and approval |
| `diagrams/review-workflow.puml` | 5.6KB | Knowledge review and validation |

**Total documentation:** ~53KB of comprehensive planning and architecture.

---

## Summary

The AdvanDEB architecture documentation has been **comprehensively updated** to include a complete **platform-wide** user management and authentication system. The design includes:

✅ **6 hierarchical roles** with multi-role support (Service Account removed)  
✅ **Platform-wide Google OAuth 2.0** authentication (Single Sign-On)  
✅ **API key** authentication valid across entire platform  
✅ **Shared user database** (MongoDB) for all components  
✅ **Same JWT tokens** work for Knowledge Builder and Modeling Assistant  
✅ **Role-based permission** system with component-specific permissions  
✅ **Knowledge review workflow** with consensus validation  
✅ **Day Zero seeding** for foundational knowledge  
✅ **Unified component integration** (no service-to-service auth needed)  
✅ **Complete audit logging** across all platform components  
✅ **15-week implementation roadmap** with clear milestones  
✅ **6 PlantUML diagrams** (5 updated/created for unified auth, 1 unchanged)  
✅ **Updated system documentation** (USER-MANAGEMENT-PLAN.md, SYSTEM-OVERVIEW.md, ROADMAP.md)  

The system is **ready for implementation** following the phased approach outlined in `USER-MANAGEMENT-PLAN.md`.

---

**Document Author:** OpenCode AI Assistant  
**Review Status:** Awaiting Stakeholder Review  
**Implementation Status:** Design Complete - Ready to Build
