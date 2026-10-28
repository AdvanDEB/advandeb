"""Builders for the elicitation tests: facts, experts, evidence sets, and a
valid decision for whatever item the queue serves.

Kept small and explicit. Each test states the population it needs, because
most of what is being tested is a property of that population — who authored
what, who is panel, which evidence set a fact has.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from bson import ObjectId

from app.models.elicitation import (
    ElicitationDecision, PassageJudgment, QueueItem,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def fact(n: int, category: str = "growth", authored_by: Sequence[str] = (),
         provenance: Optional[str] = None) -> Dict:
    statement = f"Stylized fact {n} in {category}."
    return {
        "sf_number": n, "statement": statement, "category": category,
        "statement_sha256": sha(statement), "authored_by": list(authored_by),
        "provenance_type": provenance, "source_citation": None,
        "legacy_assessment": None, "status": "published",
    }


async def seed_facts(db, facts: Iterable[Dict]) -> List[Dict]:
    docs = list(facts)
    if docs:
        await db.stylized_facts.insert_many([dict(d) for d in docs])
    return docs


def collection(sizes: Dict[str, int], start: int = 1) -> List[Dict]:
    """A synthetic collection with the given facts per category."""
    out, n = [], start
    for cat, size in sizes.items():
        for _ in range(size):
            out.append(fact(n, cat))
            n += 1
    return out


async def expert(db, tier: Optional[str] = "panel", slugs: Sequence[str] = (),
                 authored: Sequence[int] = (), roles: Sequence[str] = (
                     "knowledge_explorator",),
                 name: str = "expert") -> str:
    doc = {"email": f"{name}-{ObjectId()}@example.org", "full_name": name,
           "roles": list(roles), "capabilities": ["sf_elicitation"],
           "author_slugs": list(slugs),
           "authored_sf_numbers": list(authored)}
    if tier is not None:
        doc["tier"] = tier
    return str((await db.users.insert_one(doc)).inserted_id)


async def calibration_set(db, n: int = 1) -> List[str]:
    ids = []
    for i in range(n):
        cid = f"cal_test_{i}"
        await db.elicitation_calibration.insert_one({
            "calibration_id": cid, "order": i, "task": "provenance",
            "sf_number": 9000 + i, "statement": f"calibration {i}",
            "statement_sha256": sha(f"calibration {i}"), "category": "growth",
            "reference": {"provenance_type": "published"},
            "explanation": "documented", "reference_basis": "test"})
        ids.append(cid)
    return ids


async def calibrate(db, *expert_ids: str) -> None:
    """Mark experts as having finished the calibration set (seeding one if
    none exists), so the server-side gate opens for them."""
    ids = [c["calibration_id"] async for c in db.elicitation_calibration.find()]
    if not ids:
        ids = await calibration_set(db)
    for e in expert_ids:
        for cid in ids:
            await db.elicitation_calibration_results.update_one(
                {"expert_id": e, "calibration_id": cid},
                {"$set": {"expert_id": e, "calibration_id": cid,
                          "correct": True,
                          "created_at": datetime.now(timezone.utc)}},
                upsert=True)


def evidence_set(f: Dict, corpus: str, n_passages: int = 18) -> Dict:
    passages = [{"index": i, "text": f"passage {i} on fact {f['sf_number']}",
                 "similarity": round(0.9 - i * 0.01, 3), "doi": f"10.1/{i}",
                 "title": f"Paper {i}", "year": 2000 + i,
                 "document_id": f"doc{i}"} for i in range(n_passages)]
    content = "|".join(p["text"] for p in passages)
    return {"evidence_set_id": f"{f['sf_number']}:{corpus}",
            "sf_candidate_id": f"cand_{f['sf_number']}",
            "sf_number": f["sf_number"], "statement": f["statement"],
            "statement_sha256": f["statement_sha256"],
            "category": f["category"], "corpus_id": corpus,
            "content_hash": sha(content), "n_passages": n_passages,
            "embedding_model": "test", "passages": passages}


def evidence_artefact(facts: Iterable[Dict],
                      corpora: Sequence[str] = ("deb", "reproduction"),
                      n_passages: int = 18) -> Dict:
    return {"manifest": {"version": "test"},
            "sets": [evidence_set(f, c, n_passages)
                     for f in facts for c in corpora]}


def decision_for(item: QueueItem, **over) -> ElicitationDecision:
    """A complete, valid decision for whatever item was served."""
    base = dict(task=item.task, sf_number=item.sf_number,
                statement_sha256=item.statement_sha256,
                confidence=3, rationale="because", time_spent_s=12.0)
    if item.task == "provenance":
        base.update(provenance_type="unknown")
    elif item.task == "scope":
        base.update(scope_verdict="absent")
    elif item.task == "assessability":
        base.update(assessability="assessable")
    else:
        base.update(
            corpus_id=item.corpus_id, evidence_set_id=item.evidence_set_id,
            evidence_content_hash=item.evidence_content_hash,
            evidence_strength=2, consensus_direction=3,
            passage_judgments={
                str(p.index): PassageJudgment(
                    direction="supports" if p.index == 0 else "neutral",
                    evidential_role="primary_evidence" if p.index == 0 else None)
                for p in item.passages})
    base.update(over)
    return ElicitationDecision(**base)
