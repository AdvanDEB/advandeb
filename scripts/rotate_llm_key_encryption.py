#!/usr/bin/env python3
"""
rotate_llm_key_encryption.py — rotate the BYOK Fernet key (LLM_KEY_ENCRYPTION_KEY).

Stored user secrets (``user_llm_keys``: encrypted_key, encrypted_access_token,
encrypted_refresh_token) are re-encrypted under the current primary key. The
web app and chatbot_agent accept LLM_KEY_ENCRYPTION_KEY_PREVIOUS for
decryption during the rotation, so nobody's key stops working at any point.

Procedure (see the operator checklist; every step is reversible until the
last one):

  1. --generate-key FILE          write a fresh random key to FILE (mode 600)
  2. --stage-env FILE             in app/backend/.env: new key → LLM_KEY_ENCRYPTION_KEY,
                                  old key → LLM_KEY_ENCRYPTION_KEY_PREVIOUS
                                  (backup of the old .env kept, mode 600)
  3. restart advandeb.service + advandeb-agent@chatbot_agent.service
  4. (no flag)                    DRY RUN: report what would be re-encrypted
  5. --apply                      re-encrypt every field under the primary key
  6. (no flag)                    dry run again: everything should be "primary"
  7. --finish-env                 remove LLM_KEY_ENCRYPTION_KEY_PREVIOUS (and the
                                  old passphrase comment), then restart again

Nothing secret is ever printed: only counts, field names and document ids.
Default is a dry run; writes need --apply.
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import envfile  # noqa: E402

FIELDS = ("encrypted_key", "encrypted_access_token", "encrypted_refresh_token")
COLLECTION = "user_llm_keys"
OVERRIDABLE = ("MONGODB_URI", "MONGODB_DB_NAME", "LLM_KEY_ENCRYPTION_KEY", "LLM_KEY_ENCRYPTION_KEY_PREVIOUS")


def load_values(path: Path) -> dict:
    values = envfile.load_values(path)
    values.update({k: v for k, v in os.environ.items() if k in OVERRIDABLE})
    return values


def split_keys(value: str | None) -> list[str]:
    return [k.strip() for k in (value or "").split(",") if k.strip()]


# ── env-file editing ─────────────────────────────────────────────────────────

def stage_env(new_key_file: Path) -> None:
    from cryptography.fernet import Fernet

    path = envfile.env_file()
    values = load_values(path)
    old = values.get("LLM_KEY_ENCRYPTION_KEY")
    new = new_key_file.read_text().strip()
    Fernet(new.encode())  # validates, raises without echoing the key
    if not old:
        sys.exit("LLM_KEY_ENCRYPTION_KEY is not set in the env file; nothing to rotate")
    if new == old:
        sys.exit("the new key equals the current key")
    previous = [k for k in split_keys(values.get("LLM_KEY_ENCRYPTION_KEY_PREVIOUS")) if k != new]

    def edit(lines):
        lines = envfile.set_line(lines, "LLM_KEY_ENCRYPTION_KEY", new)
        lines = envfile.set_line(lines, "LLM_KEY_ENCRYPTION_KEY_PREVIOUS", ",".join([old, *previous]))
        # The comment that recorded the passphrase the old key was derived from.
        return envfile.drop_comments_matching(lines, "passphrase")

    saved = envfile.rewrite(path, edit)
    print(f"staged: {path} now holds the new primary key and the old one as _PREVIOUS")
    print(f"backup of the previous file: {saved} (mode 600; delete once the rotation is done)")
    print("next: restart advandeb.service and advandeb-agent@chatbot_agent.service, then dry-run this script")


def finish_env() -> None:
    path = envfile.env_file()

    def edit(lines):
        lines = envfile.set_line(lines, "LLM_KEY_ENCRYPTION_KEY_PREVIOUS", None)
        return envfile.drop_comments_matching(lines, "passphrase")

    saved = envfile.rewrite(path, edit)
    print(f"finished: LLM_KEY_ENCRYPTION_KEY_PREVIOUS removed from {path}; backup {saved}")
    print("next: restart advandeb.service and advandeb-agent@chatbot_agent.service")


# ── re-encryption ────────────────────────────────────────────────────────────

def classify(token: str, primary, previous: list) -> str:
    from cryptography.fernet import InvalidToken

    try:
        primary.decrypt(token.encode())
        return "primary"
    except InvalidToken:
        pass
    for f in previous:
        try:
            f.decrypt(token.encode())
            return "previous"
        except InvalidToken:
            continue
    return "undecryptable"


def rotate(apply: bool) -> int:
    from cryptography.fernet import Fernet, MultiFernet
    from pymongo import MongoClient

    values = load_values(envfile.env_file())
    primary_key = values.get("LLM_KEY_ENCRYPTION_KEY")
    if not primary_key:
        sys.exit("LLM_KEY_ENCRYPTION_KEY is not set")
    primary = Fernet(primary_key.encode())
    previous = [Fernet(k.encode()) for k in split_keys(values.get("LLM_KEY_ENCRYPTION_KEY_PREVIOUS"))]
    multi = MultiFernet([primary, *previous])

    uri = values.get("MONGODB_URI", "mongodb://localhost:27017")
    db_name = values.get("MONGODB_DB_NAME", "advandeb")
    collection = MongoClient(uri, serverSelectionTimeoutMS=5000)[db_name][COLLECTION]

    counts = {"primary": 0, "previous": 0, "undecryptable": 0}
    undecryptable: list[str] = []
    rewritten = 0
    docs = 0
    for doc in collection.find({}, {f: 1 for f in FIELDS}):
        docs += 1
        update = {}
        for field in FIELDS:
            token = doc.get(field)
            if not token:
                continue
            kind = classify(token, primary, previous)
            counts[kind] += 1
            if kind == "undecryptable":
                undecryptable.append(f"{doc['_id']}.{field}")
            elif kind == "previous":
                update[field] = multi.rotate(token.encode()).decode()
        if update and apply:
            # Only overwrite if the stored value is still the one we read, so a
            # concurrent token refresh by the app is never clobbered.
            match = {"_id": doc["_id"], **{f: doc[f] for f in update}}
            rewritten += collection.update_one(match, {"$set": update}).modified_count

    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] {db_name}.{COLLECTION}: {docs} documents")
    print(f"  fields under the primary key : {counts['primary']}")
    print(f"  fields under a previous key  : {counts['previous']}"
          + ("" if apply else "  (would be re-encrypted with --apply)"))
    print(f"  undecryptable with any key   : {counts['undecryptable']}")
    for ref in undecryptable:
        print(f"    {ref}")
    if apply:
        print(f"  re-encrypted documents       : {rewritten}")
    if counts["undecryptable"]:
        print("Undecryptable fields were left untouched; those users must re-enter their key.")
    return 1 if counts["undecryptable"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--generate-key", metavar="FILE", type=Path,
                       help="write a new random Fernet key to FILE (mode 600) and exit")
    group.add_argument("--stage-env", metavar="FILE", type=Path,
                       help="install the key in FILE as primary, current key as _PREVIOUS")
    group.add_argument("--finish-env", action="store_true",
                       help="drop LLM_KEY_ENCRYPTION_KEY_PREVIOUS from the env file")
    group.add_argument("--apply", action="store_true", help="re-encrypt (default: dry run)")
    args = parser.parse_args()

    if args.generate_key:
        from cryptography.fernet import Fernet

        if args.generate_key.exists():
            sys.exit(f"{args.generate_key} exists; refusing to overwrite a key file")
        envfile.write_private(args.generate_key, Fernet.generate_key().decode() + "\n")
        mode = stat.filemode(args.generate_key.stat().st_mode)
        print(f"wrote a new key to {args.generate_key} ({mode}); the key itself is not printed")
        return
    if args.stage_env:
        stage_env(args.stage_env)
        return
    if args.finish_env:
        finish_env()
        return
    sys.exit(rotate(apply=args.apply))


if __name__ == "__main__":
    main()
