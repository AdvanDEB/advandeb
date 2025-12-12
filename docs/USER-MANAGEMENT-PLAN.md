# AdvandEB Platform: User Management & Authentication Plan

**Version:** 2.0  
**Date:** December 11, 2025  
**Status:** Design Complete - Ready for Implementation

---

## Executive Summary

This document defines the comprehensive user management, authentication, and authorization architecture for the **entire AdvandEB Platform** (Knowledge Builder + Modeling Assistant). The system implements a **unified 6-role hierarchy** with **multi-role assignment**, **Google OAuth authentication**, **API key access**, and **consensus-based validation** workflows.

### Key Features

- ✅ **Platform-wide unified authentication** - Single Sign-On (SSO) across all components
- ✅ **Shared authentication library** - `advandeb-shared-utils` Python package eliminates code duplication
- ✅ 6 user roles with hierarchical inheritance (Service Account role removed)
- ✅ Multi-role support (users can have multiple roles simultaneously)
- ✅ Google OAuth 2.0 authentication
- ✅ API key authentication for programmatic access
- ✅ Role-based permission system across Knowledge Builder and Modeling Assistant
- ✅ Knowledge review/approval workflow
- ✅ Communal knowledge with contribution tracking
- ✅ Audit logging for all actions across platform
- ✅ Day Zero knowledge seeding workflow
- ✅ **Shared user database** - MongoDB stores users, roles, and audit logs for entire platform

---

## 1. Role Architecture

### 1.1 Role Hierarchy (Model C: Core + Specialized Multi-Role)

**Core Hierarchy:**
```
Administrator (System Authority)
    ↓
Knowledge Curator (Expert Authority)
    ↓
Knowledge Explorator (Knowledge User)
```

**Specialized Roles** (require base role + specialization):

- **Knowledge Reviewer**: Knowledge Curator + Review/approval permissions
- **Agent Operator**: Knowledge Curator + Agent management permissions
- **Data Analyst**: Knowledge Explorator + Advanced analytics + API key access

### 1.2 Role Definitions

#### Administrator
- **Purpose**: System-level authority and configuration
- **Key Permissions**:
  - Full system access
  - User management (create, edit, delete, approve roles)
  - System configuration
  - View all audit logs
  - Day Zero knowledge seeding
  - Override any review decision
  - Access all knowledge regardless of status

#### Knowledge Curator
- **Purpose**: Domain experts who create and manage knowledge
- **Key Permissions**:
  - Upload documents (single and batch)
  - Create facts and stylized facts
  - Build knowledge graphs
  - Run agent sessions
  - Edit own contributions
  - Generate API keys (with scoped permissions)
  - View own audit logs

#### Knowledge Reviewer
- **Purpose**: Quality control and validation
- **Key Permissions**:
  - All Knowledge Curator permissions
  - View pending review queue
  - Approve/reject/request changes on knowledge
  - View review audit logs
  - Edit knowledge for quality improvements

#### Agent Operator
- **Purpose**: AI/ML specialists managing the agent framework
- **Key Permissions**:
  - All Knowledge Curator permissions
  - Modify agent configurations
  - Create custom tools
  - View all agent sessions
  - View agent performance metrics
  - Test and debug agent behaviors

#### Data Analyst
- **Purpose**: Advanced research and analysis users
- **Key Permissions**:
  - Full read access to all published knowledge
  - Advanced search and filtering
  - Bulk export (CSV, JSON)
  - Network analysis tools
  - Generate API keys for programmatic access
  - View own API usage statistics

#### Knowledge Explorator
- **Purpose**: General knowledge consumers
- **Key Permissions**:
  - Browse and search published knowledge
  - View knowledge graphs
  - Run read-only agent queries
  - Create personal annotations (private)
  - Export limited data (small datasets)
  - Save search queries

### 1.3 Multi-Role Assignment

Users can have **multiple roles simultaneously**. Permissions are the **union** of all assigned roles.

**Examples**:
- User with `[knowledge_curator, agent_operator]`: Can create knowledge AND manage agents
- User with `[knowledge_curator, knowledge_reviewer]`: Can create AND approve knowledge
- User with `[knowledge_explorator, data_analyst]`: Read access + analytics tools

