# AdvandEB Shared Utils: Authentication & Authorization Library

**Version:** 1.0  
**Date:** December 11, 2025  
**Status:** Design Complete - Ready for Implementation

---

## Executive Summary

The `advandeb-shared-utils` repository is a **Python package** that provides shared authentication, authorization, and utility functions for the entire AdvandEB platform. Both **Knowledge Builder** and **Modeling Assistant** backends import this package to ensure consistent authentication and eliminate code duplication.

### Key Features

- ✅ **JWT token validation** - Shared token validation logic
- ✅ **API key validation** - Centralized API key authentication
- ✅ **Permission checking** - Role-based access control utilities
- ✅ **Audit logging** - Consistent audit logging across components
- ✅ **User models** - Pydantic models for users, roles, API keys
- ✅ **OAuth clients** - Google OAuth integration helpers
- ✅ **Database utilities** - MongoDB connection helpers for user collections

---

## 1. Repository Structure

```
advandeb-shared-utils/
├── README.md
├── pyproject.toml              # Package configuration (Poetry or setuptools)
├── setup.py                    # Alternative package setup
├── advandeb_shared/            # Main package
│   ├── __init__.py
│   ├── auth/                   # Authentication & Authorization
│   │   ├── __init__.py
│   │   ├── jwt.py              # JWT generation and validation
│   │   ├── api_keys.py         # API key validation
│   │   ├── oauth.py            # Google OAuth helpers
│   │   ├── permissions.py      # Role-based permission checking
│   │   └── dependencies.py     # FastAPI dependencies (require_role, etc.)
│   ├── models/                 # Shared Pydantic models
│   │   ├── __init__.py
│   │   ├── user.py             # User, RoleRequest models
│   │   ├── auth.py             # Token, APIKey models
│   │   └── audit.py            # AuditLog models
│   ├── database/               # Database utilities
│   │   ├── __init__.py
│   │   └── mongodb.py          # MongoDB connection helpers
│   ├── logging/                # Audit logging
│   │   ├── __init__.py
│   │   └── audit.py            # Audit logging functions
│   └── config/                 # Configuration
│       ├── __init__.py
│       └── settings.py         # Shared settings (JWT_SECRET, etc.)
├── tests/                      # Unit tests
│   ├── __init__.py
│   ├── test_jwt.py
│   ├── test_api_keys.py
│   ├── test_permissions.py
│   └── test_oauth.py
└── .github/
    └── workflows/
        └── ci.yml              # CI/CD for testing and publishing
```

---

## 2. Core Modules

### 2.1 JWT Module (`auth/jwt.py`)

**Purpose**: Generate and validate JWT tokens

```python
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from advandeb_shared.models.user import User
from advandeb_shared.config.settings import get_settings

settings = get_settings()

def create_access_token(user: User, expires_delta: Optional[timedelta] = None) -> str:
    """Generate JWT access token for user"""
    if expires_delta is None:
        expires_delta = timedelta(hours=1)
    
    expire = datetime.utcnow() + expires_delta
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "roles": user.roles,
        "iat": datetime.utcnow(),
        "exp": expire,
        "jti": generate_token_id()
    }
    
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def validate_jwt_token(token: str) -> dict:
    """Validate JWT token and return payload"""
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        raise InvalidTokenError(f"Invalid token: {e}")

def create_refresh_token(user_id: str) -> str:
    """Generate refresh token (long-lived)"""
    expire = datetime.utcnow() + timedelta(days=30)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": datetime.utcnow(),
        "exp": expire,
        "jti": generate_token_id()
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
```

**Exports**:
- `create_access_token(user, expires_delta) -> str`
- `create_refresh_token(user_id) -> str`
- `validate_jwt_token(token) -> dict`

---

### 2.2 API Key Module (`auth/api_keys.py`)

**Purpose**: Generate and validate API keys

