#!/usr/bin/env python
"""
build_sf_infographic.py — render a one-page visual abstract of the AI-based
stylized-fact (SF) scientific-support assessment, from the cached raw results.

Reads analysis/sf_support/raw/*.json and writes:
    analysis/sf_support/sf_ai_assessment_infographic.png
    analysis/sf_support/sf_ai_assessment_infographic.pdf
"""
from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "analysis" / "sf_support"

# ---- palette -------------------------------------------------------------- #
INK = "#1d2733"
TEAL = "#0f6e78"
TEAL_D = "#0a4c54"
SLATE = "#475569"
PAPER = "#ffffff"
PANEL = "#f4f7f8"
SCORE_CMAP = LinearSegmentedColormap.from_list(
    "score", ["#f7e8d0", "#f0b27a", "#5aa9b5", "#0f6e78"]
)
DIV_CMAP = LinearSegmentedColormap.from_list(
    "div", ["#c0612a", "#e8e2d6", "#0f6e78"]
)


def load():
    data = [json.load(open(f)) for f in sorted(glob.glob(str(OUTDIR / "raw" / "*.json")))]
    # category order as printed in the combined summary
    order: list[str] = []
    for line in open(OUTDIR / "summary_combined.md"):
        m = re.match(r"\| `[^`]+` \| ([^|]+?) \|", line)
        if m and m.group(1).strip() not in order:
            order.append(m.group(1).strip())
    return data, order


def aggregate(data, order):
    scopes = ("deb", "reproduction", "combined")
    ev = {s: {} for s in scopes}
    cons = {s: {} for s in scopes}
    refs = {s: {} for s in scopes}
    ncat = {}
    buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    rbuck = defaultdict(int)
    for d in data:
        c = d["category"]
        ncat[c] = ncat.get(c, 0) + 1
        for s in scopes:
            sc = d["scopes"][s]["scores"]
            buckets[c][s]["ev"].append(sc["evidence_strength"])
            buckets[c][s]["cons"].append(sc["consensus_direction"])
            rbuck[(c, s)] += d["scopes"][s]["n_references"]
    for c in order:
        for s in scopes:
            ev[s][c] = float(np.mean(buckets[c][s]["ev"]))
            cons[s][c] = float(np.mean(buckets[c][s]["cons"]))
            refs[s][c] = rbuck[(c, s)]
    return ev, cons, refs, ncat


# --------------------------------------------------------------------------- #
def rbox(ax, x, y, w, h, title, body, fc, tc="white", fs_t=12.5, fs_b=9.2):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.03",
            linewidth=0, facecolor=fc, mutation_aspect=0.6,
        )
    )
    ax.text(x + w / 2, y + h * 0.70, title, ha="center", va="center",
            color=tc, fontsize=fs_t, fontweight="bold")
    ax.text(x + w / 2, y + h * 0.33, body, ha="center", va="center",
            color=tc, fontsize=fs_b, linespacing=1.25)


def arrow(ax, x0, x1, y):
    ax.add_patch(FancyArrowPatch(
        (x0, y), (x1, y), arrowstyle="-|>", mutation_scale=16,
        linewidth=2.0, color=TEAL_D))


