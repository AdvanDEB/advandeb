# Backups

Production collections were dropped once (commit `0cd580c`) and could only be
partly rebuilt, because there was no dump, no snapshot and no oplog. These
scripts make every AdvanDEB store restorable, and the guards described below
refuse irreversible operations until a recent backup exists.

## What is backed up

| Profile | When | Contents |
| --- | --- | --- |
| `daily` | Mon–Sat 03:15 | MongoDB `advandeb`, `advandeb_knowledge_builder_kb`, `deb_literature_review`; ArangoDB `advandeb_kb` |
| `weekly` | Sun 03:15 | everything in `daily`, plus MongoDB `deb_abstracts_reproduction` (~60 GB) and the ChromaDB store `data/chromadb` (~17 GB) |

Runs land in `$ADVANDEB_BACKUP_DIR` (default `~/backups/advandeb`, mode 0700):

```
20261028T031500Z-daily/
    mongo/<db>/<collection>.bson.gz             # mongorestore --gzip layout
    mongo/<db>/<collection>.metadata.json.gz
    arango/<db>/                                # arangodump, compressed
    chroma/                                     # weekly only
    manifest.json                               # written last
```

The manifest records a status, document counts and duration per component
(`mongo:<db>`, `arango:<db>`, `chroma`). A run is written as `<name>.partial`
and renamed when it ends, so an interrupted run never counts as a restore point.
Retention keeps the newest 7 good daily runs and 4 good weekly runs; failures
never prune the last good runs.

Limits worth knowing:

- MongoDB runs standalone without an oplog, so a dump of a database that is
  being written to is not a point-in-time snapshot. Counts are recorded so a
  restore can be checked.
- Backups sit on the same disk as the data. They protect against deletion and
  corruption, not against losing the disk. Copy them off the machine (see below).
- The dumps contain user records and encrypted BYOK keys. Treat the backup
  directory like `app/backend/.env`.

## Run it by hand

```bash
conda run -n advandeb python scripts/backup/advandeb_backup.py --profile daily
conda run -n advandeb python scripts/backup/advandeb_backup.py --profile daily --only arango:advandeb_kb
conda run -n advandeb python scripts/backup/advandeb_restore.py list
```

## Install the timers (needs sudo)

```bash
sudo cp scripts/systemd/advandeb-backup@.service scripts/systemd/advandeb-backup-daily.timer scripts/systemd/advandeb-backup-weekly.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now advandeb-backup-daily.timer advandeb-backup-weekly.timer
systemctl list-timers 'advandeb-backup*'
journalctl -u 'advandeb-backup@*' -n 50
```

## Restore drill

A backup nobody has restored is a hope. `verify` restores every component of a
run into throwaway `*_restore_scratch_*` databases, compares each collection's
count with the manifest, and drops the throwaway databases again:

```bash
conda run -n advandeb python scripts/backup/advandeb_restore.py verify
conda run -n advandeb python scripts/backup/advandeb_restore.py verify --run 20261028T031500Z-daily --keep-scratch
```

Run it after installing the timers and then monthly.

## Restoring for real

Restores default to a new scratch database next to production, never onto it.
Inspect the result there first.

```bash
# MongoDB: one database into a scratch copy, then (only if needed) into production.
conda run -n advandeb python scripts/backup/advandeb_restore.py mongo --db advandeb
conda run -n advandeb python scripts/backup/advandeb_restore.py mongo --db advandeb --target advandeb --confirm advandeb
```

Into production, existing non-empty collections are skipped, so a partial loss
(say, one dropped collection) is repaired without touching the rest. `--replace`
drops and restores non-empty collections too.

```bash
# ArangoDB: into a scratch database, or into the existing production database.
conda run -n advandeb python scripts/backup/advandeb_restore.py arango
conda run -n advandeb python scripts/backup/advandeb_restore.py arango --target advandeb_kb --confirm advandeb_kb --overwrite
```

ChromaDB: stop the retrieval agent, move `data/chromadb` aside, copy the run's
`chroma/` directory into its place, start the agent again.

## Guards that depend on these backups

- `advandeb_kb.backup_guard.require_recent_backup(component, max_age_hours)`
  raises unless a backup of that component succeeded recently.
- `POST /api/kb/db/reset` needs the database name typed back and an ArangoDB
  backup newer than `KB_RESET_MAX_BACKUP_AGE_HOURS` (default 26 h).
- `knowledge-builder/scripts/migrate_mongo_to_arango.py` wipes ArangoDB only
  with `--confirm-wipe <db>` and a recent backup; it used to wipe by default.
- `ArangoDatabase.setup_schema(drop_existing=True)` needs `confirm_drop=<db>`
  and a recent backup.
- Scripts that drop collections on purpose (`app/backend/tests/verify_*.py`)
  check the database handle they actually use with `app.core.dbguard`, which
  refuses anything not named as scratch.

## Off-machine copy

Not configured yet. Any of these works with the run directories as they are:
`rsync -a --delete ~/backups/advandeb/ <host>:advandeb-backups/` to another
machine, `rclone sync` to object storage, or a USB disk rotated weekly.