```python
import secrets
import hashlib
from datetime import datetime, timedelta
from advandeb_shared.models.auth import APIKey

def generate_api_key() -> tuple[str, str]:
    """
    Generate API key and return (plain_key, hash)
    
    Returns:
        plain_key: "advk_" + 32-byte random (show to user ONCE)
        key_hash: SHA-256 hash (store in database)
    """
    random_bytes = secrets.token_hex(32)
    plain_key = f"advk_{random_bytes}"
    key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
    return plain_key, key_hash

def hash_api_key(plain_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(plain_key.encode()).hexdigest()

async def validate_api_key(plain_key: str, api_keys_collection) -> Optional[APIKey]:
    """
    Validate API key against database
    
    Args:
        plain_key: API key from Authorization header
        api_keys_collection: MongoDB collection
        
    Returns:
        APIKey model if valid and active, None otherwise
    """
    key_hash = hash_api_key(plain_key)
    key_prefix = plain_key[:12]  # "advk_abc1234"
    
    # Find key by hash
    key_doc = await api_keys_collection.find_one({
        "key_hash": key_hash,
        "status": "active"
    })
    
    if not key_doc:
        return None
    
    # Check expiration
    if key_doc["expires_at"] < datetime.utcnow():
        await api_keys_collection.update_one(
            {"_id": key_doc["_id"]},
            {"$set": {"status": "expired"}}
        )
        return None
    
    # Update last_used_at
    await api_keys_collection.update_one(
        {"_id": key_doc["_id"]},
        {"$set": {"last_used_at": datetime.utcnow()}}
    )
    
    return APIKey(**key_doc)
```

**Exports**:
- `generate_api_key() -> (plain_key, hash)`
- `hash_api_key(plain_key) -> str`
- `validate_api_key(plain_key, collection) -> APIKey | None`

---

### 2.3 Permissions Module (`auth/permissions.py`)

**Purpose**: Role-based permission checking

```python
from typing import List, Optional
from advandeb_shared.models.user import User

# Role hierarchy
ROLE_HIERARCHY = {
    "administrator": 100,
    "knowledge_curator": 50,
    "knowledge_reviewer": 50,  # Same level as curator
    "agent_operator": 50,
    "data_analyst": 30,
    "knowledge_explorator": 10
}

def has_role(user: User, required_role: str) -> bool:
    """Check if user has specific role"""
    return required_role in user.roles

def has_any_role(user: User, required_roles: List[str]) -> bool:
    """Check if user has any of the required roles"""
    return any(role in user.roles for role in required_roles)

def has_all_roles(user: User, required_roles: List[str]) -> bool:
    """Check if user has all required roles"""
    return all(role in user.roles for role in required_roles)

def has_permission(user: User, permission: str) -> bool:
    """
    Check if user has specific permission based on roles
    
    Permissions examples:
    - "read:facts"
    - "write:facts"
    - "approve:knowledge"
    - "manage:users"
    """
    # Map permissions to roles
    PERMISSION_MAP = {
        # Knowledge Builder permissions
        "read:facts": ["knowledge_explorator", "data_analyst", "knowledge_curator", "administrator"],
        "write:facts": ["knowledge_curator", "administrator"],
        "approve:knowledge": ["knowledge_reviewer", "administrator"],
        "manage:users": ["administrator"],
        "manage:agents": ["agent_operator", "administrator"],
        "bulk:export": ["data_analyst", "administrator"],
        
        # Modeling Assistant permissions
        "read:models": ["knowledge_explorator", "data_analyst", "knowledge_curator", "administrator"],
        "write:models": ["knowledge_curator", "administrator"],
        "run:scenarios": ["knowledge_curator", "data_analyst", "administrator"],
        "export:results": ["data_analyst", "administrator"],
    }
    
    allowed_roles = PERMISSION_MAP.get(permission, [])
    return has_any_role(user, allowed_roles)

def is_owner(user: User, resource_user_id: str) -> bool:
    """Check if user owns the resource"""
    return str(user.id) == resource_user_id

def can_edit_resource(user: User, resource_user_id: str, resource_status: str) -> bool:
    """Check if user can edit a knowledge resource"""
    # Admins can edit anything
    if has_role(user, "administrator"):
        return True
    
    # Reviewers can edit during review
    if has_role(user, "knowledge_reviewer") and resource_status == "pending_review":
        return True
    
    # Users can edit own pending resources
    if is_owner(user, resource_user_id) and resource_status in ["draft", "pending_review", "changes_requested"]:
        return True
    
    return False
```

**Exports**:
- `has_role(user, role) -> bool`
- `has_any_role(user, roles) -> bool`
- `has_all_roles(user, roles) -> bool`
- `has_permission(user, permission) -> bool`
- `is_owner(user, resource_user_id) -> bool`
- `can_edit_resource(user, resource_user_id, status) -> bool`

---

### 2.4 FastAPI Dependencies (`auth/dependencies.py`)

