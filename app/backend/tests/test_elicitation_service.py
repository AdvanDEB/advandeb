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
* calibration — the team's published set gates once; none published never
  blocks;
* the combined mode — the departure answer and the rationale rule;
* fact-level tasks — kept, and no longer served.
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


@pytest.fixture(autouse=True)
def _no_knowledge_store(monkeypatch):
    """Citations are resolved against ArangoDB when an item is served; here
    against nothing, unless a test supplies records."""
    from tests.elicitation_support import stub_citation_store
    stub_citation_store(monkeypatch)


@pytest.fixture
def serve_fact_level(monkeypatch):
    """The fact-level tasks are not served since 2026-10-28. Their code is
    kept, and the rules these tests pin down still hold for it, so the tests
    serve them again — the one-line change reversing the decision would be."""
    monkeypatch.setattr(es, "SERVED_TASKS", es.DAY_ONE_TASKS + ("evidence",))


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

async def test_published_set_gates_until_worked(scratch_db):
    svc = await _with_evidence(scratch_db, collection({"growth": 3}), n_passages=2)
    await calibration_set(scratch_db, 2)
    e = await expert(scratch_db)
    assert await svc.next_item(e) is None
    assert (await svc.progress(e)).calibration_required is True
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    assert item is not None

    other = await expert(scratch_db, name="uncalibrated")
    res = await svc.submit(decision_for(item), other)
    assert res["status"] == "error" and res["code"] == 403
    assert "calibration" in res["detail"]


async def test_no_published_set_never_blocks(scratch_db):
    """Until the team publishes a set, experts work the queue, and their
    judgments say they were made before calibration."""
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=2)
    await calibration_set(scratch_db, 1, status="draft")
    e = await expert(scratch_db)
    st = await svc.calibration_status(e)
    assert st["available"] is False and st["required"] is False
    assert st["done"] is False and st["version"] is None
    item = await svc.next_item(e)
    assert item is not None
    assert (await svc.submit(decision_for(item), e))["status"] == "recorded"
    rec = await scratch_db.elicitations.find_one({})
    assert rec["calibration_version"] is None
    assert rec["guidelines_version"] == es.GUIDELINES_VERSION


async def test_judgments_after_calibration_carry_its_version(scratch_db):
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=2)
    await calibration_set(scratch_db, 1, version=3)
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    await svc.submit(decision_for(await svc.next_item(e)), e)
    assert (await scratch_db.elicitations.find_one({}))["calibration_version"] == 3


def _calibration_answer(case, **over):
    base = dict(
        calibration_id=case["calibration_id"], evidence_strength=2,
        consensus_direction=3, departs_from_passages=False, confidence=4,
        passage_judgments={
            str(p.index): PassageJudgment(
                direction="supports" if p.index == 0 else "neutral",
                evidential_role="primary_evidence" if p.index == 0 else None)
            for p in case["passages"]})
    base.update(over)
    return CalibrationDecision(**base)


async def test_calibration_round_trip(scratch_db):
    ids = await calibration_set(scratch_db, 2)
    svc = ElicitationService()
    e = await expert(scratch_db)
    st = await svc.calibration_status(e)
    assert st["available"] and st["required"] and st["total"] == 2

    case = await svc.calibration_next(e)
    assert case["calibration_id"] == ids[0] and len(case["passages"]) == 3
    assert case["passages"][0].citation.status in (
        "resolved", "partial", "unresolved")
    fb = await svc.calibration_submit(_calibration_answer(case), e)
    assert fb["correct"] is True and fb["passages_compared"] == 1
    assert fb["passages_agreed"] == 1
    assert fb["reference"]["explanation"] == "agreed by the team"

    case = await svc.calibration_next(e)
    fb = await svc.calibration_submit(
        _calibration_answer(case, consensus_direction=2), e)
    assert fb["correct"] is False and fb["consensus_matches"] is False
    assert await svc.calibration_next(e) is None
    st = await svc.calibration_status(e)
    assert (st["completed"], st["correct"], st["done"], st["required"]) == (
        2, 1, True, False)


