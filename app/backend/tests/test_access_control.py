"""
Access-control matrix: every router prefix × every kind of caller.

One representative endpoint per mounted router (two where a router mixes
policies), each requested as anonymous, explorator, curator, administrator,
external contributor and a suspended account. The expectation for a cell
follows from the endpoint's policy alone, so the table below *is* the access
model, and a router that drifts from it fails here.

``test_every_api_router_is_in_the_matrix`` keeps the table honest: mounting a
new router without adding it here fails the suite.

Runs against the in-memory Motor stand-in from conftest.py — never a database.
"""
import json
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from starlette.websockets import WebSocketDisconnect

CALLERS = ["anonymous", "explorator", "curator", "admin", "external_contributor", "suspended"]

OK = "ok"  # the request got past access control and was served

# Expected outcome per policy, per caller. 401: no usable credentials (absent,
# or the account is suspended). 403: authenticated, but not allowed.
POLICIES = {
    # No authentication at all.
    "public": dict.fromkeys(CALLERS, OK),
    # Any signed-in account except an external contributor.
    "member": {"anonymous": 401, "explorator": OK, "curator": OK, "admin": OK,
               "external_contributor": 403, "suspended": 401},
    # One's own account and settings — external contributors included.
    "self": {"anonymous": 401, "explorator": OK, "curator": OK, "admin": OK,
             "external_contributor": OK, "suspended": 401},
    # The elicitation queue: curators, administrators, external contributors
    # and anyone granted the sf_elicitation capability (not this explorator).
    "elicitor": {"anonymous": 401, "explorator": 403, "curator": OK, "admin": OK,
                 "external_contributor": OK, "suspended": 401},
    "curator": {"anonymous": 401, "explorator": 403, "curator": OK, "admin": OK,
                "external_contributor": 403, "suspended": 401},
    "admin": {"anonymous": 401, "explorator": 403, "curator": 403, "admin": OK,
              "external_contributor": 403, "suspended": 401},
}

BATCH_ID = str(ObjectId())

# (router prefix, method, path, policy, served status, token transport)
#
# "served status" is what a caller who passes access control gets back from
# the stubbed stores — 200 almost everywhere. Transport "ticket" sends a
# one-time ?ticket= from POST /api/auth/ws-ticket, what an EventSource uses;
# "query" the deprecated raw ?token=.
ENDPOINTS = [
    ("/api/auth", "GET", "/api/auth/config", "public", 200, "header"),
    ("/api/auth", "POST", "/api/auth/ws-ticket", "member", 200, "header"),
    ("/api/users", "GET", "/api/users/me", "self", 200, "header"),
    ("/api/users", "GET", "/api/users/", "admin", 200, "header"),
    ("/api/users/me/llm-keys", "GET", "/api/users/me/llm-keys", "self", 200, "header"),
    ("/api/documents", "GET", "/api/documents/", "member", 200, "header"),
    ("/api/facts", "GET", "/api/facts/", "member", 200, "header"),
    ("/api/facts", "PATCH", f"/api/facts/{ObjectId()}/review", "curator", 404, "header"),
    ("/api/chat", "GET", "/api/chat/sessions", "member", 200, "header"),
    ("/api/elicitation", "GET", "/api/elicitation/progress", "elicitor", 200, "header"),
    ("/api/elicitation", "GET", "/api/elicitation/experts", "admin", 200, "header"),
    ("/api/enrolment", "GET", "/api/enrolment/requests", "admin", 200, "header"),
    ("/api/models", "GET", "/api/models/", "member", 200, "header"),
    ("/api/tdeb", "GET", "/api/tdeb/templates", "member", 200, "header"),
    ("/api/graph", "GET", "/api/graph/provenance/chunk:abc", "member", 200, "header"),
    ("/api/graph", "GET", "/api/graph/chunk/abc/context", "member", 200, "header"),
    ("/api/kb/agents", "GET", "/api/kb/agents/models", "curator", 200, "header"),
    ("/api/kb/viz", "GET", "/api/kb/viz/schema/sf_support/status", "curator", 200, "header"),
    ("/api/kb/viz", "GET", "/api/kb/viz/schema/unknown/stream", "curator", 200, "query"),
    ("/api/kb/viz", "GET", "/api/kb/viz/schema/unknown/stream", "curator", 200, "ticket"),
    ("/api/kb/ingestion", "GET", "/api/kb/ingestion/batches", "curator", 200, "header"),
    ("/api/kb/ingestion", "GET", f"/api/kb/ingestion/batches/{BATCH_ID}/stream", "curator", 200, "query"),
    ("/api/kb/db", "GET", "/api/kb/db/collections", "curator", 200, "header"),
    ("/api/kb/db", "GET", "/api/kb/db/reset/preview", "admin", 200, "header"),
    ("/api/kb/fs", "GET", "/api/kb/fs/browse", "curator", 200, "header"),
    ("/api/kb/kg", "GET", "/api/kb/kg/stats", "curator", 200, "header"),
    ("/api/kb/documents", "GET", "/api/kb/documents/", "member", 200, "header"),
    ("/api/kb/stylized-facts", "GET", "/api/kb/stylized-facts/", "member", 200, "header"),
    ("/api/kb/facts", "GET", "/api/kb/facts/", "member", 200, "header"),
    ("/api/info", "GET", "/api/info", "public", 200, "header"),
    ("/api/health", "GET", "/api/health", "public", 200, "header"),
]


