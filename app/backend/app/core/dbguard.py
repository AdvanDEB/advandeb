"""Refuse destructive operations against the production database.

Written after a verification script dropped two production collections
(`stylized_facts`, 1,262 docs; `documents`, 1,695 docs — the latter
unrecoverable, there is no backup). The script did this:

    os.environ.setdefault("MONGODB_DB_NAME", "advandeb_scratch")

which looks defensive and is not. The environment had already been loaded from
``app/backend/.env``, which exports ``MONGODB_DB_NAME=advandeb``, so
``setdefault`` was a no-op and every ``drop()`` ran against production.

The general shape of the mistake is worth naming, because it will recur in a
different disguise: **a default is not a guard.** A default expresses a
preference about the unset case; it says nothing when the value is already set,
which is exactly the situation where the damage happens. A guard has to
*assert*, and it has to fail closed.

Usage in any script that drops, deletes or overwrites at scale::

    from app.core.dbguard import require_scratch_db
    db_name = require_scratch_db()          # raises unless clearly non-production

Or, when the name is already in hand::

    assert_not_production(db_name)
"""

from __future__ import annotations

import os

# Databases that must never be the target of a destructive test operation.
PRODUCTION_DATABASES = {
    "advandeb",
    "advandeb_kb",
    "advandeb_knowledge_builder_kb",
    "deb_literature_review",
    "deb_abstracts_reproduction",
    "reproduction_db",
}

# A scratch database has to say so in its name. Requiring the marker — rather
# than merely excluding the known production names — is what makes this fail
# closed: a database nobody has classified is treated as dangerous, not as safe.
SCRATCH_MARKERS = ("scratch", "_test", "test_", "sandbox", "tmp")


class ProductionDatabaseError(RuntimeError):
    """Raised when a destructive operation would hit production."""


def is_scratch(db_name: str) -> bool:
    name = (db_name or "").strip().lower()
    if not name or name in PRODUCTION_DATABASES:
        return False
    return any(m in name for m in SCRATCH_MARKERS)


def assert_not_production(db_name: str, operation: str = "destructive operation") -> None:
    """Raise unless ``db_name`` is unmistakably a scratch database."""
    if is_scratch(db_name):
        return
    raise ProductionDatabaseError(
        f"refusing {operation} against database {db_name!r}.\n"
        f"A scratch database must carry one of {SCRATCH_MARKERS} in its name.\n"
        f"Set MONGODB_DB_NAME explicitly, e.g. MONGODB_DB_NAME=advandeb_scratch, "
        f"and do not rely on os.environ.setdefault — if the variable is already "
        f"set (sourcing .env sets it), setdefault does nothing and the target "
        f"stays production."
    )


def require_scratch_db(env_var: str = "MONGODB_DB_NAME") -> str:
    """Return the configured database name, or raise if it is not scratch.

    Deliberately reads the environment *as it actually is* rather than applying
    a default, because the incident this exists to prevent was caused by a
    default silently not applying.
    """
    name = os.environ.get(env_var, "")
    if not name:
        raise ProductionDatabaseError(
            f"{env_var} is not set. Set it explicitly to a scratch database; "
            f"this helper will not guess one, because guessing is how the "
            f"previous incident happened."
        )
    assert_not_production(name, f"use of {env_var}")
    return name
