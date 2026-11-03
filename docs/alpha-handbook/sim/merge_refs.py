"""Merge sections/refs_*.tex into sections/11_literatura.tex (dedupe by DOI, sort by first author).

Usage: python merge_refs.py HANDBOOK_DIR
"""
import re
import sys
import unicodedata
from pathlib import Path

root = Path(sys.argv[1])
lit = root / "sections" / "11_literatura.tex"
text = lit.read_text()
start = text.index(r"\begin{enumerate}")
start = text.index("\n", start) + 1
end = text.index(r"\end{enumerate}")
head, body, tail = text[:start], text[start:end], text[end:]


def items(s):
    return [m.strip() for m in re.split(r"(?m)^\s*(?=\\item\b)", s) if m.strip().startswith(r"\item")]


def doi(item):
    m = re.search(r"doi\.org/([^}\s]+)", item) or re.search(r"doi:(10\.[^\s}]+)", item)
    return m.group(1).lower().rstrip(".") if m else None


def key(item):
    t = item[len(r"\item"):].strip()
    t = re.sub(r"\\[a-zA-Z]+\{?", "", t)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return t


merged, seen, added = [], set(), []
for it in items(body):
    d = doi(it) or key(it)[:60]
    if d not in seen:
        seen.add(d)
        merged.append(it)
for f in sorted((root / "sections").glob("refs_*.tex")):
    for it in items(f.read_text()):
        d = doi(it) or key(it)[:60]
        if d not in seen:
            seen.add(d)
            merged.append(it)
            added.append((f.name, it[:90]))
merged.sort(key=key)
lit.write_text(head + "\n".join(merged) + "\n" + tail)
print(f"{len(merged)} references total, {len(added)} added:")
for f, it in added:
    print(f"  [{f}] {it}")
