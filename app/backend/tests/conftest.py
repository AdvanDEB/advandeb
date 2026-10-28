"""
Shared test setup.

This machine is production: the MongoDB ``advandeb`` database holds real
users, and the default ArangoDB/MongoDB URLs point at the live stores. So the
environment is pinned *before* any application module is imported — every
store URL at an unreachable port, the log file in a temp directory — and the
HTTP tests run against an in-memory stand-in for Motor, never a database.

``TestClient(app)`` is deliberately never entered as a context manager: that
would run the lifespan, which connects to MongoDB and builds indexes.
"""
import os
import re
import tempfile

_UNREACHABLE_MONGO = "mongodb://127.0.0.1:1/never_used"

os.environ["MONGODB_URI"] = _UNREACHABLE_MONGO
os.environ["MONGODB_URL"] = _UNREACHABLE_MONGO          # advandeb_kb settings
os.environ["ARANGO_URL"] = "http://127.0.0.1:1"
os.environ["ENVIRONMENT"] = "development"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-unit-tests-only-0123456789"
os.environ["LOG_FILE"] = os.path.join(tempfile.mkdtemp(prefix="advandeb-tests-"), "app.log")
os.environ.pop("FORWARDED_ALLOW_IPS", None)

from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from bson import ObjectId  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402


# --------------------------------------------------------------------------- #
# In-memory Motor stand-in                                                     #
# --------------------------------------------------------------------------- #
#
# Only as much of the query language as the routes under test use. An operator
# it does not know makes a document *not* match, so a gap shows up as a test
# failure rather than as a query that silently matches everything.

def _ci(value, case_insensitive):
    return value.lower() if case_insensitive and isinstance(value, str) else value


def _match_value(actual, cond, ci=False):
    if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$in":
                if not any(_match_value(actual, a, ci) for a in arg):
                    return False
            elif op == "$ne":
                if _match_value(actual, arg, ci):
                    return False
            elif op == "$exists":
                if (actual is not _MISSING) != bool(arg):
                    return False
            elif op == "$regex":
                flags = re.IGNORECASE if "i" in cond.get("$options", "") else 0
                if not isinstance(actual, str) or not re.search(arg, actual, flags):
                    return False
            elif op == "$options":
                continue
            elif op == "$type":
                if arg != "string" or not isinstance(actual, str):
                    return False
            else:
                return False
        return True
    if isinstance(actual, list) and not isinstance(cond, list):
        return any(_ci(a, ci) == _ci(cond, ci) for a in actual)
    return _ci(actual, ci) == _ci(cond, ci)


_MISSING = object()


def _matches(doc, query, ci=False):
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, q, ci) for q in cond):
                return False
            continue
        if not _match_value(doc.get(key, _MISSING), cond, ci):
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        if n:
            self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, length=None):
        return list(self._docs)


class FakeCollection:
    def __init__(self, name, unique=()):
        self.name = name
        self.docs = []
        self.unique = tuple(unique)

    def _find(self, query, collation=None):
        ci = bool(collation and collation.get("strength", 3) <= 2)
        return [d for d in self.docs if _matches(d, query, ci)]

    async def find_one(self, query=None, projection=None, collation=None, **kwargs):
        found = self._find(query or {}, collation)
        return dict(found[0]) if found else None

    def find(self, query=None, projection=None, **kwargs):
        return FakeCursor(dict(d) for d in self._find(query or {}))

    def aggregate(self, pipeline, **kwargs):
        return FakeCursor([])

    async def count_documents(self, query=None, **kwargs):
        return len(self._find(query or {}))

    async def distinct(self, key, query=None, **kwargs):
        return sorted({d[key] for d in self._find(query or {}) if key in d})

    async def insert_one(self, doc):
        for field in self.unique:
            if any(d.get(field) == doc.get(field) for d in self.docs):
                raise DuplicateKeyError(f"duplicate {self.name}.{field}")
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def _apply(self, doc, update):
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        for key, value in update.get("$addToSet", {}).items():
            doc.setdefault(key, [])
            if value not in doc[key]:
                doc[key].append(value)
        for key, value in update.get("$pull", {}).items():
            doc[key] = [v for v in doc.get(key, []) if v != value]
        for key, value in update.get("$inc", {}).items():
            doc[key] = doc.get(key, 0) + value

    async def update_one(self, query, update, upsert=False, **kwargs):
        found = self._find(query)
        if found:
            self._apply(found[0], update)
            return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            doc = {k: v for k, v in query.items() if not k.startswith("$")}
            self._apply(doc, update)
            await self.insert_one(doc)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc["_id"])
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    async def update_many(self, query, update, **kwargs):
        found = self._find(query)
        for doc in found:
            self._apply(doc, update)
        return SimpleNamespace(matched_count=len(found), modified_count=len(found))

    async def delete_one(self, query, **kwargs):
        found = self._find(query)
        if found:
            self.docs.remove(found[0])
        return SimpleNamespace(deleted_count=len(found[:1]))

    async def delete_many(self, query, **kwargs):
        found = self._find(query)
        for doc in found:
            self.docs.remove(doc)
        return SimpleNamespace(deleted_count=len(found))

    async def create_index(self, *args, **kwargs):
        return kwargs.get("name", "idx")


