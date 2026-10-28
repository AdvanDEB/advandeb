#!/usr/bin/env python3
"""
mongo_auth_setup.py — prepare MongoDB authentication for AdvanDEB.

MongoDB (Docker, mongo:6.0) runs without --auth, so anyone who can reach
:27017 can read and drop every database. This creates one user per app
*while auth is still off*, so the apps can switch to credentials first and
auth can then be switched on without an outage.

    mongo_auth_setup.py plan                 show databases, users, what would change
    mongo_auth_setup.py create --apply       create/update the users (default: dry run)
    mongo_auth_setup.py write-env            put advandeb_app's URI into app/backend/.env
    mongo_auth_setup.py check                does the configured MONGODB_URI authenticate?

Passwords are generated here and kept in ~/.config/advandeb/mongo-<user>.pw
(mode 600, directory 700); they are never printed or put on a command line.
Re-running reuses existing password files, so the script is idempotent.

Once auth is enabled, pass --as-admin to authenticate as the admin user.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import envfile  # noqa: E402

SECRETS_DIR = Path.home() / ".config" / "advandeb"
# 127.0.0.1, not localhost: once the port is published on IPv4 loopback only,
# "localhost" first resolves to ::1 and is refused before falling back.
HOST = "127.0.0.1:27017"

#: Databases the AdvanDEB web app, agents and ops scripts use. Scratch
#: databases are listed explicitly: MongoDB grants have no wildcards, so a
#: script inventing a new scratch name needs a grant (or the admin user).
ADVANDEB_DATABASES = (
    "advandeb",
    "advandeb_knowledge_builder_kb",
    "deb_abstracts_reproduction",
    "deb_literature_review",
    "reproduction_db",
    "advandeb_elicit_scratch",
    "advandeb_expertref_scratch",
    "advandeb_scratch",
)

USERS = {
    # name: roles (all users live in the admin database)
    "admin": [{"role": "root", "db": "admin"}],
    "advandeb_app": [{"role": "readWrite", "db": d} for d in ADVANDEB_DATABASES],
    "cadapti_app": [{"role": "readWrite", "db": "cadapti"}],
}


def password_file(user: str) -> Path:
    return SECRETS_DIR / f"mongo-{user}.pw"


def ensure_password(user: str, create: bool) -> str | None:
    path = password_file(user)
    if path.exists():
        return path.read_text().strip()
    if not create:
        return None
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
    password = secrets.token_urlsafe(32)
    envfile.write_private(path, password + "\n")
    return password


def uri_for(user: str, password: str, host: str = HOST) -> str:
    return f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}/?authSource=admin"


def client(as_admin: bool):
    from pymongo import MongoClient

    if as_admin:
        password = ensure_password("admin", create=False)
        if password is None:
            sys.exit(f"--as-admin: {password_file('admin')} does not exist")
        return MongoClient(uri_for("admin", password), serverSelectionTimeoutMS=5000)
    return MongoClient(f"mongodb://{HOST}", serverSelectionTimeoutMS=5000)


def plan(as_admin: bool) -> None:
    c = client(as_admin)
    names = {d["name"] for d in c.list_databases()}
    existing = {u["user"] for u in c.admin.command("usersInfo").get("users", [])}
    print(f"databases: {', '.join(sorted(names))}")
    print(f"existing users in admin: {', '.join(sorted(existing)) or '(none)'}")
    unknown = sorted(names - set(ADVANDEB_DATABASES) - {"admin", "config", "local", "cadapti"})
    if unknown:
        print(f"NOT covered by any app user (only admin can reach them): {', '.join(unknown)}")
    for user, roles in USERS.items():
        action = "update roles of" if user in existing else "create"
        has_pw = "existing password file" if password_file(user).exists() else "new password file"
        print(f"would {action} {user} ({has_pw}): " + ", ".join(f"{r['role']}@{r['db']}" for r in roles))


def create(apply: bool, as_admin: bool, only: list[str]) -> None:
    c = client(as_admin)
    existing = {u["user"] for u in c.admin.command("usersInfo").get("users", [])}
    for user, roles in USERS.items():
        if only and user not in only:
            continue
        if not apply:
            print(f"[dry run] {'updateUser' if user in existing else 'createUser'} {user}")
            continue
        password = ensure_password(user, create=True)
        if user in existing:
            c.admin.command("updateUser", user, pwd=password, roles=roles)
            print(f"updated {user} (password from {password_file(user)})")
        else:
            c.admin.command("createUser", user, pwd=password, roles=roles)
            print(f"created {user} (password in {password_file(user)})")
    if not apply:
        print("dry run — re-run with --apply to create the users")


def write_env() -> None:
    password = ensure_password("advandeb_app", create=False)
    if password is None:
        sys.exit(f"{password_file('advandeb_app')} does not exist — run `create --apply` first")
    path = envfile.env_file()
    saved = envfile.rewrite(path, lambda lines: envfile.set_line(lines, "MONGODB_URI", uri_for("advandeb_app", password)))
    print(f"MONGODB_URI in {path} now authenticates as advandeb_app; backup: {saved}")
    print("next: restart advandeb.service and advandeb-stack.target, then: mongo_auth_setup.py check")


def check() -> None:
    from pymongo import MongoClient
    from pymongo.errors import OperationFailure

    values = envfile.load_values(envfile.env_file())
    uri = os.environ.get("MONGODB_URI") or values.get("MONGODB_URI", f"mongodb://{HOST}")
    db_name = values.get("MONGODB_DB_NAME", "advandeb")
    authenticated = "@" in uri.split("://", 1)[-1]
    try:
        c = MongoClient(uri, serverSelectionTimeoutMS=5000)
        c[db_name].list_collection_names()
        print(f"OK: MONGODB_URI ({'with' if authenticated else 'WITHOUT'} credentials) can read {db_name}")
    except OperationFailure as exc:
        sys.exit(f"FAILED: {exc.code} {exc.details.get('errmsg', '') if exc.details else ''}")
    try:
        MongoClient(f"mongodb://{HOST}", serverSelectionTimeoutMS=5000).list_database_names()
        print("NOTE: an unauthenticated client can still list databases — auth is not enforced yet")
    except OperationFailure:
        print("OK: unauthenticated clients are refused (auth is enforced)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "create", "write-env", "check"))
    parser.add_argument("--apply", action="store_true", help="create: actually write (default: dry run)")
    parser.add_argument("--as-admin", action="store_true", help="authenticate as admin (after auth is on)")
    parser.add_argument("--only", nargs="*", default=[], help="create: limit to these users")
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.as_admin)
    elif args.command == "create":
        create(args.apply, args.as_admin, args.only)
    elif args.command == "write-env":
        write_env()
    else:
        check()


if __name__ == "__main__":
    main()
