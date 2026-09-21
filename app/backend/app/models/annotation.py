"""
Human annotation of stylized facts.

Annotation records live in MongoDB alongside users, submissions and chat —
the application store. Panel verdicts, consensus records and standing live in
ArangoDB with the knowledge graph.

The design constraints these models exist to satisfy are specified in
``advandeb_methods/docs/02-annotation-protocol.md``:

* **Interruptible sampling.** Total annotator availability is unknown, so the
  queue is a fixed, seeded order whose every prefix is a valid reweightable
  sample. Annotators draw strictly from the head; they never choose an item.
* **Conflict of interest.** An annotator is never assigned a stylized fact
  they authored. Facts 1201-1236 have a known author who is also an annotator.
* **Anchoring control.** Whether a reviewer opened the machine verdict is
  logged, so exposure is measurable rather than assumed.
* **Time on task** is captured automatically; it is the throughput figure the
  method paper needs and it is free to collect here.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# Day-one tasks operate on the statement alone and need no evidence set, so
# annotation can begin before the consensus pipeline runs inside the platform.
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
    """One unit of work, as handed to an annotator."""

    queue_position: int
    task: TaskType
    sf_number: int
    statement: str
    statement_sha256: str
    category: str
    collection_version: str
    # Present only where it already exists; deliberately not shown first in the
    # UI for tasks where it could anchor the annotator.
    existing_provenance: Optional[ProvenanceType] = None
    existing_source_citation: Optional[str] = None
    # Legacy 1-100 score from the older pipeline, collapsed by default.
    legacy_assessment: Optional[Dict[str, Any]] = None
    # True when this position is designated for a second independent annotator.
    double_annotation: bool = False
    stratum: str


class AnnotationDecision(BaseModel):
    """What an annotator submits. One per (task, fact, annotator)."""

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

    # --- captured by the client ---
    time_spent_s: Optional[float] = None
    machine_verdict_expanded: Optional[bool] = None


class AnnotationRecord(AnnotationDecision):
    """A stored decision."""

    id: str = Field(alias="_id")
    annotator_id: str
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


class AnnotationProgress(BaseModel):
    """Where the effort has actually gone — per annotator and overall.

    Reported against the claims ladder (docs/02 4.2) rather than as a bare
    count, so it is visible at any moment which conclusions the annotation so
    far can support.
    """

    total_queue: int
    completed: int
    completed_by_me: int
    median_seconds_per_item: Optional[float] = None
    by_task: Dict[str, int] = {}
    by_stratum: Dict[str, int] = {}
    double_annotated: int = 0
    rung: str = "R0"
    rung_note: str = ""
    next_rung_at: Optional[int] = None
