"""Enrolment over HTTP, against the payloads the client actually sends.

Both halves were broken end to end. The signup form sent `full_name` and
`consent_acknowledgement` to a model that requires `name` and `consent`, so
every request was a 422. The admin view posted `{decision: 'approve'}` to a
model that requires `{approve: true}`, to an id it read from a field the list
did not serve, and discarded the one-time password a new account is created
with. These tests pin the contract the generated types now describe.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import enrolment as routes
from app.core.dependencies import require_admin
from app.core.limiter import limiter
from app.models.enrolment import (
    EnrolmentDecisionResult, EnrolmentRequestRecord,
)

from tests.elicitation_support import fact, seed_facts

# Exactly what EnrolmentView builds (src/components/enrolment/request.ts).
CLIENT_PAYLOAD = {
    "name": "Tin Klanjšček", "email": "tin.test@example.org",
    "affiliation": "IRB", "orcid": None, "years_in_field": 20,
    "deb_experience": "fits DEB models routinely",
    "category_familiarity": {"core_deb_rules": 5}, "consent": True,
}

# The categories the payload rates must exist in the collection.
TIN_FACT = fact(1201, "core_deb_rules", authored_by=["tin_klanjscek"])


@pytest.fixture
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)


def _client(admin_id="admin-1"):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(routes.router, prefix="/api/enrolment")
    app.dependency_overrides[require_admin] = lambda: {
        "id": admin_id, "roles": ["administrator"]}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://test/api/enrolment")


async def _pending(c):
    r = await c.get("/requests", params={"status_filter": "pending"})
    assert r.status_code == 200, r.text
    return r.json()["requests"]


async def test_the_client_payload_is_accepted(scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT])
    async with _client() as c:
        r = await c.post("/request", json=CLIENT_PAYLOAD)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "pending"}
    doc = await scratch_db.enrolment_requests.find_one({})
    assert doc["name"] == "Tin Klanjšček" and doc["consent"] is True


async def test_the_old_client_payload_was_a_422(scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT])
    old = {**{k: v for k, v in CLIENT_PAYLOAD.items()
              if k not in ("name", "consent")},
           "full_name": "Tin Klanjšček", "consent_acknowledgement": True}
    async with _client() as c:
        r = await c.post("/request", json=old)
    assert r.status_code == 422
    assert await scratch_db.enrolment_requests.count_documents({}) == 0


async def test_pending_requests_are_served_with_id_and_the_conflict(
        scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT, fact(7)])
    async with _client() as c:
        await c.post("/request", json=CLIENT_PAYLOAD)
        reqs = await _pending(c)
    assert len(reqs) == 1
    rec = reqs[0]
    assert set(rec) == set(EnrolmentRequestRecord.model_fields)
    assert "_id" not in rec and rec["id"]
    assert rec["matched_authored_sf_numbers"] == [1201]
    assert rec["matched_author_slugs"] == ["tin_klanjscek"]


async def test_approval_creates_the_account_and_returns_its_password(
        scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT])
    async with _client() as c:
        await c.post("/request", json=CLIENT_PAYLOAD)
        rid = (await _pending(c))[0]["id"]
        r = await c.post(f"/requests/{rid}/decide",
                         json={"approve": True, "tier": "contributor",
                               "note": "workshop speaker"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == set(EnrolmentDecisionResult.model_fields)
        assert body["status"] == "approved" and body["tier"] == "contributor"
        # Shown once, stored only as a hash: the admin view must display it.
        assert body["temp_password"]
        assert body["author_slugs"] == ["tin_klanjscek"]
        assert await _pending(c) == []

    user = await scratch_db.users.find_one({"email": "tin.test@example.org"})
    assert user["tier"] == "contributor"
    assert user["roles"] == ["external_contributor"]
    # The link the queue's conflict-of-interest exclusion reads.
    assert user["author_slugs"] == ["tin_klanjscek"]
    assert user["authored_sf_numbers"] == [1201]
    assert "temp_password" not in user and user["password_hash"]


async def test_the_old_decision_payload_was_a_422(scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT])
    async with _client() as c:
        await c.post("/request", json=CLIENT_PAYLOAD)
        rid = (await _pending(c))[0]["id"]
        r = await c.post(f"/requests/{rid}/decide",
                         json={"decision": "approve", "tier": "panel"})
    assert r.status_code == 422
    assert await scratch_db.users.count_documents({}) == 0


async def test_decline_creates_nothing(scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT])
    async with _client() as c:
        await c.post("/request", json=CLIENT_PAYLOAD)
        rid = (await _pending(c))[0]["id"]
        r = await c.post(f"/requests/{rid}/decide",
                         json={"approve": False, "note": "not DEB"})
        assert r.status_code == 200
        assert r.json()["status"] == "declined"
        assert r.json()["temp_password"] is None
    assert await scratch_db.users.count_documents({}) == 0
    doc = await scratch_db.enrolment_requests.find_one({})
    assert doc["status"] == "declined"


async def test_approval_without_a_tier_is_refused(scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT])
    async with _client() as c:
        await c.post("/request", json=CLIENT_PAYLOAD)
        rid = (await _pending(c))[0]["id"]
        r = await c.post(f"/requests/{rid}/decide", json={"approve": True})
    assert r.status_code == 400 and "tier" in r.json()["detail"]
    assert await scratch_db.users.count_documents({}) == 0



# --------------------------------------------------------------------------- #
# Categories for self-rated familiarity
# --------------------------------------------------------------------------- #

EVIDENCE_BLOCK = ["core_deb_rules", "hypoxia_dissolved_oxygen",
                  "phytoplankton_chlorophyll", "phytoplankton_eps",
                  "phytoplankton_nc_ratio"]


async def _collection_with_evidence(db):
    from app.services.elicitation_service import ElicitationService
    from tests.elicitation_support import evidence_artefact

    block = [fact(1201 + i, cat) for i, cat in enumerate(EVIDENCE_BLOCK)]
    backbone = [fact(1, "reproductive_strategy"), fact(2, "toxicology_and_ecotoxicology"),
                fact(3, "toxicology_and_ecotoxicology")]
    await seed_facts(db, block + backbone)
    svc = ElicitationService()
    await svc.import_evidence_sets(evidence_artefact(block, n_passages=2))
    await svc.build_evidence_queue()


async def test_categories_come_from_the_collection(scratch_db, no_rate_limit):
    """The form offered a hand-written list of the twelve backbone categories
    and none of the evidence block's. It now offers what the collection holds,
    with what experts judge now marked and listed first."""
    from app.models.enrolment import CATEGORY_LABELS, CategoryList

    await _collection_with_evidence(scratch_db)
    async with _client() as c:
        r = await c.get("/categories")
    assert r.status_code == 200, r.text
    cats = CategoryList.model_validate(r.json()).categories
    by_key = {c.key: c for c in cats}
    assert set(by_key) == set(EVIDENCE_BLOCK) | {
        "reproductive_strategy", "toxicology_and_ecotoxicology"}
    for k in EVIDENCE_BLOCK:
        assert by_key[k].currently_assessed and by_key[k].n_facts == 1
        assert by_key[k].label == CATEGORY_LABELS[k]
    assert not by_key["toxicology_and_ecotoxicology"].currently_assessed
    assert by_key["toxicology_and_ecotoxicology"].n_facts == 2
    # Assessed first.
    flags = [c.currently_assessed for c in cats]
    assert flags == sorted(flags, reverse=True)


async def test_a_category_without_a_label_still_appears(scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [fact(1, "brand_new_area")])
    async with _client() as c:
        cats = (await c.get("/categories")).json()["categories"]
    assert cats == [{"key": "brand_new_area", "label": "Brand new area",
                     "n_facts": 1, "currently_assessed": False}]


async def test_evidence_block_categories_can_be_rated(scratch_db, no_rate_limit):
    await _collection_with_evidence(scratch_db)
    payload = {**CLIENT_PAYLOAD, "category_familiarity": {
        "core_deb_rules": 5, "hypoxia_dissolved_oxygen": 4,
        "phytoplankton_eps": 3, "reproductive_strategy": 2}}
    async with _client() as c:
        r = await c.post("/request", json=payload)
    assert r.status_code == 200, r.text
    doc = await scratch_db.enrolment_requests.find_one({})
    assert doc["category_familiarity"] == payload["category_familiarity"]


async def test_a_rating_for_a_category_the_collection_lacks_is_refused(
        scratch_db, no_rate_limit):
    await seed_facts(scratch_db, [TIN_FACT])
    payload = {**CLIENT_PAYLOAD, "category_familiarity": {
        "core_deb_rules": 5, "not_a_category": 3}}
    async with _client() as c:
        r = await c.post("/request", json=payload)
    assert r.status_code == 400 and "not_a_category" in r.json()["detail"]
    assert await scratch_db.enrolment_requests.count_documents({}) == 0