**Purpose**: FastAPI dependency injection for authentication/authorization

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Optional
from advandeb_shared.auth.jwt import validate_jwt_token
from advandeb_shared.auth.api_keys import validate_api_key
from advandeb_shared.auth.permissions import has_any_role
from advandeb_shared.models.user import User
from advandeb_shared.database.mongodb import get_database

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    Get current authenticated user from JWT token or API key
    
    Usage in FastAPI:
        @router.get("/api/facts")
        async def get_facts(user: User = Depends(get_current_user)):
            ...
    """
    token = credentials.credentials
    
    # Try JWT first
    if not token.startswith("advk_"):
        try:
            payload = validate_jwt_token(token)
            db = await get_database()
            user_doc = await db.users.find_one({"_id": ObjectId(payload["sub"])})
            if not user_doc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )
            return User(**user_doc)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {e}"
            )
    
    # Try API key
    else:
        db = await get_database()
        api_key = await validate_api_key(token, db.api_keys)
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key"
            )
        
        # Load user from API key
        user_doc = await db.users.find_one({"_id": api_key.user_id})
        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        return User(**user_doc)

def require_role(required_roles: List[str]):
    """
    Require user to have one of the specified roles
    
    Usage:
        @router.post("/api/facts")
        async def create_fact(
            user: User = Depends(require_role(["knowledge_curator", "administrator"]))
        ):
            ...
    """
    async def check_role(user: User = Depends(get_current_user)) -> User:
        if not has_any_role(user, required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: one of {required_roles}"
            )
        return user
    return check_role

def require_admin(user: User = Depends(get_current_user)) -> User:
    """Shorthand for requiring administrator role"""
    if not has_any_role(user, ["administrator"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required"
        )
    return user
```

**Exports**:
- `get_current_user() -> User` (FastAPI dependency)
- `require_role(roles) -> User` (FastAPI dependency factory)
- `require_admin() -> User` (FastAPI dependency)

---

### 2.5 Google OAuth Module (`auth/oauth.py`)

**Purpose**: Google OAuth integration helpers

```python
import httpx
from typing import Optional
from advandeb_shared.config.settings import get_settings

settings = get_settings()

class GoogleOAuthClient:
    """Helper for Google OAuth 2.0 flow"""
    
    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI
        
        self.authorization_url = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_url = "https://oauth2.googleapis.com/token"
        self.userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    def get_authorization_url(self, state: str) -> str:
        """Get URL to redirect user for OAuth consent"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent"
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.authorization_url}?{query}"
    
    async def exchange_code_for_token(self, code: str) -> dict:
        """Exchange authorization code for access token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri
                }
            )
            response.raise_for_status()
            return response.json()
    
    async def get_user_info(self, access_token: str) -> dict:
        """Get user profile from Google"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json()  # {id, email, name, picture}
```

**Exports**:
- `GoogleOAuthClient` class

---

### 2.6 Audit Logging (`logging/audit.py`)

**Purpose**: Centralized audit logging

```python
from datetime import datetime
from typing import Optional
from bson import ObjectId
from advandeb_shared.models.user import User
from advandeb_shared.database.mongodb import get_database

async def log_action(
    user: User,
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    component: str,  # "knowledge_builder" or "modeling_assistant"
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    auth_method: str = "jwt"
):
    """
    Log user action to audit trail
    
    Args:
        user: Authenticated user
        action: Action performed (e.g., "create_fact", "approve_knowledge")
        resource_type: Type of resource (e.g., "fact", "document", "scenario")
        resource_id: ID of resource affected (or None for list operations)
        component: Which component logged this action
        details: Additional context (dict)
        ip_address: User's IP address
        user_agent: User's browser/client
        auth_method: "jwt", "api_key", or "google_oauth"
    """
    db = await get_database()
    
    log_entry = {
        "user_id": user.id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": ObjectId(resource_id) if resource_id else None,
        "component": component,
        "details": details or {},
        "ip_address": ip_address,
        "user_agent": user_agent,
        "auth_method": auth_method,
        "timestamp": datetime.utcnow()
    }
    
    await db.audit_logs.insert_one(log_entry)
```

**Exports**:
- `log_action(...) -> None`

---

## 3. Shared Pydantic Models

### 3.1 User Models (`models/user.py`)

```python
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

class User(BaseModel):
    """Platform user model"""
    id: ObjectId = Field(alias="_id")
    google_id: str
    email: EmailStr
    name: str
    picture_url: Optional[str] = None
    roles: List[str] = []
    status: str = "active"  # active, suspended, pending_approval
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    login_count: int = 0
    metadata: dict = {}
    
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class RoleRequest(BaseModel):
    """Role request model"""
    id: ObjectId = Field(alias="_id")
    user_id: ObjectId
    requested_roles: List[str]
    current_roles: List[str]
    justification: str
    form_data: dict
    status: str  # pending, approved, rejected
    created_at: datetime
    reviewed_by: Optional[ObjectId] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
