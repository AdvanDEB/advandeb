#!/usr/bin/env python
"""Rotate the ArangoDB password in ArangoDB and app/backend/.env together.

Written because the production password was committed to the public
repository (knowledge-builder/scripts/migrate_mongo_to_arango.py, from commit
b1999819 until it was removed). Removing it from the code does not un-publish
it; only a new password does.

Every service authenticates on every HTTP request, so the moment the password
changes the running backend and agents start getting 401s. Restart them right
after this script:

    conda run -n advandeb python scripts/ops/rotate_arango_password.py            # dry run
    conda run -n advandeb python scripts/ops/rotate_arango_password.py --apply
    sudo systemctl restart advandeb.target

Order of operations, so that a failure never leaves the two out of step:
the new .env is written to a private temp file first, then the password is
changed and verified in ArangoDB, and only then does the temp file replace
.env (the old .env is kept as .env.bak-<timestamp>, mode 0600).
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / "app" / "backend" / ".env"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="actually rotate (default: dry run)")
    args = parser.parse_args()

    from arango import ArangoClient
    from dotenv import dotenv_values

    env = dotenv_values(ENV_FILE)
    url = env.get("ARANGO_URL") or "http://localhost:8529"
    user = env.get("ARANGO_USERNAME") or "root"
    old = env.get("ARANGO_PASSWORD") or ""
    client = ArangoClient(hosts=url)
    client.db("_system", username=user, password=old).properties()   # current login works

    text = ENV_FILE.read_text()
    if not re.search(r"^ARANGO_PASSWORD=.*$", text, flags=re.M):
        sys.exit(f"no ARANGO_PASSWORD line in {ENV_FILE}")
    if not args.apply:
        print(f"dry run: would set a new random password for ArangoDB user {user!r} at {url} "
              f"and update ARANGO_PASSWORD in {ENV_FILE}. Re-run with --apply.")
        return 0

    new = secrets.token_urlsafe(24)
    fd, tmp = tempfile.mkstemp(dir=ENV_FILE.parent, prefix=".env.rotate-")
    with os.fdopen(fd, "w") as fh:
        fh.write(re.sub(r"^ARANGO_PASSWORD=.*$", f"ARANGO_PASSWORD={new}", text, flags=re.M))

    try:
        sys_db = client.db("_system", username=user, password=old)
        sys_db.update_user(username=user, password=new)
        client.db("_system", username=user, password=new).properties()
    except Exception:
        os.unlink(tmp)
        raise

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ENV_FILE.with_name(f".env.bak-{stamp}")
    shutil.copy2(ENV_FILE, backup)
    os.chmod(backup, 0o600)
    os.replace(tmp, ENV_FILE)
    os.chmod(ENV_FILE, 0o600)
    print(f"rotated the password of {user!r}; {ENV_FILE} updated (old copy: {backup}).")
    print("Now restart the services: sudo systemctl restart advandeb.target")
    print(f"Once they are healthy, delete the old copy: rm {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
