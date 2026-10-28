"""The elicitation HTTP contract, end to end through the router.

What the client reads is what these tests read: the JSON the routes emit,
checked against the models the TypeScript types are generated from. The
calibration-status test is the round trip that would have caught the client
gating on `required` / `complete` / `passed`, which the server never sent.

Authentication is overridden, not exercised — role enforcement belongs to the
auth layer and has its own tests. What is checked here is that the elicitation
routes depend on `require_elicitor` (so an external contributor reaches them)
and what they return.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import elicitation as routes
from app.core.dependencies import require_admin, require_elicitor
from app.models.elicitation import CalibrationStatus, QueueItem

from tests.elicitation_support import (
    calibrate, calibration_set, collection, evidence_artefact, expert,
    seed_facts,
)

pytestmark = pytest.mark.asyncio


def _app(user):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/elicitation")
    app.dependency_overrides[require_elicitor] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    return app


def _client(user):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(user)),
                             base_url="http://test/api/elicitation")


async def _user(db, **kw):
    uid = await expert(db, **kw)
    return {"id": uid, "roles": ["external_contributor"], "capabilities": []}


async def test_calibration_status_round_trip(scratch_db):
    user = await _user(scratch_db)
    async with _client(user) as c:
        r = await c.get("/calibration/status")
        assert r.status_code == 200
        body = r.json()
        # Exactly the model's fields — the ones the generated TS type declares.
        assert set(body) == set(CalibrationStatus.model_fields)
        assert body == {"total": 0, "completed": 0, "correct": 0,
                        "done": False, "available": False}

        await calibration_set(scratch_db, 2)
        body = (await c.get("/calibration/status")).json()
        assert body["available"] and not body["done"] and body["total"] == 2

        # Work the set through the API the client uses.
        while (case := (await c.get("/calibration/next")).json()) is not None:
            fb = await c.post("/calibration/decide", json={
                "calibration_id": case["calibration_id"], "task": case["task"],
                "provenance_type": "published", "confidence": 3,
                "rationale": "r"})
            assert fb.status_code == 200, fb.text
            assert fb.json()["reference"]["provenance_type"] == "published"
        body = (await c.get("/calibration/status")).json()
        assert body == {"total": 2, "completed": 2, "correct": 2,
                        "done": True, "available": True}


async def test_uncalibrated_next_is_null_and_progress_says_why(scratch_db):
    await seed_facts(scratch_db, collection({"growth": 3}))
    await calibration_set(scratch_db, 1)
    user = await _user(scratch_db)
    async with _client(user) as c:
        await c.post("/queue/build")
        assert (await c.get("/next")).json() is None
        prog = (await c.get("/progress")).json()
        assert prog["calibration_required"] is True
        assert prog["rung"] == "pre-R0"


async def test_evidence_item_and_decision_over_http(scratch_db):
    facts = collection({"growth": 2})
    await seed_facts(scratch_db, facts)
    user = await _user(scratch_db)
    await calibrate(scratch_db, user["id"])
    async with _client(user) as c:
        assert (await c.post("/evidence/import",
                             json=evidence_artefact(facts, n_passages=3))
                ).json()["status"] == "imported"
        assert (await c.post("/queue/build-evidence")).json()["status"] == "built"

        item = (await c.get("/next")).json()
        assert set(item) == set(QueueItem.model_fields)
        assert item["task"] == "evidence"
        assert item["evidence_condition"] == "matched"
        assert len(item["passages"]) == 3

        decision = {
            "task": "evidence", "sf_number": item["sf_number"],
            "statement_sha256": item["statement_sha256"],
            "corpus_id": item["corpus_id"],
            "evidence_set_id": item["evidence_set_id"],
            "evidence_content_hash": item["evidence_content_hash"],
            "evidence_strength": 2, "consensus_direction": 2,
            "passage_judgments": {str(p["index"]): {"direction": "neutral"}
                                  for p in item["passages"]},
            "confidence": 3, "rationale": "r", "time_spent_s": 30,
        }
        # One passage short: 400, nothing stored.
        short = {**decision, "passage_judgments": dict(
            list(decision["passage_judgments"].items())[:-1])}
        r = await c.post("/decide", json=short)
        assert r.status_code == 400 and "every passage shown" in r.json()["detail"]

        r = await c.post("/decide", json=decision)
        assert r.status_code == 200, r.text
        assert set(r.json()) == {"status", "id", "round"}

        # Resubmitting the same item: it is no longer this expert's head.
        r = await c.post("/decide", json=decision)
        assert r.status_code == 409


async def test_decide_status_codes(scratch_db):
    facts = collection({"growth": 4})
    await seed_facts(scratch_db, facts)
    user = await _user(scratch_db)
    await calibrate(scratch_db, user["id"])
    async with _client(user) as c:
        await c.post("/queue/build")
        item = (await c.get("/next")).json()
        base = {"task": item["task"], "sf_number": item["sf_number"],
                "statement_sha256": item["statement_sha256"],
                "confidence": 3, "rationale": "r"}
        answer = {"provenance": {"provenance_type": "unknown"},
                  "scope": {"scope_verdict": "absent"},
                  "assessability": {"assessability": "assessable"}}[item["task"]]

        r = await c.post("/decide", json=base)   # no answer for its task
        assert r.status_code == 400
        r = await c.post("/decide", json={**base, **answer, "sf_number": 999999})
        assert r.status_code == 404
        later = await scratch_db.elicitation_queue.find_one(
            {"queue_position": item["queue_position"] + 3})
        crafted = {**base, "task": later["task"], "sf_number": later["sf_number"],
                   **{"provenance": {"provenance_type": "unknown"},
                      "scope": {"scope_verdict": "absent"},
                      "assessability": {"assessability": "assessable"}}[later["task"]]}
        r = await c.post("/decide", json=crafted)
        assert r.status_code == 409 and "head of the queue" in r.json()["detail"]
        r = await c.post("/decide", json={**base, **answer})
        assert r.status_code == 200


async def test_author_gets_403_over_http(scratch_db):
    from tests.elicitation_support import fact
    await seed_facts(scratch_db, [fact(1201, authored_by=["tin_klanjscek"])])
    tin = await _user(scratch_db, slugs=["tin_klanjscek"])
    await calibrate(scratch_db, tin["id"])
    async with _client(tin) as c:
        await c.post("/queue/build")
        assert (await c.get("/next")).json() is None
        q = await scratch_db.elicitation_queue.find_one({})
        f = await scratch_db.stylized_facts.find_one({})
        r = await c.post("/decide", json={
            "task": q["task"], "sf_number": 1201,
            "statement_sha256": f["statement_sha256"], "confidence": 3,
            "rationale": "r",
            **{"provenance": {"provenance_type": "unknown"},
               "scope": {"scope_verdict": "absent"},
               "assessability": {"assessability": "assessable"}}[q["task"]]})
        assert r.status_code == 403


async def test_events_endpoint_logs_and_exposure_lands_on_the_record(scratch_db):
    await seed_facts(scratch_db, collection({"growth": 3}))
    user = await _user(scratch_db)
    await calibrate(scratch_db, user["id"])
    async with _client(user) as c:
        await c.post("/queue/build")
        item = (await c.get("/next")).json()
        r = await c.post("/events", json={
            "event": "machine_verdict_opened", "sf_number": item["sf_number"],
            "task": item["task"], "corpus_id": None, "answered": False})
        assert r.status_code == 200 and r.json() == {"status": "logged"}
        answer = {"provenance": {"provenance_type": "unknown"},
                  "scope": {"scope_verdict": "absent"},
                  "assessability": {"assessability": "assessable"}}[item["task"]]
        await c.post("/decide", json={
            "task": item["task"], "sf_number": item["sf_number"],
            "statement_sha256": item["statement_sha256"], "confidence": 3,
            "rationale": "r", "machine_verdict_expanded": False, **answer})
    rec = await scratch_db.elicitations.find_one({})
    assert rec["machine_verdict_opened"] is True
    assert rec["machine_verdict_opened_before_answer"] is True


async def test_forced_rebuild_after_judgments_is_409(scratch_db):
    await seed_facts(scratch_db, collection({"growth": 3}))
    user = await _user(scratch_db)
    await calibrate(scratch_db, user["id"])
    async with _client(user) as c:
        await c.post("/queue/build")
        item = (await c.get("/next")).json()
        answer = {"provenance": {"provenance_type": "unknown"},
                  "scope": {"scope_verdict": "absent"},
                  "assessability": {"assessability": "assessable"}}[item["task"]]
        await c.post("/decide", json={
            "task": item["task"], "sf_number": item["sf_number"],
            "statement_sha256": item["statement_sha256"], "confidence": 3,
            "rationale": "r", **answer})
        r = await c.post("/queue/build", params={"force": True})
        assert r.status_code == 409


async def test_calibration_next_never_seeds_over_http(scratch_db):
    from tests.elicitation_support import fact
    await seed_facts(scratch_db, [fact(1201, provenance="published")])
    user = await _user(scratch_db)
    async with _client(user) as c:
        assert (await c.get("/calibration/next")).json() is None
        assert await scratch_db.elicitation_calibration.count_documents({}) == 0
        r = await c.post("/calibration/seed")
        assert r.json()["status"] == "built"
        assert (await c.get("/calibration/next")).json() is not None


async def test_guidelines_are_served(scratch_db):
    """/guidelines failed response validation (500) once the evidence task's
    sub-sections were added under a `TaskType` field."""
    user = await _user(scratch_db)
    async with _client(user) as c:
        r = await c.get("/guidelines")
        assert r.status_code == 200, r.text
        sections = {t["task"] for t in r.json()["tasks"]}
        assert {"evidence", "evidence_role", "evidence_strength",
                "consensus_direction"} <= sections


async def test_admin_stats_serve_what_the_dashboard_reads(scratch_db):
    """The admin view read comparison_total/complete, total_queue, completed,
    repeated_judgments and median_seconds_per_item — none of which were
    sent — and rendered `by_expert`, a list, as a mapping."""
    from app.models.elicitation import AdminStats

    await seed_facts(scratch_db, collection({"growth": 3}))
    user = await _user(scratch_db)
    await calibrate(scratch_db, user["id"])
    async with _client(user) as c:
        await c.post("/queue/build")
        item = (await c.get("/next")).json()
        answer = {"provenance": {"provenance_type": "unknown"},
                  "scope": {"scope_verdict": "absent"},
                  "assessability": {"assessability": "assessable"}}[item["task"]]
        await c.post("/decide", json={
            "task": item["task"], "sf_number": item["sf_number"],
            "statement_sha256": item["statement_sha256"], "confidence": 3,
            "rationale": "r", "time_spent_s": 40, **answer})
        r = await c.get("/stats/admin")
    assert r.status_code == 200, r.text
    s = r.json()
    assert set(s) == set(AdminStats.model_fields)
    assert s["total_queue"] == 9 and s["completed"] == 1
    assert s["comparison_total"] == 1          # position 0
    assert s["comparison_complete"] == 0       # needs the full panel
    assert s["median_seconds_per_item"] == 40
    assert isinstance(s["by_expert"], list) and s["by_expert"][0]["n"] == 1
    assert s["by_expert"][0]["calibration"]["done"] is True


async def test_experts_list_carries_tier_count_and_author_slugs(scratch_db):
    from app.models.elicitation import ExpertListEntry

    await seed_facts(scratch_db, collection({"growth": 3}))
    user = await _user(scratch_db, tier="panel", slugs=["tin_klanjscek"])
    await calibrate(scratch_db, user["id"])
    async with _client(user) as c:
        await c.post("/queue/build")
        item = (await c.get("/next")).json()
        answer = {"provenance": {"provenance_type": "unknown"},
                  "scope": {"scope_verdict": "absent"},
                  "assessability": {"assessability": "assessable"}}[item["task"]]
        await c.post("/decide", json={
            "task": item["task"], "sf_number": item["sf_number"],
            "statement_sha256": item["statement_sha256"], "confidence": 3,
            "rationale": "r", **answer})
        body = (await c.get("/experts")).json()
    row = next(u for u in body["users"] if u["id"] == user["id"])
    assert set(row) == set(ExpertListEntry.model_fields)
    assert row["tier"] == "panel" and row["n_elicitations"] == 1
    assert row["author_slugs"] == ["tin_klanjscek"] and row["can_elicit"]
