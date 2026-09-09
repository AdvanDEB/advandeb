"""
tDEB persistence
================
Transport networks and per-user equation overrides, stored in the app MongoDB.

The upstream simulator kept networks in a process-local dict, so models were
shared between everyone and vanished on restart.  Here each model belongs to the
user who created it and survives a redeploy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.core.database import get_database
from app.tdeb.core import (
    EquationSet, TransportNetwork,
    extract_overrides, merge_overrides,
)

logger = logging.getLogger(__name__)

MODELS_COLLECTION = "tdeb_models"
EQUATIONS_COLLECTION = "tdeb_equations"

# Guard rails on a single stored model.  Well past any hand-built DEB network,
# but low enough that a scripted client cannot store something that would take
# minutes to integrate.
MAX_NODES = 200
MAX_EDGES = 400


class TDebModelNotFound(Exception):
    """Raised when a model id does not exist or is not visible to the caller."""


class TDebModelForbidden(Exception):
    """Raised when a caller may see a model but not perform this action on it."""


class TDebModelTooLarge(Exception):
    """Raised when a network exceeds the node/edge limits."""


def _oid(model_id: str) -> ObjectId:
    try:
        return ObjectId(model_id)
    except (InvalidId, TypeError) as exc:
        raise TDebModelNotFound(model_id) from exc


class TDebModelService:
    """CRUD for a user's stored transport networks."""

    def __init__(self):
        self.collection = get_database()[MODELS_COLLECTION]

    @staticmethod
    def _check_size(network: TransportNetwork) -> None:
        if len(network.nodes) > MAX_NODES:
            raise TDebModelTooLarge(
                f"Model has {len(network.nodes)} nodes; the limit is {MAX_NODES}."
            )
        if len(network.edges) > MAX_EDGES:
            raise TDebModelTooLarge(
                f"Model has {len(network.edges)} edges; the limit is {MAX_EDGES}."
            )

    @staticmethod
    def _to_summary(doc: dict, owner_email: Optional[str] = None) -> dict:
        network = doc.get("network") or {}
        published = doc.get("published")
        return {
            "id": str(doc["_id"]),
            "name": network.get("name") or "Untitled",
            "description": doc.get("description") or "",
            "n_nodes": len(network.get("nodes") or {}),
            "n_edges": len(network.get("edges") or {}),
            "template_id": doc.get("template_id"),
            "source": doc.get("source") or "template",
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "is_published": bool(published),
            "published_at": (published or {}).get("at"),
            "owner_email": owner_email,
        }

    async def _owner_emails(self, owner_ids) -> Dict[str, str]:
        """Map owner id -> email, for attributing published templates."""
        unique = {oid for oid in owner_ids if oid}
        if not unique:
            return {}
        object_ids = []
        for oid in unique:
            try:
                object_ids.append(ObjectId(oid))
            except (InvalidId, TypeError):
                continue
        if not object_ids:
            return {}
        cursor = get_database().users.find({"_id": {"$in": object_ids}}, {"email": 1})
        return {str(u["_id"]): u.get("email", "") async for u in cursor}

    async def list_models(self, user_id: str, limit: int = 100) -> List[dict]:
        """Every model owned by ``user_id``, newest first."""
        cursor = (
            self.collection.find({"owner_id": user_id})
            .sort("updated_at", -1)
            .limit(limit)
        )
        return [self._to_summary(doc) async for doc in cursor]

    async def create(self, user_id: str, network: TransportNetwork,
                     template_id: Optional[str] = None,
                     description: str = "",
                     source: str = "template") -> dict:
        """Persist a new network and return ``{id, network}``."""
        self._check_size(network)
        now = datetime.now(timezone.utc)
        doc = {
            "owner_id": user_id,
            "template_id": template_id,
            "description": description,
            "source": source,
            "network": network.to_dict(),
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(doc)
        return {"id": str(result.inserted_id), "network": doc["network"]}

    async def load(self, user_id: str, model_id: str) -> TransportNetwork:
        """
        Load a model as a live :class:`TransportNetwork`.

        The owner filter is part of the query rather than a check afterwards, so
        a guessed id reads as "not found" instead of leaking another user's model.
        """
        doc = await self.collection.find_one(
            {"_id": _oid(model_id), "owner_id": user_id}
        )
        if not doc:
            raise TDebModelNotFound(model_id)
        return TransportNetwork.from_dict(doc.get("network") or {})

    async def save(self, user_id: str, model_id: str, network: TransportNetwork) -> dict:
        """Overwrite the stored network; returns the serialized network."""
        self._check_size(network)
        payload = network.to_dict()
        result = await self.collection.update_one(
            {"_id": _oid(model_id), "owner_id": user_id},
            {"$set": {"network": payload, "updated_at": datetime.now(timezone.utc)}},
        )
        if result.matched_count == 0:
            raise TDebModelNotFound(model_id)
        return payload

    async def set_metadata(self, user_id: str, model_id: str, *,
                           name: Optional[str] = None,
                           description: Optional[str] = None) -> dict:
        """Rename a model and/or update its description."""
        updates: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if name is not None:
            updates["network.name"] = name
        if description is not None:
            updates["description"] = description

        result = await self.collection.update_one(
            {"_id": _oid(model_id), "owner_id": user_id}, {"$set": updates}
        )
        if result.matched_count == 0:
            raise TDebModelNotFound(model_id)
        doc = await self.collection.find_one({"_id": _oid(model_id)})
        return self._to_summary(doc)

    async def duplicate(self, user_id: str, model_id: str,
                        new_name: Optional[str] = None) -> dict:
        """
        Copy a model into ``user_id``'s library.

        The source may be the caller's own model or one published as an org
        template; anything else is invisible to them and reads as not found.
        """
        doc = await self.collection.find_one({
            "_id": _oid(model_id),
            "$or": [{"owner_id": user_id}, {"published": {"$ne": None}}],
        })
        if not doc:
            raise TDebModelNotFound(model_id)

        network = TransportNetwork.from_dict(doc.get("network") or {})
        network.name = new_name or f"{network.name} (copy)"

        return await self.create(
            user_id, network,
            template_id=doc.get("template_id"),
            description=doc.get("description") or "",
            # A copy is never itself published — publishing is a separate,
            # curator-only act on the copy.
            source="published" if doc.get("published") else "copy",
        )

    async def delete(self, user_id: str, model_id: str) -> None:
        result = await self.collection.delete_one(
            {"_id": _oid(model_id), "owner_id": user_id}
        )
        if result.deleted_count == 0:
            raise TDebModelNotFound(model_id)

    # ── Org-published templates ───────────────────────────────────────

    async def list_published(self) -> List[dict]:
        """Models published as org-wide starting templates, newest first."""
        docs = [d async for d in self.collection.find({"published": {"$ne": None}})
                .sort("published.at", -1).limit(200)]
        emails = await self._owner_emails([d.get("owner_id") for d in docs])
        return [self._to_summary(d, emails.get(d.get("owner_id"))) for d in docs]

    async def publish(self, user_id: str, model_id: str) -> dict:
        """
        Publish one of the caller's own models as an org-wide template.

        Callers must already have passed the curator check at the route; this
        additionally requires ownership, so a curator cannot publish someone
        else's private model out from under them.
        """
        doc = await self.collection.find_one({"_id": _oid(model_id)})
        if not doc:
            raise TDebModelNotFound(model_id)
        if doc.get("owner_id") != user_id:
            raise TDebModelForbidden(model_id)

        await self.collection.update_one(
            {"_id": _oid(model_id)},
            {"$set": {"published": {"at": datetime.now(timezone.utc), "by": user_id}}},
        )
        return self._to_summary(await self.collection.find_one({"_id": _oid(model_id)}))

    async def unpublish(self, user_id: str, model_id: str) -> dict:
        """Withdraw a published template. Existing copies are unaffected."""
        doc = await self.collection.find_one({"_id": _oid(model_id)})
        if not doc:
            raise TDebModelNotFound(model_id)
        if doc.get("owner_id") != user_id:
            raise TDebModelForbidden(model_id)

        await self.collection.update_one(
            {"_id": _oid(model_id)}, {"$set": {"published": None}}
        )
        return self._to_summary(await self.collection.find_one({"_id": _oid(model_id)}))


class TDebEquationService:
    """
    Per-user overrides of the simulator's formulas.

    Only the differences from the shipped defaults are stored, so improving a
    default formula later still reaches users who never edited that entry.
    """

    def __init__(self):
        self.collection = get_database()[EQUATIONS_COLLECTION]

    async def get_overrides(self, user_id: str) -> Dict[str, Any]:
        doc = await self.collection.find_one({"user_id": user_id})
        return (doc or {}).get("overrides") or {}

    async def get_resolved(self, user_id: str) -> Dict[str, Any]:
        """Defaults with this user's overrides layered on top."""
        return merge_overrides(await self.get_overrides(user_id))

    async def build_equation_set(self, user_id: str) -> EquationSet:
        """An :class:`EquationSet` ready to hand to the solver."""
        return EquationSet(await self.get_resolved(user_id))

    async def save_resolved(self, user_id: str, resolved: Dict[str, Any]) -> Dict[str, Any]:
        """Store the diff of ``resolved`` against defaults; returns the resolved set."""
        overrides = extract_overrides(resolved)
        await self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "overrides": overrides,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        return merge_overrides(overrides)

    async def reset(self, user_id: str) -> Dict[str, Any]:
        """Drop every override, returning the user to the shipped defaults."""
        await self.collection.delete_one({"user_id": user_id})
        return merge_overrides(None)


async def ensure_tdeb_indexes(app_db) -> None:
    """Create the tDEB collection indexes. Idempotent — safe on every startup."""
    await app_db[MODELS_COLLECTION].create_index(
        [("owner_id", 1), ("updated_at", -1)],
        background=True,
        name="tdeb_models_owner_updated",
    )
    # Serves the published-template listing, which filters on `published` and
    # sorts by when it was published.
    await app_db[MODELS_COLLECTION].create_index(
        [("published.at", -1)],
        background=True,
        sparse=True,
        name="tdeb_models_published_at",
    )
    await app_db[EQUATIONS_COLLECTION].create_index(
        "user_id", unique=True, background=True, name="tdeb_equations_user",
    )
    logger.info("ensure_tdeb_indexes: tDEB collection indexes verified/created")
