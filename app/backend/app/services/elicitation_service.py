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

# Bumped whenever the task definitions change. A mid-study guideline change
# invalidates prior judgments unless they are re-checked, so the version is
# recorded rather than implied (docs/02 section 7).
GUIDELINES_VERSION = "1.0"

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
                {"tier": "panel"}, {"sf_number": 1, "task": 1}):
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
        # Project members admitted before tiering existed are panel members:
        # they are the named DEB experts the comparison was designed around.
        roles = u.get("roles") or []
        if "external_contributor" in roles:
            return "contributor"
        return "panel"

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
        if decision.sf_number in await self.authored_by_expert(expert_id):
            return {"status": "error",
                    "detail": "expert authored this fact (conflict of interest)"}

        tier = await self.tier_of(expert_id)
        prior = await self.db.elicitations.count_documents({
            "sf_number": decision.sf_number, "task": decision.task,
            "tier": tier})
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

        rung, note, nxt = _rung(done)
        return ElicitationProgress(
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
                {"n": 0, "times": [], "tier": tier})
            e["n"] += 1
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
            name = eid
            try:
                u = await self.db.users.find_one({"_id": ObjectId(eid)},
                                                 {"full_name": 1, "email": 1})
                if u:
                    name = u.get("full_name") or u.get("email") or eid
            except Exception:
                pass
            experts.append({
                "name": name, "tier": v["tier"], "n": v["n"],
                "median_s": (statistics.median(v["times"])
                             if v["times"] else None),
            })
        experts.sort(key=lambda x: -x["n"])

        done = sum(by_task.values())
        rung, note, nxt = _rung(done)
        return {
            "by_stratum": by_stratum, "by_task": by_task, "by_tier": by_tier,
            "by_expert": experts,
            "rung": rung, "rung_note": note, "next_rung_at": nxt,
            "panel_coverage": {"n_required_met": met,
                               "n_required_pending": pending},
        }
