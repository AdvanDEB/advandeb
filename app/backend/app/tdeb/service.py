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
    """Raised when a model id does not exist or is not owned by the caller."""


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
    def _to_summary(doc: dict) -> dict:
        network = doc.get("network") or {}
        return {
            "id": str(doc["_id"]),
            "name": network.get("name") or "Untitled",
            "n_nodes": len(network.get("nodes") or {}),
            "n_edges": len(network.get("edges") or {}),
            "template_id": doc.get("template_id"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
        }

    async def list_models(self, user_id: str, limit: int = 100) -> List[dict]:
        """Every model owned by ``user_id``, newest first."""
        cursor = (
            self.collection.find({"owner_id": user_id})
            .sort("updated_at", -1)
            .limit(limit)
        )
        return [self._to_summary(doc) async for doc in cursor]

    async def create(self, user_id: str, network: TransportNetwork,
                     template_id: Optional[str] = None) -> dict:
        """Persist a new network and return ``{id, network}``."""
        self._check_size(network)
        now = datetime.now(timezone.utc)
        doc = {
            "owner_id": user_id,
            "template_id": template_id,
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

    async def delete(self, user_id: str, model_id: str) -> None:
        result = await self.collection.delete_one(
            {"_id": _oid(model_id), "owner_id": user_id}
        )
        if result.deleted_count == 0:
            raise TDebModelNotFound(model_id)


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
    await app_db[EQUATIONS_COLLECTION].create_index(
        "user_id", unique=True, background=True, name="tdeb_equations_user",
    )
    logger.info("ensure_tdeb_indexes: tDEB collection indexes verified/created")
