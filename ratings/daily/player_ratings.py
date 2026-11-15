#!/usr/bin/env python3
"""Refresh men's Division I season-to-date BPM and lineup-based RAPM."""
import argparse
import csv
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from itertools import groupby
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
from scipy.sparse import csr_matrix, diags, vstack
from scipy.sparse.linalg import lsqr

from box_plus_minus import season_bpm
from rapm_repairs import (LINEUP_NAMES, MISSING_ROSTER_PLAYERS, collect_play_evidence,
                          expected_score, iowa_reconstruction, merge_split_possessions, placeholder_id,
                          reconcile_points, updated_slot)

ROOT = Path(__file__).resolve().parent
RELEASES = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
TORVIK = "https://barttorvik.com"
ALPHA = 2000.0  # Frozen setting from the earlier court-impact validation.
RAPM_HALF_LIFE_DAYS = 90
FEEDS = ("possessions", "schedule", "team_ids", "team_rosters", "pbp")
COLUMNS = (
    "season", "player_name", "team", "torvik_player_id", "ncaa_player_id",
    "bpm", "bpm_games", "bpm_minutes", "bpm_last_game", "rapm", "rapm_games", "rapm_possessions",
    "rapm_last_game", "rapm_through", "bpm_through", "refreshed_at_utc",
)
SIDES = ("home", "away")
LINEUP_SLOTS = tuple((side, f"{side}_{number}") for side in SIDES for number in range(1, 6))
# Verified against school rosters, jersey numbers, and the provider IDs.
PLAYER_CROSSWALKS = {
    2027: {
        ("627394", "11471945"): ("133990", "Georgia St."),
        ("627354", "12153191"): ("145291", "Winthrop"),
        ("627308", "11593023"): ("143893", "Louisiana"),
        ("627583", "11953762"): ("135174", "Tarleton St."),
        ("627353", "11588991"): ("143793", "William & Mary"),
        ("627353", "11588988"): ("75962", "William & Mary"),
        ("627475", "12146992"): ("144738", "Coastal Carolina"),
        ("627449", "11956116"): ("79085", "Morgan St."),
        ("627563", "12151923"): ("145134", "Richmond"),
        ("627404", "11475506"): ("135134", "Central Arkansas"),  # J.C. Shulman, #4
        ("627404", "12148184"): ("144833", "Central Arkansas"),  # R.J. Young, #0
        ("627404", "11472687"): ("133887", "Central Arkansas"),  # R.J. Newton, #7
        ("627404", "12148179"): ("135452", "Central Arkansas"),  # Simm-Marten Saadi, #35
    },
}


@lru_cache(maxsize=25000)
def key(value):
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    parts = re.findall(r"[a-z0-9]+", ascii_name.lower().replace("&", " and "))
    while parts and parts[-1] in {"jr", "sr", "ii", "iii", "iv", "v", "vi", "vii"}:
        parts.pop()
    return "".join(parts)


@lru_cache(maxsize=600)
def ncaa_date(value):
    return datetime.strptime(value, "%m/%d/%Y").date()


def unique(items):
    options = defaultdict(set)
    for identifier, value in items:
        options[identifier].add(value)
    return {identifier: next(iter(values)) for identifier, values in options.items()
            if len(values) == 1}


