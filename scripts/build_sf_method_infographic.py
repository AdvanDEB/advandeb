#!/usr/bin/env python
"""
build_sf_method_infographic.py — methodological + validation visual abstract for
the AI-assisted stylized-fact (SF) assessment.

Focus: HOW the system works and HOW it is validated (not the per-SF results).

Panels:
    METHOD      five-stage retrieval-augmented adjudication pipeline
    VALIDATION  (1) human-in-the-loop curation workflow
                (2) internal guardrails  — real run statistics
                (3) retrieval quality    — real cosine-distance distributions
                (4) AI vs expert         — conceptual comparison / knowledge-gap
                                           discovery (empirical numbers: main text)

Reads analysis/sf_support/raw/*.json ; writes
    analysis/sf_support/sf_ai_method_infographic.png / .pdf
"""
from __future__ import annotations

import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np  # noqa: E402
from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "analysis" / "sf_support"

INK = "#1d2733"
TEAL = "#0f6e78"
TEAL_D = "#0a4c54"
SLATE = "#475569"
AMBER = "#c0612a"
GREEN = "#2f8f6b"
PANEL = "#f4f7f8"
PAPER = "#ffffff"
SUP = "#0f6e78"
CON = "#c0612a"
NEU = "#c2ccd0"


def load():
    return [json.load(open(f)) for f in sorted(glob.glob(str(OUTDIR / "raw" / "*.json")))]


def run_stats(data):
    lab = {s: Counter() for s in ("deb", "reproduction")}
    dist = {s: [] for s in ("deb", "reproduction")}
    hi = hi_neu = 0
    for d in data:
        for s in ("deb", "reproduction"):
            for sn in d["scopes"][s]["snippets"]:
                lab[s][sn["label"]] += 1
                dist[s].append(sn["distance"])
                if sn["distance"] < 0.45:
                    hi += 1
                    if sn["label"] == "neutral":
                        hi_neu += 1
    return lab, {s: np.array(v) for s, v in dist.items()}, hi, hi_neu


# ---- drawing helpers ------------------------------------------------------ #
def rbox(ax, x, y, w, h, title, body, fc, tc="white", fs_t=11.0, fs_b=8.3, r=0.03):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle=f"round,pad=0.012,rounding_size={r}",
                                linewidth=0, facecolor=fc, mutation_aspect=0.7))
    yy = y + h * (0.66 if body else 0.5)
    ax.text(x + w / 2, yy, title, ha="center", va="center", color=tc,
            fontsize=fs_t, fontweight="bold")
    if body:
        ax.text(x + w / 2, y + h * 0.30, body, ha="center", va="center",
                color=tc, fontsize=fs_b, linespacing=1.22)


def arr(ax, p0, p1, color=TEAL_D, lw=2.0, ms=15, style="-|>"):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=ms,
                                 linewidth=lw, color=color,
                                 connectionstyle="arc3,rad=0"))


def section_label(fig, y, text):
    ax = fig.add_axes([0.03, y, 0.94, 0.02]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.5, text, fontsize=14.5, fontweight="bold", color=TEAL_D, va="center")
    ax.plot([0.118, 1.0], [0.5, 0.5], color="#cfdadc", lw=1.4)


