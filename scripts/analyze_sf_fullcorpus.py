#!/usr/bin/env python
"""
analyze_sf_fullcorpus.py — CORRECTED stylized-fact (SF) support assessment that
retrieves from the FULL literature corpora (not the small ChromaDB subset).

Fixes the defect in analyze_sf_support.py, whose reproduction evidence came from
~0.6 M ChromaDB chunks instead of the full corpus. Here both corpora are the real
nomic-embed-text (768-d) stores used by the main pipeline:

    reproduction  ->  deb_abstracts_reproduction.abstract_chunks   (~4.4 M, 20 GB FastVectorIndex cache)
    deb literature->  deb_literature_review.document_chunks         (152 k)

Each of the 62 paper SFs is embedded with nomic-embed-text (via Ollama), the
nearest passages are retrieved from each full corpus, and EACH passage is judged
by TWO judges as a cross-check:

    gpt-oss (Ollama, the paper's judge family)   and   Claude Opus 4.8 (API)

Outputs per SF (resumable cache):  analysis/sf_support_fullcorpus/raw/<sf_id>.json
with judges × {deb, reproduction, combined} → evidence_strength(1-3),
consensus_direction(1-3), reference counts, labelled snippets.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
AUX = Path.home() / "dev" / "advandeb_auxiliary" / "stylized_DEB"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "app" / "backend"))
sys.path.insert(0, str(AUX))

# reuse SF list + judge prompt + aggregation helpers from the original script
from analyze_sf_support import (  # noqa: E402
    SFS, JUDGE_SYSTEM, JUDGE_TEMPLATE, _parse_json,
    Snippet, references_from, snippet_to_dict,
)
from literature_review.phase3_review.fast_vector_index import FastVectorIndex  # noqa: E402

OUTDIR = REPO_ROOT / "analysis" / "sf_support_fullcorpus"
OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
REPRO_CACHE = AUX / "data" / "repro_full_index_cache.pkl"      # rebuilt from full Mongo (100% coverage)
LIT_CACHE = AUX / "data" / "lit_vector_index_cache.pkl"        # built on first run

TOP_K = 100              # nearest passages pulled from each corpus
SIM_THRESHOLD = 0.50     # keep passages with cosine similarity >= this
MAX_SNIPPETS = 18        # candidate passages sent to each judge per corpus
COMBINED_PER_CORPUS = 12
SNIPPET_CHARS = 700


# --------------------------------------------------------------------------- #
# Embedding (nomic-embed-text via Ollama)                                      #
# --------------------------------------------------------------------------- #
def nomic_embed(text: str) -> list[float]:
    for attempt in range(4):
        try:
            r = requests.post(f"{OLLAMA}/api/embeddings",
                              json={"model": "nomic-embed-text", "prompt": text},
                              timeout=120)
            return r.json()["embedding"]
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


# --------------------------------------------------------------------------- #
# Indices                                                                      #
# --------------------------------------------------------------------------- #
def load_repro_index() -> FastVectorIndex:
    idx = FastVectorIndex("mongodb://localhost:27017",
                          "deb_abstracts_reproduction", "abstract_chunks")
    print("[index] loading reproduction index (20 GB cache) …", flush=True)
    t = time.time()
    idx.load_from_mongodb(cache_path=REPRO_CACHE)
    print(f"[index] reproduction ready: {idx.get_stats()['num_vectors']:,} vectors ({time.time()-t:.0f}s)")
    return idx


def load_lit_index() -> FastVectorIndex:
    # NOTE: FastVectorIndex.load_from_mongodb has a fallback that loads the
    # reproduction embeddings_export shards regardless of the requested DB, so
    # we build the DEB-literature index directly and normalise it ourselves.
    idx = FastVectorIndex("mongodb://localhost:27017",
                          "deb_literature_review", "document_chunks")
    print("[index] loading DEB-literature index (152 k) …", flush=True)
    t = time.time()
    if LIT_CACHE.exists():
        with open(LIT_CACHE, "rb") as f:
            data = pickle.load(f)
        idx.embeddings = data["embeddings"]
        idx.metadata = data["metadata"]
        idx.is_loaded = True
    else:
        from pymongo import MongoClient
        col = MongoClient("mongodb://localhost:27017")["deb_literature_review"]["document_chunks"]
        embs, meta = [], []
        cur = col.find({"embedding": {"$exists": True}},
                       {"embedding": 1, "text": 1, "doc_id": 1, "filename": 1})
        for d in cur:
            embs.append(d["embedding"])
            fn = d.get("filename", "")
            meta.append({"doc_id": d.get("doc_id"), "text": d.get("text", ""),
                         "title": fn, "filename": fn})
        arr = np.asarray(embs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        idx.embeddings = arr / norms
        idx.metadata = meta
        idx.is_loaded = True
        with open(LIT_CACHE, "wb") as f:
            pickle.dump({"embeddings": idx.embeddings, "metadata": idx.metadata},
                        f, protocol=pickle.HIGHEST_PROTOCOL)
    n = idx.embeddings.shape[0]
    if n > 500_000:
        raise SystemExit(f"[index] literature index has {n:,} vectors — expected ~152k. Aborting (stale cache?).")
    print(f"[index] literature ready: {n:,} vectors ({time.time()-t:.0f}s)")
    return idx


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def retrieve(idx: FastVectorIndex, qvec, corpus: str) -> list[Snippet]:
    raw = idx.search(qvec, top_k=TOP_K)
    seen, out = set(), []
    for r in raw:
        sim = float(r.get("similarity_score", 0.0))
        text = _norm(r.get("text", ""))
        if len(text) < 40:
            continue
        key = text[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        # keep above threshold; if nothing qualifies we still keep the very top few
        out.append(Snippet(
            document_id=str(r.get("doc_id", "")),
            title=str(r.get("title") or r.get("filename") or "(untitled)"),
            doi=str(r.get("doi") or ""),
            year=str(r.get("publication_year") or ""),
            distance=round(1.0 - sim, 4),   # store as distance for compatibility
            text=text[:SNIPPET_CHARS],
            corpus=corpus,
        ))
    above = [s for s in out if (1.0 - s.distance) >= SIM_THRESHOLD]
    chosen = (above or out)[:MAX_SNIPPETS]
    return chosen


# --------------------------------------------------------------------------- #
# Judges                                                                       #
# --------------------------------------------------------------------------- #
def _judge_prompt(category, statement, corpus_label, snippets):
    numbered = "\n".join(f"[{i+1}] (source: {s.title}) {s.text}"
                         for i, s in enumerate(snippets))
    return JUDGE_TEMPLATE.format(category=category, statement=statement,
                                 n=len(snippets), corpus_label=corpus_label,
                                 snippets=numbered)


def _apply(data, snippets):
    for item in data.get("snippets", []):
        i = int(item.get("i", 0)) - 1
        if 0 <= i < len(snippets):
            snippets[i].label = str(item.get("label", "neutral"))
            snippets[i].relevance = float(item.get("relevance", 0.0))
    return {
        "evidence_strength": int(data.get("evidence_strength", 1)),
        "consensus_direction": int(data.get("consensus_direction", 2)),
        "rationale": str(data.get("rationale", "")).strip(),
    }


def judge_claude(client, model, category, statement, corpus_label, snippets):
    prompt = _judge_prompt(category, statement, corpus_label, snippets)
    last = None
    for attempt in range(4):
        try:
            resp = client.messages.create(model=model, max_tokens=2000,
                                          system=JUDGE_SYSTEM,
                                          messages=[{"role": "user", "content": prompt}])
            return _apply(_parse_json(resp.content[0].text), snippets)
        except Exception as exc:  # noqa: BLE001
            last = exc; time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"claude judge failed: {last}")


def judge_gptoss(model, category, statement, corpus_label, snippets):
    prompt = _judge_prompt(category, statement, corpus_label, snippets)
    last = None
    for attempt in range(4):
        try:
            r = requests.post(f"{OLLAMA}/api/chat", json={
                "model": model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": JUDGE_SYSTEM},
                             {"role": "user", "content": prompt}],
                "options": {"temperature": 0.1, "num_ctx": 32000},
            }, timeout=1200).json()
            if "message" not in r:
                raise RuntimeError(str(r.get("error"))[:200])
            return _apply(_parse_json(r["message"]["content"]), snippets)
        except Exception as exc:  # noqa: BLE001
            last = exc; time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"gpt-oss judge failed: {last}")


# --------------------------------------------------------------------------- #
# Per-SF analysis                                                              #
# --------------------------------------------------------------------------- #
CORP_LABEL = {"deb": "DEB literature (full corpus)",
              "reproduction": "Reproduction abstracts (full 4.4M corpus)",
              "combined": "Combined (both full corpora)"}


def fresh(snips):
    return [Snippet(s.document_id, s.title, s.doi, s.year, s.distance, s.text, s.corpus)
            for s in snips]


def run_judge(kind, claude, gptoss_model, category, statement, snips, label):
    if kind == "claude":
        return judge_claude(claude, "claude-opus-4-8", category, statement, label, snips)
    return judge_gptoss(gptoss_model, category, statement, label, snips)


def analyze(sf_id, category, statement, repro_idx, lit_idx, claude, gptoss_model):
    qvec = nomic_embed(statement)
    base = {"deb": retrieve(lit_idx, qvec, "deb"),
            "reproduction": retrieve(repro_idx, qvec, "reproduction")}
    out = {"sf_id": sf_id, "category": category, "statement": statement,
           "retrieval": "fullcorpus_nomic", "judges": {}}
    for kind, jname in (("gptoss", "gptoss"), ("claude", "claude")):
        scopes = {}
        per = {}
        for corpus in ("deb", "reproduction"):
            snips = fresh(base[corpus])
            scores = run_judge(kind, claude, gptoss_model, category, statement,
                               snips, CORP_LABEL[corpus])
            per[corpus] = snips
            refs = references_from(snips)
            scopes[corpus] = {"scores": scores, "n_references": len(refs),
                              "references": refs,
                              "snippets": [snippet_to_dict(s) for s in snips]}
        # combined: fresh judgement over merged nearest snippets
        merged = fresh(sorted(per["deb"], key=lambda s: s.distance)[:COMBINED_PER_CORPUS]
                       + sorted(per["reproduction"], key=lambda s: s.distance)[:COMBINED_PER_CORPUS])
        cscores = run_judge(kind, claude, gptoss_model, category, statement,
                            merged, CORP_LABEL["combined"])
        crefs = references_from(merged)
        scopes["combined"] = {"scores": cscores, "n_references": len(crefs),
                              "references": crefs,
                              "snippets": [snippet_to_dict(s) for s in merged]}
        out["judges"][jname] = {"model": "claude-opus-4-8" if kind == "claude" else gptoss_model,
                                "scopes": scopes}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gptoss-model", default=os.environ.get("SF_GPTOSS_MODEL",
                                                             "huihui_ai/gpt-oss-abliterated:120b"))
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    raw_dir = OUTDIR / "raw"; raw_dir.mkdir(parents=True, exist_ok=True)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    sfs = [s for s in SFS if (not only or s[0] in only)]

    # anthropic client (decrypt BYOK key)
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / "app" / "backend" / ".env")
    from pymongo import MongoClient
    from app.core.crypto import decrypt  # type: ignore
    import anthropic
    key = decrypt(MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017"))[
        os.environ.get("MONGODB_DB_NAME") or "advandeb"].user_llm_keys.find_one(
        {"provider": "anthropic"})["encrypted_key"])
    claude = anthropic.Anthropic(api_key=key)
    print(f"[setup] gpt-oss judge = {args.gptoss_model}")

    repro_idx = load_repro_index()
    lit_idx = load_lit_index()

    for n, (sf_id, cat, stmt) in enumerate(sfs, 1):
        cache = raw_dir / f"{sf_id}.json"
        if cache.exists() and not args.force:
            print(f"[{n}/{len(sfs)}] {sf_id}: cached"); continue
        t = time.time()
        print(f"[{n}/{len(sfs)}] {sf_id}: full-corpus retrieve + dual judge …", flush=True)
        res = analyze(sf_id, cat, stmt, repro_idx, lit_idx, claude, args.gptoss_model)
        cache.write_text(json.dumps(res, indent=2, ensure_ascii=False))
        g = res["judges"]["gptoss"]["scopes"]; c = res["judges"]["claude"]["scopes"]
        print(f"      {time.time()-t:.0f}s  "
              f"gptoss[deb Ev{g['deb']['scores']['evidence_strength']} "
              f"repro Ev{g['reproduction']['scores']['evidence_strength']} "
              f"(refs {g['reproduction']['n_references']})]  "
              f"claude[deb Ev{c['deb']['scores']['evidence_strength']} "
              f"repro Ev{c['reproduction']['scores']['evidence_strength']} "
              f"(refs {c['reproduction']['n_references']})]")
    print(f"[done] -> {OUTDIR}")


if __name__ == "__main__":
    main()
