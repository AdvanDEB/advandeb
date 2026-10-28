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
#
# `evidence` is the task the whole comparison rests on, and it came later for a
# bad reason: the fact-level tasks were easy to queue before evidence sets
# existed in the platform, so they were built first and the gap went unnoticed.
# They produce useful metadata and they cannot produce the human ceiling — no
# amount of provenance labelling says whether a machine alpha of 0.43 is poor
# or is the task's noise floor. Only humans reading the *same frozen passages*
# can say that.
TaskType = Literal["provenance", "scope", "assessability", "evidence"]

# Passage-level judgment, deliberately the same two axes and the same wording
# the agents were given (advandeb_methods docs/01 section 4.2a). Parity is the
# point: if the human task differed, a human-machine gap could always be
# explained away as a difference of instructions rather than of judgment.
PassageDirection = Literal["supports", "contradicts", "neutral"]

# Separating evidence from assertion. Roughly half of what reads as DEB
# "support" turns out to be restatement of the theory rather than a measurement
# of it (restatement_ratio 0.474 across 3,294 passages), so a passage that
# supports a fact is not yet evidence for it.
EvidentialRole = Literal["primary_evidence", "restatement", "derivation", "review"]

ProvenanceType = Literal["published", "new", "adapted", "unknown"]

# 84% of the collection states no organismal scope (advandeb_methods docs/06
# 6.1a). Scope adequacy cannot be computed without one, so eliciting it is the
# highest-value fact-level task available before evidence sets exist.
ScopeVerdict = Literal["stated", "implicit", "absent", "not_applicable"]

AssessabilityVerdict = Literal[
    "assessable", "too_vague", "compound", "not_empirical", "unclear_terms"
]

# Which evidence condition a judgment was made under (advandeb_methods docs/09
# section 5.2; renamed H-EK / H-K in docs/14 section 2). `matched` = the
# expert saw the frozen evidence set the agents saw; `expertise` = judged from
# the statement and domain knowledge alone. Determined by the task — evidence
# items are `matched`, the fact-level tasks are `expertise` — and stamped by
# the server, never chosen by the client.
EvidenceCondition = Literal["matched", "expertise"]

# Client-logged interface events. Only the anchoring-relevant one exists so
# far: whether the machine assessment was ever opened, and when relative to the
# expert's own answer (docs/09 section 5.4).
ElicitationEventType = Literal["machine_verdict_opened", "machine_verdict_closed"]


class EvidencePassage(BaseModel):
    """One frozen passage, as shown to an expert.

    `index` is the **canonical** index within the evidence set, which is the
    join key against every machine verdict. The agents read these rotated to
    control positional attention decay (docs/11 section 7.1) and their labels
    are stored against the canonical index too, so the two panels' judgments
    line up passage for passage regardless of what order either one saw.
    """

    index: int
    text: str
    similarity: float
    doi: Optional[str] = None
    title: Optional[str] = None
    year: Optional[Any] = None
    document_id: Optional[str] = None


