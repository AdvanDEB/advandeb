#!/usr/bin/env python
"""
analyze_sf_support.py — Score scientific support for DEB stylized facts (SFs)
against the two corpora held in the AdvanDEB ChromaDB vector store.

Two corpora (distinguished by the ``general_domain`` chunk metadata):
    - DEB domain papers         -> general_domain == ""            (~1.6k docs)
    - Reproduction abstracts    -> general_domain == "reproduction" (~600k docs)

For every SF the script:
    1. embeds the SF statement (sentence-transformers, same model as ingestion);
    2. retrieves the top-K nearest chunks from each corpus separately;
    3. de-duplicates and trims them into candidate snippets;
    4. asks a Claude model (BYOK key, decrypted from the app MongoDB) to judge
       each snippet as supports / contradicts / neutral and to assign:
         - evidence_strength    1-3 (weak / moderate / strong support)
         - consensus_direction  1-3 (contradicted-or-mixed / neutral / corroborated)
    5. counts the distinct *references* (documents) that actually deal with the SF.

This is done independently for three scopes — ``deb``, ``reproduction`` and
``combined`` (a fresh judgement over the merged top snippets of both corpora).

Outputs (under --out, default analysis/sf_support/):
    raw/<sf_id>.json                  full machine-readable result per SF (cache)
    summary_deb.md
    summary_reproduction.md
    summary_combined.md               one score/ref-count table per scope
    deb/<sf_id>_references.md         per-SF reference list  (per scope)
    deb/<sf_id>_snippets.md           per-SF text snippets   (per scope)
    reproduction/... combined/...

The script is resumable: an SF whose raw/<sf_id>.json already exists is not
re-judged (delete the file or pass --force to redo it).

This is an analysis / reporting script — it is NOT part of the app runtime.

Usage:
    conda run -n advandeb python scripts/analyze_sf_support.py
    python scripts/analyze_sf_support.py --only feeding_01,growth_04
    python scripts/analyze_sf_support.py --model claude-sonnet-4-6 --force
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "knowledge-builder"))
sys.path.insert(0, str(REPO_ROOT / "app" / "backend"))

# --------------------------------------------------------------------------- #
# The 36 stylized facts, grouped by category.                                 #
# --------------------------------------------------------------------------- #

SFS: list[dict] = [
    # ---- Feeding --------------------------------------------------------- #
    ("feeding_01", "Feeding", "Many species (most animals and plants) have an embryo stage that does not feed."),
    ("feeding_02", "Feeding", "During starvation, organisms are able to reproduce, grow, and survive for some time."),
    ("feeding_03", "Feeding", "At abundant food, feeding rate is at a maximum, independent of food density."),
    ("feeding_04", "Feeding", "Organisms show a transient increase in metabolic rate independent of body mass after ingesting food (heat increment of feeding)."),
    ("feeding_05", "Feeding", "At abundant food, feeding reduces at high temperatures in some species."),
    # ---- Growth ---------------------------------------------------------- #
    ("growth_01", "Growth", "Length of isomorphic organisms at abundant food follows the von Bertalanffy growth curve."),
    ("growth_02", "Growth", "Many species exhibit indeterminate growth, meaning they do not stop growing after reproduction starts."),
    ("growth_03", "Growth", "Growth can be simultaneous with reproduction, but growth can also cease long before reproduction is initiated."),
    ("growth_04", "Growth", "The logarithm of the von Bertalanffy growth rate of different species corrected for a common body temperature decreases almost linearly with the logarithm of the species maximum size."),
    ("growth_05", "Growth", "The inverse of the von Bertalanffy growth rate for organisms of the same species at different food availabilities decreases linearly with ultimate length."),
    ("growth_06", "Growth", "Foetuses increase in weight proportional to cubed time."),
    ("growth_07", "Growth", "Foetuses increase in weight exponentially."),
    ("growth_08", "Growth", "At constant food density, no substantial shrinking occurs independent of ageing."),
    ("growth_09", "Growth", "Increase in temperature reduces ultimate length in some species."),
    ("growth_10", "Growth", "Maximal growth rate in some species can be obtained through high feeding, regardless of nutritional status (energy reserves)."),
    ("growth_11", "Growth", "Some species reduce growth during reproduction."),
    # ---- Reproduction ---------------------------------------------------- #
    ("reproduction_01", "Reproduction", "Many species have a juvenile stage that does not reproduce."),
    ("reproduction_02", "Reproduction", "Reproduction increases with size intra-specifically but decreases with size inter-specifically."),
    ("reproduction_03", "Reproduction", "A range of constant low food levels exists where an individual can survive but reproduction is never initiated."),
    ("reproduction_04", "Reproduction", "Egg size (or initial reserve) covaries with the nutritional status of the mother."),
    ("reproduction_05", "Reproduction", "In some species energy committed per offspring does not depend significantly on the nutritional status of the mother."),
    # ---- Respiration ----------------------------------------------------- #
    ("respiration_01", "Respiration", "Freshly laid eggs/seeds initially use negligible amounts of dioxygen."),
    ("respiration_02", "Respiration", "Dioxygen use increases with decreasing mass in embryos and increases with mass in juveniles and adults."),
    ("respiration_03", "Respiration", "Dioxygen use by isomorphs scales approximately with body weight raised to the power 0.75 (Kleiber's law)."),
    ("respiration_04", "Respiration", "Intraspecific scaling of maximum dioxygen use with size depends on morphology of the energy and material transport network(s)."),
    ("respiration_05", "Respiration", "Intraspecific scaling of maximum dioxygen use changes with developmental stage."),
    # ---- Stoichiometry --------------------------------------------------- #
    ("stoichiometry_01", "Stoichiometry", "The chemical composition of organisms depends on their nutritional status (starved vs. well-fed)."),
    ("stoichiometry_02", "Stoichiometry", "Organisms at constant food density converge to a constant chemical composition (weak homeostasis)."),
    # ---- General Physiology --------------------------------------------- #
    ("genphys_01", "General Physiology", "Dissipating heat is a weighted sum of three mass flows: carbon dioxide, dioxygen, and nitrogenous waste."),
    ("genphys_02", "General Physiology", "Cells in a tissue are metabolically similar regardless of the size of the organism."),
    ("genphys_03", "General Physiology", "Some energy always dissipates, also in absence of dioxygen."),
    ("genphys_04", "General Physiology", "Survivor curves for life span terminated by ageing are typically well described by the Weibull and Gompertz models."),
    ("genphys_05", "General Physiology", "Life span typically increases inter-specifically with maximum body length in endotherms, hardly depends on body length in ectotherms."),
    ("genphys_06", "General Physiology", "Simpler transport network morphologies (also passive transport systems) should have lower maintenance."),
    ("genphys_07", "General Physiology", "Within a species or related group, individuals in colder climates tend to be larger, while those in warmer climates are smaller (Bergmann's rule)."),
    ("genphys_08", "General Physiology", "Scaling of maximal feeding rate with size should depend on transport network morphology."),
    # ---- Hypoxia / Dissolved Oxygen ------------------------------------- #
    ("hypoxia_01", "Hypoxia / DO", "Organisms reduce their feeding rate with decreasing dissolved oxygen (DO) level."),
    ("hypoxia_02", "Hypoxia / DO", "Food assimilation efficiency can be enhanced, unchanged or reduced under hypoxia, depending on species."),
    ("hypoxia_03", "Hypoxia / DO", "Growth decreases with decreasing DO level, due to reduction in energy uptake and/or increase in energy expenditure (dissipation)."),
    ("hypoxia_04", "Hypoxia / DO", "Energy allocation is reprioritized to first pay maintenance costs under hypoxic conditions."),
    ("hypoxia_05", "Hypoxia / DO", "Under moderate hypoxia, organisms may continue to allocate energy to reproduction even if there is no allocation to structural growth."),
    ("hypoxia_06", "Hypoxia / DO", "Decrease in DO may decrease the gonado-somatic index."),
    ("hypoxia_07", "Hypoxia / DO", "Hypoxia can disrupt endocrine functions, affecting gametogenesis, sexual maturity, gamete quality and fecundity."),
    ("hypoxia_08", "Hypoxia / DO", "O2 consumption starts to diminish at a reduced PO2 below a critical saturation level; when an animal has an elevated O2 consumption (swimming, digesting, etc.), consumption starts to diminish at a greater PO2 than the critical saturation."),
    ("hypoxia_09", "Hypoxia / DO", "Above the critical saturation, compensatory mechanisms compensate the O2 reduction to maintain respiration and sustain the standard metabolic rate. These responses can lead to increased O2 consumption (e.g. ventilation rate, heartbeat, mobility)."),
    ("hypoxia_10", "Hypoxia / DO", "Behavioural responses under hypoxia can lead to decreased O2 consumption (e.g. reduce activity, reduce feeding); some species may also enter a hypometabolic state for surviving."),
    ("hypoxia_11", "Hypoxia / DO", "Anaerobiosis can start under the critical saturation threshold, with less efficient energy production and toxic end-product formation (e.g. lactate, acidosis), leading to a long-lasting (several hours) imprint on metabolism (oxygen debt)."),
    ("hypoxia_12", "Hypoxia / DO", "Lethal DO level and time are different across taxa."),
    ("hypoxia_13", "Hypoxia / DO", "Lethal DO level increases with increasing metabolic activity."),
    ("hypoxia_14", "Hypoxia / DO", "Exponential increase of survival time under anaerobic glycolysis with body mass due to the decrease of mass-specific metabolic rate."),
    # ---- Phytoplankton N:C ratio ---------------------------------------- #
    ("nc_01", "N:C ratio", "N:C increases with dilution rate in nutrient limiting conditions."),
    ("nc_02", "N:C ratio", "N:C decreases with dilution rate in light limiting conditions."),
    ("nc_03", "N:C ratio", "N:C decreases with temperature in nutrient or light limiting conditions."),
    ("nc_04", "N:C ratio", "N:C decreases with irradiance in nutrient replete conditions."),
    # ---- Phytoplankton Chlorophyll -------------------------------------- #
    ("chl_01", "Chlorophyll", "chl:C increases with dilution rate in nutrient limiting conditions."),
    ("chl_02", "Chlorophyll", "chl:C decreases with dilution rate in light limiting conditions."),
    ("chl_03", "Chlorophyll", "Chlorophyll concentration increases with dilution rate in nutrient limiting conditions."),
    ("chl_04", "Chlorophyll", "Chlorophyll concentration decreases with irradiance."),
    ("chl_05", "Chlorophyll", "chl:N decreases with irradiance for constant dilution rate in nutrient replete conditions."),
    # ---- Phytoplankton EPS Production ----------------------------------- #
    ("eps_01", "EPS Production", "No EPS production results directly from light-dependent carbon assimilation."),
    ("eps_02", "EPS Production", "Cellular production rates of EPS and other extracellular carbohydrates increase with specific growth rate."),
    ("eps_03", "EPS Production", "EPS type 1 is produced under all conditions while type 2 only in nutrient-limiting cells."),
]

CORPORA = {
    "deb": "",                       # general_domain value for DEB papers
    "reproduction": "reproduction",  # general_domain value for repro abstracts
}
CORPUS_LABEL = {
    "deb": "DEB domain papers",
    "reproduction": "Reproduction abstracts",
    "combined": "Combined (both corpora)",
}

# --------------------------------------------------------------------------- #
# Tunables                                                                     #
# --------------------------------------------------------------------------- #
K_RETRIEVE = 60          # nearest chunks pulled from each corpus
MAX_SNIPPETS = 18        # candidate snippets sent to the judge per corpus
COMBINED_PER_CORPUS = 12 # snippets taken from each corpus for the combined judge
SNIPPET_CHARS = 700      # max chars of chunk text kept per snippet
RELEVANT_THRESHOLD = 0.5 # judge relevance >= this counts a snippet as "dealing with" the SF


# --------------------------------------------------------------------------- #
# BYOK key                                                                     #
# --------------------------------------------------------------------------- #

def load_anthropic_key() -> str:
    """Decrypt the stored Anthropic BYOK key from the app MongoDB."""
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / "app" / "backend" / ".env")
    from pymongo import MongoClient
    from app.core.crypto import decrypt  # type: ignore

    url = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    dbn = os.environ.get("MONGODB_DB_NAME") or "advandeb"
    coll = MongoClient(url)[dbn].user_llm_keys
    row = coll.find_one({"provider": "anthropic", "encrypted_key": {"$exists": True}})
    if not row:
        raise SystemExit("No stored Anthropic BYOK key found in user_llm_keys.")
    return decrypt(row["encrypted_key"])


# --------------------------------------------------------------------------- #
# Retrieval                                                                    #
# --------------------------------------------------------------------------- #

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass
class Snippet:
    document_id: str
    title: str
    doi: str
    year: str
    distance: float
    text: str
    corpus: str
    # filled in by the judge:
    label: str = "neutral"
    relevance: float = 0.0


def retrieve(emb, chroma, query_vec, corpus_key: str) -> list[Snippet]:
    """Top distinct snippets for one corpus, ordered by ascending distance."""
    domain = CORPORA[corpus_key]
    raw = chroma.search(query_vec, n_results=K_RETRIEVE, where={"general_domain": domain})
    seen: set[str] = set()
    out: list[Snippet] = []
    for r in raw:
        text = _norm(r["text"])
        if len(text) < 40:
            continue
        key = text[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        m = r.get("metadata", {}) or {}
        out.append(
            Snippet(
                document_id=str(m.get("document_id", "")),
                title=str(m.get("title") or m.get("source_path") or "(untitled)"),
                doi=str(m.get("doi") or ""),
                year=str(m.get("year") or ""),
                distance=float(r["distance"]),
                text=text[:SNIPPET_CHARS],
                corpus=corpus_key,
            )
        )
        if len(out) >= MAX_SNIPPETS:
            break
    return out


# --------------------------------------------------------------------------- #
# LLM judge                                                                    #
# --------------------------------------------------------------------------- #

JUDGE_SYSTEM = (
    "You are a meticulous scientific-evidence assessor for Dynamic Energy Budget "
    "(DEB) theory. You judge whether retrieved literature snippets support, "
    "contradict, or are merely topically related to a stated empirical pattern "
    "(a 'stylized fact'). You never invent evidence and you only use the snippets "
    "provided. You output strict JSON and nothing else."
)

JUDGE_TEMPLATE = """\
STYLIZED FACT (category: {category}):
"{statement}"

