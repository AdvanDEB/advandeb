#!/usr/bin/env python3
"""Build the workshop wiki bundle (hr/en) from an Obsidian vault.

The vault, in Croatian, is the single source of truth. English lives in a mirror
tree (``<en>/<same rel path>.md``) produced by translation. ``<en>/_manifest.json``
records the sha256 of the Croatian source each translation was made from, so a
note edited after it was translated shows as "outdated" rather than drifting
silently.

The output is a JSON bundle, which the backend serves from settings.WIKI_BUNDLE_PATH
(app/services/wiki_service.py). Optionally the script also writes a
self-contained HTML preview for offline review.

    build_wiki.py --vault SRC/Workshop --en SRC/wiki-en --json wiki-bundle.json
    build_wiki.py ... --html preview.html --links hash \
                  --marked node_modules/marked/marked.min.js \
                  --purify node_modules/dompurify/dist/purify.min.js

The bundle holds internal project documents and transcripts, so it never goes
into this (public) repository. Only this script does.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import yaml

HERE = Path(__file__).resolve().parent

# Folder → section key. This order is the sidebar order.
SECTIONS = [
    ("concepts", "Pojmovi"),
    ("models", "Modeli"),
    ("organisms", "Organizmi"),
    ("project", "Projekt"),
    ("literature", "Izvori"),
    ("journal", "Dnevnik"),
    ("slides", "Claude/Prezentacije"),
    ("drive", "Claude/Drive"),
    ("transcripts", "Claude/Transkripti"),
    ("maps", "MOC"),
    ("questions", "Pitanja"),
    ("meta", "Meta"),
]
SPECIAL = {
    "MOC/Početna.md": "home",
    "Claude/Sažetak radionice.md": "hub",
    "AdvanDEB radionica.md": "livenotes",
}
# Who may read a section (the backend enforces it): summaries of internal
# project documents from Drive. Everything else is "open".
TIERS = {"drive": "internal"}
SKIP_DIRS = {".obsidian", "Meta/Predlošci", "Snimke"}
SKIP_FILES = {"Welcome.md"}

# The wiki is the reader's edition: the results of the workshop, not its raw
# material. Transcripts, the live notes taken during talks and the vault's own
# housekeeping (conventions, templates) stay out. Links to them become plain
# text, recordings are never embedded or named, and a citation of a recording
# becomes a citation of the workshop session it came from (see Reader).
EXCLUDED_SECTIONS = {"transcripts", "livenotes", "meta"}

WIKILINK = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
FENCE = re.compile(r"(^```.*?^```[^\n]*$)", re.M | re.S)
INLINE_CODE = re.compile(r"(`[^`\n]+`)")
H1 = re.compile(r"^# (.+?)\s*$", re.M)
BADGE = re.compile(r"`([RDTEPSHI])`")
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
AUDIO_EXT = {".m4a", ".ogg", ".webm", ".mp3", ".wav", ".opus"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            try:
                fm = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                fm = {}
            return (fm if isinstance(fm, dict) else {}), text[end + 4:].lstrip("\n")
    return {}, text


def take_h1(body: str) -> tuple[str | None, str]:
    """The title, when the first non-empty line is an H1, and the rest."""
    m = H1.search(body)
    if m and not body[: m.start()].strip():
        return m.group(1).strip(), body[m.end():].lstrip("\n")
    return None, body


def jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if isinstance(v, list):
        return [jsonable(x) for x in v]
    return v


def section_for(rel: str) -> str:
    if rel in SPECIAL:
        return SPECIAL[rel]
    for key, folder in SECTIONS:
        if rel.startswith(folder + "/"):
            return key
    return "other"


def walk_vault(vault: Path):
    for p in sorted(vault.rglob("*")):
        rel = p.relative_to(vault).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
            continue
        if p.is_file():
            yield rel, p


def image_data_uri(path: Path, max_px: int = 1600) -> str:
    """A data URI for an embedded image; large photos are downscaled to JPEG."""
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"} and path.stat().st_size > 400_000:
        try:
            from PIL import Image
            with Image.open(path) as im:
                im.thumbnail((max_px, max_px))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=80)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            pass
        try:  # no Pillow here: ImageMagick does the same
            out = subprocess.run(["magick", str(path), "-resize", f"{max_px}x{max_px}>", "-quality", "80", "jpg:-"],
                                 check=True, capture_output=True).stdout
            return "data:image/jpeg;base64," + base64.b64encode(out).decode()
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"warning: {path.name} not downscaled ({exc})", file=sys.stderr)
    mime = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif",
            ".webp": "webp", ".svg": "svg+xml"}[ext]
    return f"data:image/{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def map_outside_code(text: str, fn) -> str:
    """Apply fn to the parts of a markdown text that are not code."""
    out = []
    for i, block in enumerate(FENCE.split(text)):
        if i % 2:
            out.append(block)
            continue
        for j, span in enumerate(INLINE_CODE.split(block)):
            out.append(span if j % 2 else fn(span))
    return "".join(out)


REC = r"\[\[Recording (\d{14})(?:\.\w+)?(?:\|[^\]\n]*)?\]\]"
TIME = r"\d{1,3}:\d{2}(?::\d{2})?"
TIMES = rf"~?{TIME}(?:\s*[–-]\s*~?{TIME})?(?:,\s*~?{TIME}(?:\s*[–-]\s*~?{TIME})?)*"
AUDIO_EMBED = re.compile(r"!\[\[[^\]\n]+\.(?:m4a|ogg|webm|mp3|wav|opus)(?:\|[^\]\n]*)?\]\]")
# "- 10:30–10:38 · [[Recording …]] (8:22) — topic": the journal's recording slot.
JOURNAL_SLOT = re.compile(rf"\s*·\s*{REC}\s*\({TIME}\)")
# "3. [[Recording …]] · 10:26–14:00 (quiet recording)": a source list item.
SOURCE_ITEM = re.compile(rf"^(\s*\d+\.\s+){REC}(?:\s*·?\s*({TIMES}))?(.*)$", re.M)
INLINE_REC = re.compile(rf"{REC}(?:\s*·?\s*({TIMES}))?")
RECORDING_WORDS = re.compile(r"snim(?:k|c|a|i|lj)|transkript|whisper|recorded|recording|transcri|\.m4a\b|\.ogg\b", re.I)
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_clock(s: str) -> int:
    """'12:34' (m:s) or '1:02:03' (h:m:s) → seconds."""
    parts = [int(p) for p in s.strip().lstrip("~").split(":")]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]


class Reader:
    """Turns vault notes into the reader's edition (see EXCLUDED_SECTIONS).

    ``edits`` is a YAML list of content fixes that no rule can make, kept with
    the content rather than in this script:

        - note: Početna            # note id; omit for every note
          lang: hr                 # hr, en or both (default)
          replace: "old text"      # exact substring …
          with: "new text"         # … and its replacement ("" deletes)
        - note: Početna
          drop_section: Pravila vaulta     # a heading and everything under it
        - section: journal
          drop_lines: "izvan teme|off-topic"   # regex, whole lines
        - section: journal
          sub: "\\s*\\(\\d+–\\d+ min\\)"    # regex …
          with: ""                         # … and its replacement

    An edit that no longer matches anything is reported, so a fix that went
    stale with the vault is noticed rather than silently lost.
    """

    def __init__(self, edits: list | None = None):
        self.starts: dict[str, datetime] = {}   # recording stamp → start time
        self.stops: set[str] = set()
        self.edits = edits or []
        self.used = [0] * len(self.edits)
        self.first_day: date | None = None
        self.journal: set[str] = set()

    def add_recording(self, stamp: str, duration):
        stop = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        # YAML 1.1 reads an unquoted 15:16 as base 60, which is already seconds.
        seconds = duration if isinstance(duration, int) else parse_clock(duration) if duration else None
        # Obsidian names a recording when it stops, so it began one duration earlier.
        start = stop - timedelta(seconds=seconds) if seconds else None
        if start:
            self.starts[stamp] = start
        day = (start or stop).date()
        self.first_day = min(self.first_day or day, day)

    def session(self, stamp: str, times: str | None, lang: str) -> str:
        stop = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        start = self.starts.get(stamp)
        day = (start or stop).date()
        k = (day - self.first_day).days + 1 if self.first_day else 1
        label = f"Dan {k}" if lang == "hr" else f"Day {k}"
        iso = day.isoformat()
        link = f"[[{iso}|{label}]]" if iso in self.journal else label
        when = (f"{day.day}. {day.month}. {day.year}." if lang == "hr"
                else f"{day.day} {MONTHS_EN[day.month - 1]} {day.year}")
        clock = ""
        if times and start:
            spans = []
            for span in times.split(","):
                ends = [start + timedelta(seconds=parse_clock(t)) for t in re.split(r"\s*[–-]\s*", span.strip())]
                a, b = ends[0].strftime("%H:%M"), ends[-1].strftime("%H:%M")
                spans.append(a if a == b else f"{a}–{b}")
            clock = ", " + ", ".join(dict.fromkeys(spans))
        word = "Radionica" if lang == "hr" else "Workshop"
        return f"{word}, {link} ({when}){clock}"

    def _applies(self, e: dict, note: dict, lang: str) -> bool:
        if e.get("note") not in (None, note["id"]):
            return False
        if e.get("section") not in (None, note["section"]):
            return False
        return e.get("lang", "both") in ("both", lang)

    def apply_edits(self, md: str, note: dict, lang: str) -> str:
        for i, e in enumerate(self.edits):
            if not self._applies(e, note, lang):
                continue
            if "replace" in e:
                if e["replace"] in md:
                    md = md.replace(e["replace"], e.get("with", ""))
                    self.used[i] += 1
            elif "drop_section" in e:
                m = re.search(rf"^(#+) {re.escape(e['drop_section'])}\s*$", md, re.M)
                if m:
                    level = len(m.group(1))
                    nxt = re.compile(rf"^#{{1,{level}}} ", re.M).search(md, m.end())
                    md = md[: m.start()] + (md[nxt.start():] if nxt else "")
                    self.used[i] += 1
            elif "sub" in e:
                md, n = re.subn(e["sub"], e.get("with", ""), md, flags=re.M)
                self.used[i] += n
            elif "drop_lines" in e:
                pat = re.compile(e["drop_lines"])
                kept = [ln for ln in md.split("\n") if not pat.search(ln)]
                if len(kept) != md.count("\n") + 1:
                    self.used[i] += 1
                md = "\n".join(kept)
        return md

    @staticmethod
    def drop_recording_columns(md: str) -> str:
        """Remove table columns whose header names recordings."""
        lines, out, i = md.split("\n"), [], 0
        cells = lambda ln: re.split(r"(?<!\\)\|", ln.strip().strip("|"))
        while i < len(lines):
            if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
                head = cells(lines[i])
                drop = {j for j, c in enumerate(head) if RECORDING_WORDS.search(c)}
                j = i
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    row = cells(lines[j])
                    out.append("| " + " | ".join(c.strip() for k, c in enumerate(row) if k not in drop) + " |"
                               if drop else lines[j])
                    j += 1
                i = j
                continue
            out.append(lines[i])
            i += 1
        return "\n".join(out)

    def clean(self, md: str, note: dict, lang: str) -> str:
        md = self.apply_edits(md, note, lang)
        md = self.drop_recording_columns(md)
        md = AUDIO_EMBED.sub("", md)
        md = JOURNAL_SLOT.sub("", md)

        def source_item(m: re.Match) -> str:
            tail = m.group(4)
            # "(quiet recording, hard to follow)" describes the recording, not the claim.
            tail = re.sub(r"\s*\([^)]*\)\s*$", lambda t: "" if RECORDING_WORDS.search(t.group(0)) else t.group(0), tail)
            return m.group(1) + self.session(m.group(2), m.group(3), lang) + tail

        md = SOURCE_ITEM.sub(source_item, md)
        md = INLINE_REC.sub(lambda m: self.session(m.group(1), m.group(2), lang), md)
        return re.sub(r"\n{3,}", "\n\n", md)

    def stale_edits(self) -> list:
        return [e for e, n in zip(self.edits, self.used) if n == 0]

    @staticmethod
    def leftovers(md: str) -> list:
        """Lines that still talk about recordings or transcripts."""
        return [ln.strip()[:160] for ln in md.split("\n") if RECORDING_WORDS.search(ln)]


class Vault:
    def __init__(self, vault: Path, en_root: Path | None, links: str = "app",
                 reader: Reader | None = None):
        self.vault = vault
        self.en_root = en_root
        self.links = links
        self.reader = reader or Reader()
        self.notes: dict[str, dict] = {}
        self.by_name: dict[str, str] = {}   # lower-cased note name → id
        self.files: dict[str, Path] = {}    # attachment file name → path
        self.assets: dict[str, str] = {}
        manifest = en_root / "_manifest.json" if en_root else None
        self.manifest = json.loads(manifest.read_text()) if manifest and manifest.exists() else {}

    def href(self, lang: str, nid: str) -> str:
        if self.links == "hash":
            return f"#/{lang}/{quote(nid, safe='')}"
        return f"/2026Workshop/{lang}/n/{quote(nid, safe='')}"

    def load(self):
        for rel, p in walk_vault(self.vault):
            if p.suffix != ".md":
                self.files[p.name] = p
                continue
            if rel in SKIP_FILES:
                continue
            nid = p.stem
            raw = p.read_text(encoding="utf-8")
            fm, body = split_frontmatter(raw)
            title_hr, body_hr = take_h1(body)
            section = section_for(rel)
            if section == "transcripts":
                m = re.match(r"Recording (\d{14})$", nid)
                if m:
                    dur = fm.get("trajanje")
                    self.reader.add_recording(m.group(1), dur)
            if section == "journal":
                self.reader.journal.add(nid)
            note = {
                "id": nid,
                "rel": rel,
                "section": section,
                "tier": TIERS.get(section, "open"),
                "type": fm.get("type") or ("transkript" if section == "transcripts" else "bilješka"),
                "tags": [t for t in (fm.get("tags") or []) if isinstance(t, str)],
                "aliases": [a for a in (fm.get("aliases") or []) if isinstance(a, str)],
                "created": jsonable(fm.get("created")),
                "updated": jsonable(fm.get("updated")),
                "title": {"hr": title_hr or nid, "en": None},
                "_md": {"hr": body_hr, "en": None},
                "en_status": "missing",
                "_sha": sha(raw),
            }
            en_file = self.en_root / rel if self.en_root else None
            if en_file and en_file.exists():
                _, en_body = split_frontmatter(en_file.read_text(encoding="utf-8"))
                title_en, en_body = take_h1(en_body)
                note["title"]["en"] = title_en or note["title"]["hr"]
                note["_md"]["en"] = en_body
                recorded = self.manifest.get(rel)
                note["en_status"] = "ok" if recorded in (None, note["_sha"]) else "outdated"
            elif section == "transcripts":
                note["title"]["en"] = note["title"]["hr"].replace("Transkript", "Transcript")
            self.notes[nid] = note
            self.by_name[nid.lower()] = nid

    def resolve(self, target: str) -> str | None:
        name = target.split("/")[-1].strip()
        if name.lower().endswith(".md"):
            name = name[:-3]
        return self.by_name.get(name.lower())

    def title(self, nid: str, lang: str) -> str:
        t = self.notes[nid]["title"]
        return t.get(lang) or t["hr"]

    def anchor(self, lang: str, nid: str, text: str, cls: str = "wl") -> str:
        # The backend recognises exactly this shape to hide links to notes a
        # reader may not open (wiki_service._LINK); keep the two in step.
        return (f'<a class="{cls}" href="{self.href(lang, nid)}" '
                f'data-id="{html.escape(nid)}">{html.escape(text)}</a>')

    def render_links(self, md: str, lang: str, out: set[str], broken: set[str]) -> str:
        transcript = {"hr": "transkript", "en": "transcript"}[lang]
        no_audio = {"hr": "audio nije uključen", "en": "audio not included"}[lang]

        def repl(m: re.Match) -> str:
            embed, inner = m.group(1) == "!", m.group(2).replace("\\|", "|")
            target, _, alias = inner.partition("|")
            target = target.partition("#")[0].strip()
            name = target.split("/")[-1]
            ext = os.path.splitext(target)[1].lower()
            if ext in IMG_EXT:
                f = self.files.get(name)
                if not f:
                    broken.add(target)
                    return f'<span class="wl broken">{html.escape(target)}</span>'
                self.assets.setdefault(f.name, image_data_uri(f))
                label = html.escape(alias.strip() or os.path.splitext(f.name)[0])
                if not embed:
                    return (f'<a class="wl asset-link" href="#" '
                            f'data-asset="{html.escape(f.name)}">🖼 {label}</a>')
                return (f'<figure class="embed"><img data-asset="{html.escape(f.name)}" alt="{label}">'
                        f'<figcaption>{label}</figcaption></figure>')
            if ext in AUDIO_EXT:
                stem = os.path.splitext(name)[0]
                tid = self.resolve(stem)
                link = ""
                if tid:
                    out.add(tid)
                    link = " · " + self.anchor(lang, tid, transcript, "wl wl-rec")
                return (f'<span class="audio-embed">🎙 {html.escape(stem)} '
                        f'<span class="muted">({no_audio})</span>{link}</span>')
            nid = self.resolve(target)
            if not nid:
                broken.add(target)
                text = alias.strip() or target
                return f'<span class="wl broken" title="{html.escape(target)}">{html.escape(text)}</span>'
            text = alias.strip() or self.title(nid, lang)
            if self.notes[nid]["section"] in EXCLUDED_SECTIONS:
                return html.escape(text)
            out.add(nid)
            return self.anchor(lang, nid, text)

        return map_outside_code(md, lambda s: WIKILINK.sub(repl, s))

    def build(self) -> dict:
        broken_all: dict[str, list[str]] = {}
        self.leftovers: dict[str, list[str]] = {}
        for nid, n in self.notes.items():
            if n["section"] in EXCLUDED_SECTIONS:
                continue
            out: set[str] = set()
            broken: set[str] = set()
            n["md"] = {}
            for lang in ("hr", "en"):
                src = n["_md"][lang]
                if src is None:
                    n["md"][lang] = None
                    continue
                clean = self.reader.clean(src, n, lang)
                left = self.reader.leftovers(clean)
                if left:
                    self.leftovers[f"{nid} [{lang}]"] = left
                n["md"][lang] = self.render_links(clean, lang, out, broken)
            out.discard(nid)
            n["out"] = sorted(out)
            n["badges"] = {}
            for b in BADGE.findall(n["_md"]["hr"]):
                n["badges"][b] = n["badges"].get(b, 0) + 1
            if broken:
                broken_all[nid] = sorted(broken)
        kept = {nid: n for nid, n in self.notes.items() if n["section"] not in EXCLUDED_SECTIONS}
        back: dict[str, set[str]] = {nid: set() for nid in kept}
        for nid, n in kept.items():
            for t in n["out"]:
                back[t].add(nid)
        notes = {}
        for nid, n in kept.items():
            n["in"] = sorted(back[nid])
            notes[nid] = {k: v for k, v in n.items() if not k.startswith("_") and k != "rel"}
        return {
            "version": 1,
            "built": datetime.now().isoformat(timespec="minutes"),
            "sections": [k for k, _ in SECTIONS if k not in EXCLUDED_SECTIONS],
            "notes": notes,
            "assets": self.assets,
            "broken": broken_all,
        }


def write_manifest(v: Vault):
    """Record the Croatian source hash for every existing English translation."""
    manifest = {n["rel"]: n["_sha"] for n in v.notes.values()
                if (v.en_root / n["rel"]).exists()}
    (v.en_root / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"manifest: {len(manifest)} translations recorded")


def write_atomically(path: Path, text: str):
    """The backend reloads on mtime; never let it read a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", type=Path, required=True)
    ap.add_argument("--en", type=Path, help="English mirror tree")
    ap.add_argument("--json", type=Path, help="write the bundle here")
    ap.add_argument("--html", type=Path, help="write a self-contained preview here")
    ap.add_argument("--links", choices=["app", "hash"], default=None,
                    help="link style: app (/2026Workshop/...) or hash (#/..., for the preview); "
                         "default: hash when only --html is given")
    ap.add_argument("--template", type=Path, default=HERE / "preview_template.html")
    ap.add_argument("--marked", type=Path)
    ap.add_argument("--purify", type=Path)
    ap.add_argument("--edits", type=Path, help="reader edits (YAML), see Reader")
    ap.add_argument("--strict", action="store_true",
                    help="fail on broken links, stale edits or leftover mentions of recordings")
    ap.add_argument("--write-manifest", action="store_true",
                    help="record the current Croatian hashes for all existing translations")
    a = ap.parse_args()
    links = a.links or ("hash" if a.html and not a.json else "app")
    vault, en = a.vault.expanduser(), a.en.expanduser() if a.en else None

    edits = yaml.safe_load(a.edits.read_text(encoding="utf-8")) if a.edits else []

    def fresh() -> Vault:
        v = Vault(vault, en, links, Reader(edits))
        v.load()
        return v

    v = fresh()
    if a.write_manifest and en:
        write_manifest(v)
        v = fresh()
    bundle = v.build()

    notes = bundle["notes"].values()
    status = {s: sum(1 for n in notes if n["en_status"] == s) for s in ("ok", "outdated", "missing")}
    tiers = {t: sum(1 for n in notes if n["tier"] == t) for t in ("open", "internal", "raw")}
    print(f"notes: {len(bundle['notes'])} · tiers: {tiers} · en: {status} · "
          f"assets: {len(bundle['assets'])} · notes with broken links: {len(bundle['broken'])}")
    for nid, b in bundle["broken"].items():
        print(f"  broken in {nid}: {b}", file=sys.stderr)
    for n in notes:
        if n["en_status"] == "outdated":
            print(f"  en outdated: {n['rel']}", file=sys.stderr)
    for key, lines in v.leftovers.items():
        for ln in lines:
            print(f"  mentions recordings, {key}: {ln}", file=sys.stderr)
    stale = v.reader.stale_edits()
    for e in stale:
        print(f"  edit matched nothing: {e}", file=sys.stderr)
    if a.strict and (bundle["broken"] or v.leftovers or stale):
        sys.exit("refusing to publish: fix the problems listed above")

    if a.json:
        write_atomically(a.json, json.dumps(bundle, ensure_ascii=False))
        print(f"wrote {a.json} ({a.json.stat().st_size / 1e6:.1f} MB)")
    if a.html:
        if not (a.marked and a.purify):
            ap.error("--html needs --marked and --purify (from app/frontend/node_modules)")
        data = json.dumps(bundle, ensure_ascii=False).replace("</", "<\\/")
        page = (a.template.read_text(encoding="utf-8")
                .replace("__DATA__", data)
                .replace("/*__MARKED__*/", a.marked.read_text())
                .replace("/*__PURIFY__*/", a.purify.read_text()))
        write_atomically(a.html, page)
        print(f"wrote {a.html} ({a.html.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
