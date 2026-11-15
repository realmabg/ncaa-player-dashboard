"""Build the dashboard projection snapshot with the saved forecasting workspace."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta
import gzip
import json
import math
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from projection_keys import name_key
SEASON = 2027
PERCENT_STATS = {"three", "two", "ft", "ast", "orb", "drb", "usage", "personal_tov", "share"}
RATIO_STATS = {"ftr"}
# UAC is the renamed WAC. Metro is Torvik’s label for the MAAC.
CONFERENCE_CODES = {"UAC": "WAC", "Metro": "MAAC"}


def csv_rows(path):
    reader = gzip.open if path.suffix == ".gz" else open
    with reader(path, "rt", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def write_roster(path, rows):
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["player_id", "destination_team", "destination_conf"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "rosters", "teams", "games", "audit-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "www/player_projections.json")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    games_path = args.games.resolve()
    audit = args.audit_dir.resolve()
    audit.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(workspace / "scripts"))
    from audit_game_logs import read_rows
    from court_impact_population import destination_aliases
    from live_player_skills import ALL_STATS
    from profile_data import school_key
    from three_point import conference_tier

    aliases = destination_aliases()
    # The NCAA roster uses the university's full name for the Torvik team.
    roster_school = {"lsuneworleans": "New Orleans"}

    def canonical(team):
        return school_key(aliases.get(school_key(team), team))

    team_conferences = {}
    for row in csv_rows(args.teams):
        key = canonical(row["team"])
        conf = CONFERENCE_CODES.get(row["conf"], row["conf"])
        conference_tier(conf, SEASON)
        if key in team_conferences and team_conferences[key] != conf:
            raise ValueError(f"Conflicting conferences for {row['team']}")
        team_conferences[key] = conf
    games, _ = read_rows(games_path)
    if any(row[52] != SEASON for row in games):
        raise ValueError("Expected the 2026–27 Torvik advanced game archive")
    date_key = args.date.strftime("%Y%m%d")
    eligible_dates = [str(row[0]) for row in games if str(row[0]) < date_key]
    if not eligible_dates:
        raise ValueError("The game feed has no results before the forecast date")
    data_through = datetime.strptime(max(eligible_dates), "%Y%m%d").date()
    current = defaultdict(set)
    current_teams = defaultdict(set)
    current_names = defaultdict(set)
    for row in games:
        if str(row[0]) >= date_key:
            continue
        player_id = int(row[51])
        team = canonical(row[47])
        name = name_key(row[48])
        current[team, name].add(player_id)
        current_names[team, player_id].add(name)
        current_teams[player_id].add(team)

    context = csv_rows(workspace / "runs/all_player_skills/context.csv")
    historical = defaultdict(set)
    for row in context:
        if int(row["end_year"]) == SEASON - 1:
            historical[canonical(row["team"]), name_key(row["player_name"])].add(int(float(row["pid"])))

    roster = {}
    ratings_keys = defaultdict(set)
    audit_rows = []
    seen_ncaa = set()
    for row in csv_rows(args.rosters):
        if int(row["season"]) != SEASON:
            raise ValueError("Unexpected season on NCAA roster")
        player_name = row["clean_name"] or row["name"]
        school = roster_school.get(school_key(row["team"]), row["team"])
        team = canonical(school)
        ncaa_key = (row["team_id"], row["player_id"])
        if row["player_id"] and ncaa_key in seen_ncaa:
            continue
        seen_ncaa.add(ncaa_key)
        names = {name_key(value) for value in (player_name, row["name"], row["player"]) if value}
        candidates = set().union(*(current[team, name] for name in names))
        source = "current_torvik_box"
        if not candidates:
            candidates = {pid for name in names for pid in historical[team, name]
                          if not current_teams[pid] or team in current_teams[pid]}
            source = "previous_torvik_player_same_team"
        destination = aliases.get(school_key(school))
        conf = team_conferences.get(team)
        found = next(iter(candidates)) if len(candidates) == 1 else None
        if found is None:
            status = "ambiguous_torvik_id" if candidates else "no_verified_torvik_id"
        elif not destination or not conf:
            status = "unmapped_team_or_conference"
        elif current_teams[found] - {team}:
            status = "torvik_id_has_multiple_current_teams"
        else:
            status = source
            roster.setdefault(found, set()).add((destination, conf))
            for name in names | current_names[team, found]:
                ratings_keys[row["team"], name].add(found)
        audit_rows.append({"player": player_name, "team": row["team"], "ncaa_id": row["player_id"],
                           "torvik_id": found, "status": status})
    ambiguous = {pid for pid, destinations in roster.items() if len(destinations) != 1}
    for row in audit_rows:
        if row["torvik_id"] in ambiguous:
            row["status"] = "torvik_id_has_multiple_roster_teams"
    roster_path = audit / "exporter_roster.csv"
    roster_rows = [
        dict(player_id=pid, destination_team=team, destination_conf=conf)
        for pid, destinations in sorted(roster.items()) if pid not in ambiguous
        for team, conf in destinations
    ]
    if not roster_rows:
        raise ValueError("No NCAA roster players matched the Torvik feed")
    write_roster(roster_path, roster_rows)
    write_audit(audit / "roster_matches.csv", audit_rows)
    print("NCAA roster:", dict(Counter(row["status"] for row in audit_rows)), flush=True)

    forecast_path = audit / "player_skills.csv"
    subprocess.run([
        sys.executable, "scripts/live_player_skills.py", "forecast",
        "--roster", str(roster_path), "--games", str(games_path),
        "--settings", "outputs/live_player_skills_v2/settings.json",
        "--date", args.date.isoformat(), "--output", str(forecast_path),
    ], cwd=workspace, check=True)

    forecasts = defaultdict(dict)
    labels = {}
    forecast_teams = {}
    forecast_rows = csv_rows(forecast_path)
    for row in forecast_rows:
        pid, stat = int(row["player_id"]), row["stat"]
        if (row["date"] != args.date.isoformat() or row["forecast_period"] != "rest of season"
                or row["data_through_date"] != (args.date - timedelta(days=1)).isoformat()):
            raise ValueError("Unexpected forecast period or cutoff")
        if stat in forecasts[pid] or stat not in ALL_STATS:
            raise ValueError(f"Unexpected or duplicate forecast stat {stat}")
        if pid in forecast_teams and forecast_teams[pid] != row["destination_team"]:
            raise ValueError(f"Forecast has multiple destinations for {pid}")
        forecast_teams[pid] = row["destination_team"]
        labels[stat] = row["label"]
        values = [float(row[key]) if row[key] else None for key in ("preseason", "dynamic")]
        if any(value is not None and (not math.isfinite(value) or value < 0
                or (stat in PERCENT_STATS and value > 1)) for value in values):
            raise ValueError(f"Invalid forecast units for {pid}, {stat}")
        forecasts[pid][stat] = values
    if any(set(values) != set(ALL_STATS) for values in forecasts.values()):
        raise ValueError("Expected all 18 forecast stats per mapped roster player")

    ratings_players = defaultdict(dict)
    ratings_names = defaultdict(dict)
    for (team, name), ids in sorted(ratings_keys.items()):
        if len(ids) != 1:
            continue
        pid, = ids
        if pid not in forecasts:
            continue
        rates = [forecasts[pid][stat] for stat in ALL_STATS]
        if any(value is not None for pair in rates for value in pair):
            ratings_players[pid] = {"team": forecast_teams[pid], "rates": rates}
            ratings_names[team][name] = pid
    print(f"Ratings projections: {len(ratings_players)} players across {len(ratings_names)} teams",
          flush=True)
    updated = Counter(row["stat"] for row in forecast_rows if row["status"] == "updated")
    print("Players with observed evidence by stat:", dict(updated), flush=True)
    payload = {
        "season": SEASON, "preseason_through": "2026-06-30",
        "updated_through": data_through.isoformat(),
        "stats": [{"label": labels[stat], "unit": "percent" if stat in PERCENT_STATS
                   else "ratio" if stat in RATIO_STATS else "per100"} for stat in ALL_STATS],
        "players": ratings_players, "names": ratings_names,
    }
    draft = args.output.with_suffix(".tmp")
    draft.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n",
                     encoding="utf-8")
    draft.replace(args.output)


def write_audit(path, rows):
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
