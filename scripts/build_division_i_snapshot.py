"""Build a validated season-to-date Division I snapshot from Bart Torvik."""

import argparse
import csv
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

TORVIK = "https://barttorvik.com"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

RAW_HEADERS = [
    "player_name",
    "team",
    "conf",
    "GP",
    "min_pct",
    "ORtg",
    "usg",
    "eFG",
    "TS_pct",
    "ORB_pct",
    "DRB_pct",
    "AST_pct",
    "TOV_pct",
    "FTM",
    "FTA",
    "FT_pct",
    "2PM",
    "2PA",
    "2P_pct",
    "3PM",
    "3PA",
    "3P_pct",
    "Blk_pct",
    "Stl_pct",
    "FTR",
    "yr",
    "ht",
    "Number",
    "PORPAG",
    "adjoe",
    "personal_fouls_per_40",
    "year",
    "pid",
    "hometown",
    "Rec_Rank",
    "AST_TOV",
    "rimmade",
    "rim_attempts",
    "midmade",
    "mid_attempts",
    "rim_pct",
    "mid_pct",
    "dunksmade",
    "dunks_attempts",
    "dunk_pct",
    "pick",
    "drtg",
    "adj_drtg",
    "D_PORPAG",
    "stops",
    "bpm",
    "obpm",
    "dbpm",
    "gbpm",
    "mins_per_game",
    "ogbpm",
    "dgbpm",
    "oreb_per_game",
    "dreb_per_game",
    "treb_per_game",
    "ast_per_game",
    "stl_per_game",
    "blk_per_game",
    "pts_per_game",
    "role",
    "3P_per_100_team_pos",
    "DOB",
]

PBP_HEADERS = [
    "pbp_pid",
    "pbp_player_name",
    "pbp_team",
    "pbp_rim_made",
    "pbp_rim_missed",
    "pbp_rim_assisted",
    "pbp_mid_made",
    "pbp_mid_missed",
    "pbp_mid_assisted",
    "pbp_three_made",
    "pbp_three_missed",
    "pbp_three_assisted",
    "pbp_dunk_made",
    "pbp_dunk_missed",
    "pbp_dunk_assisted",
]


REQUIRED_NUMERIC = (
    "GP", "mins_per_game", "eFG", "2PA", "3PA", "2P_pct", "3P_pct",
    "TOV_pct", "DRB_pct", "ORB_pct",
)
DERIVED_HEADERS = [
    "height_inches", "total_known_fga", "rim_share", "mid_share", "three_share",
    "arch_PC1", "arch_PC2", "arch_PC3", "val_PC1", "snapshot_retrieved_at",
]


def download(path):
    with urlopen(TORVIK + path, timeout=45) as response:
        return response.read().decode("utf-8-sig")


def read_players(payload, season):
    players = {}
    player_ids = set()
    for values in csv.reader(io.StringIO(payload)):
        if not values:
            continue
        if len(values) < len(RAW_HEADERS):
            raise ValueError(f"Unexpected Torvik player row width: {len(values)}")
        row = dict(zip(RAW_HEADERS, values))
        key = (row["pid"], row["team"])
        if (
            row["year"] != str(season)
            or not row["pid"].isdigit()
            or not row["player_name"]
            or not row["team"]
            or row["pid"] in player_ids
        ):
            raise ValueError(f"Invalid or duplicate player for season {season}: {key}")
        for field in REQUIRED_NUMERIC:
            number = float(row[field])
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"Invalid {field} for player {key}: {row[field]}")
        players[key] = row
        player_ids.add(row["pid"])
    if len({team for _, team in players}) < 300:
        raise ValueError("Player feed covers fewer than 300 Division I teams")
    return players


