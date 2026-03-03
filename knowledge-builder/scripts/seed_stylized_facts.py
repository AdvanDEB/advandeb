"""
Seed stylized facts from CSV files into MongoDB.

Reads the second column (statement text) and first column (sf_number) from
each CSV file in the configured source directory and upserts StylizedFact
documents into MongoDB.

The category is derived from the CSV filename (without .csv extension).

Usage:
    conda run -n advandeb-modeling-assistant python scripts/seed_stylized_facts.py
    conda run -n advandeb-modeling-assistant python scripts/seed_stylized_facts.py --dry-run
    conda run -n advandeb-modeling-assistant python scripts/seed_stylized_facts.py --csv-dir /path/to/csvs
"""
import argparse
import asyncio
import csv
import logging
import os
import sys
from pathlib import Path
from typing import List, Tuple

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import mongodb
from advandeb_kb.models.knowledge import StylizedFact

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CSV_DIR = os.path.expanduser(
    "~/dev/advandeb_auxiliary/stylized_DEB/csv_files/"
)


def load_sfs_from_csv(path: Path) -> List[Tuple[int, str, str]]:
    """Return list of (sf_number, statement, category) tuples from one CSV file.

    Only the first and second columns are read; all other columns are ignored.
    The header row and any rows with an empty statement are skipped.
    """
    category = path.stem  # filename without .csv
    results: List[Tuple[int, str, str]] = []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0:
                continue  # skip header
            if len(row) < 2:
                continue
            number_raw = row[0].strip()
            statement = row[1].strip()
            if not statement:
                continue
            sf_number = int(number_raw) if number_raw.isdigit() else None
            results.append((sf_number, statement, category))

    return results


def load_all_sfs(csv_dir: str) -> List[Tuple[int, str, str]]:
    """Load SFs from all CSV files in the given directory."""
    csv_dir_path = Path(csv_dir)
    if not csv_dir_path.is_dir():
        raise FileNotFoundError(f"CSV directory not found: {csv_dir}")

    all_sfs: List[Tuple[int, str, str]] = []
    csv_files = sorted(csv_dir_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in: {csv_dir}")

    for path in csv_files:
        sfs = load_sfs_from_csv(path)
        logger.info(f"  {path.name}: {len(sfs)} stylized facts (category: {path.stem})")
        all_sfs.extend(sfs)

    return all_sfs


async def seed(csv_dir: str, dry_run: bool = False) -> dict:
    """Upsert all stylized facts from the CSV files into MongoDB.

    Returns a summary dict with counts.
    """
    logger.info(f"Loading SFs from: {csv_dir}")
    all_sfs = load_all_sfs(csv_dir)
    logger.info(f"Total: {len(all_sfs)} stylized facts across {len(set(c for _, _, c in all_sfs))} categories")

    if dry_run:
        logger.info("Dry-run mode — no database writes.")
        categories = {}
        for _, _, cat in all_sfs:
            categories[cat] = categories.get(cat, 0) + 1
        for cat, count in sorted(categories.items()):
            logger.info(f"  {cat}: {count}")
        return {"total": len(all_sfs), "inserted": 0, "updated": 0, "dry_run": True}

    await mongodb.connect()
    db = mongodb.database

    inserted = 0
    updated = 0

    for sf_number, statement, category in all_sfs:
        sf = StylizedFact(
            statement=statement,
            category=category,
            sf_number=sf_number,
            status="published",  # seed data is authoritative
        )
        data = sf.model_dump(by_alias=True)

        # Upsert: match on (sf_number, category) if number exists, else on statement
        if sf_number is not None:
            filter_ = {"sf_number": sf_number, "category": category}
        else:
            filter_ = {"statement": statement, "category": category}

        result = await db.stylized_facts.update_one(
            filter_,
            {"$setOnInsert": data},
            upsert=True,
        )
        if result.upserted_id:
            inserted += 1
        elif result.matched_count:
            updated += 1

    await mongodb.disconnect()

    logger.info(f"Done — inserted: {inserted}, already existed: {updated}")
    return {"total": len(all_sfs), "inserted": inserted, "already_existed": updated}


def main():
    parser = argparse.ArgumentParser(description="Seed stylized facts from CSV files.")
    parser.add_argument(
        "--csv-dir",
        default=DEFAULT_CSV_DIR,
        help=f"Directory containing SF CSV files (default: {DEFAULT_CSV_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count without writing to the database.",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.csv_dir, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
