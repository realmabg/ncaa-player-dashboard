"""Validate daily lineups and export a RAPM snapshot."""
import argparse
import csv
import json
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from player_ratings import (FEEDS, RELEASES, TORVIK, download, feed_rows, game_logs,
                            key, lineup_ratings, unique)
from rebuild_espn_rapm import reconstruct

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
PACIFIC = ZoneInfo("America/Los_Angeles")


def fetch_json(url, path):
    download(url, path)
    return json.loads(path.read_text())


def missing_matchups(inputs, season, cutoff, known, roster, teams):
    boxes = defaultdict(lambda: defaultdict(int))
    names = defaultdict(set)
    for row in game_logs(inputs, season, False):
        played = date.fromisoformat(row[0])
        if played <= cutoff:
            boxes[played, row[6]][row[47]] += int(row[33])
            names[row[47]].add(key(row[48]))
    roster_names = defaultdict(set)
    for (team, _), name in roster.items():
        roster_names[team].add(key(name))
    exact = unique((key(name), name) for name in names)
    team_boxes = {}
    for team, name in teams.items():
        if key(name) in exact:
            team_boxes[team] = exact[key(name)]
            continue
        overlap = sorted(((len(roster_names[team] & players), box) for box, players in names.items()),
                         reverse=True)
        if len(overlap) > 1 and overlap[0][0] >= 3 and overlap[1][0] <= 1:
            team_boxes[team] = overlap[0][1]
    covered = {
        (date.fromisoformat(g["game_date"]),
         frozenset((team_boxes.get(g[f"{side}_team_id"]), g[f"{side}_score"])
                   for side in ("home", "away")))
        for g, _ in known.values()
    }
    # Torvik credits Washington's own basket to the scorer instead of Colgate.
    if season == 2027 and (date(2026, 11, 2), frozenset({("Washington", 90), ("Colgate", 76)})) in covered:
        covered.add((date(2026, 11, 2), frozenset({("Washington", 90), ("Colgate", 74)})))
    missing = {}
    for (played, _), score in boxes.items():
        matchup = frozenset(score.items())
        if len(score) == 2 and not any(
            (played + timedelta(days=offset), matchup) in covered for offset in (-1, 0, 1)
        ):
            missing[played, matchup] = score
    return missing, team_boxes


def espn_scoreboards(days, scratch):
    def fetch(day):
        path = scratch / f"scoreboard-{day}.json"
        if path.exists():
            return json.loads(path.read_text())["events"]
        return fetch_json(f"{ESPN}/scoreboard?dates={day:%Y%m%d}&groups=50&limit=500", path)["events"]

    with ThreadPoolExecutor(max_workers=5) as pool:
        yield from pool.map(fetch, days)


def scoreboard_matchups(inputs, scratch, season, cutoff, known, teams):
    team_ids = unique(
        (r[f"{side}_espn_team_id"], r[f"{side}_ncaa_team_id"])
        for r in feed_rows(inputs, "pbp", season) for side in ("home", "away")
        if r[f"{side}_espn_team_id"] and r[f"{side}_ncaa_team_id"] in teams
    )
    by_name = unique((key(name), team) for team, name in teams.items())
    first = min(date.fromisoformat(g["game_date"]) for g, _ in known.values())
    days = [first + timedelta(days=i) for i in range((cutoff - first).days + 1)]
    covered = {(date.fromisoformat(g["game_date"]), frozenset((g["home_team_id"], g["away_team_id"])))
               for g, _ in known.values()}
    missing = {}
    for board in espn_scoreboards(days, scratch):
        for event in board:
            if event["id"] in known or not event["status"]["type"]["completed"]:
                continue
            played = datetime.fromisoformat(event["date"]).astimezone(PACIFIC).date()
            if played > cutoff:
                continue
            scores = {}
            for club in event["competitions"][0]["competitors"]:
                team = club["team"]
                team_id = team_ids.get(team["id"]) or by_name.get(key(team["location"]))
                if team_id:
                    scores[team_id] = int(club["score"])
            if len(scores) != 2 or any((played + timedelta(days=shift), frozenset(scores)) in covered
                                       for shift in (-1, 0, 1)):
                continue
            names = {teams[t]: score for t, score in scores.items()}
            missing[played, frozenset(names.items())] = names
    return missing, teams


