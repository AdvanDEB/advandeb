"""
Expert elicitation on stylized facts.

Elicitation records live in MongoDB alongside users, submissions and chat —
the application store. Panel verdicts, consensus records and standing live in
ArangoDB with the knowledge graph.

"Elicitation" rather than "annotation" deliberately: this is the structured
gathering of expert judgment, in the sense the term carries in risk analysis
and Delphi-style studies, not the labelling of data by workers. The experts are
domain authorities whose judgment is one of the two consensus processes the
method compares (advandeb_methods docs/09 section 0).

The design constraints these models exist to satisfy are specified in
``advandeb_methods/docs/02-elicitation-protocol.md``:

* **Interruptible sampling.** Total expert availability is unknown, so the
  queue is a fixed, seeded order whose every prefix is a valid reweightable
  sample. Experts draw strictly from the head; they never choose an item.
* **Conflict of interest.** An expert is never assigned a stylized fact they
  authored. Facts 1201-1236 have a known author who is also an expert.
* **Anchoring control.** Whether a reviewer opened the machine verdict is
  logged, so exposure is measurable rather than assumed.
* **Time on task** is captured automatically; it is the throughput figure the
  method paper needs and it is free to collect here.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# Day-one tasks operate on the statement alone and need no evidence set, so
# elicitation can begin before the consensus pipeline runs inside the platform.
TaskType = Literal["provenance", "scope", "assessability"]

ProvenanceType = Literal["published", "new", "adapted", "unknown"]

# 84% of the collection states no organismal scope (advandeb_methods docs/06
# 6.1a). Scope adequacy cannot be computed without one, so eliciting it is the
# highest-value fact-level task available before evidence sets exist.
ScopeVerdict = Literal["stated", "implicit", "absent", "not_applicable"]

AssessabilityVerdict = Literal[
    "assessable", "too_vague", "compound", "not_empirical", "unclear_terms"
]


class QueueItem(BaseModel):
    """One unit of work, as handed to an expert."""

    queue_position: int
    task: TaskType
    sf_number: int
    statement: str
    statement_sha256: str
    category: str
    collection_version: str
    # Present only where it already exists; deliberately not shown first in the
    # UI for tasks where it could anchor the expert.
    existing_provenance: Optional[ProvenanceType] = None
    existing_source_citation: Optional[str] = None
    # Legacy 1-100 score from the older pipeline, collapsed by default.
    legacy_assessment: Optional[Dict[str, Any]] = None
    # True when this position needs more than one independent judgment.
    repeated_judgment: bool = False
    # How many independent expert judgments this position needs. Comparison
    # items take the full human panel so the human consensus has the same
    # structure as the agent consensus (advandeb_methods docs/09 section 5.3).
    n_required: int = 1
    comparison_item: bool = False
    stratum: str


class ElicitationDecision(BaseModel):
    """What an expert submits. One per (task, fact, expert)."""

    task: TaskType
    sf_number: int
    statement_sha256: str

    # --- task payloads: exactly one is filled ---
    provenance_type: Optional[ProvenanceType] = None
    source_citation: Optional[str] = None

    scope_verdict: Optional[ScopeVerdict] = None
    proposed_scope: Optional[str] = None
    proposed_taxon_ids: List[int] = []

    assessability: Optional[AssessabilityVerdict] = None

    # --- required of every decision ---
    confidence: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)

    # Which evidence condition this judgment was made under
    # (advandeb_methods docs/09 section 5.2). `matched` = the expert saw the
    # same frozen evidence set the agents saw, isolating judgment difference.
    # `expertise` = judged from domain knowledge alone, as in the predecessor
    # review. Running both is what lets a human-machine disagreement be
    # decomposed rather than merely observed.
    evidence_condition: Optional[Literal["matched", "expertise"]] = "expertise"

    # --- captured by the client ---
    time_spent_s: Optional[float] = None
    machine_verdict_expanded: Optional[bool] = None


class ElicitationRecord(ElicitationDecision):
    """A stored decision."""

    id: str = Field(alias="_id")
    expert_id: str
    # The expert's tier **as it was at the moment of judgment**, stamped at
    # write time and never resolved later (advandeb_methods docs/10 section
    # 2.1). If tier were looked up at analysis time, promoting one contributor
    # to the panel would retroactively move all their past judgments into the
    # panel stratum — silently changing the sampling frame and invalidating
    # every agreement statistic already computed from it. Same principle as
    # `panel_id` on machine records: the instrument that produced a measurement
    # is a property of the measurement.
    tier: Optional[Literal["panel", "contributor"]] = None
    queue_position: int
    stratum: str
    collection_version: str
    round: Literal["primary", "secondary", "adjudication"] = "primary"
    gold_split: Optional[Literal["pilot", "dev", "test", "audit"]] = None
    sampling_weight: Optional[float] = None
    # True when this item was routed away from an author of the fact.
    author_excluded: Optional[bool] = None
    created_at: datetime

    class Config:
        populate_by_name = True


class ElicitationProgress(BaseModel):
    """Where the effort has actually gone — per expert and overall.

    Reported against the claims ladder (docs/02 4.2) rather than as a bare
    count, so it is visible at any moment which conclusions the elicitation so
    far can support.
    """

    # True until the expert has finished the calibration set. Lets the client
    # tell "queue exhausted" from "calibrate first" — both make /next return
    # null, and the documented /next contract stays unchanged.
    calibration_required: bool = False
    calibration_completed: int = 0
    calibration_total: int = 0

    total_queue: int
    completed: int
    completed_by_me: int
    median_seconds_per_item: Optional[float] = None
    by_task: Dict[str, int] = {}
    by_stratum: Dict[str, int] = {}
    repeated_judgments: int = 0
    rung: str = "R0"
    rung_note: str = ""
    next_rung_at: Optional[int] = None


# --------------------------------------------------------------------------- #
# Guidelines, history and calibration
# --------------------------------------------------------------------------- #


class TaskOption(BaseModel):
    """One selectable answer for a task, with the hint shown beside it."""
    value: str
    label: str
    hint: str


class TaskGuideline(BaseModel):
    task: TaskType
    title: str
    help: str
    options: List[TaskOption] = []


class Guidelines(BaseModel):
    """Served rather than duplicated in the client.

    The guidelines are a versioned instrument: a mid-study change invalidates
    prior judgments unless they are re-checked, so the version travels with
    them (docs/02 section 7).
    """
    tasks: List[TaskGuideline] = []
    version: str


class HistoryItem(BaseModel):
    """One of the expert's own past judgments."""
    sf_number: int
    statement: str
    task: TaskType
    provenance_type: Optional[ProvenanceType] = None
    source_citation: Optional[str] = None
    scope_verdict: Optional[ScopeVerdict] = None
    proposed_scope: Optional[str] = None
    assessability: Optional[AssessabilityVerdict] = None
    confidence: int
    rationale: str
    tier: Optional[str] = None
    created_at: datetime


class HistoryResponse(BaseModel):
    items: List[HistoryItem] = []


class CalibrationItem(BaseModel):
    """A calibration case, shaped like a queue item so the UI can reuse it."""
    calibration_id: str
    queue_position: int = -1
    task: TaskType
    sf_number: int
    statement: str
    statement_sha256: str
    category: str
    collection_version: str
    existing_provenance: Optional[ProvenanceType] = None
    existing_source_citation: Optional[str] = None
    legacy_assessment: Optional[Dict[str, Any]] = None
    repeated_judgment: bool = False
    n_required: int = 1
    comparison_item: bool = False
    stratum: str = "calibration"
    completed: int = 0
    total: int = 0


class CalibrationDecision(BaseModel):
    """An answer to one calibration case."""
    calibration_id: str
    task: TaskType
    provenance_type: Optional[ProvenanceType] = None
    scope_verdict: Optional[ScopeVerdict] = None
    assessability: Optional[AssessabilityVerdict] = None
    confidence: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)
    time_spent_s: Optional[float] = None


class CalibrationFeedback(BaseModel):
    """Immediate feedback — calibration teaches, so it does not withhold."""
    correct: bool
    reference: Dict[str, Any] = {}
    explanation: str
    completed: int
    total: int
