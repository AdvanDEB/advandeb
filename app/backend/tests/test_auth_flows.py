"""
Authentication flows and the input guards around them.

Runs against the in-memory Motor stand-in from conftest.py — never a database.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.core.auth import create_refresh_token, verify_password

PASSWORD = "correct horse battery"


def _login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _user_doc(app_db, user):
    return next(d for d in app_db.users.docs if d["_id"] == user["_id"])


# --------------------------------------------------------------------------- #
# Refresh                                                                      #
# --------------------------------------------------------------------------- #

def test_refresh_issues_a_new_pair(client, make_user):
    """Regression: from 8fa44bf8 (2026-05-21) every refresh was refused,
    because the endpoint verified the refresh token as an access token."""
    make_user("r@example.org")
    tokens = _login(client, "r@example.org").json()

    response = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 200, response.text
    fresh = response.json()
    assert fresh["refresh_token"] != tokens["refresh_token"]
    me = client.get("/api/users/me", headers={"Authorization": f"Bearer {fresh['access_token']}"})
    assert me.status_code == 200


def test_refresh_token_is_single_use(client, make_user):
    make_user("r@example.org")
    refresh = _login(client, "r@example.org").json()["refresh_token"]

    assert client.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code == 200
    replay = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert replay.status_code == 401


def test_access_token_cannot_refresh(client, make_user):
    make_user("r@example.org")
    access = _login(client, "r@example.org").json()["access_token"]
    assert client.post("/api/auth/refresh", json={"refresh_token": access}).status_code == 401


def test_refresh_token_without_jti_is_refused(client, make_user):
    from jose import jwt
    from app.core.config import settings

    user = make_user("r@example.org")
    legacy = jwt.encode(
        {"sub": str(user["_id"]), "type": "refresh",
         "exp": datetime.now(timezone.utc) + timedelta(days=1)},
        settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert client.post("/api/auth/refresh", json={"refresh_token": legacy}).status_code == 401


def test_suspended_account_cannot_refresh(client, make_user, app_db):
    user = make_user("r@example.org")
    refresh = _login(client, "r@example.org").json()["refresh_token"]
    _user_doc(app_db, user)["status"] = "suspended"
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_logout_revokes_the_refresh_token(client, make_user):
    make_user("r@example.org")
    refresh = _login(client, "r@example.org").json()["refresh_token"]

    assert client.post("/api/auth/logout", json={"refresh_token": refresh}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_logout_answers_the_same_for_garbage(client):
    response = client.post("/api/auth/logout", json={"refresh_token": "not-a-token"})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Login                                                                        #
# --------------------------------------------------------------------------- #

def test_suspended_account_cannot_log_in(client, make_user):
    make_user("s@example.org", status="suspended")
    response = _login(client, "s@example.org")
    assert response.status_code == 403
    assert response.json()["detail"] == "Account suspended"


def test_suspension_is_not_revealed_without_the_password(client, make_user):
    make_user("s@example.org", status="suspended")
    assert _login(client, "s@example.org", "wrong password").status_code == 401


def test_overlong_password_is_a_failed_login_not_a_500(client, make_user):
    """bcrypt 5 raises ValueError for >72 bytes; that used to surface as a 500."""
    make_user("l@example.org")
    assert _login(client, "l@example.org", "x" * 200).status_code == 401


def test_login_ignores_email_case(client, make_user):
    make_user("Mixed.Case@Example.org")
    assert _login(client, "mixed.case@example.org").status_code == 200


def test_verify_password_tolerates_a_malformed_hash():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


# --------------------------------------------------------------------------- #
# Self-service password change                                                 #
# --------------------------------------------------------------------------- #

NEW_PASSWORD = "a much better passphrase"


def test_password_change_requires_the_current_password(client, make_user, auth_header):
    user = make_user("p@example.org")
    headers = auth_header(user)

    missing = client.put("/api/users/me/password", headers=headers, json={"password": NEW_PASSWORD})
    wrong = client.put("/api/users/me/password", headers=headers,
                       json={"password": NEW_PASSWORD, "current_password": "nope nope"})
    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert _login(client, "p@example.org").status_code == 200


@pytest.mark.parametrize("new_password", ["", "short", "x" * 73, "ž" * 37])
def test_password_policy(client, make_user, auth_header, new_password):
    user = make_user("p@example.org")
    response = client.put("/api/users/me/password", headers=auth_header(user),
                          json={"password": new_password, "current_password": PASSWORD})
    assert response.status_code == 422


def test_password_change_ends_every_other_session(client, make_user):
    make_user("p@example.org")
    old = _login(client, "p@example.org").json()
    old_headers = {"Authorization": f"Bearer {old['access_token']}"}

    response = client.put("/api/users/me/password", headers=old_headers,
                          json={"password": NEW_PASSWORD, "current_password": PASSWORD})
    assert response.status_code == 200, response.text
    fresh = response.json()

    assert client.post("/api/auth/refresh", json={"refresh_token": old["refresh_token"]}).status_code == 401
    assert client.get("/api/users/me", headers=old_headers).status_code == 401
    assert client.get("/api/users/me",
                      headers={"Authorization": f"Bearer {fresh['access_token']}"}).status_code == 200
    assert _login(client, "p@example.org", NEW_PASSWORD).status_code == 200
    assert _login(client, "p@example.org").status_code == 401


def test_refresh_keeps_the_session_generation(client, make_user, app_db):
    """A refreshed pair belongs to the same generation as the one it replaced,
    and a later revocation still reaches it."""
    user = make_user("p@example.org", token_version=3)
    refresh = _login(client, "p@example.org").json()["refresh_token"]
    fresh = client.post("/api/auth/refresh", json={"refresh_token": refresh}).json()

    _user_doc(app_db, user)["token_version"] = 4
    assert client.post("/api/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 401


def test_first_password_needs_no_current_one(client, make_user, auth_header):
    """An account created through Google sign-in has no password to prove."""
    user = make_user("g@example.org", password=None, google_id="g-123")
    response = client.put("/api/users/me/password", headers=auth_header(user),
                          json={"password": NEW_PASSWORD})
    assert response.status_code == 200
    assert _login(client, "g@example.org", NEW_PASSWORD).status_code == 200


def test_admin_reset_and_suspension_revoke_sessions(client, make_user, auth_header, app_db):
    admin = make_user("admin@example.org", roles=["administrator"])
    target = make_user("t@example.org")

    assert client.post(f"/api/users/{target['_id']}/reset-password",
                       headers=auth_header(admin)).status_code == 200
    assert _user_doc(app_db, target)["token_version"] == 1

    assert client.patch(f"/api/users/{target['_id']}/status", headers=auth_header(admin),
                        json={"status": "suspended"}).status_code == 200
    assert _user_doc(app_db, target)["token_version"] == 2


# --------------------------------------------------------------------------- #
# Account creation and roles                                                   #
# --------------------------------------------------------------------------- #

def _create(client, admin_headers, **body):
    payload = {"email": "new@example.org", "password": "long enough pw", **body}
    return client.post("/api/users/", headers=admin_headers, json=payload)


def test_create_user_validates_roles(client, make_user, auth_header):
    headers = auth_header(make_user("admin@example.org", roles=["administrator"]))
    assert _create(client, headers, roles=["superuser"]).status_code == 422
    assert _create(client, headers, roles=[]).status_code == 422
    created = _create(client, headers, roles=["external_contributor"])
    assert created.status_code == 201, created.text
    assert created.json()["roles"] == ["external_contributor"]


def test_create_user_normalises_email_and_refuses_case_duplicates(client, make_user, auth_header):
    headers = auth_header(make_user("admin@example.org", roles=["administrator"]))
    created = _create(client, headers, email="  New.Person@Example.ORG ")
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "new.person@example.org"
    assert _create(client, headers, email="NEW.person@example.org").status_code == 409


def test_create_user_applies_password_policy(client, make_user, auth_header):
    headers = auth_header(make_user("admin@example.org", roles=["administrator"]))
    assert _create(client, headers, password="short").status_code == 422


def test_external_contributor_role_can_be_assigned(client, make_user, auth_header):
    headers = auth_header(make_user("admin@example.org", roles=["administrator"]))
    target = make_user("t@example.org")
    response = client.post(f"/api/users/{target['_id']}/roles",
                           params={"role": "external_contributor"}, headers=headers)
    assert response.status_code == 200
    assert "external_contributor" in response.json()["roles"]


@pytest.mark.asyncio
async def test_unique_email_index_failure_does_not_block_startup(caplog):
    """Existing duplicates make the build fail; that is logged, not raised."""
    from unittest.mock import AsyncMock, MagicMock
    from pymongo.errors import OperationFailure
    from app.core.database import ensure_app_indexes

    db = MagicMock()
    for name in ("document_submissions", "fact_submissions", "sf_submissions",
                 "revoked_tokens", "user_llm_keys", "user_oauth_flows"):
        getattr(db, name).create_index = AsyncMock()
    db.users.create_index = AsyncMock(side_effect=OperationFailure("E11000 duplicate key"))

    with caplog.at_level(logging.ERROR):
        await ensure_app_indexes(db)

    kwargs = db.users.create_index.call_args.kwargs
    assert kwargs["unique"] is True
    assert kwargs["collation"]["strength"] == 2
    assert "users.email" in caplog.text


# --------------------------------------------------------------------------- #
# Submissions: ownership, search, paging                                       #
# --------------------------------------------------------------------------- #

def _submission(owner_key, owner_id, title="A paper"):
    now = datetime.now(timezone.utc)
    return {"_id": ObjectId(), owner_key: owner_id, "title": title, "status": "suggestion",
            "statement": "s", "summary": "s", "source_type": "manual",
            "created_at": now, "updated_at": now}


def test_submissions_are_listed_to_their_owner_and_to_curators(
        client, personas, auth_header, app_db):
    mine = _submission("uploader_id", str(personas["explorator"]["_id"]), "Mine")
    theirs = _submission("uploader_id", str(personas["curator"]["_id"]), "Theirs")
    app_db.document_submissions.docs.extend([mine, theirs])

    as_explorator = client.get("/api/documents/", headers=auth_header(personas["explorator"]))
    as_curator = client.get("/api/documents/", headers=auth_header(personas["curator"]))

    assert [d["title"] for d in as_explorator.json()] == ["Mine"]
    assert {d["title"] for d in as_curator.json()} == {"Mine", "Theirs"}
    other = client.get(f"/api/documents/{theirs['_id']}", headers=auth_header(personas["explorator"]))
    assert other.status_code == 404


def test_fact_submissions_are_listed_to_their_owner(client, personas, auth_header, app_db):
    app_db.fact_submissions.docs.extend([
        _submission("creator_id", str(personas["explorator"]["_id"])),
        _submission("creator_id", str(personas["curator"]["_id"])),
    ])
    app_db.sf_submissions.docs.append(_submission("creator_id", str(personas["curator"]["_id"])))
    headers = auth_header(personas["explorator"])

    assert len(client.get("/api/facts/", headers=headers).json()) == 1
    assert client.get("/api/facts/stylized/", headers=headers).json() == []


def test_document_search_is_literal_not_a_pattern(client, personas, auth_header, app_db):
    """A caller-supplied regex can backtrack catastrophically (ReDoS)."""
    app_db.document_submissions.docs.append(
        _submission("uploader_id", str(personas["curator"]["_id"]), "Growth (a+)+ model"))
    headers = auth_header(personas["curator"])

    literal = client.get("/api/documents/", params={"search": "(a+)+"}, headers=headers)
    pattern = client.get("/api/documents/", params={"search": "G.owth"}, headers=headers)

    assert [d["title"] for d in literal.json()] == ["Growth (a+)+ model"]
    assert pattern.json() == []


@pytest.mark.parametrize("path", [
    "/api/documents/", "/api/facts/", "/api/facts/stylized/", "/api/models/",
    "/api/kb/documents/", "/api/kb/facts/", "/api/kb/stylized-facts/",
])
def test_list_limit_is_bounded(client, personas, auth_header, path):
    headers = auth_header(personas["admin"])
    assert client.get(path, params={"limit": 501}, headers=headers).status_code == 422
    assert client.get(path, params={"skip": -1}, headers=headers).status_code == 422


# --------------------------------------------------------------------------- #
# Filesystem containment                                                       #
# --------------------------------------------------------------------------- #

def test_is_within_compares_components_not_prefixes(tmp_path):
    from app.core.paths import is_within

    root = tmp_path / "dev"
    sibling = tmp_path / "dev_x"
    root.mkdir()
    sibling.mkdir()
    assert is_within(str(root / "a"), str(root))
    assert not is_within(str(sibling), str(root))
    assert not is_within(str(root / ".." / "dev_x"), str(root))


def test_symlink_out_of_the_root_is_outside_it(tmp_path):
    from app.core.paths import is_within

    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(tmp_path)
    assert not is_within(str(root / "escape"), str(root))


@pytest.mark.parametrize("name,expected", [
    ("../../etc/evil.pdf", "evil.pdf"),
    ("..\\..\\win\\evil.pdf", "evil.pdf"),
    ("/abs/path/paper.PDF", "paper.pdf"),
    ("....pdf", None),
    ("we$ird na<me>.pdf", "we_ird na_me.pdf"),
])
def test_safe_upload_filename(name, expected):
    from app.core.paths import safe_upload_filename

    result = safe_upload_filename(name, extension=".pdf")
    assert "/" not in result and "\\" not in result and result.endswith(".pdf")
    if expected:
        assert result == expected


@pytest.fixture
def papers_root(monkeypatch, tmp_path):
    from advandeb_kb.config.settings import settings as kb_settings
    from app.api.routes.kb import ingestion

    root = tmp_path / "papers"
    (root / "inside").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    monkeypatch.setattr(kb_settings, "PAPERS_ROOT", str(root))

    async def _no_pipeline(*args, **kwargs):
        return None

    monkeypatch.setattr(ingestion, "run_pdf_job", _no_pipeline)
    return root


def test_upload_cannot_escape_the_uploads_folder(client, personas, auth_header, papers_root):
    response = client.post(
        "/api/kb/ingestion/upload", headers=auth_header(personas["curator"]),
        files={"file": ("../../outside/evil.pdf", b"%PDF-1.4 body", "application/pdf")})

    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "evil.pdf"
    assert (papers_root / "uploads" / "evil.pdf").exists()
    assert not (papers_root.parent / "outside" / "evil.pdf").exists()


def test_upload_does_not_overwrite_an_earlier_one(client, personas, auth_header, papers_root):
    headers = auth_header(personas["curator"])
    files = {"file": ("same.pdf", b"%PDF-1.4 first", "application/pdf")}
    first = client.post("/api/kb/ingestion/upload", headers=headers, files=files)
    files = {"file": ("same.pdf", b"%PDF-1.4 second", "application/pdf")}
    second = client.post("/api/kb/ingestion/upload", headers=headers, files=files)

    assert first.json()["filename"] != second.json()["filename"]
    assert (papers_root / "uploads" / "same.pdf").read_bytes() == b"%PDF-1.4 first"


def test_upload_rejects_non_pdf_and_oversized(client, personas, auth_header, papers_root, monkeypatch):
    from app.api.routes.kb import ingestion

    headers = auth_header(personas["curator"])
    fake = client.post("/api/kb/ingestion/upload", headers=headers,
                       files={"file": ("x.pdf", b"MZ not a pdf", "application/pdf")})
    assert fake.status_code == 400

    monkeypatch.setattr(ingestion, "MAX_UPLOAD_BYTES", 16)
    big = client.post("/api/kb/ingestion/upload", headers=headers,
                      files={"file": ("big.pdf", b"%PDF-" + b"x" * 64, "application/pdf")})
    assert big.status_code == 413
    assert os.listdir(papers_root / "uploads") == []


def test_source_browsing_stays_inside_papers_root(client, personas, auth_header, papers_root):
    headers = auth_header(personas["curator"])
    assert client.get("/api/kb/ingestion/sources/inside", headers=headers).status_code == 200
    escaped = client.get("/api/kb/ingestion/sources/inside/../../outside", headers=headers)
    assert escaped.status_code in (403, 404)
    assert client.get("/api/kb/ingestion/sources/%2E%2E", headers=headers).status_code in (403, 404)


def test_scan_refuses_folders_outside_papers_root(client, personas, auth_header, papers_root):
    response = client.post("/api/kb/ingestion/scan", headers=auth_header(personas["curator"]),
                           json={"folders": ["../outside"]})
    assert response.status_code == 403


def test_fs_browse_refuses_a_sibling_with_a_shared_prefix(
        client, personas, auth_header, monkeypatch, tmp_path):
    from app.api.routes.kb import filesystem

    root = tmp_path / "dev"
    root.mkdir()
    (tmp_path / "dev_x").mkdir()
    monkeypatch.setattr(filesystem, "FS_ROOT", str(root))
    headers = auth_header(personas["curator"])

    assert client.get("/api/kb/fs/browse", params={"path": str(root)}, headers=headers).status_code == 200
    sibling = client.get("/api/kb/fs/browse", params={"path": str(tmp_path / "dev_x")}, headers=headers)
    assert sibling.status_code == 403


def test_resolve_within_refuses_escape(tmp_path):
    from app.core.paths import resolve_within

    with pytest.raises(HTTPException) as exc_info:
        resolve_within(str(tmp_path), "../elsewhere")
    assert exc_info.value.status_code == 403
    assert resolve_within(str(tmp_path), ".") == os.path.realpath(tmp_path)


# --------------------------------------------------------------------------- #
# Proxy headers                                                                #
# --------------------------------------------------------------------------- #

def test_forwarded_headers_are_trusted_from_localhost_only(client):
    """With "*", anyone reaching :8400 directly could pick the client IP the
    per-IP rate limits key on."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    from app.main import app

    proxy = next(m for m in app.user_middleware if m.cls is ProxyHeadersMiddleware)
    assert proxy.options["trusted_hosts"] == "127.0.0.1"