```

### 3.2 Auth Models (`models/auth.py`)

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

class APIKey(BaseModel):
    """API key model"""
    id: ObjectId = Field(alias="_id")
    user_id: ObjectId
    key_hash: str  # SHA-256
    key_prefix: str  # "advk_abc1234"
    name: str
    scopes: List[str]
    status: str  # active, revoked, expired
    created_at: datetime
    expires_at: datetime
    last_used_at: Optional[datetime] = None
    rate_limit: dict  # {requests_per_minute: int, requests_per_day: int}
    
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class TokenPair(BaseModel):
    """JWT token pair"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600  # seconds
```

### 3.3 Audit Models (`models/audit.py`)

```python
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from bson import ObjectId

class AuditLog(BaseModel):
    """Audit log entry"""
    id: ObjectId = Field(alias="_id")
    user_id: ObjectId
    action: str
    resource_type: str
    resource_id: Optional[ObjectId] = None
    component: str  # "knowledge_builder", "modeling_assistant"
    details: dict
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    auth_method: str  # "jwt", "api_key", "google_oauth"
    timestamp: datetime
    
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
```

---

## 4. Configuration (`config/settings.py`)

```python
from pydantic_settings import BaseSettings
from typing import Optional

class SharedSettings(BaseSettings):
    """Shared configuration for authentication"""
    
    # JWT Configuration
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # Google OAuth Configuration
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    
    # MongoDB Configuration
    MONGODB_URI: str
    MONGODB_DB_NAME: str = "advandeb"
    
    # Admin Configuration
    ADMIN_EMAILS: Optional[str] = None  # Comma-separated
    
    class Config:
        env_file = ".env"
        case_sensitive = True

_settings = None

def get_settings() -> SharedSettings:
    """Get singleton settings instance"""
    global _settings
    if _settings is None:
        _settings = SharedSettings()
    return _settings
```

---

## 5. Database Utilities (`database/mongodb.py`)

```python
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from advandeb_shared.config.settings import get_settings

_db_client = None
_db = None

async def get_database() -> AsyncIOMotorDatabase:
    """Get MongoDB database instance (singleton)"""
    global _db_client, _db
    
    if _db is None:
        settings = get_settings()
        _db_client = AsyncIOMotorClient(settings.MONGODB_URI)
        _db = _db_client[settings.MONGODB_DB_NAME]
    
    return _db

async def close_database():
    """Close MongoDB connection"""
    global _db_client, _db
    if _db_client:
        _db_client.close()
        _db_client = None
        _db = None
```

---

## 6. Package Installation

### 6.1 pyproject.toml (Poetry)

```toml
[tool.poetry]
name = "advandeb-shared"
version = "0.1.0"
description = "Shared authentication and utilities for AdvandEB platform"
authors = ["AdvandEB Team"]
readme = "README.md"
packages = [{include = "advandeb_shared"}]

[tool.poetry.dependencies]
python = "^3.10"
fastapi = "^0.104.0"
pydantic = "^2.5.0"
pydantic-settings = "^2.1.0"
python-jose = {extras = ["cryptography"], version = "^3.3.0"}
httpx = "^0.25.0"
motor = "^3.3.0"
python-multipart = "^0.0.6"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.0"
pytest-asyncio = "^0.21.0"
pytest-cov = "^4.1.0"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

### 6.2 Installation in KB and MA

In both `advandeb-knowledge-builder/backend` and `advandeb-modeling-assistant/backend`:

```toml
# pyproject.toml or requirements.txt

# Local development (editable install)
advandeb-shared = {path = "../../advandeb-shared-utils", develop = true}

# Or from Git
advandeb-shared = {git = "https://github.com/your-org/advandeb-shared-utils.git", tag = "v0.1.0"}
```

---

## 7. Usage Examples

### 7.1 In Knowledge Builder Backend

```python
# advandeb-knowledge-builder/backend/routers/knowledge.py

from fastapi import APIRouter, Depends
from advandeb_shared.auth.dependencies import get_current_user, require_role
from advandeb_shared.models.user import User
from advandeb_shared.logging.audit import log_action

router = APIRouter()

@router.post("/api/facts")
async def create_fact(
    fact_data: dict,
    user: User = Depends(require_role(["knowledge_curator", "administrator"]))
):
    """Create a new fact (requires Curator or Admin role)"""
    
    # Create fact in database
    fact_id = await create_fact_in_db(fact_data, user.id)
    
    # Log action
    await log_action(
        user=user,
        action="create_fact",
        resource_type="fact",
        resource_id=str(fact_id),
        component="knowledge_builder",
        details={"fact_title": fact_data.get("title")}
    )
    
    return {"id": str(fact_id), "status": "pending_review"}

