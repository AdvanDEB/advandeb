"""
SFMatcherService — links facts to stylized facts, natively in ArangoDB.

Why this exists
---------------
The original SF matching lives in ``app/kb/pipeline.py`` (``_match_sfs``) and
reads ``stylized_facts`` / writes ``fact_sf_relations`` in **MongoDB**. The
abstract-derived corpus was ingested straight into ArangoDB and never landed in
Mongo — sampling 20 facts from completed reproduction documents found 0 of them
in either Mongo database. So the Mongo matcher is structurally incapable of
seeing them, which is why every one of the 18,053 facts carrying an
``sf_support`` edge comes from the 1,253 curated papers, and why the
``sf_support`` and ``reproduction`` graphs share no structure at all.

This service does the same two-phase job against Arango, where the other 91,342
unlinked facts actually live.

Matching strategy
-----------------
  Phase 1 — keyword overlap against an in-memory inverted index of stylized
            fact statements. Free: ~5,000 facts scored in 0.1s. Measured hit
            rate on unlinked facts is 37.5%, mean 5.5 candidates each.
  Phase 2 — one LLM call per surviving fact to decide supports vs opposes and
            a confidence, over that fact's candidates.

Phase 2 dominates the cost, and the model choice dominates Phase 2. Measured on
an identical prompt: ``deepseek-r1:latest`` (the pipeline default, a reasoning
model) ~80s per call; ``gemma3:latest`` 5.8s; ``llama3.1:8b`` 3.6s with valid
JSON every time. Hence ``DEFAULT_MODEL`` below — a reasoning model is the wrong
tool for a two-way classification.

Edges are written to ``sf_support`` with ``status="suggested"`` and
``created_by="sf_matcher"`` so they are distinguishable from the existing
``created_by="agent"`` rows and reviewable rather than asserted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from advandeb_kb.database.arango_client import ArangoDatabase

logger = logging.getLogger(__name__)

# A reasoning model spends its budget on chain-of-thought before emitting the
# JSON. For a binary classification that is pure overhead — see module docstring
# for the measured comparison.
DEFAULT_MODEL = "llama3.1:8b"

# Words shorter than this carry no signal for overlap scoring.
_MIN_WORD_LEN = 5

# Candidate ceiling per fact. Mirrors the Mongo matcher's `.limit(15)`; also
# bounds the prompt so latency stays predictable.
_MAX_CANDIDATES = 15

# Minimum shared words before a stylized fact is even considered.
_MIN_OVERLAP = 2

_STOPWORDS = {
    "about", "above", "after", "again", "against", "among", "around", "because",
    "been", "before", "being", "below", "between", "both", "cannot", "could",
    "does", "doing", "during", "each", "either", "found", "from", "further",
    "have", "having", "here", "however", "into", "itself", "just", "more",
    "most", "much", "must", "neither", "only", "other", "over", "same",
    "should", "since", "some", "such", "than", "that", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "under", "until",
    "very", "were", "what", "when", "where", "which", "while", "with", "would",
    "study", "studies", "results", "result", "shown", "showed", "show",
    "observed", "using", "used", "also", "both", "based",
}

_SYSTEM_PROMPT = (
    "You are a scientific knowledge linker. "
    "Given a fact and a numbered list of stylized facts, return ONLY a JSON array. "
    "Each element must be an object with: 'index' (integer, 0-based), "
    "'relation_type' (exactly 'supports' or 'opposes'), 'confidence' (float 0-1). "
    "Include an entry for every stylized fact that the given fact either supports "
    "OR opposes. Omit unrelated ones. Return [] if none are related. "
    "No markdown, no commentary."
)

# Scope → AQL selecting candidate fact keys. Every scope excludes facts that
# already carry an sf_support edge unless the caller asks to overwrite.
_SCOPE_AQL = {
    # Everything without a link yet.
    "unlinked": """
    LET linked = (FOR e IN sf_support RETURN DISTINCT PARSE_IDENTIFIER(e._from).key)
    FOR f IN facts
        FILTER @overwrite OR f._key NOT IN linked
        SORT f._key
        LIMIT @skip, @limit
        RETURN {_key: f._key, content: f.content}
    """,
    # Facts from the abstract corpus — the half of the KB that has never been
    # matched at all, and the reason the reproduction graph has no supports edges.
    "reproduction": """
    LET linked = (FOR e IN sf_support RETURN DISTINCT PARSE_IDENTIFIER(e._from).key)
    LET dk = (FOR d IN documents
                FILTER d.general_domain == 'reproduction'
                   AND d.processing_status == 'completed'
                RETURN d._key)
    FOR f IN facts
        FILTER f.document_id IN dk
        FILTER @overwrite OR f._key NOT IN linked
        SORT f._key
        LIMIT @skip, @limit
        RETURN {_key: f._key, content: f.content}
    """,
}


def _words(text: str) -> set:
    """Content words used for overlap scoring."""
    return {
        w.lower().strip(".,;:()[]\"'")
        for w in re.split(r"\s+", text or "")
        if len(w) > _MIN_WORD_LEN and w.lower() not in _STOPWORDS
    }


def _parse_llm_json(raw: str) -> Optional[list]:
    """Parse the model's reply, tolerating a markdown fence around it."""
    clean = (raw or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(clean)
    except Exception:
        return None
    return parsed if isinstance(parsed, list) else None


class SFMatcherService:
    """Two-phase fact → stylized-fact matcher operating on ArangoDB."""

    def __init__(
        self,
        database: ArangoDatabase,
        ollama_url: str = "http://localhost:11434",
        model: str = DEFAULT_MODEL,
    ):
        self.db = database
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        # normalized word → [stylized_fact _key, ...]
        self._inverted: Dict[str, List[str]] = {}
        self._statements: Dict[str, str] = {}
        self._sf_words: Dict[str, set] = {}

    # ------------------------------------------------------------------
    # Phase 1 — candidate index
    # ------------------------------------------------------------------

    async def build_sf_index(self) -> int:
        """Load published stylized facts and build the inverted word index."""
        def _build():
            rows = self.db.aql(
                "FOR s IN stylized_facts FILTER s.status == null OR s.status == 'published' "
                "RETURN {k: s._key, statement: s.statement}",
                bind_vars={},
            )
            inverted: Dict[str, List[str]] = {}
            statements: Dict[str, str] = {}
            sf_words: Dict[str, set] = {}
            for row in rows:
                key, statement = row["k"], row.get("statement") or ""
                statements[key] = statement
                ws = _words(statement)
                sf_words[key] = ws
                for w in ws:
                    inverted.setdefault(w, []).append(key)
            return inverted, statements, sf_words

        loop = asyncio.get_running_loop()
        self._inverted, self._statements, self._sf_words = await loop.run_in_executor(None, _build)
        logger.info(
            "SFMatcherService: indexed %d stylized facts, %d distinct words",
            len(self._statements), len(self._inverted),
        )
        return len(self._statements)

    def candidates_for(self, content: str) -> List[str]:
        """Stylized fact keys sharing at least ``_MIN_OVERLAP`` words with the fact."""
        fact_words = _words(content)
        if not fact_words:
            return []
        counts: Dict[str, int] = {}
        for w in fact_words:
            for key in self._inverted.get(w, ()):
                counts[key] = counts.get(key, 0) + 1
        ranked = [(k, n) for k, n in counts.items() if n >= _MIN_OVERLAP]
        ranked.sort(key=lambda kv: (-kv[1], kv[0]))
        return [k for k, _ in ranked[:_MAX_CANDIDATES]]

    # ------------------------------------------------------------------
    # Phase 2 — LLM classification
    # ------------------------------------------------------------------

    async def classify(
        self,
        client: httpx.AsyncClient,
        content: str,
        candidate_keys: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Classify supports/opposes for one fact against its candidates.

        Returns ``{sf_key: {relation_type, confidence}}``. On any failure the
        fact is left unlinked rather than guessed at — the Mongo matcher's
        fallback of "supports @ 0.4 for every candidate" manufactures edges the
        model never actually endorsed, and at this volume that would be tens of
        thousands of invented relations.
        """
        sf_lines = "\n".join(f"[{i}] {self._statements[k]}" for i, k in enumerate(candidate_keys))
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Fact: {content}\n\nStylized facts:\n{sf_lines}\n\n"
                    "For each stylized fact above, does the given fact support or oppose it?"
                )},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            resp = await client.post(f"{self.ollama_url}/api/chat", json=payload, timeout=180.0)
            resp.raise_for_status()
            parsed = _parse_llm_json(resp.json()["message"]["content"])
        except Exception as exc:
            logger.warning("SF classification failed: %s", exc)
            return {}
        if parsed is None:
            return {}

        out: Dict[str, Dict[str, Any]] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(candidate_keys)):
                continue
            rel = item.get("relation_type")
            if rel not in ("supports", "opposes"):
                continue
            try:
                conf = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            out[candidate_keys[idx]] = {
                "relation_type": rel,
                "confidence": round(min(1.0, max(0.0, conf)), 3),
            }
        return out

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    async def match_facts(
        self,
        limit: int = 500,
        skip: int = 0,
        scope: str = "unlinked",
        overwrite: bool = False,
        concurrency: int = 3,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Match a batch of facts and write ``sf_support`` edges.

        ``concurrency`` is how many classifications are in flight at once.
        Ollama serialises requests per loaded model instance, so raising this
        past what the GPU can hold as parallel instances buys nothing.

        ``dry_run`` runs both phases and reports what would be written without
        touching the database — use it to sanity-check quality before a long run.
        """
        if not self._statements:
            raise RuntimeError("Call build_sf_index() before match_facts()")
        if scope not in _SCOPE_AQL:
            raise ValueError(f"Unknown scope {scope!r}; expected one of {sorted(_SCOPE_AQL)}")

        loop = asyncio.get_running_loop()
        facts = await loop.run_in_executor(
            None,
            lambda: self.db.aql(
                _SCOPE_AQL[scope],
                bind_vars={"skip": skip, "limit": limit, "overwrite": overwrite},
            ),
        )

        # Phase 1 is cheap enough to run over everything up front.
        pending: List[Tuple[Dict[str, Any], List[str]]] = []
        for fact in facts:
            cands = self.candidates_for(fact.get("content") or "")
            if cands:
                pending.append((fact, cands))

        stats = {
            "scope": scope,
            "facts_scanned": len(facts),
            "facts_with_candidates": len(pending),
            "facts_linked": 0,
            "edges_written": 0,
            "classification_failures": 0,
            "dry_run": dry_run,
        }
        if not pending:
            return stats

        semaphore = asyncio.Semaphore(max(1, concurrency))
        now_iso = datetime.now(timezone.utc).isoformat()
        edges: List[Dict[str, Any]] = []
        failures = 0

        async with httpx.AsyncClient() as client:
            async def _one(fact: Dict[str, Any], cands: List[str]) -> List[Dict[str, Any]]:
                nonlocal failures
                async with semaphore:
                    result = await self.classify(client, fact.get("content") or "", cands)
                if not result:
                    failures += 1
                    return []
                return [
                    {
                        "_key": f"{fact['_key']}_{sf_key}",
                        "_from": f"facts/{fact['_key']}",
                        "_to": f"stylized_facts/{sf_key}",
                        "relation_type": rel["relation_type"],
                        "confidence": rel["confidence"],
                        "status": "suggested",
                        "created_by": "sf_matcher",
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    }
                    for sf_key, rel in result.items()
                ]

            for batch in await asyncio.gather(*[_one(f, c) for f, c in pending]):
                if batch:
                    stats["facts_linked"] += 1
                    edges.extend(batch)

        stats["classification_failures"] = failures
        stats["edges_written"] = len(edges)

        if edges and not dry_run:
            await loop.run_in_executor(None, lambda: self._write_edges(edges))

        logger.info("SF matching (%s): %s", scope, stats)
        return stats

    def _write_edges(self, edges: Iterable[Dict[str, Any]]) -> None:
        """Upsert edges; the deterministic _key makes re-runs idempotent."""
        collection = self.db.db.collection("sf_support")
        collection.insert_many(list(edges), overwrite=True, silent=True)
