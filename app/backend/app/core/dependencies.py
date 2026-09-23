"""
Common dependencies for API routes.
"""
from fastapi import Depends, HTTPException, status
from typing import Callable, List

from app.core.auth import get_current_user


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


async def require_curator(current_user: dict = Depends(get_current_user)):
    """Dependency to require curator role or higher."""
    user_roles = current_user.get("roles", [])
    if not any(role in ["administrator", "knowledge_curator"] for role in user_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Curator access required"
        )
    return current_user


# --------------------------------------------------------------------------- #
# Capabilities                                                                 #
# --------------------------------------------------------------------------- #
#
# The user model has carried a ``capabilities: List[str]`` field since the
# beginning, initialised to ``[]``, with nothing granting or checking it
# (docs/SYSTEM-OVERVIEW.md §6). Annotation is the first feature that needs it:
# the DEB experts who do the annotating hold ``knowledge_explorator`` only, so
# gating on the curator role would lock out exactly the people the work depends
# on.

CAP_SF_ANNOTATOR = "sf_annotator"


def require_capability(capability: str) -> Callable:
    """Require a named capability, or a role that implies it.

    Administrators always pass. Curators pass for annotation capabilities,
    since the curator role already means "may contribute knowledge" — but an
    explorator with the capability granted passes too, which is the point.
    """
    async def capability_checker(current_user: dict = Depends(get_current_user)):
        roles = current_user.get("roles", []) or []
        caps = current_user.get("capabilities", []) or []
        if "administrator" in roles or capability in caps:
            return current_user
        if capability == CAP_SF_ANNOTATOR and "knowledge_curator" in roles:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires the '{capability}' capability",
        )
    return capability_checker


require_annotator = require_capability(CAP_SF_ANNOTATOR)
