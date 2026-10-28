"""ElicitationService against a scratch database.

Grouped by the defect or rule each block pins down. Every rule here was either
broken in production or stated in the protocol and enforced nowhere:

* conflict of interest — authors were served their own facts (slug vs id);
* head of queue — /decide accepted any item, so the no-selection rule was
  decoration;
* the panel requirement — contributors must never decrement it;
* tier — stamped at write time, unknown fails toward contributor;
* the evidence task — every passage shown judged, the hash matched;
* anchoring — exposure derived from logged events, not the state at submit;
* progress and stats — keyed by corpus, so DEB and reproduction never merge;
* the claims ladder — the doc's thresholds, counted over the doc's basis;
* calibration — no seeding from a GET, an empty set is not a passed one.
"""
from __future__ import annotations

import pytest
from pymongo.errors import DuplicateKeyError

from app.models.elicitation import (
    CalibrationDecision, ElicitationEvent, PassageJudgment,
)
from app.services import elicitation_service as es
from app.services.elicitation_service import ElicitationService

from tests.elicitation_support import (
    calibrate, calibration_set, collection, decision_for, evidence_artefact,
    expert, fact, seed_facts,
)

pytestmark = pytest.mark.asyncio


async def _fact_level(db, facts):
    await seed_facts(db, facts)
    await ElicitationService().build_queue()


async def _with_evidence(db, facts, n_passages=4, fact_level=False):
    await seed_facts(db, facts)
    svc = ElicitationService()
    await svc.import_evidence_sets(evidence_artefact(facts, n_passages=n_passages))
    await svc.build_evidence_queue()
    if fact_level:
        await svc.build_queue()
    return svc


async def _drain(svc, expert_id, limit=10_000):
    """Everything an expert is served, judging each as it comes."""
    seen = []
    for _ in range(limit):
        item = await svc.next_item(expert_id)
        if item is None:
            return seen
        seen.append(item)
        res = await svc.submit(decision_for(item), expert_id)
        assert res["status"] == "recorded", res
    raise AssertionError("queue did not drain")


# --------------------------------------------------------------------------- #
# Calibration gate and calibration contract
# --------------------------------------------------------------------------- #

async def test_uncalibrated_expert_is_served_nothing_and_cannot_submit(scratch_db):
    await _fact_level(scratch_db, collection({"growth": 5}))
    await calibration_set(scratch_db, 2)
    e = await expert(scratch_db)
    svc = ElicitationService()
    assert await svc.next_item(e) is None
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    assert item is not None

    other = await expert(scratch_db, name="uncalibrated")
    res = await svc.submit(decision_for(item), other)
    assert res["status"] == "error" and res["code"] == 403
    assert "calibration" in res["detail"]


async def test_empty_calibration_set_is_not_a_passed_one(scratch_db):
    e = await expert(scratch_db)
    st = await ElicitationService().calibration_status(e)
    assert st == {"total": 0, "completed": 0, "correct": 0, "done": False,
                  "available": False}


async def test_calibration_next_does_not_seed(scratch_db):
    """A GET used to seed the calibration set. Seeding is an admin action."""
    await seed_facts(scratch_db, [fact(1201, provenance="published"),
                                  fact(1237, provenance="new")])
    e = await expert(scratch_db)
    svc = ElicitationService()
    assert await svc.calibration_next(e) is None
    assert await scratch_db.elicitation_calibration.count_documents({}) == 0
    assert (await svc.seed_calibration())["status"] == "built"
    assert (await svc.calibration_next(e)) is not None


async def test_calibration_round_trip(scratch_db):
    await seed_facts(scratch_db, [fact(1201, provenance="published"),
                                  fact(1237, provenance="new")])
    svc = ElicitationService()
    await svc.seed_calibration()
    e = await expert(scratch_db)
    st = await svc.calibration_status(e)
    assert st["available"] and not st["done"] and st["total"] == 2

    answers = {"published": True, "new": False}
    while (case := await svc.calibration_next(e)) is not None:
        fb = await svc.calibration_submit(CalibrationDecision(
            calibration_id=case["calibration_id"], task=case["task"],
            provenance_type="published", confidence=4, rationale="r"), e)
        ref = fb["reference"]["provenance_type"]
        assert fb["correct"] is answers[ref]
    st = await svc.calibration_status(e)
    assert st == {"total": 2, "completed": 2, "correct": 1, "done": True,
                  "available": True}


