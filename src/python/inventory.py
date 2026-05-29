#!/usr/bin/env python3
"""Compatibility wrapper for footage inventory reports."""

from __future__ import annotations

import argparse
import os

from videoedit.inventory import build_inventory, write_inventory_csv, write_inventory_json, write_inventory_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan footage directory and generate inventory reports")
    parser.add_argument("directory", help="Directory to scan")
    parser.add_argument("--output", "-o", default="inventory", help="Output filename base")
    parser.add_argument("--csv-only", action="store_true", help="Generate CSV only")
    parser.add_argument("--json-only", action="store_true", help="Generate JSON only")
    args = parser.parse_args()

    directory = os.fspath(args.directory)
    if not os.path.exists(directory):
        parser.error(f"Directory not found: {directory}")

    items = build_inventory(directory)
    if not items:
        print("No video files found.")
        return 0

    base = os.fspath(args.output)
    if not args.json_only:
        write_inventory_csv(items, _with_suffix(base, ".csv"))
    if not args.csv_only and not args.json_only:
        write_inventory_markdown(items, _with_suffix(base, ".md"))
    if not args.csv_only:
        write_inventory_json(items, _with_suffix(base, ".json"))

    print(f"Found {len(items)} video files")
    return 0


def _with_suffix(path: str, suffix: str) -> str:
    return os.path.splitext(path)[0] + suffix


if __name__ == "__main__":
    raise SystemExit(main())
