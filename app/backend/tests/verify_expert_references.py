#!/usr/bin/env python
"""Exercise every resolution outcome for expert-asserted references.

The outcome classification is the whole feature, and `in_corpus_not_retrieved`
is both the one that matters and the one easiest to get subtly wrong — a false
positive manufactures a retrieval-recall failure that was never tested for, and
that figure is reported in the paper.

Runs against a scratch database with fixtures; external DOI resolution is
stubbed so the test is deterministic and offline.

    conda run -n advandeb python tests/verify_expert_references.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from types import SimpleNamespace

# Assigned, never setdefault: this script drops `documents` and
# `stylized_facts`, and setdefault is a no-op once .env has exported
# MONGODB_DB_NAME=advandeb — the exact mistake behind the production data loss.
os.environ["MONGODB_DB_NAME"] = "advandeb_expertref_scratch"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import (  # noqa: E402
    close_mongo_connection, connect_to_mongo, get_database,
)
from app.core.dbguard import assert_not_production  # noqa: E402
from app.services import expert_reference_service as mod  # noqa: E402
from app.services.expert_reference_service import (  # noqa: E402
    ExpertReferenceService, normalise_doi,
)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  — {detail}" if detail else ""))


def ref(sf_number: int, doi: str, direction: str = "supports"):
    return SimpleNamespace(sf_number=sf_number, statement_sha256="h" * 8,
                           doi=doi, direction=direction, note=None)


async def main() -> int:
    await connect_to_mongo()
    db = get_database()
    # Check the handle actually in use, not the variable we hoped would apply.
    assert_not_production(db.name, "dropping fixture collections")
    for c in ("expert_references", "documents", "stylized_facts"):
        await db[c].drop()

    # --- fixtures ---------------------------------------------------- #
    # A fact whose evidence set we control, and one with no evidence set.
    await db.stylized_facts.insert_many([
        {"sf_number": 9001, "statement": "Fixture fact with evidence.",
         "legacy_sf_id": "fixture_01"},
        {"sf_number": 9002, "statement": "Fixture fact without evidence.",
         "legacy_sf_id": "fixture_missing"},
    ])
    # A document in the app corpus, carrying a DOI.
    ins = await db.documents.insert_one(
        {"doi": "10.1000/retrieved", "title": "Seen by the panel"})
    retrieved_id = str(ins.inserted_id)
    ins2 = await db.documents.insert_one(
        {"doi": "10.1000/missed", "title": "Held but never surfaced"})
    missed_id = str(ins2.inserted_id)

    # An evidence-set artefact whose `reproduction` scope cites one of them.
    tmp = tempfile.mkdtemp()
    artefact = {
        "sf_id": "fixture_01",
        "statement": "Fixture fact with evidence.",
        "judges": {"claude": {"scopes": {"reproduction": {"snippets": [
            {"document_id": retrieved_id, "label": "supports",
             "relevance": 0.9, "title": "Seen by the panel"},
            {"document_id": "someone-else", "label": "neutral",
             "relevance": 0.2, "title": "Other"},
        ]}}}},
    }
    with open(os.path.join(tmp, "fixture_01.json"), "w") as f:
        json.dump(artefact, f)
    mod.EVIDENCE_DIR = tmp

    svc = ExpertReferenceService()

    # Deterministic, offline resolution. `10.1000/dead` never resolves.
    async def fake_meta(doi):
        if doi == "10.1000/dead":
            return None
        return {"title": f"T({doi})", "year": 2020, "openalex_id": None,
                "source": "stub"}
    svc.resolve_metadata = fake_meta

    # The fixture documents live in the app corpus; force the corpus lookup to
    # report them as `reproduction` so the evidence set is comparable, which is
    # the only combination where a retrieval verdict is legitimate.
    real_find = svc.find_in_corpus

    async def find(doi, oaid):
        got = await real_find(doi, oaid)
        if got:
            got["corpus"] = "reproduction"
        return got
    svc.find_in_corpus = find

    print("\n--- normalisation ---")
    check("strips https://doi.org/", normalise_doi("https://doi.org/10.1/AB") == "10.1/ab")
    check("strips doi: prefix", normalise_doi("doi: 10.1/AB") == "10.1/ab")

    print("\n--- the four outcomes ---")

    r = await svc.add(ref(9001, "10.1000/dead"), "expert_a", "panel")
    check("unresolvable DOI is rejected, not stored",
          r["status"] == "error", r.get("detail", ""))
    check("nothing persisted for a dead DOI",
          await db.expert_references.count_documents({}) == 0)

    r = await svc.add(ref(9001, "10.1000/absent"), "expert_a", "panel")
    st = r["reference"]["resolution"]["status"]
    check("absent from corpus -> not_in_corpus", st == "not_in_corpus", st)
    check("absent paper is queued for ingestion",
          r["reference"]["ingestion_queued"] is True)
    check("ingestion triggers re-adjudication",
          r["reference"]["triggered_readjudication"] is True)

    r = await svc.add(ref(9001, "10.1000/retrieved"), "expert_a", "panel")
    res = r["reference"]["resolution"]
    check("held and surfaced -> in_corpus_retrieved",
          res["status"] == "in_corpus_retrieved", res["status"])
    check("panel labels recorded for comparison",
          bool(res.get("panel_labels")))
    check("agreement with panel computed",
          res.get("agrees_with_panel") is True)

    # THE one that matters.
    r = await svc.add(ref(9001, "10.1000/missed"), "expert_b", "panel")
    res = r["reference"]["resolution"]
    check("held but never surfaced -> in_corpus_not_retrieved  [RECALL MISS]",
          res["status"] == "in_corpus_not_retrieved", res["status"])
    check("recall miss is an exact check, not a guess",
          res.get("retrieval_check") == "exact", str(res.get("retrieval_check")))
    check("a recall miss is NOT queued for ingestion (we already hold it)",
          not r["reference"]["ingestion_queued"])

    print("\n--- undetermined cases are named, never absorbed ---")
    r = await svc.add(ref(9002, "10.1000/retrieved"), "expert_a", "panel")
    res = r["reference"]["resolution"]
    check("no evidence set -> in_corpus_retrieval_unknown",
          res["status"] == "in_corpus_retrieval_unknown", res["status"])
    check("reason recorded as no_evidence_set",
          res.get("retrieval_check") == "no_evidence_set")

    # DEB-scope corpora carry no DOI; a verdict there would be fabricated.
    svc.find_in_corpus = real_find
    chk = svc.check_retrieval(artefact, "app", "not-in-this-set")
    check("corpus without DOIs -> retrieval undetermined, not 'missed'",
          chk["retrieved"] is None and chk["check"] == "corpus_lacks_doi",
          str(chk))

    print("\n--- duplicate guard ---")
    r = await svc.add(ref(9001, "10.1000/missed"), "expert_b", "panel")
    check("same expert cannot cite the same DOI twice for a fact",
          r["status"] == "error")

    print("\n--- the third score ---")
    ev = await svc.asserted_evidence(9001)
    check("counts distinct supporting papers",
          ev["n_supporting"] == 3, str(ev))
    check("counts distinct experts", ev["n_distinct_experts"] == 2, str(ev))
    check("recall misses surfaced in the score", ev["n_recall_misses"] == 1)
    check("new-to-corpus surfaced in the score", ev["n_new_to_corpus"] == 1)
    check("3+ distinct supporting papers -> score 3", ev["score_1_3"] == 3,
          str(ev["score_1_3"]))

    await svc.add(ref(9001, "10.1000/against1", "opposes"), "expert_c", "panel")
    await svc.add(ref(9001, "10.1000/against2", "opposes"), "expert_c", "panel")
    await svc.add(ref(9001, "10.1000/against3", "opposes"), "expert_c", "panel")
    ev = await svc.asserted_evidence(9001)
    check("opposing papers net off supporting ones",
          ev["n_opposing"] == 3 and ev["score_1_3"] == 1,
          f"net={ev['n_supporting'] - ev['n_opposing']} score={ev['score_1_3']}")

    print("\n--- tier is stamped at write time ---")
    r = await svc.add(ref(9001, "10.1000/contrib"), "expert_d", "contributor")
    check("contributor tier stamped on the record",
          r["reference"]["tier"] == "contributor")

    print("\n--- recall summary ---")
    s = await svc.recall_summary()
    check("recall misses counted corpus-wide", s["recall_misses"] == 1, str(s))
    check("miss rate computed over checked items only",
          s["checked_for_retrieval"] == 2
          and abs(s["miss_rate"] - 0.5) < 1e-9, str(s))
    check("undetermined reported separately from misses",
          s["undetermined"] >= 1, str(s))

    print("\n--- deletion ---")
    one = await db.expert_references.find_one({"expert_id": "expert_b"})
    d = await svc.delete(str(one["_id"]), "expert_a", is_admin=False)
    check("cannot delete another expert's reference", d["status"] == "error")
    d = await svc.delete(str(one["_id"]), "expert_b", is_admin=False)
    check("can delete your own", d["status"] == "deleted")

    for c in ("expert_references", "documents", "stylized_facts"):
        await db[c].drop()
    await close_mongo_connection()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
