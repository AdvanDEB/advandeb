"""Queue construction invariants (advandeb_methods docs/02 section 4.1).

The queue is the sampling frame. These are the properties the design rests
on, each checked against a real (scratch) database rather than restated from
the code:

* any prefix stays proportional across strata — up to the deliberate floor;
* the order is a function of the seed and the collection, not of storage order;
* builds are idempotent, refuse a silent rebuild, and refuse even a forced one
  once judgments exist;
* the two blocks are independent — rebuilding one never touches the other;
* comparison and repeated-judgment positions are fixed in the queue.
"""
from __future__ import annotations

import random
from collections import Counter

import pytest

from app.services import elicitation_service as es
from app.services.elicitation_service import ElicitationService

from tests.elicitation_support import (
    calibrate, collection, decision_for, evidence_artefact, expert, fact,
    seed_facts,
)

pytestmark = pytest.mark.asyncio

# Deliberately uneven, with a category smaller than the floor — the case the
# floor exists for (phytoplankton EPS has three facts in the real collection).
SIZES = {"growth": 120, "reproduction": 90, "feeding": 60, "ageing": 30,
         "toxicology": 12, "eps": 3}


async def _queue(db, task_filter=None):
    q = {} if task_filter is None else {"task": task_filter}
    return [d async for d in db.elicitation_queue.find(q).sort(
        [("priority", 1), ("queue_position", 1)])]


def _assert_prefix_invariant(strata, sizes):
    """Every prefix is proportionally allocated, up to the floor.

    After the floor phase, a stratum k that has been drawn proportionally
    (more than its floor) never leads any still-open stratum j by more than
    one of j's items: e_k/s_k <= (e_j + 1)/s_j. That is what makes any prefix
    reweightable with low variance — the property that lets elicitation stop
    anywhere. Round-robin would violate it (equal counts exhaust small strata
    early), and so would any ordering that let one stratum run ahead.
    """
    floor = {k: min(es.STRATUM_FLOOR, s) for k, s in sizes.items()}
    floor_len = sum(floor.values())
    emitted = Counter()
    for L, k in enumerate(strata, 1):
        emitted[k] += 1
        if L <= floor_len:
            continue
        for a, sa in sizes.items():
            if emitted[a] <= floor[a]:
                continue
            for b, sb in sizes.items():
                if emitted[b] < sb:
                    assert emitted[a] / sa <= (emitted[b] + 1) / sb + 1e-9, (
                        f"prefix {L}: {a} at {emitted[a]}/{sa} runs ahead of "
                        f"{b} at {emitted[b]}/{sb}")


async def test_every_prefix_is_proportional_across_strata(scratch_db):
    await seed_facts(scratch_db, collection(SIZES))
    built = await ElicitationService().build_queue()
    assert built["status"] == "built"
    rows = await _queue(scratch_db)
    strata = [r["stratum"] for r in rows]
    sizes = Counter(strata)
    _assert_prefix_invariant(strata, sizes)

    # And in plain terms: at a quarter, half and three quarters of the queue,
    # every category with more than a floor's worth of facts is within 10% of
    # its population share.
    pop = Counter(s.split("|")[0] for s in strata)
    for frac in (0.25, 0.5, 0.75):
        prefix = strata[: int(len(strata) * frac)]
        got = Counter(s.split("|")[0] for s in prefix)
        for cat, n in pop.items():
            if SIZES[cat] < 30:
                continue
            ratio = (got[cat] / len(prefix)) / (n / len(strata))
            assert 0.9 <= ratio <= 1.1, (frac, cat, ratio)


async def test_the_floor_covers_every_stratum_early(scratch_db):
    await seed_facts(scratch_db, collection(SIZES))
    await ElicitationService().build_queue()
    rows = await _queue(scratch_db)
    n_strata = len({r["stratum"] for r in rows})
    head = rows[: n_strata * es.STRATUM_FLOOR]
    # Every stratum — including the three-fact one — appears in the floor.
    assert {r["stratum"] for r in head} == {r["stratum"] for r in rows}


async def test_evidence_block_prefix_is_proportional_too(scratch_db):
    facts = collection({"growth": 20, "feeding": 9, "eps": 3})
    await seed_facts(scratch_db, facts)
    svc = ElicitationService()
    await svc.import_evidence_sets(evidence_artefact(facts, n_passages=4))
    await svc.build_evidence_queue()
    rows = await _queue(scratch_db, "evidence")
    strata = [r["stratum"] for r in rows]
    _assert_prefix_invariant(strata, Counter(strata))
    assert [r["queue_position"] for r in rows] == list(range(len(rows)))


async def test_order_depends_on_the_seed_not_on_storage_order(scratch_db):
    """The recorded seed must determine the queue. It did not: the shuffle ran
    over the collection's storage order, and production's fact-level queue
    can no longer be regenerated from its seed because the collection was
    restored in a different order."""
    facts = collection(SIZES)
    await seed_facts(scratch_db, facts)
    await ElicitationService().build_queue()
    first = [(r["sf_number"], r["task"]) for r in await _queue(scratch_db)]

    await scratch_db.elicitation_queue.delete_many({})
    await scratch_db.stylized_facts.delete_many({})
    shuffled = list(facts)
    random.Random(7).shuffle(shuffled)
    await seed_facts(scratch_db, shuffled)
    await ElicitationService().build_queue()
    second = [(r["sf_number"], r["task"]) for r in await _queue(scratch_db)]
    assert first == second