async def test_calibration_answer_follows_the_queue_rules(scratch_db):
    """Calibration trains the act the queue asks for: every passage labelled,
    and a reason where the judgment departs from the passages."""
    await calibration_set(scratch_db, 1)
    svc = ElicitationService()
    e = await expert(scratch_db)
    case = await svc.calibration_next(e)
    res = await svc.calibration_submit(
        _calibration_answer(case, passage_judgments={}), e)
    assert res["code"] == 400 and "no judgment for passage" in res["detail"]
    res = await svc.calibration_submit(
        _calibration_answer(case, departs_from_passages=True), e)
    assert res["code"] == 400 and "rationale" in res["detail"]


async def test_first_calibration_answer_is_the_one_kept(scratch_db):
    await calibration_set(scratch_db, 1)
    svc = ElicitationService()
    e = await expert(scratch_db)
    case = await svc.calibration_next(e)
    await svc.calibration_submit(_calibration_answer(case, consensus_direction=1,
                                                     rationale="hunch"), e)
    await svc.calibration_submit(_calibration_answer(case), e)
    st = await svc.calibration_status(e)
    assert st["completed"] == 1 and st["correct"] == 0


async def test_answers_to_a_retired_version_do_not_count(scratch_db):
    old = await calibration_set(scratch_db, 1, version=1, status="retired")
    await calibration_set(scratch_db, 1, version=2, first_fact=9100)
    e = await expert(scratch_db)
    await scratch_db.elicitation_calibration_answers.insert_one(
        {"expert_id": e, "calibration_id": old[0], "version": 1,
         "correct": True})
    st = await ElicitationService().calibration_status(e)
    assert st["version"] == 2 and st["completed"] == 0 and st["required"]


async def test_draft_publish_and_versioning(scratch_db):
    from app.models.elicitation import CalibrationSetDraft
    facts = [fact(1), fact(2)]
    svc = await _with_evidence(scratch_db, facts, n_passages=3)
    spec = {"evidence_set_id": "1:deb", "reference": {
        "evidence_strength": 3, "consensus_direction": 3,
        "passage_directions": {"0": "supports"}, "explanation": "clear"}}
    draft = CalibrationSetDraft(items=[spec], note="first pass")
    v1 = await svc.save_calibration_draft(draft, "admin")
    assert v1["version"] == 1 and v1["status"] == "draft"
    assert v1["items"][0]["sf_number"] == 1

    bad = CalibrationSetDraft(items=[{**spec, "reference": {
        **spec["reference"], "passage_directions": {"7": "supports"}}}])
    res = await svc.save_calibration_draft(bad, "admin", version=1)
    assert res["code"] == 400 and "not in the set" in res["detail"]
    res = await svc.save_calibration_draft(
        CalibrationSetDraft(items=[{**spec, "evidence_set_id": "nope"}]), "admin")
    assert res["code"] == 400

    pub = await svc.publish_calibration_set(1)
    assert pub["status"] == "published"
    res = await svc.save_calibration_draft(draft, "admin", version=1)
    assert res["code"] == 409            # published sets are not edited

    v2 = await svc.save_calibration_draft(CalibrationSetDraft(items=[
        {**spec, "evidence_set_id": "2:deb"}]), "admin")
    assert v2["version"] == 2
    await svc.publish_calibration_set(2)
    listed = await svc.list_calibration_sets()
    assert listed["published_version"] == 2
    assert [s["status"] for s in listed["sets"]] == ["published", "retired"]
    # Both facts were shown with an answer, so neither is measured now.
    assert await svc.calibration_facts() == {1, 2}