---

## 2. Authentication Architecture

**Platform-Wide Authentication**: The AdvandEB platform uses a unified authentication system shared across all components (Knowledge Builder, Modeling Assistant, and future modules). Users authenticate once and receive JWT tokens valid for the entire platform.

### 2.1 Google OAuth 2.0 Flow

**Provider**: Google OAuth 2.0  
**Scopes**: `email`, `profile`  
**Client**: Frontend redirects to Google consent screen

**Flow**:
```
1. User clicks "Sign in with Google" (from KB or MA frontend)
2. Frontend redirects to Google OAuth
3. User approves, Google returns authorization code
4. Backend exchanges code for user profile (email, name, picture)
5. Backend creates/loads user from shared platform database
6. Backend generates JWT tokens (access + refresh) valid across all components
7. Frontend stores tokens, user authenticated for entire platform
8. Same JWT token works for both Knowledge Builder and Modeling Assistant APIs
```

**New User Behavior**:
- Status: `pending_approval`
- Roles: `[]` (empty)
- User must request roles to access features

### 2.2 JWT Token Structure

**Access Token** (short-lived, 1 hour):
```json
{
  "sub": "user_id",
  "email": "user@example.com",
  "name": "User Name",
  "roles": ["knowledge_curator", "agent_operator"],
  "iat": 1702300000,
  "exp": 1702303600,
  "jti": "token_id"
}
```

**Refresh Token** (long-lived, 30 days):
- Stored in database with user_id
- One-time use (rotated on refresh)
- Revocable

### 2.3 API Key Authentication

**Format**: `advk_` prefix + 32-byte random (256-bit)  
**Storage**: SHA-256 hash in database  
**Display**: Plain text shown ONCE at creation  
**Platform-Wide**: API keys work across all AdvandEB components (KB and MA)

**Scopes** (for Knowledge Curators):
- `read:facts`, `write:facts`
- `read:documents`, `write:documents`
- `read:graphs`, `write:graphs`
- `run:agents`
- `read:models`, `write:models` (Modeling Assistant)
- `run:scenarios` (Modeling Assistant)

**Scopes** (for Data Analysts):
- `read:facts`, `read:stylized_facts`
- `read:documents`, `read:graphs`
- `export:bulk`, `analytics:advanced`
- `read:models`, `read:scenarios` (Modeling Assistant)
- `export:results` (Modeling Assistant)

**Expiration**:
- Curator keys: 30 days
- Analyst keys: 90 days

**Rate Limits**:
- Curator: 200 requests/minute
- Analyst: 500 requests/minute

---

## 3. Authorization & Permissions

### 3.1 Permission System

**Middleware**: FastAPI dependencies check authentication and authorization

**Hierarchy**:
1. **Authentication**: Validate JWT or API key
2. **Role Check**: Verify user has required role
3. **Resource Check**: Verify ownership or special permissions
4. **Rate Limit**: Check request limits
5. **Audit Log**: Record action

**Example Dependency**:
```python
async def require_curator(user: User = Depends(get_current_user)) -> User:
    if not user.has_any_role(["administrator", "knowledge_curator", "agent_operator"]):
        raise HTTPException(403, "Curator role required")
    return user
```

### 3.2 Resource-Level Permissions

**Ownership Rules**:
- Users can edit/delete **own pending** knowledge items
- Administrators can edit/delete **any** knowledge
- Reviewers can edit knowledge **during review**

**Status-Based Access**:
- **Pending Review**: Visible to creator, reviewers, admins
- **Published**: Visible to all authenticated users
- **Rejected**: Visible to creator and admins only
- **Draft**: Visible to creator only (future)

---

## 4. Workflows

### 4.1 Role Request Workflow

**User Perspective**:
```
1. User signs in with Google → Status: "pending_approval", Roles: []
2. Dashboard shows: "Request roles to get started"
3. User fills role request form:
   - Select roles (Curator, Explorator, Analyst)
   - Affiliation
   - Research area
   - Justification
   - References (optional)
4. User submits → Status: "Pending admin review"
5. Admin approves → User receives email
6. User logs in → Full access based on granted roles
```