class PassageJudgment(BaseModel):
    """An expert's two labels for one passage."""

    direction: PassageDirection
    evidential_role: Optional[EvidentialRole] = None


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

    # --- evidence task only ---
    # Which corpus this judgment is about. A fact is scored once per corpus,
    # so (sf_number, task) is no longer a unique item key and `corpus_id`
    # completes it. Null for the fact-level tasks, which have no corpus.
    corpus_id: Optional[str] = None
    evidence_set_id: Optional[str] = None
    # The hash of the passages the agent panel read. Carried onto the
    # expert's record so that "both panels saw the same evidence" is a
    # checkable claim rather than an assumption (ADR 0003).
    evidence_content_hash: Optional[str] = None
    passages: List[EvidencePassage] = []
    # How many passages the set holds in total, when fewer are shown. Stated
    # to the expert: judging 9 of 18 passages is a different question from
    # judging all the evidence there is, and they are entitled to know which
    # one they are being asked.
    n_passages_total: Optional[int] = None

    # The arm this item belongs to, decided by the server from the task. The
    # client renders from it (passages or not) and never chooses it: the
    # previous client defaulted to `expertise` because the field was absent,
    # and so hid the very passages the evidence task exists to show.
    evidence_condition: EvidenceCondition = "expertise"


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

    # evidence task. The two fact-level scores are the same 1-3 scales the
    # agents produce (docs/09 sections 2.1 and 2.2), unchanged from the
    # predecessor so every existing score stays on one scale.
    corpus_id: Optional[str] = None
    evidence_set_id: Optional[str] = None
    evidence_content_hash: Optional[str] = None
    evidence_strength: Optional[int] = Field(default=None, ge=1, le=3)
    consensus_direction: Optional[int] = Field(default=None, ge=1, le=3)
    # Keyed by canonical passage index as a string, because that is the join
    # key against the machine panel. Passage judgments are what the headline
    # agreement number is computed over, so an evidence decision without them
    # is not comparable to anything.
    passage_judgments: Dict[str, PassageJudgment] = {}

    # --- required of every decision ---
    confidence: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)

    # Which evidence condition this judgment was made under
    # (advandeb_methods docs/09 section 5.2). `matched` = the expert saw the
    # same frozen evidence set the agents saw, isolating judgment difference.
    # `expertise` = judged from domain knowledge alone, as in the predecessor
    # review. Running both is what lets a human-machine disagreement be
    # decomposed rather than merely observed.
    #
    # Stamped by the server from the task. A client may echo it; a value that
    # contradicts the task is refused rather than stored. It used to default
    # to `expertise` here, which made an omitted field indistinguishable from a
    # claim, and would have labelled every evidence judgment with the wrong arm.
    evidence_condition: Optional[EvidenceCondition] = None

    # --- captured by the client ---
    time_spent_s: Optional[float] = None
    # Whether the machine assessment was expanded *at the moment of submit*.
    # Not the anchoring measure — an expert can open it, read it, and close it
    # again. The record's `machine_verdict_opened` is derived on the server
    # from the logged open events instead.
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
    # Anchoring exposure, derived on the server from the logged events
    # (`elicitation_events`), not from the client's state at submit: whether
    # the expert opened the machine assessment for this item at any point, how
    # many times, and whether the first opening came before they had picked
    # an answer.
    machine_verdict_opened: Optional[bool] = None
    machine_verdict_open_events: Optional[int] = None
    machine_verdict_opened_before_answer: Optional[bool] = None
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
    # Queue items (sf_number, task, corpus_id) with two or more judgments.
    repeated_judgments: int = 0
    # The claims ladder counts what the doc counts: panel-tier judgments on
    # the evidence task, the only task the ladder's claims are about (docs/02
    # section 4.2). Metadata tasks and contributor judgments move nothing up
    # it, however many there are.
    ladder_count: int = 0
    ladder_basis: str = ""
    rung: str = "pre-R0"
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


# The sections the guidelines are served in: the four tasks, plus the three
# parts of the evidence task that have their own definitions. It was typed
# `TaskType`, so serving the evidence sub-sections failed response validation
# and /guidelines returned 500 from the day the evidence task was added — the
# client's fallback text hid it.
GuidelineSection = Literal[
    "provenance", "scope", "assessability", "evidence",
    "evidence_role", "evidence_strength", "consensus_direction",
]


class TaskGuideline(BaseModel):
    task: GuidelineSection
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
    corpus_id: Optional[str] = None
    evidence_strength: Optional[int] = None
    consensus_direction: Optional[int] = None
    confidence: int
    rationale: str
    time_spent_s: Optional[float] = None
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
    """Immediate feedback — calibration teaches, so it does not withhold.

    `reference` carries the one reference field for the case's task
    (`provenance_type`, `scope_verdict` or `assessability`) plus `basis`.
    """
    correct: bool
    reference: Dict[str, Optional[str]] = {}
    explanation: str
    completed: int
    total: int


class CalibrationStatus(BaseModel):
    """How far through the calibration set an expert is.

    The contract the client gates on. It used to be an untyped dict, and the
    client read `required` / `complete` / `passed` — three fields that never
    existed — so every expert was waved through to a queue the server then
    refused to serve, and saw "queue exhausted".
    """
    total: int
    completed: int
    correct: int
    # True only when a calibration set exists AND this expert has finished
    # it. An empty set is not a passed one: it means nobody has seeded it,
    # and the gate stays shut until an administrator does.
    done: bool
    # Whether any calibration set exists. Lets the client say "not set up
    # yet — ask an administrator" instead of offering cases that are not there.
    available: bool


class DecisionReceipt(BaseModel):
    """What /decide returns when a decision is recorded."""
    status: Literal["recorded"]
    id: str
    round: Literal["primary", "secondary", "adjudication"]


