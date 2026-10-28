"""
Authentication and authorization utilities.

Every way a request can carry a token — the ``Authorization`` header, the
``?token=`` query parameter that EventSource and WebSocket clients are limited
to — ends in :func:`resolve_user`. It is the one place that decides whether a
token still speaks for an account, so suspension, session revocation and the
external-contributor boundary are enforced once rather than in each resolver
that used to grow beside the routes that needed one.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# The only account status that may act. Documents written before the field
# existed have none and count as active; anything else ("suspended", and the
# "inactive" the User model mentions) is refused.
ACTIVE_STATUS = "active"

# Minimum-privilege role for external elicitation participants
# (advandeb_methods docs/10 section 4.1). Defined by what it EXCLUDES: no
# documents, no chat, no knowledge base, no graph, no models. Every existing
# role implies read access to curated material, some of it licensed full text
# that cannot leave the project, so an external contributor must not inherit
# that by accident.
ROLE_EXTERNAL_CONTRIBUTOR = "external_contributor"

# What an account holding *only* the external-contributor role may reach: its
# elicitation queue and its own settings. The rule is an allowlist checked in
# the resolver, so a router added later is closed to them by default instead
# of open until someone remembers to gate it. Mirrors EXTERNAL_ALLOWED_PREFIXES
# in the frontend router, which is presentation; this is the control.
EXTERNAL_CONTRIBUTOR_ALLOWED_PREFIXES = ("/api/elicitation", "/api/users/me")

# bcrypt hashes the first 72 bytes of a password and, from bcrypt 5, raises on
# anything longer rather than truncating silently.
BCRYPT_MAX_PASSWORD_BYTES = 72

_CREDENTIALS_ERROR = "Could not validate credentials"


def _unauthorized(detail: str = _CREDENTIALS_ERROR) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode["type"] = "access"
    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token.

    Each refresh token gets a unique ``jti`` (JWT ID) claim so that individual
    tokens can be revoked server-side via ``revoke_refresh_token``.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode["jti"] = uuid.uuid4().hex
    to_encode.update({"exp": expire, "iat": now, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_token_pair(user_id: str, email: Optional[str], token_version: int = 0) -> tuple[str, str]:
    """Mint an (access, refresh) pair for a user.

    ``token_version`` is the account's current session generation (see
    :func:`token_revoked`); a pair minted with an older one is dead on arrival.
    """
    return (
        create_access_token(data={"sub": user_id, "email": email, "ver": token_version}),
        create_refresh_token(data={"sub": user_id, "ver": token_version}),
    )


def verify_token(token: str, expected_type: Optional[str] = "access") -> dict:
    """Verify and decode JWT token.

    If ``expected_type`` is not None, the token's ``type`` claim must equal it,
    otherwise a 401 is raised. Refresh tokens carry ``type="refresh"``, so the
    refresh and logout endpoints pass ``expected_type="refresh"``; pass
    ``expected_type=None`` to skip the check entirely.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise _unauthorized()

    if expected_type is not None and payload.get("type") != expected_type:
        raise _unauthorized()

    return payload


# ---------------------------------------------------------------------------
# Account checks shared by every resolver
# ---------------------------------------------------------------------------

def is_external_only(roles: Optional[Iterable[str]]) -> bool:
    """True when every role an account holds is the external-contributor role.

    An external contributor who has *also* been granted an ordinary role is
    treated by that role — the same rule the frontend router applies.
    """
    roles = list(roles or [])
    return bool(roles) and all(r == ROLE_EXTERNAL_CONTRIBUTOR for r in roles)


def path_allowed_for_external(path: str) -> bool:
    """Whether an external-contributor-only account may reach ``path``."""
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in EXTERNAL_CONTRIBUTOR_ALLOWED_PREFIXES
    )


def token_revoked(payload: dict, user_doc: dict) -> bool:
    """True if the account's sessions were revoked after this token was minted.

    Every token carries the account's session generation (``ver``) from the
    moment it was issued; ending all sessions — a password change, an
    administrator reset, a suspension — increments ``users.token_version``.
    A counter rather than a timestamp: JWT ``iat`` has one-second resolution,
    so a cutoff time would spare a token minted in the same second. Tokens and
    accounts from before the counter existed both read as generation 0.
    """
    return payload.get("ver", 0) != user_doc.get("token_version", 0)


def ensure_account_active(user_doc: dict) -> None:
    """Refuse a suspended (or otherwise non-active) account.

    401 rather than 403: the credentials the client holds no longer speak for
    an account, and a 401 is what makes the SPA drop them — the refresh it
    attempts fails the same check and ends the session.
    """
    if (user_doc.get("status") or ACTIVE_STATUS) != ACTIVE_STATUS:
        raise _unauthorized("Account suspended")


def ensure_path_allowed(user_doc: dict, path: Optional[str]) -> None:
    """Confine an external-contributor-only account to its allowlist."""
    if path is None:
        return
    if is_external_only(user_doc.get("roles")) and not path_allowed_for_external(path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not available to external contributors",
        )


def user_context(user_doc: dict) -> dict:
    """The ``current_user`` dict routes receive."""
    return {
        "id": str(user_doc["_id"]),
        "email": user_doc.get("email"),
        "roles": user_doc.get("roles", []) or [],
        "capabilities": user_doc.get("capabilities", []) or [],
        "status": user_doc.get("status") or ACTIVE_STATUS,
    }


async def load_user_doc(user_id: Optional[str]) -> Optional[dict]:
    """Fetch a user document by id string; None for a missing or malformed id."""
    from bson import ObjectId
    from bson.errors import InvalidId
    from app.core.database import get_database

    if not user_id:
        return None
    try:
        user_oid = ObjectId(user_id)
    except (InvalidId, TypeError):
        return None
    return await get_database().users.find_one({"_id": user_oid})


