"""
Document suggestions: the upload route is gone, and approval no longer pretends.

POST /api/documents/upload kept a PDF's extracted text and dropped the file.
Approving any document suggestion then queued a KB ingestion job for
``uploads/<filename or title>`` — a path nothing had written — and launched it
with ``asyncio.run`` in a thread against the server loop's Motor client, so the
job died on its first query and its batch stayed "running" while the curator
saw the suggestion vanish as if queued. Approval is now refused with a reason
(409) and the suggestion stays put; rejecting works as before.

The documents router is mounted on a bare app (as app.main mounts it), with the
app MongoDB replaced by mocks. Nothing here touches a database.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.api.routes import documents
from app.core.auth import get_current_user

CURATOR = {"id": "curator-1", "roles": ["knowledge_curator"]}
EXPLORER = {"id": "explorer-1", "roles": ["knowledge_explorator"]}


@pytest.fixture
def submissions():
    """The document_submissions collection, mocked."""
    coll = MagicMock()
    coll.find_one = AsyncMock(return_value=None)
    coll.update_one = AsyncMock()
    coll.insert_one = AsyncMock()
    return coll


@pytest.fixture
def kb_database():
    """Stands in for the KB MongoDB; approval must never reach for it."""
    with patch("app.core.database.get_kb_database") as m:
        yield m


def _app(submissions, user):
    db = MagicMock()
    db.document_submissions = submissions
    app = FastAPI()
    app.include_router(documents.router, prefix="/api/documents")
    app.dependency_overrides[get_current_user] = lambda: user
    return app, db


@pytest.fixture
async def client(submissions):
    app, db = _app(submissions, CURATOR)
    with patch("app.services.user_submission_service.get_database", return_value=db):
        # httpx's ASGI transport: starlette's TestClient does not work against
        # the httpx this environment pins.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _suggestion(**fields):
    doc = {
        "_id": ObjectId(),
        "title": "Kooijman 2010",
        "source_type": "text",
        "uploader_id": "u1",
        "status": "suggestion",
        "metadata": {},
    }
    doc.update(fields)
    return doc


# ---------------------------------------------------------------------------
# The upload route
# ---------------------------------------------------------------------------

def test_router_has_no_upload_route():
    assert not [r for r in documents.router.routes if r.path.endswith("/upload")]


@pytest.mark.asyncio
async def test_posting_a_file_to_the_old_upload_path_stores_nothing(client, submissions):
    r = await client.post(
        "/api/documents/upload",
        files={"file": ("paper.pdf", b"%PDF-1.4 not really", "application/pdf")},
    )
    # The path still matches GET/DELETE /{submission_id}; there is no POST.
    assert r.status_code == 405
    submissions.insert_one.assert_not_awaited()


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approving_a_metadata_only_suggestion_is_refused_and_left_in_queue(
    client, submissions, kb_database,
):
    doc = _suggestion(source_type="text", url="https://doi.org/10.1017/CBO9780511805400")
    submissions.find_one.return_value = doc

    r = await client.patch(f"/api/documents/{doc['_id']}/approve", json={"action": "approve"})

    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "metadata only" in detail
    assert "Knowledge Builder → Ingestion" in detail and "reject this suggestion" in detail
    submissions.update_one.assert_not_awaited()     # still status "suggestion"
    kb_database.assert_not_called()                 # no batch, no job


@pytest.mark.asyncio
async def test_approving_an_old_upload_suggestion_says_the_file_was_never_kept(
    client, submissions, kb_database,
):
    doc = _suggestion(
        title="paper.pdf",
        source_type="upload",
        content="extracted text",
        metadata={"filename": "paper.pdf", "content_type": "application/pdf", "size": 1234},
    )
    submissions.find_one.return_value = doc

    r = await client.patch(f"/api/documents/{doc['_id']}/approve", json={"action": "approve"})

    assert r.status_code == 409
    assert "never stored" in r.json()["detail"]
    submissions.update_one.assert_not_awaited()
    kb_database.assert_not_called()


# ---------------------------------------------------------------------------
# Rejection and the rest of the endpoint's contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rejecting_still_marks_the_suggestion_rejected(client, submissions, kb_database):
    doc = _suggestion()
    submissions.find_one.return_value = doc

    r = await client.patch(
        f"/api/documents/{doc['_id']}/approve",
        json={"action": "reject", "comment": "out of scope"},
    )

    assert r.status_code == 200
    assert r.json() == {"updated": True, "status": "rejected"}
    (query, update), _ = submissions.update_one.await_args
    assert query == {"_id": doc["_id"]}
    assert update["$set"]["status"] == "rejected"
    assert update["$set"]["reviewer_id"] == CURATOR["id"]
    assert update["$set"]["review_comment"] == "out of scope"
    kb_database.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("submission_id", [str(ObjectId()), "not-an-object-id"])
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_unknown_submission_is_404(client, submissions, submission_id, action):
    submissions.find_one.return_value = None
    r = await client.patch(f"/api/documents/{submission_id}/approve", json={"action": action})
    assert r.status_code == 404
    submissions.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_action_is_422(client, submissions):
    r = await client.patch(f"/api/documents/{ObjectId()}/approve", json={"action": "publish"})
    assert r.status_code == 422
    submissions.find_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_curators_may_review(submissions):
    app, db = _app(submissions, EXPLORER)
    submissions.find_one.return_value = _suggestion()
    with patch("app.services.user_submission_service.get_database", return_value=db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.patch(f"/api/documents/{ObjectId()}/approve", json={"action": "reject"})
    assert r.status_code == 403
    submissions.find_one.assert_not_awaited()
    submissions.update_one.assert_not_awaited()