class ElicitationEvent(BaseModel):
    """A client-logged interface event on one queue item."""
    event: ElicitationEventType
    sf_number: int
    task: TaskType
    corpus_id: Optional[str] = None
    # Whether the expert had already picked an answer when this happened.
    # Opening the machine verdict before answering is anchoring exposure;
    # opening it after is a check. Which one it was is the measurement.
    answered: bool = False


class EventReceipt(BaseModel):
    status: Literal["logged"]


# --------------------------------------------------------------------------- #
# Expert-asserted evidence — the third instrument                              #
# --------------------------------------------------------------------------- #
#
# An expert names a DOI that supports or opposes a fact. This is NOT an
# adjustment to the machine's score: an expert saying "this paper supports it"
# must never raise the panel's number directly, or the machine score becomes
# partly a human artifact and agreement between the two panels becomes partly
# experts editing one of them (advandeb_methods docs/09 sections 0 and 2.5).
# The machine may still change its mind — but only by reading the passage,
# via ingestion and re-adjudication.

ReferenceDirection = Literal["supports", "opposes"]

# The resolution outcomes. The first four are the settled design
# (docs/09 section 2.5a); the fifth is required by the data and is flagged in
# the report back to the coordinator.
#
#   not_in_corpus              a genuine coverage gap -> queue for ingestion
#   in_corpus_not_retrieved    RETRIEVAL RECALL FAILURE - the corpus held it
#                              and retrieval never surfaced it
#   in_corpus_retrieved        the panel already read it, so a disagreement is
#                              about JUDGMENT, not retrieval
#   unresolvable               the DOI does not resolve; rejected, never stored
#   pending                    async resolution not finished
#
#   in_corpus_retrieval_unknown
#       Membership is known but the retrieval question CANNOT be answered.
#       Required because the DEB full-text corpus (deb_literature_review,
#       1,306 documents) carries no DOI field at all — its evidence sets
#       reference documents by numeric doc_id, so a DOI can never be matched
#       against them. Collapsing this into `not_in_corpus` would inflate the
#       coverage-gap count and trigger spurious re-ingestion of papers already
#       held; collapsing it into `in_corpus_not_retrieved` would inflate the
#       headline recall-failure number with cases never actually checked.
#       Neither is acceptable for a figure the method reports, so the
#       undetermined case is named rather than absorbed.
ResolutionStatus = Literal[
    "pending", "unresolvable", "not_in_corpus",
    "in_corpus_not_retrieved", "in_corpus_retrieved",
    "in_corpus_retrieval_unknown",
]

# Why a retrieval determination could or could not be made. Recorded separately
# from the status so an undetermined case can always be explained.
RetrievalCheck = Literal[
    "exact",                      # checked against the fact's evidence set
    "no_evidence_set",            # no evidence set exists for this fact yet
    "corpus_lacks_doi",           # the holding corpus stores no DOIs
    "not_applicable",             # not in corpus, or unresolvable
]


class ExpertReferenceCreate(BaseModel):
    """What an expert submits."""

    sf_number: int
    statement_sha256: str
    doi: str = Field(min_length=3)
    direction: ReferenceDirection
    note: Optional[str] = None


class ExpertReference(BaseModel):
    """A stored expert-asserted reference."""

    id: str = Field(alias="_id")
    sf_number: int
    statement_sha256: str
    doi: str
    direction: ReferenceDirection
    note: Optional[str] = None
    expert_id: str
    # Stamped at write time, exactly as on an elicitation record
    # (docs/10 section 2.1). A promotion must not retroactively relabel
    # evidence a contributor named while they were a contributor.
    tier: Optional[str] = None
    resolution: Dict[str, Any] = {}
    ingestion_queued: Optional[bool] = None
    triggered_readjudication: Optional[bool] = None
    created_at: datetime

    class Config:
        populate_by_name = True


class ExpertAssertedEvidence(BaseModel):
    """The third score, aggregated per fact.

    Reported beside machine evidence strength, never summed with it.
    """

    n_supporting: int = 0
    n_opposing: int = 0
    n_distinct_experts: int = 0
    n_distinct_papers: int = 0
    n_recall_misses: int = 0
    n_new_to_corpus: int = 0
    n_retrieval_unknown: int = 0
    score_1_3: Optional[int] = None
