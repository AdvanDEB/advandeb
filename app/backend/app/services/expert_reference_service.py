"""
ExpertReferenceService — publications an expert names as bearing on a fact.

The third instrument (advandeb_methods docs/09 §2.5). An expert asserting that
a paper supports a stylized fact never moves the machine's score: that would
make the machine score partly a human artifact, and agreement between the two
panels would then be partly experts editing one of them. The machine can still
change its mind, but only by *reading the passage* — a named paper absent from
the corpus is queued for ingestion, which triggers re-retrieval and
re-adjudication.

**Resolution is the valuable part**, and its outcomes mean different things:

    not_in_corpus              a coverage gap
    in_corpus_not_retrieved    RETRIEVAL RECALL FAILURE — held and missed
    in_corpus_retrieved        the panel read it; disagreement is about
                               JUDGMENT, not retrieval

The second and third both present as "the expert disagrees with the machine"
and have opposite remedies — one is fixed by better retrieval, the other cannot
be. Collapsing them would make the disagreement uninterpretable.

A fifth outcome, `in_corpus_retrieval_unknown`, exists because the data
requires it: the DEB full-text corpus carries no DOI on any of its 1,306
documents, so a DOI cannot be matched against a `deb`-scope evidence set at
all. Forcing that case into one of the four would either inflate the
coverage-gap count or inflate the headline recall-failure figure with checks
never performed. It is named instead.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from bson import ObjectId
from bson.errors import InvalidId

from app.core.database import get_database

logger = logging.getLogger(__name__)

OPENALEX = "https://api.openalex.org/works/doi:"
CROSSREF = "https://api.crossref.org/works/"

# Corpora that can be searched by DOI at all. The DEB full-text corpus is
# deliberately absent: it stores no DOIs (verified — 0 of 1,306 documents carry
# the field), which is why `in_corpus_retrieval_unknown` exists.
LIT_DB = os.environ.get("DEB_LITERATURE_DB", "deb_literature_review")
REPRO_DB = os.environ.get("DEB_REPRO_DB", "deb_abstracts_reproduction")

# Evidence sets currently live as analysis artefacts rather than in the app
# store; retrieval membership is checked against them where they exist.
EVIDENCE_DIR = os.path.expanduser(
    "~/dev/advandeb/analysis/sf_support_fullcorpus/raw")


def normalise_doi(raw: str) -> str:
    """Strip the many ways a DOI gets pasted down to the bare identifier."""
    d = (raw or "").strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d.strip()


class ExpertReferenceService:
    def __init__(self) -> None:
        self.db = get_database()

    # ------------------------------------------------------------------ #
    # External resolution
    # ------------------------------------------------------------------ #

    async def resolve_metadata(self, doi: str) -> Optional[Dict[str, Any]]:
        """Title/year/OpenAlex id for a DOI, or None if it does not resolve.

        OpenAlex first (it is what the corpora are keyed on), Crossref as a
        fallback so a paper OpenAlex has not indexed is not called invalid.
        """
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                r = await client.get(OPENALEX + doi,
                                     headers={"User-Agent": "advandeb/1.0"})
                if r.status_code == 200:
                    w = r.json()
                    return {
                        "title": w.get("title") or w.get("display_name"),
                        "year": w.get("publication_year"),
                        "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1] or None,
                        "source": "openalex",
                    }
            except Exception as exc:
                logger.warning("OpenAlex lookup failed for %s: %s", doi, exc)
            try:
                r = await client.get(CROSSREF + doi,
                                     headers={"User-Agent": "advandeb/1.0"})
                if r.status_code == 200:
                    m = (r.json() or {}).get("message", {})
                    title = (m.get("title") or [None])[0]
                    parts = (m.get("issued", {}).get("date-parts") or [[None]])[0]
                    return {"title": title, "year": parts[0] if parts else None,
                            "openalex_id": None, "source": "crossref"}
            except Exception as exc:
                logger.warning("Crossref lookup failed for %s: %s", doi, exc)
        return None

    # ------------------------------------------------------------------ #
    # Corpus membership
    # ------------------------------------------------------------------ #

    async def find_in_corpus(self, doi: str,
                             openalex_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Locate a DOI in any corpus that stores DOIs.

        Returns the corpus name and the identifier that corpus uses, because
        the retrieval check has to compare like with like — evidence sets
        reference documents by whatever id their source corpus assigns.
        """
        # App's own ingested documents
        d = await self.db.documents.find_one(
            {"doi": {"$regex": f"^{re.escape(doi)}$", "$options": "i"}},
            {"_id": 1, "title": 1})
        if d:
            return {"corpus": "app", "document_id": str(d["_id"]),
                    "title": d.get("title")}

        # Reproduction abstracts — chunks carry both doi and an OpenAlex doc_id
        try:
            client = self.db.client
            chunk = await client[REPRO_DB].abstract_chunks.find_one(
                {"doi": {"$regex": re.escape(doi) + "$", "$options": "i"}},
                {"doc_id": 1, "title": 1})
            if chunk:
                return {"corpus": "reproduction",
                        "document_id": str(chunk.get("doc_id")),
                        "title": chunk.get("title")}
        except Exception as exc:
            logger.warning("reproduction corpus lookup failed: %s", exc)

        if openalex_id:
            try:
                chunk = await self.db.client[REPRO_DB].abstract_chunks.find_one(
                    {"doc_id": openalex_id}, {"doc_id": 1, "title": 1})
                if chunk:
                    return {"corpus": "reproduction",
                            "document_id": str(chunk.get("doc_id")),
                            "title": chunk.get("title")}
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------ #
    # Retrieval membership — did the panel actually see it?
    # ------------------------------------------------------------------ #

    def _evidence_sets_for(self, sf_id: str) -> Optional[Dict[str, Any]]:
        import json
        path = os.path.join(EVIDENCE_DIR, f"{sf_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    async def _sf_id_for(self, sf_number: int) -> Optional[str]:
        """Map a collection fact number to the analysis artefact's sf_id.

        Only the 62 assessed facts have evidence sets; everything else returns
        None, which is a legitimate `no_evidence_set` outcome rather than an
        error.
        """
        fact = await self.db.stylized_facts.find_one(
            {"$or": [{"sf_number": sf_number}, {"sf_number": str(sf_number)}]},
            {"legacy_sf_id": 1, "statement": 1})
        if not fact:
            return None
        if fact.get("legacy_sf_id"):
            return fact["legacy_sf_id"]
        # Fall back to matching the statement against the artefacts.
        import glob
        import json
        want = re.sub(r"\W+", " ", (fact.get("statement") or "")).strip().lower()
        if not want:
            return None
        for path in glob.glob(os.path.join(EVIDENCE_DIR, "*.json")):
            try:
                with open(path) as f:
                    rec = json.load(f)
            except Exception:
                continue
            got = re.sub(r"\W+", " ", rec.get("statement", "")).strip().lower()
            if got == want:
                return rec.get("sf_id")
        return None

    def check_retrieval(self, artefact: Dict[str, Any], corpus: str,
                        document_id: str) -> Dict[str, Any]:
        """Did a passage from this document appear in the fact's evidence set?

        Only answerable when the holding corpus and the evidence set identify
        documents the same way. For the DEB full-text corpus they do not — it
        stores no DOIs — so that combination returns `corpus_lacks_doi` rather
        than a guess.
        """
        scopes = (artefact.get("judges", {}).get("claude", {})
                  .get("scopes", {}) or {})
        seen_any_scope = False
        panel_labels: Dict[str, Any] = {}

        for scope, block in scopes.items():
            for s in block.get("snippets", []) or []:
                if str(s.get("document_id")) == str(document_id):
                    seen_any_scope = True
                    panel_labels.setdefault(scope, []).append({
                        "label": s.get("label"),
                        "relevance": s.get("relevance"),
                        "title": s.get("title"),
                    })

        if seen_any_scope:
            return {"retrieved": True, "check": "exact",
                    "panel_labels": panel_labels}

        # Not found. Only a real "missed" if the evidence set could have
        # contained it — i.e. the scope's source corpus is the one holding the
        # document and identifies documents compatibly.
        if corpus == "reproduction" and "reproduction" in scopes:
            return {"retrieved": False, "check": "exact", "panel_labels": None}

        # The DEB scope references deb_literature_review by numeric doc_id and
        # that corpus has no DOI on any document, so a DOI-sourced identifier
        # can never match. Saying "not retrieved" here would manufacture a
        # recall failure that was never tested for.
        return {"retrieved": None, "check": "corpus_lacks_doi",
                "panel_labels": None}

    # ------------------------------------------------------------------ #
    # Create / list / delete
    # ------------------------------------------------------------------ #

    async def add(self, ref: Any, expert_id: str,
                  tier: Optional[str]) -> Dict[str, Any]:
        doi = normalise_doi(ref.doi)
        if not doi or "/" not in doi:
            return {"status": "error", "detail": "That does not look like a DOI."}

        existing = await self.db.expert_references.find_one({
            "sf_number": ref.sf_number, "doi": doi, "expert_id": expert_id})
        if existing:
            return {"status": "error",
                    "detail": "You have already cited this DOI for this fact."}

        meta = await self.resolve_metadata(doi)
        if not meta:
            # Rejected rather than stored: a dead identifier is not evidence,
            # and keeping one would quietly pad the counts.
            return {"status": "error",
                    "detail": "That DOI could not be resolved in OpenAlex or "
                              "Crossref. Check it and try again."}

        found = await self.find_in_corpus(doi, meta.get("openalex_id"))
        resolution: Dict[str, Any] = {
            "resolved_title": meta.get("title"),
            "resolved_year": meta.get("year"),
            "openalex_id": meta.get("openalex_id"),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "document_id": None, "evidence_set_id": None,
            "panel_labels": None, "agrees_with_panel": None,
        }
        ingestion_queued = False

        if not found:
            resolution["status"] = "not_in_corpus"
            resolution["retrieval_check"] = "not_applicable"
            ingestion_queued = True
        else:
            resolution["document_id"] = found["document_id"]
            resolution["corpus"] = found["corpus"]
            sf_id = await self._sf_id_for(ref.sf_number)
            artefact = self._evidence_sets_for(sf_id) if sf_id else None
            if not artefact:
                resolution["status"] = "in_corpus_retrieval_unknown"
                resolution["retrieval_check"] = "no_evidence_set"
            else:
                resolution["evidence_set_id"] = sf_id
                chk = self.check_retrieval(artefact, found["corpus"],
                                           found["document_id"])
                resolution["retrieval_check"] = chk["check"]
                if chk["retrieved"] is True:
                    resolution["status"] = "in_corpus_retrieved"
                    resolution["panel_labels"] = chk["panel_labels"]
                    # Did the panel read it the same way the expert does?
                    labels = [p["label"] for v in (chk["panel_labels"] or {}).values()
                              for p in v]
                    if labels:
                        agree = (ref.direction == "supports"
                                 and "supports" in labels) or \
                                (ref.direction == "opposes"
                                 and "contradicts" in labels)
                        resolution["agrees_with_panel"] = bool(agree)
                elif chk["retrieved"] is False:
                    # The measurement this feature exists to produce.
                    resolution["status"] = "in_corpus_not_retrieved"
                else:
                    resolution["status"] = "in_corpus_retrieval_unknown"

        doc = {
            "sf_number": ref.sf_number,
            "statement_sha256": ref.statement_sha256,
            "doi": doi,
            "direction": ref.direction,
            "note": (ref.note or "").strip() or None,
            "expert_id": expert_id,
            "tier": tier,
            "resolution": resolution,
            "ingestion_queued": ingestion_queued,
            "triggered_readjudication": ingestion_queued,
            "created_at": datetime.now(timezone.utc),
        }
        res = await self.db.expert_references.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        doc["created_at"] = doc["created_at"].isoformat()
        return {"status": "recorded", "reference": doc}

    async def list_for(self, sf_number: int,
                       expert_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q: Dict[str, Any] = {"sf_number": sf_number}
        if expert_id:
            q["expert_id"] = expert_id
        out = []
        async for r in self.db.expert_references.find(q).sort("created_at", -1):
            r["_id"] = str(r["_id"])
            if isinstance(r.get("created_at"), datetime):
                r["created_at"] = r["created_at"].isoformat()
            out.append(r)
        return out

    async def delete(self, reference_id: str, expert_id: str,
                     is_admin: bool) -> Dict[str, Any]:
        try:
            oid = ObjectId(reference_id)
        except InvalidId:
            return {"status": "error", "detail": "invalid id"}
        q: Dict[str, Any] = {"_id": oid}
        if not is_admin:
            q["expert_id"] = expert_id
        res = await self.db.expert_references.delete_one(q)
        if not res.deleted_count:
            return {"status": "error", "detail": "not found, or not yours"}
        return {"status": "deleted"}

    # ------------------------------------------------------------------ #
    # The third score
    # ------------------------------------------------------------------ #

    async def asserted_evidence(self, sf_number: int) -> Dict[str, Any]:
        """Aggregate expert-named references into the third score.

        Mapping (pre-registered, docs/09 §2.5): from **distinct supporting
        papers named by distinct experts**, net of opposing —
        1 = none or net-negative, 2 = one to two, 3 = three or more.

        Distinct experts matter for the same reason independence is counted by
        author group rather than by paper: one enthusiast naming five papers is
        not five experts agreeing.
        """
        sup_papers, opp_papers = set(), set()
        experts, papers = set(), set()
        misses = new_to_corpus = unknown = 0

        async for r in self.db.expert_references.find({"sf_number": sf_number}):
            papers.add(r["doi"])
            experts.add(r.get("expert_id"))
            if r.get("direction") == "supports":
                sup_papers.add((r["doi"], r.get("expert_id")))
            else:
                opp_papers.add((r["doi"], r.get("expert_id")))
            st = (r.get("resolution") or {}).get("status")
            if st == "in_corpus_not_retrieved":
                misses += 1
            elif st == "not_in_corpus":
                new_to_corpus += 1
            elif st == "in_corpus_retrieval_unknown":
                unknown += 1

        n_sup = len({d for d, _ in sup_papers})
        n_opp = len({d for d, _ in opp_papers})
        net = n_sup - n_opp
        score = 1 if net <= 0 else (2 if net <= 2 else 3)

        return {
            "n_supporting": n_sup,
            "n_opposing": n_opp,
            "n_distinct_experts": len([e for e in experts if e]),
            "n_distinct_papers": len(papers),
            "n_recall_misses": misses,
            "n_new_to_corpus": new_to_corpus,
            "n_retrieval_unknown": unknown,
            "score_1_3": score,
        }

    async def recall_summary(self) -> Dict[str, Any]:
        """Corpus-wide counts by resolution status.

        `in_corpus_not_retrieved` is the headline: every one is a paper the
        corpus held and retrieval failed to surface, named by an expert who
        knew it was relevant.
        """
        counts: Dict[str, int] = {}
        async for r in self.db.expert_references.find({}, {"resolution": 1}):
            st = (r.get("resolution") or {}).get("status", "pending")
            counts[st] = counts.get(st, 0) + 1
        total_checked = counts.get("in_corpus_not_retrieved", 0) + \
            counts.get("in_corpus_retrieved", 0)
        return {
            "by_status": counts,
            "recall_misses": counts.get("in_corpus_not_retrieved", 0),
            "checked_for_retrieval": total_checked,
            "miss_rate": (counts.get("in_corpus_not_retrieved", 0) / total_checked
                          if total_checked else None),
            "undetermined": counts.get("in_corpus_retrieval_unknown", 0),
        }
