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
    ElicitationDecision, ElicitationProgress, EvidencePassage, QueueItem,
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

# Bumped whenever the task definitions change. A mid-study guideline change
# invalidates prior judgments unless they are re-checked, so the version is
# recorded rather than implied (docs/02 section 7).
GUIDELINES_VERSION = "1.1"

# Tasks offered before evidence sets exist in the platform. All three operate
# on the statement alone.
DAY_ONE_TASKS = ("provenance", "scope", "assessability")

# --------------------------------------------------------------------------- #
# The evidence block                                                           #
# --------------------------------------------------------------------------- #
#
# Evidence items lead the queue, ahead of every fact-level task. Not a
# preference: the human ceiling is the one measurement that unblocks the rest
# of the method, and expert time is the scarcest input in the project. Metadata
# tasks are worth collecting and they are worth collecting *second*.
#
# Ordering is expressed as a block `priority` rather than by renumbering, so
# each block keeps its own seeded order and its own prefix property. The
# reweighting argument (docs/02 section 4.1) therefore holds **within a
# block** — which is what it has to do, since the two blocks stratify over
# different populations anyway (evidence sets versus the whole collection).
PRIORITY_EVIDENCE = 0
PRIORITY_FACT_LEVEL = 1

# Corpora an expert is asked to score. `combined` is deliberately excluded: the
# method suppresses the combined score outright whenever one corpus returns no
# on-topic evidence (docs/09 section 3.4), so eliciting it would spend the
# scarcest input in the project on a number the analysis refuses to emit.
EVIDENCE_CORPORA = ("deb", "reproduction")

# The corpus whose items take the full human panel. The comparison the ceiling
# comes from needs several independent experts on the *same* evidence set, and
# spreading five-deep coverage across every corpus would give shallow coverage
# of both instead of a measurable panel on one.
EVIDENCE_COMPARISON_CORPUS = "deb"

# How many of a set's passages an expert is shown. Every set holds 18.
#
# The trade-off is real and runs in both directions. Passage-level agreement is
# the headline number (alpha = 0.431), and showing all 18 both maximises
# passage judgments per expert-hour — the per-item orientation cost amortises
# over more passages — and removes any objection that the humans were asked a
# different question from the agents. Showing fewer covers more distinct facts
# per hour, which is what the *fact-level* scores need.
#
# Set here rather than inferred, and recorded on every queue item, because an
# expert judging 9 of 18 passages is answering a different question from one
# judging all of them and the record has to say which.
EVIDENCE_PASSAGES_SHOWN = int(
    os.environ.get("ELICITATION_EVIDENCE_PASSAGES", "18"))

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


