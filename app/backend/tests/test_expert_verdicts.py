"""Aggregated expert verdicts next to each stylized fact.

Three layers:

* the pure rules — labels, majority, median, minimum n, who counts as a
  potential judge, what is open — with no database;
* the service against a scratch MongoDB (``scratch_db``; skipped without
  TEST_MONGODB_URI), seeded with judgment and queue records in the shape
  ``ElicitationService`` writes them;
* the routes, through the router, as the client reads them.

The withholding tests are the important ones for the methods paper: an expert
who may still be asked to judge a fact must not see the others' verdict on it.
"""
from __future__ import annotations

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.api.routes.kb import facts as facts_routes
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.expert_verdict import (
    ConsensusDistribution, ExpertVerdictBatch, ExpertVerdictGroup,
    ExpertVerdictSummary,
)
from app.services.elicitation_service import ElicitationService, _item_key
from app.services.expert_verdict_service import (
    MAX_BATCH, ExpertVerdictService, is_potential_judge, lower_median,
    majority, open_for_user, parse_sf_numbers, summarise_group,
)


# --------------------------------------------------------------------------- #
# Pure rules                                                                   #
# --------------------------------------------------------------------------- #

def _row(tier="panel", corpus="deb", c=(0, 0, 0), s=(0, 0, 0), n=None,
         n_experts=None):
    n = sum(c) if n is None else n
    return {"sf_number": 1, "corpus_id": corpus, "tier": tier, "n": n,
            "n_experts": n if n_experts is None else n_experts,
            "c1": c[0], "c2": c[1], "c3": c[2],
            "s1": s[0], "s2": s[1], "s3": s[2]}


def test_majority_reports_the_top_label_and_its_count():
    assert majority(ConsensusDistribution(supported=4, inconclusive=1)) == ("supported", 4)
    assert majority(ConsensusDistribution(against=2, inconclusive=1)) == ("against", 2)


def test_a_tie_is_reported_as_split_not_resolved():
    assert majority(ConsensusDistribution(supported=2, against=2)) == (None, 2)
    assert majority(ConsensusDistribution()) == (None, 0)


def test_median_is_a_point_on_the_scale_never_a_midpoint():
    assert lower_median({1: 0, 2: 1, 3: 2}) == 3
    # [1, 2, 3, 3]: the midpoint would be 2.5, which is an average of two
    # ordinal scores. The lower median is reported instead.
    assert lower_median({1: 1, 2: 1, 3: 2}) == 2
    assert lower_median({1: 2, 2: 0, 3: 2}) == 1
    assert lower_median({1: 0, 2: 0, 3: 0}) is None


def test_group_below_minimum_n_is_not_shown_at_all():
    assert summarise_group(_row(c=(0, 0, 2), s=(0, 0, 2)), 3) is None
    assert summarise_group(_row(c=(0, 0, 1), s=(0, 0, 1)), 3) is None
    # The same rule for contributors.
    assert summarise_group(_row(tier="contributor", c=(0, 1, 1), s=(1, 1, 0)), 3) is None


def test_group_at_minimum_n_reports_distributions_majority_and_median():
    g = summarise_group(_row(c=(0, 1, 3), s=(1, 1, 2), n_experts=4), 3)
    assert isinstance(g, ExpertVerdictGroup)
    assert (g.corpus_id, g.tier, g.n, g.n_experts) == ("deb", "panel", 4, 4)
    assert (g.majority_label, g.majority_n) == ("supported", 3)
    assert g.consensus.model_dump() == {"against": 0, "inconclusive": 1, "supported": 3}
    assert g.strength.model_dump() == {"weak": 1, "moderate": 1, "strong": 2}
    assert g.strength_median == 2
    # No mean anywhere in the payload.
    assert not any("mean" in k or "avg" in k for k in g.model_dump())


