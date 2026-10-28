"""
Every API path the frontend calls must be a route the backend serves.

F-026: kbApi.ts asked for GET /api/documents and /api/facts, while the routes
are /api/documents/ and /api/facts/. FastAPI would normally redirect the
missing slash, but the SPA catch-all (app/core/spa.py) matches every GET first
and answers backend paths with 404, so the KB Suggestions tab silently lost
two of its lists. Nothing failed until a curator opened the tab.

This reads the frontend's axios calls statically —
``api|http|_authClient.<method>(<literal or template path>, …)`` in
app/frontend/src — and resolves each against ``app.main.app``'s routes, the
SPA catch-all excluded. ``${…}`` interpolations and a ``'…/' + id``
concatenation become one path segment (a path parameter), a ``${BASE}`` whose ``const BASE = '…'`` sits in the same
file is substituted, and the query string is dropped. Calls whose path is not
a literal (``api.get(url)``) cannot be checked here and are skipped.

No database, no network.
"""
import re
from pathlib import Path

import pytest
from starlette.routing import Match

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"

CALL = re.compile(r"\b(?:api|http|_authClient)\.(get|post|put|patch|delete)\b")
CONST = re.compile(r"""\bconst\s+([A-Z_][A-Z0-9_]*)\s*=\s*(['"`])([^'"`$]*)\2""")


def _skip_generic(src: str, i: int) -> int:
    """Past a TypeScript type argument list ``<…>`` starting at ``i``."""
    if i >= len(src) or src[i] != "<":
        return i
    depth = 0
    while i < len(src):
        depth += {"<": 1, ">": -1}.get(src[i], 0)
        i += 1
        if depth == 0:
            return i
    return i


def _read_path_argument(src: str, i: int, consts: dict) -> str | None:
    """The first call argument as a path, or None when it is not a literal."""
    while src[i].isspace():
        i += 1
    quote = src[i]
    if quote in "'\"":
        end = src.index(quote, i + 1)
        literal = src[i + 1:end]
        # '/elicitation/references/' + id
        if re.match(r"\s*\+", src[end + 1:]):
            literal += "__param__"
        return literal
    if quote == "`":
        out, i = [], i + 1
        while src[i] != "`":
            if src.startswith("${", i):
                depth, j = 1, i + 2
                while depth:
                    depth += {"{": 1, "}": -1}.get(src[j], 0)
                    j += 1
                expr = src[i + 2:j - 1].strip()
                out.append(consts.get(expr, "__param__"))
                i = j
            else:
                out.append(src[i])
                i += 1
        return "".join(out)
    ident = re.match(r"[A-Za-z_$][\w$]*", src[i:])
    if ident and ident.group(0) in consts:
        return consts[ident.group(0)]
    return None


def frontend_calls():
    calls = []
    for f in sorted(FRONTEND_SRC.rglob("*")):
        if f.suffix not in (".ts", ".vue") or "tests" in f.parts or f.name.endswith(".d.ts"):
            continue
        src = f.read_text(encoding="utf-8")
        consts = {m.group(1): m.group(3) for m in CONST.finditer(src)}
        for m in CALL.finditer(src):
            i = _skip_generic(src, m.end())
            if i >= len(src) or src[i] != "(":
                continue
            path = _read_path_argument(src, i + 1, consts)
            if path is None or not path.startswith("/"):
                continue
            path = path.split("?", 1)[0]
            line = src.count("\n", 0, m.start()) + 1
            calls.append((m.group(1).upper(), "/api" + path, f"{f.relative_to(FRONTEND_SRC)}:{line}"))
    return calls


def _served(app, method: str, path: str) -> bool:
    scope = {"type": "http", "method": method, "path": path, "root_path": "",
             "query_string": b"", "headers": []}
    for route in app.routes:
        if getattr(route, "name", None) == "spa_fallback":
            continue
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return True
    return False


CALLS = frontend_calls()


def test_the_scan_finds_the_frontend_calls():
    assert len(CALLS) > 100, CALLS
    assert ("GET", "/api/documents/", ) in {(m, p) for m, p, _ in CALLS}


@pytest.mark.parametrize("method,path,where", CALLS, ids=[f"{c[0]} {c[1]} ({c[2]})" for c in CALLS])
def test_frontend_call_hits_a_backend_route(method, path, where):
    from app.main import app
    concrete = path.replace("__param__", "x")
    assert _served(app, method, concrete), (
        f"{where}: {method} {path} matches no backend route"
        + (" (try the trailing slash)" if _served(app, method, concrete.rstrip("/") + "/") else ""))
