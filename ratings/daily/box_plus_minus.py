"""Locally calculated season BPM using a college adaptation of Myers' BPM 2.0."""
from collections import Counter, defaultdict
from datetime import date, datetime

import numpy as np
from scipy.linalg import solve
from scipy.optimize import brentq

# Raw game-log columns. Published ratings and possession estimates are ignored.
BOX_COLUMNS = {
    "two_made": 23, "two_attempts": 24, "threes": 25, "three_attempts": 26,
    "free_throws": 27, "fta": 28, "points": 33, "orb": 34, "drb": 35,
    "assists": 36, "turnovers": 37, "steals": 38, "blocks": 39, "fouls": 42,
}
FT_WEIGHT = 0.44
TEAM_PRIOR_GAMES = 3.0
PLAYER_PRIOR_POSSESSIONS = 100.0


def complete_team_box(rows):
    if len({row[51] for row in rows}) != len(rows):
        raise ValueError("Duplicate player in a team box score")
    minutes = np.array([float(row[8]) for row in rows])
    stats = {stat: np.array([float(row[column]) for row in rows])
             for stat, column in BOX_COLUMNS.items()}
    if not np.isfinite(minutes).all() or np.any(minutes < 0):
        raise ValueError("Invalid minutes")
    for values in stats.values():
        if not np.isfinite(values).all() or np.any(values < 0) or np.any(values % 1):
            raise ValueError("Invalid box score count")
    if not np.array_equal(stats["points"], 2 * stats["two_made"] + 3 * stats["threes"]
                          + stats["free_throws"]):
        raise ValueError("Box score scoring identity failed")
    if (np.any(stats["two_made"] > stats["two_attempts"])
        or np.any(stats["threes"] > stats["three_attempts"])
        or np.any(stats["free_throws"] > stats["fta"])):
        raise ValueError("Makes exceed attempts")
    if any(np.any(values[minutes == 0]) for values in stats.values()):
        raise ValueError("Counting stats without playing time")
    total_minutes = minutes.sum()
    expected = 200 + 25 * max(round((total_minutes - 200) / 25), 0)
    if abs(total_minutes - expected) > 1.5 or np.any(minutes > expected / 5 + 0.1):
        raise ValueError("Incomplete team minutes")
    stats["fga"] = stats["two_attempts"] + stats["three_attempts"]
    return minutes, stats


def bounded_team_average(values, minutes):
    shift = brentq(
        lambda offset: np.average(np.clip(values + offset, 1, 5), weights=minutes) - 3,
        1 - values.max(), 5 - values.min(),
    )
    return np.clip(values + shift, 1, 5)


def calculate_team_bpm(stats, minutes, possessions, league_points_per_shot, team_rating,
                       listed_positions=3.0):
    """Allocate a team's adjusted net rating across its players."""
    fraction = 5 * minutes / minutes.sum()

    def share(counts):
        total = counts.sum()
        # A team with no events of this type supplies no evidence about player roles.
        return counts / (total * fraction) if total else np.full_like(minutes, 0.2)

    shots = stats["fga"] + FT_WEIGHT * stats["fta"]
    team_points_per_shot = stats["points"].sum() / shots.sum()
    threshold_points = stats["points"] - (team_points_per_shot - 0.33) * shots

    position = (2.130 + 8.668 * share(stats["orb"] + stats["drb"])
                - 2.486 * share(stats["steals"]) + 0.992 * share(stats["fouls"])
                - 3.536 * share(stats["assists"]) + 1.667 * share(stats["blocks"]))
    role = 6.0 - 6.642 * share(stats["assists"]) - 8.544 * share(threshold_points)
    position = bounded_team_average((position * minutes + 50 * listed_positions) / (minutes + 50),
                                    minutes)
    role = bounded_team_average((role * minutes + 50 * 4.0) / (minutes + 50), minutes)
    position_weight = (position - 1) / 4
    shot_cost = -0.560 - 0.220 * (role - 1) / 4
    adjusted_points = stats["points"] + (league_points_per_shot - team_points_per_shot) * shots

    box_value = (
        0.860 * adjusted_points + 0.389 * stats["threes"]
        + (0.580 + 0.454 * position_weight) * stats["assists"] - 0.964 * stats["turnovers"]
        + (0.613 - 0.432 * position_weight) * stats["orb"]
        + (0.116 + 0.065 * position_weight) * stats["drb"]
        + (1.369 - 0.361 * position_weight) * stats["steals"]
        + (1.327 - 0.624 * position_weight) * stats["blocks"]
        - 0.367 * stats["fouls"] + shot_cost * shots
    )
    raw = (100 * box_value / possessions - 0.409 * np.maximum(3 - position, 0)
           + 1.387 * (role - 3))
    # Shrink small samples toward the team's average before the final team adjustment.
    raw_mean = np.average(raw, weights=possessions)
    stabilized = raw_mean + (raw - raw_mean) * possessions / (possessions + PLAYER_PRIOR_POSSESSIONS)
    return stabilized + team_rating / 5 - np.average(stabilized, weights=possessions)


