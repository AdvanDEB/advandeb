"""
AnnotationService — the human-validation queue.

The queue is the methodological artefact here, not just a work list. Its
properties are specified in ``advandeb_methods/docs/02-annotation-protocol.md``
section 4, and the reason they matter is that **total annotator availability is
unknown**: the design has to stay valid whenever annotation happens to stop.

  1. **One fixed, seeded order.** Generated once from a recorded seed: a small
     floor per stratum, then weighted fair queueing, so every prefix is close
     to proportionally allocated across categories. Annotators draw strictly
     from the head. Cherry-picking — "I'll do the interesting ones first" — is
     what destroys the sample, so the API never offers a choice.

     The floor deliberately over-represents small categories in a *short*
     prefix, in exchange for guaranteeing they are covered at all. Since design
     weights are computed from realised counts (point 4), the sample stays
     valid either way; the floor costs a little efficiency early and buys
     coverage of categories like phytoplankton EPS, which holds three facts.

  2. **Double-annotation positions are fixed IN the queue**, every k-th item,
     not appended at the end. Deferring them is the classic way to finish a
     project with no measurable inter-annotator agreement at all, and therefore
     no human ceiling to compare any machine against.

  3. **Authors never judge their own facts.** Facts 1201-1236 have a known
     author who is also an annotator. The queue skips those pairings; it is not
     left to anyone's memory.

  4. **Design weights are computed from realised per-stratum counts** at
     analysis time, not assumed in advance — which is what keeps a
     half-finished queue a valid sample rather than a convenience sample.
"""
from __future__ import annotations

import hashlib
import logging
import random
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.core.database import get_database
from app.models.annotation import (
    AnnotationDecision, AnnotationProgress, QueueItem,
)

logger = logging.getLogger(__name__)

# Fixed for the life of a collection version. Changing it reshuffles the queue
# and invalidates the "every prefix is a valid sample" property for everything
# annotated so far, so it is a constant and not a setting.
QUEUE_SEED = 20260921

# Every k-th position is independently annotated a second time.
DOUBLE_ANNOTATION_EVERY = 5

# Items each stratum contributes before proportional allocation begins, so a
# small category (phytoplankton EPS has three facts) is not crowded out of a
# short prefix by a large one.
STRATUM_FLOOR = 3

# Tasks offered before evidence sets exist in the platform. All three operate
# on the statement alone.
DAY_ONE_TASKS = ("provenance", "scope", "assessability")

