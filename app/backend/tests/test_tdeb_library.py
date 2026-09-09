"""
Authorization tests for the tDEB model library.

The interesting rules are all about who may see and act on whose models, so
these drive TDebModelService against a mocked collection rather than a live
MongoDB: what matters is the *query* each method issues, since that — not a
post-hoc check — is what enforces ownership.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tdeb.service import (  # noqa: E402
    TDebModelForbidden, TDebModelNotFound, TDebModelService,
)


def _service(collection):
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    with patch("app.tdeb.service.get_database", return_value=db):
        return TDebModelService()


def _model_doc(owner_id="user-1", published=None, name="Model"):
    return {
        "_id": ObjectId(),
        "owner_id": owner_id,
        "description": "",
        "published": published,
        "network": {"name": name, "nodes": {}, "edges": {}},
    }


@pytest.mark.asyncio
async def test_load_filters_by_owner_in_the_query():
    """
    Ownership must be part of the lookup, not a check afterwards.

    A post-hoc check would still have fetched the document; filtering in the
    query is what makes another user's id read as simply absent.
    """
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    service = _service(collection)

    with pytest.raises(TDebModelNotFound):
        await service.load("user-2", str(ObjectId()))

    query = collection.find_one.call_args[0][0]
    assert query["owner_id"] == "user-2"


@pytest.mark.asyncio
async def test_malformed_id_reads_as_not_found():
    """A junk id must not surface as a 500 from bson."""
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    service = _service(collection)

    with pytest.raises(TDebModelNotFound):
        await service.load("user-1", "not-an-objectid")


@pytest.mark.asyncio
async def test_duplicate_accepts_own_or_published_only():
    """
    The duplicate lookup must admit exactly two cases: the caller's own model,
    or one published org-wide. Anything else stays invisible.
    """
    doc = _model_doc(owner_id="user-1")
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=doc)
    collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
    service = _service(collection)

    await service.duplicate("user-1", str(doc["_id"]))

    query = collection.find_one.call_args[0][0]
    assert query["$or"] == [{"owner_id": "user-1"}, {"published": {"$ne": None}}]


@pytest.mark.asyncio
async def test_duplicate_of_an_invisible_model_is_not_found():
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    service = _service(collection)

    with pytest.raises(TDebModelNotFound):
        await service.duplicate("user-2", str(ObjectId()))


@pytest.mark.asyncio
async def test_duplicate_names_the_copy_and_does_not_inherit_published():
    """A copy of a published template is the copier's own private model."""
    doc = _model_doc(owner_id="curator", published={"at": "now", "by": "curator"},
                     name="Reference kDEB")
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=doc)
    collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
    service = _service(collection)

    await service.duplicate("user-2", str(doc["_id"]))

    stored = collection.insert_one.call_args[0][0]
    assert stored["owner_id"] == "user-2"
    assert stored["network"]["name"] == "Reference kDEB (copy)"
    assert "published" not in stored


@pytest.mark.asyncio
async def test_publish_requires_ownership_even_for_a_curator():
    """
    The curator role grants the right to publish, not the right to publish
    someone else's private model.
    """
    doc = _model_doc(owner_id="someone-else")
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=doc)
    collection.update_one = AsyncMock()
    service = _service(collection)

    with pytest.raises(TDebModelForbidden):
        await service.publish("curator", str(doc["_id"]))
    collection.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_publish_marks_the_owner_and_time():
    doc = _model_doc(owner_id="curator")
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=doc)
    collection.update_one = AsyncMock()
    service = _service(collection)

    await service.publish("curator", str(doc["_id"]))

    published = collection.update_one.call_args[0][1]["$set"]["published"]
    assert published["by"] == "curator"
    assert published["at"] is not None


@pytest.mark.asyncio
async def test_unpublish_requires_ownership():
    doc = _model_doc(owner_id="someone-else", published={"at": "now", "by": "x"})
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=doc)
    collection.update_one = AsyncMock()
    service = _service(collection)

    with pytest.raises(TDebModelForbidden):
        await service.unpublish("curator", str(doc["_id"]))
    collection.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_delete_is_scoped_to_the_owner():
    collection = MagicMock()
    collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
    service = _service(collection)

    with pytest.raises(TDebModelNotFound):
        await service.delete("user-2", str(ObjectId()))

    assert collection.delete_one.call_args[0][0]["owner_id"] == "user-2"


@pytest.mark.asyncio
async def test_set_metadata_is_scoped_to_the_owner():
    collection = MagicMock()
    collection.update_one = AsyncMock(return_value=MagicMock(matched_count=0))
    service = _service(collection)

    with pytest.raises(TDebModelNotFound):
        await service.set_metadata("user-2", str(ObjectId()), name="Renamed")

    assert collection.update_one.call_args[0][0]["owner_id"] == "user-2"


@pytest.mark.asyncio
async def test_rename_does_not_rewrite_the_network():
    """Renaming should touch the name field, not rewrite every node and edge."""
    oid = ObjectId()
    collection = MagicMock()
    collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    collection.find_one = AsyncMock(return_value=_model_doc(name="Renamed"))
    service = _service(collection)

    await service.set_metadata("user-1", str(oid), name="Renamed")

    updates = collection.update_one.call_args[0][1]["$set"]
    assert updates["network.name"] == "Renamed"
    assert not any(key == "network" for key in updates)
