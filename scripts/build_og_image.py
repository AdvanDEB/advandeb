"""
Generate the 1200x630 social-share card referenced by app/frontend/index.html
as og:image / twitter:image.

Regenerate after any wordmark or tagline change:

    conda run -n advandeb python scripts/build_og_image.py

Deterministic: the node/edge motif is driven by a fixed-seed RNG so re-running
produces a byte-identical file and doesn't churn the repo.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "frontend" / "public" / "og-image.png"

W, H = 1200, 630
SEED = 20260825

# Slate palette, matching the app shell (AppLayout.vue) with its blue accent.
BG_TOP = (15, 23, 42)        # slate-900
BG_BOTTOM = (30, 41, 59)     # slate-800
ACCENT = (59, 130, 246)      # blue-500
EDGE = (71, 85, 105)         # slate-600
TEXT = (241, 245, 249)       # slate-100
MUTED = (148, 163, 184)      # slate-400

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _gradient() -> Image.Image:
    """Vertical slate gradient as the card background."""
    base = Image.new("RGB", (1, H))
    px = base.load()
    for y in range(H):
        t = y / (H - 1)
        px[0, y] = tuple(
            round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        )
    return base.resize((W, H))


def _graph_motif(img: Image.Image) -> None:
    """A knowledge-graph constellation occupying the right third of the card.

    Nodes are laid out on jittered concentric rings so the result reads as a
    graph rather than scattered dots, and every node connects to at least one
    neighbour — an isolated dot looks like a rendering artefact.
    """
    rng = random.Random(SEED)
    cx, cy = 930, 315

    nodes: list[tuple[float, float, int]] = [(cx, cy, 13)]
    for ring, (count, radius, size) in enumerate(
        [(6, 105, 9), (9, 190, 7), (11, 275, 5)], start=1
    ):
        offset = rng.uniform(0, math.tau)
        for i in range(count):
            angle = offset + math.tau * i / count + rng.uniform(-0.12, 0.12)
            r = radius + rng.uniform(-22, 22)
            nodes.append((cx + r * math.cos(angle), cy + r * math.sin(angle) * 0.86, size))

    # Draw onto an oversampled layer so the thin edges and small circles stay
    # smooth after downscaling.
    scale = 2
    layer = Image.new("RGBA", (W * scale, H * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    for i, (x, y, _) in enumerate(nodes):
        # Connect each node to its two nearest predecessors — guarantees
        # connectivity while keeping the edge count visually sparse.
        neighbours = sorted(
            range(i), key=lambda j: (nodes[j][0] - x) ** 2 + (nodes[j][1] - y) ** 2
        )[:2]
        for j in neighbours:
            nx, ny, _ = nodes[j]
            draw.line(
                [(x * scale, y * scale), (nx * scale, ny * scale)],
                fill=EDGE + (150,),
                width=2 * scale,
            )

    for i, (x, y, size) in enumerate(nodes):
        # Inner rings sit closer to the accent colour, outer ones fade back.
        t = min(1.0, math.hypot(x - cx, y - cy) / 300)
        color = tuple(round(ACCENT[k] + (EDGE[k] - ACCENT[k]) * t) for k in range(3))
        r = size * scale
        draw.ellipse(
            [(x * scale - r, y * scale - r), (x * scale + r, y * scale + r)],
            fill=color + (255,),
        )

    layer = layer.resize((W, H), Image.LANCZOS)

    # Soft glow behind the constellation so it sits in the background and never
    # competes with the wordmark.
    glow = layer.filter(ImageFilter.GaussianBlur(18))
    img.paste(Image.alpha_composite(glow, layer), (0, 0), Image.alpha_composite(glow, layer))


def main() -> None:
    img = _gradient().convert("RGBA")
    _graph_motif(img)

    draw = ImageDraw.Draw(img)

    # Accent rule above the wordmark.
    draw.rectangle([(90, 214), (90 + 88, 214 + 6)], fill=ACCENT)

    draw.text((90, 252), "AdvanDEB", font=_font("DejaVuSans-Bold.ttf", 88), fill=TEXT)
    draw.text(
        (90, 366),
        "A curated knowledge graph and AI assistant",
        font=_font("DejaVuSans.ttf", 31),
        fill=MUTED,
    )
    draw.text(
        (90, 410),
        "for Dynamic Energy Budget biology",
        font=_font("DejaVuSans.ttf", 31),
        fill=MUTED,
    )
    draw.text(
        (90, 492), "advandeb.com", font=_font("DejaVuSans-Bold.ttf", 26), fill=ACCENT
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
