"""
User management API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from app.core.auth import get_current_user
from app.core.dependencies import require_admin
from app.models.user import User, UserUpdate
from app.services.user_service import UserService


router = APIRouter()


@router.get("/me", response_model=User)
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """Get current user profile."""
    user_service = UserService()
    user = await user_service.get_user_by_id(current_user["id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.put("/me", response_model=User)
async def update_current_user(
    user_update: UserUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update current user profile."""
    user_service = UserService()
    user = await user_service.update_user(current_user["id"], user_update)
    return user


@router.get("/", response_model=List[User])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(require_admin)
):
    """List all users (admin only)."""
    user_service = UserService()
    users = await user_service.list_users(skip=skip, limit=limit)
    return users


@router.get("/{user_id}", response_model=User)
async def get_user(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Get user by ID (admin only)."""
    user_service = UserService()
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.post("/{user_id}/roles")
async def assign_role(
    user_id: str,
    role: str,
    current_user: dict = Depends(require_admin)
):
    """Assign role to user (admin only)."""
    user_service = UserService()
    user = await user_service.assign_role(user_id, role)
    return user


@router.delete("/{user_id}/roles/{role}")
async def remove_role(
    user_id: str,
    role: str,
    current_user: dict = Depends(require_admin)
):
    """Remove role from user (admin only)."""
    user_service = UserService()
    user = await user_service.remove_role(user_id, role)
    return user
