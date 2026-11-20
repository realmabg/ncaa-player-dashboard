#!/usr/bin/env python3
"""Add missing tier-similarity stats to the historical player bundles.

The dashboard's historical similarity export was built before the tiered
comparison view needed eFG/FT and midrange/dunk fields. The parent TROP
workspace keeps the fuller BartTorvik + PBP season snapshots, so this script
uses those files to enrich the thin historical CSVs reproducibly.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
from pathlib import Path


ADD_COLUMNS = [
    "eFG",
    "FT_pct",
    "mid_pct",
    "mid_share",
    "dunk_pct",
    "dunk_share",
    "assisted_fg_pct",
    "three_assisted_pct",
    "rim_assisted_pct",
]


def clean_key(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def to_float(value: str | None) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return math.nan
    return num if math.isfinite(num) else math.nan


def format_num(value: float) -> str:
    if not math.isfinite(value):
        return ""
    return f"{value:.10g}"


def ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0:
        return math.nan
    return numerator / denominator


def build_source_lookup(source_dir: Path, years: range) -> dict[tuple[int, str, str], dict[str, str]]:
    lookup: dict[tuple[int, str, str], dict[str, str]] = {}
    for year in years:
        path = source_dir / f"trank_final_data_{year}_with_pbp.csv"
        if not path.exists():
            continue
        with path.open(newline="", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                player = clean_key(row.get("player_name"))
                team = clean_key(row.get("team"))
                if not player or not team:
                    continue

                rim_attempts = to_float(row.get("rim_attempts"))
                mid_attempts = to_float(row.get("mid_attempts"))
                three_attempts = to_float(row.get("3PA"))
                total_known_fga = rim_attempts + mid_attempts + three_attempts
                if not math.isfinite(total_known_fga) or total_known_fga <= 0:
                    total_known_fga = math.nan

                mid_share = mid_attempts / total_known_fga if math.isfinite(total_known_fga) else math.nan
                dunk_share = to_float(row.get("dunks_attempts")) / total_known_fga if math.isfinite(total_known_fga) else math.nan
                rim_made = to_float(row.get("pbp_rim_made"))
                dunk_made = to_float(row.get("pbp_dunk_made"))
                mid_made = to_float(row.get("pbp_mid_made"))
                three_made = to_float(row.get("pbp_three_made"))
                rim_assisted = to_float(row.get("pbp_rim_assisted"))
                dunk_assisted = to_float(row.get("pbp_dunk_assisted"))
                mid_assisted = to_float(row.get("pbp_mid_assisted"))
                three_assisted = to_float(row.get("pbp_three_assisted"))
                rim_dunk_made = rim_made + dunk_made
                rim_dunk_assisted = rim_assisted + dunk_assisted
                total_made = rim_dunk_made + mid_made + three_made
                total_assisted = rim_dunk_assisted + mid_assisted + three_assisted

                lookup[(year, player, team)] = {
                    "eFG": format_num(to_float(row.get("eFG"))),
                    "FT_pct": format_num(to_float(row.get("FT_pct"))),
                    "mid_pct": format_num(to_float(row.get("mid_pct"))),
                    "mid_share": format_num(mid_share),
                    "dunk_pct": format_num(to_float(row.get("dunk_pct"))),
                    "dunk_share": format_num(dunk_share),
                    "assisted_fg_pct": format_num(ratio(total_assisted, total_made)),
                    "three_assisted_pct": format_num(ratio(three_assisted, three_made)),
                    "rim_assisted_pct": format_num(ratio(rim_dunk_assisted, rim_dunk_made)),
                }
    return lookup


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def augment_file(path: Path, lookup: dict[tuple[int, str, str], dict[str, str]]) -> int:
    fieldnames, rows = read_rows(path)
    for col in ADD_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    updated = 0
    for row in rows:
        year = int(to_float(row.get("year"))) if math.isfinite(to_float(row.get("year"))) else None
        if year is None:
            continue
        source = lookup.get((year, clean_key(row.get("player_name")), clean_key(row.get("team"))))
        if not source:
            continue
        changed = False
        for col, value in source.items():
            if value and not (row.get(col) or "").strip():
                row[col] = value
                changed = True
        if changed:
            updated += 1

    write_rows(path, fieldnames, rows)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path(".."))
    parser.add_argument("--historical-dir", type=Path, default=Path("data/historical"))
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()

    lookup = build_source_lookup(args.source_dir, range(args.start_year, args.end_year + 1))
    targets = [
        args.historical_dir / "d1_historical_player_index.csv.gz",
        args.historical_dir / "d1_historical_current_category_scores_2026.csv",
    ]
    for target in targets:
        if target.exists():
            print(f"{target}: updated {augment_file(target, lookup)} rows")


if __name__ == "__main__":
    main()
