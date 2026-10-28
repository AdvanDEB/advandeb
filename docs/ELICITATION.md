# Expert Elicitation

> **Written 2026-10-28** from the code at `5ceb4fa`. Covers what landed between
> `d4a38f3` (2026-09-21, "Replace Scenarios with an Annotation section") and
> `5ceb4fa` (2026-09-24, "the evidence-scoring task, and it leads the queue").
> The method behind it is specified in the separate `advandeb_methods`
> repository (`docs/02-elicitation-protocol.md`, `docs/09-scoring-reference.md`,
> `docs/10-external-collaboration.md`); this page documents what the platform
> implements, not the method.
>
> **Known defect, read before relying on the UI:** the Vue views and the API
> disagree on several endpoints and payloads (enrolment, calibration, admin
> decisions, the evidence task). The server side described here is the tested
> half. See C19 in `docs/PLAN-2026-08-26.md`.

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

## 2. Tasks and the queue

`TaskType` (`app/backend/app/models/elicitation.py`) has four values:

| Task | Asks the expert | Needs evidence? |
|---|---|---|
| `evidence` | Label each passage of a frozen evidence set `supports` / `contradicts` / `neutral`. Then give `evidence_strength` (1–3) and `consensus_direction` (1–3) for the fact. | yes — an imported evidence set |
| `provenance` | Is the stylized fact published, or new? | no |
| `scope` | Does the statement state its scope? | no |
| `assessability` | Can the statement be assessed against literature at all? | no |

The three fact-level tasks were built first, because they need no evidence
sets. The `evidence` task produces the human ceiling, so it **leads the
queue**.

**Queue order** (`app/backend/app/services/elicitation_service.py`):
- Items sort by block `priority`, then by `queue_position`. Evidence items have
  `PRIORITY_EVIDENCE = 0`; fact-level items have `PRIORITY_FACT_LEVEL = 1`.
- Within a block the order is seeded (`QUEUE_SEED`). Each stratum contributes
  at least `STRATUM_FLOOR = 3` items, then weighted fair queueing fills the
  rest. Any prefix of the queue is therefore a usable stratified sample.
- `n_required` says how many independent panel judgments an item needs. Every
  `ELICITATION_COMPARISON_EVERY`-th position (default 25) needs the full human
  panel, every 5th needs 2, the rest need 1.
- Evidence items come from two corpora, `deb` and `reproduction`. `deb` items
  take the full panel, because the comparison needs several experts on the
  *same* evidence set. `reproduction` items take one judgment.
- An expert is shown `ELICITATION_EVIDENCE_PASSAGES` passages per set (default
  18, which is every passage). The number is recorded on each item.
- Experts cannot pick items. They get the next one they have not judged.

Guidelines are served by `GET /api/elicitation/guidelines` and carry a version
(`GUIDELINES_VERSION = "1.1"`). A judgment record stamps:
- the expert's tier (§3);
- the stylized-fact `collection_version`;
- the queue position and stratum;
- `round`: `primary`, or `secondary` once an earlier judgment exists;
- `author_excluded`, for an expert judging a fact they authored.

It does **not** stamp the guidelines version. A mid-study change to the
guidelines therefore has to be dated from the commit history.

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

## 4. Calibration gate

Before an expert's first real item, they work through a fixed calibration set
of 15 cases:
- 5 × provenance = published
- 5 × provenance = new
- 3 × scope = stated
- 2 × scope = absent

The set is seeded automatically on first use. An administrator can also seed
it with `POST /calibration/seed`.

**The gate requires completion, not correctness.** An expert passes by
answering all 15. Their answers are recorded as a quality signal and shown back
as feedback. They do not exclude anyone.

**The gate is enforced on the server** (`0b5376b`):
- `next_item()` returns nothing until calibration is complete.
- `submit()` refuses with `calibration incomplete (x/y)`, which
  `POST /api/elicitation/decide` returns as HTTP 400.

A client that skips the calibration screen therefore still cannot submit.

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

References are stored in Mongo `expert_references`, with the tier stamped. The
`ingestion_queued` flag marks works that should be ingested, but nothing in
the app consumes it yet.

---

## 7. Storage

All in MongoDB `advandeb`. Elicitation writes nothing to ArangoDB.

| Collection | Holds |
|---|---|
| `elicitation_queue` | queue items: fact, task, corpus, priority, position, `n_required` |
| `elicitations` | one judgment per (item, expert); unique index `item_expert_unique`; tier, collection version and round stamped |
| `evidence_sets` | frozen evidence sets imported from `advandeb_methods` (`POST /evidence/import`) |
| `elicitation_calibration` | the 15 calibration cases |
| `elicitation_calibration_results` | each expert's calibration answers |
| `enrolment_requests` | public enrolment requests and their decisions |
| `expert_references` | expert-asserted DOIs and their retrieval status |
| `users` | `tier`, `capabilities`, `expertise_profile`, `approval`, `authored_sf_numbers` |

It reads `stylized_facts` and `documents`.

---

## 8. Configuration

Read directly from the environment, not via `Settings`:

| Variable | Default | Meaning |
|---|---|---|
| `ELICITATION_HUMAN_PANEL_SIZE` | `5` | judgments a full-panel item needs |
| `ELICITATION_COMPARISON_EVERY` | `25` | every k-th queue position is a full-panel comparison item |
| `ELICITATION_EVIDENCE_PASSAGES` | `18` | passages shown per evidence set |
| `DEB_REPRO_DB` | — | Mongo database holding the reproduction abstract corpus (DOI lookup) |

---

## 9. API

All under `/api/elicitation` unless stated.

| Method | Path | Who |
|---|---|---|
| GET | `/next` | elicitor |
| POST | `/decide` | elicitor (blocked until calibrated) |
| GET | `/progress`, `/history`, `/guidelines` | elicitor |
| GET | `/calibration/next`, `/calibration/status` | elicitor |
| POST | `/calibration/decide` | elicitor |
| POST / GET / DELETE | `/references`, `/references/{id}` | elicitor |
| POST | `/queue/build`, `/evidence/import`, `/queue/build-evidence`, `/calibration/seed` | admin |
| GET | `/experts`, `/stats/admin`, `/references/recall` | admin |
| POST | `/experts/{user_id}?granted=` | admin |
| POST | `/api/enrolment/request` | **public**, 5/min |
| GET | `/api/enrolment/requests` | admin |
| POST | `/api/enrolment/requests/{id}/decide` | admin |

"Elicitor" means it passes `require_elicitor` (§5).

---

## 10. Tests and checks

- `app/frontend/src/tests/elicitationValidation.test.ts` covers the shared
  validation predicate (vitest).
- `app/backend/tests/verify_elicitation_queue.py` and
  `verify_expert_references.py` are **scripts, not pytest modules**. pytest
  does not collect `verify_*`. They write to MongoDB.
  - Run them only against a scratch database whose name says so (see
    `app/backend/app/core/dbguard.py`), never with the production `.env`
    loaded.
  - The two scripts redirect the database name differently. One of them uses
    `os.environ.setdefault`, the pattern that once dropped a production
    collection (see `docs/STORAGE-CONTRACT.md` §2a).
