"""
EnrolmentService — self-signup with administrator approval.

The approval step exists for one reason: **tier assignment is a scientific
decision**, not an administrative one (advandeb_methods docs/10 section 5).
Who counts as a panel member determines what the agreement statistics are
agreement *over*, and that cannot be delegated to whoever fills in a form.

A request creates no account and grants nothing until it is approved.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.core.auth import get_password_hash
from app.core.database import get_database
from app.core.dependencies import CAP_SF_ELICITATION, ROLE_EXTERNAL_CONTRIBUTOR
from app.models.enrolment import EnrolmentDecision, EnrolmentRequest

logger = logging.getLogger(__name__)


def _norm_name(name: str) -> str:
    """Loose name key for conflict matching: lowercase, no accents-as-letters,
    no punctuation, sorted tokens so 'Klanjšček, Tin' meets 'Tin Klanjšček'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    toks = sorted(t for t in re.split(r"[^a-z]+", s) if len(t) > 1)
    return " ".join(toks)


def _norm_orcid(orcid: Optional[str]) -> str:
    return re.sub(r"[^0-9X]", "", (orcid or "").upper())


class EnrolmentService:
    def __init__(self) -> None:
        self.db = get_database()

    # ------------------------------------------------------------------ #
    # Request
    # ------------------------------------------------------------------ #

    async def submit_request(self, req: EnrolmentRequest) -> Dict[str, Any]:
        """Record a request. Public endpoint — deliberately says little.

        Returns the same shape whether or not the email is already known, so
        the endpoint cannot be used to enumerate who is already enrolled.
        """
        email = req.email.lower().strip()
        existing_user = await self.db.users.find_one({"email": email})
        existing_req = await self.db.enrolment_requests.find_one(
            {"email": email, "status": "pending"})
        if existing_user or existing_req:
            return {"status": "pending"}

        doc = {
            "name": req.name.strip(),
            "email": email,
            "affiliation": (req.affiliation or "").strip() or None,
            "orcid": (req.orcid or "").strip() or None,
            "years_in_field": req.years_in_field,
            "deb_experience": (req.deb_experience or "").strip() or None,
            # clamp to the documented 1-5 range rather than trusting the client
            "category_familiarity": {
                str(k): max(1, min(5, int(v)))
                for k, v in (req.category_familiarity or {}).items()
                if str(v).lstrip("-").isdigit()
            },
            "consent": bool(req.consent),
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
        }
        await self.db.enrolment_requests.insert_one(doc)
        logger.info("enrolment request recorded for %s", email)
        return {"status": "pending"}

    # ------------------------------------------------------------------ #
    # Conflict of interest
    # ------------------------------------------------------------------ #

    async def match_authored(self, name: str,
                             orcid: Optional[str]) -> List[int]:
        """Stylized facts this person authored — ORCID first, then name.

        An outsider's conflict is no less a conflict (docs/10 section 5.1).
        Several likely contributors authored facts: the workshop participants
        acknowledged in the predecessor review among them.
        """
        return (await self._match(name, orcid))[0]

    async def match_author_slugs(self, name: str,
                                 orcid: Optional[str]) -> List[str]:
        """The `authored_by` values this person answers to.

        Recorded on the user as `author_slugs` at approval, because the queue
        names authors by slug and the slug is what its exclusion compares.
        A group slug such as `advandeb_workshop_2025` never matches a person's
        name here; mapping workshop participants to it is an administrator's
        decision (scripts/map_author_slugs.py).
        """
        return (await self._match(name, orcid))[1]

    async def _match(self, name: str,
                     orcid: Optional[str]) -> tuple[List[int], List[str]]:
        want_orcid = _norm_orcid(orcid)
        want_name = _norm_name(name)
        hits: List[int] = []
        slugs: set = set()
        async for f in self.db.stylized_facts.find(
                {"authored_by": {"$exists": True, "$ne": []}},
                {"sf_number": 1, "authored_by": 1}):
            for a in f.get("authored_by") or []:
                a = str(a)
                if ((want_orcid and _norm_orcid(a) == want_orcid)
                        or (want_name
                            and _norm_name(a.replace("_", " ")) == want_name)):
                    hits.append(int(f["sf_number"]))
                    slugs.add(a)
                    break
        return sorted(set(hits)), sorted(slugs)

    # ------------------------------------------------------------------ #
    # Review
    # ------------------------------------------------------------------ #

    async def list_requests(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        q = {"status": status} if status else {}
        out = []
        async for r in self.db.enrolment_requests.find(q).sort("created_at", -1):
            r["_id"] = str(r["_id"])
            # Surface the conflict the queue will have to exclude, so the
            # administrator sees it at the moment of the decision.
            if r.get("status") == "pending" and "matched_authored_sf_numbers" not in r:
                r["matched_authored_sf_numbers"] = await self.match_authored(
                    r.get("name", ""), r.get("orcid"))
            out.append(r)
        return out

    async def decide(self, request_id: str, decision: EnrolmentDecision,
                     admin_id: str) -> Dict[str, Any]:
        """Approve at a tier, or decline. Creates the account on approval."""
        try:
            oid = ObjectId(request_id)
        except InvalidId:
            return {"status": "error", "detail": "invalid request id"}
        req = await self.db.enrolment_requests.find_one({"_id": oid})
        if not req:
            return {"status": "error", "detail": "request not found"}
        if req.get("status") != "pending":
            return {"status": "error",
                    "detail": f"already {req.get('status')}"}

        now = datetime.now(timezone.utc)

        if not decision.approve:
            await self.db.enrolment_requests.update_one(
                {"_id": oid},
                {"$set": {"status": "declined", "decided_at": now,
                          "decided_by": admin_id, "note": decision.note}})
            return {"status": "declined"}

        if decision.tier not in ("panel", "contributor"):
            return {"status": "error",
                    "detail": "approving requires a tier: panel or contributor"}

        authored, author_slugs = await self._match(
            req.get("name", ""), req.get("orcid"))

        existing = await self.db.users.find_one({"email": req["email"]})
        if existing:
            user_id = str(existing["_id"])
            await self.db.users.update_one(
                {"_id": existing["_id"]},
                {"$set": {"tier": decision.tier,
                          "approval": {"by": admin_id, "at": now,
                                       "tier": decision.tier},
                          "authored_sf_numbers": authored,
                          "updated_at": now},
                 "$addToSet": {"capabilities": CAP_SF_ELICITATION,
                               "author_slugs": {"$each": author_slugs}}})
        else:
            # A one-time password the administrator passes on; the account is
            # created only now, never at request time.
            temp_password = secrets.token_urlsafe(12)
            doc = {
                "email": req["email"],
                "full_name": req.get("name"),
                "password_hash": get_password_hash(temp_password),
                # Minimum privilege: the elicitation capability and nothing
                # else. Every existing role implies read access to curated
                # material, some of it licensed full text, so the external role
                # is defined by what it excludes (docs/10 section 4.1).
                "roles": [ROLE_EXTERNAL_CONTRIBUTOR]
                if decision.tier == "contributor" else ["knowledge_explorator"],
                "capabilities": [CAP_SF_ELICITATION],
                "status": "active",
                "tier": decision.tier,
                "expertise_profile": {
                    "affiliation": req.get("affiliation"),
                    "orcid": req.get("orcid"),
                    "years_in_field": req.get("years_in_field"),
                    "deb_experience": req.get("deb_experience"),
                    "category_familiarity": req.get("category_familiarity") or {},
                    "consent_acknowledgement": bool(req.get("consent")),
                },
                "approval": {"by": admin_id, "at": now, "tier": decision.tier},
                "authored_sf_numbers": authored,
                "author_slugs": author_slugs,
                "chat_history_visible_to_admin": True,
                "created_at": now,
                "updated_at": now,
            }
            res = await self.db.users.insert_one(doc)
            user_id = str(res.inserted_id)

        await self.db.enrolment_requests.update_one(
            {"_id": oid},
            {"$set": {"status": "approved", "decided_at": now,
                      "decided_by": admin_id, "assigned_tier": decision.tier,
                      "matched_authored_sf_numbers": authored,
                      "user_id": user_id, "note": decision.note}})
        logger.info("enrolment approved: %s as %s (%d authored facts)",
                    req["email"], decision.tier, len(authored))
        return {"status": "approved", "tier": decision.tier,
                "user_id": user_id,
                "matched_authored_sf_numbers": authored,
                "temp_password": temp_password if not existing else None}
