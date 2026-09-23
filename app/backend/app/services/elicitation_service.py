"""
ElicitationService — the expert-judgment queue.

The queue is the methodological artefact here, not just a work list. Its
properties are specified in
``advandeb_methods/docs/02-elicitation-protocol.md`` section 4, and the reason
they matter is that **total expert availability is unknown**: the design has to
stay valid whenever elicitation happens to stop.

  1. **One fixed, seeded order.** Generated once from a recorded seed: a small
     floor per stratum, then weighted fair queueing, so every prefix is close
     to proportionally allocated across categories. Experts draw strictly from
     the head. Cherry-picking — "I'll do the interesting ones first" — is what
     destroys the sample, so the API never offers a choice.

     The floor deliberately over-represents small categories in a *short*
     prefix, in exchange for guaranteeing they are covered at all. Since design
     weights are computed from realised counts (point 4), the sample stays
     valid either way; the floor costs a little efficiency early and buys
     coverage of categories like phytoplankton EPS, which holds three facts.

  2. **Repeated-judgment positions are fixed IN the queue**, every k-th item,
     not appended at the end. Deferring them is the classic way to finish a
     project with no measurable inter-rater agreement at all, and therefore no
     human dispersion to compare any machine panel against.

  3. **Authors never judge their own facts.** Facts 1201-1236 have a known
     author who is also an expert. The queue skips those pairings; it is not
     left to anyone's memory.

  4. **Design weights are computed from realised per-stratum counts** at
     analysis time, not assumed in advance — which is what keeps a
     half-finished queue a valid sample rather than a convenience sample.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.core.database import get_database
from app.models.elicitation import (
    ElicitationDecision, ElicitationProgress, QueueItem,
)

logger = logging.getLogger(__name__)

# Fixed for the life of a collection version. Changing it reshuffles the queue
# and invalidates the "every prefix is a valid sample" property for everything
# judged so far, so it is a constant and not a setting.
QUEUE_SEED = 20260921

# Every k-th position is independently judged a second time, for the inter-rater
# agreement that gives the human panel a measurable dispersion.
REPEATED_JUDGMENT_EVERY = 5

# --------------------------------------------------------------------------- #
# Human panel size — modifiable, not hard-coded
# --------------------------------------------------------------------------- #
#
# The comparison the method is built for (advandeb_methods docs/09 §0) needs a
# *human consensus* with the same structure as the agent consensus: a majority,
# a computable dispersion, and abstention headroom. That means a real panel on
# a designated comparison subset, not a single rating.
#
# Five is the starting point and the platform has the people for it — eight
# potential experts besides the administrator. It is a setting rather than a
# constant because expert availability is unknown and will change; below three
# the same identifiability argument applies to people as to models (ADR 0006).
HUMAN_PANEL_SIZE = int(os.environ.get("ELICITATION_HUMAN_PANEL_SIZE", "5"))

# Every k-th queue position is a comparison item, judged by the full human
# panel. Sized so the comparison subset accrues steadily from the start rather
# than being a block at the end — the same reason repeated-judgment positions
# are fixed in the queue rather than appended.
COMPARISON_SUBSET_EVERY = int(
    os.environ.get("ELICITATION_COMPARISON_EVERY", "25"))

# Items each stratum contributes before proportional allocation begins, so a
# small category (phytoplankton EPS has three facts) is not crowded out of a
# short prefix by a large one.
STRATUM_FLOOR = 3

# Tasks offered before evidence sets exist in the platform. All three operate
# on the statement alone.
DAY_ONE_TASKS = ("provenance", "scope", "assessability")

# docs/02 4.2 — what each elicitation volume supports. Reported rather than
# implied, so work can stop at any rung without a scramble to salvage a claim.
CLAIMS_LADDER = [
    (0, "R0", "Pilot: guidelines calibrated, per-item timing measured"),
    (60, "R1", "Human dispersion measurable; pooled machine-human comparison"),
    (400, "R2", "Per-category agreement; atlas error bars at category level"),
    (900, "R3", "Category comparison; published vs new facts compared"),
    (1800, "R4", "Per-cell estimates; atlas authoritative rather than indicative"),
]


def _rung(n: int) -> tuple[str, str, Optional[int]]:
    rung, note, nxt = "R0", CLAIMS_LADDER[0][2], CLAIMS_LADDER[1][0]
    for i, (threshold, name, desc) in enumerate(CLAIMS_LADDER):
        if n >= threshold:
            rung, note = name, desc
            nxt = CLAIMS_LADDER[i + 1][0] if i + 1 < len(CLAIMS_LADDER) else None
    return rung, note, nxt


class ElicitationService:
    """Queue construction, assignment and decision recording."""

    def __init__(self) -> None:
        self.db = get_database()

    # ------------------------------------------------------------------ #
    # Queue
    # ------------------------------------------------------------------ #

    async def build_queue(self, collection_version: str = "1.0",
                          force: bool = False) -> Dict[str, Any]:
        """Generate the fixed elicitation order. Idempotent.

        Runs once per collection version. A rebuild after elicitation has begun
        would silently change what the completed prefix represents, so it
        refuses unless forced.
        """
        existing = await self.db.elicitation_queue.count_documents(
            {"collection_version": collection_version})
        if existing and not force:
            return {"status": "exists", "queue_length": existing}

        facts: List[Dict[str, Any]] = []
        async for f in self.db.stylized_facts.find(
                {}, {"sf_number": 1, "statement": 1, "category": 1,
                     "statement_sha256": 1, "authored_by": 1,
                     "provenance_type": 1, "source_citation": 1,
                     "legacy_assessment": 1}):
            facts.append(f)
        if not facts:
            return {"status": "empty", "queue_length": 0}

        # Strata: category x task. Every fact appears once per task, so a fact
        # can be judged for provenance by one expert and for scope by
        # another without either being a repeat.
        cells: Dict[str, List[Dict[str, Any]]] = {}
        for f in facts:
            for task in DAY_ONE_TASKS:
                cells.setdefault(f"{f.get('category', '?')}|{task}", []).append(
                    {"fact": f, "task": task})

        rng = random.Random(QUEUE_SEED)
        for items in cells.values():
            rng.shuffle(items)

        keys = sorted(cells)
        sizes = {k: len(cells[k]) for k in keys}
        order: List[Dict[str, Any]] = []
        emitted = {k: 0 for k in keys}

        # Phase 1 — floor. Every stratum contributes its first few items before
        # any stratum contributes many, so a category can never be crowded out
        # of a short prefix by a large one.
        for _ in range(STRATUM_FLOOR):
            for k in keys:
                if cells[k]:
                    order.append({**cells[k].pop(), "stratum": k})
                    emitted[k] += 1

        # Phase 2 — proportional. Weighted fair queueing: always take from the
        # stratum whose emitted share is furthest behind its population share.
        #
        # Plain round-robin would be wrong here, and subtly: it gives every
        # stratum *equal* counts, so small strata are exhausted early and a
        # half-finished queue over-represents them. The whole design rests on
        # any prefix being reweightable back to the collection, and equal
        # allocation makes that reweighting carry far more variance than it
        # needs to.
        remaining = [k for k in keys if cells[k]]
        while remaining:
            k = min(remaining, key=lambda c: (emitted[c] + 1) / sizes[c])
            order.append({**cells[k].pop(), "stratum": k})
            emitted[k] += 1
            if not cells[k]:
                remaining.remove(k)

        if force:
            await self.db.elicitation_queue.delete_many(
                {"collection_version": collection_version})

        docs = []
        for pos, entry in enumerate(order):
            f = entry["fact"]
            try:
                sf_number = int(f.get("sf_number"))
            except (TypeError, ValueError):
                continue
            docs.append({
                "collection_version": collection_version,
                "queue_position": pos,
                "task": entry["task"],
                "stratum": entry["stratum"],
                "sf_number": sf_number,
                "statement_sha256": f.get("statement_sha256") or "",
                "authored_by": f.get("authored_by") or [],
                # How many independent judgments this position needs. Fixed in
                # the queue, never appended later: comparison items and
                # repeated-judgment items must accrue from the start, or a
                # queue that stops early yields no measurable agreement at all.
                "n_required": (
                    HUMAN_PANEL_SIZE if pos % COMPARISON_SUBSET_EVERY == 0
                    else 2 if pos % REPEATED_JUDGMENT_EVERY == 0
                    else 1),
                "comparison_item": pos % COMPARISON_SUBSET_EVERY == 0,
            })
        if docs:
            await self.db.elicitation_queue.insert_many(docs)
        await self.db.elicitation_queue.create_index(
            [("collection_version", 1), ("queue_position", 1)])
        await self.db.elicitations.create_index(
            [("sf_number", 1), ("task", 1), ("expert_id", 1)], unique=True)

        logger.info("elicitation queue built: %d items", len(docs))
        return {"status": "built", "queue_length": len(docs),
                "strata": len(cells), "seed": QUEUE_SEED}

    async def next_item(self, expert_id: str,
                        collection_version: str = "1.0") -> Optional[QueueItem]:
        """The head of the queue that this expert may still do.

        'May still do' excludes: items they have already decided; items already
        decided by someone else unless the position needs more judgments; and
        **any fact they authored**.
        """
        done = set()
        async for a in self.db.elicitations.find(
                {"expert_id": expert_id}, {"sf_number": 1, "task": 1}):
            done.add((a["sf_number"], a["task"]))

        counts: Dict[tuple, int] = {}
        async for a in self.db.elicitations.find({}, {"sf_number": 1, "task": 1}):
            key = (a["sf_number"], a["task"])
            counts[key] = counts.get(key, 0) + 1

        cursor = self.db.elicitation_queue.find(
            {"collection_version": collection_version}).sort("queue_position", 1)
        async for q in cursor:
            key = (q["sf_number"], q["task"])
            if key in done:
                continue
            n_done = counts.get(key, 0)
            needed = int(q.get("n_required", 1))
            if n_done >= needed:
                continue
            # Conflict of interest: an author never judges their own fact.
            if expert_id in (q.get("authored_by") or []):
                continue

            fact = await self.db.stylized_facts.find_one({
                "$or": [{"sf_number": q["sf_number"]},
                        {"sf_number": str(q["sf_number"])}]})
            if not fact:
                continue
            return QueueItem(
                queue_position=q["queue_position"], task=q["task"],
                sf_number=q["sf_number"], statement=fact.get("statement", ""),
                statement_sha256=q.get("statement_sha256")
                or fact.get("statement_sha256", ""),
                category=fact.get("category", ""),
                collection_version=collection_version,
                existing_provenance=fact.get("provenance_type"),
                existing_source_citation=fact.get("source_citation"),
                legacy_assessment=fact.get("legacy_assessment"),
                repeated_judgment=int(q.get("n_required", 1)) > 1,
                n_required=int(q.get("n_required", 1)),
                comparison_item=bool(q.get("comparison_item")),
                stratum=q.get("stratum", ""),
            )
        return None

    # ------------------------------------------------------------------ #
    # Decisions
    # ------------------------------------------------------------------ #

    async def submit(self, decision: ElicitationDecision,
                     expert_id: str,
                     collection_version: str = "1.0") -> Dict[str, Any]:
        """Record one decision. Refuses to overwrite an existing one."""
        q = await self.db.elicitation_queue.find_one({
            "collection_version": collection_version,
            "sf_number": decision.sf_number, "task": decision.task})
        if not q:
            return {"status": "error", "detail": "item not in queue"}
        if expert_id in (q.get("authored_by") or []):
            return {"status": "error",
                    "detail": "expert authored this fact (conflict of interest)"}

        prior = await self.db.elicitations.count_documents({
            "sf_number": decision.sf_number, "task": decision.task})
        doc = {
            **decision.model_dump(),
            "expert_id": expert_id,
            "queue_position": q["queue_position"],
            "stratum": q.get("stratum", ""),
            "collection_version": collection_version,
            "round": "secondary" if prior else "primary",
            "author_excluded": bool(q.get("authored_by")),
            "created_at": datetime.now(timezone.utc),
        }
        try:
            res = await self.db.elicitations.insert_one(doc)
        except Exception as exc:  # duplicate key = already judged by this user
            logger.warning("elicitation insert refused: %s", exc)
            return {"status": "error", "detail": "already judged by you"}
        return {"status": "recorded", "id": str(res.inserted_id),
                "round": doc["round"]}

    # ------------------------------------------------------------------ #
    # Progress
    # ------------------------------------------------------------------ #

    async def progress(self, expert_id: str,
                       collection_version: str = "1.0") -> ElicitationProgress:
        total = await self.db.elicitation_queue.count_documents(
            {"collection_version": collection_version})
        done = await self.db.elicitations.count_documents({})
        mine = await self.db.elicitations.count_documents(
            {"expert_id": expert_id})

        by_task: Dict[str, int] = {}
        by_stratum: Dict[str, int] = {}
        times: List[float] = []
        pairs: Dict[tuple, int] = {}
        async for a in self.db.elicitations.find(
                {}, {"task": 1, "stratum": 1, "time_spent_s": 1,
                     "sf_number": 1}):
            by_task[a.get("task", "?")] = by_task.get(a.get("task", "?"), 0) + 1
            st = a.get("stratum", "?")
            by_stratum[st] = by_stratum.get(st, 0) + 1
            if a.get("time_spent_s"):
                times.append(float(a["time_spent_s"]))
            key = (a.get("sf_number"), a.get("task"))
            pairs[key] = pairs.get(key, 0) + 1

        rung, note, nxt = _rung(done)
        return ElicitationProgress(
            total_queue=total, completed=done, completed_by_me=mine,
            median_seconds_per_item=statistics.median(times) if times else None,
            by_task=by_task, by_stratum=by_stratum,
            repeated_judgments=sum(1 for v in pairs.values() if v >= 2),
            rung=rung, rung_note=note, next_rung_at=nxt,
        )