async def test_calibration_facts_leave_the_measured_queue(scratch_db):
    svc = await _with_evidence(scratch_db, [fact(1), fact(2)], n_passages=2)
    await scratch_db.elicitation_calibration_sets.insert_one({
        "version": 1, "status": "published", "items": [
            {"evidence_set_id": "1:reproduction", "sf_number": 1,
             "corpus_id": "reproduction",
             "reference": {"evidence_strength": 1, "consensus_direction": 2,
                           "passage_directions": {}, "explanation": "x"}}],
        "created_at": None})
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    served = await _drain(svc, e)
    assert {i.sf_number for i in served} == {2}


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


async def test_authored_sf_numbers_still_excludes(scratch_db, serve_fact_level):
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

async def test_only_the_head_of_the_queue_can_be_submitted(scratch_db, serve_fact_level):
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


async def test_items_whose_panel_requirement_is_met_are_refused(scratch_db, serve_fact_level):
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


async def test_already_judged_is_refused(scratch_db, serve_fact_level):
    await _fact_level(scratch_db, collection({"growth": 3}))
    svc = ElicitationService()
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    assert (await svc.submit(decision_for(item), e))["status"] == "recorded"
    res = await svc.submit(decision_for(item), e)
    assert res["code"] == 409 and res["detail"] == "already judged by you"


async def test_unique_index_prevents_duplicates(scratch_db, serve_fact_level):
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


async def test_statement_hash_must_match(scratch_db, serve_fact_level):
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

async def test_contributor_never_decrements_n_required(scratch_db, serve_fact_level):
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


async def test_panel_judgments_do_satisfy_n_required(scratch_db, serve_fact_level):
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


async def test_tier_is_stamped_at_write_time(scratch_db, serve_fact_level):
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


async def test_fact_level_item_is_served_under_expertise(scratch_db, serve_fact_level):
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


async def test_cannot_judge_is_a_label_that_asks_no_role(scratch_db):
    # 2.1: an abstention labels the passage (no hole in the record) and, like
    # neutral, is not asked what kind of evidence it is.
    svc, e, item = await _evidence_item(scratch_db)
    d = decision_for(item)
    pj = dict(d.passage_judgments)
    pj["2"] = PassageJudgment(direction="cannot_judge")
    res = await svc.submit(d.model_copy(update={"passage_judgments": pj}), e)
    assert res["status"] == "recorded", res
    rec = await scratch_db.elicitations.find_one({})
    assert rec["passage_judgments"]["2"]["direction"] == "cannot_judge"
    assert rec["guidelines_version"] == "2.1"


async def test_disputes_shows_the_stored_contradicts_value(scratch_db):
    g = ElicitationService().guidelines()
    evidence = next(t for t in g["tasks"] if t["task"] == "evidence")
    labels = {o["value"]: o["label"] for o in evidence["options"]}
    assert labels == {"supports": "Supports", "contradicts": "Disputes",
                      "neutral": "Neutral", "cannot_judge": "Cannot judge"}


async def test_evidence_scores_are_required(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(item, consensus_direction=None), e)
    assert res["code"] == 400 and "consensus direction" in res["detail"]


async def test_evidence_decision_cannot_claim_the_expertise_arm(scratch_db, serve_fact_level):
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
async def test_fact_level_payload_must_answer_its_task(scratch_db, over, fragment, serve_fact_level):
    svc, e, item = await _fact_item(scratch_db, "provenance")
    res = await svc.submit(decision_for(item, **over), e)
    assert res["code"] == 400 and fragment in res["detail"], res


async def test_published_with_citation_is_accepted(scratch_db, serve_fact_level):
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

async def test_exposure_is_derived_from_logged_open_events(scratch_db, serve_fact_level):
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


async def test_ladder_thresholds_follow_the_doc():
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


async def test_metadata_tasks_do_not_climb_the_ladder(scratch_db, monkeypatch, serve_fact_level):
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