def test_group_with_an_unknown_tier_is_never_shown():
    assert summarise_group(_row(tier=None, c=(0, 0, 5), s=(0, 0, 5)), 3) is None
    assert summarise_group(_row(tier="unknown", c=(0, 0, 5), s=(0, 0, 5)), 3) is None


@pytest.mark.parametrize("user,tier,expected", [
    ({"roles": ["knowledge_explorator"], "capabilities": ["sf_elicitation"]}, None, True),
    ({"roles": ["external_contributor"], "capabilities": []}, None, True),
    ({"roles": ["knowledge_explorator"], "capabilities": []}, "panel", True),
    ({"roles": ["knowledge_explorator"], "capabilities": []}, "contributor", True),
    # Curators and administrators reach elicitation by role, but without a
    # tier the queue never serves them; they see verdicts.
    ({"roles": ["knowledge_curator"], "capabilities": []}, None, False),
    ({"roles": ["administrator"], "capabilities": []}, None, False),
    ({"roles": ["knowledge_explorator"], "capabilities": []}, None, False),
])
def test_potential_judge(user, tier, expected):
    assert is_potential_judge(user, tier) is expected


def _q(sf, corpus="deb", n_required=5):
    return {"sf_number": sf, "task": "evidence", "corpus_id": corpus,
            "n_required": n_required}


def _key(sf, corpus="deb"):
    return _item_key({"sf_number": sf, "task": "evidence", "corpus_id": corpus})


def test_open_for_user():
    queue = [_q(1), _q(2), _q(3), _q(4, "reproduction", 1)]
    panel = {_key(1): 4, _key(2): 5, _key(4, "reproduction"): 0}
    judged = {_key(3)}
    # 1: open, not judged → withheld. 2: panel requirement met → closed.
    # 3: open but already judged by this user. 4: open, not judged.
    assert open_for_user(queue, panel, judged) == {1, 4}


def test_open_item_on_either_corpus_withholds_the_whole_fact():
    queue = [_q(1, "deb", 5), _q(1, "reproduction", 1)]
    panel = {_key(1, "deb"): 2, _key(1, "reproduction"): 1}
    assert open_for_user(queue, panel, {_key(1, "reproduction")}) == {1}
    assert open_for_user(queue, panel, {_key(1, "deb")}) == set()


def test_parse_sf_numbers():
    assert parse_sf_numbers("3, 1,3,,2") == [3, 1, 2]
    assert parse_sf_numbers("") == []
    with pytest.raises(ValueError):
        parse_sf_numbers("1,two")
    with pytest.raises(ValueError):
        parse_sf_numbers(",".join(str(i) for i in range(MAX_BATCH + 1)))
    assert len(parse_sf_numbers(",".join(str(i) for i in range(MAX_BATCH)))) == MAX_BATCH


# --------------------------------------------------------------------------- #
# Service against a scratch database                                           #
# --------------------------------------------------------------------------- #

async def _user(db, roles=("knowledge_explorator",), capabilities=(), tier=None):
    doc = {"email": f"u-{ObjectId()}@example.org", "roles": list(roles),
           "capabilities": list(capabilities)}
    if tier is not None:
        doc["tier"] = tier
    uid = (await db.users.insert_one(doc)).inserted_id
    # The current_user dict routes receive: no tier on it.
    return {"id": str(uid), "roles": list(roles),
            "capabilities": list(capabilities)}


async def _judge(db, sf, corpus, tier, consensus, strength, expert_id=None,
                 version="1.0"):
    await db.elicitations.insert_one({
        "task": "evidence", "sf_number": sf, "corpus_id": corpus,
        "tier": tier, "expert_id": expert_id or str(ObjectId()),
        "consensus_direction": consensus, "evidence_strength": strength,
        "collection_version": version, "confidence": 3, "rationale": "r",
    })


async def _queue(db, sf, corpus="deb", n_required=None, pos=0):
    await db.elicitation_queue.insert_one({
        "collection_version": "1.0", "priority": 0, "queue_position": pos,
        "task": "evidence", "sf_number": sf, "corpus_id": corpus,
        "n_required": n_required if n_required is not None
        else (5 if corpus == "deb" else 1),
    })