**Administrator Perspective**:
```
1. Admin sees "5 pending role requests"
2. Admin reviews request details
3. Admin decides:
   - Approve all requested roles
   - Approve subset of roles
   - Reject with reason
4. User notified via email
5. Audit log records decision
```

**Diagram**: See `diagrams/role-request-workflow.puml`

### 4.2 Knowledge Review Workflow (Phase 1: Single Reviewer)

**Curator Creates Knowledge**:
```
1. Curator uploads document or creates fact
2. Resource saved with:
   - status: "pending_review"
   - created_by: curator_user_id
3. Knowledge NOT visible to Explorators
4. Reviewers notified
```

**Reviewer Approves**:
```
1. Reviewer sees pending queue
2. Reviewer examines fact/document
3. Reviewer decides:
   - Approve → status: "published" (visible to all)
   - Reject → status: "rejected" (curator notified)
   - Request Changes → status: "changes_requested"
4. Audit log records decision
5. Creator notified
```

**Diagram**: See `diagrams/review-workflow.puml`

### 4.3 Day Zero Seeding Workflow

**Purpose**: Initialize knowledge base with curated, authoritative foundational knowledge

**Process**:
```
1. Administrator creates "Day Zero" batch
2. Batch characteristics:
   - is_day_zero: true
   - created_by: administrator_id
   - Auto-approved (status: "published")
3. Administrator selects sources:
   - Curated PDFs (e.g., textbooks, reference materials)
   - Authoritative databases
   - Expert-written content
4. Batch processing extracts facts
5. All facts marked:
   - is_day_zero: true
   - status: "published"
   - Special "Foundational" badge in UI
6. Day Zero knowledge is:
   - Immutable by non-admins
   - Highlighted in search
   - Used as reference for validation
```

**Use Cases**:
- Import textbook content (core biological principles)
- Load reference databases (species taxonomy)
- Seed domain ontologies
- Establish authoritative baseline

---

## 5. Database Schema

**Platform-Wide Database**: The AdvandEB platform uses a **single shared MongoDB database** for user management, authentication, and audit logs. Both Knowledge Builder and Modeling Assistant components query the same `users` collection for authentication and authorization.

**Database Name**: `advandeb` (shared)

**Authentication Collections** (shared across platform):
- `users` - Platform users with roles
- `role_requests` - Role approval workflow
- `api_keys` - API keys valid across all components
- `audit_logs` - Audit logs for all platform actions

**Component-Specific Collections**:
- Knowledge Builder: `facts`, `stylized_facts`, `knowledge_graphs`, `documents`, `ingestion_batches`, `agent_sessions`
- Modeling Assistant: `scenarios`, `models`, `simulations`, `results`

### 5.1 New Collections

#### **users**
```python
{
    "_id": ObjectId,
    "google_id": str,  # Unique
    "email": str,
    "name": str,
    "picture_url": str,
    "roles": List[str],  # ["knowledge_curator", "agent_operator"]
    "status": str,  # "active", "suspended", "pending_approval"
    "created_at": datetime,
    "updated_at": datetime,
    "last_login": datetime,
    "login_count": int,
    "metadata": {
        "affiliation": str,
        "research_area": str,
        "orcid": str
    }
}
```

#### **role_requests**
```python
{
    "_id": ObjectId,
    "user_id": ObjectId,
    "requested_roles": List[str],
    "current_roles": List[str],
    "justification": str,
    "form_data": dict,
    "status": str,  # "pending", "approved", "rejected"
    "created_at": datetime,
    "reviewed_by": ObjectId,
    "reviewed_at": datetime,
    "review_notes": str
}
```

#### **api_keys**
```python
{
    "_id": ObjectId,
    "user_id": ObjectId,
    "key_hash": str,  # SHA-256
    "key_prefix": str,  # "advk_abc1" (first 8 chars)
    "name": str,
    "scopes": List[str],
    "status": str,  # "active", "revoked", "expired"
    "created_at": datetime,
    "expires_at": datetime,
    "last_used_at": datetime,
    "rate_limit": {
        "requests_per_minute": int,
        "requests_per_day": int
    }
}
```

