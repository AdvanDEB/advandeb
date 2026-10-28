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

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field

# `panel` carries the agreement statistics and the human consensus the paper
# reports. `contributor` is stored, attributed and creditable, but never pooled
# into panel statistics — a different measurement, not a lesser one.
Tier = Literal["panel", "contributor"]

RequestStatus = Literal["pending", "approved", "declined"]


# Display labels for the collection's categories. Labels only: WHICH categories
# exist is read from `stylized_facts` at request time — the source the queue's
# strata are built from — so the form cannot offer a different set from the
# one experts are judged on. A category missing here still appears, under a
# label derived from its slug.
CATEGORY_LABELS: Dict[str, str] = {
    "universal_laws_of_biological_organization": "Universal laws of biological organization",
    "ecological_physiological_proportions_and_relationships": "Ecological–physiological proportions",
    "temporal_characteristics_of_development_and_growth": "Development and growth over time",
    "reproductive_strategy": "Reproductive strategy",
    "metabolism_and_environment": "Metabolism and environment",
    "biological_experiments_and_data_patterns": "Experiments and data patterns",
    "dynamic_properties_and_equilibrium_states": "Dynamics and equilibrium states",
    "molecular_and_cellular_foundations": "Molecular and cellular foundations",
    "microbiological_and_parasitological_aspects": "Microbiology and parasitology",
    "thermoregulation_and_biophysical_constraints": "Thermoregulation and biophysics",
    "integrative_aspects_and_emergent_properties": "Integrative and emergent properties",
    "toxicology_and_ecotoxicology": "Toxicology and ecotoxicology",
    # Facts 1201-1262 — the evidence block. The signup form used to offer only
    # the twelve backbone categories above, so self-rated familiarity covered
    # none of the facts experts are currently asked to judge.
    "core_deb_rules": "Core DEB rules",
    "hypoxia_dissolved_oxygen": "Hypoxia and dissolved oxygen",
    "phytoplankton_chlorophyll": "Phytoplankton chlorophyll",
    "phytoplankton_eps": "Phytoplankton EPS",
    "phytoplankton_nc_ratio": "Phytoplankton N:C ratio",
}


def category_label(key: str) -> str:
    return CATEGORY_LABELS.get(key) or (key or "").replace("_", " ").capitalize()


class StylizedFactCategory(BaseModel):
    """One category of the collection, as offered for self-rating."""

    key: str
    label: str
    n_facts: int
    # Facts in this category are in the evidence block — what experts are
    # being asked to judge now.
    currently_assessed: bool = False


class CategoryList(BaseModel):
    categories: List[StylizedFactCategory] = []


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

    model_config = ConfigDict(populate_by_name=True)

    # Read from Mongo's `_id`, served as `id`. The list endpoint used to hand
    # back raw documents keyed `_id` while the admin view read `id`, so every
    # approval was posted to /requests/undefined/decide.
    id: str = Field(validation_alias=AliasChoices("_id", "id"))
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
    # The `authored_by` slugs matched by the same rule. Recorded on the user
    # at approval as `author_slugs`, which is what the queue's
    # conflict-of-interest exclusion compares against.
    matched_author_slugs: List[str] = []
    user_id: Optional[str] = None
    note: Optional[str] = None


class EnrolmentRequestList(BaseModel):
    requests: List[EnrolmentRequestRecord] = []


class EnrolmentSubmitted(BaseModel):
    """The public endpoint's only answer — the same whether or not the email
    is already known, so it cannot be used to enumerate who is enrolled."""
    status: Literal["pending"]


class EnrolmentDecision(BaseModel):
    """An administrator's ruling on one request."""

    approve: bool
    # Required when approving. Tier assignment is the scientific decision the
    # whole approval step exists for.
    tier: Optional[Tier] = None
    note: Optional[str] = Field(default=None, max_length=2000)


class EnrolmentDecisionResult(BaseModel):
    """What a decision returns to the administrator."""

    status: Literal["approved", "declined"]
    tier: Optional[Tier] = None
    user_id: Optional[str] = None
    matched_authored_sf_numbers: List[int] = []
    author_slugs: List[str] = []
    # Set only when approval created a new account. Returned once and stored
    # only as a hash: if the administrator's screen does not show it, the
    # person cannot sign in. The previous admin view discarded it.
    temp_password: Optional[str] = None
