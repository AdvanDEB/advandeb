"""
Tests for the SF seed importer (CSV → StylizedFact).
Run with: conda run -n advandeb-modeling-assistant python3 tests/test_sf_seed.py
"""
import csv
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed_stylized_facts import load_sfs_from_csv, load_all_sfs


def _make_csv(path: Path, rows: list):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Number", "DEB Stylized Fact", "Accuracy", "Extra"])
        for row in rows:
            w.writerow(row)


def test_load_single_csv():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "reproductive_strategy.csv"
        _make_csv(path, [
            ["301", "Energy investment scales with body size.", "high", "ignored"],
            ["302", "Trade-off between offspring size and number.", "", ""],
            ["303", "", "", ""],   # empty statement — should be skipped
            ["abc", "Non-numeric number.", "", ""],  # non-numeric sf_number
        ])
        sfs = load_sfs_from_csv(path)

        assert len(sfs) == 3
        assert sfs[0] == (301, "Energy investment scales with body size.", "reproductive_strategy")
        assert sfs[1] == (302, "Trade-off between offspring size and number.", "reproductive_strategy")
        assert sfs[2] == (None, "Non-numeric number.", "reproductive_strategy")
    print("  load_sfs_from_csv OK")


def test_load_all_csvs():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_csv(Path(tmpdir) / "reproduction.csv", [
            ["1", "Fact A.", "", ""],
            ["2", "Fact B.", "", ""],
        ])
        _make_csv(Path(tmpdir) / "metabolism.csv", [
            ["101", "Fact C.", "", ""],
        ])
        sfs = load_all_sfs(tmpdir)

        assert len(sfs) == 3
        categories = {cat for _, _, cat in sfs}
        assert categories == {"reproduction", "metabolism"}
    print("  load_all_csvs OK")


def test_empty_csv_skipped():
    with tempfile.TemporaryDirectory() as tmpdir:
        # File with only a header row
        _make_csv(Path(tmpdir) / "empty_cat.csv", [])
        sfs = load_all_sfs(tmpdir)
        assert sfs == []
    print("  empty_csv_skipped OK")


def test_real_csv_dir():
    """Validate the actual SF CSV files can be parsed without errors."""
    real_dir = os.path.expanduser("~/dev/advandeb_auxiliary/stylized_DEB/csv_files/")
    if not os.path.isdir(real_dir):
        print("  real_csv_dir SKIPPED (directory not found)")
        return

    sfs = load_all_sfs(real_dir)

    assert len(sfs) > 1000, f"Expected >1000 SFs, got {len(sfs)}"

    # Every entry must have a non-empty statement and category
    for sf_number, statement, category in sfs:
        assert statement, f"Empty statement found in category {category}"
        assert category, "Empty category found"

    # sf_numbers must be unique within each category
    by_category: dict = {}
    for sf_number, _, category in sfs:
        if sf_number is None:
            continue
        if category not in by_category:
            by_category[category] = set()
        assert sf_number not in by_category[category], (
            f"Duplicate sf_number {sf_number} in category {category}"
        )
        by_category[category].add(sf_number)

    categories = {cat for _, _, cat in sfs}
    print(f"  real_csv_dir OK — {len(sfs)} SFs across {len(categories)} categories")
    for cat in sorted(categories):
        count = sum(1 for _, _, c in sfs if c == cat)
        print(f"    {cat}: {count}")


if __name__ == "__main__":
    tests = [
        test_load_single_csv,
        test_load_all_csvs,
        test_empty_csv_skipped,
        test_real_csv_dir,
    ]
    print(f"Running {len(tests)} SF seed tests...")
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")
