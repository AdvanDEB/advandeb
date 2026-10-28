#!/usr/bin/env python3
"""
Offline retrieval evaluation: recall@k and MRR for hybrid retrieval.

Query set
---------
``build-queries`` derives one query per stylized fact from the judged
evidence in ``analysis/sf_support_fullcorpus/raw/*.json``: the query is the
SF statement, and a paper is relevant when both judges (gpt-oss:120b and
Claude) labelled one of its passages as supporting or contradicting the SF.
Relevance is judged at the paper level because the passages were retrieved
from a differently chunked corpus. Papers are keyed so every chunk lineage of
the same paper maps to one key:

    file:<pdf basename, lower case>   full-text DEB library (all lineages)
    oa:<OpenAlex id>                  reproduction abstracts

Caveat: the judged passages were themselves found by retrieval (nomic-embed
top hits), so this is pooled relevance — papers that pool never surfaced are
unlabelled, and absolute recall is an upper bound. Use it to compare
configurations, not as a population estimate.

Metrics (over the top-k chunks returned, chunk ranks):
    recall@k  share of the query's retrievable relevant papers among the papers
              of the top-k chunks
    MRR       1 / rank of the first chunk from a relevant paper (0 if none in top 20)
    dup@10    top-10 chunks whose paper already appeared higher in the list
    duptxt@10 top-10 chunks whose text (whitespace-normalised) already appeared:
              the same passage under two chunk ids, i.e. two ingestions of one PDF
Queries whose relevant papers are absent from the corpus are reported, not scored.

Subcommands
-----------
    build-queries   write the query set JSON
    run             evaluate retrieval configurations against a ChromaDB copy,
                    a (scratch) Arango database with the chunks view, and the
                    MongoDB $text fallback (read-only)
    chunker-ab      re-chunk the full-text library with the old and the new
                    chunker, embed both, and compare vector retrieval

Never point --chroma-dir at the live store while the retrieval agent runs:
work on a copy.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPO = ROOT.parent
DEFAULT_QUERIES = ROOT / "eval" / "sf_support_queries.json"
DEFAULT_ANALYSIS = REPO / "analysis" / "sf_support_fullcorpus" / "raw"
RELEVANT_LABELS = {"supports", "contradicts"}
KS = (5, 10, 20)


# ---------------------------------------------------------------------------
# Paper keys
# ---------------------------------------------------------------------------

def file_key(path: str) -> str:
    return "file:" + os.path.basename(path.strip()).lower()


def paper_key(metadata: dict, doc_paths: dict[str, str]) -> str:
    """Map a retrieved chunk's metadata to its paper key."""
    src = (metadata.get("source_path") or "").strip()
    if src:
        return file_key(src)
    doc_id = str(metadata.get("document_id") or "")
    if doc_id.startswith("W") and doc_id[1:].isdigit():
        return "oa:" + doc_id
    if doc_id in doc_paths:
        return file_key(doc_paths[doc_id])
    return "doc:" + doc_id


# ---------------------------------------------------------------------------
# build-queries
# ---------------------------------------------------------------------------

def _snippet_key(s: dict) -> tuple:
    return (str(s.get("document_id")), (s.get("text") or "")[:120])


def _paper_of_snippet(s: dict, scope: str) -> str:
    if s.get("corpus", scope) == "reproduction":
        return "oa:" + str(s["document_id"])
    return file_key(s.get("title") or "")


