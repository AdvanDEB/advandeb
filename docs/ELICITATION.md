# Expert Elicitation

> **Written 2026-10-28** from the code at `5ceb4fa`. Covers what landed between
> `d4a38f3` (2026-09-21, "Replace Scenarios with an Annotation section") and
> `5ceb4fa` (2026-09-24, "the evidence-scoring task, and it leads the queue").
> The method behind it is specified in the separate `advandeb_methods`
> repository (`docs/02-elicitation-protocol.md`, `docs/09-scoring-reference.md`,
> `docs/10-external-collaboration.md`); this page documents what the platform
> implements, not the method.
>
> **Reshaped 2026-10-28** (branch `feat/elicitation-reshape`, guidelines 2.0)
> to the project owner's decisions of that day: one combined mode, a citation
> on every passage, a rationale only where the judgment departs from the
> passages, team-chosen calibration examples, the fact-level tasks no longer
> served, and the panel's verdict shown in the knowledge base. Where this
> page and `advandeb_methods/docs/02` differ, this page describes the
> platform; the deviation is logged for the methods paper (draft in
> `docs/elicitation/DEVIATION-2026-10-28-draft.md`).

---

## 1. What it is for

DEB experts judge stylized facts, item by item. Their judgments form one of
**two consensus processes** the method compares: a panel of open-weight models
and a panel of human experts. **Neither is treated as ground truth.** The
headline measurement is the human agreement ceiling: how well experts agree
with *each other* on the same evidence. Without it, the machine panel's
agreement (Krippendorff's α ≈ 0.43 in the first sweep) cannot be interpreted.

Elicitation replaced the old Scenarios page. It lives at `/elicitation` in the
app and under `/api/elicitation` on the backend.

---

## 2. What an expert does, and the queue

Experts assess each stylized fact **from the retrieved passages and from their
own knowledge**, in one combined mode — the H-EK arm of
`advandeb_methods/docs/14` §2. For each item they:

1. read the fact and up to 18 passages, each shown with its citation (§2a);
2. label every passage `supports` / `contradicts` / `neutral` /
   `cannot_judge`, **by what the passage itself says**, and give an
   evidential role to each `supports` or `contradicts` one. Since guidelines
   2.1 the form shows `contradicts` as **Disputes** (the stored value is
   unchanged), and `cannot_judge` lets an expert abstain on a passage; it is
   excluded from agreement counts as a missing value.
   The passage labels keep the agents' axes and wording, so passage-level
   agreement stays comparable with the machine panel;
3. judge the fact: `evidence_strength` (1–3) and `consensus_direction` (1–3),
   from the passages **and** what they know;
4. answer *"Does your judgment go beyond or against what these passages
   show?"* (`departs_from_passages`) — the human counterpart of M-EK's
   attribution;
5. give a rationale **only when required** (below), optionally add references
   by DOI (§6), set confidence 1–5, submit.

**When a rationale is required** (`judgment_problem` in the service, mirrored
in `app/frontend/src/components/elicitation/decision.ts`):
- the expert answered *yes* to the departure question; or
- the overall scores contradict the expert's **own** passage labels
  (`score_label_conflicts`): consensus 3 with no passage `supports`
  (`corroborated_without_support`), consensus 1 with no passage `contradicts`
  (`against_without_contradiction`), or strength ≥ 2 with no passage
  `supports` (`strength_without_support`).

The machine assessment is never used to decide this and is never shown to an
expert — neither the old 1–100 score (`legacy_assessment` is null on evidence
items) nor, through reference resolution, how the machine labelled a paper.

`TaskType` still has four values. **Only `evidence` is served**
(`SERVED_TASKS`). The fact-level tasks `provenance`, `scope` and
`assessability` (3,786 rows in production) stay stored and their code stays in
place; serving them again is a one-line change. No database write was needed
to stop serving them, and `/decide` refuses them.

**Queue order** (`app/backend/app/services/elicitation_service.py`):
- Items sort by block `priority`, then by `queue_position`; within a block the
  order is seeded (`QUEUE_SEED`). Each stratum contributes at least
  `STRATUM_FLOOR = 3` items, then weighted fair queueing fills the rest, so any
  prefix of the queue is a usable stratified sample.
- Evidence items come from two corpora, `deb` and `reproduction`. `deb` items
  take the full human panel (`n_required = ELICITATION_HUMAN_PANEL_SIZE`,
  default 5); `reproduction` items take one judgment.
- An expert is shown `ELICITATION_EVIDENCE_PASSAGES` passages per set (default
  18, every passage).
- Experts cannot pick items. They get the next one they have not judged, that
  they did not author, whose panel requirement is not met, and whose fact is
  not a calibration example (§4).

Guidelines and the one-screen *How this works* text are served by
`GET /api/elicitation/guidelines` with `GUIDELINES_VERSION = "2.1"`. A
judgment record stamps:
- the expert's tier (§3), `collection_version`, queue position and stratum;
- `round`: `primary`, or `secondary` once an earlier judgment exists;
- `author_excluded`;
- `guidelines_version` and `calibration_version` (`None` = made before any
  calibration set was published);
- `departs_from_passages`, `score_label_conflicts`, `rationale_required`, and
  the `reference_ids` the expert added on that item.

### 2a. Passage citations

The frozen evidence sets record a library **file name** as the title of every
DEB-corpus passage (`Kooy93.pdf`) and no DOI or year. Citations are therefore
**resolved at serve time** by `app/backend/app/services/passage_citation_service.py`
and never written onto the passage — the sets, their `content_hash`,
`text_sha256` and `statement_sha256` stay exactly as the agents read them.

- `deb`: the passage's `document_id` is the DEB-library folder; the curated
  papers are the ArangoDB `documents` with `source_type == "pdf_local"`
  (1,253), joined on `source_path == "<document_id>/<file>"`, or on the folder
  alone when it holds exactly one paper. Loaded once, cached 15 minutes.
- `reproduction`: `document_id` is the OpenAlex work id, looked up by `_key`.
- Each passage carries `citation` (`PassageCitation`): `status`
  (`resolved` / `partial` / `unresolved`), authors, year, title, journal, DOI
  (normalised to the bare form), pages, and — when unresolved — the file name
  and library folder, which the UI shows plainly as *"Source not yet
  identified"*.
- ArangoDB unreachable: passages are served with unresolved citations and the
  store is not retried for 60 s. A citation never blocks an item.

Corrections to a citation are made in ArangoDB (canonical for documents,
`docs/STORAGE-CONTRACT.md`) and reach experts on the next cache refresh. See
`docs/elicitation/UNRESOLVED-CITATIONS.md` for the papers that still need
manual completion and for DOIs found to be wrong.

---

## 3. Tiers: panel and contributor

Every elicitation participant has a **tier**, and the two tiers are **never
pooled**:

| Tier | Meaning |
|---|---|
| `panel` | The core expert panel. Only panel judgments count towards `n_required`, the agreement statistics, and the human consensus. |
| `contributor` | Anyone else admitted to elicitation. Judgments are stored and credited, but never mixed into panel statistics. |

**The tier is assigned, never inferred.**
- An administrator assigns it when approving an enrolment request. Approval
  without a tier is rejected.
- The founding panel was tiered by `scripts/migrate_expert_tiers.py`, which
  supports `--dry-run`.
- `tier_of()` returns the user's stored `tier`. If none is stored, it returns
  `contributor` and logs a warning. It never guesses `panel`, so a missing tier
  can only shrink the panel, never contaminate it.

**The tier is stamped on every record at write time**, both on `elicitations`
and on `expert_references`. Statistics aggregate by the *stamped* tier, not by
the user's current tier. A later change of tier therefore cannot rewrite
history. `GET /api/elicitation/stats/admin` reports both: `by_record_tier`, and
the expert's `current_tier`.

---

## 4. Calibration

Calibration is **three to five real evidence items the team picks**, each with
an agreed reference answer (`evidence_strength`, `consensus_direction`,
optionally reference labels for some passages) and an explanation shown to the
expert. It replaced the 15 generated provenance/scope cases, which tested a
task nobody is asked any more and used one expert's own facts; the old
`elicitation_calibration` collection is no longer read.

- **Versioned.** Administrators draft a set under `/admin/experts`
  (`POST/PUT /calibration/sets`), and publish it
  (`POST /calibration/sets/{version}/publish`), which retires the previous
  one. Published and retired versions are never edited.
- **Never blocks while nothing is published.** Until the team publishes a set,
  experts work the queue and their judgments carry `calibration_version: None`.
- **Once published, each expert works it once** before their next item:
  `/next` returns null and `/decide` refuses (403) while
  `CalibrationStatus.required` is true. Publishing a new version asks
  everyone again.
- Calibration cases are served exactly like real items (passages, citations,
  the same form and the same rationale rule) and checked with the same
  `judgment_problem`. The first answer to a case is kept; feedback shows the
  team's answer, the explanation, and agreement on the passages the team
  labelled. Results are a quality signal, never an exclusion gate.
- **A calibration fact leaves the measured queue for good** (both corpora, for
  every expert): it has been shown with its answer. The admin picker warns when
  a fact already has judgments.

Proposed candidates are in `docs/elicitation/CALIBRATION-CANDIDATES.md`; the
choice and the reference answers are the team's.

---

## 5. Who can take part

### Capability: `sf_elicitation`

Elicitation is the first feature behind a **capability** rather than a role
(`app/backend/app/core/dependencies.py`):
- `require_capability("sf_elicitation")` (alias `require_elicitor`) passes
  administrators and any user holding the capability.
- For this capability it also passes the `knowledge_curator` and
  `external_contributor` roles.

The reason is in the code comment. The DEB experts hold only
`knowledge_explorator`, so a role gate would have locked out exactly the people
the work depends on.

An administrator grants or revokes the capability with
`POST /api/elicitation/experts/{user_id}?granted=true|false`. Enrolment
approval also grants it.

### Role: `external_contributor`

`external_contributor` is the minimum-privilege role for outside participants.
It is defined by what it excludes: no documents, no chat, no knowledge base,
no graph, and no models. The reason is that some curated material is licensed
full text that cannot leave the project.

The frontend router confines users who hold only this role to `/elicitation`,
`/settings` and `/login`.

**The exclusion is not enforced on the backend.** An external contributor's
token passes `get_current_user`, so it can call every API route that needs
only authentication. That includes chat (on the shared default key),
documents, facts, provenance, and chunk context, which returns passage text.
This is tracked as C25 in `docs/PLAN-2026-08-26.md`. Until it is fixed,
approving someone as an external contributor gives them API-level read access
to the knowledge base.

### Public enrolment — `/elicitation/join`

`/elicitation/join` (`EnrolmentView`) is the **only unauthenticated form in the
app**. It posts to `POST /api/enrolment/request`, which is rate-limited to
5/minute.

**The request:**
- carries name, email, affiliation, ORCID, years in the field, DEB experience,
  per-category familiarity (1–5), and consent to acknowledgement;
- is stored as `pending` in `enrolment_requests`, and **creates no account**;
- always gets the answer `{"status": "pending"}`, so the form does not reveal
  whether an email is already registered;
- needs no invitation code. Self-signup was chosen deliberately.

**An administrator then approves the request**, as `panel` or `contributor`,
or declines it. On approval:
- If the email is new, a user is created. A `contributor` gets the role
  `external_contributor`; a `panel` member gets `knowledge_explorator`. Either
  way the user gets `sf_elicitation`, the tier, the expertise profile, and a
  one-time `temp_password` returned to the admin.
- If the email already exists, that user gets the tier and the capability.

### Admin surface — `/admin/experts`

`AdminExpertsView` (admin only). It is where an administrator:
- reviews enrolment requests;
- grants and revokes `sf_elicitation`;
- monitors progress: panel coverage against `n_required`, queue depth, the
  "claims ladder" rung reached, breakdowns by task, expert and stratum, and the
  retrieval-recall figures from §6.

---

## 6. Expert-asserted DOI references and retrieval recall

Experts can name literature themselves. They submit
`{sf_number, statement_sha256, doi, direction: supports|opposes, note}` to
`POST /api/elicitation/references`. Each reference is then processed as
follows (`app/backend/app/services/expert_reference_service.py`):

1. **DOI resolution.** The DOI is resolved against OpenAlex, then Crossref. A
   DOI that resolves nowhere is rejected and not stored.
2. **Corpus lookup.** The work is looked up in Mongo `documents`, then in the
   reproduction abstract corpus (`DEB_REPRO_DB`, `abstract_chunks`).
3. **Retrieval check.** If the work is in the corpus, the service checks
   whether the machine panel's retrieval for that fact actually surfaced it.
   The check reads the full-corpus run's raw outputs under
   `analysis/sf_support_fullcorpus/raw`.

Each reference gets one of these statuses:

| Status | Meaning |
|---|---|
| `not_in_corpus` | the literature the system searches does not contain the work |
| `in_corpus_not_retrieved` | the work is in the corpus, but retrieval missed it — a recall failure |
| `in_corpus_retrieved` | the work is in the corpus and retrieval found it (plus an `agrees_with_panel` flag) |
| `in_corpus_retrieval_unknown` | no retrieval record to check against |

**What this measures.** Expert references are a free measurement of the
retriever's recall:

```
miss_rate = in_corpus_not_retrieved / (in_corpus_not_retrieved + in_corpus_retrieved)
```

Undetermined cases are reported separately rather than guessed. The figure is
served at `GET /api/elicitation/references/recall` (admin) and is embedded in
`stats/admin`.

Per fact, the references also form a **third score**, `asserted_evidence`. It
is never added to the machine's score; that rule is a fixed method decision.

References are stored in Mongo `expert_references`, with the tier stamped.

**They enter the knowledge base as candidates, not as evidence.** Every new
reference carries `curation: {status: "pending"}` and appears to curators in
KB → Suggestions → *Expert evidence candidates*
(`GET /references/candidates`), without the expert's identity. A curator
accepts or rejects it (`POST /references/{id}/review`). Accepting records that
the paper bears on the fact; it moves no score, and a paper not in the corpus
still has to be ingested with its PDF. Promoting accepted candidates into an
ArangoDB evidence schema is a separate, open decision.

**Independence.** An expert sees only their own references, and never the
machine panel's labels for a paper (`panel_labels`, `agrees_with_panel` are
stripped for non-curators) or the per-fact `asserted_evidence` totals.
`mine_only=false` is curator-only.