Below are {n} numbered snippets retrieved from {corpus_label}. Each may or may
not be relevant. For EACH snippet decide:
  - label: "supports" (the snippet provides evidence consistent with / affirming
            the stylized fact), "contradicts" (evidence against it), or
            "neutral" (off-topic, or merely mentions the area without bearing on
            the truth of the fact).
  - relevance: 0.0-1.0, how directly the snippet bears on the stylized fact.

Then give two overall scores for THIS corpus:
  - evidence_strength (1-3):  1 = weak / sparse / no real support,
                              2 = moderate support,
                              3 = strong, multiple clear supporting references.
  - consensus_direction (1-3): 1 = predominantly contradicted or mixed-against,
                               2 = neutral / insufficient evidence either way,
                               3 = corroborated (clearly supported, little conflict).
And a one-paragraph rationale.

Snippets:
{snippets}

Return ONLY this JSON (no markdown fence):
{{"snippets": [{{"i": 1, "label": "supports|contradicts|neutral", "relevance": 0.0}}],
  "evidence_strength": 1, "consensus_direction": 1, "rationale": "..."}}
"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # grab the outermost {...}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def judge(client, model: str, category: str, statement: str,
          corpus_label: str, snippets: list[Snippet]) -> dict:
    numbered = "\n".join(
        f"[{i+1}] (source: {s.title}) {s.text}" for i, s in enumerate(snippets)
    )
    prompt = JUDGE_TEMPLATE.format(
        category=category, statement=statement, n=len(snippets),
        corpus_label=corpus_label, snippets=numbered,
    )
    last_err = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                system=JUDGE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _parse_json(resp.content[0].text)
            # apply per-snippet judgements back onto the Snippet objects
            for item in data.get("snippets", []):
                idx = int(item.get("i", 0)) - 1
                if 0 <= idx < len(snippets):
                    snippets[idx].label = str(item.get("label", "neutral"))
                    snippets[idx].relevance = float(item.get("relevance", 0.0))
            return {
                "evidence_strength": int(data.get("evidence_strength", 1)),
                "consensus_direction": int(data.get("consensus_direction", 2)),
                "rationale": str(data.get("rationale", "")).strip(),
            }
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"judge failed after retries: {last_err}")


