"""
Common dependencies for API routes.
"""
from fastapi import Depends, Header, HTTPException, Query, Request, status
from typing import Callable, List, Optional

# ROLE_EXTERNAL_CONTRIBUTOR is defined in app.core.auth, which enforces it;
# enrolment_service imports it from here.
from app.core.auth import (
    ROLE_EXTERNAL_CONTRIBUTOR,
    bearer_or_query_token,
    get_current_user,
    resolve_ticket,
    resolve_user,
)

CURATOR_ROLES = ("administrator", "knowledge_curator")


def require_role(required_roles: List[str]) -> Callable:
    """Dependency factory to require specific user roles."""
    async def role_checker(current_user: dict = Depends(get_current_user)):
        user_roles = current_user.get("roles", [])
        if not any(role in required_roles for role in user_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


async def require_admin(current_user: dict = Depends(get_current_user)):
    """Dependency to require administrator role."""
    if "administrator" not in current_user.get("roles", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required"
        )
    return current_user


def is_curator(current_user: dict) -> bool:
    """Curator or administrator."""
    return any(role in CURATOR_ROLES for role in current_user.get("roles", []) or [])


async def require_curator(current_user: dict = Depends(get_current_user)):
    """Dependency to require curator role or higher."""
    if not is_curator(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Curator access required"
        )
    return current_user


async def get_current_user_sse(
    request: Request,
    ticket: Optional[str] = Query(default=None),
    token: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """``get_current_user`` for Server-Sent Event streams.

    EventSource cannot send custom headers, so its credential rides in the
    URL: a one-time ``?ticket=`` from POST /api/auth/ws-ticket (``?token=``
    is the deprecated form). A Bearer header is accepted for non-browser
    callers. Resolves through the same account checks as every other route.
    """
    if ticket:
        return await resolve_ticket(ticket, path=request.url.path)
    return await resolve_user(
        bearer_or_query_token(token, authorization), path=request.url.path)


async def require_curator_sse(current_user: dict = Depends(get_current_user_sse)):
    """``require_curator`` for Server-Sent Event streams."""
    return await require_curator(current_user)


# --------------------------------------------------------------------------- #
# Capabilities                                                                 #
# --------------------------------------------------------------------------- #
#
# The user model has carried a ``capabilities: List[str]`` field since the
# beginning, initialised to ``[]``, with nothing granting or checking it
# (docs/SYSTEM-OVERVIEW.md §6). Elicitation is the first feature that needs it:
# the DEB experts who provide the judgments hold ``knowledge_explorator`` only,
# so gating on the curator role would lock out exactly the people the work
# depends on.

CAP_SF_ELICITATION = "sf_elicitation"

# ROLE_EXTERNAL_CONTRIBUTOR (imported above) is the minimum-privilege role for
# external elicitation participants. What it may reach is enforced centrally,
# in app.core.auth.resolve_user, so that it holds for every route — including
# the ones that only ask for get_current_user.


def require_capability(capability: str) -> Callable:
    """Require a named capability, or a role that implies it.

    Administrators always pass. Curators pass for elicitation, since the
    curator role already means "may contribute knowledge" — but an explorator
    with the capability granted passes too, which is the point.
    """
    async def capability_checker(current_user: dict = Depends(get_current_user)):
        roles = current_user.get("roles", []) or []
        caps = current_user.get("capabilities", []) or []
        if "administrator" in roles or capability in caps:
            return current_user
        if capability == CAP_SF_ELICITATION and (
                "knowledge_curator" in roles
                or ROLE_EXTERNAL_CONTRIBUTOR in roles):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires the '{capability}' capability",
        )
    return capability_checker


require_elicitor = require_capability(CAP_SF_ELICITATION)