def build_queries(analysis_dir: Path, out: Path) -> None:
    queries = []
    for f in sorted(glob.glob(str(analysis_dir / "*.json"))):
        d = json.loads(Path(f).read_text())
        relevant: dict[str, set] = {"deb": set(), "reproduction": set()}
        for scope in ("deb", "reproduction", "combined"):
            claude = d["judges"]["claude"]["scopes"].get(scope, {}).get("snippets", [])
            gpt = {
                _snippet_key(s): s.get("label")
                for s in d["judges"]["gptoss"]["scopes"].get(scope, {}).get("snippets", [])
            }
            for s in claude:
                if s.get("label") in RELEVANT_LABELS and gpt.get(_snippet_key(s)) in RELEVANT_LABELS:
                    corpus = s.get("corpus") or scope
                    relevant["reproduction" if corpus == "reproduction" else "deb"].add(
                        _paper_of_snippet(s, scope)
                    )
        if not (relevant["deb"] or relevant["reproduction"]):
            continue
        queries.append({
            "qid": d["sf_id"],
            "category": d.get("category"),
            "query": d["statement"],
            "relevant": {k: sorted(v) for k, v in relevant.items()},
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "name": "sf_support_fullcorpus",
        "source": str(analysis_dir.relative_to(REPO)),
        "relevance": "paper judged supports/contradicts by both gpt-oss:120b and Claude",
        "queries": queries,
    }, indent=1, ensure_ascii=False) + "\n")
    n_deb = sum(len(q["relevant"]["deb"]) for q in queries)
    n_rep = sum(len(q["relevant"]["reproduction"]) for q in queries)
    print(f"wrote {len(queries)} queries ({n_deb} deb + {n_rep} reproduction relevant papers) to {out}")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def score_ranking(keys: list[str], relevant: set[str], texts: Optional[list[str]] = None) -> dict:
    out: dict = {}
    for k in KS:
        found = {p for p in keys[:k] if p in relevant}
        out[f"recall@{k}"] = len(found) / len(relevant)
    out["mrr"] = next((1.0 / (i + 1) for i, p in enumerate(keys[:20]) if p in relevant), 0.0)
    seen: set = set()
    dups = 0
    for p in keys[:10]:
        dups += p in seen
        seen.add(p)
    out["dup@10"] = dups
    if texts is not None:
        norm = [" ".join(t.split())[:300] for t in texts[:10]]
        out["duptext@10"] = len(norm) - len(set(norm))
    return out


def summarize(per_query: list[dict]) -> dict:
    keys = [f"recall@{k}" for k in KS] + ["mrr", "dup@10", "duptext@10"]
    return {k: statistics.fmean(q.get(k, 0) for q in per_query) for k in keys} | {"n": len(per_query)}


def paired_diff(a: list[dict], b: list[dict], metric: str, n_boot: int = 10000, seed: int = 0) -> dict:
    """Mean of b - a over the same queries, with a paired bootstrap 95% CI."""
    import random

    diffs = [y[metric] - x[metric] for x, y in zip(a, b)]
    rng = random.Random(seed)
    boots = sorted(
        statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(n_boot)
    )
    return {
        "mean": statistics.fmean(diffs),
        "ci95": (boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot)]),
        "wins": sum(d > 0 for d in diffs),
        "losses": sum(d < 0 for d in diffs),
    }


def print_table(rows: dict[str, dict], title: str) -> None:
    print(f"\n{title}")
    header = f"{'config':<22}" + "".join(f"{h:>11}" for h in ("recall@5", "recall@10", "recall@20", "MRR", "dup@10", "duptxt@10", "n"))
    print(header)
    print("-" * len(header))
    for name, s in rows.items():
        print(f"{name:<22}" + "".join(
            f"{s[k]:>11.3f}" for k in ("recall@5", "recall@10", "recall@20", "mrr", "dup@10", "duptext@10")
        ) + f"{s['n']:>11d}")


# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------

def arango_db(db_name: str):
    from arango import ArangoClient
    from advandeb_kb.config.settings import settings

    client = ArangoClient(hosts=settings.ARANGO_URL, request_timeout=600)
    return client.db(db_name, username=settings.ARANGO_USERNAME, password=settings.ARANGO_PASSWORD)


def load_doc_paths(docs_db) -> dict[str, str]:
    """document key -> source_path for the full-text library (read-only)."""
    rows = docs_db.aql.execute(
        "FOR d IN documents FILTER d.source_type == 'pdf_local' AND d.source_path != null "
        "RETURN [d._key, d.source_path]"
    )
    return {k: p for k, p in rows}


def corpus_papers(chunks_db, doc_paths: dict[str, str], wanted: set[str]) -> set[str]:
    """Which of the wanted paper keys have at least one chunk in the corpus."""
    present = set()
    paths = chunks_db.aql.execute(
        "FOR c IN chunks FILTER c.source_path != null COLLECT p = c.source_path RETURN p"
    )
    present |= {file_key(p) for p in paths}
    # Library documents whose chunks carry no source_path.
    with_chunks = set(chunks_db.aql.execute(
        "FOR k IN @keys FILTER LENGTH(FOR c IN chunks FILTER c.document_id == k LIMIT 1 RETURN 1) > 0 RETURN k",
        bind_vars={"keys": list(doc_paths)},
    ))
    present |= {file_key(doc_paths[k]) for k in with_chunks}
    oa = [p[3:] for p in wanted if p.startswith("oa:")]
    if oa:
        found = chunks_db.aql.execute(
            "FOR id IN @ids FILTER LENGTH(FOR c IN chunks FILTER c.document_id == id LIMIT 1 RETURN 1) > 0 RETURN id",
            bind_vars={"ids": oa},
        )
        present |= {"oa:" + i for i in found}
    return present & wanted


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