# --------------------------------------------------------------------------- #
# The combined mode (guidelines 2.0): one arm, the departure answer, and a
# rationale only where the judgment departs from the passages
# --------------------------------------------------------------------------- #

async def test_fact_level_tasks_are_not_served(scratch_db):
    """3,786 statement-only items were removed from the queue on 2026-10-28;
    their rows stay stored, nobody is served them."""
    facts = collection({"growth": 3})
    svc = await _with_evidence(scratch_db, facts, n_passages=2, fact_level=True)
    assert await scratch_db.elicitation_queue.count_documents(
        {"task": {"$in": list(es.DAY_ONE_TASKS)}}) == 9
    e = await expert(scratch_db)
    served = await _drain(svc, e)
    assert served and {i.task for i in served} == {"evidence"}
    assert (await svc.progress(e)).total_queue == 6
    assert (await svc.admin_stats())["total_queue"] == 6


async def test_an_unserved_task_cannot_be_recorded(scratch_db):
    await _fact_level(scratch_db, [fact(1)])
    e = await expert(scratch_db)
    q = await scratch_db.elicitation_queue.find_one({"task": "provenance"})
    from app.models.elicitation import ElicitationDecision
    res = await ElicitationService().submit(ElicitationDecision(
        task="provenance", sf_number=q["sf_number"],
        statement_sha256=q["statement_sha256"], provenance_type="unknown",
        confidence=3, rationale="r"), e)
    assert res["code"] == 400 and "no longer served" in res["detail"]


async def test_the_departure_answer_is_required(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(item, departs_from_passages=None), e)
    assert res["code"] == 400 and "departs_from_passages" in res["detail"]


async def test_rationale_is_optional_when_the_judgment_follows_the_passages(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(item, rationale=""), e)
    assert res["status"] == "recorded"
    rec = await scratch_db.elicitations.find_one({})
    assert rec["rationale_required"] is False
    assert rec["score_label_conflicts"] == []
    assert rec["departs_from_passages"] is False


async def test_departing_requires_a_rationale(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(item, departs_from_passages=True,
                                        rationale="  "), e)
    assert res["code"] == 400 and "beyond or against" in res["detail"]
    res = await svc.submit(decision_for(item, departs_from_passages=True,
                                        rationale="Kooijman 2010 shows it"), e)
    assert res["status"] == "recorded"
    assert (await scratch_db.elicitations.find_one({}))["rationale_required"]


def _all_neutral(item):
    return {str(p.index): PassageJudgment(direction="neutral")
            for p in item.passages}


@pytest.mark.parametrize("scores, conflicts", [
    ({"consensus_direction": 3, "evidence_strength": 1},
     ["corroborated_without_support"]),
    ({"consensus_direction": 1, "evidence_strength": 1},
     ["against_without_contradiction"]),
    ({"consensus_direction": 2, "evidence_strength": 2},
     ["strength_without_support"]),
    ({"consensus_direction": 3, "evidence_strength": 3},
     ["corroborated_without_support", "strength_without_support"]),
])
async def test_scores_beyond_own_labels_require_a_rationale(scratch_db, scores,
                                                            conflicts):
    """Decided from the expert's own labels, never from the machine's."""
    svc, e, item = await _evidence_item(scratch_db)
    d = decision_for(item, passage_judgments=_all_neutral(item), rationale="",
                     **scores)
    res = await svc.submit(d, e)
    assert res["code"] == 400 and "your own passage labels" in res["detail"]
    for c in conflicts:
        assert c in res["detail"]
    res = await svc.submit(d.model_copy(update={"rationale": "I know of X"}), e)
    assert res["status"] == "recorded"
    rec = await scratch_db.elicitations.find_one({})
    assert rec["score_label_conflicts"] == conflicts
    assert rec["rationale_required"] is True


