"""
Common dependencies for API routes.
"""
from fastapi import Depends, HTTPException, status
from typing import List

from app.core.auth import get_current_user


async def require_role(required_roles: List[str]):
    """Dependency to require specific user roles."""
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
