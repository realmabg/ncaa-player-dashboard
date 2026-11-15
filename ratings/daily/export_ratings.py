"""Export the latest published Supabase snapshot as one dashboard CSV."""
import argparse
import csv
import io
from pathlib import Path

from ratings_store import query

EXPORT_SQL = """
copy (
    with latest as (
        select season, through_date, coverage
        from ratings.snapshots
        order by season desc, through_date desc
        limit 1
    )
    select p.player_name, p.team, p.bpm, p.rapm,
           p.details->>'bpm_minutes' as bpm_minutes,
           p.details->>'rapm_possessions' as rapm_possessions,
           p.season, p.through_date,
           s.coverage #>> '{bpm,through_date}' as bpm_through_date,
           s.coverage #>> '{rapm,through_date}' as rapm_through_date,
           s.coverage #>> '{bpm,expected_games}' as expected_games,
           s.coverage #>> '{bpm,included_games}' as bpm_games_included,
           s.coverage #>> '{rapm,included_games}' as rapm_games_included,
           s.coverage #>> '{rapm,excluded_input_rows}' as rapm_excluded_possessions
    from latest s join ratings.player_ratings p using (season, through_date)
    where p.bpm is not null or p.rapm is not null
    order by p.team, p.player_name, p.player_key
) to stdout with (format csv, header true);
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = query(EXPORT_SQL)
    rows = csv.DictReader(io.StringIO(result))
    if next(rows, None) is None:
        raise SystemExit("No published player ratings to export")
    args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