#### **audit_logs**
```python
{
    "_id": ObjectId,
    "user_id": ObjectId,
    "action": str,  # "create_fact", "approve_fact", "create_scenario", etc.
    "resource_type": str,  # "fact", "document", "user", "scenario", "model"
    "resource_id": ObjectId,
    "component": str,  # "knowledge_builder", "modeling_assistant"
    "details": dict,
    "ip_address": str,
    "user_agent": str,
    "auth_method": str,  # "google_oauth", "api_key"
    "timestamp": datetime
}
```

### 5.2 Modified Existing Collections

**facts, stylized_facts, knowledge_graphs** - Add fields:
```python
{
    # ... existing fields ...
    "created_by": ObjectId,
    "status": str,  # "draft", "pending_review", "published", "rejected"
    "review_status": {
        "reviewed_by": ObjectId,
        "reviewed_at": datetime,
        "decision": str,
        "comments": str
    },
    "is_day_zero": bool
}
```

**documents** - Add fields:
```python
{
    # ... existing fields ...
    "uploaded_by": ObjectId,
    "is_day_zero": bool,
    "batch_id": ObjectId
}
```

**ingestion_batches** - Add fields:
```python
{
    # ... existing fields ...
    "created_by": ObjectId,
    "is_day_zero": bool
}
```

**agent_sessions** - Add fields:
```python
{
    # ... existing fields ...
    "user_id": ObjectId,
    "session_type": str  # "interactive", "background", "api"
}
```

**Diagram**: See `diagrams/knowledge-builder-data-model.puml`

---

## 6. API Endpoints

**Authentication Hosting**: Authentication endpoints are hosted by the **Knowledge Builder backend** (as the primary component). The Modeling Assistant backend validates JWT tokens by querying the shared user database or calling KB auth validation endpoints.

### 6.1 Authentication Endpoints (Knowledge Builder Backend)

```
POST   /api/auth/google           # OAuth code exchange
POST   /api/auth/refresh          # Refresh access token
POST   /api/auth/logout           # Invalidate tokens
GET    /api/auth/me               # Get current user info
```

### 6.2 User Management Endpoints

```
GET    /api/users                 # List users (admin only)
GET    /api/users/{id}            # Get user (admin or self)
PUT    /api/users/{id}            # Update user (admin only)
DELETE /api/users/{id}            # Deactivate user (admin only)
```

### 6.3 Role Request Endpoints

```
POST   /api/role-requests         # Submit role request
GET    /api/role-requests         # List requests
GET    /api/role-requests/{id}    # Get request details
PUT    /api/role-requests/{id}/approve   # Approve (admin)
PUT    /api/role-requests/{id}/reject    # Reject (admin)
```

### 6.4 API Key Endpoints

```
POST   /api/api-keys              # Generate API key
GET    /api/api-keys              # List own keys
DELETE /api/api-keys/{id}         # Revoke key
PUT    /api/api-keys/{id}/regenerate  # Regenerate key
```

### 6.5 Review Workflow Endpoints

```
GET    /api/reviews/pending       # Get pending review queue
POST   /api/reviews/{type}/{id}/approve        # Approve knowledge
POST   /api/reviews/{type}/{id}/reject         # Reject knowledge
POST   /api/reviews/{type}/{id}/request-changes  # Request changes
```

### 6.6 Audit Log Endpoints

```
GET    /api/audit-logs            # View audit logs (platform-wide)
GET    /api/audit-logs/{type}/{id}  # Get resource history
GET    /api/audit-logs/component/{name}  # Filter by component (kb, ma)
```

### 6.7 Modeling Assistant Integration

**Token Validation**: Modeling Assistant backend validates JWT tokens using one of:

1. **Shared validation logic** (recommended): MA backend includes JWT validation code, queries shared MongoDB for user/roles
2. **Token validation endpoint**: MA calls KB endpoint to validate tokens