# --------------------------------------------------------------------------- #
# Aggregation                                                                  #
# --------------------------------------------------------------------------- #

def references_from(snippets: list[Snippet]) -> dict[str, dict]:
    """Group relevant snippets into distinct documents (references)."""
    refs: dict[str, dict] = {}
    for s in snippets:
        relevant = s.label in ("supports", "contradicts") or s.relevance >= RELEVANT_THRESHOLD
        if not relevant:
            continue
        key = s.document_id or s.title
        r = refs.setdefault(key, {
            "title": s.title, "doi": s.doi, "year": s.year, "corpus": s.corpus,
            "n_chunks": 0, "supports": 0, "contradicts": 0, "best_distance": s.distance,
        })
        r["n_chunks"] += 1
        if s.label == "supports":
            r["supports"] += 1
        elif s.label == "contradicts":
            r["contradicts"] += 1
        r["best_distance"] = min(r["best_distance"], s.distance)
    return refs


def snippet_to_dict(s: Snippet) -> dict:
    return {
        "document_id": s.document_id, "title": s.title, "doi": s.doi,
        "year": s.year, "distance": round(s.distance, 4), "corpus": s.corpus,
        "label": s.label, "relevance": round(s.relevance, 3), "text": s.text,
    }


def analyze_sf(client, model, emb, chroma, sf_id, category, statement) -> dict:
    query_vec = emb.embed_query(statement)
    result = {"sf_id": sf_id, "category": category, "statement": statement,
              "model": model, "scopes": {}}

    per_corpus_snips: dict[str, list[Snippet]] = {}
    for corpus_key in ("deb", "reproduction"):
        snips = retrieve(emb, chroma, query_vec, corpus_key)
        scores = judge(client, model, category, statement,
                       CORPUS_LABEL[corpus_key], snips)
        per_corpus_snips[corpus_key] = snips
        refs = references_from(snips)
        result["scopes"][corpus_key] = {
            "scores": scores,
            "n_references": len(refs),
            "references": refs,
            "snippets": [snippet_to_dict(s) for s in snips],
        }

    # combined: fresh judgement over merged top snippets from both corpora
    combined = (
        sorted(per_corpus_snips["deb"], key=lambda s: s.distance)[:COMBINED_PER_CORPUS]
        + sorted(per_corpus_snips["reproduction"], key=lambda s: s.distance)[:COMBINED_PER_CORPUS]
    )
    # fresh Snippet copies so the combined judgement doesn't clobber per-corpus labels
    combined = [
        Snippet(s.document_id, s.title, s.doi, s.year, s.distance, s.text, s.corpus)
        for s in combined
    ]
    cscores = judge(client, model, category, statement,
                    CORPUS_LABEL["combined"], combined)
    crefs = references_from(combined)
    result["scopes"]["combined"] = {
        "scores": cscores,
        "n_references": len(crefs),
        "references": crefs,
        "snippets": [snippet_to_dict(s) for s in combined],
    }
    return result