async def _run(args) -> dict:
    from pymongo import MongoClient

    from advandeb_kb.config.settings import settings
    from advandeb_kb.services.chromadb_service import ChromaDBService
    from advandeb_kb.services.embedding_service import EmbeddingService
    from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService, chunk_domain

    qset = json.loads(Path(args.queries).read_text())["queries"]
    if args.limit:
        qset = qset[: args.limit]

    if Path(args.chroma_dir).resolve() == Path(settings.CHROMA_PERSIST_DIR).resolve() and not args.allow_live_chroma:
        raise SystemExit("refusing to open the live ChromaDB store; pass a copy via --chroma-dir")

    chunks_db = arango_db(args.arango_db)
    docs_db = arango_db(args.docs_db)
    doc_paths = load_doc_paths(docs_db)
    mongo = MongoClient(settings.MONGODB_URL)[args.mongo_db]

    all_relevant = {p for q in qset for v in q["relevant"].values() for p in v}
    present = corpus_papers(chunks_db, doc_paths, all_relevant)

    embedder = EmbeddingService()
    chroma = ChromaDBService(persist_dir=args.chroma_dir)
    svc = HybridRetrievalService(
        embedding_svc=embedder,
        chromadb_svc=chroma,
        arango_db=chunks_db,
        mongo_db=mongo,
        keyword_backend="arango",
        rerank_model=args.rerank_model,
    )
    # "Before": the fusion code as deployed (git --old-rev), with the MongoDB
    # $text keyword arm the deployed RetrievalAgent uses. Its reranker always
    # failed (model "llama2" is not installed), so before = no reranking.
    OldService = _load_module_at(
        args.old_rev, "advandeb_kb/services/hybrid_retrieval_service.py", Path(args.work_dir)
    ).HybridRetrievalService
    old_svc = OldService(embedder, chroma, mongo_db=mongo)

    configs = ["before (vec+mongo)", "vec+bm25, old fusion", "vector only", "bm25 only", "after (vec+bm25)"]
    if args.rerank_model:
        configs.append("after + rerank")
    per_cfg: dict[str, list] = {c: [] for c in configs}
    per_domain: dict[str, dict[str, list]] = {d: {c: [] for c in configs} for d in ("deb", "reproduction")}
    latency: dict[str, list] = {"vector": [], "mongo": [], "bm25": [], "rerank": []}
    skipped = []
    top_k = args.top_k

    def keys_of(results) -> list[str]:
        return [paper_key(r.metadata if hasattr(r, "metadata") else r["metadata"], doc_paths) for r in results]

    def texts_of(results) -> list[str]:
        return [r.text if hasattr(r, "text") else r["text"] for r in results]

    for qi, q in enumerate(qset):
        relevant = {p for v in q["relevant"].values() for p in v} & present
        if not relevant:
            skipped.append(q["qid"])
            continue
        qvec = await svc._embed(q["query"])
        t = time.perf_counter(); vec = svc._vector_hits_sync(qvec, top_k * 2, None); latency["vector"].append(time.perf_counter() - t)
        t = time.perf_counter(); mongo_hits = svc._mongo_keyword_search(q["query"], top_k * 2, None); latency["mongo"].append(time.perf_counter() - t)
        t = time.perf_counter(); bm25 = svc._arango_bm25_search(q["query"], top_k * 2, None); latency["bm25"].append(time.perf_counter() - t)

        after = svc._build_results(svc._reciprocal_rank_fusion(vec, bm25), vec, bm25, top_k)
        rankings = {
            "before (vec+mongo)": old_svc._build_results(
                old_svc._reciprocal_rank_fusion(vec, mongo_hits), vec, mongo_hits, top_k),
            "vec+bm25, old fusion": old_svc._build_results(
                old_svc._reciprocal_rank_fusion(vec, bm25), vec, bm25, top_k),
            "vector only": svc._dedupe(vec)[:top_k],
            "bm25 only": svc._dedupe(bm25)[:top_k],
            "after (vec+bm25)": after,
        }
        if args.rerank_model:
            t = time.perf_counter()
            fresh = [type(r).from_dict(r.to_dict()) for r in after]
            rankings["after + rerank"] = await svc._rerank_with_llm(q["query"], fresh, top_n=10)
            latency["rerank"].append(time.perf_counter() - t)

        for cfg, res in rankings.items():
            keys = keys_of(res)
            per_cfg[cfg].append(score_ranking(keys, relevant, texts_of(res)) | {"qid": q["qid"]})
            for dom in ("deb", "reproduction"):
                rel_d = set(q["relevant"][dom]) & present
                if rel_d:
                    per_domain[dom][cfg].append(score_ranking(keys, rel_d))
        if args.verbose:
            print(f"[{qi + 1}/{len(qset)}] {q['qid']}: " + "  ".join(
                f"{c.split()[0]} mrr={per_cfg[c][-1]['mrr']:.2f}" for c in configs))

    # Domain filter, exercised through the public API.
    filt: dict[str, list] = {"deb": [], "reproduction": []}
    for q in qset:
        for dom in ("deb", "reproduction"):
            rel_d = set(q["relevant"][dom]) & present
            if not rel_d:
                continue
            res = await svc.retrieve(q["query"], top_k=top_k, domain_filter=dom)
            assert all(chunk_domain(r.metadata) == dom for r in res)
            filt[dom].append(score_ranking(keys_of(res), rel_d))

    report = {
        "queries": len(qset),
        "scored": len(qset) - len(skipped),
        "skipped_no_relevant_in_corpus": skipped,
        "relevant_papers": len(all_relevant),
        "relevant_papers_in_corpus": len(present),
        "overall": {c: summarize(v) for c, v in per_cfg.items()},
        "by_domain_unfiltered": {d: {c: summarize(v) for c, v in cs.items() if v} for d, cs in per_domain.items()},
        "domain_filtered_hybrid": {d: summarize(v) for d, v in filt.items() if v},
        "latency_ms_median": {k: round(1000 * statistics.median(v), 1) for k, v in latency.items() if v},
        "paired_deb": {
            f"{b} vs {a}": {m: paired_diff(per_domain["deb"][a], per_domain["deb"][b], m)
                            for m in ("mrr", "recall@5", "recall@10")}
            for a, b in [("before (vec+mongo)", "after (vec+bm25)"),
                         ("before (vec+mongo)", "vec+bm25, old fusion"),
                         ("vec+bm25, old fusion", "after (vec+bm25)")]
            + ([("after (vec+bm25)", "after + rerank"), ("before (vec+mongo)", "after + rerank")]
               if args.rerank_model else [])
        },
        "per_query": per_cfg,
    }
    return report


