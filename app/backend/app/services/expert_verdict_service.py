"""
ExpertVerdictService — the aggregated expert verdict next to each stylized fact.

Reads the `evidence` judgments in `elicitations` and summarises them per
(fact, corpus, tier). The rules, and why each exists, are in
``app/models/expert_verdict.py``; in short: distributions and counts, never
means (ADR 0004); panel and contributor never pooled, grouped by the tier
stamped on each record; nothing below ``EXPERT_VERDICT_MIN_N``; and nothing at
all for a user who may still be asked to judge the fact.

What "open" and "judged" mean is not restated here. An item is open while its
panel-tier judgments are fewer than its `n_required`, and an expert has judged
it once they hold a record with its item key — both exactly as
``ElicitationService._head`` decides what to serve, with the same key
(``_item_key``). If those definitions drifted apart, a verdict could be shown
to an expert the queue is about to ask, which is the one thing the withholding
exists to prevent.

Two database round trips per request whatever the number of facts: one
aggregation over `elicitations`, and — only for a potential judge — one query
over `elicitation_queue`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from bson import ObjectId

from app.core.config import settings
from app.core.database import get_database
from app.core.dependencies import CAP_SF_ELICITATION, ROLE_EXTERNAL_CONTRIBUTOR
from app.models.expert_verdict import (
    ConsensusDistribution, ExpertVerdictGroup, ExpertVerdictSummary,
    StrengthDistribution,
)
from app.services.elicitation_service import (
    EVIDENCE_COMPARISON_CORPUS, EVIDENCE_CORPORA, _item_key,
)

logger = logging.getLogger(__name__)

# The only task whose judgments are a verdict on the fact. Provenance, scope
# and assessability are metadata about the statement, not about whether the
# literature supports it.
VERDICT_TASK = "evidence"

# Panel first: it is the headline, and the order groups are returned in.
TIERS = ("panel", "contributor")

CONSENSUS_LABELS = {1: "against", 2: "inconclusive", 3: "supported"}
STRENGTH_LABELS = {1: "weak", 2: "moderate", 3: "strong"}

# One page of the Facts view is at most 200 rows; this leaves headroom while
# keeping one request's `$in` list bounded.
MAX_BATCH = 500

_SCALE = [1, 2, 3]


def min_n() -> int:
    """The smallest group shown. Read per call, so a changed setting applies."""
    return max(1, int(settings.EXPERT_VERDICT_MIN_N))


def parse_sf_numbers(raw: str) -> List[int]:
    """``"3,1,3"`` → ``[3, 1]``: integers, de-duplicated, order kept.

    Raises ValueError on a non-integer or on more than ``MAX_BATCH`` numbers.
    """
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValueError(
            "sf_numbers must be a comma-separated list of integers") from None
    nums = list(dict.fromkeys(nums))
    if len(nums) > MAX_BATCH:
        raise ValueError(f"at most {MAX_BATCH} sf_numbers per request")
    return nums


# --------------------------------------------------------------------------- #
# Who sees what                                                                #
# --------------------------------------------------------------------------- #

def is_potential_judge(user: Mapping[str, Any], tier: Optional[str]) -> bool:
    """May this user still be asked to judge facts?

    Anyone holding the elicitation capability, an external contributor, or
    anyone with a panel or contributor tier. Curators and administrators
    without a tier are not: they reach the elicitation routes by role, but the
    queue only serves people admitted to a stratum.
    """
    caps = user.get("capabilities") or []
    roles = user.get("roles") or []
    return (CAP_SF_ELICITATION in caps
            or ROLE_EXTERNAL_CONTRIBUTOR in roles
            or tier in TIERS)


def open_for_user(queue_items: Iterable[Mapping[str, Any]],
                  panel_counts: Mapping[tuple, int],
                  judged_by_user: Set[tuple]) -> Set[int]:
    """Facts with at least one open evidence item this user has not judged.

    Open and judged are decided as ``ElicitationService._head`` decides them:
    an item is open while panel-tier judgments under its ``_item_key`` are
    fewer than its `n_required`; it is judged by this user once they hold any
    record under that key.
    """
    out: Set[int] = set()
    for q in queue_items:
        key = _item_key(q)
        if key in judged_by_user:
            continue
        if panel_counts.get(key, 0) >= int(q.get("n_required", 1)):
            continue
        out.add(q.get("sf_number"))
    return out


# --------------------------------------------------------------------------- #
# Summarising one group                                                        #
# --------------------------------------------------------------------------- #

def majority(consensus: ConsensusDistribution) -> Tuple[Optional[str], int]:
    """The most common consensus label and its count.

    The label is None when two labels share the top count — a split panel is
    reported as split, not resolved by an arbitrary order.
    """
    counts = consensus.model_dump()
    top = max(counts.values(), default=0)
    if top == 0:
        return None, 0
    leaders = [label for label, n in counts.items() if n == top]
    return (leaders[0] if len(leaders) == 1 else None), top


def lower_median(counts_by_score: Mapping[int, int]) -> Optional[int]:
    """The lower median of an ordinal sample given as counts per scale point.

    With an even n the two middle values may differ; the lower one is
    reported rather than their midpoint, which would be an average of two
    ordinal scores and a value the scale does not have.
    """
    n = sum(counts_by_score.values())
    if n <= 0:
        return None
    target = (n - 1) // 2
    seen = 0
    for score in sorted(counts_by_score):
        seen += counts_by_score[score]
        if seen > target:
            return score
    return None


def summarise_group(row: Mapping[str, Any], minimum: int) -> Optional[ExpertVerdictGroup]:
    """One aggregation row → a group, or None below the minimum n.

    `row` carries ``corpus_id``, ``tier``, ``n``, ``n_experts`` and the counts
    ``c1``..``c3`` (consensus direction) and ``s1``..``s3`` (strength).
    """
    n = int(row.get("n") or 0)
    if n < max(1, minimum) or row.get("tier") not in TIERS:
        return None
    c = {v: int(row.get(f"c{v}") or 0) for v in _SCALE}
    s = {v: int(row.get(f"s{v}") or 0) for v in _SCALE}
    consensus = ConsensusDistribution(**{CONSENSUS_LABELS[v]: k for v, k in c.items()})
    strength = StrengthDistribution(**{STRENGTH_LABELS[v]: k for v, k in s.items()})
    label, top = majority(consensus)
    return ExpertVerdictGroup(
        corpus_id=str(row.get("corpus_id") or ""),
        tier=row["tier"],
        n=n,
        n_experts=int(row.get("n_experts") or 0),
        majority_label=label,
        majority_n=top,
        consensus=consensus,
        strength=strength,
        strength_median=lower_median(s),
    )


def _group_order(g: ExpertVerdictGroup) -> tuple:
    """The comparison corpus first, then the other elicited corpora, then any
    others; panel before contributor within a corpus."""
    corpora = [EVIDENCE_COMPARISON_CORPUS] + [
        c for c in EVIDENCE_CORPORA if c != EVIDENCE_COMPARISON_CORPUS]
    rank = corpora.index(g.corpus_id) if g.corpus_id in corpora else len(corpora)
    return (rank, g.corpus_id, TIERS.index(g.tier))


# --------------------------------------------------------------------------- #
# Service                                                                      #
# --------------------------------------------------------------------------- #

def _count_if(cond: Any) -> Dict[str, Any]:
    return {"$sum": {"$cond": [cond, 1, 0]}}


def verdict_pipeline(sf_numbers: List[int], collection_version: str,
                     user_id: str) -> List[Dict[str, Any]]:
    """One row per (fact, corpus, stamped tier) among the requested facts.

    A row carries two kinds of count, deliberately apart:

    * ``recorded`` — every evidence record under the item key, whatever its
      version or scores. Summed over panel rows it is exactly what
      ``ElicitationService._panel_counts`` counts, so "open" agrees with the
      queue. ``mine`` says whether this user holds one of them.
    * ``n``, ``n_experts``, ``c*``, ``s*`` — only records of this collection
      version, a known tier and both scores on the 1-3 scale: what the verdict
      is computed from.
    """
    counted = {"$and": [
        {"$eq": ["$collection_version", collection_version]},
        {"$in": ["$tier", list(TIERS)]},
        {"$in": ["$consensus_direction", _SCALE]},
        {"$in": ["$evidence_strength", _SCALE]},
    ]}
    group: Dict[str, Any] = {
        "_id": {"sf_number": "$sf_number", "corpus_id": "$corpus_id",
                "tier": "$tier"},
        "recorded": {"$sum": 1},
        "mine": {"$max": {"$eq": ["$expert_id", user_id]}},
        "n": _count_if("$counted"),
        "experts": {"$addToSet": {"$cond": ["$counted", "$expert_id", None]}},
    }
    for v in _SCALE:
        group[f"c{v}"] = _count_if(
            {"$and": ["$counted", {"$eq": ["$consensus_direction", v]}]})
        group[f"s{v}"] = _count_if(
            {"$and": ["$counted", {"$eq": ["$evidence_strength", v]}]})
    project: Dict[str, Any] = {
        "_id": 0,
        "sf_number": "$_id.sf_number",
        "corpus_id": "$_id.corpus_id",
        "tier": "$_id.tier",
        "recorded": 1, "mine": 1, "n": 1,
        # Distinct experts, without shipping their ids out of the database.
        "n_experts": {"$size": {"$setDifference": ["$experts", [None]]}},
    }
    for v in _SCALE:
        project[f"c{v}"] = 1
        project[f"s{v}"] = 1
    return [
        {"$match": {"task": VERDICT_TASK, "sf_number": {"$in": sf_numbers}}},
        {"$addFields": {"counted": counted}},
        {"$group": group},
        {"$project": project},
    ]


class ExpertVerdictService:
    """Aggregated, access-aware expert verdicts on stylized facts."""

    def __init__(self) -> None:
        self.db = get_database()

    async def _stored_tier(self, user_id: str) -> Optional[str]:
        try:
            u = await self.db.users.find_one({"_id": ObjectId(user_id)},
                                             {"tier": 1})
        except Exception:
            return None
        return (u or {}).get("tier")

    async def _potential_judge(self, user: Mapping[str, Any]) -> bool:
        # Capability and role ride on the request's user; the tier does not,
        # so it is read only when nothing else already decides.
        if is_potential_judge(user, None):
            return True
        return is_potential_judge(
            user, await self._stored_tier(str(user.get("id") or "")))

    async def summaries(self, sf_numbers: Iterable[int],
                        user: Mapping[str, Any]) -> Dict[int, ExpertVerdictSummary]:
        """A summary for every requested fact, as this user may see it.

        Every requested number gets an entry; a fact with no qualifying group
        has an empty `groups` list, and a fact withheld from this user has
        `withheld="open_for_you"` and no groups at all.
        """
        nums = list(dict.fromkeys(int(n) for n in sf_numbers))
        if not nums:
            return {}
        minimum = min_n()
        version = settings.EXPERT_VERDICT_COLLECTION_VERSION
        user_id = str(user.get("id") or "")

        groups: Dict[int, List[ExpertVerdictGroup]] = {n: [] for n in nums}
        panel_counts: Dict[tuple, int] = {}
        judged: Set[tuple] = set()
        async for row in self.db.elicitations.aggregate(
                verdict_pipeline(nums, version, user_id)):
            key = _item_key({"sf_number": row.get("sf_number"),
                             "task": VERDICT_TASK,
                             "corpus_id": row.get("corpus_id")})
            if row.get("tier") == "panel":
                panel_counts[key] = panel_counts.get(key, 0) + int(row.get("recorded") or 0)
            if row.get("mine"):
                judged.add(key)
            g = summarise_group(row, minimum)
            if g is not None and row.get("sf_number") in groups:
                groups[row["sf_number"]].append(g)

        withheld: Set[int] = set()
        if await self._potential_judge(user):
            queue = [q async for q in self.db.elicitation_queue.find(
                {"collection_version": version, "task": VERDICT_TASK,
                 "sf_number": {"$in": nums}},
                {"sf_number": 1, "task": 1, "corpus_id": 1, "n_required": 1})]
            withheld = open_for_user(queue, panel_counts, judged)

        out: Dict[int, ExpertVerdictSummary] = {}
        for n in nums:
            if n in withheld:
                out[n] = ExpertVerdictSummary(sf_number=n, withheld="open_for_you")
            else:
                out[n] = ExpertVerdictSummary(
                    sf_number=n, groups=sorted(groups[n], key=_group_order))
        return out

    async def summary(self, sf_number: int,
                      user: Mapping[str, Any]) -> ExpertVerdictSummary:
        return (await self.summaries([sf_number], user))[int(sf_number)]
