"""
Aggregated expert verdicts on stylized facts, for display in the KB.

Read-only summaries of the `evidence` judgments in `elicitations`. What they
may and may not say is a methods question as much as a display one:

* **Never averaged.** Both scores are ordinal (advandeb_methods ADR 0004), so
  a verdict is reported as distributions, the most common label with its
  count, and at most a median that is itself a point on the scale.
* **Tiers never pooled.** Groups are per (fact, corpus, tier), by the tier
  stamped on each record. The panel is the headline; contributors are shown
  separately and never merged into the panel's numbers (docs/10 section 2).
* **Nothing below a minimum n.** A group with fewer than
  ``EXPERT_VERDICT_MIN_N`` judgments is left out entirely, rather than shown as
  "1 of 1".
* **Not shown to someone who may still judge the fact.** Seeing colleagues'
  verdicts first would anchor them; such a summary carries
  ``withheld="open_for_you"`` and no groups.
"""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

# Stamped on each judgment at write time; aggregation groups by it.
VerdictTier = Literal["panel", "contributor"]

# consensus_direction 3 / 2 / 1, as a word.
VerdictLabel = Literal["supported", "inconclusive", "against"]

# Why a fact's verdict is not shown to this user.
WithheldReason = Literal["open_for_you"]


class ConsensusDistribution(BaseModel):
    """How many judgments gave each consensus direction."""
    against: int = 0
    inconclusive: int = 0
    supported: int = 0


class StrengthDistribution(BaseModel):
    """How many judgments gave each evidence strength."""
    weak: int = 0
    moderate: int = 0
    strong: int = 0


class ExpertVerdictGroup(BaseModel):
    """One (fact, corpus, tier) group with at least the minimum n judgments.

    `majority_label` is the most common consensus label, or null when two
    labels tie for most common; `majority_n` is that top count either way.
    `strength_median` is the lower median on the 1-3 scale (1 weak,
    2 moderate, 3 strong) — never interpolated between two scale points.
    """
    corpus_id: str
    tier: VerdictTier
    n: int
    n_experts: int
    majority_label: Optional[VerdictLabel] = None
    majority_n: int
    consensus: ConsensusDistribution
    strength: StrengthDistribution
    strength_median: Optional[int] = None


class ExpertVerdictSummary(BaseModel):
    """The verdict on one stylized fact, as this user may see it."""
    sf_number: int
    withheld: Optional[WithheldReason] = None
    groups: List[ExpertVerdictGroup] = []


class ExpertVerdictBatch(BaseModel):
    """Verdicts for several facts, keyed by sf_number as a string."""
    min_n: int
    verdicts: Dict[str, ExpertVerdictSummary] = {}