**Example MA validation**:
```python
# In Modeling Assistant backend
from shared.auth import validate_jwt_token  # Shared library

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Same validation logic as KB
    payload = validate_jwt_token(token)
    user = await users_collection.find_one({"_id": payload["sub"]})
    return user
```

---

## 7. Frontend Integration

### 7.1 New UI Components

**Authentication**:
- Login page with Google OAuth button
- Registration flow (post-Google login)
- Role request form

**User Management (Admin)**:
- User management dashboard
- Role request review page
- Audit log viewer

**User Settings**:
- Profile settings page
- API key management page

**Knowledge Review (Reviewer)**:
- Review queue page
- Review detail page

**Day Zero (Admin)**:
- Day Zero batch creation wizard

### 7.2 State Management

**Auth Store** (Pinia/Vuex):
```javascript
{
  user: User | null,
  roles: string[],
  permissions: string[],
  accessToken: string | null,
  refreshToken: string | null,
  isAuthenticated: boolean
}
```

**Getters**:
- `hasRole(role)`: Check if user has specific role
- `isAdmin`, `isCurator`, `isReviewer`: Convenience checks
- `hasPermission(permission)`: Check specific permission

**Actions**:
- `loginWithGoogle(code)`: Complete OAuth flow
- `logout()`: Clear auth state
- `refreshAccessToken()`: Get new access token

### 7.3 Route Guards

```javascript
router.beforeEach((to, from, next) => {
  if (!to.meta.public && !authStore.isAuthenticated) {
    return next('/login')
  }
  
  if (to.meta.requiredRoles) {
    const hasRole = to.meta.requiredRoles.some(role => 
      authStore.hasRole(role)
    )
    if (!hasRole) {
      return next('/unauthorized')
    }
  }
  
  next()
})
```

---

## 8. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-3)

**Week 1: Backend Core**
- Create database models (User, RoleRequest, APIKey, AuditLog)
- Database migration scripts
- Add fields to existing collections
- Create database indexes

**Week 2: Authentication**
- Google OAuth integration
- JWT generation/validation
- API key generation/validation
- Auth middleware and dependencies
- Refresh token rotation

**Week 3: Authorization**
- Role-based permission system
- Update all endpoints with auth checks
- Audit logging for all actions
- Rate limiting implementation

**Milestone**: Backend fully authenticated, all endpoints protected

### Phase 2: User Management (Weeks 4-5)

**Week 4: Role Request System**
- Role request API endpoints
- Email notifications (approval/rejection)
- Admin approval workflow
- User status management

**Week 5: API Key Management**
- API key CRUD endpoints
- Scope validation
- Key expiration handling
- Usage tracking

**Milestone**: Users can request roles, admins can approve, API keys functional

### Phase 3: Frontend Integration (Weeks 6-8)

**Week 6: Authentication UI**
- Login page with Google OAuth
- Auth state management
- Token storage and refresh
- Route guards
- User profile dropdown

**Week 7: User Management UI**
- Role request form
- Admin user management dashboard
- Admin role request review page
- API key management page
- Profile settings page

**Week 8: Permission-Based UI**
- Update all views with role-based visibility
- Add status badges to knowledge items
- Display creator information
- "Insufficient permissions" messaging

**Milestone**: Frontend fully integrated with auth system

### Phase 4: Review Workflow (Weeks 9-10)

**Week 9: Backend Review System**
- Review queue endpoints
- Approve/reject/request changes logic
- Status transitions
- Reviewer notifications

**Week 10: Frontend Review UI**
- Review queue page
- Review detail page
- Bulk review actions
- Status filtering

**Milestone**: Knowledge review workflow operational

### Phase 5: Day Zero & Migration (Weeks 11-12)

**Week 11: Day Zero System**
- Day Zero batch creation UI
- Auto-publish logic for Day Zero content
- Foundational knowledge indicators
- Day Zero documentation

**Week 12: Data Migration**
- Migration script testing
- Existing data attribution
- 1,300 PDF ingestion as Day Zero
- Production database migration

**Milestone**: Historical data migrated, Day Zero knowledge established

### Phase 6: Shared Library & MA Integration (Weeks 13-15)