async def test_build_is_idempotent_and_refuses_a_silent_rebuild(scratch_db):
    await seed_facts(scratch_db, collection({"growth": 10, "feeding": 5}))
    svc = ElicitationService()
    built = await svc.build_queue()
    before = [(r["_id"], r["sf_number"], r["task"]) for r in await _queue(scratch_db)]

    again = await svc.build_queue()
    assert again == {"status": "exists", "queue_length": built["queue_length"]}
    after = [(r["_id"], r["sf_number"], r["task"]) for r in await _queue(scratch_db)]
    assert after == before   # not rebuilt: same documents, same ids


async def test_forced_rebuild_is_refused_once_judgments_exist(scratch_db):
    await seed_facts(scratch_db, collection({"growth": 10, "feeding": 5}))
    svc = ElicitationService()
    await svc.build_queue()
    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    assert (await svc.submit(decision_for(item), e))["status"] == "recorded"

    before = [r["_id"] for r in await _queue(scratch_db)]
    res = await svc.build_queue(force=True)
    assert res["status"] == "refused" and res["judgments"] == 1
    assert [r["_id"] for r in await _queue(scratch_db)] == before


async def test_forced_fact_level_rebuild_leaves_the_evidence_block_alone(scratch_db):
    """A forced rebuild of the fact-level block used to delete every row of
    the collection version — the evidence block included."""
    facts = collection({"growth": 6, "feeding": 4})
    await seed_facts(scratch_db, facts)
    svc = ElicitationService()
    await svc.import_evidence_sets(evidence_artefact(facts[:3], n_passages=3))
    await svc.build_evidence_queue()
    await svc.build_queue()
    evidence_ids = [r["_id"] for r in await _queue(scratch_db, "evidence")]
    assert evidence_ids

    res = await svc.build_queue(force=True)
    assert res["status"] == "built"
    assert [r["_id"] for r in await _queue(scratch_db, "evidence")] == evidence_ids


async def test_evidence_rebuild_is_idempotent_and_refused_after_judgments(scratch_db):
    facts = collection({"growth": 4})
    await seed_facts(scratch_db, facts)
    svc = ElicitationService()
    await svc.import_evidence_sets(evidence_artefact(facts, n_passages=3))
    built = await svc.build_evidence_queue()
    assert (await svc.build_evidence_queue())["status"] == "exists"

    e = await expert(scratch_db)
    await calibrate(scratch_db, e)
    item = await svc.next_item(e)
    assert item.task == "evidence"
    assert (await svc.submit(decision_for(item), e))["status"] == "recorded"
    res = await svc.build_evidence_queue(force=True)
    assert res["status"] == "refused"
    assert len(await _queue(scratch_db, "evidence")) == built["queue_length"]


async def test_comparison_and_repeated_positions_are_fixed_in_the_queue(scratch_db):
    await seed_facts(scratch_db, collection(SIZES))
    await ElicitationService().build_queue()
    rows = await _queue(scratch_db)
    for r in rows:
        pos = r["queue_position"]
        if pos % es.COMPARISON_SUBSET_EVERY == 0:
            assert r["comparison_item"] and r["n_required"] == es.HUMAN_PANEL_SIZE
        elif pos % es.REPEATED_JUDGMENT_EVERY == 0:
            assert r["n_required"] == 2
        else:
            assert r["n_required"] == 1
    # Accrues from the start, not as a block at the end.
    comp = [r["queue_position"] for r in rows if r["comparison_item"]]
    assert comp[0] == 0
    assert max(b - a for a, b in zip(comp, comp[1:])) == es.COMPARISON_SUBSET_EVERY


async def test_evidence_items_lead_the_queue(scratch_db):
    facts = collection({"growth": 5})
    await seed_facts(scratch_db, facts)
    svc = ElicitationService()
    await svc.build_queue()
    await svc.import_evidence_sets(evidence_artefact(facts[:2], n_passages=3))
    await svc.build_evidence_queue()
    rows = await _queue(scratch_db)
    tasks = [r["task"] for r in rows]
    n_ev = tasks.count("evidence")
    assert n_ev == 4 and tasks[:n_ev] == ["evidence"] * n_ev
    # Comparison corpus at panel depth, the other single-judged.
    for r in rows[:n_ev]:
        assert r["n_required"] == (es.HUMAN_PANEL_SIZE
                                   if r["corpus_id"] == es.EVIDENCE_COMPARISON_CORPUS
                                   else 1)


async def test_authorship_is_carried_onto_queue_items(scratch_db):
    facts = [fact(1, authored_by=["tin_klanjscek"]), fact(2)]
    await seed_facts(scratch_db, facts)
    svc = ElicitationService()
    await svc.build_queue()
    await svc.import_evidence_sets(evidence_artefact(facts, n_passages=2))
    await svc.build_evidence_queue()
    async for q in scratch_db.elicitation_queue.find():
        want = ["tin_klanjscek"] if q["sf_number"] == 1 else []
        assert q["authored_by"] == want, q
