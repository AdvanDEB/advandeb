"""
Enrolment — how someone becomes an elicitation participant.

Self-signup with administrator approval (advandeb_methods docs/10 section 5).
Chosen over invitation tokens deliberately: it scales to a symposium audience
without an administrator hand-issuing invitations, and the approval step keeps
**tier assignment** — which is the scientific decision, not an administrative
one — under control.

A request creates nothing until it is approved. A `pending` account can do
nothing at all.
"""
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field

# `panel` carries the agreement statistics and the human consensus the paper
# reports. `contributor` is stored, attributed and creditable, but never pooled
# into panel statistics — a different measurement, not a lesser one.
Tier = Literal["panel", "contributor"]

RequestStatus = Literal["pending", "approved", "declined"]


class EnrolmentRequest(BaseModel):
    """What a prospective participant submits. Public endpoint."""

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    affiliation: Optional[str] = Field(default=None, max_length=300)
    orcid: Optional[str] = Field(default=None, max_length=40)
    years_in_field: Optional[int] = Field(default=None, ge=0, le=80)
    deb_experience: Optional[str] = Field(default=None, max_length=2000)
    # category slug -> 1..5 self-rated familiarity
    category_familiarity: Dict[str, int] = {}
    # Consent for acknowledgement / authorship consideration, settled up front
    # rather than retrofitted (docs/10 section 8).
    consent: bool = False


class EnrolmentRequestRecord(BaseModel):
    """A stored request, as an administrator sees it."""

    id: str = Field(alias="_id")
    name: str
    email: EmailStr
    affiliation: Optional[str] = None
    orcid: Optional[str] = None
    years_in_field: Optional[int] = None
    deb_experience: Optional[str] = None
    category_familiarity: Dict[str, int] = {}
    consent: bool = False
    status: RequestStatus = "pending"
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    assigned_tier: Optional[Tier] = None
    # Facts this person authored, matched at approval by ORCID then name. Shown
    # to the administrator because it is the conflict the queue will exclude.
    matched_authored_sf_numbers: List[int] = []
    user_id: Optional[str] = None

    class Config:
        populate_by_name = True


class EnrolmentDecision(BaseModel):
    """An administrator's ruling on one request."""

    approve: bool
    # Required when approving. Tier assignment is the scientific decision the
    # whole approval step exists for.
    tier: Optional[Tier] = None
    note: Optional[str] = Field(default=None, max_length=2000)