---

## 6a. Expert verdicts in the knowledge base

Next to each stylized fact — the Facts view, its expanded row, and the graph
node panel — the KB shows the aggregated expert verdict, e.g. *"Supported ·
4/5 panel"* with the consensus and strength distributions
(`GET /api/kb/stylized-facts/expert-verdicts`,
`app/backend/app/services/expert_verdict_service.py`).
- Aggregated per fact, corpus and **stamped** tier, from `evidence` judgments.
  Panel is the headline; contributor verdicts are shown separately, labelled
  *Contributors (not panel)*.
- Nothing is shown for a group with fewer than `EXPERT_VERDICT_MIN_N` (3)
  judgments. Ordinal scores are reported as distributions, never averaged.
- **Withheld from anyone who may still judge the fact**: a potential judge
  (capability `sf_elicitation`, role `external_contributor`, or a tier) sees
  *"Hidden while you may still judge this fact"* while any evidence item of
  that fact is open and unjudged by them.

---

## 7. Storage

All in MongoDB `advandeb`. Elicitation writes nothing to ArangoDB.

| Collection | Holds |
|---|---|
| `elicitation_queue` | queue items: fact, task, corpus, priority, position, `n_required` |
| `elicitations` | one judgment per (item, expert); unique index `item_expert_unique`; tier, collection version and round stamped |
| `evidence_sets` | frozen evidence sets imported from `advandeb_methods` (`POST /evidence/import`) |
| `elicitation_calibration_sets` | versioned calibration sets: items, agreed answers, status |
| `elicitation_calibration_answers` | each expert's calibration answers, first answer kept |
| `elicitation_calibration`, `elicitation_calibration_results` | the retired generated set (no longer read) |
| `enrolment_requests` | public enrolment requests and their decisions |
| `expert_references` | expert-asserted DOIs, retrieval status, curator review (`curation`) |
| `users` | `tier`, `capabilities`, `expertise_profile`, `approval`, `authored_sf_numbers` |