async def _seed_fact_one(db):
    """Fact 1: four panel experts on DEB (3 supported, 1 inconclusive), three
    contributors on DEB (2 against, 1 supported), one panel expert on
    reproduction. Fact 2: two panel experts on DEB."""
    for c, s in [(3, 3), (3, 3), (3, 2), (2, 1)]:
        await _judge(db, 1, "deb", "panel", c, s)
    for c, s in [(1, 1), (1, 2), (3, 2)]:
        await _judge(db, 1, "deb", "contributor", c, s)
    await _judge(db, 1, "reproduction", "panel", 3, 3)
    for c, s in [(3, 3), (3, 3)]:
        await _judge(db, 2, "deb", "panel", c, s)


async def test_aggregates_per_corpus_and_tier_and_suppresses_small_groups(scratch_db):
    await _seed_fact_one(scratch_db)
    curator = await _user(scratch_db, roles=("knowledge_curator",))
    out = await ExpertVerdictService().summaries([1, 2, 3], curator)

    assert set(out) == {1, 2, 3}
    one = out[1]
    assert one.withheld is None
    # Panel first, contributors separate; reproduction (n=1) left out.
    assert [(g.corpus_id, g.tier, g.n) for g in one.groups] == [
        ("deb", "panel", 4), ("deb", "contributor", 3)]
    panel, contrib = one.groups
    assert (panel.majority_label, panel.majority_n, panel.n_experts) == ("supported", 3, 4)
    assert panel.consensus.model_dump() == {"against": 0, "inconclusive": 1, "supported": 3}
    assert panel.strength.model_dump() == {"weak": 1, "moderate": 1, "strong": 2}
    assert panel.strength_median == 2
    # Contributor judgments never reach the panel's numbers, and vice versa.
    assert (contrib.majority_label, contrib.majority_n) == ("against", 2)
    assert contrib.consensus.model_dump() == {"against": 2, "inconclusive": 0, "supported": 1}

    # Two panel judgments: nothing at all, not "2 of 2".
    assert out[2].groups == [] and out[2].withheld is None
    assert out[3].groups == []


async def test_minimum_n_is_a_setting(scratch_db, monkeypatch):
    await _seed_fact_one(scratch_db)
    curator = await _user(scratch_db, roles=("knowledge_curator",))
    monkeypatch.setattr(settings, "EXPERT_VERDICT_MIN_N", 4)
    out = await ExpertVerdictService().summaries([1, 2], curator)
    assert [(g.tier, g.n) for g in out[1].groups] == [("panel", 4)]
    monkeypatch.setattr(settings, "EXPERT_VERDICT_MIN_N", 1)
    out = await ExpertVerdictService().summaries([1, 2], curator)
    assert [(g.corpus_id, g.tier) for g in out[1].groups] == [
        ("deb", "panel"), ("deb", "contributor"), ("reproduction", "panel")]
    assert [g.n for g in out[2].groups] == [2]


async def test_aggregates_by_stamped_tier_not_current_tier(scratch_db):
    # An expert promoted to panel after judging as a contributor: their record
    # stays a contributor record.
    promoted = await _user(scratch_db, tier="panel")
    await _judge(scratch_db, 7, "deb", "contributor", 3, 3, expert_id=promoted["id"])
    for _ in range(3):
        await _judge(scratch_db, 7, "deb", "panel", 1, 1)
    curator = await _user(scratch_db, roles=("knowledge_curator",))
    out = await ExpertVerdictService().summaries([7], curator)
    assert [(g.tier, g.n, g.majority_label) for g in out[7].groups] == [
        ("panel", 3, "against")]


