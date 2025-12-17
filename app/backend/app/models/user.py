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
    """User creation model."""
    google_id: str


class UserUpdate(BaseModel):
    """User update model."""
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class User(UserBase):
    """User model with database fields."""
    id: str = Field(alias="_id")
    google_id: str
    roles: List[str] = []
    capabilities: List[str] = []
    status: str = "active"  # active, inactive, suspended
    created_at: datetime
    updated_at: datetime
    
    class Config:
        populate_by_name = True


class UserInDB(User):
    """User model as stored in database."""
    pass


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