async def test_stale_calibration_results_do_not_count(scratch_db):
    e = await expert(scratch_db)
    await calibration_set(scratch_db, 2)
    await scratch_db.elicitation_calibration_results.insert_many([
        {"expert_id": e, "calibration_id": "cal_removed_a", "correct": True},
        {"expert_id": e, "calibration_id": "cal_removed_b", "correct": True}])
    st = await ElicitationService().calibration_status(e)
    assert st["completed"] == 0 and not st["done"]


# --------------------------------------------------------------------------- #
# Conflict of interest
# --------------------------------------------------------------------------- #

async def test_author_slug_excludes_own_facts_from_every_block(scratch_db):
    """Queue items carry slugs. Comparing them with user ids matched nothing,
    so every author was served their own facts."""
    facts = [fact(n, authored_by=["tin_klanjscek"]) for n in (1201, 1202)] + \
            [fact(n, authored_by=["advandeb_workshop_2025"]) for n in (1237, 1238)] + \
            [fact(n) for n in (1, 2)]
    svc = await _with_evidence(scratch_db, facts, n_passages=2, fact_level=True)
    tin = await expert(scratch_db, slugs=["tin_klanjscek"], name="tin")
    await calibrate(scratch_db, tin)
    served = await _drain(svc, tin)
    assert served
    assert not {i.sf_number for i in served} & {1201, 1202}
    assert {i.sf_number for i in served} >= {1237, 1238, 1, 2}


async def test_group_slug_excludes_every_fact_of_the_group(scratch_db):
    facts = [fact(n, authored_by=["advandeb_workshop_2025"]) for n in (1237, 1238)] + \
            [fact(3)]
    svc = await _with_evidence(scratch_db, facts, n_passages=2, fact_level=True)
    w = await expert(scratch_db, slugs=["advandeb_workshop_2025"])
    await calibrate(scratch_db, w)
    assert {i.sf_number for i in await _drain(svc, w)} == {3}


async def test_authored_sf_numbers_still_excludes(scratch_db):
    """The enrolment-approval source of authorship keeps working."""
    await _fact_level(scratch_db, [fact(1), fact(2)])
    e = await expert(scratch_db, authored=[1])
    await calibrate(scratch_db, e)
    svc = ElicitationService()
    assert {i.sf_number for i in await _drain(svc, e)} == {2}


async def test_author_cannot_submit_own_fact_even_crafted(scratch_db):
    svc = await _with_evidence(scratch_db, [fact(1201, authored_by=["tin_klanjscek"]),
                                            fact(5)], n_passages=2)
    other = await expert(scratch_db, name="other")
    tin = await expert(scratch_db, slugs=["tin_klanjscek"], name="tin")
    await calibrate(scratch_db, other, tin)
    item = await svc.next_item(other)
    while item.sf_number != 1201:       # served to a non-author, in order
        await svc.submit(decision_for(item), other)
        item = await svc.next_item(other)
    res = await svc.submit(decision_for(item), tin)
    assert res["code"] == 403 and "conflict of interest" in res["detail"]


async def test_author_excluded_is_recorded(scratch_db):
    svc = await _with_evidence(scratch_db, [fact(1201, authored_by=["tin_klanjscek"])],
                               n_passages=2)
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    await svc.submit(decision_for(item), e)
    rec = await scratch_db.elicitations.find_one({})
    assert rec["author_excluded"] is True


# --------------------------------------------------------------------------- #
# Head of queue — no self-selection
# --------------------------------------------------------------------------- #

async def test_only_the_head_of_the_queue_can_be_submitted(scratch_db):
    await _fact_level(scratch_db, collection({"growth": 6, "feeding": 6}))
    svc = ElicitationService()
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    head = await svc.next_item(e)
    later = await scratch_db.elicitation_queue.find_one(
        {"queue_position": head.queue_position + 7})
    crafted = decision_for(head, sf_number=later["sf_number"], task=later["task"])
    # Re-fill the task field for the crafted task.
    crafted = crafted.model_copy(update={
        "provenance_type": "unknown" if later["task"] == "provenance" else None,
        "scope_verdict": "absent" if later["task"] == "scope" else None,
        "assessability": "assessable" if later["task"] == "assessability" else None,
    })
    res = await svc.submit(crafted, e)
    assert res["code"] == 409 and "head of the queue" in res["detail"]
    assert await scratch_db.elicitations.count_documents({}) == 0

    ok = await svc.submit(decision_for(head), e)
    assert ok["status"] == "recorded"


