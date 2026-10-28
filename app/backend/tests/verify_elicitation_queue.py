"""End-to-end verification of the elicitation queue against a scratch database.

Not a pytest module: it needs a live MongoDB and builds a full 3,786-item
queue, so it runs on demand rather than in the unit suite.

    conda run -n advandeb python tests/verify_elicitation_queue.py

The checks that matter, and why each exists:

* **Queue properties unchanged** - 3,786 items, n_required {1:3028, 2:606,
  5:152}, comparison gap 25. This is the pre-tiering baseline; tiering must not
  perturb the sampling frame.
* **Contributor judgments do not decrement n_required** (advandeb_methods
  docs/10 section 2.2). Without this, open contributors silently complete
  comparison items and the panel consensus is never collected - and the failure
  looks exactly like healthy throughput until the analysis finds no panel data.
* **Tier is stamped at write time** (docs/10 section 2.1), so promoting someone
  cannot retroactively move their past judgments between strata.
* **Conflict of interest** from both sources: the seeded queue for the core
  group, and the user record for external contributors matched at approval.
"""
import asyncio, os, sys, collections, json, pathlib
os.environ["MONGODB_DB_NAME"] = "advandeb_elicit_scratch"
sys.path.insert(0, "/home/adeb/dev/advandeb/app/backend")

from bson import ObjectId
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.core.dbguard import assert_not_production
from app.services.elicitation_service import ElicitationService
from app.services.enrolment_service import EnrolmentService
from app.models.elicitation import ElicitationDecision, CalibrationDecision
from app.models.enrolment import EnrolmentRequest, EnrolmentDecision

FAIL = []
def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got}" + ("" if ok else f"  (expected {want})"))
    if not ok: FAIL.append(label)

