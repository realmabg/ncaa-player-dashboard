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


from .projection_keys import name_key

SNAPSHOT_PATH = Path(__file__).with_name("player_projections.json")
WCC_SNAPSHOT_NAME = "ucsd_wcc_forecast.json"
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


def write_wcc_snapshot(path, rows, forecast_date, data_through, snapshot):
    """Save the same-roster forecast with only the destination conference changed."""
    expected = set(snapshot["names"].get("UC San Diego", {}).values())
    allowed_stats = {stat["key"] for stat in snapshot["stats"]}
    players = defaultdict(dict)
    for row in rows:
        pid, stat = int(row["player_id"]), row["stat"]
        if (pid not in expected or row["destination_team"] != "UC San Diego"
                or row["date"] != forecast_date.isoformat()
                or row["data_through_date"] != (forecast_date - timedelta(days=1)).isoformat()
                or stat not in allowed_stats or stat in players[pid]):
            raise ValueError(f"Unexpected WCC forecast row for {pid}, {stat}")
        value = float(row["dynamic"]) if row["dynamic"] else None
        if value is not None and (not math.isfinite(value) or value < 0
                                  or (stat in PERCENT_STATS and value > 1)):
            raise ValueError(f"Invalid WCC forecast for {pid}, {stat}")
        players[pid][stat] = value
    if set(players) != expected or any(set(values) != allowed_stats for values in players.values()):
        raise ValueError("Incomplete WCC forecast")
    payload = {"season": snapshot["season"], "through": data_through.isoformat(), "players": players}
    draft = path.with_suffix(".tmp")
    draft.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    draft.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "rosters", "teams", "games", "audit-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    games_path = args.games.resolve()
    audit = args.audit_dir.resolve()
    audit.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(workspace / "scripts"))
    from audit_game_logs import read_rows
    from court_impact_population import destination_aliases
    from live_player_skills import ALL_STATS, HEADS, game_evidence, priors, read_games, roster_context, sums, update
    import numpy as np
    import pandas as pd
    from profile_data import school_key
    from three_point import conference_tier

    aliases = destination_aliases()
    current_destinations = {}
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
        current_destinations[key] = aliases.get(school_key(row["team"]), row["team"])
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
        destination = current_destinations.get(team)
        conf = team_conferences.get(team)
        found = next(iter(candidates)) if len(candidates) == 1 else None
        if found is None:
            status = "ambiguous_torvik_id" if candidates else "no_verified_torvik_id"
        elif not destination or not conf:
            status = "unmapped_team_or_conference"
        elif current_teams[found] - {team}:
            status = "torvik_id_has_multiple_current_teams"
        else:
            status = source if team in aliases else "current_team_outside_model_registry"
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
    # The fitted forecast requires a destination from its historical registry.
    # Current Division I teams outside that registry can use the pooled prior.
    model_roster = [row for row in roster_rows if school_key(row["destination_team"]) in aliases]
    if not model_roster:
        raise ValueError("No roster players found in the fitted model's school registry")
    write_roster(roster_path, model_roster)
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
    for row in roster_rows:
        pid = row["player_id"]
        if school_key(row["destination_team"]) not in aliases:
            forecasts[pid] = {stat: [None, None] for stat in ALL_STATS}
            forecast_teams[pid] = row["destination_team"]

    eligible_games = read_games(games_path, SEASON, pd.Timestamp(args.date), aliases)
    evidence = game_evidence(eligible_games)
    fallback = {}
    missing_prior = [pid for pid, stats in forecasts.items()
                     if all(prior is None and updated is None for prior, updated in stats.values())]
    if missing_prior:
        cohort = pd.DataFrame.from_dict(
            {pid: {head: stats[head][0] for head in HEADS} for pid, stats in forecasts.items()},
            orient="index",
        ).dropna()
        if cohort.empty:
            raise ValueError("No eligible preseason forecasts for the Division I prior")
        # Reuse the production model's exposure scales and recency settings.
        # Only the prior mean changes for players without an eligible profile.
        sample = pd.DataFrame(roster_rows).set_index("player_id").loc[[cohort.index[0]]].reset_index()
        _, strength = priors(roster_context(sample, SEASON - 1, aliases), "production")
        index = pd.MultiIndex.from_tuples(
            [(pid, canonical(forecast_teams[pid])) for pid in missing_prior], names=["player_id", "team"],
        )
        base = pd.DataFrame([cohort.mean()] * len(index), index=index)
        settings = json.loads((workspace / "outputs/live_player_skills_v2/settings.json").read_text())
        weights = np.exp2(-(pd.Timestamp(args.date) - evidence.date).dt.days / settings["half_life_days"])
        rates = update(base, strength, sums(evidence, index, weights), settings["dynamic_strength"])
        fallback = dict(zip(missing_prior, rates[ALL_STATS].to_numpy().tolist(), strict=True))

    totals = evidence.groupby(["player_id", "team"]).sum(numeric_only=True)
    actuals = {
        stat: totals[f"{stat}_k"].div(totals[f"{stat}_e"].where(totals[f"{stat}_e"].gt(0)))
        for stat in ALL_STATS
    }
    # FTR is a season ratio. A zero-FGA game can still add free-throw attempts.
    attempts = eligible_games.groupby(["player_id", "team"])[["ft_a", "two_a", "three_a"]].sum()
    fga = attempts.two_a + attempts.three_a
    actuals["ftr"] = attempts.ft_a.div(fga.where(fga.gt(0)))
    actuals = pd.DataFrame(actuals).astype(object)
    actuals = actuals.where(actuals.notna(), None)

    ratings_players = {}
    ratings_names = defaultdict(dict)
    for (team, name), ids in sorted(ratings_keys.items()):
        if len(ids) != 1:
            continue
        pid, = ids
        if pid not in forecasts:
            continue
        if pid not in ratings_players:
            key = (pid, canonical(forecast_teams[pid]))
            observed = actuals.loc[key, :].tolist() if key in actuals.index else [None] * len(ALL_STATS)
            ratings_players[pid] = {
                "actual": observed,
                "preseason": [forecasts[pid][stat][0] for stat in ALL_STATS],
                "updated": [forecasts[pid][stat][1] for stat in ALL_STATS],
            }
            if pid in fallback:
                ratings_players[pid]["fallback"] = fallback[pid]
        ratings_names[team][name] = pid
    print(f"Ratings stats: {len(ratings_players)} players across {len(ratings_names)} teams "
          f"({len(fallback)} with a Division I prior)", flush=True)
    updated = Counter(row["stat"] for row in forecast_rows if row["status"] == "updated")
    print("Players with observed evidence by stat:", dict(updated), flush=True)
    payload = {
        "season": SEASON, "preseason_through": "2026-06-30",
        "updated_through": data_through.isoformat(), "actual_through": data_through.isoformat(),
        "stats": [{"key": stat, "label": labels[stat], "unit": "percent" if stat in PERCENT_STATS
                   else "ratio" if stat in RATIO_STATS else "per100"} for stat in ALL_STATS],
        "players": ratings_players, "names": ratings_names,
    }
    ucsd_ids = set(ratings_names.get("UC San Diego", {}).values())
    if ucsd_ids:
        wcc_roster_path = audit / "ucsd_wcc_roster.csv"
        wcc_forecast_path = audit / "ucsd_wcc_player_skills.csv"
        write_roster(wcc_roster_path, [
            {**row, "destination_conf": "WCC"} for row in roster_rows if row["player_id"] in ucsd_ids
        ])
        subprocess.run([
            sys.executable, "scripts/live_player_skills.py", "forecast",
            "--roster", str(wcc_roster_path), "--games", str(games_path),
            "--settings", "outputs/live_player_skills_v2/settings.json",
            "--date", args.date.isoformat(), "--output", str(wcc_forecast_path),
        ], cwd=workspace, check=True)
        write_wcc_snapshot(args.output.with_name(WCC_SNAPSHOT_NAME), csv_rows(wcc_forecast_path),
                           args.date, data_through, payload)
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