async def test_items_whose_panel_requirement_is_met_are_refused(scratch_db):
    """Two panel experts load the same single-judgment item; the first to
    submit completes it, and the second is told the queue moved on."""
    await _fact_level(scratch_db, collection({"growth": 6}))
    svc = ElicitationService()
    a = await expert(scratch_db, name="a")
    b = await expert(scratch_db, name="b")
    await calibrate(scratch_db, a, b)
    # Walk past position 0 (a comparison item, n_required 5) to a single one.
    while True:
        item_a = await svc.next_item(a)
        if item_a.n_required == 1:
            break
        await svc.submit(decision_for(item_a), a)
    item_b = await svc.next_item(b)
    while item_b.queue_position != item_a.queue_position:
        await svc.submit(decision_for(item_b), b)
        item_b = await svc.next_item(b)

    assert (await svc.submit(decision_for(item_a), a))["status"] == "recorded"
    res = await svc.submit(decision_for(item_b), b)
    assert res["code"] == 409 and "already met" in res["detail"]


async def test_already_judged_is_refused(scratch_db):
    await _fact_level(scratch_db, collection({"growth": 3}))
    svc = ElicitationService()
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    assert (await svc.submit(decision_for(item), e))["status"] == "recorded"
    res = await svc.submit(decision_for(item), e)
    assert res["code"] == 409 and res["detail"] == "already judged by you"


async def test_unique_index_prevents_duplicates(scratch_db):
    """The last line of defence, below every check above it."""
    await _fact_level(scratch_db, collection({"growth": 3}))
    svc = ElicitationService()
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    await svc.submit(decision_for(item), e)
    rec = await scratch_db.elicitations.find_one({})
    rec.pop("_id")
    with pytest.raises(DuplicateKeyError):
        await scratch_db.elicitations.insert_one(rec)
    # ...but the same fact on another corpus is a different item.
    rec["corpus_id"] = "reproduction"
    await scratch_db.elicitations.insert_one(rec)


async def test_statement_hash_must_match(scratch_db):
    await _fact_level(scratch_db, collection({"growth": 3}))
    svc = ElicitationService()
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    res = await svc.submit(decision_for(item, statement_sha256="0" * 64), e)
    assert res["code"] == 409 and "statement_sha256" in res["detail"]


# --------------------------------------------------------------------------- #
# The panel requirement and tier
# --------------------------------------------------------------------------- #

async def test_contributor_never_decrements_n_required(scratch_db):
    await _fact_level(scratch_db, collection({"growth": 3}))
    svc = ElicitationService()
    contributors = [await expert(scratch_db, tier="contributor", name=f"c{i}")
                    for i in range(es.HUMAN_PANEL_SIZE)]
    panel = await expert(scratch_db, tier="panel", name="p")
    await calibrate(scratch_db, panel, *contributors)
    head = await svc.next_item(panel)
    assert head.queue_position == 0 and head.n_required == es.HUMAN_PANEL_SIZE
    for c in contributors:
        item = await svc.next_item(c)
        assert item.queue_position == 0
        assert (await svc.submit(decision_for(item), c))["status"] == "recorded"
    # Five contributor judgments later, the panel still owes all five.
    again = await svc.next_item(panel)
    assert again.queue_position == 0
    stats = await svc.admin_stats()
    assert stats["by_tier"] == {"contributor": es.HUMAN_PANEL_SIZE}


async def test_panel_judgments_do_satisfy_n_required(scratch_db):
    await _fact_level(scratch_db, collection({"growth": 3}))
    svc = ElicitationService()
    panel = [await expert(scratch_db, name=f"p{i}")
             for i in range(es.HUMAN_PANEL_SIZE + 1)]
    await calibrate(scratch_db, *panel)
    for p in panel[:-1]:
        item = await svc.next_item(p)
        assert item.queue_position == 0
        await svc.submit(decision_for(item), p)
    assert (await svc.next_item(panel[-1])).queue_position != 0