# --------------------------------------------------------------------------- #
# Report rendering                                                             #
# --------------------------------------------------------------------------- #

def render_references_md(sf, scope, data) -> str:
    refs = data["references"]
    rows = sorted(refs.values(), key=lambda r: (-(r["supports"] + r["contradicts"]), r["best_distance"]))
    lines = [
        f"# References — {sf['sf_id']}",
        "",
        f"**Scope:** {CORPUS_LABEL[scope]}  ",
        f"**Category:** {sf['category']}  ",
        f"**Stylized fact:** {sf['statement']}",
        "",
        f"**Evidence-strength score:** {data['scores']['evidence_strength']}/3 &nbsp;|&nbsp; "
        f"**Consensus-direction score:** {data['scores']['consensus_direction']}/3 &nbsp;|&nbsp; "
        f"**References dealing with this SF:** {data['n_references']}",
        "",
        "| # | Reference | Year | DOI | Supporting | Contradicting | Best cos-dist |",
        "|---|-----------|------|-----|:----------:|:-------------:|:-------------:|",
    ]
    for i, r in enumerate(rows, 1):
        doi = r["doi"] or "—"
        lines.append(
            f"| {i} | {r['title']} | {r['year'] or '—'} | {doi} | "
            f"{r['supports']} | {r['contradicts']} | {r['best_distance']:.3f} |"
        )
    if not rows:
        lines.append("| — | _No references in this corpus dealt with the SF._ | | | | | |")
    lines += ["", "_Rationale:_ " + data["scores"].get("rationale", ""), ""]
    return "\n".join(lines)