def cmd_run(args) -> None:
    report = asyncio.run(_run(args))
    print(f"\nqueries scored: {report['scored']}/{report['queries']}  "
          f"(relevant papers in corpus: {report['relevant_papers_in_corpus']}/{report['relevant_papers']})")
    print_table(report["overall"], "All relevant papers (no domain filter)")
    for d, rows in report["by_domain_unfiltered"].items():
        print_table(rows, f"Relevant papers of domain {d} only (no filter)")
    print_table({f"filter={d}": s for d, s in report["domain_filtered_hybrid"].items()},
                "Hybrid with domain_filter (relevant papers of that domain)")
    print(f"\nmedian latency (ms): {report['latency_ms_median']}")
    print("\nPaired differences on the deb slice (mean, 95% bootstrap CI, wins/losses):")
    for pair, metrics in report["paired_deb"].items():
        print(f"  {pair}: " + "; ".join(
            f"{m} {d['mean']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}] {d['wins']}/{d['losses']}"
            for m, d in metrics.items()))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
        print(f"report written to {args.out}")


# ---------------------------------------------------------------------------
# chunker-ab
# ---------------------------------------------------------------------------

def _load_module_at(rev: str, relpath: str, tmp_dir: Path):
    """Import a knowledge-builder module as it was at git revision ``rev``."""
    src = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{rev}:knowledge-builder/{relpath}"],
        check=True, capture_output=True, text=True,
    ).stdout
    tmp_dir.mkdir(parents=True, exist_ok=True)
    name = f"{Path(relpath).stem}_at_{rev.replace('/', '_')}"
    path = tmp_dir / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look their module up while being defined
    spec.loader.exec_module(mod)
    return mod