async def test_tier_is_stamped_at_write_time(scratch_db):
    await _fact_level(scratch_db, collection({"growth": 6}))
    svc = ElicitationService()
    e = await expert(scratch_db, tier="contributor")
    await calibrate(scratch_db, e)
    await svc.submit(decision_for(await svc.next_item(e)), e)
    await scratch_db.users.update_one({}, {"$set": {"tier": "panel"}})
    from bson import ObjectId
    await scratch_db.users.update_one({"_id": ObjectId(e)},
                                      {"$set": {"tier": "panel"}})
    await svc.submit(decision_for(await svc.next_item(e)), e)
    tiers = [r["tier"] async for r in scratch_db.elicitations.find().sort("created_at", 1)]
    assert tiers == ["contributor", "panel"]   # promotion moved nothing back


@pytest.mark.parametrize("tier", [None, "", "gold", "Panel"])
async def test_unknown_tier_fails_toward_contributor(scratch_db, tier):
    e = await expert(scratch_db, tier=tier)
    assert await ElicitationService().tier_of(e) == "contributor"


async def test_missing_user_fails_toward_contributor(scratch_db):
    from bson import ObjectId
    assert await ElicitationService().tier_of(str(ObjectId())) == "contributor"


# --------------------------------------------------------------------------- #
# The evidence task
# --------------------------------------------------------------------------- #

async def test_evidence_item_is_served_matched_with_its_passages(scratch_db):
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=6)
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    assert item.task == "evidence"
    assert item.evidence_condition == "matched"
    assert [p.index for p in item.passages] == list(range(6))
    assert item.n_passages_total == 6
    assert item.evidence_content_hash and item.evidence_set_id


async def test_fact_level_item_is_served_under_expertise(scratch_db):
    await _fact_level(scratch_db, [fact(1)])
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await ElicitationService().next_item(e)
    assert item.evidence_condition == "expertise" and item.passages == []


async def test_complete_evidence_decision_is_recorded_as_matched(scratch_db):
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=5)
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    res = await svc.submit(decision_for(item), e)
    assert res["status"] == "recorded"
    rec = await scratch_db.elicitations.find_one({})
    assert rec["evidence_condition"] == "matched"
    assert set(rec["passage_judgments"]) == {str(i) for i in range(5)}
    assert rec["corpus_id"] == item.corpus_id


async def _evidence_item(db, n_passages=5):
    svc = await _with_evidence(db, [fact(1)], n_passages=n_passages)
    e = await expert(db)
    await calibrate(db, e)
    return svc, e, await svc.next_item(e)