class _StubProvenance:
    async def get_provenance(self, citation_id):
        return {"citation_id": citation_id, "facts": [], "chunks": [], "documents": []}

    async def get_chunk_context(self, chunk_id, window):
        return {"chunk_id": chunk_id, "neighbors": []}


class _StubAgentService:
    def __init__(self, db):
        pass

    async def list_ollama_models(self):
        return []


class _StubKG:
    def __init__(self, db):
        pass

    async def get_stats(self):
        return {}


class _StubArtifactBuilder:
    async def get_public_meta(self, *args, **kwargs):
        return {"status": "ready"}


@pytest.fixture
def stubbed_stores(monkeypatch, fake_mongo, tmp_path):
    """Replace everything behind the representative endpoints that would leave
    the process (Ollama, ArangoDB, ChromaDB, the filesystem) with stubs."""
    from app.api.routes import graph
    from app.api.routes.kb import agents, filesystem, kg_builder, visualization
    from app.core.config import settings

    monkeypatch.setattr(graph, "ProvenanceService", _StubProvenance)
    monkeypatch.setattr(agents, "AgentService", _StubAgentService)
    monkeypatch.setattr(kg_builder, "KGBuilderService", _StubKG)
    monkeypatch.setattr(visualization, "_get_artifact_builder", lambda: _StubArtifactBuilder())
    monkeypatch.setattr(filesystem, "FS_ROOT", str(tmp_path))
    monkeypatch.setattr(filesystem, "DEFAULT_PATH", str(tmp_path))

    # The ingestion stream polls until its batch is terminal; start it there.
    fake_mongo[settings.KB_DB_NAME].ingestion_batches.docs.append(
        {"_id": ObjectId(BATCH_ID), "status": "completed",
         "created_at": datetime.now(timezone.utc)})

    # Arango-backed lists: no collections, an empty result set.
    from app.core import database
    arango = database._arango_db
    arango.db.aql.execute.side_effect = lambda *a, **k: iter([])
    arango.db.collections.return_value = []
    arango.db.has_collection.return_value = False


def _ticket(user_doc):
    """Mint a socket ticket directly: the matrix row for /ws-ticket already
    covers who may ask for one, and a caller refused there (an external
    contributor) must still be refused where the ticket is presented."""
    from app.core.auth import create_socket_ticket
    return create_socket_ticket(user_doc)