def render_snippets_md(sf, scope, data) -> str:
    # keep the judge-input order so the rationale's snippet numbers map 1:1
    snips = data["snippets"]
    lines = [
        f"# Evidence snippets — {sf['sf_id']}",
        "",
        f"**Scope:** {CORPUS_LABEL[scope]}  ",
        f"**Stylized fact:** {sf['statement']}",
        "",
    ]
    for i, s in enumerate(snips, 1):
        badge = {"supports": "✅ supports", "contradicts": "❌ contradicts"}.get(s["label"], "▫️ neutral")
        src = s["title"]
        if s["year"]:
            src += f" ({s['year']})"
        lines += [
            f"### {i}. {badge} — relevance {s['relevance']:.2f} — cos-dist {s['distance']:.3f}",
            f"*Source:* {src}" + (f" — DOI {s['doi']}" if s["doi"] else ""),
            "",
            "> " + s["text"].replace("\n", " "),
            "",
        ]
    if not snips:
        lines.append("_No snippets retrieved._")
    return "\n".join(lines)


def render_summary_md(scope, results) -> str:
    lines = [
        f"# SF scientific-support summary — {CORPUS_LABEL[scope]}",
        "",
        "Scores: **Ev** = evidence strength (1 weak … 3 strong), "
        "**Cons** = consensus direction (1 contradicted/mixed, 2 neutral, 3 corroborated). "
        "**Refs** = distinct documents in this corpus that deal with the SF.",
        "",
        "| SF | Category | Ev | Cons | Refs | Stylized fact |",
        "|----|----------|:--:|:----:|:----:|---------------|",
    ]
    for res in results:
        d = res["scopes"][scope]
        sc = d["scores"]
        stmt = res["statement"]
        stmt = (stmt[:90] + "…") if len(stmt) > 92 else stmt
        lines.append(
            f"| `{res['sf_id']}` | {res['category']} | {sc['evidence_strength']} | "
            f"{sc['consensus_direction']} | {d['n_references']} | {stmt} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO_ROOT / "analysis" / "sf_support"))
    ap.add_argument("--model", default=os.environ.get("SF_JUDGE_MODEL", "claude-opus-4-8"))
    ap.add_argument("--only", default="", help="comma-separated sf_ids to run")
    ap.add_argument("--force", action="store_true", help="re-judge even if cached")
    args = ap.parse_args()

    out = Path(args.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for scope in ("deb", "reproduction", "combined"):
        (out / scope).mkdir(parents=True, exist_ok=True)

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    sfs = [s for s in SFS if (not only or s[0] in only)]

    print(f"[setup] loading embedding model + chroma + anthropic ({args.model}) …")
    from advandeb_kb.services.embedding_service import EmbeddingService
    from advandeb_kb.services.chromadb_service import ChromaDBService
    import anthropic

    emb = EmbeddingService()
    chroma = ChromaDBService()
    client = anthropic.Anthropic(api_key=load_anthropic_key())
    print(f"[setup] chroma chunks = {chroma.count():,}")

    results = []
    for n, (sf_id, category, statement) in enumerate(sfs, 1):
        cache = raw_dir / f"{sf_id}.json"
        if cache.exists() and not args.force:
            results.append(json.loads(cache.read_text()))
            print(f"[{n}/{len(sfs)}] {sf_id}: cached")
            continue
        t0 = time.time()
        print(f"[{n}/{len(sfs)}] {sf_id}: retrieving + judging …", flush=True)
        res = analyze_sf(client, args.model, emb, chroma, sf_id, category, statement)
        cache.write_text(json.dumps(res, indent=2, ensure_ascii=False))
        results.append(res)
        sc = res["scopes"]
        print(
            f"          done in {time.time()-t0:.0f}s  "
            f"deb(Ev{sc['deb']['scores']['evidence_strength']},refs{sc['deb']['n_references']})  "
            f"repro(Ev{sc['reproduction']['scores']['evidence_strength']},refs{sc['reproduction']['n_references']})  "
            f"comb(Ev{sc['combined']['scores']['evidence_strength']},refs{sc['combined']['n_references']})"
        )

    # keep canonical SF ordering in reports
    order = {s[0]: i for i, s in enumerate(SFS)}
    results.sort(key=lambda r: order.get(r["sf_id"], 999))

    print("[reports] writing markdown …")
    for scope in ("deb", "reproduction", "combined"):
        (out / f"summary_{scope}.md").write_text(render_summary_md(scope, results))
        for res in results:
            sf = {"sf_id": res["sf_id"], "category": res["category"], "statement": res["statement"]}
            data = res["scopes"][scope]
            (out / scope / f"{res['sf_id']}_references.md").write_text(render_references_md(sf, scope, data))
            (out / scope / f"{res['sf_id']}_snippets.md").write_text(render_snippets_md(sf, scope, data))

    print(f"[done] {len(results)} SFs -> {out}")
    print("       summaries: summary_deb.md, summary_reproduction.md, summary_combined.md")


if __name__ == "__main__":
    main()