def _item_key(doc: Dict[str, Any]) -> tuple:
    """What makes one queue item distinct from another.

    `corpus_id` is part of it. A fact is scored once per corpus, so without it
    an expert's DEB judgment would mark the reproduction item done as well —
    and the queue would report coverage it does not have.
    """
    return (doc.get("sf_number"), doc.get("task"), doc.get("corpus_id"))


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
                "priority": PRIORITY_FACT_LEVEL,
                "corpus_id": None,
                "n_required": (
                    HUMAN_PANEL_SIZE if pos % COMPARISON_SUBSET_EVERY == 0
                    else 2 if pos % REPEATED_JUDGMENT_EVERY == 0
                    else 1),
                "comparison_item": pos % COMPARISON_SUBSET_EVERY == 0,
            })
        if docs:
            await self.db.elicitation_queue.insert_many(docs)
        await self._ensure_indexes()

        logger.info("elicitation queue built: %d items", len(docs))
        return {"status": "built", "queue_length": len(docs),
                "strata": len(cells), "seed": QUEUE_SEED}

    async def _ensure_indexes(self) -> None:
        """Indexes, including the one that defines what a distinct item is.

        The uniqueness key is (sf_number, task, corpus_id, expert_id). It used
        to omit `corpus_id`, which was correct while every task was fact-level
        and silently wrong the moment the evidence task arrived: one expert
        scoring a fact against the DEB corpus would have blocked themselves
        from ever scoring it against the reproduction corpus, and the failure
        would have surfaced as a bare duplicate-key error reported to them as
        "already judged by you".
        """
        await self.db.elicitation_queue.create_index(
            [("collection_version", 1), ("priority", 1), ("queue_position", 1)])
        await self.db.elicitation_queue.create_index(
            [("collection_version", 1), ("sf_number", 1), ("task", 1),
             ("corpus_id", 1)])
        # Drop the superseded key if it is still present, then install the
        # corpus-aware one. Ordering matters: the old index would reject the
        # second corpus for a fact even though the new one permits it.
        try:
            await self.db.elicitations.drop_index("sf_number_1_task_1_expert_id_1")
            logger.info("dropped superseded elicitations uniqueness index")
        except Exception:
            pass
        await self.db.elicitations.create_index(
            [("sf_number", 1), ("task", 1), ("corpus_id", 1), ("expert_id", 1)],
            unique=True, name="item_expert_unique")

    # ------------------------------------------------------------------ #
    # Evidence sets
    # ------------------------------------------------------------------ #

    async def import_evidence_sets(self, artefact: Dict[str, Any],
                                   force: bool = False) -> Dict[str, Any]:
        """Load the frozen evidence sets the agent panel read.

        The artefact is the verified export from advandeb_methods
        (`data/evidence/evidence_sets_v1.0.json`), whose every `content_hash`
        was checked against the backfill manifest before it was written. It is
        stored here verbatim, hashes included, so the claim that both panels
        read the same passages stays checkable from inside the platform
        (ADR 0003).
        """
        sets = artefact.get("sets") or []
        if not sets:
            return {"status": "empty", "n": 0}
        existing = await self.db.evidence_sets.count_documents({})
        if existing and not force:
            return {"status": "exists", "n": existing}
        if force:
            await self.db.evidence_sets.delete_many({})

        docs = []
        for es in sets:
            docs.append({
                "_id": es["evidence_set_id"],
                **{k: es.get(k) for k in (
                    "sf_candidate_id", "sf_number", "statement",
                    "statement_sha256", "category", "corpus_id",
                    "content_hash", "n_passages", "embedding_model",
                    "passages")},
                "artefact_version": (artefact.get("manifest") or {}).get("version"),
                "imported_at": datetime.now(timezone.utc),
            })
        await self.db.evidence_sets.insert_many(docs)
        await self.db.evidence_sets.create_index(
            [("sf_number", 1), ("corpus_id", 1)])
        logger.info("imported %d evidence sets", len(docs))
        return {"status": "imported", "n": len(docs),
                "facts": len({d["sf_number"] for d in docs}),
                "corpora": sorted({d["corpus_id"] for d in docs})}

    @staticmethod
    def shown_passage_indices(n_total: int, n_shown: int) -> List[int]:
        """Which passages an expert sees, when not all of them.

        Spread evenly across the canonical order rather than taken from the
        top. Passages are ordered by retrieval similarity, so the first k are
        systematically the strongest evidence — showing those would hand the
        human panel an easier task than the agents got and bias the ceiling
        upward, which is the one direction that would make the machine look
        worse for no reason.
        """
        if n_shown >= n_total:
            return list(range(n_total))
        step = n_total / float(n_shown)
        return sorted({min(n_total - 1, int(i * step)) for i in range(n_shown)})

    async def build_evidence_queue(self, collection_version: str = "1.0",
                                   force: bool = False) -> Dict[str, Any]:
        """Queue one evidence item per (fact, corpus), ahead of everything else.

        Idempotent, and refuses a silent rebuild for the same reason
        `build_queue` does: re-ordering after elicitation has begun changes
        what the completed prefix represents.
        """
        existing = await self.db.elicitation_queue.count_documents(
            {"collection_version": collection_version, "task": "evidence"})
        if existing and not force:
            return {"status": "exists", "queue_length": existing}

        sets: List[Dict[str, Any]] = []
        async for es in self.db.evidence_sets.find(
                {"corpus_id": {"$in": list(EVIDENCE_CORPORA)}},
                {"passages": 0}):
            sets.append(es)
        if not sets:
            return {"status": "no_evidence_sets", "queue_length": 0}

        authored: Dict[int, List[str]] = {}
        async for f in self.db.stylized_facts.find(
                {"authored_by": {"$exists": True, "$ne": []}},
                {"sf_number": 1, "authored_by": 1}):
            try:
                authored[int(f["sf_number"])] = f.get("authored_by") or []
            except (TypeError, ValueError):
                continue

        # Same stratification as the fact-level block — category x corpus —
        # and the same floor-then-proportional allocation, so a short prefix
        # is still representative of the evidence sets as a whole.
        cells: Dict[str, List[Dict[str, Any]]] = {}
        for es in sets:
            cells.setdefault(
                f"{es.get('category', '?')}|{es['corpus_id']}", []).append(es)
        rng = random.Random(QUEUE_SEED)
        for items in cells.values():
            rng.shuffle(items)

        keys = sorted(cells)
        sizes = {k: len(cells[k]) for k in keys}
        emitted = {k: 0 for k in keys}
        order: List[Dict[str, Any]] = []
        for _ in range(STRATUM_FLOOR):
            for k in keys:
                if cells[k]:
                    order.append({**cells[k].pop(), "stratum": k})
                    emitted[k] += 1
        remaining = [k for k in keys if cells[k]]
        while remaining:
            k = min(remaining, key=lambda c: (emitted[c] + 1) / sizes[c])
            order.append({**cells[k].pop(), "stratum": k})
            emitted[k] += 1
            if not cells[k]:
                remaining.remove(k)

        if force:
            await self.db.elicitation_queue.delete_many(
                {"collection_version": collection_version, "task": "evidence"})

        docs = []
        for pos, es in enumerate(order):
            sf_number = int(es["sf_number"])
            comparison = es["corpus_id"] == EVIDENCE_COMPARISON_CORPUS
            docs.append({
                "collection_version": collection_version,
                "priority": PRIORITY_EVIDENCE,
                "queue_position": pos,
                "task": "evidence",
                "stratum": es["stratum"],
                "sf_number": sf_number,
                "corpus_id": es["corpus_id"],
                "evidence_set_id": es["_id"],
                "evidence_content_hash": es.get("content_hash"),
                "statement_sha256": es.get("statement_sha256") or "",
                "authored_by": authored.get(sf_number, []),
                # The comparison corpus takes the full human panel; the other
                # is single-judged. Fixed in the queue, never appended: a
                # position that only becomes five-deep later yields no
                # measurable agreement if the effort stops early.
                "n_required": HUMAN_PANEL_SIZE if comparison else 1,
                "comparison_item": comparison,
                "n_passages_shown": EVIDENCE_PASSAGES_SHOWN,
            })
        if docs:
            await self.db.elicitation_queue.insert_many(docs)
        # The fact-level block predates `priority`; stamp it so ordering is
        # well defined for rows written before this existed.
        await self.db.elicitation_queue.update_many(
            {"collection_version": collection_version,
             "priority": {"$exists": False}},
            {"$set": {"priority": PRIORITY_FACT_LEVEL, "corpus_id": None}})
        await self._ensure_indexes()

        panel_items = sum(1 for d in docs if d["comparison_item"])
        logger.info("evidence queue built: %d items (%d at panel depth)",
                    len(docs), panel_items)
        return {"status": "built", "queue_length": len(docs),
                "strata": len(cells), "comparison_items": panel_items,
                "panel_judgments_target": panel_items * HUMAN_PANEL_SIZE,
                "passages_shown": EVIDENCE_PASSAGES_SHOWN}

    async def next_item(self, expert_id: str,
                        collection_version: str = "1.0") -> Optional[QueueItem]:
        """The head of the queue that this expert may still do.

        'May still do' excludes: items they have already decided; items already
        decided by someone else unless the position needs more judgments; and
        **any fact they authored**.
        """
        # Calibration gate, enforced HERE rather than in the client
        # (advandeb_methods docs/10 section 5.3). An expert works the fixed
        # calibration set before their judgments enter either stratum. A
        # client-side gate would be bypassable and the stratum contamination
        # would be silent — the judgments would look exactly like any others.
        if not (await self.calibration_status(expert_id))["done"]:
            return None

        done = set()
        async for a in self.db.elicitations.find(
                {"expert_id": expert_id},
                {"sf_number": 1, "task": 1, "corpus_id": 1}):
            done.add(_item_key(a))
        authored = await self.authored_by_expert(expert_id)

        # `n_required` is satisfied by PANEL-tier judgments only
        # (advandeb_methods docs/10 section 2.2). A contributor may work the
        # same position and their judgment is recorded, but it does not
        # decrement the panel's requirement.
        #
        # Without this, open contributors silently "complete" comparison items
        # and the panel consensus is never collected — and the failure looks
        # exactly like healthy throughput until the analysis finds no panel
        # data at all.
        counts: Dict[tuple, int] = {}
        async for a in self.db.elicitations.find(
                {"tier": "panel"},
                {"sf_number": 1, "task": 1, "corpus_id": 1}):
            key = _item_key(a)
            counts[key] = counts.get(key, 0) + 1

        # Evidence first, then the fact-level block; seeded order within each
        # (see PRIORITY_EVIDENCE). Rows written before `priority` existed sort
        # as 1 via the backfill in build_evidence_queue.
        cursor = self.db.elicitation_queue.find(
            {"collection_version": collection_version}).sort(
                [("priority", 1), ("queue_position", 1)])
        async for q in cursor:
            key = _item_key(q)
            if key in done:
                continue
            n_done = counts.get(key, 0)
            needed = int(q.get("n_required", 1))
            if n_done >= needed:
                continue
            # Conflict of interest: an author never judges their own fact.
            # Two sources — the seeded queue for the core group, and the user
            # record for external contributors matched at approval.
            if expert_id in (q.get("authored_by") or []):
                continue
            if q["sf_number"] in authored:
                continue

            fact = await self.db.stylized_facts.find_one({
                "$or": [{"sf_number": q["sf_number"]},
                        {"sf_number": str(q["sf_number"])}]})
            if not fact:
                continue

            passages: List[EvidencePassage] = []
            n_total = None
            if q["task"] == "evidence":
                es = await self.db.evidence_sets.find_one(
                    {"_id": q.get("evidence_set_id")})
                if not es:
                    # Queued but not imported. Skip rather than serve an
                    # evidence task with no evidence: an expert cannot judge
                    # passages they were not shown, and a decision recorded
                    # against an empty set would be indistinguishable from a
                    # real one afterwards.
                    logger.warning("evidence set %s missing; skipping item %s",
                                   q.get("evidence_set_id"), q["queue_position"])
                    continue
                all_p = es.get("passages") or []
                n_total = len(all_p)
                keep = set(self.shown_passage_indices(
                    n_total, int(q.get("n_passages_shown") or n_total)))
                passages = [
                    EvidencePassage(
                        index=pp.get("index", i), text=pp.get("text", ""),
                        similarity=float(pp.get("similarity") or 0.0),
                        doi=pp.get("doi"), title=pp.get("title"),
                        year=pp.get("year"), document_id=pp.get("document_id"))
                    for i, pp in enumerate(all_p) if pp.get("index", i) in keep]

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
                corpus_id=q.get("corpus_id"),
                evidence_set_id=q.get("evidence_set_id"),
                evidence_content_hash=q.get("evidence_content_hash"),
                passages=passages,
                n_passages_total=n_total,
            )
        return None

    # ------------------------------------------------------------------ #
    # Decisions
    # ------------------------------------------------------------------ #

    async def tier_of(self, expert_id: str) -> Optional[str]:
        """The expert's tier right now, for stamping onto a new record."""
        try:
            u = await self.db.users.find_one({"_id": ObjectId(expert_id)},
                                             {"tier": 1, "roles": 1})
        except Exception:
            return None
        if not u:
            return None
        if u.get("tier"):
            return u["tier"]
        roles = u.get("roles") or []
        if "external_contributor" in roles:
            return "contributor"
        # No explicit tier: fail toward `contributor`, never toward `panel`.
        #
        # The asymmetry is the whole argument. Mislabelling a panel member as a
        # contributor loses data from the panel stratum — visible, and
        # recoverable by re-running. Mislabelling a contributor as panel
        # *contaminates* the panel stratum, silently: the record stamps
        # `panel`, every statistic still computes, and the agreement figures
        # the study rests on quietly stop describing a known population
        # (docs/10 section 1).
        #
        # Known panel members are stamped explicitly by
        # scripts/migrate_expert_tiers.py. Anyone reaching this line was never
        # admitted to the panel, so they are not in it.
        logger.warning(
            "expert %s has no explicit tier; defaulting to contributor. "
            "Panel membership must be assigned, not inferred.", expert_id)
        return "contributor"

    async def authored_by_expert(self, expert_id: str) -> set:
        """Fact numbers this expert authored, from their user record.

        The queue also carries `authored_by` per item; this covers external
        contributors matched at approval (docs/10 section 5.1), whose link
        lives on the user rather than in the seeded queue.
        """
        try:
            u = await self.db.users.find_one({"_id": ObjectId(expert_id)},
                                             {"authored_sf_numbers": 1})
        except Exception:
            return set()
        return set((u or {}).get("authored_sf_numbers") or [])

    @staticmethod
    def _evidence_problem(decision: ElicitationDecision,
                          q: Dict[str, Any]) -> Optional[str]:
        """Why this evidence decision cannot be recorded, or None.

        Validated on the server because each of these failures is silent. A
        decision missing its passage judgments still stores, still counts
        toward `n_required`, and still looks like a completed item — and the
        absence only surfaces when the agreement statistic is computed over a
        sample smaller than the queue says it is.
        """
        if decision.evidence_strength is None or decision.consensus_direction is None:
            return ("evidence decisions carry both fact-level scores "
                    "(evidence strength and consensus direction)")
        # The evidence hash is what makes "both panels read the same passages"
        # checkable rather than assumed (ADR 0003). A mismatch means the client
        # submitted against a different or a stale evidence set.
        expected = q.get("evidence_content_hash")
        if expected and decision.evidence_content_hash != expected:
            return ("evidence_content_hash does not match the queued evidence "
                    "set; the judgment would not be attributable to known "
                    "evidence")
        if not decision.passage_judgments:
            return ("evidence decisions carry a judgment for every passage "
                    "shown; passage agreement is the comparison this task "
                    "exists to support")
        return None

    async def submit(self, decision: ElicitationDecision,
                     expert_id: str,
                     collection_version: str = "1.0") -> Dict[str, Any]:
        """Record one decision. Refuses to overwrite an existing one."""
        q = await self.db.elicitation_queue.find_one({
            "collection_version": collection_version,
            "sf_number": decision.sf_number, "task": decision.task,
            "corpus_id": decision.corpus_id})
        if not q:
            return {"status": "error", "detail": "item not in queue"}

        if decision.task == "evidence":
            problem = self._evidence_problem(decision, q)
            if problem:
                return {"status": "error", "detail": problem}
        if expert_id in (q.get("authored_by") or []):
            return {"status": "error",
                    "detail": "expert authored this fact (conflict of interest)"}
        if decision.sf_number in await self.authored_by_expert(expert_id):
            return {"status": "error",
                    "detail": "expert authored this fact (conflict of interest)"}

        # The authoritative gate. next_item declines to serve live items before
        # calibration, but a crafted request could reach here directly, and the
        # whole point is that uncalibrated judgments never enter a stratum.
        cal = await self.calibration_status(expert_id)
        if not cal["done"]:
            return {"status": "error",
                    "detail": (f"calibration incomplete "
                               f"({cal['completed']}/{cal['total']}) — the "
                               "calibration set must be finished before "
                               "judgments enter a stratum")}

        tier = await self.tier_of(expert_id)
        prior = await self.db.elicitations.count_documents({
            "sf_number": decision.sf_number, "task": decision.task,
            "corpus_id": decision.corpus_id, "tier": tier})
        doc = {
            **decision.model_dump(),
            "expert_id": expert_id,
            # Stamped now, never resolved later (docs/10 section 2.1).
            "tier": tier,
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

        # Lets the client distinguish "queue exhausted" from "calibrate first",
        # both of which make /next return null. Additive, so the documented
        # /next contract (QueueItem | null) is unchanged.
        cal = await self.calibration_status(expert_id)

        rung, note, nxt = _rung(done)
        return ElicitationProgress(
            calibration_required=not cal["done"],
            calibration_completed=cal["completed"],
            calibration_total=cal["total"],
            total_queue=total, completed=done, completed_by_me=mine,
            median_seconds_per_item=statistics.median(times) if times else None,
            by_task=by_task, by_stratum=by_stratum,
            repeated_judgments=sum(1 for v in pairs.values() if v >= 2),
            rung=rung, rung_note=note, next_rung_at=nxt,
        )

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #

    async def history(self, expert_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """This expert's own past judgments, newest first.

        Visible to the person who made them (docs/10 section 8). Not to anyone
        else: seeing a colleague's answer before your own would destroy the
        independence the agreement statistics rest on.
        """
        limit = max(1, min(int(limit), 500))
        out: List[Dict[str, Any]] = []
        cursor = self.db.elicitations.find({"expert_id": expert_id}) \
            .sort("created_at", -1).limit(limit)
        async for a in cursor:
            fact = await self.db.stylized_facts.find_one(
                {"$or": [{"sf_number": a.get("sf_number")},
                         {"sf_number": str(a.get("sf_number"))}]},
                {"statement": 1})
            out.append({
                "sf_number": a.get("sf_number"),
                "statement": (fact or {}).get("statement", ""),
                "task": a.get("task"),
                "provenance_type": a.get("provenance_type"),
                "source_citation": a.get("source_citation"),
                "scope_verdict": a.get("scope_verdict"),
                "proposed_scope": a.get("proposed_scope"),
                "assessability": a.get("assessability"),
                "corpus_id": a.get("corpus_id"),
                "evidence_strength": a.get("evidence_strength"),
                "consensus_direction": a.get("consensus_direction"),
                "confidence": a.get("confidence", 3),
                "rationale": a.get("rationale", ""),
                "tier": a.get("tier"),
                "created_at": a.get("created_at"),
            })
        return out

    # ------------------------------------------------------------------ #
    # Guidelines
    # ------------------------------------------------------------------ #

    def guidelines(self) -> Dict[str, Any]:
        """The task definitions, served rather than duplicated in the client.

        Versioned: a mid-study guideline change invalidates prior judgments
        unless they are re-checked, so the version is stored on the record and
        the changelog is what makes that auditable (docs/02 section 7).
        """
        return {
            "version": GUIDELINES_VERSION,
            "tasks": [
                {
                    "task": "provenance",
                    "title": "Where does this fact come from?",
                    "help": (
                        "The collection is of mixed provenance and largely "
                        "untraced. Published facts must be cited to their "
                        "source; new ones are being published here for the "
                        "first time. `unknown` is an acceptable answer — "
                        "pretending to a provenance is worse than recording "
                        "the gap."),
                    "options": [
                        {"value": "published", "label": "Published",
                         "hint": "states a result already in the literature"},
                        {"value": "new", "label": "New",
                         "hint": "first stated here, not from a published source"},
                        {"value": "adapted", "label": "Adapted",
                         "hint": "a published result, materially restated"},
                        {"value": "unknown", "label": "Unknown",
                         "hint": "cannot establish — an acceptable answer"},
                    ],
                },
                {
                    "task": "scope",
                    "title": "What does this fact range over?",
                    "help": (
                        "84% of the collection states no organismal scope. "
                        "Scope adequacy compares evidence against a *claimed* "
                        "scope, so without one that check cannot be made at "
                        "all. Where the scope is implicit but clear, state it."),
                    "options": [
                        {"value": "stated", "label": "Scope stated",
                         "hint": "the statement says what it ranges over"},
                        {"value": "implicit", "label": "Implicit",
                         "hint": "not stated, but clear from context — give it below"},
                        {"value": "absent", "label": "Absent",
                         "hint": "no scope, and none can be inferred"},
                        {"value": "not_applicable", "label": "Not applicable",
                         "hint": "not a claim about organisms"},
                    ],
                },
                {
                    "task": "evidence",
                    "title": "How well does this literature support the fact?",
                    "help": (
                        "You are reading the same frozen passages the agent "
                        "panel read, in the same wording. That parity is the "
                        "point: it is what makes a disagreement between you "
                        "and the machine a difference of judgment rather than "
                        "of instructions.\n\n"
                        "Label each passage, then give the two scores. "
                        "`neutral` is a real answer and most passages are — "
                        "retrieval returns nearest neighbours, not evidence. "
                        "Judge only what the passage says; do not fill in "
                        "from what you know about the fact. There is a "
                        "separate place for that."),
                    "options": [
                        {"value": "supports", "label": "Supports",
                         "hint": "the passage is consistent with the fact"},
                        {"value": "contradicts", "label": "Contradicts",
                         "hint": "the passage is inconsistent with it"},
                        {"value": "neutral", "label": "Neutral",
                         "hint": "on another topic, or says nothing either way"},
                    ],
                },
                {
                    "task": "evidence_role",
                    "title": "Is the passage evidence, or a restatement?",
                    "help": (
                        "Asked of every passage you did not call neutral. "
                        "Nearly half of what reads as support for DEB turns "
                        "out to restate the theory rather than measure it "
                        "(restatement ratio 0.474 across 3,294 passages), and "
                        "a literature that agrees with itself is not the same "
                        "as one that has tested itself."),
                    "options": [
                        {"value": "primary_evidence", "label": "Primary evidence",
                         "hint": "reports a measurement or an observation"},
                        {"value": "restatement", "label": "Restatement",
                         "hint": "asserts the fact, citing it rather than testing it"},
                        {"value": "derivation", "label": "Derivation",
                         "hint": "follows from theory or a model, not from data"},
                        {"value": "review", "label": "Review",
                         "hint": "summarises others' findings"},
                    ],
                },
                {
                    "task": "evidence_strength",
                    "title": "Evidence strength (1-3)",
                    "help": (
                        "How much support these passages actually provide. "
                        "Unchanged from the predecessor's scale so every "
                        "existing score stays comparable."),
                    "options": [
                        {"value": "1", "label": "1 - weak or sparse",
                         "hint": "little or no real support here"},
                        {"value": "2", "label": "2 - moderate", "hint": "some support"},
                        {"value": "3", "label": "3 - strong",
                         "hint": "multiple clear supporting references"},
                    ],
                },
                {
                    "task": "consensus_direction",
                    "title": "Consensus direction (1-3)",
                    "help": (
                        "Which way the literature points, as a sign rather "
                        "than a magnitude. How strongly is carried by the "
                        "strength score and by contestation, not here."),
                    "options": [
                        {"value": "1", "label": "1 - against",
                         "hint": "predominantly contradicted, or mixed against"},
                        {"value": "2", "label": "2 - neutral",
                         "hint": "insufficient evidence either way"},
                        {"value": "3", "label": "3 - corroborated",
                         "hint": "supported, with little conflict"},
                    ],
                },
                {
                    "task": "assessability",
                    "title": "Can this be assessed as written?",
                    "help": (
                        "Some statements cannot be evaluated against "
                        "literature as written. Recording that is more useful "
                        "than quietly excluding them: the count is itself a "
                        "finding about the collection."),
                    "options": [
                        {"value": "assessable", "label": "Assessable",
                         "hint": "could be checked against literature as written"},
                        {"value": "too_vague", "label": "Too vague",
                         "hint": "no determinate claim to check"},
                        {"value": "compound", "label": "Compound",
                         "hint": "several claims in one sentence"},
                        {"value": "not_empirical", "label": "Not empirical",
                         "hint": "a modelling convention or definition"},
                        {"value": "unclear_terms", "label": "Unclear terms",
                         "hint": "key terms undefined or ambiguous"},
                    ],
                },
            ],
        }

    # ------------------------------------------------------------------ #
    # Calibration
    # ------------------------------------------------------------------ #

    async def seed_calibration(self, force: bool = False) -> Dict[str, Any]:
        """Build the fixed calibration set. Idempotent.

        **Every case has a documented reference answer, not an invented one.**
        Only the provenance task admits genuine references at present: facts
        1201-1236 are published (Sousa et al. 2008 / Kooijman 2020) and
        1237-1262 are new (Heraklion workshop), both recorded during the
        collection build. Scope cases are drawn only from the unambiguous ends
        of the distribution — a statement either carries an explicit organismal
        quantifier or plainly carries none — never the contested middle.

        What calibration measures is therefore agreement with a **documented
        reference**, not with truth. That distinction is stated to the expert.
        """
        existing = await self.db.elicitation_calibration.count_documents({})
        if existing and not force:
            return {"status": "exists", "n": existing}
        if force:
            await self.db.elicitation_calibration.delete_many({})

        cases: List[Dict[str, Any]] = []

        async def _add(fact, task, reference, explanation, basis):
            cases.append({
                "calibration_id": f"cal_{task}_{fact['sf_number']}",
                "order": len(cases),
                "task": task,
                "sf_number": int(fact["sf_number"]),
                "statement": fact.get("statement", ""),
                "statement_sha256": fact.get("statement_sha256", ""),
                "category": fact.get("category", ""),
                "reference": reference,
                "explanation": explanation,
                "reference_basis": basis,
            })

        # --- provenance: published (documented citation) ---
        n = 0
        async for f in self.db.stylized_facts.find(
                {"provenance_type": "published"}).sort("sf_number", 1):
            if n >= 5:
                break
            await _add(f, "provenance", {"provenance_type": "published"},
                       "This is one of the core DEB rules synthesized by "
                       "Sousa et al. (2008) and Kooijman (2020); its source is "
                       "recorded in the collection.",
                       "collection provenance record")
            n += 1

        # --- provenance: new (workshop-formulated) ---
        n = 0
        async for f in self.db.stylized_facts.find(
                {"provenance_type": "new"}).sort("sf_number", 1):
            if n >= 5:
                break
            await _add(f, "provenance", {"provenance_type": "new"},
                       "Formulated at the AdvanDEB Heraklion workshop in June "
                       "2025 and stated here for the first time, so it has no "
                       "prior published source.",
                       "collection provenance record")
            n += 1

        # --- scope: unambiguous ends only ---
        import re as _re
        explicit = _re.compile(
            r"\b(all|most|many|every|some)\s+(species|organisms?|animals?|"
            r"plants?|taxa|ectotherms?|endotherms?)\b", _re.I)
        got_stated = got_absent = 0
        async for f in self.db.stylized_facts.find({}).sort("sf_number", 1):
            st = f.get("statement", "")
            if got_stated < 3 and explicit.search(st):
                await _add(f, "scope", {"scope_verdict": "stated"},
                           "The statement carries an explicit organismal "
                           "quantifier, so the scope is stated rather than "
                           "inferred.", "explicit quantifier in the statement")
                got_stated += 1
            elif (got_absent < 2 and len(st.split()) > 8
                  and not _re.search(
                      r"\b(species|organisms?|animals?|plants?|taxa|cells?|"
                      r"individuals?|ectotherms?|endotherms?|fish|mammals?|"
                      r"birds?|insects?|bacteri\w*|algae?|embryos?|larva\w*|"
                      r"juveniles?|adults?|populations?|tissues?)\b", st, _re.I)):
                await _add(f, "scope", {"scope_verdict": "absent"},
                           "The statement names no organism, life stage or "
                           "taxon at all, so there is no claimed scope to "
                           "compare evidence against.",
                           "no organismal noun in the statement")
                got_absent += 1
            if got_stated >= 3 and got_absent >= 2:
                break

        for c in cases:
            c["order"] = cases.index(c)
        if cases:
            await self.db.elicitation_calibration.insert_many(cases)
            await self.db.elicitation_calibration.create_index("order")
            await self.db.elicitation_calibration_results.create_index(
                [("expert_id", 1), ("calibration_id", 1)], unique=True)
        return {"status": "built", "n": len(cases)}

    async def calibration_next(self, expert_id: str) -> Optional[Dict[str, Any]]:
        """The next calibration case this expert has not answered."""
        total = await self.db.elicitation_calibration.count_documents({})
        if not total:
            await self.seed_calibration()
            total = await self.db.elicitation_calibration.count_documents({})
        done = set()
        async for r in self.db.elicitation_calibration_results.find(
                {"expert_id": expert_id}, {"calibration_id": 1}):
            done.add(r["calibration_id"])
        cursor = self.db.elicitation_calibration.find({}).sort("order", 1)
        async for c in cursor:
            if c["calibration_id"] in done:
                continue
            return {
                "calibration_id": c["calibration_id"],
                "queue_position": -1,
                "task": c["task"],
                "sf_number": c["sf_number"],
                "statement": c["statement"],
                "statement_sha256": c.get("statement_sha256", ""),
                "category": c.get("category", ""),
                "collection_version": "1.0",
                "stratum": "calibration",
                "completed": len(done),
                "total": total,
            }
        return None

    async def calibration_submit(self, decision, expert_id: str) -> Dict[str, Any]:
        """Score one calibration answer and give immediate feedback.

        Calibration teaches, so the reference is shown straight away rather
        than withheld. The result is stored as a **quality signal**, never as
        an automatic exclusion gate: auto-excluding low-agreement participants
        would quietly select for people who agree with the reference, which
        manufactures the consensus the study is trying to measure
        (docs/10 section 7).
        """
        c = await self.db.elicitation_calibration.find_one(
            {"calibration_id": decision.calibration_id})
        if not c:
            return {"status": "error", "detail": "unknown calibration case"}

        ref = c.get("reference", {})
        given = {
            "provenance": decision.provenance_type,
            "scope": decision.scope_verdict,
            "assessability": decision.assessability,
        }.get(c["task"])
        expected = (ref.get("provenance_type") or ref.get("scope_verdict")
                    or ref.get("assessability"))
        correct = bool(given is not None and given == expected)

        await self.db.elicitation_calibration_results.update_one(
            {"expert_id": expert_id, "calibration_id": c["calibration_id"]},
            {"$set": {
                "expert_id": expert_id,
                "calibration_id": c["calibration_id"],
                "task": c["task"],
                "given": given,
                "expected": expected,
                "correct": correct,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
                "time_spent_s": decision.time_spent_s,
                "created_at": datetime.now(timezone.utc),
            }}, upsert=True)

        total = await self.db.elicitation_calibration.count_documents({})
        completed = await self.db.elicitation_calibration_results.count_documents(
            {"expert_id": expert_id})
        return {
            "correct": correct,
            "reference": {**ref, "basis": c.get("reference_basis")},
            "explanation": c.get("explanation", ""),
            "completed": completed,
            "total": total,
        }

    async def calibration_status(self, expert_id: str) -> Dict[str, Any]:
        total = await self.db.elicitation_calibration.count_documents({})
        results = [r async for r in
                   self.db.elicitation_calibration_results.find(
                       {"expert_id": expert_id})]
        return {
            "total": total,
            "completed": len(results),
            "correct": sum(1 for r in results if r.get("correct")),
            "done": bool(total) and len(results) >= total,
        }

    # ------------------------------------------------------------------ #
    # Admin statistics
    # ------------------------------------------------------------------ #

    async def admin_stats(self, collection_version: str = "1.0") -> Dict[str, Any]:
        """Where the effort has gone, and what the panel still owes.

        `panel_coverage` is the number that matters operationally: positions
        whose `n_required` is met **by panel-tier judgments**. A dashboard that
        counted all judgments would show healthy progress while the panel
        consensus went uncollected.
        """
        by_stratum: Dict[str, int] = {}
        by_task: Dict[str, int] = {}
        by_tier: Dict[str, int] = {}
        per_expert: Dict[str, Dict[str, Any]] = {}
        panel_counts: Dict[tuple, int] = {}

        async for a in self.db.elicitations.find({}):
            st = a.get("stratum", "?")
            by_stratum[st] = by_stratum.get(st, 0) + 1
            tk = a.get("task", "?")
            by_task[tk] = by_task.get(tk, 0) + 1
            tier = a.get("tier") or "unknown"
            by_tier[tier] = by_tier.get(tier, 0) + 1
            e = per_expert.setdefault(
                a.get("expert_id", "?"),
                {"n": 0, "times": [], "n_by_record_tier": {}})
            e["n"] += 1
            # Counted by the tier STAMPED ON EACH RECORD, not by the person's
            # current tier (docs/10 section 2.1). An expert promoted from
            # contributor to panel has records under both, and collapsing them
            # under their present tier would label historical contributor-tier
            # judgments as panel — exactly the mixing the write-time stamp
            # exists to prevent.
            e["n_by_record_tier"][tier] = e["n_by_record_tier"].get(tier, 0) + 1
            if a.get("time_spent_s"):
                e["times"].append(float(a["time_spent_s"]))
            if tier == "panel":
                key = (a.get("sf_number"), a.get("task"))
                panel_counts[key] = panel_counts.get(key, 0) + 1

        met = pending = 0
        async for q in self.db.elicitation_queue.find(
                {"collection_version": collection_version},
                {"sf_number": 1, "task": 1, "n_required": 1}):
            need = int(q.get("n_required", 1))
            have = panel_counts.get((q["sf_number"], q["task"]), 0)
            if have >= need:
                met += 1
            else:
                pending += 1

        experts = []
        for eid, v in per_expert.items():
            name, current_tier = eid, None
            try:
                u = await self.db.users.find_one({"_id": ObjectId(eid)},
                                                 {"full_name": 1, "email": 1,
                                                  "tier": 1})
                if u:
                    name = u.get("full_name") or u.get("email") or eid
                    current_tier = u.get("tier")
            except Exception:
                pass
            cal = await self.calibration_status(eid)
            experts.append({
                "name": name,
                # The person's tier now — for routing and display only.
                "current_tier": current_tier,
                # What their judgments actually count as, by stamped record
                # tier. This is the figure any coverage claim must rest on.
                "n_by_record_tier": v["n_by_record_tier"],
                # Kept for display compatibility; equals current_tier and is
                # deliberately NOT what the counts are aggregated by.
                "tier": current_tier,
                "n": v["n"],
                "median_s": (statistics.median(v["times"])
                             if v["times"] else None),
                # Who is cleared to contribute at all (docs/10 section 5.3).
                "calibration": {"completed": cal["completed"],
                                "total": cal["total"],
                                "correct": cal["correct"],
                                "done": cal["done"]},
            })
        experts.sort(key=lambda x: -x["n"])

        # Experts who hold the capability but have not cleared calibration, and
        # so are contributing nothing yet — the number an administrator needs
        # to chase.
        uncleared = []
        async for u in self.db.users.find(
                {"capabilities": "sf_elicitation"},
                {"full_name": 1, "email": 1, "tier": 1}):
            cal = await self.calibration_status(str(u["_id"]))
            if not cal["done"]:
                uncleared.append({
                    "name": u.get("full_name") or u.get("email"),
                    "tier": u.get("tier"),
                    "calibration": cal,
                })

        done = sum(by_task.values())
        rung, note, nxt = _rung(done)
        # Expert-asserted evidence, summarised corpus-wide. `recall_misses` is
        # the headline: papers the corpus held that retrieval never surfaced,
        # each named by an expert who knew it was relevant (docs/09 §2.5a).
        try:
            from app.services.expert_reference_service import (
                ExpertReferenceService,
            )
            expert_refs = await ExpertReferenceService().recall_summary()
        except Exception as exc:  # never let a dashboard extra break the page
            logger.warning("recall summary unavailable: %s", exc)
            expert_refs = None

        return {
            "expert_references": expert_refs,
            "by_stratum": by_stratum, "by_task": by_task, "by_tier": by_tier,
            "by_expert": experts,
            "by_record_tier": by_tier,
            "awaiting_calibration": uncleared,
            "rung": rung, "rung_note": note, "next_rung_at": nxt,
            "panel_coverage": {"n_required_met": met,
                               "n_required_pending": pending},
        }