def _request(client, method, path, transport, headers, user=None):
    sep = "&" if "?" in path else "?"
    if transport == "query" and headers:
        token = headers["Authorization"].split(" ", 1)[1]
        return client.request(method, f"{path}{sep}token={token}")
    if transport == "ticket" and user is not None:
        return client.request(method, f"{path}{sep}ticket={_ticket(user)}")
    if transport in ("query", "ticket"):
        return client.request(method, path)
    body = {"status": "published"} if method == "PATCH" else None
    return client.request(method, path, headers=headers, json=body)


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize(
    "prefix,method,path,policy,served,transport", ENDPOINTS,
    ids=[f"{e[1]} {e[2]} [{e[5]}]" for e in ENDPOINTS],
)
def test_access_matrix(client, personas, auth_header, stubbed_stores, monkeypatch,
                       prefix, method, path, policy, served, transport, caller):
    user = None if caller == "anonymous" else personas[caller]
    expected = POLICIES[policy][caller]

    response = _request(client, method, path, transport, auth_header(user), user)

    if expected == OK:
        assert response.status_code == served, (
            f"{caller} on {method} {path}: expected to be served ({served}), "
            f"got {response.status_code}: {response.text[:300]}")
    else:
        assert response.status_code == expected, (
            f"{caller} on {method} {path}: expected {expected}, "
            f"got {response.status_code}: {response.text[:300]}")


def test_every_api_router_is_in_the_matrix():
    """Mounting a router without a row in ENDPOINTS fails the suite."""
    from fastapi.routing import APIRoute, APIWebSocketRoute
    from app.main import app

    covered = {e[0] for e in ENDPOINTS} | {"/ws/chat", "/api/tdeb/ws"}
    uncovered = set()
    for route in app.routes:
        if not isinstance(route, (APIRoute, APIWebSocketRoute)):
            continue
        if not (route.path.startswith("/api/") or route.path.startswith("/ws/")):
            continue
        if not any(route.path == c or route.path.startswith(c + "/") for c in covered):
            uncovered.add(route.path)
    assert not uncovered, f"routes with no matrix row: {sorted(uncovered)}"


def test_every_api_route_requires_auth_unless_listed_public():
    """Statically: an /api route reachable without credentials is a decision,
    so it must be on this list."""
    from fastapi.routing import APIRoute
    from app.core.auth import get_current_user
    from app.core.dependencies import get_current_user_sse
    from app.main import app

    public = {
        "/api/auth/config", "/api/auth/login", "/api/auth/token", "/api/auth/google",
        "/api/auth/refresh", "/api/auth/logout", "/api/enrolment/request",
        "/api/info", "/api/health",
    }

    def depends_on_auth(dependant):
        for dep in dependant.dependencies:
            if dep.call in (get_current_user, get_current_user_sse) or depends_on_auth(dep):
                return True
        return False

    open_routes = sorted(
        r.path for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api/")
        and not depends_on_auth(r.dependant) and r.path not in public
    )
    assert not open_routes, f"unauthenticated /api routes: {open_routes}"


# --------------------------------------------------------------------------- #
# WebSockets                                                                   #
# --------------------------------------------------------------------------- #

WS_ALLOWED = {"explorator", "curator", "admin"}


class _StubChatService:
    async def process_message_stream(self, **kwargs):
        yield {"type": "message", "role": "assistant", "content": "stub",
               "user_id": kwargs["user_id"]}


def _ws_credential(user, transport, token_for):
    if user is None:
        return ""
    if transport == "ticket":
        from app.core.auth import create_socket_ticket
        return f"?ticket={create_socket_ticket(user)}"
    return f"?token={token_for(user)}"


@pytest.mark.parametrize("transport", ["ticket", "token"])
@pytest.mark.parametrize("caller", CALLERS)
def test_chat_websocket_requires_an_account_that_may_chat(
        client, personas, token_for, monkeypatch, caller, transport):
    """No anonymous fallback: an unauthenticated socket would spend the shared
    default-model key. External contributors have no chat; suspended accounts
    nothing. ``?token=`` is the deprecated credential, refused the same way."""
    from app.api.routes import ws

    monkeypatch.setattr(ws, "ChatService", _StubChatService)
    user = None if caller == "anonymous" else personas[caller]
    url = "/ws/chat/new" + _ws_credential(user, transport, token_for)

    with client.websocket_connect(url) as sock:
        # Always send first: a refused socket answers with its close frame, an
        # accepted one with the stub reply — so a regression fails, not hangs.
        sock.send_json({"type": "user_message", "text": "hello"})
        message = sock.receive()
        if caller in WS_ALLOWED:
            assert message["type"] == "websocket.send", message
            event = json.loads(message["text"])
            assert event["content"] == "stub"
            # The server's identity for the turn is the token's, not the payload's.
            assert event["user_id"] == str(user["_id"])
        else:
            assert message["type"] == "websocket.close", message
            assert message["code"] == 4401


