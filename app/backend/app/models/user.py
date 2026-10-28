"""
User data models.
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Dict, List, Optional
from datetime import datetime


# A new password must be long enough to resist guessing, and short enough for
# bcrypt, which hashes only the first 72 bytes and (from bcrypt 5) raises on
# longer input. The ceiling is in bytes, not characters: non-ASCII letters
# take two to four bytes each in UTF-8.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72

# Login accepts what it is given — the policy applies to passwords being set,
# not to existing ones — but a bound keeps absurd bodies away from bcrypt.
LOGIN_PASSWORD_MAX_LENGTH = 1024


def validate_new_password(value: str) -> str:
    """Apply the password policy to a password being set."""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes")
    return value


def normalize_email(value: str) -> str:
    """The stored and looked-up form of an email address."""
    return value.strip().lower()


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

    _check_password = field_validator("password")(validate_new_password)


class UserUpdate(BaseModel):
    """User update model."""
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    chat_history_visible_to_admin: Optional[bool] = None


class PasswordSet(BaseModel):
    """Model for setting or changing a password.

    ``current_password`` is required whenever the account already has one; it
    may be omitted only when setting a first password on an account that has
    none (one created through Google sign-in).
    """
    password: str
    current_password: Optional[str] = Field(default=None, max_length=LOGIN_PASSWORD_MAX_LENGTH)

    _check_password = field_validator("password")(validate_new_password)


class UserStatusUpdate(BaseModel):
    """Model for changing a user's account status (admin only)."""
    status: str


class PasswordResetResponse(BaseModel):
    """Response for an admin-triggered password reset."""
    password: str


class NativeLoginRequest(BaseModel):
    """Native email/password login request."""
    email: EmailStr
    password: str = Field(max_length=LOGIN_PASSWORD_MAX_LENGTH)


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
    # Research-consent flag: whether AdvanDEB staff may review this user's
    # chat history. Defaults to opted-in, matching the existing blanket
    # consent given by current users; self-service opt-out via PUT /users/me.
    chat_history_visible_to_admin: bool = True
    # Session generation, embedded in every token as ``ver``; bumped to end all
    # sessions (app.core.auth.revoke_all_sessions). Never serialised.
    token_version: int = Field(default=0, exclude=True)
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
    """Google OAuth request model.

    ``code_verifier`` is the PKCE secret whose S256 challenge the browser sent
    with the authorization request; Google refuses the exchange without it
    when a challenge was sent.
    """
    code: str
    redirect_uri: str
    code_verifier: Optional[str] = Field(default=None, min_length=43, max_length=128)


class RefreshTokenRequest(BaseModel):
    """Refresh token request model."""
    refresh_token: str
