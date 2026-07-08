#!/usr/bin/env python
"""
render_claude_only_reports.py — build single-judge (Claude Opus 4.8) reports
from the full-corpus dual-judge raw results.

Reads  analysis/sf_support_fullcorpus/raw/*.json
Writes analysis/sf_support_claude/
    summary_deb.md / summary_reproduction.md / summary_combined.md
    SUPPLEMENTARY_AI_assessment.md
    <scope>/<sf_id>_references.md
    <scope>/<sf_id>_snippets.md
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "analysis" / "sf_support_fullcorpus" / "raw"
OUT  = ROOT / "analysis" / "sf_support_claude"
OLD_ORDER = ROOT / "analysis" / "sf_support" / "summary_combined.md"

SCOPES = ("deb", "reproduction", "combined")
SCOPE_LABEL = {
    "deb":          "DEB literature (full, 152k chunks)",
    "reproduction": "Reproduction abstracts (full ~3.9M unique)",
    "combined":     "Combined (both full corpora)",
}


# --------------------------------------------------------------------------- #
# Load + sort
# --------------------------------------------------------------------------- #
def load():
    data = [json.load(open(f)) for f in sorted(glob.glob(str(SRC / "*.json")))]
    order = []
    if OLD_ORDER.exists():
        for line in open(OLD_ORDER):
            m = re.match(r"\| `[^`]+` \| ([^|]+?) \|", line)
            if m and m.group(1).strip() not in order:
                order.append(m.group(1).strip())
    data.sort(key=lambda d: (
        order.index(d["category"]) if d["category"] in order else 99,
        d["sf_id"]
    ))
    return data


def sc(d, scope, key):
    return d["judges"]["claude"]["scopes"][scope]["scores"][key]


# --------------------------------------------------------------------------- #
# Summary tables
# --------------------------------------------------------------------------- #
def render_summary(data, scope):
    L = [
        f"# SF support — {SCOPE_LABEL[scope]}",
        "",
        "Full-corpus retrieval (nomic-embed-text, 768-d). "
        "Judge: **Claude Opus 4.8**. "
        "Ev = evidence strength (1–3), Cons = consensus direction (1–3), "
        "Refs = distinct references supporting or contradicting.",
        "",
        "| SF | Category | Ev | Cons | Refs | Stylized fact |",
        "|----|----------|:--:|:----:|:----:|---------------|",
    ]
    for d in data:
        ev   = sc(d, scope, "evidence_strength")
        cons = sc(d, scope, "consensus_direction")
        refs = d["judges"]["claude"]["scopes"][scope]["n_references"]
        stmt = d["statement"]
        stmt = (stmt[:84] + "…") if len(stmt) > 86 else stmt
        L.append(f"| `{d['sf_id']}` | {d['category']} | {ev} | {cons} | {refs} | {stmt} |")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# Per-SF references
# --------------------------------------------------------------------------- #
def render_refs(d, scope):
    blk  = d["judges"]["claude"]["scopes"][scope]
    refs = blk["references"]
    rows = sorted(refs.values(), key=lambda r: -(r.get("supports", 0) + r.get("contradicts", 0)))
    ev   = blk["scores"]["evidence_strength"]
    cons = blk["scores"]["consensus_direction"]
    L = [
        f"# References — {d['sf_id']} — {SCOPE_LABEL[scope]}",
        "",
        f"**Stylized fact:** {d['statement']}",
        "",
        f"Claude Ev {ev}/3 · Cons {cons}/3 · refs {blk['n_references']}",
        "",
        "| # | Reference | Year | DOI | Supports | Contradicts |",
        "|---|-----------|------|-----|:--------:|:-----------:|",
    ]
    for i, r in enumerate(rows, 1):
        L.append(
            f"| {i} | {r['title']} | {r.get('year') or '—'} | "
            f"{r.get('doi') or '—'} | {r.get('supports', 0)} | {r.get('contradicts', 0)} |"
        )
    if not rows:
        L.append("| — | _no references_ | | | | |")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# Per-SF snippets
# --------------------------------------------------------------------------- #
def render_snips(d, scope):
    snips = d["judges"]["claude"]["scopes"][scope]["snippets"]
    L = [
        f"# Evidence snippets — {d['sf_id']} — {SCOPE_LABEL[scope]}",
        "",
        f"**Stylized fact:** {d['statement']}",
        "",
        "Judge: Claude Opus 4.8. Each passage: verdict (supports/contradicts/neutral) + relevance + cosine similarity.",
        "",
    ]
    badge = {"supports": "✅", "contradicts": "❌", "neutral": "▫️"}
    for i, s in enumerate(snips):
        src = s.get("title", "") + (f" ({s['year']})" if s.get("year") else "")
        sim = round(1.0 - s.get("distance", 0.5), 2)
        L += [
            f"### {i+1}. {badge.get(s['label'], '?')} {s['label']} "
            f"(relevance {s.get('relevance', 0):.1f}) · sim ~{sim:.2f}",
            f"*Source:* {src}" + (f" — DOI {s['doi']}" if s.get("doi") else ""),
            "",
            "> " + s["text"].replace("\n", " "),
            "",
        ]
    if not snips:
        L.append("_no snippets_")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# Supplementary methods text
# --------------------------------------------------------------------------- #
SUPPLEMENT = """\
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
"""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    data = load()
    OUT.mkdir(parents=True, exist_ok=True)

    for scope in SCOPES:
        (OUT / scope).mkdir(parents=True, exist_ok=True)
        (OUT / f"summary_{scope}.md").write_text(render_summary(data, scope))
        for d in data:
            (OUT / scope / f"{d['sf_id']}_references.md").write_text(render_refs(d, scope))
            (OUT / scope / f"{d['sf_id']}_snippets.md").write_text(render_snips(d, scope))

    (OUT / "SUPPLEMENTARY_AI_assessment.md").write_text(SUPPLEMENT)

    n_docs = len(data) * len(SCOPES) * 2
    print(f"wrote summaries + SUPPLEMENTARY_AI_assessment.md + {n_docs} per-SF docs -> {OUT}")


if __name__ == "__main__":
    main()