@pytest.mark.parametrize("transport", ["ticket", "token"])
@pytest.mark.parametrize("caller", CALLERS)
def test_tdeb_websocket_requires_an_account_that_may_model(
        client, personas, token_for, caller, transport):
    user = None if caller == "anonymous" else personas[caller]
    url = f"/api/tdeb/ws/simulate/{ObjectId()}" + _ws_credential(user, transport, token_for)

    if caller in WS_ALLOWED:
        with client.websocket_connect(url) as sock:
            # Authenticated and served: the (absent) model is looked up.
            assert sock.receive_json() == {"error": "Model not found"}
    else:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(url) as sock:
                sock.receive_json()
        assert exc_info.value.code == 4401


def test_chat_websocket_reconnect_does_not_reveal_another_users_generation(
        client, personas, app_db, token_for, monkeypatch):
    """The session id comes from the URL; catch-up events are for its owner only."""
    from app.api.routes import ws

    monkeypatch.setattr(ws, "ChatService", _StubChatService)
    session_id = ObjectId()
    app_db.chat_sessions.docs.append({"_id": session_id, "user_id": str(personas["curator"]["_id"])})
    app_db.chat_messages.docs.append({"_id": ObjectId(), "session_id": str(session_id),
                                      "status": "generating"})

    with client.websocket_connect(
            f"/ws/chat/{session_id}?token={token_for(personas['explorator'])}") as sock:
        sock.send_json({"type": "user_message", "text": "hi"})
        # The first event is the stubbed reply, not a "generating" catch-up.
        assert sock.receive_json()["type"] == "message"

    with client.websocket_connect(
            f"/ws/chat/{session_id}?token={token_for(personas['curator'])}") as sock:
        sock.send_json({"type": "user_message", "text": "hi"})
        assert sock.receive_json()["type"] == "generating"
        assert sock.receive_json()["type"] == "message"


# --------------------------------------------------------------------------- #
# Token types and revocation, at the resolver                                  #
# --------------------------------------------------------------------------- #

def test_refresh_token_is_not_an_access_token(client, personas):
    from app.core.auth import create_refresh_token

    refresh = create_refresh_token({"sub": str(personas["admin"]["_id"])})
    response = client.get("/api/users/me", headers={"Authorization": f"Bearer {refresh}"})
    assert response.status_code == 401


def test_access_token_from_an_earlier_session_generation_is_refused(
        client, personas, auth_header, app_db):
    user = personas["explorator"]
    headers = auth_header(user)
    assert client.get("/api/users/me", headers=headers).status_code == 200

    for doc in app_db.users.docs:
        if doc["_id"] == user["_id"]:
            doc["token_version"] = 1
    assert client.get("/api/users/me", headers=headers).status_code == 401


def test_token_for_a_deleted_user_is_refused(client, personas, auth_header, app_db):
    user = personas["curator"]
    headers = auth_header(user)
    app_db.users.docs[:] = [d for d in app_db.users.docs if d["_id"] != user["_id"]]
    assert client.get("/api/documents/", headers=headers).status_code == 401


def test_external_contributor_with_an_ordinary_role_is_treated_by_that_role(
        client, make_user, auth_header):
    """The confinement applies to accounts holding *only* the external role."""
    user = make_user("both@example.org", roles=["external_contributor", "knowledge_explorator"])
    assert client.get("/api/documents/", headers=auth_header(user)).status_code == 200