class FakeDatabase:
    # Mirrors the unique indexes that matter to the code under test.
    _UNIQUE = {"revoked_tokens": ("jti",)}

    def __init__(self, name):
        self.name = name
        self._collections = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollection(name, self._UNIQUE.get(name, ()))
        return self._collections[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    async def command(self, *args, **kwargs):
        return {"ok": 1}


class FakeMongoClient:
    def __init__(self):
        self._dbs = {}

    def __getitem__(self, name):
        if name not in self._dbs:
            self._dbs[name] = FakeDatabase(name)
        return self._dbs[name]

    def close(self):
        pass


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture
def fake_mongo(monkeypatch):
    """Install the in-memory client behind get_database()/get_kb_database(),
    and a MagicMock behind get_arango_db(), for the duration of a test."""
    from app.core import database

    client = FakeMongoClient()
    monkeypatch.setattr(database.db, "client", client)
    monkeypatch.setattr(database, "_arango_db", MagicMock(name="arango"))
    return client


@pytest.fixture
def app_db(fake_mongo):
    from app.core.config import settings
    return fake_mongo[settings.MONGODB_DB_NAME]


def _test_client(app):
    """``TestClient(app)``, working around starlette 0.27 + httpx 0.28.

    That starlette passes ``app=`` to ``httpx.Client.__init__``, which httpx
    0.28 removed; the transport it also passes is what actually carries the
    app. Dropping the keyword for the duration of the constructor is enough —
    the env serves production, so upgrading packages in it is not the fix.
    """
    import inspect

    import httpx
    from fastapi.testclient import TestClient

    if "app" in inspect.signature(httpx.Client.__init__).parameters:
        return TestClient(app, raise_server_exceptions=False)

    original = httpx.Client.__init__

    def _init_without_app(self, *args, app=None, **kwargs):
        original(self, *args, **kwargs)

    httpx.Client.__init__ = _init_without_app
    try:
        return TestClient(app, raise_server_exceptions=False)
    finally:
        httpx.Client.__init__ = original


@pytest.fixture
def client(fake_mongo):
    """A TestClient that never runs the lifespan, with rate limits off."""
    from app.core.limiter import limiter
    from app.main import app

    previous = limiter.enabled
    limiter.enabled = False
    try:
        yield _test_client(app)
    finally:
        limiter.enabled = previous


# One account per row of the access-control matrix. The suspended account is
# an administrator so that suspension is the only thing that can refuse it.
PERSONAS = {
    "explorator": {"roles": ["knowledge_explorator"]},
    "curator": {"roles": ["knowledge_curator"]},
    "admin": {"roles": ["administrator"]},
    "external_contributor": {"roles": ["external_contributor"], "capabilities": ["sf_elicitation"]},
    "suspended": {"roles": ["administrator"], "status": "suspended"},
}

TEST_PASSWORD = "correct horse battery"


_HASH_CACHE = {}


def _password_hash(password):
    # bcrypt is deliberately slow; hashing per persona per test would cost
    # minutes across the matrix.
    if password not in _HASH_CACHE:
        from app.core.auth import get_password_hash
        _HASH_CACHE[password] = get_password_hash(password)
    return _HASH_CACHE[password]


@pytest.fixture
def make_user(app_db):
    """Insert a user into the fake app DB and return its document."""
    def _make(email, roles=("knowledge_explorator",), status="active",
              capabilities=(), password=TEST_PASSWORD, **extra):
        now = datetime.now(timezone.utc)
        doc = {
            "_id": ObjectId(),
            "email": email,
            "full_name": email.split("@")[0],
            "roles": list(roles),
            "capabilities": list(capabilities),
            "status": status,
            "created_at": now,
            "updated_at": now,
            **extra,
        }
        if password is not None:
            doc["password_hash"] = _password_hash(password)
        app_db.users.docs.append(doc)
        return doc

    return _make


@pytest.fixture
def personas(make_user):
    """{persona name: user document} for every matrix persona."""
    return {
        name: make_user(f"{name}@example.org", **spec)
        for name, spec in PERSONAS.items()
    }


@pytest.fixture
def token_for():
    """Mint an access token for a user document."""
    from app.core.auth import create_access_token

    def _token(user_doc):
        return create_access_token({"sub": str(user_doc["_id"]), "email": user_doc["email"]})

    return _token


@pytest.fixture
def auth_header(token_for):
    """``Authorization: Bearer`` headers for a user document (None → none)."""
    def _header(user_doc):
        return {} if user_doc is None else {"Authorization": f"Bearer {token_for(user_doc)}"}

    return _header