async def test_other_versions_and_unscored_records_are_not_counted(scratch_db):
    for _ in range(3):
        await _judge(scratch_db, 5, "deb", "panel", 3, 3, version="0.9")
    await _judge(scratch_db, 5, "deb", "panel", 3, 3)
    await scratch_db.elicitations.insert_one({
        "task": "evidence", "sf_number": 5, "corpus_id": "deb", "tier": "panel",
        "expert_id": "x", "collection_version": "1.0",
        "consensus_direction": None, "evidence_strength": None})
    # A fact-level task is not a verdict on the fact.
    await scratch_db.elicitations.insert_one({
        "task": "provenance", "sf_number": 5, "corpus_id": None, "tier": "panel",
        "expert_id": "y", "collection_version": "1.0",
        "provenance_type": "published"})
    curator = await _user(scratch_db, roles=("knowledge_curator",))
    assert settings.EXPERT_VERDICT_MIN_N == 3
    # Five evidence records, one of them scored, in this version: below n.
    out = await ExpertVerdictService().summaries([5], curator)
    assert out[5].groups == []


async def test_withheld_from_a_potential_judge_with_an_open_item(scratch_db):
    await _seed_fact_one(scratch_db)
    await _queue(scratch_db, 1, "deb")            # 4 of 5 panel → open
    await _queue(scratch_db, 1, "reproduction")   # 1 of 1 → closed
    await _queue(scratch_db, 2, "deb", pos=1)     # 2 of 5 → open

    panel_expert = await _user(scratch_db, tier="panel")
    with_capability = await _user(scratch_db, capabilities=("sf_elicitation",))
    external = await _user(scratch_db, roles=("external_contributor",))
    curator = await _user(scratch_db, roles=("knowledge_curator",))
    admin = await _user(scratch_db, roles=("administrator",))
    explorator = await _user(scratch_db)

    svc = ExpertVerdictService()
    for judge in (panel_expert, with_capability, external):
        out = await svc.summaries([1, 2], judge)
        assert out[1].withheld == "open_for_you" and out[1].groups == []
        assert out[2].withheld == "open_for_you"
    for viewer in (curator, admin, explorator):
        out = await svc.summaries([1, 2], viewer)
        assert out[1].withheld is None and len(out[1].groups) == 2


async def test_judging_the_open_item_or_its_closing_releases_the_verdict(scratch_db):
    await _seed_fact_one(scratch_db)
    await _queue(scratch_db, 1, "deb")
    await _queue(scratch_db, 1, "reproduction")
    svc = ExpertVerdictService()

    # A contributor who already judged fact 1 on DEB is no longer asked.
    contributor = await _user(scratch_db, tier="contributor")
    await _judge(scratch_db, 1, "deb", "contributor", 2, 2,
                 expert_id=contributor["id"])
    out = await svc.summaries([1], contributor)
    assert out[1].withheld is None
    assert [(g.tier, g.n) for g in out[1].groups] == [("panel", 4), ("contributor", 4)]

    # Contributor judgments never close a panel item.
    other = await _user(scratch_db, tier="panel")
    assert (await svc.summaries([1], other))[1].withheld == "open_for_you"

    # A fifth panel judgment meets n_required: the item closes for everyone.
    await _judge(scratch_db, 1, "deb", "panel", 3, 3)
    out = await svc.summaries([1], other)
    assert out[1].withheld is None
    assert out[1].groups[0].tier == "panel" and out[1].groups[0].n == 5


async def test_open_agrees_with_the_elicitation_queue(scratch_db):
    """Cross-check against ElicitationService's own panel counts: a potential
    judge with no judgments is withheld exactly the facts the queue still has
    open, by the queue's definition."""
    await _seed_fact_one(scratch_db)
    for i, (sf, corpus) in enumerate([(1, "deb"), (1, "reproduction"),
                                      (2, "deb"), (9, "reproduction")]):
        await _queue(scratch_db, sf, corpus, pos=i)
    counts = await ElicitationService()._panel_counts()
    queue = [q async for q in scratch_db.elicitation_queue.find({})]
    expected = {q["sf_number"] for q in queue
                if counts.get(_item_key(q), 0) < int(q.get("n_required", 1))}
    judge = await _user(scratch_db, tier="panel")
    out = await ExpertVerdictService().summaries([1, 2, 9, 10], judge)
    assert {n for n, s in out.items() if s.withheld} == expected == {1, 2, 9}


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #

def _client(user):
    app = FastAPI()
    app.include_router(facts_routes.stylized_router,
                       prefix="/api/kb/stylized-facts")
    app.dependency_overrides[get_current_user] = lambda: user
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://test/api/kb/stylized-facts")


async def test_batch_endpoint_shape(scratch_db):
    await _seed_fact_one(scratch_db)
    curator = await _user(scratch_db, roles=("knowledge_curator",))
    async with _client(curator) as c:
        r = await c.get("/expert-verdicts", params={"sf_numbers": "1,2,1"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == set(ExpertVerdictBatch.model_fields)
        assert body["min_n"] == 3
        assert set(body["verdicts"]) == {"1", "2"}
        one = body["verdicts"]["1"]
        assert set(one) == set(ExpertVerdictSummary.model_fields)
        assert one["withheld"] is None
        assert set(one["groups"][0]) == set(ExpertVerdictGroup.model_fields)
        assert one["groups"][0] == {
            "corpus_id": "deb", "tier": "panel", "n": 4, "n_experts": 4,
            "majority_label": "supported", "majority_n": 3,
            "consensus": {"against": 0, "inconclusive": 1, "supported": 3},
            "strength": {"weak": 1, "moderate": 1, "strong": 2},
            "strength_median": 2,
        }
        assert body["verdicts"]["2"] == {"sf_number": 2, "withheld": None,
                                         "groups": []}

        r = await c.get("/1/expert-verdict")
        assert r.status_code == 200
        assert r.json() == one


async def test_batch_endpoint_withholds_for_a_potential_judge(scratch_db):
    await _seed_fact_one(scratch_db)
    await _queue(scratch_db, 1, "deb")
    judge = await _user(scratch_db, capabilities=("sf_elicitation",))
    async with _client(judge) as c:
        body = (await c.get("/expert-verdicts", params={"sf_numbers": "1,2"})).json()
        assert body["verdicts"]["1"] == {"sf_number": 1,
                                         "withheld": "open_for_you", "groups": []}
        # Fact 2 has no queue item here, so it is not withheld (and too small
        # to show anyway).
        assert body["verdicts"]["2"]["withheld"] is None
        assert (await c.get("/1/expert-verdict")).json()["withheld"] == "open_for_you"


# Without a database: argument handling, through the full app and the real
# authentication path (in-memory Motor stand-in, see conftest).

def test_batch_endpoint_rejects_bad_lists(client, personas, auth_header):
    h = auth_header(personas["explorator"])
    base = "/api/kb/stylized-facts/expert-verdicts"
    assert client.get(f"{base}?sf_numbers=1,x", headers=h).status_code == 422
    too_many = ",".join(str(i) for i in range(MAX_BATCH + 1))
    assert client.get(f"{base}?sf_numbers={too_many}", headers=h).status_code == 422
    assert client.get(f"{base}?sf_numbers=1", headers={}).status_code == 401


def test_batch_endpoint_is_not_shadowed_and_answers_every_number(client, personas, auth_header):
    h = auth_header(personas["explorator"])
    r = client.get("/api/kb/stylized-facts/expert-verdicts?sf_numbers=4,5", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"min_n": 3, "verdicts": {
        "4": {"sf_number": 4, "withheld": None, "groups": []},
        "5": {"sf_number": 5, "withheld": None, "groups": []}}}
    r = client.get("/api/kb/stylized-facts/expert-verdicts", headers=h)
    assert r.status_code == 200 and r.json() == {"min_n": 3, "verdicts": {}}
