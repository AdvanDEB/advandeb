# Supplementary Material — AI-Assisted Scientific-Support Assessment of Stylized Facts

## S1. Purpose

Each stylized fact (SF) reported in the main text was assigned an automated,
literature-grounded support score by a retrieval-augmented, large-language-model
(LLM) pipeline. The goal is to make evidence gathering across corpora of millions
of documents systematic, reproducible, and fully traceable to primary sources,
and — by scoring with two independent judges and against two distinct corpora —
to expose where automated assessment and expert intuition agree or diverge.
Sixty-two SFs were assessed across ten categories in three domains: the core DEB
stylized facts (36), hypoxia / dissolved-oxygen responses (14), and phytoplankton
physiology (N:C, chlorophyll, EPS; 12).

## S2. Literature corpora

Two corpora were indexed as independent retrieval sources:

| Corpus | Content | Size |
|--------|---------|------|
| **DEB literature** | Full text of Dynamic Energy Budget and related ecophysiology manuscripts, chunked (~1,000 chars) | 1,306 documents → **152,076** chunks |
| **Reproduction abstracts** | Abstracts on organismal reproduction and life history (OpenAlex) | 4,553,458 records → **~3,895,724 unique** abstracts → **4,441,514** embedded chunks |

The reproduction collection contains ~657,734 duplicate records (the same
OpenAlex work ingested more than once); after de-duplication it holds
**~3.9 million unique abstracts**, of which **>99.99 %** are embedded. Reported
reference counts and corpus sizes refer to the unique abstracts.

## S3. Embedding and retrieval

Every chunk and every SF query is embedded with **`nomic-embed-text`** (768-d,
served by Ollama); query and corpus therefore share one embedding space. Each
corpus is held as an in-memory vector index and searched by exact cosine
similarity. For each SF and corpus the pipeline retrieves the **100** nearest
chunks, keeps those with cosine similarity **≥ 0.50**, de-duplicates, and passes
up to **18** distinct passages to the judges. Retrieval is performed
independently per corpus.

## S4. Dual-judge adjudication

The candidate passages are submitted, with the SF statement and its category, to
**two** LLM judges as a cross-check:

- **`gpt-oss:120b`** (served locally by Ollama; the judge family used for the
  main-text assessment), and
- **Claude Opus 4.8** (API).

Each judge, under a fixed instruction forbidding outside knowledge, labels every
passage as **supporting**, **contradicting**, or **neutral**, with a 0–1
relevance. This adjudication is the heart of the method: semantic similarity
locates topically related text, but only an explicit support/contradict judgment
turns that text into evidence. Each judge's passage-level verdicts are then
aggregated per SF and corpus into:

- **evidence strength (1–3)** — 1 weak/sparse, 2 moderate, 3 strong;
- **consensus direction (1–3)** — 1 contradicted/mixed, 2 neutral/insufficient,
  3 corroborated;
- a **reference count** — distinct documents contributing supporting or
  contradicting passages (relevance ≥ 0.5).

The assessment is run independently over the DEB corpus, the reproduction corpus,
and a **combined** scope (a fresh judgment over the merged nearest passages of
both corpora). Every score resolves to its source documents and verbatim
passages, so any rating is auditable back to primary literature.

## S5. Validation

**Cross-judge agreement.** Treating the two judges as independent raters of
evidence strength, agreement is high and the disagreement is informative rather
than random:

| Scope | Exact match | Within ±1 |
|-------|:-----------:|:---------:|
| DEB literature | 79 % | 100 % |
| Reproduction abstracts | 60 % | 98 % |
| Combined | 79 % | 100 % |

(Consensus-direction agreement is 84–85 % exact / 98–100 % within ±1.) The
broad reproduction corpus is the noisiest, as expected; `gpt-oss:120b` scores
marginally more generously than Claude (mean +0.1 to +0.3 on the 1–3 scale).

**Internal guardrail.** A large fraction of the *nearest* retrieved passages are
judged neutral, demonstrating that the adjudication step — not raw similarity —
decides support (full statistics in the accompanying infographic).

**Provenance.** For each SF, scope and judge the pipeline emits a reference list
and a snippet document carrying both judges' verdicts, so every score can be
inspected and challenged.

## S6. Relationship to the empirical AI-versus-expert comparison

The empirical comparison between these automated scores and expert ratings is
reported in the main text. Because the AI reads entire corpora statistically
whereas an expert judges from domain experience, agreement corroborates a fact
while disagreement is treated not as AI error but as a candidate, objective
knowledge gap worth further study — a target a reasoning LLM agent (or a human)
can pursue.

## S7. Reproducibility — parameter summary

| Parameter | Value |
|-----------|-------|
| Embedding model | `nomic-embed-text` (768-d), via Ollama |
| Index / metric | in-memory dense index, exact cosine |
| Retrieved per corpus | 100 → similarity ≥ 0.50 → ≤ 18 adjudicated |
| Combined scope | 12 nearest per corpus, re-adjudicated |
| Judges | `gpt-oss:120b` (Ollama) and Claude Opus 4.8 (API) |
| Judge temperature | 0.1 (gpt-oss) |
| Scopes × scores × judges | {DEB, abstracts, combined} × {evidence, consensus} × {gpt-oss, Claude} |
| SFs assessed | 62 |

## S8. Limitations

(i) Semantic proximity is not proof of support; explicit adjudication mitigates
but does not remove topical false positives. (ii) Reference counts are bounded by
retrieval depth and corpus coverage — a low count can reflect a thin corpus
(e.g. the phytoplankton facts are niche in both corpora) rather than weak science.
(iii) LLMs can hallucinate, misread context, and inherit biases; the dual-judge
design surfaces disagreement but does not eliminate shared error, so expert
spot-checking of flagged cases remains appropriate. (iv) An earlier internal run
that retrieved from only a 0.6 M-abstract subset materially undercounted
reproduction evidence (mean +1.1 references per SF were recovered by moving to
the full corpus); the results reported here use the complete ~3.9 M-abstract
corpus.

---

*Figure S1.* Method-and-validation visual abstract
(`sf_ai_method_infographic.png`): the retrieval-augmented dual-judge pipeline,
corpus statistics, cross-judge agreement, the similarity-≠-support guardrail, and
the AI↔expert knowledge-gap framing.