async def test_inconclusive_weak_with_neutral_passages_is_no_conflict(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    res = await svc.submit(decision_for(
        item, passage_judgments=_all_neutral(item), rationale="",
        consensus_direction=2, evidence_strength=1), e)
    assert res["status"] == "recorded"


async def test_against_with_a_contradicting_passage_is_no_conflict(scratch_db):
    svc, e, item = await _evidence_item(scratch_db)
    pj = _all_neutral(item)
    pj["1"] = PassageJudgment(direction="contradicts",
                              evidential_role="primary_evidence")
    res = await svc.submit(decision_for(
        item, passage_judgments=pj, rationale="", consensus_direction=1,
        evidence_strength=1), e)
    assert res["status"] == "recorded"


async def test_reference_ids_must_be_own_and_on_this_fact(scratch_db):
    from bson import ObjectId
    svc, e, item = await _evidence_item(scratch_db)
    other = await expert(scratch_db, name="other")
    mine = (await scratch_db.expert_references.insert_one(
        {"expert_id": e, "sf_number": item.sf_number, "doi": "10.1/a"})).inserted_id
    theirs = (await scratch_db.expert_references.insert_one(
        {"expert_id": other, "sf_number": item.sf_number, "doi": "10.1/b"})).inserted_id
    elsewhere = (await scratch_db.expert_references.insert_one(
        {"expert_id": e, "sf_number": 999, "doi": "10.1/c"})).inserted_id
    for bad in ([str(theirs)], [str(elsewhere)], ["nope"], [str(ObjectId())]):
        res = await svc.submit(decision_for(item, reference_ids=bad), e)
        assert res["code"] == 400 and "reference" in res["detail"], bad
    res = await svc.submit(decision_for(item, reference_ids=[str(mine)]), e)
    assert res["status"] == "recorded"
    rec = await scratch_db.elicitations.find_one({})
    assert rec["reference_ids"] == [str(mine)]


async def test_no_machine_score_is_offered_on_an_evidence_item(scratch_db):
    f = fact(1)
    f["legacy_assessment"] = {"score_1_100": 80, "confidence": "high"}
    svc = await _with_evidence(scratch_db, [f], n_passages=2)
    e = await expert(scratch_db)
    assert (await svc.next_item(e)).legacy_assessment is None


async def test_guidelines_describe_the_combined_mode(scratch_db):
    g = ElicitationService().guidelines()
    assert g["version"] == es.GUIDELINES_VERSION == "2.1"
    assert 4 <= len(g["how_it_works"]) <= 8
    sections = {s["task"] for s in g["tasks"]}
    assert {"evidence", "evidence_role", "evidence_strength",
            "consensus_direction", "departure"} <= sections
    text = " ".join(g["how_it_works"]).lower()
    assert "what you know" in text and "machine assessment" in text


# --------------------------------------------------------------------------- #
# Citations — resolved at serve time, the frozen passages untouched
# --------------------------------------------------------------------------- #

async def test_passages_are_served_with_citations_and_the_set_is_unchanged(
        scratch_db, monkeypatch):
    from app.services import passage_citation_service as pcs
    pcs.reset_cache()
    monkeypatch.setattr(pcs, "_load_documents_by_key", lambda keys: [
        {"_key": "doc0", "title": "Paper 0.", "year": "2001",
         "authors": "['S.A.L.M. Kooijman', 'T. Sousa']",
         "journal": "J Theor Biol", "doi": "None"}])
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=2)
    before = await scratch_db.evidence_sets.find_one({"_id": "1:reproduction"})
    e = await expert(scratch_db)
    item = await svc.next_item(e)
    while item.corpus_id != "reproduction":
        await svc.submit(decision_for(item), e)
        item = await svc.next_item(e)
    c0 = item.passages[0].citation
    assert c0.status == "resolved" and c0.authors == ["S.A.L.M. Kooijman",
                                                      "T. Sousa"]
    assert c0.year == 2001 and c0.journal == "J Theor Biol"
    # No DOI in the record: the passage's own, well-formed one is kept.
    assert c0.doi == "10.5555/0"
    after = await scratch_db.evidence_sets.find_one({"_id": "1:reproduction"})
    assert after == before


