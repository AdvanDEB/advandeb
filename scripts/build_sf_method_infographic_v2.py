#!/usr/bin/env python
"""
build_sf_method_infographic_v2.py — corrected method-and-validation visual abstract
for the FULL-CORPUS, DUAL-JUDGE stylized-fact assessment.

Reads analysis/sf_support_fullcorpus/raw/*.json ; writes
    analysis/sf_support_fullcorpus/sf_ai_method_infographic.png / .pdf
"""
from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import numpy as np  # noqa: E402
from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FC = ROOT / "analysis" / "sf_support_fullcorpus"

INK, TEAL, TEAL_D, SLATE = "#1d2733", "#0f6e78", "#0a4c54", "#475569"
AMBER, GREEN, PANEL, PAPER = "#c0612a", "#2f8f6b", "#f4f7f8", "#ffffff"
SUP, CON, NEU = "#0f6e78", "#c0612a", "#c2ccd0"
SCORES = ("deb", "reproduction", "combined")


def load():
    return [json.load(open(f)) for f in sorted(glob.glob(str(FC / "raw" / "*.json")))]


def stats(data):
    lab = {j: {c: Counter() for c in ("deb", "reproduction")} for j in ("gptoss", "claude")}
    dist = {"deb": [], "reproduction": []}
    hi = hi_neu = 0
    for d in data:
        for c in ("deb", "reproduction"):
            for s in d["judges"]["gptoss"]["scopes"][c]["snippets"]:
                dist[c].append(s["distance"])
            for j in ("gptoss", "claude"):
                for s in d["judges"][j]["scopes"][c]["snippets"]:
                    lab[j][c][s["label"]] += 1
                    if j == "gptoss" and s["distance"] < 0.30:   # sim > 0.70 = very near
                        hi += 1
                        if s["label"] == "neutral":
                            hi_neu += 1
    agree = {}
    for sc in SCORES:
        diffs = np.array([d["judges"]["gptoss"]["scopes"][sc]["scores"]["evidence_strength"]
                          - d["judges"]["claude"]["scopes"][sc]["scores"]["evidence_strength"] for d in data])
        agree[sc] = (100 * np.mean(diffs == 0), 100 * np.mean(np.abs(diffs) <= 1))
    return lab, {c: np.array(v) for c, v in dist.items()}, (100 * hi_neu / hi if hi else 0), agree


def rbox(ax, x, y, w, h, title, body, fc, tc="white", fs_t=11, fs_b=8.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.03",
                                linewidth=0, facecolor=fc, mutation_aspect=0.7))
    ax.text(x + w / 2, y + h * (0.66 if body else 0.5), title, ha="center", va="center",
            color=tc, fontsize=fs_t, fontweight="bold")
    if body:
        ax.text(x + w / 2, y + h * 0.30, body, ha="center", va="center", color=tc,
                fontsize=fs_b, linespacing=1.22)


def arr(ax, p0, p1, color=TEAL_D, lw=2, ms=15):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=ms, linewidth=lw, color=color))


def section(fig, y, text):
    ax = fig.add_axes([0.03, y, 0.94, 0.02]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.5, text, fontsize=14.5, fontweight="bold", color=TEAL_D, va="center")
    ax.plot([0.118, 1.0], [0.5, 0.5], color="#cfdadc", lw=1.4)