**Week 13: Create advandeb-shared-utils**
- Create shared-utils repository
- Implement auth modules (JWT, API keys, OAuth, permissions)
- Create Pydantic models (User, APIKey, AuditLog)
- Write unit tests for shared library
- Set up CI/CD for shared package

**Week 14: Integrate Shared Library**
- Add advandeb-shared dependency to KB backend
- Replace KB-specific auth code with shared imports
- Add advandeb-shared dependency to MA backend
- Implement MA authentication using shared library
- Test cross-component authentication (same JWT works for both)

**Week 15: Testing & Documentation**
- End-to-end testing (all roles, both components)
- Security audit
- User documentation
- Admin documentation
- API documentation updates
- Shared library documentation

**Milestone**: Both KB and MA fully authenticated with unified shared library

### Phase 7: Deployment (Week 15)

- Staging deployment
- Production deployment
- Monitoring dashboards
- Alert configuration
- User onboarding

**Milestone**: System live in production

---

## 9. Security Considerations

### 9.1 Token Security

- **JWT Secret**: 256-bit random key, environment variable
- **Access Token**: 1-hour expiration, HS256 signing
- **Refresh Token**: 30-day expiration, one-time use, stored in DB with revocation support
- **API Keys**: 256-bit random, SHA-256 hashed in database

### 9.2 Input Validation

- All user inputs validated with Pydantic models
- Parameterized queries (Motor/MongoDB)
- XSS prevention (frontend sanitization)
- File upload validation (type, size)

### 9.3 Rate Limiting

**Per-Role Limits** (applies to both KB and MA APIs):
- Explorator: 100 req/min, 10,000/day
- Curator: 200 req/min, 50,000/day
- Analyst: 500 req/min, 100,000/day

**Implementation**: Redis-based rate limiter

### 9.4 HTTPS & CORS

- **Production**: Enforce HTTPS only
- **CORS**: Restrict to known frontend origins
- **CSP Headers**: Content Security Policy

### 9.5 Audit Logging

- All write operations logged
- User attribution for all actions
- IP address and user agent tracking
- Searchable by user, action, resource, timestamp

---

## 10. Migration Strategy

### 10.1 Existing Data

**Current State**:
- ~1,300 PDFs in papers directory (not yet ingested)
- Existing facts/documents in database (if any)

**Migration Steps**:

1. **Prepare**: Create migration scripts, backup database
2. **Schema Migration**: Add new fields to existing collections
3. **Create Collections**: users, role_requests, api_keys, audit_logs
4. **First Admin**: Create administrator account (from environment variable)
5. **Attribute Existing Data**:
   - Existing knowledge: `created_by=NULL`, display as "Community"
   - 1,300 PDFs: Ingested via Day Zero batch by administrator

### 10.2 Rollout Plan

1. Deploy updated backend with auth (unenforced)
2. Deploy updated frontend with login UI
3. Enable authentication enforcement
4. Administrator creates Day Zero batch for 1,300 PDFs
5. Notify initial users to create accounts
6. Administrator manually approves initial users

---

## 11. Component Integration (Knowledge Builder ↔ Modeling Assistant)

### 11.1 Unified Authentication Model

**Architecture**: Both Knowledge Builder and Modeling Assistant share the same authentication infrastructure:

- **Single User Database**: Both components query the same MongoDB `users` collection
- **Shared JWT Tokens**: Tokens issued by KB authentication endpoints work for MA endpoints
- **Same Roles Apply**: User roles (Curator, Analyst, etc.) grant permissions in both KB and MA
- **Cross-Component Audit**: All actions logged to shared `audit_logs` collection

### 11.2 Modeling Assistant Permissions by Role

Each role has specific permissions within the Modeling Assistant:

#### Administrator
- Full access to all MA features
- Configure model templates
- Manage simulation infrastructure
- View all users' scenarios and models
- Override scenario ownership

#### Knowledge Curator
- Create scenarios
- Build biological models
- Run simulations
- Edit own scenarios/models
- View published scenarios from other users