async def test_an_unreachable_store_serves_unresolved_citations(scratch_db,
                                                                monkeypatch):
    from app.services import passage_citation_service as pcs
    pcs.reset_cache()

    def boom(*a):
        raise ConnectionError("arango down")
    monkeypatch.setattr(pcs, "_load_deb_documents", boom)
    monkeypatch.setattr(pcs, "_load_documents_by_key", boom)
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=2)
    await scratch_db.evidence_sets.update_many(
        {"corpus_id": "deb"}, {"$set": {"passages.$[].title": "Kooy93.pdf",
                                        "passages.$[].doi": "None"}})
    e = await expert(scratch_db)
    item = await svc.next_item(e)
    assert item.corpus_id == "deb"
    c = item.passages[0].citation
    assert c.status == "unresolved" and c.file_name == "Kooy93.pdf"
    assert c.doi is None


# --------------------------------------------------------------------------- #
# Expert references as evidence candidates for curator review
# --------------------------------------------------------------------------- #

async def test_references_are_candidates_until_a_curator_decides(scratch_db):
    from datetime import datetime, timezone
    from app.services.expert_reference_service import ExpertReferenceService
    await seed_facts(scratch_db, [fact(7)])
    now = datetime.now(timezone.utc)
    new = (await scratch_db.expert_references.insert_one({
        "sf_number": 7, "doi": "10.1/x", "direction": "supports",
        "expert_id": "e1", "tier": "panel", "curation": {"status": "pending"},
        "resolution": {"status": "not_in_corpus", "resolved_title": "T",
                       "resolved_year": "2004"}, "created_at": now})).inserted_id
    # Recorded before curation existed: never reviewed, so pending too.
    await scratch_db.expert_references.insert_one({
        "sf_number": 7, "doi": "10.1/y", "direction": "opposes",
        "expert_id": "e2", "created_at": now})
    svc = ExpertReferenceService()
    listed = await svc.candidates("pending")
    assert listed["counts"] == {"pending": 2, "accepted": 0, "rejected": 0}
    first = listed["candidates"][0]
    assert first["statement"] == "Stylized fact 7 in growth."
    assert first["resolved_year"] == 2004 and "expert_id" not in first

    res = await svc.review(str(new), "curator", True, "checked the paper")
    assert res == {"id": str(new), "status": "accepted"}
    listed = await svc.candidates("accepted")
    assert listed["counts"]["accepted"] == 1
    assert listed["candidates"][0]["review_comment"] == "checked the paper"
    assert (await svc.review("nope", "curator", False, None))["code"] == 404


async def test_a_record_for_another_work_is_not_joined(scratch_db, monkeypatch):
    """Some reproduction passages carry an OpenAlex id that points at an
    unrelated work; the passage's own title and DOI are kept instead."""
    from app.services import passage_citation_service as pcs
    pcs.reset_cache()
    monkeypatch.setattr(pcs, "_load_documents_by_key", lambda keys: [
        {"_key": "doc0", "title": "Rice leaf morphogenesis", "year": 2013,
         "authors": ["Someone Else"], "doi": "10.3724/sp.j.1006.2013.00767"}])
    svc = await _with_evidence(scratch_db, [fact(1)], n_passages=2)
    e = await expert(scratch_db)
    item = await svc.next_item(e)
    while item.corpus_id != "reproduction":
        await svc.submit(decision_for(item), e)
        item = await svc.next_item(e)
    c0 = item.passages[0].citation
    assert c0.title == "Paper 0" and c0.authors == [] and c0.doi == "10.5555/0"
    assert c0.status == "partial"
    assert pcs.same_work("Energy budgets <i>in</i> Daphnia", "Energy budgets in daphnia.")