It reads `stylized_facts` and `documents` (Mongo), and ArangoDB `documents`
for passage citations (read-only).

---

## 8. Configuration

Read directly from the environment, not via `Settings`:

| Variable | Default | Meaning |
|---|---|---|
| `ELICITATION_HUMAN_PANEL_SIZE` | `5` | judgments a full-panel item needs |
| `ELICITATION_COMPARISON_EVERY` | `25` | every k-th queue position is a full-panel comparison item |
| `ELICITATION_EVIDENCE_PASSAGES` | `18` | passages shown per evidence set |
| `EXPERT_VERDICT_MIN_N` (Settings) | `3` | judgments a verdict group needs before the KB shows it |
| `DEB_REPRO_DB` | — | Mongo database holding the reproduction abstract corpus (DOI lookup) |

---

## 9. API

All under `/api/elicitation` unless stated.

| Method | Path | Who |
|---|---|---|
| GET | `/next` | elicitor |
| POST | `/decide` | elicitor (blocked while a published calibration set waits) |
| GET | `/progress`, `/history`, `/guidelines` | elicitor |
| GET | `/calibration/next`, `/calibration/status` | elicitor |
| POST | `/calibration/decide` | elicitor |
| POST / GET / DELETE | `/references`, `/references/{id}` | elicitor (`mine_only=false`: curator) |
| GET | `/references/candidates` | curator |
| POST | `/references/{id}/review` | curator |
| GET | `/calibration/sets`, `/calibration/evidence-sets`, `/calibration/evidence-sets/{id}` | admin |
| POST / PUT / DELETE | `/calibration/sets`, `/calibration/sets/{version}`, `/calibration/sets/{version}/publish` | admin |
| POST | `/queue/build`, `/evidence/import`, `/queue/build-evidence` | admin |
| GET | `/api/kb/stylized-facts/expert-verdicts`, `/api/kb/stylized-facts/{n}/expert-verdict` | signed in |
| GET | `/experts`, `/stats/admin`, `/references/recall` | admin |
| POST | `/experts/{user_id}?granted=` | admin |
| POST | `/api/enrolment/request` | **public**, 5/min |
| GET | `/api/enrolment/requests` | admin |
| POST | `/api/enrolment/requests/{id}/decide` | admin |