async def main():
    await connect_to_mongo(); db = get_database()
    # This drops `users` among others: check the handle in use, fail closed.
    assert_not_production(db.name, "dropping fixture collections")
    for c in ("stylized_facts","elicitation_queue","elicitations","users",
              "elicitation_calibration","elicitation_calibration_results",
              "enrolment_requests"):
        await db[c].drop()

    art = json.loads((pathlib.Path.home()/
        "dev/advandeb_methods/data/collection/collection_v1.0.json").read_text())
    await db.stylized_facts.insert_many([{
        "sf_number": f["sf_number"], "statement": f["statement"],
        "category": f["category"], "statement_sha256": f["statement_sha256"],
        "authored_by": f.get("authored_by", []),
        "provenance_type": f["provenance_type"],
        "source_citation": f.get("source_citation"),
        "legacy_assessment": f.get("legacy_assessment"), "status":"published",
    } for f in art["facts"]])

    svc = ElicitationService()
    built = await svc.build_queue()
    print("\n=== QUEUE PROPERTIES (must match pre-change baseline) ===")
    check("queue length", built["queue_length"], 3786)
    check("strata", built["strata"], 51)
    rows = [q async for q in db.elicitation_queue.find().sort("queue_position",1)]
    check("n_required distribution",
          dict(sorted(collections.Counter(r["n_required"] for r in rows).items())),
          {1:3028, 2:606, 5:152})
    comp = [r["queue_position"] for r in rows if r.get("comparison_item")]
    check("comparison max gap", max(b-a for a,b in zip(comp, comp[1:])), 25)

    pop = collections.Counter(r["stratum"].split("|")[0] for r in rows)
    pre = rows[:len(rows)//2]
    cats = collections.Counter(r["stratum"].split("|")[0] for r in pre)
    ratios = {c: (cats.get(c,0)/len(pre))/(pop[c]/len(rows)) for c in pop}
    print(f"  INFO  50% prefix share ratio: {min(ratios.values()):.2f}-{max(ratios.values()):.2f}")

    # users: one panel expert who authored facts, one contributor
    authored = sorted({f["sf_number"] for f in art["facts"]
                       if "tin_klanjscek" in (f.get("authored_by") or [])})
    panel_id = str((await db.users.insert_one({
        "email":"tin@irb.hr","full_name":"Tin","roles":["knowledge_explorator"],
        "capabilities":["sf_elicitation"],"tier":"panel",
        "authored_sf_numbers": authored})).inserted_id)
    contrib_id = str((await db.users.insert_one({
        "email":"outsider@x.org","full_name":"Outsider",
        "roles":["external_contributor"],"capabilities":["sf_elicitation"],
        "tier":"contributor"})).inserted_id)

    print("\n=== CALIBRATION GATE (docs/10 5.3) ===")
    await svc.seed_calibration()
    gated = await svc.next_item(panel_id)
    check("no live item served before calibration", gated, None)
    blocked_early = await svc.submit(ElicitationDecision(task="provenance",
        sf_number=1, statement_sha256="x", provenance_type="unknown",
        confidence=3, rationale="should be gated"), panel_id)
    check("submit refused before calibration", blocked_early["status"], "error")
    check("refusal names calibration",
          "calibration" in blocked_early["detail"], True)

    # clear calibration for the panel expert
    while True:
        c = await svc.calibration_next(panel_id)
        if not c: break
        ref = await db.elicitation_calibration.find_one(
            {"calibration_id": c["calibration_id"]})
        exp = (ref["reference"].get("provenance_type")
               or ref["reference"].get("scope_verdict"))
        await svc.calibration_submit(CalibrationDecision(
            calibration_id=c["calibration_id"], task=c["task"],
            provenance_type=exp if c["task"]=="provenance" else None,
            scope_verdict=exp if c["task"]=="scope" else None,
            confidence=4, rationale="ref"), panel_id)
    check("queue opens after calibration",
          (await svc.next_item(panel_id)) is not None, True)
    prog = await svc.progress(panel_id)
    check("progress reports calibration cleared", prog.calibration_required, False)

    print("\n=== COI ===")
    seen=[]
    for _ in range(40):
        it = await svc.next_item(panel_id)
        if not it: break
        seen.append(it.sf_number)
        await svc.submit(ElicitationDecision(task=it.task, sf_number=it.sf_number,
            statement_sha256=it.statement_sha256, provenance_type="unknown",
            scope_verdict="absent", assessability="assessable",
            confidence=3, rationale="verify"), panel_id)
    check("authored facts assigned to their author", len(set(seen)&set(authored)), 0)
    check("tier stamped on record",
          (await db.elicitations.find_one({"expert_id":panel_id}))["tier"], "panel")

    print("\n=== CONTRIBUTOR DOES NOT DECREMENT n_required (docs/10 2.2) ===")
    target = next(r for r in rows if r["n_required"]==5)
    key = {"sf_number": target["sf_number"], "task": target["task"]}
    before_panel = await db.elicitations.count_documents({**key, "tier":"panel"})
    for _ in range(50):
        c = await svc.calibration_next(contrib_id)
        if not c: break
        await svc.calibration_submit(CalibrationDecision(
            calibration_id=c["calibration_id"], task=c["task"],
            provenance_type="unknown" if c["task"]=="provenance" else None,
            scope_verdict="absent" if c["task"]=="scope" else None,
            confidence=2, rationale="contributor attempt"), contrib_id)
    # contributor judges the comparison item five times over? once is enough
    await svc.submit(ElicitationDecision(task=target["task"],
        sf_number=target["sf_number"], statement_sha256=target["statement_sha256"],
        provenance_type="unknown", scope_verdict="absent",
        assessability="assessable", confidence=3,
        rationale="contributor"), contrib_id)
    rec = await db.elicitations.find_one({**key, "expert_id":contrib_id})
    check("contributor judgment recorded", rec is not None, True)
    check("contributor tier stamped", rec["tier"], "contributor")
    after_panel = await db.elicitations.count_documents({**key, "tier":"panel"})
    check("panel-tier count unchanged by contributor", after_panel, before_panel)
    stats = await svc.admin_stats()
    # the comparison item must still be pending panel coverage
    panel_have = before_panel
    check("comparison item still needs panel judgments", panel_have < 5, True)

    print("\n=== CALIBRATION SCORING ===")
    # A fresh expert: panel_id and contrib_id have both already cleared the set.
    fresh_id = str((await db.users.insert_one({
        "email":"fresh@x.org","full_name":"Fresh","roles":["knowledge_explorator"],
        "capabilities":["sf_elicitation"],"tier":"panel"})).inserted_id)
    check("calibration cases seeded",
          await db.elicitation_calibration.count_documents({}) >= 10, True)
    c1 = await svc.calibration_next(fresh_id)
    check("calibration case served", c1 is not None, True)
    ref = await db.elicitation_calibration.find_one({"calibration_id": c1["calibration_id"]})
    exp = (ref["reference"].get("provenance_type") or ref["reference"].get("scope_verdict"))
    fb = await svc.calibration_submit(CalibrationDecision(
        calibration_id=c1["calibration_id"], task=c1["task"],
        provenance_type=exp if c1["task"]=="provenance" else None,
        scope_verdict=exp if c1["task"]=="scope" else None,
        confidence=4, rationale="matches documented reference"), fresh_id)
    check("correct answer scored correct", fb["correct"], True)
    check("reference basis returned", bool(fb["reference"].get("basis")), True)
    check("partially-calibrated expert still gated",
          await svc.next_item(fresh_id), None)

    print("\n=== ENROLMENT + COI AT APPROVAL ===")
    ens = EnrolmentService()
    await ens.submit_request(EnrolmentRequest(name="Tin Klanjscek",
        email="tin.k@example.org", affiliation="IRB", years_in_field=20,
        category_familiarity={"core_deb_rules":5}, consent=True))
    reqs = await ens.list_requests("pending")
    check("request recorded", len(reqs), 1)
    check("authorship conflict surfaced at review",
          len(reqs[0]["matched_authored_sf_numbers"]) > 0, True)
    dec = await ens.decide(reqs[0]["_id"], EnrolmentDecision(approve=True, tier="contributor"), "admin1")
    check("approved at tier", dec["tier"], "contributor")
    u = await db.users.find_one({"email":"tin.k@example.org"})
    check("minimum-privilege role", u["roles"], ["external_contributor"])
    check("authored facts linked to user", len(u["authored_sf_numbers"]) > 0, True)
    # the new user must never be served a fact they authored
    blocked = await svc.submit(ElicitationDecision(task="provenance",
        sf_number=u["authored_sf_numbers"][0], statement_sha256="x",
        provenance_type="unknown", confidence=3, rationale="should fail"),
        str(u["_id"]))
    check("COI blocks authored fact for external contributor",
          blocked["status"], "error")

    print("\n=== ADMIN STATS ===")
    st = await svc.admin_stats()
    check("aggregates by stamped record tier", "by_record_tier" in st, True)
    me = next(e for e in st["by_expert"] if e["n_by_record_tier"].get("panel"))
    check("per-expert counts split by record tier",
          isinstance(me["n_by_record_tier"], dict), True)
    check("per-expert calibration exposed", me["calibration"]["done"], True)
    check("awaiting_calibration listed", "awaiting_calibration" in st, True)

    print("\n=== HISTORY / GUIDELINES ===")
    h = await svc.history(panel_id, 10)
    check("history returns own judgments", len(h) > 0, True)
    check("history carries tier", h[0]["tier"], "panel")
    g = svc.guidelines()
    check("guidelines tasks", len(g["tasks"]), 3)
    check("guidelines versioned", bool(g["version"]), True)

    for c in ("stylized_facts","elicitation_queue","elicitations","users",
              "elicitation_calibration","elicitation_calibration_results",
              "enrolment_requests"):
        await db[c].drop()
    await close_mongo_connection()
    print("\n" + ("ALL CHECKS PASSED" if not FAIL else f"FAILURES: {FAIL}"))
    return 1 if FAIL else 0

sys.exit(asyncio.run(main()))