@router.get("/api/facts")
async def list_facts(
    user: User = Depends(get_current_user)
):
    """List facts (any authenticated user)"""
    # ... implementation
```

### 7.2 In Modeling Assistant Backend

```python
# advandeb-modeling-assistant/backend/routers/scenarios.py

from fastapi import APIRouter, Depends
from advandeb_shared.auth.dependencies import get_current_user, require_role
from advandeb_shared.models.user import User
from advandeb_shared.logging.audit import log_action

router = APIRouter()

@router.post("/api/scenarios")
async def create_scenario(
    scenario_data: dict,
    user: User = Depends(require_role(["knowledge_curator", "administrator"]))
):
    """Create a new modeling scenario (requires Curator or Admin role)"""
    
    # Create scenario in database
    scenario_id = await create_scenario_in_db(scenario_data, user.id)
    
    # Log action
    await log_action(
        user=user,
        action="create_scenario",
        resource_type="scenario",
        resource_id=str(scenario_id),
        component="modeling_assistant",
        details={"scenario_name": scenario_data.get("name")}
    )
    
    return {"id": str(scenario_id)}
```

---

## 8. Testing Strategy

```python
# tests/test_jwt.py

import pytest
from advandeb_shared.auth.jwt import create_access_token, validate_jwt_token
from advandeb_shared.models.user import User
from datetime import datetime
from bson import ObjectId

@pytest.mark.asyncio
async def test_create_and_validate_jwt():
    """Test JWT creation and validation"""
    user = User(
        _id=ObjectId(),
        google_id="123456",
        email="test@example.com",
        name="Test User",
        roles=["knowledge_curator"],
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    # Create token
    token = create_access_token(user)
    assert token.startswith("eyJ")
    
    # Validate token
    payload = validate_jwt_token(token)
    assert payload["email"] == "test@example.com"
    assert "knowledge_curator" in payload["roles"]
```

---

## 9. Deployment & Versioning

### 9.1 Versioning Strategy

- **Semantic Versioning**: `MAJOR.MINOR.PATCH`
  - MAJOR: Breaking changes to API
  - MINOR: New features (backward compatible)
  - PATCH: Bug fixes

### 9.2 Publishing Package

```bash
# Build package
poetry build

# Publish to private PyPI or Git
poetry publish --repository private-pypi

# Or tag and push to Git
git tag v0.1.0
git push origin v0.1.0
```

### 9.3 Updating in KB and MA

```bash
# In knowledge-builder or modeling-assistant backend
poetry update advandeb-shared
```

---

## 10. Migration Plan

### Phase 1: Create Repository (Week 1)
1. Create `advandeb-shared-utils` repository
2. Implement core auth modules (JWT, API keys, permissions)
3. Create Pydantic models
4. Write unit tests
5. Set up CI/CD

### Phase 2: Integrate into KB (Week 2)
1. Add `advandeb-shared` dependency to KB
2. Replace KB-specific auth code with shared imports
3. Update KB routers to use shared dependencies
4. Test authentication flows

### Phase 3: Integrate into MA (Week 3)
1. Add `advandeb-shared` dependency to MA
2. Implement authentication in MA using shared library
3. Test cross-component authentication (same JWT works for both)
4. Validate audit logging from both components

### Phase 4: Refinement (Week 4)
1. Add missing features based on feedback
2. Improve error handling
3. Add more comprehensive tests
4. Update documentation

---

## 11. Benefits

✅ **Code Reusability**: Write authentication logic once, use in multiple components  
✅ **Consistency**: Same authentication behavior across KB and MA  
✅ **Maintainability**: Fix bugs in one place, all components benefit  
✅ **Testing**: Unit test auth logic independently  
✅ **Versioning**: Track changes to auth logic with semantic versions  
✅ **Isolation**: Auth logic separated from business logic  

---

## 12. Future Enhancements

- **Rate limiting utilities**: Centralized rate limiting helpers
- **Encryption utilities**: Shared encryption/decryption functions
- **Common exceptions**: Standardized exception classes
- **Monitoring helpers**: Shared logging and metrics utilities
- **Cache utilities**: Redis caching helpers

---

**Document Status**: Design Complete  
**Next Action**: Create `advandeb-shared-utils` repository and implement Phase 1  
**Contact**: AdvandEB Development Team