def cmd_chunker_ab(args) -> None:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    from advandeb_kb.config.settings import settings
    from advandeb_kb.services.chunking_service import ChunkingService as NewChunker

    OldChunker = _load_module_at(
        args.old_rev, "advandeb_kb/services/chunking_service.py", Path(args.work_dir)
    ).ChunkingService
    qset = json.loads(Path(args.queries).read_text())["queries"]

    docs_db = arango_db(args.docs_db)
    docs = list(docs_db.aql.execute(
        "FOR d IN documents FILTER d.source_type == 'pdf_local' AND LENGTH(d.content) > 0 "
        "RETURN {k: d._key, p: d.source_path, c: d.content}"
    ))
    print(f"{len(docs)} full-text documents, {sum(len(d['c']) for d in docs) / 1e6:.1f}M chars")
    in_corpus = {file_key(d["p"]) for d in docs if d.get("p")}

    model = SentenceTransformer(settings.EMBEDDING_MODEL, device=args.device)
    q_emb = model.encode([q["query"] for q in qset], normalize_embeddings=True, convert_to_numpy=True)

    rows, per_query_by = {}, {}
    for name, chunker in (("old chunker", OldChunker(512, 128)), ("new chunker", NewChunker(512, 128))):
        texts, keys = [], []
        t = time.time()
        for d in docs:
            for c in chunker.chunk_document(d["c"], d["k"]):
                texts.append(c.text)
                keys.append(file_key(d["p"]) if d.get("p") else "doc:" + d["k"])
        t_chunk = time.time() - t
        t = time.time()
        emb = model.encode(texts, batch_size=256, normalize_embeddings=True, convert_to_numpy=True,
                           show_progress_bar=False).astype(np.float32)
        t_emb = time.time() - t
        sims = q_emb @ emb.T
        per_query = []
        for qi, q in enumerate(qset):
            rel = set(q["relevant"]["deb"]) & in_corpus
            if not rel:
                continue
            top = np.argsort(-sims[qi])[: args.top_k]
            per_query.append(score_ranking([keys[i] for i in top], rel))
        rows[name] = summarize(per_query)
        per_query_by[name] = per_query
        glued = sum(1 for tx in texts if "\n" not in tx and len(tx) > 400 and " " not in tx[100:200])
        print(f"{name}: {len(texts):,} chunks (avg {statistics.fmean(map(len, texts)):.0f} chars), "
              f"chunked in {t_chunk:.1f}s, embedded in {t_emb:.0f}s ({len(texts) / t_emb:.0f}/s); "
              f"chunks with a 100-char run without spaces: {glued}")
    print_table(rows, "Full-text library only, vector retrieval, deb-relevant papers")
    paired = {m: paired_diff(per_query_by["old chunker"], per_query_by["new chunker"], m)
              for m in ("mrr", "recall@5", "recall@10", "recall@20")}
    print("new vs old chunker (mean, 95% bootstrap CI, wins/losses): " + "; ".join(
        f"{m} {d['mean']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}] {d['wins']}/{d['losses']}"
        for m, d in paired.items()))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": rows, "paired": paired}, indent=1) + "\n")


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-queries")
    b.add_argument("--analysis-dir", default=str(DEFAULT_ANALYSIS))
    b.add_argument("--out", default=str(DEFAULT_QUERIES))

    r = sub.add_parser("run")
    r.add_argument("--queries", default=str(DEFAULT_QUERIES))
    r.add_argument("--chroma-dir", required=True, help="a COPY of data/chromadb")
    r.add_argument("--allow-live-chroma", action="store_true")
    r.add_argument("--arango-db", required=True, help="database holding chunks + the BM25 view (scratch)")
    r.add_argument("--docs-db", default="advandeb_kb", help="database holding documents (read only)")
    r.add_argument("--mongo-db", default="advandeb_knowledge_builder_kb", help="MongoDB with legacy chunks (read only)")
    r.add_argument("--rerank-model", default=None, help="also evaluate LLM reranking with this Ollama model")
    r.add_argument("--old-rev", default="main", help="git revision with the deployed retrieval code")
    r.add_argument("--work-dir", default="/tmp/advandeb_eval")
    r.add_argument("--top-k", type=int, default=20)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--out")
    r.add_argument("-v", "--verbose", action="store_true")

    c = sub.add_parser("chunker-ab")
    c.add_argument("--queries", default=str(DEFAULT_QUERIES))
    c.add_argument("--docs-db", default="advandeb_kb", help="database holding documents (read only)")
    c.add_argument("--old-rev", default="main", help="git revision with the old chunker")
    c.add_argument("--work-dir", default="/tmp/advandeb_eval")
    c.add_argument("--device", default=None)
    c.add_argument("--top-k", type=int, default=20)
    c.add_argument("--out")

    args = ap.parse_args()
    {"build-queries": lambda a: build_queries(Path(a.analysis_dir), Path(a.out)),
     "run": cmd_run, "chunker-ab": cmd_chunker_ab}[args.cmd](args)


if __name__ == "__main__":
    main()
