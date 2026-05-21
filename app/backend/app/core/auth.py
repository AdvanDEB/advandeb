"""
Authentication and authorization utilities.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode["type"] = "access"
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token.

    Each refresh token gets a unique ``jti`` (JWT ID) claim so that individual
    tokens can be revoked server-side via ``revoke_refresh_token``.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode["jti"] = uuid.uuid4().hex
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str, expected_type: Optional[str] = "access") -> dict:
    """Verify and decode JWT token.

    If ``expected_type`` is not None, the token's ``type`` claim must equal it,
    otherwise a 401 is raised. Pass ``expected_type=None`` to skip the check
    (e.g. when the caller wants to inspect the type itself, such as the
    refresh-token endpoint).
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if expected_type is not None and payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Get current authenticated user from token, including roles from DB."""
    from bson import ObjectId
    from bson.errors import InvalidId
    from app.core.database import get_database

    payload = verify_token(token)
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

    try:
        user_oid = ObjectId(user_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

    db = get_database()
    user_doc = await db.users.find_one({"_id": user_oid})
    if user_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return {
        "id": str(user_doc["_id"]),
        "email": user_doc.get("email"),
        "roles": user_doc.get("roles", []),
        "capabilities": user_doc.get("capabilities", []),
    }


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def get_password_hash(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


# ---------------------------------------------------------------------------
# Refresh-token revocation
# ---------------------------------------------------------------------------

async def revoke_refresh_token(jti: str, exp: datetime) -> None:
    """Record a refresh token as revoked.

    The ``exp`` datetime mirrors the JWT's ``exp`` claim so a TTL index on
    ``revoked_tokens.exp`` can auto-prune stale entries once the token would
    have expired anyway.
    """
    from app.core.database import get_database
    db = get_database()
    await db.revoked_tokens.update_one(
        {"jti": jti},
        {"$set": {"jti": jti, "exp": exp}},
        upsert=True,
    )


async def is_refresh_token_revoked(jti: str) -> bool:
    """Return True if the given refresh-token jti has been revoked."""
    from app.core.database import get_database
    db = get_database()
    return await db.revoked_tokens.find_one({"jti": jti}) is not None