def main():
    data, order = load()
    ev, cons, refs, ncat = aggregate(data, order)
    n_sf = len(data)
    scopes = ["deb", "reproduction", "combined"]
    scope_lab = ["DEB\npapers", "Repro.\nabstracts", "Combined"]

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK,
                         "axes.edgecolor": "#c9d4d6"})
    fig = plt.figure(figsize=(12.6, 16.4), dpi=200)
    fig.patch.set_facecolor(PAPER)

    # ====================================================================== #
    # 1. TITLE BAND
    # ====================================================================== #
    ax = fig.add_axes([0, 0.93, 1, 0.07]); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.0, 0.0), 1.0, 1.0, boxstyle="square,pad=0",
                                facecolor=TEAL_D, linewidth=0,
                                transform=ax.transAxes))
    ax.text(0.035, 0.62, "AI-Assisted Scientific-Support Assessment of Stylized Facts",
            color="white", fontsize=20, fontweight="bold", va="center")
    ax.text(0.035, 0.24,
            "Retrieval-augmented, LLM-adjudicated evidence scoring across two literature corpora",
            color="#bfe3e6", fontsize=12.5, va="center")
    ax.text(0.965, 0.5, "VISUAL\nABSTRACT", color="#7fc3cb", fontsize=12,
            fontweight="bold", ha="right", va="center", linespacing=1.1)

    # ====================================================================== #
    # 2. PIPELINE
    # ====================================================================== #
    ax = fig.add_axes([0.03, 0.785, 0.94, 0.12]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.95, "How each stylized fact is scored", fontsize=13.5,
            fontweight="bold", color=TEAL_D, va="top")
    stages = [
        ("1 · Stylized fact", f"{n_sf} statements\n10 categories · 3 domains", TEAL),
        ("2 · Embed", "all-MiniLM-L6-v2\n384-dim vector", SLATE),
        ("3 · Dual-corpus\nretrieval", "ChromaDB cosine kNN\nDEB lit. | abstracts", SLATE),
        ("4 · LLM adjudication", "Claude Opus 4.8\nsupport / contradict /\nneutral per passage", TEAL),
        ("5 · Scores +\nprovenance", "Evidence 1–3 · Consensus 1–3\nref. counts + snippets", TEAL_D),
    ]
    n = len(stages); gap = 0.022
    w = (1 - gap * (n - 1)) / n
    for i, (t, b, fc) in enumerate(stages):
        x = i * (w + gap)
        rbox(ax, x, 0.04, w, 0.72, t, b, fc, fs_t=11.0, fs_b=8.4)
        if i < n - 1:
            arrow(ax, x + w + 0.001, x + w + gap - 0.001, 0.40)

    # ====================================================================== #
    # 3. KEY NUMBERS
    # ====================================================================== #
    ax = fig.add_axes([0.03, 0.70, 0.94, 0.075]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.005,rounding_size=0.02",
                                facecolor=PANEL, linewidth=0))
    stats = [
        (f"{n_sf}", "stylized facts"),
        ("1,643", "DEB-domain papers"),
        ("599,540", "reproduction abstracts"),
        ("2.81 M", "indexed text passages"),
        ("3 × 2", "scopes × score types"),
        ("372", "provenance documents"),
    ]
    m = len(stats)
    for i, (num, lab) in enumerate(stats):
        cx = (i + 0.5) / m
        ax.text(cx, 0.66, num, ha="center", va="center", fontsize=19,
                fontweight="bold", color=TEAL_D)
        ax.text(cx, 0.24, lab, ha="center", va="center", fontsize=9.6, color=SLATE)
        if i:
            ax.plot([i / m, i / m], [0.18, 0.82], color="#d4dee0", lw=1)

    # ====================================================================== #
    # 4. HEATMAPS  (evidence strength | consensus direction)
    # ====================================================================== #
    cats = order
    ev_mat = np.array([[ev[s][c] for s in scopes] for c in cats])
    cons_mat = np.array([[cons[s][c] for s in scopes] for c in cats])
    # domain separators after 'General Physiology' (idx5) and 'Hypoxia / DO' (idx6)
    seps = [6, 7]

    def heat(axpos, mat, title, sub):
        ax = fig.add_axes(axpos)
        im = ax.imshow(mat, cmap=SCORE_CMAP, vmin=1, vmax=3, aspect="auto")
        ax.set_xticks(range(3)); ax.set_xticklabels(scope_lab, fontsize=9.5)
        ax.set_yticks(range(len(cats)))
        ax.set_yticklabels([f"{c}  (n={ncat[c]})" for c in cats], fontsize=9.5)
        ax.tick_params(length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        for i in range(len(cats)):
            for j in range(3):
                v = mat[i, j]
                ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                        fontsize=9.6, fontweight="bold",
                        color="white" if v >= 2.15 else INK)
        for s in seps:
            ax.axhline(s - 0.5, color="white", lw=3)
        ax.text(0.5, 1.135, title, transform=ax.transAxes, ha="center",
                fontsize=12.5, fontweight="bold", color=TEAL_D)
        ax.text(0.5, 1.045, sub, transform=ax.transAxes, ha="center",
                fontsize=9, color=SLATE)
        return im

    im = heat([0.085, 0.385, 0.36, 0.235], ev_mat,
              "Evidence strength", "mean per category  (1 weak – 3 strong)")
    heat([0.585, 0.385, 0.36, 0.235], cons_mat,
         "Consensus direction", "1 contradicted/mixed · 2 neutral · 3 corroborated")
    cax = fig.add_axes([0.085, 0.357, 0.86, 0.011])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.set_ticks([1, 1.5, 2, 2.5, 3]); cb.ax.tick_params(labelsize=8.5, length=0)
    cb.outline.set_visible(False)
    cb.set_label("score (1 – 3)", fontsize=9, color=SLATE)

    # ====================================================================== #
    # 5. CROSS-CORPUS DIVERGENCE
    # ====================================================================== #
    ax = fig.add_axes([0.155, 0.135, 0.79, 0.155])
    gap = np.array([ev["deb"][c] - ev["reproduction"][c] for c in cats])
    yy = np.arange(len(cats))[::-1]
    norm = TwoSlopeNorm(vmin=-1.6, vcenter=0, vmax=1.6)
    colors = DIV_CMAP(norm(gap))
    ax.barh(yy, gap, color=colors, edgecolor="white", height=0.74)
    ax.axvline(0, color=SLATE, lw=1)
    ax.set_yticks(yy); ax.set_yticklabels(cats, fontsize=9.3)
    ax.set_xlabel("mean evidence-strength gap   (DEB papers − reproduction abstracts)",
                  fontsize=9.6, color=SLATE)
    ax.tick_params(length=0)
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    for y, g in zip(yy, gap):
        ax.text(g + (0.03 if g >= 0 else -0.03), y, f"{g:+.1f}",
                va="center", ha="left" if g >= 0 else "right",
                fontsize=8.6, color=INK)
    ax.set_xlim(-1.0, 1.8)
    ax.set_title("Where the two corpora disagree most",
                 fontsize=12.5, fontweight="bold", color=TEAL_D, loc="left", pad=8)
    ax.text(0.0, 1.06, "positive → better evidenced in the focused DEB literature",
            transform=ax.transAxes, fontsize=9, color=SLATE)

    # ====================================================================== #
    # 6. FOOTER
    # ====================================================================== #
    ax = fig.add_axes([0.03, 0.005, 0.94, 0.085]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.004,rounding_size=0.02",
                                facecolor=PANEL, linewidth=0))
    ax.text(0.02, 0.80, "Method in one line", fontsize=10.5, fontweight="bold", color=TEAL_D)
    ax.text(0.02, 0.50,
            "Each stylized fact is embedded and matched against the 60 nearest passages in each corpus; an LLM labels every passage "
            "as supporting / contradicting / neutral, and the verdicts are aggregated into two 1–3 scores plus a count of distinct "
            "primary references. Every score resolves to its source documents and verbatim snippets.",
            fontsize=8.9, color=INK, va="top", wrap=True)
    ax.text(0.02, 0.12,
            "Caveats: semantic retrieval ≠ proof of support (mitigated by explicit adjudication); reference counts are bounded by "
            "retrieval depth, not an exhaustive census; LLM judgments warrant expert spot-checking.",
            fontsize=8.2, color=SLATE, va="top", style="italic")

    png = OUTDIR / "sf_ai_assessment_infographic.png"
    pdf = OUTDIR / "sf_ai_assessment_infographic.pdf"
    fig.savefig(png, facecolor=PAPER, bbox_inches="tight", pad_inches=0.2)
    fig.savefig(pdf, facecolor=PAPER, bbox_inches="tight", pad_inches=0.2)
    print("wrote", png)
    print("wrote", pdf)


if __name__ == "__main__":
    main()