def main():
    data = load()
    lab, dist, hi, hi_neu = run_stats(data)
    n_sf = len(data)
    pct_neu_hi = 100 * hi_neu / hi

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK,
                         "axes.edgecolor": "#c9d4d6"})
    fig = plt.figure(figsize=(12.6, 16.6), dpi=200)
    fig.patch.set_facecolor(PAPER)

    # ===== TITLE ========================================================== #
    ax = fig.add_axes([0, 0.95, 1, 0.05]); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="square,pad=0",
                                facecolor=TEAL_D, linewidth=0, transform=ax.transAxes))
    ax.text(0.035, 0.62, "AI-Assisted Assessment of Stylized Facts — Method & Validation",
            color="white", fontsize=18.5, fontweight="bold", va="center")
    ax.text(0.035, 0.22,
            "Retrieval-augmented, LLM-adjudicated scoring of empirical patterns, with a human-validatable, fully traceable design",
            color="#bfe3e6", fontsize=11.5, va="center")

    # ===== METHOD ========================================================= #
    section_label(fig, 0.915, "METHOD")
    ax = fig.add_axes([0.03, 0.80, 0.94, 0.105]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    stages = [
        ("1 · Stylized fact", f"{n_sf} statements\nas declarative claims", TEAL),
        ("2 · Embed", "all-MiniLM-L6-v2\n384-dim vector", SLATE),
        ("3 · Dual-corpus\nretrieval", "ChromaDB cosine kNN\n60 nearest / corpus", SLATE),
        ("4 · LLM adjudication", "Claude Opus 4.8 labels each\npassage support/contradict/\nneutral + relevance", TEAL),
        ("5 · Scores +\nprovenance", "Evidence 1–3 · Consensus 1–3\nref. counts · verbatim snippets", TEAL_D),
    ]
    n = len(stages); gap = 0.02
    w = (1 - gap * (n - 1)) / n
    for i, (t, b, fc) in enumerate(stages):
        x = i * (w + gap)
        rbox(ax, x, 0.06, w, 0.82, t, b, fc, fs_t=10.6, fs_b=8.1)
        if i < n - 1:
            arr(ax, (x + w + 0.0015, 0.47), (x + w + gap - 0.0015, 0.47))
    ax.text(0.5 * (w) , 0.02, "two corpora kept separate ➜ also re-judged combined",
            fontsize=7.6, color=SLATE, ha="left", va="bottom")

    # ===== VALIDATION ===================================================== #
    section_label(fig, 0.775, "VALIDATION")

    # ---- (1) Human-in-the-loop workflow --------------------------------- #
    ax = fig.add_axes([0.035, 0.55, 0.45, 0.20]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.96, "1 · Human-in-the-loop curation", fontsize=11.5,
            fontweight="bold", color=TEAL_D, va="top")
    rbox(ax, 0.05, 0.62, 0.40, 0.20, "AI proposes", "score + linked evidence", TEAL, fs_t=9.8, fs_b=7.8)
    rbox(ax, 0.55, 0.62, 0.40, 0.20, "Expert reviews", "reads the cited snippets", SLATE, fs_t=9.8, fs_b=7.8)
    rbox(ax, 0.55, 0.30, 0.40, 0.20, "Accept / revise", "label outcome", GREEN, fs_t=9.8, fs_b=7.8)
    rbox(ax, 0.05, 0.30, 0.40, 0.20, "Curated knowledge", "vetted stylized facts", TEAL_D, fs_t=9.8, fs_b=7.8)
    arr(ax, (0.45, 0.72), (0.55, 0.72))
    arr(ax, (0.75, 0.62), (0.75, 0.50))
    arr(ax, (0.55, 0.40), (0.45, 0.40))
    arr(ax, (0.25, 0.62), (0.25, 0.50), color="#9aa9ad", lw=1.6, style="-|>")
    ax.text(0.25, 0.555, "feeds", fontsize=6.8, color=SLATE, ha="center")
    ax.text(0.5, 0.13, "every step recorded → transparent audit trail",
            fontsize=8.2, color=SLATE, ha="center", style="italic")

    # ---- (4) AI vs expert (conceptual) ---------------------------------- #
    ax = fig.add_axes([0.545, 0.55, 0.43, 0.20]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.96, "2 · AI ↔ expert comparison", fontsize=11.5,
            fontweight="bold", color=TEAL_D, va="top")
    rbox(ax, 0.02, 0.66, 0.45, 0.18, "AI score", "full-corpus\nstatistical reading", TEAL, fs_t=9.5, fs_b=7.4)
    rbox(ax, 0.53, 0.66, 0.45, 0.18, "Expert score", "domain opinion\n(niche · recency)", SLATE, fs_t=9.5, fs_b=7.4)
    rbox(ax, 0.30, 0.40, 0.40, 0.13, "compare", "", AMBER, fs_t=9.8)
    arr(ax, (0.24, 0.66), (0.40, 0.53))
    arr(ax, (0.76, 0.66), (0.60, 0.53))
    rbox(ax, 0.02, 0.13, 0.45, 0.17, "Agree", "method corroborated;\nfact well-grounded", GREEN, fs_t=9.5, fs_b=7.4)
    rbox(ax, 0.53, 0.13, 0.45, 0.17, "Diverge", "candidate objective\nknowledge gap", AMBER, fs_t=9.5, fs_b=7.4)
    arr(ax, (0.42, 0.40), (0.27, 0.30), color=GREEN)
    arr(ax, (0.58, 0.40), (0.73, 0.30), color=AMBER)
    ax.text(0.5, 0.045, "empirical agreement reported in main text",
            fontsize=7.8, color=SLATE, ha="center", style="italic")

    # ---- (3) Internal guardrails (real stats) --------------------------- #
    ax = fig.add_axes([0.095, 0.305, 0.40, 0.165])
    corp = ["deb", "reproduction"]
    clab = ["DEB papers", "Repro. abstracts"]
    tot = {c: sum(lab[c].values()) for c in corp}
    sup = [100 * lab[c]["supports"] / tot[c] for c in corp]
    con = [100 * lab[c]["contradicts"] / tot[c] for c in corp]
    neu = [100 * lab[c]["neutral"] / tot[c] for c in corp]
    y = np.arange(len(corp))[::-1]
    ax.barh(y, sup, color=SUP, label="supports", height=0.55)
    ax.barh(y, con, left=sup, color=CON, label="contradicts", height=0.55)
    ax.barh(y, neu, left=[s + c for s, c in zip(sup, con)], color=NEU, label="neutral", height=0.55)
    for i, c in enumerate(corp):
        yy = y[i]
        if sup[i] > 7:
            ax.text(sup[i] / 2, yy, f"{sup[i]:.0f}%", ha="center", va="center", color="white", fontsize=8.5, fontweight="bold")
        ax.text(sup[i] + con[i] + neu[i] / 2, yy, f"{neu[i]:.0f}%", ha="center", va="center", color=INK, fontsize=8.5, fontweight="bold")
    ax.set_yticks(y); ax.set_yticklabels(clab, fontsize=9)
    ax.set_xlim(0, 100); ax.set_xlabel("% of retrieved passages", fontsize=8.6, color=SLATE)
    ax.tick_params(length=0, labelsize=8)
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.32), ncol=3,
              frameon=False, fontsize=8.2, handlelength=1.0, columnspacing=1.2)
    ax.set_title("3 · Internal guardrail: similarity ≠ support", fontsize=11.5,
                 fontweight="bold", color=TEAL_D, loc="left", pad=26)
    # callout box for the headline guardrail number
    ax.annotate(f"{pct_neu_hi:.0f}%",
                xy=(0.5, 0.5), xytext=(0.5, 0.5), xycoords="axes fraction",
                fontsize=0, color="white")
    ax.text(1.005, -0.34,
            f"Even among the nearest passages (cos-dist < 0.45), {pct_neu_hi:.0f}% are judged\n"
            f"NEUTRAL — the adjudication step, not similarity, decides support.",
            transform=ax.transAxes, fontsize=8.0, color=SLATE, ha="right", va="top")

    # ---- (3b) Retrieval quality (distance distributions) ---------------- #
    ax = fig.add_axes([0.60, 0.305, 0.37, 0.165])
    bins = np.linspace(0.2, 0.65, 26)
    for c, col, lb in [("deb", TEAL, "DEB papers"), ("reproduction", AMBER, "Repro. abstracts")]:
        ax.hist(dist[c], bins=bins, density=True, color=col, alpha=0.45, label=lb)
        ax.axvline(np.median(dist[c]), color=col, lw=1.8, ls="--")
    ax.set_title("4 · Retrieval quality", fontsize=11.5, fontweight="bold",
                 color=TEAL_D, loc="left", pad=10)
    ax.set_xlabel("cosine distance to stylized fact  (lower = closer)", fontsize=8.6, color=SLATE)
    ax.set_yticks([])
    ax.tick_params(length=0, labelsize=8)
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    ax.legend(frameon=False, fontsize=8.4, loc="upper right")
    ax.text(0.0, -0.34, "Dashed = median. The focused DEB corpus sits closer to the\n"
            "facts than the broad abstract corpus, as expected.",
            transform=ax.transAxes, fontsize=8.0, color=SLATE, va="top")

    # ===== FOOTER ========================================================= #
    ax = fig.add_axes([0.03, 0.025, 0.94, 0.20]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0, 0.62), 1, 0.36, boxstyle="round,pad=0.004,rounding_size=0.02",
                                facecolor=PANEL, linewidth=0))
    takeaways = [
        ("Traceable", "every score links to its\nsource passages"),
        ("Adjudicated", f"{pct_neu_hi:.0f}% of nearest passages\nfiltered out as neutral"),
        ("Reproducible", "deterministic retrieval;\nfixed parameters"),
        ("Gap-finding", "AI–expert divergence flags\nknowledge gaps to probe"),
    ]
    for i, (h, b) in enumerate(takeaways):
        cx = (i + 0.5) / len(takeaways)
        ax.text(cx, 0.90, h, ha="center", va="center", fontsize=11.5, fontweight="bold", color=TEAL_D)
        ax.text(cx, 0.715, b, ha="center", va="center", fontsize=8.5, color=SLATE, linespacing=1.2)
        if i:
            ax.plot([i / len(takeaways), i / len(takeaways)], [0.66, 0.94], color="#d4dee0", lw=1)
    ax.text(0.0, 0.50,
            "Validation philosophy.  The system is designed to be checked, not trusted blindly: similarity locates candidate text, "
            "but an explicit support/contradict adjudication — auditable down to the verbatim passage — decides evidence. Because the AI "
            "reads entire corpora statistically whereas an expert judges from domain experience, agreement corroborates a fact while "
            "disagreement is treated not as AI error but as a signal worth investigating: a candidate, objective knowledge gap that a "
            "reasoning LLM agent (or a human) can target. The empirical AI-versus-expert comparison is reported in the main text.",
            fontsize=8.6, color=INK, va="top", wrap=True)

    png = OUTDIR / "sf_ai_method_infographic.png"
    pdf = OUTDIR / "sf_ai_method_infographic.pdf"
    fig.savefig(png, facecolor=PAPER, bbox_inches="tight", pad_inches=0.2)
    fig.savefig(pdf, facecolor=PAPER, bbox_inches="tight", pad_inches=0.2)
    print("wrote", png)
    print("wrote", pdf)


if __name__ == "__main__":
    main()
