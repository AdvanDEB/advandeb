"""
User data models.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Dict, List, Optional
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
    chat_history_visible_to_admin: Optional[bool] = None


class PasswordSet(BaseModel):
    """Model for setting or changing a password."""
    password: str


class UserStatusUpdate(BaseModel):
    """Model for changing a user's account status (admin only)."""
    status: str


class PasswordResetResponse(BaseModel):
    """Response for an admin-triggered password reset."""
    password: str


class NativeLoginRequest(BaseModel):
    """Native email/password login request."""
    email: EmailStr
    password: str


class ExpertiseProfile(BaseModel):
    """Self-reported expertise, captured once at enrolment.

    Per-category familiarity is the operationally useful field
    (advandeb_methods docs/10 section 6): it lets reliability be reported
    against *stated* expertise, which answers "do people who say they know this
    area agree more?" — a question the paper can ask of both strata.
    """
    affiliation: Optional[str] = None
    orcid: Optional[str] = None
    years_in_field: Optional[int] = None
    deb_experience: Optional[str] = None
    # category slug -> 1-5
    category_familiarity: Dict[str, int] = {}
    consent_acknowledgement: bool = False


class Approval(BaseModel):
    """Who admitted this person, when, and at which tier.

    Recorded because the paper has to be able to describe how its panel was
    constituted (docs/10 section 5).
    """
    by: Optional[str] = None
    at: Optional[datetime] = None
    tier: Optional[str] = None


class User(UserBase):
    """User model with database fields."""
    id: str = Field(validation_alias="_id")
    google_id: Optional[str] = None
    roles: List[str] = []
    capabilities: List[str] = []
    status: str = "active"  # active, inactive, suspended

    # --- elicitation tiering (advandeb_methods docs/10) ---
    #
    # `panel`       invited DEB experts; their judgments carry the agreement
    #               statistics and the human consensus reported in the paper.
    # `contributor` approved self-signups; stored, attributed and creditable,
    #               but never pooled into panel statistics.
    #
    # None means the person is not an elicitation participant at all.
    tier: Optional[str] = None
    expertise_profile: Optional[ExpertiseProfile] = None
    approval: Optional[Approval] = None
    # Stylized facts this person authored, resolved at approval by ORCID then
    # name. Drives the conflict-of-interest exclusion in the queue: an
    # outsider's conflict is no less a conflict (docs/10 section 5.1).
    authored_sf_numbers: List[int] = []
    # The `authored_by` slugs this person answers to (e.g. "tin_klanjscek").
    # Stylized facts and queue items name their authors by slug, never by user
    # id, so this is the link the conflict-of-interest exclusion needs: without
    # it an author's own facts are compared against their ObjectId, never
    # match, and are served to them. Assigned by an administrator (see
    # scripts/map_author_slugs.py), or matched at enrolment approval.
    author_slugs: List[str] = []
    # Research-consent flag: whether AdvanDEB staff may review this user's
    # chat history. Defaults to opted-in, matching the existing blanket
    # consent given by current users; self-service opt-out via PUT /users/me.
    chat_history_visible_to_admin: bool = True
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