def recover_espn(inputs, scratch, season, missing, team_boxes, known):
    if not missing:
        return None, []
    espn_ids = unique(
        (r[f"{side}_espn_team_id"], team_boxes[r[f"{side}_ncaa_team_id"]])
        for r in feed_rows(inputs, "pbp", season) for side in ("home", "away")
        if r[f"{side}_espn_team_id"] and r[f"{side}_ncaa_team_id"] in team_boxes
    )
    names = unique((key(t), t) for t in team_boxes.values())

    days = sorted({day + timedelta(days=offset) for day, _ in missing for offset in (0, 1)})
    matches = defaultdict(dict)
    for board in espn_scoreboards(days, scratch):
        for event in board:
            if event["id"] in known or not event["status"]["type"]["completed"]:
                continue
            played = datetime.fromisoformat(event["date"]).astimezone(PACIFIC).date()
            sides = {}
            for club in event["competitions"][0]["competitors"]:
                team = club["team"]
                name = espn_ids.get(team["id"]) or names.get(key(team["location"]))
                sides[club["homeAway"]] = name, int(club["score"])
            if set(sides) != {"home", "away"}:
                continue
            for offset in (0, -1, 1):
                match = played + timedelta(days=offset), frozenset(sides.values())
                if match in missing:
                    matches[match][event["id"]] = sides
                    break

    rows, gaps = [], []
    for match, score in missing.items():
        played, _ = match
        candidates = matches[match]
        if len(candidates) != 1:
            gaps.append({"date": played.isoformat(), "teams": sorted(score),
                         "reason": "No unique ESPN event matched the teams and final score"})
            continue
        (event, sides), = candidates.items()
        rows.append(dict(date=played.isoformat(), espn_event_id=event,
                         home_team=sides["home"][0], away_team=sides["away"][0],
                         box_home=sides["home"][1], box_away=sides["away"][1], source="ESPN",
                         play_by_play_url=f"https://www.espn.com/mens-college-basketball/playbyplay/_/gameId/{event}"))
    if not rows:
        return None, gaps

    def summary(row):
        event = row["espn_event_id"]
        try:
            path = scratch / f"{event}.json"
            if not path.exists():
                fetch_json(f"{ESPN}/summary?event={event}", path)
        except (OSError, ValueError) as error:
            return dict(date=row["date"], teams=[row["home_team"], row["away_team"]], reason=str(error))
        return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(summary, rows))
    gaps.extend(result for result in results if result)
    ready = [row for row, error in zip(rows, results) if error is None]
    if not ready:
        return None, gaps
    matches_path = scratch / "matches.csv"
    destination = scratch / "fallback.csv.gz"
    report = scratch / "fallback-audit.csv"
    with matches_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(ready[0]))
        writer.writeheader()
        writer.writerows(ready)
    reconstruct(inputs, scratch, matches_path, destination, report, season,
                use_torvik=(inputs / "torvik-games.json.gz").exists())
    with report.open(newline="") as file:
        for row in csv.DictReader(file):
            if row["issue"]:
                gaps.append(dict(date=row["date"], teams=[row["home_team"], row["away_team"]],
                                 reason=row["issue"]))
    return destination, gaps


def write_outputs(season, through, known, ratings, gaps, output, possessions_output):
    if not (output or possessions_output):
        return
    games = []
    possession_count = 0
    for game, observations in known.values():
        possessions = [
            dict(possession_number=number, period=period, clock_seconds=clock, offense_team_id=lineup[0][0],
                 offense_players=[pid for _, pid in lineup[:5]],
                 defense_players=[pid for _, pid in lineup[5:]], points=points)
            for number, (period, clock, lineup, points) in enumerate(observations, 1)
        ]
        possession_count += len(possessions)
        games.append({"game": game, "possessions": possessions})

    snapshot = dict(season=season, through_date=through, published_at=datetime.now(PACIFIC).isoformat(),
                    game_count=len(known), possession_count=possession_count, ratings=ratings,
                    coverage_gaps=gaps)
    if output:
        output.write_text(json.dumps(snapshot, allow_nan=False) + "\n")
    if possessions_output:
        possessions_output.write_text(json.dumps(games, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--cutoff", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, help="Write the validated RAPM snapshot as JSON")
    parser.add_argument("--possessions-output", type=Path, help="Write the validated lineup inputs as JSON")
    args = parser.parse_args()
    today = datetime.now(PACIFIC).date()
    run_date = args.cutoff or today
    season = args.season or run_date.year + (run_date.month >= 7)
    cutoff = min(args.cutoff or today - timedelta(days=1), date(season, 6, 30))
    known = {}

    def remember(game, played, home, away, score, source, observations, excluded):
        if game in known:
            raise ValueError(f"Duplicate RAPM game {game}")
        known[game] = (dict(season=season, game_id=game, game_date=played.isoformat(), source=source,
                            home_team_id=home, away_team_id=away, home_score=score[0], away_score=score[1]),
                       observations)

    with tempfile.TemporaryDirectory(prefix="daily-rapm-") as temp:
        scratch = Path(temp)
        inputs = args.inputs or scratch
        if args.inputs is None:
            for name in FEEDS:
                tag = f"ncaa_mbb_{name}"
                download(f"{RELEASES}/{tag}/{tag}_{season}.csv.gz", inputs / f"{name}.csv.gz")
            try:
                download(f"{TORVIK}/{season}_all_advgames.json.gz", inputs / "torvik-games.json.gz")
            except HTTPError as error:
                if error.code != 403:
                    raise
                print("Torvik returned HTTP 403. Checking completed D-I games against ESPN scoreboards.")
        ratings, roster, teams, through = lineup_ratings(inputs, season, cutoff, game_observer=remember)
        if (inputs / "torvik-games.json.gz").exists():
            missing, team_boxes = missing_matchups(inputs, season, cutoff, known, roster, teams)
        else:
            missing, team_boxes = scoreboard_matchups(inputs, scratch, season, cutoff, known, teams)
        recovered, gaps = recover_espn(inputs, scratch, season, missing, team_boxes, known)
        if recovered is not None:
            known.clear()
            ratings, _, _, through = lineup_ratings(inputs, season, cutoff, game_observer=remember,
                                                     extra_backfill=recovered)
        players = [dict(rating, team_id=team, player_id=pid) for (team, pid), rating in ratings.items()]
        print(f"Found {len(gaps)} unresolved box-score matchups through {cutoff}")
        for gap in gaps:
            print(f"  {gap['date']} {' vs '.join(gap['teams'])} | {gap['reason']}")
        write_outputs(season, through, known, players, gaps, args.output, args.possessions_output)


if __name__ == "__main__":
    main()
