"""
User management API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Any, Dict, List, Optional

from app.core.auth import get_current_user
from app.core.dependencies import require_admin
from app.models.user import (
    PasswordResetResponse,
    PasswordSet,
    User,
    UserCreateNative,
    UserStatusUpdate,
    UserUpdate,
)
from app.services.admin_chat_service import AdminChatService
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


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def set_my_password(
    body: PasswordSet,
    current_user: dict = Depends(get_current_user)
):
    """Set or change the password for the current user."""
    user_service = UserService()
    await user_service.set_password(current_user["id"], body.password)


@router.get("/me/chat-access-log")
async def get_my_chat_access_log(
    current_user: dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """List which staff members have accessed my chat history, and when."""
    admin_chat_service = AdminChatService()
    return await admin_chat_service.list_access_log(current_user["id"])


@router.post("/", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_native_user(
    body: UserCreateNative,
    current_user: dict = Depends(require_admin)
):
    """Create a native email/password user (admin only)."""
    user_service = UserService()
    user = await user_service.create_native_user(
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        roles=body.roles
    )
    return user


@router.get("/")
async def list_users(
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """List users (admin only), with optional email/name search and role/status filters."""
    user_service = UserService()
    users = await user_service.list_users(
        skip=skip, limit=limit, q=q, role=role, status_filter=status
    )
    total = await user_service.count_users(q=q, role=role, status_filter=status)
    return {"items": users, "total": total, "skip": skip, "limit": limit}


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
    if user_id == current_user["id"] and role == "administrator":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own administrator role"
        )
    user_service = UserService()
    user = await user_service.remove_role(user_id, role)
    return user


@router.patch("/{user_id}/status", response_model=User)
async def set_user_status(
    user_id: str,
    body: UserStatusUpdate,
    current_user: dict = Depends(require_admin)
):
    """Suspend or reactivate a user's account (admin only)."""
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own account status"
        )
    user_service = UserService()
    user = await user_service.set_status(user_id, body.status)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Permanently delete a user (admin only)."""
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account"
        )
    user_service = UserService()
    deleted = await user_service.delete_user(user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )


@router.post("/{user_id}/reset-password", response_model=PasswordResetResponse)
async def reset_user_password(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Generate and set a new password for a user, returned once (admin only)."""
    user_service = UserService()
    new_password = await user_service.admin_reset_password(user_id)
    if new_password is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return PasswordResetResponse(password=new_password)


async def _get_target_user_or_404(user_id: str) -> User:
    user_service = UserService()
    target = await user_service.get_user_by_id(user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return target


@router.get("/{user_id}/chat/sessions")
async def list_user_chat_sessions_as_admin(
    user_id: str,
    current_user: dict = Depends(require_admin)
) -> List[Dict[str, Any]]:
    """List a user's chat sessions (admin only). Fails if the user opted out."""
    target = await _get_target_user_or_404(user_id)
    admin_chat_service = AdminChatService()
    return await admin_chat_service.list_sessions_as_admin(current_user, target)


@router.get("/{user_id}/chat/sessions/{session_id}")
async def get_user_chat_session_as_admin(
    user_id: str,
    session_id: str,
    current_user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """Fetch one of a user's chat sessions with messages (admin only)."""
    target = await _get_target_user_or_404(user_id)
    admin_chat_service = AdminChatService()
    session = await admin_chat_service.get_session_as_admin(current_user, target, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    return session


@router.get("/{user_id}/chat-access-log")
async def get_user_chat_access_log(
    user_id: str,
    current_user: dict = Depends(require_admin)
) -> List[Dict[str, Any]]:
    """List past staff accesses to a user's chat history (admin only)."""
    await _get_target_user_or_404(user_id)
    admin_chat_service = AdminChatService()
    return await admin_chat_service.list_access_log(user_id)