# docs/02 4.2 — what each annotation volume supports. Reported rather than
# implied, so work can stop at any rung without a scramble to salvage a claim.
CLAIMS_LADDER = [
    (0, "R0", "Pilot: guidelines calibrated, per-item timing measured"),
    (60, "R1", "Overall agreement ceiling; pooled machine-human comparison"),
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


class AnnotationService:
    """Queue construction, assignment and decision recording."""

    def __init__(self) -> None:
        self.db = get_database()

    # ------------------------------------------------------------------ #
    # Queue
    # ------------------------------------------------------------------ #

    async def build_queue(self, collection_version: str = "1.0",
                          force: bool = False) -> Dict[str, Any]:
        """Generate the fixed annotation order. Idempotent.

        Runs once per collection version. A rebuild after annotation has begun
        would silently change what the completed prefix represents, so it
        refuses unless forced.
        """
        existing = await self.db.annotation_queue.count_documents(
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
        # can be judged for provenance by one annotator and for scope by
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
            await self.db.annotation_queue.delete_many(
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
                # Fixed in the queue, never appended later.
                "double_annotation": pos % DOUBLE_ANNOTATION_EVERY == 0,
            })
        if docs:
            await self.db.annotation_queue.insert_many(docs)
        await self.db.annotation_queue.create_index(
            [("collection_version", 1), ("queue_position", 1)])
        await self.db.annotations.create_index(
            [("sf_number", 1), ("task", 1), ("annotator_id", 1)], unique=True)

        logger.info("annotation queue built: %d items", len(docs))
        return {"status": "built", "queue_length": len(docs),
                "strata": len(cells), "seed": QUEUE_SEED}

    async def next_item(self, annotator_id: str,
                        collection_version: str = "1.0") -> Optional[QueueItem]:
        """The head of the queue that this annotator may still do.

        'May still do' excludes: items they have already decided; items already
        decided by someone else unless the position is marked for double
        annotation; and **any fact they authored**.
        """
        done = set()
        async for a in self.db.annotations.find(
                {"annotator_id": annotator_id}, {"sf_number": 1, "task": 1}):
            done.add((a["sf_number"], a["task"]))

        counts: Dict[tuple, int] = {}
        async for a in self.db.annotations.find({}, {"sf_number": 1, "task": 1}):
            key = (a["sf_number"], a["task"])
            counts[key] = counts.get(key, 0) + 1

        cursor = self.db.annotation_queue.find(
            {"collection_version": collection_version}).sort("queue_position", 1)
        async for q in cursor:
            key = (q["sf_number"], q["task"])
            if key in done:
                continue
            n_done = counts.get(key, 0)
            needed = 2 if q.get("double_annotation") else 1
            if n_done >= needed:
                continue
            # Conflict of interest: an author never judges their own fact.
            if annotator_id in (q.get("authored_by") or []):
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
                double_annotation=bool(q.get("double_annotation")),
                stratum=q.get("stratum", ""),
            )
        return None

    # ------------------------------------------------------------------ #
    # Decisions
    # ------------------------------------------------------------------ #

    async def submit(self, decision: AnnotationDecision,
                     annotator_id: str,
                     collection_version: str = "1.0") -> Dict[str, Any]:
        """Record one decision. Refuses to overwrite an existing one."""
        q = await self.db.annotation_queue.find_one({
            "collection_version": collection_version,
            "sf_number": decision.sf_number, "task": decision.task})
        if not q:
            return {"status": "error", "detail": "item not in queue"}
        if annotator_id in (q.get("authored_by") or []):
            return {"status": "error",
                    "detail": "annotator authored this fact (conflict of interest)"}

        prior = await self.db.annotations.count_documents({
            "sf_number": decision.sf_number, "task": decision.task})
        doc = {
            **decision.model_dump(),
            "annotator_id": annotator_id,
            "queue_position": q["queue_position"],
            "stratum": q.get("stratum", ""),
            "collection_version": collection_version,
            "round": "secondary" if prior else "primary",
            "author_excluded": bool(q.get("authored_by")),
            "created_at": datetime.now(timezone.utc),
        }
        try:
            res = await self.db.annotations.insert_one(doc)
        except Exception as exc:  # duplicate key = already annotated by this user
            logger.warning("annotation insert refused: %s", exc)
            return {"status": "error", "detail": "already annotated by you"}
        return {"status": "recorded", "id": str(res.inserted_id),
                "round": doc["round"]}

    # ------------------------------------------------------------------ #
    # Progress
    # ------------------------------------------------------------------ #

    async def progress(self, annotator_id: str,
                       collection_version: str = "1.0") -> AnnotationProgress:
        total = await self.db.annotation_queue.count_documents(
            {"collection_version": collection_version})
        done = await self.db.annotations.count_documents({})
        mine = await self.db.annotations.count_documents(
            {"annotator_id": annotator_id})

        by_task: Dict[str, int] = {}
        by_stratum: Dict[str, int] = {}
        times: List[float] = []
        pairs: Dict[tuple, int] = {}
        async for a in self.db.annotations.find(
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
        return AnnotationProgress(
            total_queue=total, completed=done, completed_by_me=mine,
            median_seconds_per_item=statistics.median(times) if times else None,
            by_task=by_task, by_stratum=by_stratum,
            double_annotated=sum(1 for v in pairs.values() if v >= 2),
            rung=rung, rung_note=note, next_rung_at=nxt,
        )
