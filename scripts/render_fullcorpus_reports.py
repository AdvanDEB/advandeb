#!/usr/bin/env python
"""
render_fullcorpus_reports.py — build the corrected (full-corpus, dual-judge)
reports from analysis/sf_support_fullcorpus/raw/*.json.

Outputs (under analysis/sf_support_fullcorpus/):
    summary_deb.md / summary_reproduction.md / summary_combined.md
        one table per scope: gpt-oss & Claude evidence/consensus + refs + agreement
    AGREEMENT.md
        cross-judge agreement stats + impact of the corpus fix (old vs new)
    <scope>/<sf_id>_references.md   distinct references (dual-judge support counts)
    <scope>/<sf_id>_snippets.md     retrieved passages with BOTH judges' labels
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FC = ROOT / "analysis" / "sf_support_fullcorpus"
OLD = ROOT / "analysis" / "sf_support"
SCOPES = ("deb", "reproduction", "combined")
SCOPE_LABEL = {"deb": "DEB literature (full, 152k chunks)",
               "reproduction": "Reproduction abstracts (full ~3.9M unique)",
               "combined": "Combined (both full corpora)"}


def load():
    data = [json.load(open(f)) for f in sorted(glob.glob(str(FC / "raw" / "*.json")))]
    order = []
    for line in open(OLD / "summary_combined.md"):
        m = re.match(r"\| `[^`]+` \| ([^|]+?) \|", line)
        if m and m.group(1).strip() not in order:
            order.append(m.group(1).strip())
    data.sort(key=lambda d: (order.index(d["category"]) if d["category"] in order else 99, d["sf_id"]))
    return data


def sc(d, judge, scope, key):
    return d["judges"][judge]["scopes"][scope]["scores"][key]


def render_summary(data, scope):
    L = [
        f"# Corrected SF support — {SCOPE_LABEL[scope]}",
        "",
        "Full-corpus retrieval (nomic-embed-text). Two judges cross-checked: "
        "**G** = gpt-oss:120b, **C** = Claude Opus 4.8. "
        "Ev = evidence strength (1-3), Cons = consensus direction (1-3), "
        "Refs = distinct references (Claude). ✓ = judges agree on Ev (±0), ~ = within ±1.",
        "",
        "| SF | Category | G·Ev | C·Ev | G·Cons | C·Cons | Agree | Refs | Stylized fact |",
        "|----|----------|:----:|:----:|:------:|:------:|:-----:|:----:|---------------|",
    ]
    for d in data:
        gE, cE = sc(d, "gptoss", scope, "evidence_strength"), sc(d, "claude", scope, "evidence_strength")
        gC, cC = sc(d, "gptoss", scope, "consensus_direction"), sc(d, "claude", scope, "consensus_direction")
        agree = "✓" if gE == cE else ("~" if abs(gE - cE) == 1 else "✗")
        refs = d["judges"]["claude"]["scopes"][scope]["n_references"]
        stmt = d["statement"]; stmt = (stmt[:84] + "…") if len(stmt) > 86 else stmt
        L.append(f"| `{d['sf_id']}` | {d['category']} | {gE} | {cE} | {gC} | {cC} | {agree} | {refs} | {stmt} |")
    return "\n".join(L) + "\n"


def render_agreement(data):
    L = ["# Validation — cross-judge agreement & corpus-fix impact", ""]
    L.append("## gpt-oss:120b vs Claude Opus 4.8 (evidence strength)\n")
    L.append("| Scope | Exact match | Within ±1 | Mean (gpt-oss − Claude) |")
    L.append("|-------|:-----------:|:---------:|:-----------------------:|")
    for scope in SCOPES:
        diffs = np.array([sc(d, "gptoss", scope, "evidence_strength")
                          - sc(d, "claude", scope, "evidence_strength") for d in data])
        L.append(f"| {scope} | {100*np.mean(diffs==0):.0f}% | {100*np.mean(np.abs(diffs)<=1):.0f}% | {diffs.mean():+.2f} |")
    # consensus agreement
    L.append("\n## gpt-oss:120b vs Claude Opus 4.8 (consensus direction)\n")
    L.append("| Scope | Exact match | Within ±1 |")
    L.append("|-------|:-----------:|:---------:|")
    for scope in SCOPES:
        diffs = np.array([sc(d, "gptoss", scope, "consensus_direction")
                          - sc(d, "claude", scope, "consensus_direction") for d in data])
        L.append(f"| {scope} | {100*np.mean(diffs==0):.0f}% | {100*np.mean(np.abs(diffs)<=1):.0f}% |")

    # corpus-fix impact (reproduction): old chroma subset (claude) vs new full corpus (claude)
    old = {json.load(open(f))["sf_id"]: json.load(open(f)) for f in glob.glob(str(OLD / "raw" / "*.json"))}
    L.append("\n## Impact of fixing the corpus (reproduction side, Claude judge)\n")
    L.append("Old = 0.6 M ChromaDB subset (MiniLM). New = full ~3.9 M unique abstracts (nomic).\n")
    L.append("| SF | old Ev | new Ev | Δ | old refs | new refs |")
    L.append("|----|:------:|:------:|:-:|:--------:|:--------:|")
    dEv, dref = [], []
    for d in data:
        sid = d["sf_id"]
        if sid not in old:
            continue
        oE = old[sid]["scopes"]["reproduction"]["scores"]["evidence_strength"]
        nE = sc(d, "claude", "reproduction", "evidence_strength")
        oR = old[sid]["scopes"]["reproduction"]["n_references"]
        nR = d["judges"]["claude"]["scopes"]["reproduction"]["n_references"]
        dEv.append(nE - oE); dref.append(nR - oR)
        if nE != oE or nR != oR:
            L.append(f"| `{sid}` | {oE} | {nE} | {nE-oE:+d} | {oR} | {nR} |")
    L.append(f"\n**Mean Ev change:** {np.mean(dEv):+.2f}  ·  **Mean ref change:** {np.mean(dref):+.1f}  "
             f"(raised {sum(1 for x in dEv if x>0)}, unchanged {sum(1 for x in dEv if x==0)}, lowered {sum(1 for x in dEv if x<0)})")
    return "\n".join(L) + "\n"


def render_refs(d, scope):
    g = d["judges"]["gptoss"]["scopes"][scope]
    c = d["judges"]["claude"]["scopes"][scope]
    # merge reference dicts across judges by document key
    refs = {}
    for judge, blk in (("G", g), ("C", c)):
        for k, r in blk["references"].items():
            e = refs.setdefault(k, {"title": r["title"], "year": r["year"], "doi": r["doi"],
                                    "G": 0, "C": 0})
            e[judge] = r["supports"] + r["contradicts"]
    rows = sorted(refs.values(), key=lambda r: -(r["G"] + r["C"]))
    L = [f"# References — {d['sf_id']} — {SCOPE_LABEL[scope]}", "",
         f"**Stylized fact:** {d['statement']}", "",
         f"gpt-oss Ev {g['scores']['evidence_strength']}/3 · Claude Ev {c['scores']['evidence_strength']}/3 · "
         f"refs(G) {g['n_references']} / refs(C) {c['n_references']}", "",
         "| # | Reference | Year | DOI | G hits | C hits |",
         "|---|-----------|------|-----|:------:|:------:|"]
    for i, r in enumerate(rows, 1):
        L.append(f"| {i} | {r['title']} | {r['year'] or '—'} | {r['doi'] or '—'} | {r['G']} | {r['C']} |")
    if not rows:
        L.append("| — | _no references_ | | | | |")
    return "\n".join(L) + "\n"


def render_snips(d, scope):
    g = d["judges"]["gptoss"]["scopes"][scope]["snippets"]
    c = d["judges"]["claude"]["scopes"][scope]["snippets"]
    L = [f"# Evidence snippets — {d['sf_id']} — {SCOPE_LABEL[scope]}", "",
         f"**Stylized fact:** {d['statement']}", "",
         "Each passage shows both judges' verdicts (G = gpt-oss:120b, C = Claude).", ""]
    badge = {"supports": "✅", "contradicts": "❌", "neutral": "▫️"}
    for i, s in enumerate(g):
        cs = c[i] if i < len(c) else {"label": "?", "relevance": 0}
        src = s["title"] + (f" ({s['year']})" if s.get("year") else "")
        L += [f"### {i+1}. G:{badge.get(s['label'],'?')}{s['label']} (r{s['relevance']:.1f}) · "
              f"C:{badge.get(cs['label'],'?')}{cs['label']} (r{cs['relevance']:.1f}) · sim~{1-s['distance']:.2f}",
              f"*Source:* {src}" + (f" — DOI {s['doi']}" if s.get("doi") else ""), "",
              "> " + s["text"].replace("\n", " "), ""]
    if not g:
        L.append("_no snippets_")
    return "\n".join(L) + "\n"


def main():
    data = load()
    for scope in SCOPES:
        (FC / scope).mkdir(parents=True, exist_ok=True)
        (FC / f"summary_{scope}.md").write_text(render_summary(data, scope))
        for d in data:
            (FC / scope / f"{d['sf_id']}_references.md").write_text(render_refs(d, scope))
            (FC / scope / f"{d['sf_id']}_snippets.md").write_text(render_snips(d, scope))
    (FC / "AGREEMENT.md").write_text(render_agreement(data))
    print(f"wrote summaries + AGREEMENT.md + {len(data)*len(SCOPES)*2} per-SF docs -> {FC}")


if __name__ == "__main__":
    main()
