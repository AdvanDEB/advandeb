"""
Import NCBI Taxonomy into MongoDB.

Downloads the NCBI taxdump (nodes.dmp + names.dmp), parses the full tree,
pre-materialises the lineage array for each node, and bulk-inserts into
the `taxonomy_nodes` collection.

Usage:
    # Full import (downloads ~55 MB, inserts ~2.4 M nodes):
    conda run -n advandeb-modeling-assistant python scripts/import_taxonomy.py

    # Dry-run (parse only, no DB writes):
    conda run -n advandeb-modeling-assistant python scripts/import_taxonomy.py --dry-run

    # Use a previously downloaded dump:
    conda run -n advandeb-modeling-assistant python scripts/import_taxonomy.py \\
        --taxdump /path/to/taxdump.tar.gz

    # Restrict to a subtree (e.g. Metazoa, tax_id=33208):
    conda run -n advandeb-modeling-assistant python scripts/import_taxonomy.py \\
        --root-taxid 33208

Indexes created automatically:
    taxonomy_nodes.tax_id          (unique)
    taxonomy_nodes.parent_tax_id
    taxonomy_nodes.rank
    taxonomy_nodes.name            (text)
    taxonomy_nodes.lineage
"""
import argparse
import asyncio
import io
import logging
import os
import sys
import tarfile
import tempfile
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import mongodb

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TAXDUMP_URL = "https://ftp.ncbi.nih.gov/pub/taxonomy/taxdump.tar.gz"
BULK_SIZE = 5_000  # documents per insert_many call


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _iter_dmp(fileobj: io.IOBase, ncols: int = None) -> Iterator[List[str]]:
    """Yield rows from a .dmp file (tab|tab-delimited, ends with '\t|\n')."""
    for raw in fileobj:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        # Strip trailing newline and the field terminator '\t|'
        line = raw.rstrip("\n").rstrip("\t|")
        parts = [p.strip() for p in line.split("\t|\t")]
        if ncols and len(parts) < ncols:
            continue
        yield parts


def parse_nodes(fileobj: io.IOBase) -> Dict[int, Dict]:
    """Parse nodes.dmp → {tax_id: {parent_tax_id, rank}}."""
    nodes: Dict[int, Dict] = {}
    for parts in _iter_dmp(fileobj):
        if len(parts) < 3:
            continue
        tax_id = int(parts[0])
        parent_tax_id = int(parts[1])
        rank = parts[2]
        nodes[tax_id] = {
            "parent_tax_id": parent_tax_id if parent_tax_id != tax_id else None,
            "rank": rank,
        }
    logger.info(f"Parsed {len(nodes):,} nodes")
    return nodes


def parse_names(fileobj: io.IOBase) -> Dict[int, Dict]:
    """Parse names.dmp → {tax_id: {name, synonyms, common_names}}."""
    names: Dict[int, Dict] = defaultdict(
        lambda: {"name": None, "synonyms": [], "common_names": []}
    )
    for parts in _iter_dmp(fileobj):
        if len(parts) < 4:
            continue
        tax_id = int(parts[0])
        name_txt = parts[1]
        name_class = parts[3]
        if name_class == "scientific name":
            names[tax_id]["name"] = name_txt
        elif name_class in ("synonym", "equivalent name", "includes"):
            names[tax_id]["synonyms"].append(name_txt)
        elif name_class in ("common name", "genbank common name"):
            names[tax_id]["common_names"].append(name_txt)
    logger.info(f"Parsed names for {len(names):,} taxa")
    return dict(names)


def build_lineages(
    nodes: Dict[int, Dict],
    root_taxid: Optional[int] = None,
) -> Dict[int, List[int]]:
    """Pre-materialise ancestor lineages (root → parent) for every node.

    If root_taxid is given, only nodes in that subtree are included.
    """
    logger.info("Building lineages (this may take ~30 s for the full tree)…")

    # Build child → parent map
    parent_of: Dict[int, Optional[int]] = {
        tid: info["parent_tax_id"] for tid, info in nodes.items()
    }

    def _ancestors(tid: int) -> List[int]:
        path: List[int] = []
        current = parent_of.get(tid)
        seen: Set[int] = {tid}
        while current is not None and current not in seen:
            path.append(current)
            seen.add(current)
            current = parent_of.get(current)
        path.reverse()
        return path

    if root_taxid is not None:
        # Collect all descendants of root_taxid using BFS
        children_of: Dict[int, List[int]] = defaultdict(list)
        for tid, parent in parent_of.items():
            if parent is not None:
                children_of[parent].append(tid)

        subtree: Set[int] = set()
        queue = [root_taxid]
        while queue:
            node = queue.pop()
            subtree.add(node)
            queue.extend(children_of.get(node, []))
        taxa_to_process = subtree
        logger.info(f"Restricting to subtree of {root_taxid}: {len(taxa_to_process):,} nodes")
    else:
        taxa_to_process = set(nodes.keys())

    lineages: Dict[int, List[int]] = {}
    for tid in taxa_to_process:
        lineages[tid] = _ancestors(tid)

    logger.info(f"Built {len(lineages):,} lineages")
    return lineages


