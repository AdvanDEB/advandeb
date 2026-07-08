# Supplementary Material — AI-Assisted Scientific-Support Assessment of Stylized Facts

## S1. Purpose

Each stylized fact (SF) reported in the main text was assigned an automated,
literature-grounded support score by a retrieval-augmented, large-language-model
(LLM) pipeline. The goal is to make evidence gathering across corpora of millions
of documents systematic, reproducible, and fully traceable to primary sources.
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
up to **18** distinct passages to the judge. Retrieval is performed
independently per corpus.

## S4. LLM adjudication

The candidate passages are submitted, together with the SF statement and its
category, to **Claude Opus 4.8** (Anthropic API) as the scoring judge.

The judge operates under a fixed instruction that forbids use of outside knowledge;
it labels every passage as **supporting**, **contradicting**, or **neutral**, with a
0–1 relevance score. This adjudication step is the heart of the method: semantic
similarity locates topically related text, but only an explicit support/contradict
judgment turns that text into evidence. The passage-level verdicts are then
aggregated per SF and corpus into:

- **evidence strength (1–3)** — 1 weak/sparse, 2 moderate, 3 strong;
- **consensus direction (1–3)** — 1 contradicted/mixed, 2 neutral/insufficient,
  3 corroborated;
- a **reference count** — distinct documents contributing supporting or
  contradicting passages (relevance ≥ 0.5).

The assessment is run independently over the DEB corpus, the reproduction corpus,
and a **combined** scope (a fresh judgment over the merged nearest passages of both
corpora). Every score resolves to its source documents and verbatim passages, so
any rating is auditable back to primary literature.

## S5. Internal validity

**Similarity ≠ support guardrail.** A substantial fraction of the *nearest*
retrieved passages are judged neutral, demonstrating that the adjudication step —
not raw similarity — decides support. This prevents high cosine proximity to
topically related but non-evidential text from inflating scores.

**Provenance.** For each SF, scope, and corpus the pipeline emits a reference list
and a snippet document carrying the judge's verdict, relevance, and cosine
similarity, so every score can be inspected and challenged.

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
| Index / metric | in-memory dense index, exact cosine similarity |
| Retrieved per corpus | 100 → similarity ≥ 0.50 → ≤ 18 adjudicated |
| Combined scope | 12 nearest per corpus, re-adjudicated |
| Judge | Claude Opus 4.8 (Anthropic API) |
| Scopes × scores | {DEB, abstracts, combined} × {evidence strength, consensus direction} |
| SFs assessed | 62 |

## S8. Limitations

(i) Semantic proximity is not proof of support; explicit adjudication mitigates
but does not remove topical false positives. (ii) Reference counts are bounded by
retrieval depth and corpus coverage — a low count can reflect a thin corpus
(e.g. the phytoplankton facts are niche in both corpora) rather than weak science.
(iii) LLMs can hallucinate, misread context, and inherit biases; expert spot-checking
of flagged cases remains appropriate. (iv) An earlier internal run that retrieved
from only a 0.6 M-abstract subset materially undercounted reproduction evidence
(mean +1.1 references per SF were recovered by moving to the full corpus); the
results reported here use the complete ~3.9 M-abstract corpus.

---

*Figure S1.* Method-and-validation visual abstract
(`sf_ai_method_infographic.png`): the retrieval-augmented pipeline, corpus
statistics, the similarity-≠-support guardrail, and the AI↔expert
knowledge-gap framing.