async def test_every_shown_passage_needs_a_judgment(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    d = decision_for(item)
    partial = dict(d.passage_judgments)
    partial.pop("3")
    res = await svc.submit(d.model_copy(update={"passage_judgments": partial}), e)
    assert res["code"] == 400 and "passage(s) 3" in res["detail"]
    assert await scratch_db.elicitations.count_documents({}) == 0


async def test_judgments_for_passages_not_shown_are_refused(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    d = decision_for(item)
    extra = {**d.passage_judgments, "99": PassageJudgment(direction="neutral")}
    res = await svc.submit(d.model_copy(update={"passage_judgments": extra}), e)
    assert res["code"] == 400 and "not shown" in res["detail"]


async def test_only_the_shown_subset_is_required(scratch_db, monkeypatch):
    """When fewer passages are shown than the set holds, exactly those."""
    monkeypatch.setattr(es, "EVIDENCE_PASSAGES_SHOWN", 4)
    svc, e, item = await _evidence_item(scratch_db, n_passages=10)
    shown = [p.index for p in item.passages]
    assert len(shown) == 4 and shown != [0, 1, 2, 3]   # spread, not the top 4
    assert item.n_passages_total == 10
    assert (await svc.submit(decision_for(item), e))["status"] == "recorded"


async def test_evidence_hash_must_match(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    for bad in (None, "f" * 64):
        res = await svc.submit(
            decision_for(item, evidence_content_hash=bad), e)
        assert res["code"] == 400 and "evidence_content_hash" in res["detail"]


async def test_evidence_set_id_must_match(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(item, evidence_set_id="other:deb"), e)
    assert res["code"] == 400 and "evidence_set_id" in res["detail"]


async def test_queue_item_without_a_hash_cannot_be_judged(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    await scratch_db.elicitation_queue.update_many(
        {}, {"$set": {"evidence_content_hash": None}})
    await scratch_db.evidence_sets.update_many(
        {}, {"$set": {"content_hash": None}})
    item = await svc.next_item(e)
    res = await svc.submit(decision_for(item, evidence_content_hash=None), e)
    assert res["code"] == 400 and "no evidence content hash" in res["detail"]


async def test_reimported_set_with_different_content_is_not_served(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    await scratch_db.evidence_sets.update_many({}, {"$set": {"content_hash": "x"}})
    assert await svc.next_item(e) is None


async def test_non_neutral_passages_need_an_evidential_role(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    d = decision_for(item)
    pj = dict(d.passage_judgments)
    pj["2"] = PassageJudgment(direction="contradicts")
    res = await svc.submit(d.model_copy(update={"passage_judgments": pj}), e)
    assert res["code"] == 400 and "evidential role" in res["detail"]


async def test_evidence_scores_are_required(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(item, consensus_direction=None), e)
    assert res["code"] == 400 and "consensus direction" in res["detail"]


async def test_evidence_decision_cannot_claim_the_expertise_arm(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(item, evidence_condition="expertise"), e)
    assert res["code"] == 400 and "'matched'" in res["detail"]


# --------------------------------------------------------------------------- #
# Fact-level payloads
# --------------------------------------------------------------------------- #

async def _fact_item(db, task):
    await _fact_level(db, collection({"growth": 30}))
    svc = ElicitationService()
    e = await expert(db)
    await calibrate(db, e)
    item = await svc.next_item(e)
    while item.task != task:
        await svc.submit(decision_for(item), e)
        item = await svc.next_item(e)
    return svc, e, item


@pytest.mark.parametrize("over, fragment", [
    ({"provenance_type": None}, "must set provenance_type"),
    ({"scope_verdict": "absent"}, "it also set scope_verdict"),
    ({"evidence_strength": 2}, "carries no corpus"),
    ({"provenance_type": "published"}, "needs source_citation"),
    ({"evidence_condition": "matched"}, "'expertise'"),
])
async def test_fact_level_payload_must_answer_its_task(scratch_db, over, fragment):
    svc, e, item = await _fact_item(scratch_db, "provenance")
    res = await svc.submit(decision_for(item, **over), e)
    assert res["code"] == 400 and fragment in res["detail"], res


async def test_published_with_citation_is_accepted(scratch_db):
    svc, e, item = await _fact_item(scratch_db, "provenance")
    res = await svc.submit(decision_for(
        item, provenance_type="published",
        source_citation="Kooijman 2010, ch. 3"), e)
    assert res["status"] == "recorded"
    rec = await scratch_db.elicitations.find_one({})
    assert rec["evidence_condition"] == "expertise"


# --------------------------------------------------------------------------- #
# Anchoring
# --------------------------------------------------------------------------- #

async def test_exposure_is_derived_from_logged_open_events(scratch_db):
    """Opened, read, closed again: submit-time state says `false`, and the
    record must still say the expert saw the machine verdict."""
    await _fact_level(scratch_db, collection({"growth": 6}))
    svc = ElicitationService()
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    ev = dict(sf_number=item.sf_number, task=item.task, corpus_id=item.corpus_id)
    await svc.log_event(ElicitationEvent(event="machine_verdict_opened",
                                         answered=False, **ev), e)
    await svc.log_event(ElicitationEvent(event="machine_verdict_closed", **ev), e)
    await svc.log_event(ElicitationEvent(event="machine_verdict_opened",
                                         answered=True, **ev), e)
    await svc.submit(decision_for(item, machine_verdict_expanded=False), e)
    rec = await scratch_db.elicitations.find_one({})
    assert rec["machine_verdict_expanded"] is False
    assert rec["machine_verdict_opened"] is True
    assert rec["machine_verdict_open_events"] == 2
    assert rec["machine_verdict_opened_before_answer"] is True

    nxt = await svc.next_item(e)
    await svc.submit(decision_for(nxt), e)
    rec2 = await scratch_db.elicitations.find_one(
        {"queue_position": nxt.queue_position})
    assert rec2["machine_verdict_opened"] is False
    assert rec2["machine_verdict_opened_before_answer"] is None


async def test_event_for_an_unknown_item_is_refused(scratch_db):
    e = await expert(scratch_db)
    res = await ElicitationService().log_event(ElicitationEvent(
        event="machine_verdict_opened", sf_number=1, task="scope"), e)
    assert res["code"] == 404


# --------------------------------------------------------------------------- #
# Progress, admin statistics, and the claims ladder
# --------------------------------------------------------------------------- #

async def test_deb_and_reproduction_judgments_never_merge(scratch_db):
    """Keyed on (sf_number, task), one judgment on each corpus read as a
    repeated judgment and as panel coverage of the other corpus."""
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=2)
    # Make both corpora single-judgment so one panel judgment meets each.
    await scratch_db.elicitation_queue.update_many({}, {"$set": {"n_required": 1}})
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    first = await svc.next_item(e)
    await svc.submit(decision_for(first), e)

    prog = await svc.progress(e)
    assert prog.repeated_judgments == 0
    cov = (await svc.admin_stats())["panel_coverage"]
    assert cov == {"n_required_met": 1, "n_required_pending": 1}

    second = await svc.next_item(e)
    assert second.corpus_id != first.corpus_id
    await svc.submit(decision_for(second), e)
    assert (await svc.progress(e)).repeated_judgments == 0
    cov = (await svc.admin_stats())["panel_coverage"]
    assert cov == {"n_required_met": 2, "n_required_pending": 0}


def test_ladder_thresholds_follow_the_doc():
    assert es._rung(0)[0] == "pre-R0"
    assert es._rung(59) == ("pre-R0", es.PRE_LADDER[1], 60)
    assert es._rung(60)[0] == "R0" and es._rung(60)[2] == 400
    assert es._rung(399)[0] == "R0"
    assert es._rung(400)[0] == "R1" and es._rung(400)[2] == 900
    assert es._rung(900)[0] == "R2"
    assert es._rung(1800)[0] == "R3"
    assert es._rung(3000) == ("R4", es.CLAIMS_LADDER[-1][2], None)


async def test_ladder_counts_panel_evidence_judgments_only(scratch_db, monkeypatch):
    monkeypatch.setattr(es, "CLAIMS_LADDER", [(2, "R0", "pilot"),
                                              (4, "R1", "ceiling")])
    facts = collection({"growth": 4})
    svc = await _with_evidence(scratch_db, facts, n_passages=2, fact_level=True)
    contributor = await expert(scratch_db, tier="contributor", name="c")
    panel = await expert(scratch_db, tier="panel", name="p")
    await calibrate(scratch_db, contributor, panel)

    # Contributor evidence judgments move nothing.
    for _ in range(3):
        item = await svc.next_item(contributor)
        assert item.task == "evidence"
        await svc.submit(decision_for(item), contributor)
    prog = await svc.progress(panel)
    assert prog.ladder_count == 0 and prog.rung == "pre-R0"

    # Panel judgments on the evidence task do.
    for _ in range(2):
        item = await svc.next_item(panel)
        assert item.task == "evidence"
        await svc.submit(decision_for(item), panel)
    prog = await svc.progress(panel)
    assert prog.ladder_count == 2 and prog.rung == "R0"
    assert prog.ladder_basis == es.LADDER_BASIS
    assert (await svc.admin_stats())["rung"] == "R0"


async def test_metadata_tasks_do_not_climb_the_ladder(scratch_db, monkeypatch):
    monkeypatch.setattr(es, "CLAIMS_LADDER", [(1, "R0", "pilot")])
    await _fact_level(scratch_db, collection({"growth": 4}))
    svc = ElicitationService()
    p = await expert(scratch_db)
    await calibrate(scratch_db, p)
    for _ in range(5):
        await svc.submit(decision_for(await svc.next_item(p)), p)
    prog = await svc.progress(p)
    assert prog.completed == 5 and prog.ladder_count == 0
    assert prog.rung == "pre-R0"