def adjusted_team_ratings(matchups, teams):
    """Regress each game's net margin on team strength difference and venue."""
    index = {team: i for i, team in enumerate(teams)}
    design = np.zeros((len(matchups), len(teams) + 1))
    target = np.empty(len(matchups))
    for i, (first, second, venue, pace, margin) in enumerate(matchups):
        scale = np.sqrt(pace / 70)
        design[i, index[first]] = scale
        design[i, index[second]] = -scale
        design[i, -1] = scale * venue
        target[i] = scale * 100 * margin / pace
    penalty = np.diag([TEAM_PRIOR_GAMES] * len(teams) + [1.0])
    coefficients = solve(design.T @ design + penalty, design.T @ target, assume_a="pos")
    return {team: coefficients[i] for team, i in index.items()}


def restore_mikalauskas(sides, player_id):
    """Restore the 43 seconds that the raw box assigns to Tristan Hankins."""
    arlington = sides.get("UT Arlington")
    hawaii = sides.get("Hawaii")
    if not arlington or not hawaii or any(
        row[48].casefold() == "kajus mikalauskas" for row in arlington
    ):
        return
    hankins = next((row for row in arlington if str(row[51]) == "143984"), None)
    if (hankins is None or float(hankins[8]) != 36.5
        or sum(row[33] for row in arlington) != 62 or sum(row[33] for row in hawaii) != 71):
        return
    # ESPN's play-by-play records the swap at 3:19 and 2:36. CBS's box
    # score corroborates Mikalauskas's appearance and zero counting stats.
    corrected = list(hankins)
    corrected[8] = (35 * 60 + 46) / 60
    player = [None] * len(hankins)
    for column in (0, 5, 6, 46, 47, 52):
        player[column] = hankins[column]
    player[8], player[48], player[51] = 43 / 60, "Kajus Mikalauskas", player_id
    for column in BOX_COLUMNS.values():
        player[column] = 0
    arlington[arlington.index(hankins)] = corrected
    arlington.append(player)