#### Knowledge Reviewer
- All Curator permissions in MA
- Review and approve shared scenarios
- Validate model quality

#### Agent Operator
- All Curator permissions in MA
- Configure MA agent behaviors
- Test modeling algorithms
- Debug simulation failures

#### Data Analyst
- Run analyses on published models
- Export simulation results (CSV, JSON)
- Access advanced statistical tools
- Generate comparative reports
- API access to results data

#### Knowledge Explorator
- View published scenarios (read-only)
- Browse model library
- View simulation results
- No creation or editing capabilities

### 11.3 Implementation Architecture

**Shared Authentication Library**: `advandeb-shared-utils`

A dedicated Python package containing all authentication, authorization, and utility functions shared between Knowledge Builder and Modeling Assistant backends.

**Repository Structure**:
```
advandeb-shared-utils/
├── advandeb_shared/
│   ├── auth/              # JWT, API keys, OAuth, permissions
│   ├── models/            # Pydantic models (User, APIKey, AuditLog)
│   ├── database/          # MongoDB helpers
│   ├── logging/           # Audit logging
│   └── config/            # Shared settings
├── tests/
└── pyproject.toml
```

**Usage in KB and MA**:
```python
# Install in both backends
# pyproject.toml or requirements.txt
advandeb-shared = {path = "../../advandeb-shared-utils", develop = true}

# Import in Knowledge Builder
from advandeb_shared.auth.dependencies import get_current_user, require_role
from advandeb_shared.models.user import User
from advandeb_shared.logging.audit import log_action

@router.post("/api/facts")
async def create_fact(
    fact_data: dict,
    user: User = Depends(require_role(["knowledge_curator", "administrator"]))
):
    fact_id = await create_fact_in_db(fact_data, user.id)
    await log_action(user, "create_fact", "fact", str(fact_id), "knowledge_builder")
    return {"id": str(fact_id)}

# Same imports work in Modeling Assistant
@router.post("/api/scenarios")
async def create_scenario(
    scenario_data: dict,
    user: User = Depends(require_role(["knowledge_curator", "administrator"]))
):
    scenario_id = await create_scenario_in_db(scenario_data, user.id)
    await log_action(user, "create_scenario", "scenario", str(scenario_id), "modeling_assistant")
    return {"id": str(scenario_id)}
```

**See `SHARED-UTILS-PLAN.md` for complete specification of the shared library.**

### 11.4 Modeling Assistant Backend Setup

**Environment Configuration**:
```bash
# advandeb-modeling-assistant/.env
MONGODB_URI=mongodb://localhost:27017/advandeb  # Same database!
JWT_SECRET=<same_secret_as_kb>  # Must match Knowledge Builder
JWT_ALGORITHM=HS256
GOOGLE_OAUTH_CLIENT_ID=<same_as_kb>  # If MA has separate frontend
```

**Database Connection**:
```python
# MA backend connects to same MongoDB
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient(settings.MONGODB_URI)
db = client.advandeb  # Same database as KB
users_collection = db.users  # Same users collection
```

**JWT Validation**:
```python
# MA validates tokens using same secret
from jose import jwt

def validate_token(token: str):
    payload = jwt.decode(
        token, 
        settings.JWT_SECRET,  # Same secret as KB
        algorithms=[settings.JWT_ALGORITHM]
    )
    return payload
```

### 11.5 MA-to-KB Knowledge Queries

When Modeling Assistant needs to query Knowledge Builder data:

**Approach 1: Direct Database Access** (Recommended for internal queries)
```python
# MA backend directly queries KB collections
facts = await db.facts.find({"status": "published"}).to_list(100)
```

**Approach 2: Internal API Calls** (For complex business logic)
```python
# MA backend calls KB API endpoints
# Uses user's JWT token (passed from MA frontend)
async def search_knowledge(user_token: str, query: str):
    response = await httpx.post(
        "http://kb-backend:8000/api/knowledge/search",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"query": query}
    )
    return response.json()
```

**Key Principle**: MA doesn't need a "service account" - it operates on behalf of the authenticated user using their JWT token.

### 11.6 Cross-Component Workflows