def main():
    data = load()
    lab, dist, pct_neu_hi, agree = stats(data)
    n = len(data)

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.edgecolor": "#c9d4d6"})
    fig = plt.figure(figsize=(12.6, 16.8), dpi=200); fig.patch.set_facecolor(PAPER)

    # title
    ax = fig.add_axes([0, 0.95, 1, 0.05]); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="square,pad=0", facecolor=TEAL_D, linewidth=0, transform=ax.transAxes))
    ax.text(0.035, 0.62, "AI-Assisted Assessment of Stylized Facts — Method & Validation",
            color="white", fontsize=18, fontweight="bold", va="center")
    ax.text(0.035, 0.22, "Full-corpus retrieval-augmented scoring, cross-checked by two independent LLM judges",
            color="#bfe3e6", fontsize=11.5, va="center")

    # METHOD
    section(fig, 0.915, "METHOD")
    ax = fig.add_axes([0.03, 0.80, 0.94, 0.105]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    stages = [
        ("1 · Stylized fact", f"{n} statements\n10 categories", TEAL),
        ("2 · Embed", "nomic-embed-text\n768-dim", SLATE),
        ("3 · Dual-corpus\nretrieval", "cosine kNN · top-100\nsim≥0.50 → ≤18", SLATE),
        ("4 · Two LLM judges", "gpt-oss:120b  +  Claude 4.8\nsupport/contradict/neutral", TEAL),
        ("5 · Scores +\nprovenance", "Evidence 1–3 · Consensus 1–3\nrefs · verbatim snippets", TEAL_D),
    ]
    g = 0.02; w = (1 - g * 4) / 5
    for i, (t, b, fc) in enumerate(stages):
        x = i * (w + g); rbox(ax, x, 0.06, w, 0.82, t, b, fc, fs_t=10.4, fs_b=8.0)
        if i < 4:
            arr(ax, (x + w + 0.0015, 0.47), (x + w + g - 0.0015, 0.47))

    # key numbers
    ax = fig.add_axes([0.03, 0.715, 0.94, 0.07]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.005,rounding_size=0.02", facecolor=PANEL, linewidth=0))
    nums = [(f"{n}", "stylized facts"), ("1,306", "DEB papers"), ("152k", "DEB-lit chunks"),
            ("~3.9 M", "unique abstracts"), ("4.44 M", "abstract chunks"), ("2", "LLM judges")]
    for i, (a, b) in enumerate(nums):
        cx = (i + 0.5) / len(nums)
        ax.text(cx, 0.64, a, ha="center", fontsize=18, fontweight="bold", color=TEAL_D)
        ax.text(cx, 0.24, b, ha="center", fontsize=9.3, color=SLATE)
        if i:
            ax.plot([i / len(nums)] * 2, [0.18, 0.82], color="#d4dee0", lw=1)

    # VALIDATION
    section(fig, 0.69, "VALIDATION")

    # (1) cross-judge agreement
    ax = fig.add_axes([0.085, 0.49, 0.40, 0.16])
    x = np.arange(3); within = [agree[s][1] for s in SCORES]; exact = [agree[s][0] for s in SCORES]
    ax.bar(x - 0.19, within, 0.36, color=TEAL, label="within ±1")
    ax.bar(x + 0.19, exact, 0.36, color=AMBER, label="exact match")
    for xi, (wv, ev) in enumerate(zip(within, exact)):
        ax.text(xi - 0.19, wv + 1.5, f"{wv:.0f}", ha="center", fontsize=8, color=TEAL_D, fontweight="bold")
        ax.text(xi + 0.19, ev + 1.5, f"{ev:.0f}", ha="center", fontsize=8, color=AMBER, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(["DEB", "Repro.", "Combined"], fontsize=9)
    ax.set_ylim(0, 112); ax.set_yticks([0, 50, 100]); ax.tick_params(length=0, labelsize=8)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.02))
    ax.set_title("1 · gpt-oss:120b ↔ Claude agreement (evidence, %)", fontsize=11.5,
                 fontweight="bold", color=TEAL_D, loc="left", pad=8)

    # (2) guardrail label mix (both judges averaged)
    ax = fig.add_axes([0.585, 0.49, 0.36, 0.16])
    corp = ["deb", "reproduction"]; clab = ["DEB papers", "Repro. abstracts"]
    def pct(c, k):
        tot = sum(lab["gptoss"][c].values()) + sum(lab["claude"][c].values())
        return 100 * (lab["gptoss"][c][k] + lab["claude"][c][k]) / tot
    y = np.arange(2)[::-1]
    sup = [pct(c, "supports") for c in corp]; con = [pct(c, "contradicts") for c in corp]; neu = [pct(c, "neutral") for c in corp]
    ax.barh(y, sup, color=SUP, label="supports", height=0.5)
    ax.barh(y, con, left=sup, color=CON, label="contradicts", height=0.5)
    ax.barh(y, neu, left=[s + c for s, c in zip(sup, con)], color=NEU, label="neutral", height=0.5)
    for i in range(2):
        ax.text(sup[i] + con[i] + neu[i] / 2, y[i], f"{neu[i]:.0f}%", ha="center", va="center", fontsize=8.5, fontweight="bold", color=INK)
    ax.set_yticks(y); ax.set_yticklabels(clab, fontsize=9); ax.set_xlim(0, 100)
    ax.set_xlabel("% of retrieved passages", fontsize=8.5, color=SLATE); ax.tick_params(length=0, labelsize=8)
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.34), ncol=3, frameon=False, fontsize=8, handlelength=1, columnspacing=1.1)
    ax.set_title("2 · Guardrail: similarity ≠ support", fontsize=11.5, fontweight="bold", color=TEAL_D, loc="left", pad=24)

    # (3) retrieval quality
    ax = fig.add_axes([0.085, 0.275, 0.40, 0.135])
    bins = np.linspace(0.0, 0.6, 26)
    for c, col, lb in [("deb", TEAL, "DEB papers"), ("reproduction", AMBER, "Repro. abstracts")]:
        ax.hist(dist[c], bins=bins, density=True, color=col, alpha=0.45, label=lb)
        ax.axvline(np.median(dist[c]), color=col, lw=1.8, ls="--")
    ax.set_title("3 · Retrieval quality", fontsize=11.5, fontweight="bold", color=TEAL_D, loc="left", pad=6)
    ax.set_xlabel("cosine distance to fact (lower = closer)", fontsize=8.5, color=SLATE)
    ax.set_yticks([]); ax.tick_params(length=0, labelsize=8)
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper right")

    # (4) AI vs expert concept
    ax = fig.add_axes([0.55, 0.265, 0.42, 0.16]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.98, "4 · AI ↔ expert comparison", fontsize=11.5, fontweight="bold", color=TEAL_D, va="top")
    rbox(ax, 0.02, 0.66, 0.45, 0.17, "AI score", "full-corpus\nstatistical reading", TEAL, fs_t=9.3, fs_b=7.2)
    rbox(ax, 0.53, 0.66, 0.45, 0.17, "Expert score", "domain opinion\n(niche · recency)", SLATE, fs_t=9.3, fs_b=7.2)
    rbox(ax, 0.30, 0.40, 0.40, 0.12, "compare", "", AMBER, fs_t=9.5)
    arr(ax, (0.24, 0.66), (0.40, 0.52)); arr(ax, (0.76, 0.66), (0.60, 0.52))
    rbox(ax, 0.02, 0.13, 0.45, 0.16, "Agree", "method corroborated", GREEN, fs_t=9.3, fs_b=7.2)
    rbox(ax, 0.53, 0.13, 0.45, 0.16, "Diverge", "candidate knowledge gap", AMBER, fs_t=9.3, fs_b=7.2)
    arr(ax, (0.42, 0.40), (0.27, 0.29), color=GREEN); arr(ax, (0.58, 0.40), (0.73, 0.29), color=AMBER)
    ax.text(0.5, 0.04, "empirical comparison reported in main text", fontsize=7.6, color=SLATE, ha="center", style="italic")

    # footer
    ax = fig.add_axes([0.03, 0.03, 0.94, 0.20]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0, 0.62), 1, 0.36, boxstyle="round,pad=0.004,rounding_size=0.02", facecolor=PANEL, linewidth=0))
    take = [("Full corpus", "~3.9M unique abstracts\n(99.99% embedded)"),
            ("Cross-checked", "two judges, 98–100%\nwithin ±1"),
            ("Adjudicated", f"{pct_neu_hi:.0f}% of nearest passages\nfiltered as neutral"),
            ("Traceable", "every score → source\npassages")]
    for i, (h, b) in enumerate(take):
        cx = (i + 0.5) / 4
        ax.text(cx, 0.90, h, ha="center", fontsize=11.5, fontweight="bold", color=TEAL_D)
        ax.text(cx, 0.715, b, ha="center", fontsize=8.4, color=SLATE, linespacing=1.2)
        if i:
            ax.plot([i / 4] * 2, [0.66, 0.94], color="#d4dee0", lw=1)
    ax.text(0, 0.50,
            "Validation philosophy.  Similarity locates candidate text; an explicit support/contradict adjudication — auditable to the "
            "verbatim passage — decides evidence. Two independent judges (gpt-oss:120b and Claude Opus 4.8) score every fact and agree "
            "within one point on 98–100% of facts, so disagreement is a focused signal rather than noise. Because the system reads entire "
            "corpora statistically while experts judge from experience, AI–expert divergence is treated as a candidate, objective "
            "knowledge gap to investigate — not as automatic AI error.",
            fontsize=8.5, color=INK, va="top", wrap=True)

    for ext in ("png", "pdf"):
        fig.savefig(FC / f"sf_ai_method_infographic.{ext}", facecolor=PAPER, bbox_inches="tight", pad_inches=0.2)
    print("wrote", FC / "sf_ai_method_infographic.png")


if __name__ == "__main__":
    main()