def read_shooting(payload, players):
    shooting = {}
    for values in json.loads(payload):
        if len(values) != len(PBP_HEADERS):
            raise ValueError(f"Unexpected Torvik shooting row width: {len(values)}")
        pid, _, team, *counts = values
        key = (str(pid), team)
        if key in shooting or key not in players:
            raise ValueError(f"Duplicate or unmatched Torvik shooting row: {key}")
        if any(type(count) is not int or count < 0 for count in counts):
            raise ValueError(f"Invalid shooting counts for player {key}")
        shooting[key] = dict(zip(PBP_HEADERS, values))
    if not shooting:
        raise ValueError("Shooting feed is empty")
    return shooting


def build_snapshot(players, shooting, retrieved_at):
    for key, row in players.items():
        matched = shooting.get(key)
        if matched is None and int(row["2PA"]) + int(row["3PA"]):
            raise ValueError(f"Player has shot attempts but no shooting row: {key}")

        height = re.fullmatch(r"(\d+)-(\d+)", row["ht"])
        if height:
            feet, inches = map(int, height.groups())
            row["height_inches"] = feet * 12 + inches
        else:
            row["height_inches"] = ""
        attempts = {
            "rim": int(row["rim_attempts"] or 0),
            "mid": int(row["mid_attempts"] or 0),
            "three": int(row["3PA"]),
        }
        total = sum(attempts.values())
        row["total_known_fga"] = total
        for zone, count in attempts.items():
            row[f"{zone}_share"] = count / total if total else 0
        # The dashboard computes its shared archetype coordinates after loading.
        row.update(arch_PC1=0, arch_PC2=0, arch_PC3=0, val_PC1=0)
        row["snapshot_retrieved_at"] = retrieved_at
        row["pbp_join_method"] = "pid" if matched else "unmatched"
        row["pbp_join_warning"] = "" if matched else "no_shot_attempts"
        row.update(matched or dict.fromkeys(PBP_HEADERS[3:], 0))
        yield row


def pull_raw(season, raw_dir):
    retrieved_at = datetime.now(timezone.utc)
    folder = raw_dir / str(season) / retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    players = folder / "players.csv"
    shooting = folder / "shooting.json"
    players.write_text(download(f"/getadvstats.php?year={season}&csv=1"), encoding="utf-8")
    shooting.write_text(download(f"/{season}_pbp_playerstat_array.json"), encoding="utf-8")
    (folder / "retrieved_at.txt").write_text(retrieved_at.isoformat(timespec="seconds"), encoding="utf-8")
    return players, shooting


def publish_snapshot(rows, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=destination.parent, delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            fields = RAW_HEADERS + DERIVED_HEADERS + ["pbp_join_method", "pbp_join_warning"] + PBP_HEADERS
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True, help="Four-digit season end year")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw" / "division_i")
    parser.add_argument("--players", type=Path, help="Use an existing raw player CSV")
    parser.add_argument("--shooting", type=Path, help="Use an existing raw shooting JSON")
    args = parser.parse_args()
    if bool(args.players) != bool(args.shooting):
        parser.error("--players and --shooting must be supplied together")
    player_path, shooting_path = (
        (args.players, args.shooting) if args.players else pull_raw(args.season, args.raw_dir)
    )
    capture = player_path.parent / "retrieved_at.txt"
    if player_path.parent == shooting_path.parent and capture.is_file():
        retrieved_at = datetime.fromisoformat(capture.read_text(encoding="utf-8").strip())
    else:
        retrieved_at = datetime.fromtimestamp(
            min(player_path.stat().st_mtime, shooting_path.stat().st_mtime), timezone.utc,
        )
    players = read_players(player_path.read_text(encoding="utf-8-sig"), args.season)
    shooting = read_shooting(shooting_path.read_text(encoding="utf-8-sig"), players)
    rows = list(build_snapshot(players, shooting, retrieved_at.isoformat(timespec="seconds")))
    destination = args.output or DATA_DIR / "current" / f"division-i-{args.season}.csv"
    publish_snapshot(rows, destination)
    print(f"Published {len(rows):,} players and {len(shooting):,} shooting records to {destination}")


if __name__ == "__main__":
    main()