**Example: User creates scenario in MA using KB knowledge**

```
1. User authenticates via Google OAuth (KB or MA frontend)
2. User receives JWT token with roles (e.g., knowledge_curator)
3. User navigates to MA frontend
4. MA frontend uses same JWT token for MA API calls
5. User creates scenario, wants to include biological fact from KB
6. MA frontend calls: GET /api/facts/{id} (KB endpoint)
   - Same JWT token in Authorization header
   - KB validates token, checks user has read permission
   - Returns fact data
7. User includes fact in scenario
8. MA frontend calls: POST /api/scenarios (MA endpoint)
   - Same JWT token in Authorization header  
   - MA validates token, checks user has knowledge_curator role
   - Creates scenario, logs action to audit_logs with component="modeling_assistant"
9. Both actions appear in user's unified audit log
```

### 11.7 Security Considerations

- **No Service-to-Service Auth Needed**: MA doesn't authenticate as a separate system; it validates user tokens
- **Shared Secret Security**: JWT secret must be kept secure, shared only between KB and MA backends
- **Database Access Control**: Both backends have full database access; trust boundary at application level
- **Future Isolation**: If components are separated later, can introduce service mesh or API gateway

---

## 12. Open Questions

Before implementation begins, confirm:

### A. Email System
What email service should we use for notifications?
- **Recommendation**: Start with in-app notifications, add email in Phase 2

### B. First Administrator
How should the first admin account be created?
- **Recommendation**: Environment variable with admin email(s), auto-promote on first login

### C. Google OAuth Configuration
Do you have:
- Google Cloud Project created?
- OAuth 2.0 Client ID/Secret?
- Authorized redirect URIs configured?

If not, setup instructions will be provided.

### D. Rate Limits
Are the proposed rate limits acceptable?
- Explorator: 100/min, 10k/day
- Curator: 200/min, 50k/day
- Analyst: 500/min, 100k/day

### E. Component Deployment
Which component will be deployed first?
- **Recommendation**: Deploy KB with authentication first, then add MA integration
- Both components can run on same server initially (different ports)
- Share same MongoDB instance

---

## 13. Success Criteria

Implementation is successful when:

✅ Users can sign in with Google OAuth  
✅ JWT tokens are generated and validated correctly  
✅ API keys authenticate successfully  
✅ All 7 roles have correct permissions  
✅ Multi-role users have union of permissions  
✅ Unauthorized access is blocked  
✅ Ownership checks work (users can only edit own content)  
✅ New users can request roles  
✅ Administrators can approve/reject requests  
✅ Curators create knowledge with "pending" status  
✅ Reviewers can approve/reject knowledge  
✅ Approved knowledge becomes visible to all  
✅ Day Zero batches are auto-published  
✅ 1,300 PDFs successfully ingested as Day Zero  
✅ Curators and Analysts can generate API keys  
✅ Rate limiting enforces limits  
✅ All write operations are logged  
✅ Frontend login flow works smoothly  
✅ Role-based UI elements show/hide correctly  
✅ System remains stable post-migration  
✅ **Modeling Assistant validates JWT tokens correctly**  
✅ **Same user can access both KB and MA with single login**  
✅ **Cross-component audit logging works**  

---

## 14. References

**Diagrams**:
- `diagrams/system-context.puml` - System context with user roles
- `diagrams/knowledge-builder-container.puml` - Container architecture with auth modules
- `diagrams/knowledge-builder-data-model.puml` - Complete data model with user entities
- `diagrams/authentication-flow.puml` - Google OAuth & API key authentication flows
- `diagrams/role-request-workflow.puml` - Role request and approval workflow
- `diagrams/review-workflow.puml` - Knowledge review and validation workflow

**Related Documents**:
- `SYSTEM-OVERVIEW.md` - Updated with user management overview
- `ROADMAP.md` - Updated with authentication phase
- `KNOWLEDGE-BUILDER-PLAN.md` - Development plan

**External Resources**:
- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)

---

**Document Status**: Design Complete  
**Next Action**: Begin Phase 1 implementation (Backend Core)  
**Contact**: AdvandEB Development Team