async def resolve_user(token: Optional[str], *, path: Optional[str] = None) -> dict:
    """Resolve an access token to the account it speaks for.

    The single token → user path: the ``get_current_user`` dependency, the
    WebSocket endpoints and the SSE streams all call this. Raises 401 for a
    missing, invalid, expired, wrong-type or revoked token, and for a suspended
    account; 403 when an external-contributor-only account asks for a path
    outside its allowlist. ``path`` is the request path being served —
    ``None`` skips the allowlist, for callers that are not serving a request.
    """
    if not token:
        raise _unauthorized("Not authenticated")
    payload = verify_token(token, expected_type="access")

    user_doc = await load_user_doc(payload.get("sub"))
    if user_doc is None:
        raise _unauthorized()

    ensure_account_active(user_doc)
    if token_revoked(payload, user_doc):
        raise _unauthorized("Session has been revoked")
    ensure_path_allowed(user_doc, path)
    return user_context(user_doc)


# --------------------------------------------------------------------------- #
# Socket tickets                                                               #
# --------------------------------------------------------------------------- #
#
# The browser WebSocket and EventSource APIs cannot set an Authorization
# header, so their credential has to ride in the URL — where proxies and
# servers log it. A ticket is what goes there instead of the access token:
# minted over an authenticated POST, valid for TICKET_TTL_SECONDS, good for one
# connection, and useless as a bearer token (its type is "ticket").

TICKET_TTL_SECONDS = 30


def create_socket_ticket(user_doc: dict) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_doc["_id"]),
            "type": "ticket",
            "jti": uuid.uuid4().hex,
            "ver": user_doc.get("token_version", 0),
            "iat": now,
            "exp": now + timedelta(seconds=TICKET_TTL_SECONDS),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


async def resolve_ticket(ticket: Optional[str], *, path: Optional[str] = None) -> dict:
    """Resolve a socket ticket to its account, consuming it.

    The same account checks as :func:`resolve_user`; the ticket is spent once
    they pass. Role checks come after (``require_curator`` and the like), so a
    ticket presented where its holder may not go is spent and refused.
    """
    if not ticket:
        raise _unauthorized("Not authenticated")
    payload = verify_token(ticket, expected_type="ticket")

    user_doc = await load_user_doc(payload.get("sub"))
    if user_doc is None:
        raise _unauthorized()
    ensure_account_active(user_doc)
    if token_revoked(payload, user_doc):
        raise _unauthorized("Session has been revoked")
    ensure_path_allowed(user_doc, path)

    jti, exp = payload.get("jti"), payload.get("exp")
    if not jti or not isinstance(exp, (int, float)) or not await consume_jti(
            jti, datetime.fromtimestamp(exp, tz=timezone.utc)):
        raise _unauthorized("Ticket already used")
    return user_context(user_doc)


async def resolve_socket_user(
    ticket: Optional[str], token: Optional[str], *, path: Optional[str] = None
) -> dict:
    """The credential a WebSocket/EventSource request carries in its URL.

    ``?ticket=`` is the supported form. ``?token=`` (a raw access token) is
    still accepted so that browser tabs running an SPA build from before
    tickets keep working until they reload; remove it once none can be left.
    """
    if ticket:
        return await resolve_ticket(ticket, path=path)
    return await resolve_user(token, path=path)


def bearer_or_query_token(token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    """Pick the JWT from ``?token=`` or an ``Authorization: Bearer`` header.

    EventSource and the browser WebSocket API cannot set headers, so those
    clients are limited to the query parameter.
    """
    if token:
        return token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)) -> dict:
    """Get current authenticated user from token, including roles from DB."""
    return await resolve_user(token, path=request.url.path)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash.

    Only the first 72 bytes are compared: that is all bcrypt ever hashed, and
    hashes made before bcrypt 5 were made from silently truncated input. Passing
    a longer value would raise ValueError (a 500 at login) instead of answering.
    A stored value that is not a bcrypt hash reads as a mismatch, not a crash.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode()[:BCRYPT_MAX_PASSWORD_BYTES],
            hashed_password.encode(),
        )
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    """Hash password with bcrypt.

    Raises ValueError for a password over 72 bytes; request models reject those
    with a 422 before they get here (see ``app.models.user``).
    """
    encoded = password.encode()
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"password exceeds {BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()


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


async def consume_jti(jti: str, exp: datetime) -> bool:
    """Atomically mark a single-use token used; False if it already was.

    Serves refresh-token rotation and socket tickets. It has to be
    check-and-set in one step: with a separate "is it revoked?" read followed
    by a write, two requests presenting the same token both pass the read.
    The unique index on ``revoked_tokens.jti`` makes the insert the arbiter,
    and its TTL index on ``exp`` prunes the entry once the token would have
    expired anyway.
    """
    from pymongo.errors import DuplicateKeyError
    from app.core.database import get_database
    db = get_database()
    try:
        await db.revoked_tokens.insert_one({"jti": jti, "exp": exp})
    except DuplicateKeyError:
        return False
    return True


async def is_refresh_token_revoked(jti: str) -> bool:
    """Return True if the given refresh-token jti has been revoked."""
    from app.core.database import get_database
    db = get_database()
    return await db.revoked_tokens.find_one({"jti": jti}) is not None


async def revoke_all_sessions(user_id: str) -> None:
    """End every outstanding session of a user (access and refresh tokens).

    Increments ``token_version``; :func:`resolve_user` and the refresh endpoint
    refuse any token minted under an earlier one.
    """
    from bson import ObjectId
    from app.core.database import get_database
    await get_database().users.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"token_version": 1}},
    )