"Elicitor" means it passes `require_elicitor` (§5).

---

## 10. Tests and checks

- Backend: `tests/test_elicitation_service.py`, `test_elicitation_queue.py`,
  `test_elicitation_routes.py`, `test_expert_verdicts.py` need a throwaway
  mongod (`TEST_MONGODB_URI`, see `tests/conftest.py`) and skip without one;
  `test_elicitation_contract.py` checks the generated TypeScript types
  (`scripts/gen_elicitation_types.py`) against the models.
- Frontend (vitest): `elicitationEvidence.test.ts` (the judgment, rationale
  rule, citations, view), `elicitationCalibration.test.ts`,
  `elicitationValidation.test.ts`, `expertEvidenceCandidates.test.ts`,
  `expertVerdict.test.ts`, `enrolmentA11y.test.ts`.
- `app/backend/tests/verify_elicitation_queue.py` and
  `verify_expert_references.py` are **scripts, not pytest modules**. pytest
  does not collect `verify_*`. They write to MongoDB.
  - Run them only against a scratch database whose name says so (see
    `app/backend/app/core/dbguard.py`), never with the production `.env`
    loaded.
  - The two scripts redirect the database name differently. One of them uses
    `os.environ.setdefault`, the pattern that once dropped a production
    collection (see `docs/STORAGE-CONTRACT.md` §2a).