def iter_documents(
    nodes: Dict[int, Dict],
    names: Dict[int, Dict],
    lineages: Dict[int, List[int]],
) -> Iterator[Dict]:
    """Yield MongoDB documents ready for insert_many."""
    now = datetime.utcnow()
    for tax_id, lineage in lineages.items():
        node = nodes[tax_id]
        name_info = names.get(tax_id, {})
        scientific_name = name_info.get("name") or f"taxon:{tax_id}"
        yield {
            "tax_id": tax_id,
            "name": scientific_name,
            "rank": node["rank"],
            "parent_tax_id": node["parent_tax_id"],
            "lineage": lineage,
            "synonyms": name_info.get("synonyms", []),
            "common_names": name_info.get("common_names", []),
            "gbif_usage_key": None,
            "ncbi_sourced": True,
            "created_at": now,
            "updated_at": now,
        }


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_taxdump(dest_dir: str) -> str:
    """Download taxdump.tar.gz to dest_dir and return the local path."""
    dest_path = os.path.join(dest_dir, "taxdump.tar.gz")
    logger.info(f"Downloading {TAXDUMP_URL} …")

    def _progress(block_count, block_size, total_size):
        if total_size > 0:
            pct = block_count * block_size * 100 // total_size
            if pct % 10 == 0:
                logger.info(f"  {pct}%")

    urllib.request.urlretrieve(TAXDUMP_URL, dest_path, reporthook=_progress)
    logger.info(f"Downloaded to {dest_path}")
    return dest_path


def open_taxdump(taxdump_path: str) -> Tuple[io.IOBase, io.IOBase]:
    """Return (nodes_fileobj, names_fileobj) from the tar.gz."""
    tf = tarfile.open(taxdump_path, "r:gz")
    nodes_member = tf.getmember("nodes.dmp")
    names_member = tf.getmember("names.dmp")
    return tf.extractfile(nodes_member), tf.extractfile(names_member)


# ---------------------------------------------------------------------------
# MongoDB import
# ---------------------------------------------------------------------------

async def ensure_indexes(db) -> None:
    col = db.taxonomy_nodes
    await col.create_index("tax_id", unique=True)
    await col.create_index("parent_tax_id")
    await col.create_index("rank")
    await col.create_index("lineage")
    await col.create_index([("name", "text")])
    logger.info("Indexes ensured on taxonomy_nodes")


async def insert_documents(db, docs: List[Dict]) -> int:
    """Upsert a batch of taxonomy documents by tax_id."""
    from pymongo import UpdateOne
    ops = [
        UpdateOne(
            {"tax_id": d["tax_id"]},
            {"$setOnInsert": d},
            upsert=True,
        )
        for d in docs
    ]
    result = await db.taxonomy_nodes.bulk_write(ops, ordered=False)
    return result.upserted_count


async def run_import(
    taxdump_path: str,
    root_taxid: Optional[int],
    dry_run: bool,
) -> Dict:
    logger.info("Parsing nodes.dmp …")
    nodes_fobj, names_fobj = open_taxdump(taxdump_path)
    nodes = parse_nodes(nodes_fobj)
    logger.info("Parsing names.dmp …")
    names = parse_names(names_fobj)
    lineages = build_lineages(nodes, root_taxid=root_taxid)

    total = len(lineages)
    logger.info(f"Total documents to import: {total:,}")

    if dry_run:
        logger.info("Dry-run mode — no database writes.")
        # Sample a few entries
        sample = list(iter_documents(nodes, names, lineages))[:3]
        for d in sample:
            logger.info(f"  Sample: {d['tax_id']} {d['name']} ({d['rank']}) lineage={d['lineage'][-3:]}")
        return {"total": total, "inserted": 0, "dry_run": True}

    await mongodb.connect()
    db = mongodb.database
    await ensure_indexes(db)

    inserted = 0
    batch: List[Dict] = []
    for i, doc in enumerate(iter_documents(nodes, names, lineages), 1):
        batch.append(doc)
        if len(batch) >= BULK_SIZE:
            inserted += await insert_documents(db, batch)
            batch.clear()
            if i % 100_000 == 0:
                logger.info(f"  {i:,}/{total:,} processed, {inserted:,} new …")
    if batch:
        inserted += await insert_documents(db, batch)

    await mongodb.disconnect()
    logger.info(f"Done — {inserted:,} new nodes inserted ({total:,} total processed)")
    return {"total": total, "inserted": inserted}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import NCBI Taxonomy into MongoDB.")
    parser.add_argument(
        "--taxdump",
        default=None,
        help="Path to existing taxdump.tar.gz. Downloads from NCBI if not given.",
    )
    parser.add_argument(
        "--root-taxid",
        type=int,
        default=None,
        help="Restrict import to the subtree rooted at this NCBI tax_id "
             "(e.g. 33208 = Metazoa, 7742 = Vertebrata). Imports all taxa if omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report counts without writing to MongoDB.",
    )
    args = parser.parse_args()

    if args.taxdump:
        taxdump_path = args.taxdump
    else:
        tmpdir = tempfile.mkdtemp(prefix="taxdump_")
        taxdump_path = download_taxdump(tmpdir)

    asyncio.run(
        run_import(
            taxdump_path=taxdump_path,
            root_taxid=args.root_taxid,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