def season_bpm(game_rows, season, cutoff, *, include_box_id=False, listed_positions=None):
    listed_positions = listed_positions or {}
    games = defaultdict(lambda: defaultdict(list))
    mikalauskas_id = "ncaa:11641617"
    for row in game_rows:
        if len(row) < 53 or int(row[52]) != season:
            raise ValueError("Unexpected season or format in the raw game log")
        game_date = datetime.strptime(str(row[0]), "%Y%m%d").date()
        if season == 2027 and row[47] == "UT Arlington" and row[48].casefold() == "kajus mikalauskas":
            mikalauskas_id = row[51]
        if date(season - 1, 7, 1) <= game_date <= cutoff:
            games[game_date, row[6]][row[47]].append(row)

    missing_box = (date(2026, 11, 8), "UT ArlingtonHawaii11-8")
    if season == 2027 and missing_box in games:
        restore_mikalauskas(games[missing_box], mikalauskas_id)

    totals = defaultdict(lambda: defaultdict(Counter))
    names, last_dates = {}, {}
    matches, accepted_dates = [], []
    rejected = Counter()
    for (played, _), sides in sorted(games.items()):
        if len(sides) != 2:
            rejected["missing_opponent_box"] += 1
            continue
        first, second = sorted(sides)
        first_box, second_box = sides[first], sides[second]
        venues = (first_box[0][46], second_box[0][46])
        if venues not in {("H", "A"), ("A", "H"), ("N", "N")} or any(
            any(row[5] != opponent or row[46] != venue for row in box)
            for box, opponent, venue in ((first_box, second, venues[0]),
                                         (second_box, first, venues[1]))
        ):
            rejected["inconsistent_matchup"] += 1
            continue
        try:
            boxes = [complete_team_box(rows) for rows in (first_box, second_box)]
        except (ValueError, TypeError):
            rejected["invalid_team_box"] += 1
            continue

        estimated = [np.sum(stats["fga"] + FT_WEIGHT * stats["fta"]
                            - stats["orb"] + stats["turnovers"]) for _, stats in boxes]
        pace = sum(estimated) / 2
        if min(estimated) <= 0 or any(
            (stats["fga"] + FT_WEIGHT * stats["fta"]).sum() <= 0 for _, stats in boxes
        ):
            rejected["invalid_shot_or_possession_total"] += 1
            continue
        margin = boxes[0][1]["points"].sum() - boxes[1][1]["points"].sum()
        matches.append((first, second, {"H": 1, "A": -1, "N": 0}[venues[0]], pace, margin))
        accepted_dates.append(played)

        for team, rows, (minutes, stats) in zip((first, second), (first_box, second_box), boxes):
            for i in np.flatnonzero(minutes > 0):
                source_id = str(rows[i][51])
                player_id = source_id if ":" in source_id else str(int(rows[i][51]))
                player = totals[team][player_id]
                player.update({stat: values[i] for stat, values in stats.items()})
                player.update(minutes=minutes[i], possessions=pace * 5 * minutes[i] / minutes.sum(),
                              games=1)
                names[team, player_id] = rows[i][48]
                last_dates[team, player_id] = played

    if not matches:
        raise ValueError(f"No validated BPM games. Exclusions {dict(rejected)}")
    teams = sorted(totals)
    ratings = adjusted_team_ratings(matches, teams)
    all_players = [player for team in teams for player in totals[team].values()]
    points_per_shot = sum(p["points"] for p in all_players) / sum(
        p["fga"] + FT_WEIGHT * p["fta"] for p in all_players
    )

    result = {}
    for team, players in totals.items():
        minutes = np.array([p["minutes"] for p in players.values()])
        possessions = np.array([p["possessions"] for p in players.values()])
        stats = {stat: np.array([p[stat] for p in players.values()])
                 for stat in (*BOX_COLUMNS, "fga")}
        position_priors = np.array([listed_positions.get((team, player_id), 3.0)
                                    for player_id in players])
        bpm = calculate_team_bpm(stats, minutes, possessions, points_per_shot, ratings[team],
                                 position_priors)
        for i, (player_id, counts) in enumerate(players.items()):
            result[player_id, team] = {
                "player_name": names[team, player_id], "team": team,
                "torvik_player_id": "" if ":" in player_id else player_id,
                **({"box_player_id": player_id} if include_box_id else {}),
                "bpm": bpm[i], "bpm_games": counts["games"],
                "bpm_minutes": round(float(minutes[i]), 1),
                "bpm_last_game": last_dates[team, player_id].isoformat(),
            }
    print(f"BPM calculated for {len(result)} players from {len(matches)}/{len(games)} games. "
          f"Exclusions {dict(rejected)}")
    return result, max(accepted_dates).isoformat()
