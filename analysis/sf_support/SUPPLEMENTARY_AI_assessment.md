# Supplementary Material — AI-Assisted Scientific-Support Assessment of Stylized Facts

## S1. Purpose and overview

The stylized facts (SFs) compiled in the main text were each assigned an
automated, literature-grounded *support score* by a retrieval-augmented,
large-language-model (LLM) assessment system (referred to here as **XXXX**).
The aim of this procedure is not to replace expert judgment but to make the
otherwise intractable task of evidence gathering — scanning a literature of
hundreds of thousands of documents per fact — systematic, reproducible, and
fully traceable to primary sources. For every SF the system retrieves the most
relevant passages from two independent literature corpora, asks an LLM to judge
whether each passage supports, contradicts, or is merely topically related to
the fact, and aggregates those passage-level verdicts into two complementary
1–3 scores together with a count of the distinct references that genuinely bear
on the statement. The complete pipeline is summarized in Figure S1.

## S2. Literature corpora

Two corpora were indexed as separate retrieval sources so that agreement and
disagreement between them could be examined directly:

| Corpus | Content | Documents | Indexed passages |
|--------|---------|----------:|-----------------:|
| **DEB literature** | Curated corpus of Dynamic Energy Budget and related ecophysiology manuscripts (full text) | 1,643 | ~0.34 M |
| **Reproduction abstracts** | Broad corpus of abstracts concerned with organismal reproduction and life history | 599,540 | ~2.20 M |

Both corpora reside in a single embedded vector store (ChromaDB); each text
chunk carries a `general_domain` tag identifying its corpus of origin, which is
used to confine retrieval to one corpus at a time. In total **2.81 million** text
passages were available for retrieval.

## S3. Stylized-fact set

Sixty-two stylized facts were assessed, spanning ten thematic categories grouped
into three domains: (i) the **core DEB stylized facts** (Feeding, Growth,
Reproduction, Respiration, Stoichiometry, General Physiology; 36 facts);
(ii) **Hypoxia / dissolved oxygen** responses (14 facts); and (iii)
**phytoplankton physiology** (N:C ratio, chlorophyll, and EPS production;
12 facts). Each fact was supplied to the system verbatim as a single declarative
statement.

## S4. Retrieval

Each SF statement was converted into a 384-dimensional dense vector using the
`all-MiniLM-L6-v2` sentence-transformer — the same embedding model used to index
the corpora, ensuring that query and documents share an embedding space. For
each corpus the 60 nearest passages were retrieved by cosine similarity. Near-
duplicate passages (identical leading text) were removed, and the highest-ranked
distinct passages were retained as candidate evidence (up to 18 per corpus).
Retrieval was performed independently for the two corpora.

## S5. LLM adjudication

The candidate passages for each SF were passed, with the SF statement and its
category, to a Claude Opus-class LLM (`claude-opus-4-8`) acting as an
evidence assessor under a fixed system instruction that forbids the use of
outside knowledge or invented evidence. The model returned a strict JSON object
in which **every** passage receives:

- a **label** — `supports` (evidence consistent with / affirming the fact),
  `contradicts` (evidence against it), or `neutral` (off-topic, or mentioning
  the area without bearing on the fact's truth); and
- a **relevance** score in [0, 1] indicating how directly the passage bears on
  the fact.

This explicit adjudication step is the core of the method: semantic similarity
locates *topically related* text, but only the support/contradict judgment
converts that text into *evidence*. The model additionally returned the two
overall scores and a free-text rationale described below. Calls used a 2,000-
token output budget and up to four retries with backoff to absorb transient API
or JSON-parsing errors.

## S6. Scoring scheme

For each SF and each corpus the passage-level verdicts were aggregated into the
quantities reported in Tables 2–4 of the main text:

- **Evidence strength (1–3)** — how much direct support exists in the corpus:
  1 = weak / sparse / no real support; 2 = moderate support;
  3 = strong, multiple clear supporting references.
- **Consensus direction (1–3)** — the balance of the evidence:
  1 = predominantly contradicted or mixed-against; 2 = neutral / insufficient;
  3 = corroborated, with little conflict.
- **Reference count** — the number of *distinct documents* that genuinely deal
  with the SF, i.e. documents contributing at least one passage labelled
  `supports`/`contradicts` or with relevance ≥ 0.5. Because counts are bounded
  by retrieval depth, they should be read as "supporting references found among
  the nearest neighbours," not as an exhaustive census of the literature.

## S7. Three scoring scopes

The assessment was carried out at three scopes, yielding the three score tables
in the main text:

1. **DEB literature** — adjudication restricted to the DEB corpus.
2. **Reproduction abstracts** — adjudication restricted to the abstract corpus.
3. **Combined** — a *fresh* adjudication over the merged top passages of both
   corpora (the 12 nearest from each), so the combined score is an independent
   judgment rather than an average of the two single-corpus scores.

Comparing scopes is itself informative. A fact strongly evidenced in the focused
DEB literature but weakly evidenced in the broad abstract corpus, or one on which
the two corpora diverge in direction, flags where a regularity may be
theory-internal, taxon-specific, or genuinely contested. The cross-corpus
evidence gap is visualized in Figure S1 (lower panel); it is largest for
respiration, stoichiometry, and phytoplankton facts — domains well represented in
the DEB literature but only marginally present in the reproduction abstracts.

## S8. Outputs and provenance

Every score is provenance-linked. For each SF and scope the system emits a
machine-readable record and two human-readable documents: a **reference list**
(the contributing documents with their supporting/contradicting passage counts,
identifiers, and best similarity) and a **snippet document** (the verbatim
passages with their labels and sources). Consequently any rating in the main
tables can be inspected, challenged, and traced back to the primary passages on
which it rests. In total the run produced three summary tables, 62 structured
records, and 372 per-fact provenance documents.

## S9. Reproducibility — parameter summary

| Parameter | Value |
|-----------|-------|
| Embedding model | `all-MiniLM-L6-v2` (384-dim) |
| Vector store / metric | ChromaDB (embedded), cosine similarity |
| Passages retrieved per corpus | 60 (deduplicated → ≤ 18 adjudicated) |
| Combined scope | 12 nearest passages per corpus, re-adjudicated |
| Reference-count relevance threshold | 0.5 |
| Adjudication model | `claude-opus-4-8` |
| Output budget / retries | 2,000 tokens / up to 4 with backoff |
| Scopes × scores | {DEB, abstracts, combined} × {evidence, consensus} |

The procedure is deterministic in its retrieval stage; LLM adjudication is
subject to the usual sampling variability, which is the principal reason results
are accompanied by full provenance for verification.

## S10. Limitations and the role of human oversight

The assessment inherits the known limitations of LLMs and of retrieval-based
evidence gathering, and the design choices above are intended to make those
limitations visible rather than to deny them. (i) Semantic proximity is not
proof of support; the explicit support/contradict adjudication mitigates but does
not eliminate topical false positives. (ii) Reference counts are capped by
retrieval depth and by corpus coverage — a low count can reflect a thin corpus
rather than weak science (e.g. the phytoplankton facts are niche relative to both
corpora). (iii) LLMs can hallucinate, misread context, and propagate biases
present in their training data or in the indexed corpora; distinguishing a
universal physiological rule from a narrow species-specific adaptation in
particular still benefits from expert biological intuition. The appropriate
division of labor is therefore complementary: the system performs exhaustive,
reproducible, traceable first-pass extraction at a scale no individual reviewer
can match, and human experts concentrate on the contested and ambiguous cases
that the scores — and the cross-corpus disagreements — have already flagged.

---

*Figure S1.* Visual abstract of the assessment pipeline and results
(`sf_ai_assessment_infographic.png` / `.pdf`): the five-stage scoring pipeline,
corpus and output statistics, mean evidence-strength and consensus-direction
scores by category and scope, and the cross-corpus evidence gap.