# --------------------------------------------------------------------------- #
# Google OAuth                                                                 #
# --------------------------------------------------------------------------- #

def test_google_exchange_forwards_the_pkce_verifier(client, monkeypatch):
    import httpx
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "https://example.org/login")
    sent = {}

    async def _post(self, url, data=None, **kwargs):
        sent.update(data or {})
        return httpx.Response(400, json={"error": "invalid_grant"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    verifier = "v" * 64
    response = client.post("/api/auth/google", json={
        "code": "c", "redirect_uri": "https://example.org/login", "code_verifier": verifier})

    assert response.status_code == 400
    assert sent["code_verifier"] == verifier


def test_refresh_token_payload_carries_iat():
    from app.core.auth import verify_token
    payload = verify_token(create_refresh_token({"sub": "x"}), expected_type="refresh")
    assert isinstance(payload["iat"], int) and payload["jti"]


# --------------------------------------------------------------------------- #
# Socket tickets                                                               #
# --------------------------------------------------------------------------- #

class _StubChat:
    async def process_message_stream(self, **kwargs):
        yield {"type": "message", "content": "stub"}


def _ticket_for(client, auth_header, user):
    response = client.post("/api/auth/ws-ticket", headers=auth_header(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] == 30
    return body["ticket"]


def test_ticket_opens_one_socket_only(client, make_user, auth_header, monkeypatch):
    from app.api.routes import ws

    monkeypatch.setattr(ws, "ChatService", _StubChat)
    ticket = _ticket_for(client, auth_header, make_user("w@example.org"))

    with client.websocket_connect(f"/ws/chat/new?ticket={ticket}") as sock:
        sock.send_json({"type": "user_message", "text": "hi"})
        assert sock.receive_json()["content"] == "stub"

    with client.websocket_connect(f"/ws/chat/new?ticket={ticket}") as sock:
        sock.send_json({"type": "user_message", "text": "replayed"})
        message = sock.receive()
        assert message["type"] == "websocket.close" and message["code"] == 4401


def test_ticket_is_not_a_bearer_token(client, make_user, auth_header):
    ticket = _ticket_for(client, auth_header, make_user("w@example.org"))
    response = client.get("/api/users/me", headers={"Authorization": f"Bearer {ticket}"})
    assert response.status_code == 401


def test_access_token_cannot_be_presented_as_a_ticket(client, make_user, token_for):
    user = make_user("w@example.org", roles=["knowledge_curator"])
    response = client.get(f"/api/kb/viz/schema/unknown/stream?ticket={token_for(user)}")
    assert response.status_code == 401


def test_expired_ticket_is_refused(client, make_user):
    from jose import jwt
    from app.core.config import settings

    user = make_user("w@example.org", roles=["knowledge_curator"])
    stale = jwt.encode(
        {"sub": str(user["_id"]), "type": "ticket", "jti": "j1", "ver": 0,
         "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert client.get(f"/api/kb/viz/schema/unknown/stream?ticket={stale}").status_code == 401


def test_ticket_dies_with_its_session_generation(client, make_user, auth_header, app_db):
    user = make_user("w@example.org", roles=["knowledge_curator"])
    ticket = _ticket_for(client, auth_header, user)
    _user_doc(app_db, user)["token_version"] = 1
    assert client.get(f"/api/kb/viz/schema/unknown/stream?ticket={ticket}").status_code == 401


def test_external_contributor_gets_no_ticket(client, make_user, auth_header):
    user = make_user("x@example.org", roles=["external_contributor"])
    assert client.post("/api/auth/ws-ticket", headers=auth_header(user)).status_code == 403


# --------------------------------------------------------------------------- #
# Google sign-in: invitation only                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_google_sign_in_never_creates_an_account(fake_mongo, app_db):
    from app.services.user_service import UserService

    with pytest.raises(HTTPException) as exc_info:
        await UserService().get_google_user(
            google_id="g-1", email="stranger@gmail.com", email_verified=True)
    assert exc_info.value.status_code == 403
    assert app_db.users.docs == []


@pytest.mark.asyncio
async def test_google_sign_in_links_an_invited_account_by_verified_email(make_user, app_db):
    from app.services.user_service import UserService

    invited = make_user("Invited@Example.org", password=None)
    user = await UserService().get_google_user(
        google_id="g-2", email="invited@example.org", email_verified=True,
        avatar_url="https://example.org/a.png")

    assert user.id == str(invited["_id"])
    assert _user_doc(app_db, invited)["google_id"] == "g-2"
    # Later sign-ins find it by the Google identity.
    again = await UserService().get_google_user(
        google_id="g-2", email="changed@example.org", email_verified=False)
    assert again.id == str(invited["_id"])


@pytest.mark.asyncio
async def test_google_sign_in_needs_a_verified_address(make_user):
    from app.services.user_service import UserService

    make_user("invited@example.org")
    with pytest.raises(HTTPException) as exc_info:
        await UserService().get_google_user(
            google_id="g-3", email="invited@example.org", email_verified=False)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_google_sign_in_cannot_claim_an_account_linked_elsewhere(make_user):
    from app.services.user_service import UserService

    make_user("invited@example.org", google_id="g-original")
    with pytest.raises(HTTPException) as exc_info:
        await UserService().get_google_user(
            google_id="g-other", email="invited@example.org", email_verified=True)
    assert exc_info.value.status_code == 403
