"""
User data models.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from datetime import datetime


class UserBase(BaseModel):
    """Base user model."""
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserCreate(UserBase):
    """User creation model (Google OAuth)."""
    google_id: str


class UserCreateNative(BaseModel):
    """Native user creation model (admin only)."""
    email: EmailStr
    full_name: Optional[str] = None
    password: str
    roles: List[str] = ["knowledge_explorator"]


class UserUpdate(BaseModel):
    """User update model."""
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class PasswordSet(BaseModel):
    """Model for setting or changing a password."""
    password: str


class NativeLoginRequest(BaseModel):
    """Native email/password login request."""
    email: EmailStr
    password: str


class User(UserBase):
    """User model with database fields."""
    id: str = Field(validation_alias="_id")
    google_id: Optional[str] = None
    roles: List[str] = []
    capabilities: List[str] = []
    status: str = "active"  # active, inactive, suspended
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class UserInDB(User):
    """User model as stored in database (includes sensitive fields)."""
    password_hash: Optional[str] = None


class TokenResponse(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: User


class GoogleAuthRequest(BaseModel):
    """Google OAuth request model."""
    code: str
    redirect_uri: str


class RefreshTokenRequest(BaseModel):
    """Refresh token request model."""
    refresh_token: str