def download(url, destination):
    request = Request(url, headers={"User-Agent": "UCSD-Recruiting-Player-Ratings/1.0"})
    with urlopen(request, timeout=90) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def feed_rows(directory, name, season):
    with gzip.open(directory / f"{name}.csv.gz", "rt", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if int(row["season"]) != season:
                raise ValueError(f"Unexpected season in {name}")
            yield row


def postgres_game_logs(season):
    """Use libpq's configured PGSERVICE to read the private game-log snapshot."""
    sql = f"""
        SELECT game_rows
        FROM recruiting.source_snapshot WHERE season = {season};
    """
    result = subprocess.check_output(
        [os.environ.get("PSQL", "psql"), "-X", "-A", "-t", "-w",
         "-v", "ON_ERROR_STOP=1", "-c", sql], text=True, timeout=90
    ).strip()
    if not result:
        raise ValueError(f"No Supabase game-log snapshot for season {season}")
    return json.loads(result)


def game_logs(directory, season, from_postgres):
    if from_postgres:
        return postgres_game_logs(season)
    with gzip.open(directory / "torvik-games.json.gz", "rt", encoding="utf-8") as source:
        return json.load(source)


def backfill_games(season, cutoff, roster, accepted_espn_ids, accepted_matchups, paths=None,
                   game_observer=None):
    """Yield validated historical possessions where the primary feed has no accepted game."""
    seen = set()
    paths = (ROOT / f"rapm_backfill_{season}.csv.gz",) if paths is None else paths

    def rows_from_files():
        for path in paths:
            if path.exists():
                with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
                    yield from csv.DictReader(source)

    for event, records in groupby(rows_from_files(), key=lambda row: row["event"]):
        rows = list(records)
        first = rows[0]
        played = date.fromisoformat(first["date"])
        home, away = first["home_team_id"], first["away_team_id"]
        teams = frozenset((home, away))
        scores = frozenset((team, int(first[f"{side}_score"]))
                           for side, team in zip(SIDES, (home, away)))
        matchup = (played, teams, scores)
        if event in accepted_espn_ids or matchup in accepted_matchups:
            continue
        if any((played + timedelta(days=shift), teams, scores) in accepted_matchups
               for shift in (-1, 1)):
            continue
        if played > cutoff:
            continue
        if len(teams) != 2 or event in seen:
            raise ValueError(f"Invalid backfill game {event}")
        seen.add(event)
        counts = Counter()
        observations = []
        for row in rows:
            if any(row[field] != first[field] for field in
                   ("date", "home_team_id", "away_team_id", "home_score", "away_score")):
                raise ValueError(f"Inconsistent backfill matchup for ESPN {event}")
            offense = row["offense"]
            if offense not in teams or not row["points"].isdigit():
                raise ValueError(f"Invalid backfill possession for ESPN {event}")
            defense = away if offense == home else home
            lineup = tuple(
                player
                for side, team in (("offense", offense), ("defense", defense))
                for player in sorted((team, row[f"{side}_{i}"]) for i in range(1, 6))
            )
            if len({pid for _, pid in lineup}) != 10 or any(player not in roster for player in lineup):
                raise ValueError(f"Unresolved backfill lineup for ESPN {event}")
            counts[offense] += 1
            observations.append((lineup, int(row["points"])))
        if min(counts[home], counts[away]) < 40 or abs(counts[home] - counts[away]) > 3:
            raise ValueError(f"Unbalanced backfill possessions for ESPN {event}")
        if game_observer is not None:
            game_observer(event, played, home, away, tuple(int(first[f"{side}_score"]) for side in SIDES),
                          "backfill", [(int(row["period"]), float(row["clock"]), *obs)
                                       for row, obs in zip(rows, observations)], 0)
        yield f"espn:{event}", played, observations


def rapm_game_weight(played, cutoff):
    return 2 ** (-(cutoff - played).days / RAPM_HALF_LIFE_DAYS)


def lineup_ratings(directory, season, cutoff, game_status=None, *, game_observer=None,
                   extra_backfill=None, fit=True):
    team_names = {row["id"]: row["team"] for row in feed_rows(directory, "team_ids", season)}
    roster = {
        (row["team_id"], row["player_id"]): row["clean_name"] or row["name"]
        for row in feed_rows(directory, "team_rosters", season)
        if row["team_id"] in team_names and row["player_id"]
    }
    aliases = unique(
        ((row["team_id"], key(name)), row["player_id"])
        for row in feed_rows(directory, "team_rosters", season)
        if (row["team_id"], row["player_id"]) in roster
        for name in (row["player"], row["clean_name"], row["name"]) if name
    )
    for (team, name), (source_id, display_name) in MISSING_ROSTER_PLAYERS.items():
        if team in team_names and (team, key(name)) not in aliases:
            roster[team, source_id] = display_name
            aliases[team, key(name)] = source_id
    shots, substitutions = collect_play_evidence(feed_rows(directory, "pbp", season), cutoff,
                                                  ncaa_date)
    schedule = {row["contest_id"]: row for row in feed_rows(directory, "schedule", season)}
    games = defaultdict(list)
    for row in feed_rows(directory, "possessions", season):
        if ncaa_date(row["game_date"]) <= cutoff:
            games[row["contest_id"]].append(row)

    groups = defaultdict(lambda: [0, 0])
    appearances = defaultdict(set)
    exposures = Counter()
    last_dates = {}
    rejected = Counter()
    accepted_dates = []
    accepted_espn_ids, accepted_matchups = set(), set()

    def reject(game_id, reason):
        rejected[reason] += 1
        if game_status is not None:
            game_status[game_id] = reason

    def include(game_id, played, observations):
        accepted_dates.append(played)
        if game_status is not None:
            game_status[game_id] = "accepted"
        weight = rapm_game_weight(played, cutoff)
        for lineup, scored in observations:
            groups[lineup][0] += weight
            groups[lineup][1] += weight * scored
            for player in lineup:
                appearances[player].add(game_id)
                exposures[player] += 1
                last_dates[player] = max(last_dates.get(player, played), played)

    for game_id, rows in games.items():
        first = rows[0]
        game = schedule.get(game_id)
        home, away = first["home_ncaa_team_id"], first["away_ncaa_team_id"]
        if home not in team_names or away not in team_names or home == away:
            reject(game_id, "outside_D1_vs_D1")
            continue
        if not game or (game["game_date"], game["home"], game["away"]) != (
            first["game_date"], first["home"], first["away"]
        ) or not game["home_score"].isdigit() or not game["away_score"].isdigit():
            reject(game_id, "schedule_mismatch")
            continue

        offense_by_name = {first["home"]: home, first["away"]: away}
        name_by_offense = {team: name for name, team in offense_by_name.items()}
        reconstruction = iowa_reconstruction(game_id, game, first)
        game_shots = shots.get(game_id)
        score = expected_score(game_id, game)
        if reconstruction is not None:
            rows, game_shots = reconstruction
            score = (88, 93)
        accepted = []
        points, seen = Counter(), set()
        excluded_observations = set()
        for row in rows:
            offense = row["poss_team_ncaa_team_id"] or offense_by_name.get(row["poss_team"])
            possession = (row["period"], row["poss_num"])
            if (offense not in (home, away) or possession in seen or not row["pts"].isdigit()
                or (row["game_date"], row["home_ncaa_team_id"], row["away_ncaa_team_id"])
                != (first["game_date"], home, away)):
                reject(game_id, "invalid_possession")
                break

            lineup = []
            placeholder_present = any(row[slot] == "TEAM" for side, slot in LINEUP_SLOTS
                                      if side == "home")
            for side, slot in LINEUP_SLOTS:
                team = home if side == "home" else away
                player_id = row[f"{slot}_player_id"]
                tag = row[slot]
                alias_id = aliases.get((team, key(tag))) or LINEUP_NAMES.get((team, tag))
                alias_id = alias_id or placeholder_id(game_id, team, possession, tag,
                                                       substitutions)
                if player_id and alias_id and player_id != alias_id:
                    break
                player = (team, updated_slot(game_id, possession, team, player_id or alias_id,
                                             placeholder_present))
                if player not in roster:
                    break
                lineup.append(player)
            if len(lineup) != 10 or len({player_id for _, player_id in lineup}) != 10:
                reject(game_id, "unresolved_lineup")
                break

            seen.add(possession)
            if row.get("use_for_rapm") == "0":
                excluded_observations.add(possession)
            scored = int(row["pts"])
            points[offense] += scored
            first_team = tuple(sorted(lineup[:5]))
            second_team = tuple(sorted(lineup[5:]))
            oriented = first_team + second_team if offense == home else second_team + first_team
            accepted.append((possession, offense, oriented, scored))
        else:
            names = (first["home"], first["away"])
            model_points = reconcile_points(
                ((possession, name_by_offense[offense], scored)
                 for possession, offense, _, scored in accepted),
                game_shots, score, names,
            )
            if model_points is None and (reconstruction is not None or (points[home], points[away]) != score):
                reject(game_id, "scoring_mismatch")
                continue
            if model_points is not None:
                accepted = [(possession, offense, lineup, scored)
                            for (possession, offense, lineup, _), scored in zip(accepted, model_points)]
            accepted = merge_split_possessions(game_id, accepted)
            if excluded_observations:
                accepted = [row for row in accepted if row[0] not in excluded_observations]
            counts = Counter(offense for _, offense, _, _ in accepted)
            if min(counts[home], counts[away]) < 40 or abs(counts[home] - counts[away]) > 3:
                reject(game_id, "possession_balance")
                continue
            played = ncaa_date(first["game_date"])
            if first.get("espn_game_id"):
                accepted_espn_ids.add(first["espn_game_id"])
            accepted_matchups.add((played, frozenset((home, away)), frozenset(zip((home, away), score))))
            if game_observer is not None:
                game_observer(first.get("espn_game_id") or f"ncaa:{game_id}", played, home, away,
                              score, "NCAA", [(int(period), None, lineup, scored)
                                              for (period, _), _, lineup, scored in accepted], len(excluded_observations))
            include(game_id, played, ((lineup, scored) for _, _, lineup, scored in accepted))

    primary_count = len(accepted_dates)
    paths = [ROOT / f"rapm_backfill_{season}.csv.gz"]
    if extra_backfill is not None:
        paths.append(extra_backfill)
    for game_id, played, observations in backfill_games(
        season, cutoff, roster, accepted_espn_ids, accepted_matchups, paths, game_observer
    ):
        include(game_id, played, observations)
    if not fit:
        return roster, team_names
    if not groups:
        raise ValueError(f"No validated D-I lineup games. Exclusions {dict(rejected)}")
    print(f"RAPM accepted {primary_count}/{len(games)} primary feed games and "
          f"{len(accepted_dates) - primary_count} backfill games, "
          f"{sum(value[0] for value in groups.values())} possessions. Primary feed exclusions {dict(rejected)}")

    ratings = solve_rapm(groups, exposures, appearances, last_dates, roster, team_names)
    return ratings, roster, team_names, max(accepted_dates).isoformat()


def solve_rapm(groups, exposures, appearances, last_dates, roster, team_names):
    players = sorted(exposures)
    index = {player: i for i, player in enumerate(players)}
    size = len(players)
    weight = np.array([value[0] for value in groups.values()], dtype=float)
    target = np.array([value[1] for value in groups.values()], dtype=float) / weight
    # Preserve the total possession weight so recency does not change the
    # overall strength of the ridge penalty relative to the observed sample.
    weight *= (sum(exposures.values()) / 10) / weight.sum()
    scale = np.sqrt(weight)
    columns = np.fromiter(
        (index[player] + (size if i >= 5 else 0)
         for lineup in groups for i, player in enumerate(lineup)), dtype=np.int32
    )
    coefficients = np.tile([1.0] * 5 + [-1.0] * 5 + [1.0], (len(groups), 1))
    coefficients *= scale[:, None]
    # Fit one unpenalized league scoring intercept plus penalized player effects.
    columns = np.column_stack((columns.reshape(-1, 10), np.full(len(groups), size * 2)))
    design = csr_matrix(
        (coefficients.ravel(), columns.ravel(), np.arange(0, 11 * (len(groups) + 1), 11)),
        shape=(len(groups), 2 * size + 1),
    )
    penalty = diags(np.r_[np.full(size * 2, math.sqrt(ALPHA)), 0.0], format="csr")
    solution = lsqr(vstack((design, penalty), format="csr"),
                    np.r_[target * scale, np.zeros(size * 2 + 1)],
                    atol=1e-9, btol=1e-9, iter_lim=600)
    if solution[1] not in (0, 1, 2, 4, 5):
        raise RuntimeError(f"RAPM regression failed to converge (LSQR status {solution[1]})")
    effects = solution[0]
    ratings = {
        player: {
            "player_name": roster[player], "team": team_names[player[0]],
            "ncaa_player_id": player[1] if not player[1].startswith("bt:") else "",
            "rapm": (effects[i] + effects[i + size]) * 100,
            "rapm_games": len(appearances[player]), "rapm_possessions": exposures[player],
            "rapm_last_game": last_dates[player].isoformat(),
        }
        for i, player in enumerate(players)
    }
    return ratings


def join_players(bpm, rapm, roster, ncaa_teams, season):
    torvik_names = defaultdict(set)
    for player in bpm.values():
        torvik_names[player["team"]].add(key(player["player_name"]))
    roster_names = defaultdict(set)
    for (team_id, _), name in roster.items():
        roster_names[team_id].add(key(name))
    team_lookup = unique((key(team), team) for team in torvik_names)
    mapped_teams = {}
    for team_id, team in ncaa_teams.items():
        if key(team) in team_lookup:
            mapped_teams[team_id] = team_lookup[key(team)]
            continue
        overlap = sorted(((len(names & roster_names[team_id]), name)
                          for name, names in torvik_names.items()), reverse=True)
        if len(overlap) > 1 and overlap[0][0] >= 3 and overlap[1][0] <= 1:
            mapped_teams[team_id] = overlap[0][1]

    torvik_lookup = unique(
        ((player["team"], key(player["player_name"])), identifier)
        for identifier, player in bpm.items()
    )
    candidates = {
        player: torvik_lookup.get((mapped_teams.get(player[0]), key(rating["player_name"])))
        for player, rating in rapm.items()
    }
    for player, identifier in PLAYER_CROSSWALKS.get(season, {}).items():
        if player in candidates and identifier in bpm:
            candidates[player] = identifier
    counts = Counter(candidates.values())
    combined = {identifier: dict(player) for identifier, player in bpm.items()}
    unmatched = []
    for player, rating in rapm.items():
        identifier = candidates[player]
        if identifier is not None and counts[identifier] == 1:
            combined[identifier].update({
                field: value for field, value in rating.items()
                if field not in ("player_name", "team")
            })
        else:
            unmatched.append(rating)
    print(f"Matched {len(rapm) - len(unmatched)}/{len(rapm)} RAPM players to Torvik.")
    return sorted([*combined.values(), *unmatched],
                  key=lambda player: (player["team"], player["player_name"],
                                      player.get("torvik_player_id", "")))


def main():
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=today.year + (today.month >= 7))
    parser.add_argument("--output", type=Path, default=ROOT / "player_ratings.csv")
    parser.add_argument("--inputs", type=Path, help="Use local copies of the provider files")
    parser.add_argument("--bpm-from-postgres", action="store_true",
                        help="Read raw box scores from recruiting.source_snapshot using libpq settings")
    args = parser.parse_args()
    output_path = args.output.resolve()
    cutoff = min(today - timedelta(days=1), date(args.season, 6, 30))
    now = datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")

    with tempfile.TemporaryDirectory(prefix="player-ratings-") as temporary:
        inputs = args.inputs or Path(temporary)
        if args.inputs is None:
            for name in FEEDS:
                tag = f"ncaa_mbb_{name}"
                download(f"{RELEASES}/{tag}/{tag}_{args.season}.csv.gz", inputs / f"{name}.csv.gz")
            if not args.bpm_from_postgres:
                download(f"{TORVIK}/{args.season}_all_advgames.json.gz", inputs / "torvik-games.json.gz")

        bpm, bpm_through = season_bpm(game_logs(inputs, args.season, args.bpm_from_postgres),
                                      args.season, cutoff)
        rapm, roster, teams, rapm_through = lineup_ratings(inputs, args.season, cutoff)
        players = join_players(bpm, rapm, roster, teams, args.season)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                         dir=output_path.parent, delete=False) as output:
            draft = Path(output.name)
            try:
                writer = csv.DictWriter(output, fieldnames=COLUMNS)
                writer.writeheader()
                for player in players:
                    player.update(season=args.season, rapm_through=rapm_through,
                                  bpm_through=bpm_through, refreshed_at_utc=now)
                    for metric in ("bpm", "rapm"):
                        if player.get(metric) is not None:
                            player[metric] = f"{player[metric]:.3f}"
                    writer.writerow(player)
                output.close()
                draft.replace(output_path)
            finally:
                draft.unlink(missing_ok=True)
        print(f"Wrote {len(players)} players to {output_path}")


if __name__ == "__main__":
    main()
