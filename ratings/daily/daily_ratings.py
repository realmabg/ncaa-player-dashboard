"""Ingest game data, recheck gaps, and publish BPM/RAPM from stored inputs."""
import argparse
import csv
import hashlib
import json
from math import floor
import os
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from itertools import chain
from pathlib import Path
from uuid import uuid4

from box_plus_minus import BOX_COLUMNS, complete_team_box, season_bpm
from daily_rapm import ESPN, PACIFIC, espn_scoreboards, fetch_json, recover_espn
from player_ratings import (FEEDS, RAPM_HALF_LIFE_DAYS, RELEASES, ROOT, download, feed_rows,
                            key, lineup_ratings, ncaa_date, rapm_game_weight, roster_jersey_ids,
                            roster_jersey_player, solve_rapm, unique)
from rapm_repairs import MISSING_ROSTER_PLAYERS, expected_score
from rebuild_espn_rapm import ESPN_NAME_VARIANTS, ESPN_ROSTER_JERSEYS, espn_game, replay
import ratings_store as store

# Increment INPUT_RULES_VERSION when validation, source selection or curated
# corrections change. The next successful run revalidates stored games.
INPUT_RULES_VERSION = 8
MODEL_VERSION = (f"bpm-college-roster-v2+rapm-ridge-2000-decay-{RAPM_HALF_LIFE_DAYS}d-v2"
                 f"+inputs-v{INPUT_RULES_VERSION}")

NCAA = "https://stats.ncaa.org/contests"
# The NCAA catalog carries an old and a corrected contest for this game.
SUPERSEDED_CONTESTS = {"6638547": ("6670672", "401920378")}
VERIFIED_FINALS = {
    "401920887": ({"627454": 62, "627586": 68},
                  "https://shupirates.com/sports/mens-basketball/stats/2026-27/charlotte/boxscore/11645"),
    "401925631": ({"627479": 54, "627295": 56},
                  "https://bradleybraves.com/boxscore.aspx?id=23039&path=mbball"),
    "401909694": ({"627521": 69, "627524": 113},
                  "https://seminoles.com/sports/mens-basketball/stats/2026/florida-am/boxscore/16827"),
    "401920378": ({"627235": 88, "627342": 93},
                  "https://hawkeyesports.com/sports/mbball/schedule"),
    "401925079": ({"627284": 84, "627537": 83},
                  "https://nsudemons.com/news/2026/11/14/demon-basketball-demons-ot-buzzer-beater-waved-off-as-nsu-falls-at-little-rock.aspx"),
    "401925889": ({"627434": 71, "627533": 46},
                  "https://uncbears.com/news/2026/11/14/mens-basketball-bears-fall-at-south-dakota-state"),
}
BOX_FIELDS = dict(two_made="fgm", two_attempts="fga", threes="tpm", three_attempts="tpa",
                  free_throws="ftm", fta="fta", points="pts", orb="orb", drb="drb",
                  assists="ast", turnovers="tov", steals="stl", blocks="blk", fouls="pf")
# Exact provider tags for players verified by team and jersey.
NCAA_BOX_ALIASES = {
    ("627449", "KHALI.HORTON"): "11956116",
    ("627467", "DANIEL.JAMES"): "11485090",
    ("627563", "SAM.SIMMONS"): "12151923",
}
MINUTES_COLUMN = 8
BOX_VOTE_COLUMNS = dict(BOX_COLUMNS, minutes=MINUTES_COLUMN)
# Verified final stints that the box scores rounded to zero or omitted.
FINAL_STINT_SECONDS = {
    "401925684": {"11474138": 8},
    "401909552": {"11479050": 12, "12154750": 12, "12154773": 12},
    "401920680": {"11480061": 21},
    "401920305": {"11956578": 28},
    "401909716": {"11481290": 17, "11484106": 17},
    "401909490": {"11477163": 14},
    "401909553": {"11473671": 29, "12154771": 29},
}
# Each entry records the disputed fields checked against a school game book.
SCHOOL_BOX_EVIDENCE = {
    "401927369": (
        "https://goblueraiders.com/news/2026/11/11/mens-basketball-blue-raiders-get-back-on-track-with-73-68-defeat-of-evansville",
        {"11471618": {"assists": 5}},
    ),
    "401925940": (
        "https://utahstateaggies.com/sports/mens-basketball/stats/2026-27/utah-tech/boxscore/16847",
        {"12153060": {"turnovers": 0}, "11472119": {"turnovers": 0}},
    ),
    "401928794": (
        "https://pepperdinewaves.com/sports/mens-basketball/stats/2026/sam-houston/boxscore/16850",
        {"11481211": {"minutes": 20}},
    ),
    "401917524": (
        "https://lmulions.com/sports/mens-basketball/stats/2026-27/south-alabama/boxscore/17969",
        {"12154705": {"minutes": 2}, "11644911": {"minutes": 24},
         "11644936": {"minutes": 22}},
    ),
    "401919041": (
        "https://okstate.com/sports/mens-basketball/stats/2026-27/texas-am/boxscore/17598",
        {"11645534": {"minutes": 11}},
    ),
    "401920064": (
        "https://gorhody.com/sports/mens-basketball/stats/2026-27/maryland-eastern-shore/boxscore/12014",
        {"11481744": {"minutes": 17}},
    ),
    "401906770": (
        "https://floridagators.com/documents/download/2026/11/9/2026.11.10_atFloridaState.pdf",
        {"11472071": {"minutes": 16.5}},
    ),
    "401910994": (
        "https://bgsufalcons.com/sports/mens-basketball/stats/2026-27/georgia-state/boxscore/25167",
        {"11949562": {"minutes": 27}},
    ),
    "401928996": (
        "https://valpoathletics.com/boxscore.aspx?id=13220&path=mbball",
        {"11476962": {"minutes": 36}},
    ),
    "401921174": (
        "https://utmsports.com/sports/mens-basketball/stats/2026-27/iu-indy/boxscore/13870",
        {"11473125": {"minutes": 22}},
    ),
    "401921175": (
        "https://iuindyjags.com/sports/mens-basketball/stats/2026-2027/southern-indiana/boxscore/17460",
        {"11564819": {"minutes": 11}},
    ),
    "401920692": (
        "https://gobobcats.com/sports/mens-basketball/stats/2026/vermont/boxscore/23634",
        {"12145104": {"minutes": 4}},
    ),
    "401920842": (
        "https://gobluehose.com/sports/mens-basketball/stats/2026-27/st-thomas/boxscore/14480",
        {"11476335": {"minutes": 17}},
    ),
    "401922248": (
        "https://fiusports.com/boxscore.aspx?id=15628&path=mbball",
        {"11565135": {"minutes": 29}},
    ),
    "401924743": (
        "https://yalebulldogs.com/sports/mens-basketball/stats/2026-27/howard/boxscore/21527",
        {"11475873": {"three_attempts": 9}, "11481741": {"three_attempts": 2}},
    ),
}


def matchup(played, home, away):
    return played, frozenset((home, away))


def catalog(inputs, scratch, season, cutoff, dates, previous):
    teams = {r["id"]: r["team"] for r in feed_rows(inputs, "team_ids", season)}
    by_name = unique((key(name), tid) for tid, name in teams.items())
    raw = list(feed_rows(inputs, "player_box", season))
    events = unique((r["contest_id"], r["espn_game_id"]) for r in raw if r["espn_game_id"])
    aliases = unique((r[f"{side}_espn_team_id"], r[f"{side}_ncaa_team_id"]) for r in raw
                     for side in ("home", "away") if r[f"{side}_espn_team_id"]
                     and r[f"{side}_ncaa_team_id"] in teams)
    games, sources, evidence = {}, defaultdict(dict), defaultdict(dict)
    known = {matchup(date.fromisoformat(g["game_date"]), g["home_team_id"], g["away_team_id"]): k
             for k, g in previous.items()}
    ids = {}

    def remember(played, home, away, score, provider, provider_id, url, event=None):
        pair = matchup(played, home, away)
        # Provider IDs identify a game even if an overnight date differs.
        prior = previous.get(f"espn:{event}") if event else None
        if prior:
            pair = matchup(date.fromisoformat(prior["game_date"]), home, away)
        elif event and f"espn:{event}" in ids:
            pair = ids[f"espn:{event}"]
        gid = known.setdefault(pair, f"espn:{event}" if event else f"ncaa:{provider_id}")
        games.setdefault(gid, dict(season=season, game_key=gid, game_date=pair[0].isoformat(),
                                   home_team_id=home, away_team_id=away,
                                   home_score=score[0], away_score=score[1]))
        evidence[gid][provider] = dict(zip((home, away), score))
        sources[gid][provider, provider_id] = dict(provider=provider, provider_game_id=provider_id, url=url)
        ids[f"{provider}:{provider_id}"] = pair
        if event:
            ids[f"espn:{event}"] = pair

    schedule = list(feed_rows(inputs, "schedule", season))
    final_contests = {r["contest_id"] for r in schedule
                      if all(r[f"{side}_score"].isdigit() for side in ("home", "away"))}
    for original, (replacement, espn) in SUPERSEDED_CONTESTS.items():
        events[original] = events[replacement] = espn
    for row in schedule:
        played = ncaa_date(row["game_date"])
        if played not in dates or not all(row[f"{side}_score"].isdigit() for side in ("home", "away")):
            continue
        home, away = (by_name.get(key(row[side])) for side in ("home", "away"))
        if not home or not away or home == away:
            continue
        ncaa = row["contest_id"]
        if ncaa in SUPERSEDED_CONTESTS and SUPERSEDED_CONTESTS[ncaa][0] in final_contests:
            continue
        remember(played, home, away, expected_score(ncaa, row), "ncaa", ncaa,
                 f"{NCAA}/{ncaa}/box_score", events.get(ncaa))

    for board in espn_scoreboards(sorted(dates | {d + timedelta(days=1) for d in dates}), scratch):
        for event in board:
            if not event["status"]["type"]["completed"]:
                continue
            game = event["competitions"][0]
            played = datetime.fromisoformat(event["date"]).astimezone(PACIFIC).date()
            if played > cutoff:
                continue
            if played not in dates and f"espn:{event['id']}" not in ids:
                continue
            sides = {c["homeAway"]: (aliases.get(c["team"]["id"]) or
                                     by_name.get(key(c["team"]["location"])), int(c["score"]))
                     for c in game["competitors"]}
            if set(sides) != {"home", "away"}:
                continue
            (home, hs), (away, aws) = sides["home"], sides["away"]
            if not home or not away or home == away:
                continue
            eid = event["id"]
            remember(played, home, away, (hs, aws), "espn", eid,
                     f"https://www.espn.com/mens-college-basketball/boxscore/_/gameId/{eid}", eid)
    for game_id, game in games.items():
        correction = VERIFIED_FINALS.get(game_id.removeprefix("espn:"))
        if correction and set(correction[0]) == {game["home_team_id"], game["away_team_id"]}:
            scores, url = correction
            for side in ("home", "away"):
                game[f"{side}_score"] = scores[game[f"{side}_team_id"]]
            evidence[game_id]["official_school"] = scores
            sources[game_id]["official_school", game_id] = dict(
                provider="official_school", provider_game_id=game_id, url=url)
    return teams, raw, games, {g: list(v.values()) for g, v in sources.items()}, evidence, known, ids, aliases


def box_row(game, tid, name, player, minutes, stats, neutral, teams):
    home = tid == game["home_team_id"]
    opponent = game["away_team_id"] if home else game["home_team_id"]
    row = [None] * 53
    row[0], row[5], row[6], row[8] = game["game_date"].replace("-", ""), teams[opponent], game["game_key"], minutes
    row[46], row[47], row[48], row[51], row[52] = (
        "N" if neutral else ("H" if home else "A"), teams[tid], name, player, game["season"])
    for stat, column in BOX_COLUMNS.items():
        row[column] = stats[stat]
    return row


def ncaa_box(game, rows, teams, neutral):
    result = []
    for raw in rows:
        team = raw["team_ncaa_team_id"]
        if team not in (game["home_team_id"], game["away_team_id"]):
            raise ValueError("NCAA box has an unresolved team")
        tag = raw["player"]
        reviewed_id, reviewed_name = MISSING_ROSTER_PLAYERS.get((team, tag), (None, None))
        player = raw["player_id"] or NCAA_BOX_ALIASES.get((team, tag)) or reviewed_id
        if not player:
            raise ValueError("NCAA box has an unresolved player")
        stats = {name: float(raw[field]) for name, field in BOX_FIELDS.items()}
        stats["two_made"] -= stats["threes"]
        stats["two_attempts"] -= stats["three_attempts"]
        name = raw["clean_name"] or reviewed_name or tag
        result.append(box_row(game, team, name, f"ncaa:{player}",
                              float(raw["mins"]), stats, neutral, teams))
    return result


def espn_box(game, summary, teams, aliases, player_ids, jersey_ids, reviewed_ids, replayed=None,
             *, school_rows=()):
    result = []
    neutral = summary["header"]["competitions"][0]["neutralSite"]
    school_ids = unique(
        ((row["team_id"], key(row["name"])), row["player_id"]) for row in school_rows
    )
    for block in summary["boxscore"]["players"]:
        team = aliases.get(block["team"]["id"])
        if team not in (game["home_team_id"], game["away_team_id"]):
            raise ValueError("ESPN box has an unresolved team")
        for group in block["statistics"]:
            for raw in group["athletes"]:
                if raw.get("didNotPlay") or not raw["stats"]:
                    continue
                data = dict(zip(group["labels"], raw["stats"]))
                athlete = raw["athlete"]
                name = athlete["displayName"]
                player = player_ids.get((team, key(name)))
                player = player or school_ids.get((team, key(name)))
                jersey = athlete.get("jersey")
                player = player or reviewed_ids.get((team, name, jersey))
                player = player or roster_jersey_player(jersey_ids, team, jersey, name)
                if not player:
                    raise ValueError(f"ESPN box player {name} has no unique NCAA roster ID")
                fg, fga = map(int, data["FG"].split("-"))
                threes, tpa = map(int, data["3PT"].split("-"))
                ft, fta = map(int, data["FT"].split("-"))
                stats = dict(two_made=fg-threes, two_attempts=fga-tpa, threes=threes,
                             three_attempts=tpa, free_throws=ft, fta=fta)
                for name_key, label in zip(("points", "orb", "drb", "assists", "turnovers", "steals",
                                            "blocks", "fouls"),
                                           ("PTS", "OREB", "DREB", "AST", "TO", "STL", "BLK", "PF")):
                    stats[name_key] = int(data[label])
                parts = data["MIN"].split(":")
                minutes = float(parts[0]) + (float(parts[1]) / 60 if len(parts) == 2 else 0)
                if replayed is not None:
                    minutes = replayed.get((block["team"]["id"], athlete["id"]), 0)
                result.append(box_row(game, team, name, f"ncaa:{player}", minutes, stats, neutral, teams))
    return result


def valid_box(rows, game, teams):
    for side in ("home", "away"):
        box = [r for r in rows if r[47] == teams[game[f"{side}_team_id"]]]
        if not box:
            raise ValueError(f"Missing {side} box score")
        _, stats = complete_team_box(box)
        points = int(sum(stats["points"]))
        expected = game[f"{side}_score"]
        # The official game includes an own basket with no individual scorer.
        if game["game_date"] == "2026-11-02" and box[0][47] == "Colgate" and (points, expected) == (74, 76):
            continue
        if points != expected:
            raise ValueError(f"{side} player points {points} differ from final {expected}")
    return sorted(rows, key=lambda r: (r[47], str(r[51])))


def load_school_boxes(season):
    boxes = defaultdict(list)
    path = ROOT / f"bpm_school_boxes_{season}.csv"
    if path.exists():
        with path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                boxes[row["event"]].append(row)
    return boxes


def school_box(game, rows, teams, neutral):
    box = [
        box_row(game, row["team_id"], row["name"], f"ncaa:{row['player_id']}",
                float(row["minutes"]), {stat: int(row[stat]) for stat in BOX_COLUMNS}, neutral, teams)
        for row in rows
    ]
    return valid_box(box, game, teams)


def restore_final_stints(rows, event, observations, roster, game, teams, neutral):
    stints = FINAL_STINT_SECONDS.get(event)
    if not stints or not observations:
        return rows, {}
    lineups = {player for _, _, lineup, _ in observations for player in lineup}
    by_id = {row[51]: index for index, row in enumerate(rows)}
    updated = rows.copy()
    restored = {}
    for team, player in sorted(lineups):
        if player not in stints:
            continue
        pid = f"ncaa:{player}"
        index = by_id.get(pid)
        if index is not None and rows[index][MINUTES_COLUMN] > 0:
            continue
        seconds = stints[player]
        if index is None:
            updated.append(box_row(game, team, roster[team, player], pid, seconds / 60,
                                   dict.fromkeys(BOX_COLUMNS, 0), neutral, teams))
        else:
            updated[index] = rows[index].copy()
            updated[index][MINUTES_COLUMN] = seconds / 60
        restored[player] = seconds
    return valid_box(updated, game, teams), restored


def school_minutes_with_feed_counts(official, candidates, game, teams):
    """Use the agreed feed counts when only the school minutes are needed."""
    ncaa, espn = candidates.get("ncaa"), candidates.get("espn")
    if not ncaa or not espn or box_conflicts(ncaa, espn, compare_minutes=False):
        raise ValueError("No feed corroborates all school counting stats")
    by_player = {(row[47], row[51]): row for row in ncaa}
    official_players = {(row[47], row[51]) for row in official}
    active = {player for player, row in by_player.items() if row[8] > 0}
    if not active <= official_players or not official_players <= by_player.keys():
        raise ValueError("School box and feeds have different player rows")
    resolved = []
    for row in official:
        count_row = by_player[row[47], row[51]].copy()
        count_row[MINUTES_COLUMN] = row[MINUTES_COLUMN]
        resolved.append(count_row)
    return valid_box(resolved, game, teams)


def box_conflicts(first, second, *, compare_minutes=True):
    a, b = ({(r[47], r[51]): r for r in rows if r[8] > 0 or any(r[c] for c in BOX_COLUMNS.values())}
            for rows in (first, second))
    conflicts = []
    for player in sorted(a.keys() | b.keys()):
        if player not in a or player not in b:
            row = a.get(player) or b[player]
            if row[8] <= 1 and all(row[c] == 0 for c in BOX_COLUMNS.values()):
                continue
            conflicts.append(f"{row[48]} is missing from one box")
            continue
        columns = BOX_VOTE_COLUMNS if compare_minutes else BOX_COLUMNS
        differences = [stat for stat, column in columns.items()
                       if not box_values_agree(stat, a[player][column], b[player][column])]
        if differences:
            conflicts.append(f"{a[player][48]} differs in {', '.join(differences)}")
    return conflicts


def box_values_agree(stat, first, second):
    return abs(first - second) <= 1 if stat == "minutes" else first == second


def school_vote_agrees(stat, feed, school):
    if stat == "minutes":
        # Whole-minute reports can corroborate a precise time at their precision.
        if float(feed).is_integer() or float(school).is_integer():
            return floor(feed + 0.5) == floor(school + 0.5)
        return abs(feed - school) <= 1 / 60
    return feed == school


def majority_box(ncaa_rows, espn_rows, school_values):
    """Resolve disputed fields with two agreeing sources and preserve the vote."""
    if any(detail.endswith(" is missing from one box") for detail in box_conflicts(ncaa_rows, espn_rows)):
        raise ValueError("Source vote cannot establish the player rows")
    espn = {(row[47], row[51]): row for row in espn_rows if row[8] > 0}
    resolved, votes = [], []
    for row in ncaa_rows:
        selected = row.copy()
        other = espn.get((row[47], row[51]))
        if row[8] > 0 and other is not None:
            player = row[51].removeprefix("ncaa:")
            for stat, column in BOX_VOTE_COLUMNS.items():
                ncaa, reported = row[column], other[column]
                if box_values_agree(stat, ncaa, reported):
                    continue
                school = school_values.get(player, {}).get(stat)
                if school is None:
                    raise ValueError(f"No third-source value for {row[48]}: {stat}")
                supports_ncaa = school_vote_agrees(stat, ncaa, school)
                supports_espn = school_vote_agrees(stat, reported, school)
                if supports_ncaa == supports_espn:
                    raise ValueError(f"No unique majority for {row[48]}: {stat}")
                selected[column] = ncaa if supports_ncaa else reported
                votes.append(dict(player_id=player, stat=stat, ncaa=ncaa, espn=reported,
                                  official_school=school, selected=selected[column],
                                  supported_source="ncaa" if supports_ncaa else "espn"))
        resolved.append(selected)
    # Keep the complete box when the votes all support the same feed.
    if votes and all(vote["supported_source"] == "espn" for vote in votes):
        return espn_rows, votes
    return resolved, votes


def replay_minutes(summary, event):
    _, final, players, plays = espn_game(summary, event)
    competitors = summary["header"]["competitions"][0]["competitors"]
    periods = {len(team.get("linescores", [])) for team in competitors}
    if len(periods) != 1 or min(periods) < 2:
        raise ValueError("Cannot verify the number of periods")
    expected = set(range(1, min(periods) + 1))
    if {p.period for p in plays} != expected or {p.period for p in plays if p.kind == "end" and p.clock == 0} != expected:
        raise ValueError("Play-by-play does not cover every period")
    _, minutes, bad_seconds, actor_errors, _ = replay(plays, players, final)
    if bad_seconds or actor_errors:
        raise ValueError("Substitutions do not establish playing time throughout the game")
    return minutes


def decision(rows, evidence, stamp, *, reason=None, excluded=0, review=False):
    if rows:
        status = "accepted_with_exclusions" if excluded or review else "accepted"
        revision = hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=False).encode()).hexdigest()
    else:
        status = "needs_review" if review else "retry"
        revision = None
    return dict(rows=rows, evidence=dict(evidence, reason=reason), status=status, revision=revision,
                excluded=excluded, reason=reason, retry_at=datetime.combine(stamp.astimezone(PACIFIC).date() + timedelta(days=1),
                                             datetime.min.time(), PACIFIC).isoformat()
                if status != "accepted" else None)


def collect(inputs, scratch, season, cutoff, dates, previous, stamp):
    school_boxes = load_school_boxes(season)
    teams, raw, games, sources, scores, known, ids, aliases = catalog(
        inputs, scratch, season, cutoff, dates, previous)
    ncaa_rows = defaultdict(list)
    for row in raw:
        ncaa_rows[row["contest_id"]].append(row)
    venue_by_event = {}
    for day in dates | {d + timedelta(days=1) for d in dates}:
        board = scratch / f"scoreboard-{day}.json"
        if board.exists():
            for event in json.loads(board.read_text())["events"]:
                venue_by_event[event["id"]] = event["competitions"][0].get("neutralSite")

    observations, rejected = {}, {}

    def remember(event, played, home, away, score, source, rows, excluded):
        pair = ids.get(f"espn:{event}") or ids.get(event) or matchup(played, home, away)
        gid = known.get(pair)
        if gid not in games:
            return
        if dict(zip((home, away), score)) != dict(zip(
            (games[gid]["home_team_id"], games[gid]["away_team_id"]),
            (games[gid]["home_score"], games[gid]["away_score"])
        )):
            rejected[gid] = "Possession feed final score differs from catalog"
            return
        observations[gid] = source, rows, excluded

    status = {}
    roster, _ = lineup_ratings(inputs, season, cutoff, status, game_observer=remember, fit=False)
    roster_rows = [r for r in feed_rows(inputs, "team_rosters", season) if r["player_id"]]
    roster_names = ((r, name) for r in roster_rows for name in (r["name"], r["clean_name"], r["player"]) if name)
    player_ids = unique(chain(
        (((team, key(name)), pid) for (team, pid), name in roster.items()),
        (((r["team_id"], key(name)), r["player_id"]) for r, name in roster_names),
    ))
    jersey_ids = roster_jersey_ids(roster_rows)
    roster_by_id = {(r["team_id"], r["player_id"]): r for r in roster_rows}
    reviewed_ids = {}
    for (club, name), (player, espn_jersey, _) in ESPN_NAME_VARIANTS.items():
        team = aliases.get(club)
        official = roster_by_id.get((team, player))
        if official and official["jersey"] == ESPN_ROSTER_JERSEYS.get(player, espn_jersey):
            reviewed_ids[team, name, espn_jersey] = player
    def score_conflict(gid):
        finals = scores[gid]
        return "official_school" not in finals and len({tuple(sorted(s.items())) for s in finals.values()}) > 1

    missing, ncaa_minutes = {}, {}
    for gid, game in games.items():
        if gid not in observations and not score_conflict(gid):
            played = date.fromisoformat(game["game_date"])
            sides = {teams[game[f"{s}_team_id"]]: game[f"{s}_score"] for s in ("home", "away")}
            missing[played, frozenset(sides.items())] = sides
            providers = {row["provider"]: row for row in sources[gid]}
            if "ncaa" in providers and "espn" in providers:
                ncaa = providers["ncaa"]
                try:
                    box = valid_box(ncaa_box(game, ncaa_rows[ncaa["provider_game_id"]],
                                             teams, neutral=False), game, teams)
                except (KeyError, TypeError, ValueError):
                    continue
                team_ids = {teams[tid]: tid for tid in (game["home_team_id"], game["away_team_id"])}
                ncaa_minutes[providers["espn"]["provider_game_id"]] = (ncaa["url"], {
                    (team_ids[row[47]], row[51].removeprefix("ncaa:"), row[33]): row[8]
                    for row in box
                })
    fallback, gaps = recover_espn(inputs, scratch, season, missing, teams, {}, ncaa_minutes=ncaa_minutes)
    if fallback:
        lineup_ratings(inputs, season, cutoff, game_observer=remember, extra_backfill=fallback, fit=False)
    gap_index = {(g["date"], frozenset(g["teams"])): g["reason"] for g in gaps}
    exclusions, historical_sources = {}, {}
    for path in (ROOT / "rapm_backfill_audit_through_2026-11-11.csv", scratch / "fallback-audit.csv"):
        if path.exists():
            with path.open(newline="") as f:
                for row in csv.DictReader(f):
                    event = row["espn_event_id"]
                    if row.get("excluded_lineup_possessions"):
                        exclusions[event] = int(row["excluded_lineup_possessions"])
                    historical_sources[event] = {field: row[field] for field in
                        ("source", "play_by_play_url", "source_review", "review_source_url",
                         "ncaa_minutes_source") if row.get(field)}

    def fetch_box(eid):
        path = scratch / f"{eid}.json"
        try:
            return eid, json.loads(path.read_text()) if path.exists() else fetch_json(f"{ESPN}/summary?event={eid}", path), None
        except (OSError, ValueError) as error:
            return eid, None, str(error)

    event_ids = {s["provider_game_id"] for rows in sources.values() for s in rows if s["provider"] == "espn"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        summaries = {eid: (data, error) for eid, data, error in pool.map(fetch_box, sorted(event_ids))}

    for gid, game in games.items():
        urls = list({s["url"] for s in sources[gid]})
        evidence = {"source_urls": sorted(urls), "final_scores": scores[gid]}
        if score_conflict(gid):
            yield game, sources[gid], {metric: decision([], evidence, stamp,
                    reason="NCAA and ESPN final scores disagree", review=True) for metric in ("bpm", "rapm")}
            continue
        source_ids = {s["provider"]: s["provider_game_id"] for s in sources[gid]}
        event = source_ids.get("espn")
        ncaa = source_ids.get("ncaa")
        summary, download_error = summaries.get(event, (None, None))
        verified_rows = school_boxes.get(event, ())
        candidates, errors = {}, {}
        unvalidated = {}
        neutral = venue_by_event.get(event)
        if summary:
            competition = summary["header"]["competitions"][0]
            neutral = competition.get("neutralSite", neutral)
            game_aliases = dict(aliases)
            if verified_rows:
                # The catalog already matched the ESPN sides for this event.
                for side in competition["competitors"]:
                    game_aliases.setdefault(side["id"], game[f"{side['homeAway']}_team_id"])
            try:
                unvalidated["espn"] = espn_box(game, summary, teams, game_aliases, player_ids,
                                               jersey_ids, reviewed_ids, school_rows=verified_rows)
                candidates["espn"] = valid_box(unvalidated["espn"], game, teams)
            except (KeyError, TypeError, ValueError) as error:
                errors["espn"] = str(error)
        elif download_error:
            errors["espn"] = download_error
        if ncaa_rows.get(ncaa) and neutral is not None:
            try:
                unvalidated["ncaa"] = ncaa_box(game, ncaa_rows[ncaa], teams, neutral)
                candidates["ncaa"] = valid_box(unvalidated["ncaa"], game, teams)
            except (KeyError, TypeError, ValueError) as error:
                errors["ncaa"] = str(error)
        conflicts = box_conflicts(*candidates.values()) if len(candidates) == 2 else []
        reported_conflicts = conflicts
        school = SCHOOL_BOX_EVIDENCE.get(event)
        majority = None
        if conflicts and school:
            url, school_values = school
            evidence["source_urls"] = sorted(set(evidence["source_urls"]) | {url})
            sources[gid].append(dict(provider="official_school_box", provider_game_id=event, url=url))
            try:
                resolved, votes = majority_box(candidates["ncaa"], candidates["espn"], school_values)
                candidates["source_majority"] = valid_box(resolved, game, teams)
                majority = {"url": url, "votes": votes}
                conflicts = []
            except ValueError as error:
                majority = {"url": url, "error": str(error)}
        minutes_review = None
        replay_used = False
        if summary and neutral is not None and (conflicts or not candidates):
            try:
                played_minutes = replay_minutes(summary, event)
                replayed_box = valid_box(
                    espn_box(game, summary, teams, game_aliases, player_ids, jersey_ids, reviewed_ids,
                             played_minutes, school_rows=verified_rows),
                    game, teams)
                ncaa_candidate = candidates.get("ncaa")
                if not ncaa_candidate and ncaa_rows.get(ncaa):
                    # A partial NCAA box may corroborate counting stats even if its minutes fail.
                    raw_ncaa = ncaa_box(game, ncaa_rows[ncaa], teams, neutral)
                    if box_conflicts(raw_ncaa, replayed_box, compare_minutes=False):
                        raise ValueError("NCAA counting stats differ from the ESPN box")
                if ncaa_candidate and box_conflicts(ncaa_candidate, replayed_box, compare_minutes=False):
                    raise ValueError("Replayed box counting stats differ from the NCAA box")
                if not ncaa_candidate or box_conflicts(ncaa_candidate, replayed_box):
                    candidates["espn"] = replayed_box
                    replay_used = True
                minutes_review = "ESPN substitution replay validated the playing time"
                conflicts = []
            except (KeyError, TypeError, ValueError) as error:
                minutes_review = str(error)
        chosen = "ncaa" if "ncaa" in candidates and not replay_used else "espn"
        if "source_majority" in candidates:
            chosen = "source_majority"
        school_review = None
        if verified_rows and neutral is not None and (conflicts or not candidates):
            url = verified_rows[0]["url"]
            timing_sources = {row["minutes_source"] for row in verified_rows}
            evidence["source_urls"] = sorted(set(evidence["source_urls"]) | {url} | timing_sources)
            sources[gid].append(dict(provider="official_school_box", provider_game_id=event, url=url))
            try:
                official = school_box(game, verified_rows, teams, neutral)
                agreeing = [source for source, rows in unvalidated.items()
                            if not box_conflicts(official, rows, compare_minutes=False)]
                school_review = {"url": url, "counting_stats_confirmed_by": agreeing}
                if event == "401922220" and "espn" in unvalidated and "espn" not in agreeing:
                    # The official book accounts for all 200 UNF minutes and omits Bergantino.
                    # ESPN's extra row has zero minutes and only the disputed foul.
                    espn_rows = unvalidated["espn"]
                    corroborating = [
                        row for row in espn_rows
                        if not (row[51] == "ncaa:12151694" and row[8] == 0
                                and all(row[col] == int(stat == "fouls")
                                        for stat, col in BOX_COLUMNS.items()))
                    ]
                    if (len(corroborating) == len(espn_rows) - 1
                        and not box_conflicts(official, corroborating, compare_minutes=False)):
                        agreeing.append("espn")
                        school_review["excluded_espn_box_row"] = {
                            "player_id": "12151694", "minutes": 0, "fouls": 1,
                            "reason": "Player is absent from the official box and substitution log",
                        }
                if timing_sources != {url}:
                    school_review["short_appearances"] = [
                        {"player_id": row["player_id"], "minutes": float(row["minutes"]),
                         "url": row["minutes_source"]}
                        for row in verified_rows if row["minutes_source"] != url
                    ]
                if not agreeing:
                    official = school_minutes_with_feed_counts(official, candidates, game, teams)
                    school_review.update(counting_stats_confirmed_by=["ncaa", "espn"],
                                         minutes_source="official_school_box",
                                         school_counting_stats_disagree=True)
                candidates["official_school_box"] = official
                chosen = "official_school_box"
                conflicts = []
            except (KeyError, TypeError, ValueError) as error:
                school_review = {"url": url, "error": str(error)}
        box_evidence = dict(evidence, box_sources=sorted(candidates), source_errors=errors, conflicts=conflicts)
        if school_review:
            box_evidence["school_box_review"] = school_review
            box_evidence["reported_box_conflicts"] = reported_conflicts
        if majority:
            box_evidence["source_majority"] = majority
            box_evidence["reported_box_conflicts"] = reported_conflicts
        if minutes_review:
            box_evidence["minutes_review"] = minutes_review
            box_evidence["reported_box_conflicts"] = reported_conflicts
        if replay_used:
            box_evidence["minutes_source"] = "espn_play_by_play"
        if conflicts:
            # Both complete boxes already passed validation. Use the NCAA feed
            # for ties, keeping the disagreement open for a later source vote.
            bpm = decision(candidates["ncaa"], dict(box_evidence, selected="ncaa",
                           selection_method="validated_source_default"), stamp,
                           reason="Validated NCAA box used pending corroboration", review=True)
        elif chosen in candidates:
            rows = candidates[chosen]
            if event in FINAL_STINT_SECONDS and gid in observations:
                try:
                    rows, restored = restore_final_stints(
                        rows, event, observations[gid][1], roster, game, teams, neutral)
                    if restored:
                        box_evidence["restored_stint_seconds"] = restored
                        box_evidence["stint_source"] = f"https://www.espn.com/mens-college-basketball/playbyplay/_/gameId/{event}"
                except ValueError as error:
                    box_evidence["short_stint_error"] = str(error)
            bpm = decision(rows, dict(box_evidence, selected=chosen), stamp)
        else:
            bpm = decision([], box_evidence, stamp, reason="No validated player box score and venue",
                           review=bool(errors) and not download_error)
        if gid in observations:
            source, rows, excluded = observations[gid]
            excluded = excluded or (exclusions.get(event, 0) if source == "backfill" else 0)
            encoded = [[period, clock, lineup, pts, [roster[p] for p in lineup]]
                       for period, clock, lineup, pts in rows]
            rapm = decision(encoded, dict(evidence, selected=source,
                                          reconstruction=historical_sources.get(event, {}),
                                          possession_exclusions=excluded), stamp, excluded=excluded,
                            reason="Some possessions have unresolved lineups or control" if excluded else None)
        else:
            problem = rejected.get(gid) or status.get(ncaa)
            names = frozenset(teams[game[f"{s}_team_id"]] for s in ("home", "away"))
            reason = gap_index.get((game["game_date"], names)) or problem or "No validated possession lineup"
            rapm = decision([], evidence, stamp, reason=reason,
                            review=bool(problem) or "Identity review" in reason or "mismatch" in reason)
        yield game, sources[gid], dict(bpm=bpm, rapm=rapm)


def listed_bpm_positions(roster_rows, teams):
    # Broad roster labels cover both guard spots and both forward spots.
    positions = {"G": 1.5, "F": 3.5, "C": 5.0}
    return unique(
        ((teams[row["team_id"]], f'ncaa:{row["player_id"]}'), positions[label])
        for row in roster_rows
        if row["team_id"] in teams and row["player_id"] and
        (label := row["position"].strip().upper()) in positions
    )


def fit_and_publish(season, cutoff, games, statuses, teams, stamp, *,
                    dry_run=False, listed_positions):
    dates = {g["game_key"]: g["game_date"] for g in games}
    expected = len(games)
    coverage = {m: dict(expected_games=expected, included_games=0, review_or_retry=0,
                        games_with_exclusions=0, excluded_input_rows=0)
                for m in ("bpm", "rapm")}
    manifest, boxes = [], []
    groups = defaultdict(lambda: [0, 0])
    exposures, appearances, latest, roster = Counter(), defaultdict(set), {}, {}
    for status in statuses:
        metric, gid, rows = status["metric"], status["game_key"], status["rows"]
        if status["status"] != "accepted":
            coverage[metric]["review_or_retry"] += 1
        if not rows:
            continue
        coverage[metric]["included_games"] += 1
        excluded = status.get("excluded_rows", status.get("excluded", 0))
        if excluded:
            coverage[metric]["games_with_exclusions"] += 1
            coverage[metric]["excluded_input_rows"] += excluded
        manifest.append([gid, metric, status["revision"]])
        if metric == "bpm":
            boxes.extend(rows)
            continue
        played = date.fromisoformat(dates[gid])
        weight = rapm_game_weight(played, cutoff)
        for _, _, lineup, points, names in rows:
            lineup = tuple(tuple(p) for p in lineup)
            groups[lineup][0] += weight
            groups[lineup][1] += weight * points
            for player, name in zip(lineup, names):
                roster[player] = name
                exposures[player] += 1
                appearances[player].add(gid)
                latest[player] = max(latest.get(player, date.min), played)
    if not boxes or not groups:
        raise ValueError("Both metrics need accepted game inputs before publishing")
    bpm, bpm_through = season_bpm(boxes, season, cutoff, include_box_id=True,
                                  listed_positions=listed_positions)
    rapm = solve_rapm(groups, exposures, appearances, latest, roster, teams)
    team_ids = unique((name, tid) for tid, name in teams.items())
    combined = {(team_ids[row["team"]], row["box_player_id"].removeprefix("ncaa:")): row
                for row in bpm.values()}
    for player, row in rapm.items():
        combined.setdefault(player, {}).update(row)
    players = []
    for (team_id, player_id), row in sorted(combined.items()):
        player_key = f"{team_id}:{player_id}"
        players.append(dict(season=season, through_date=cutoff.isoformat(), player_key=player_key,
                            player_name=row["player_name"], team=row["team"], bpm=row.get("bpm"),
                            rapm=row.get("rapm"), details=row))
    if len({p["player_key"] for p in players}) != len(players):
        raise ValueError("BPM and RAPM player identity collision")
    listed_count = sum((row["team"], row["box_player_id"]) in listed_positions
                       for row in bpm.values())
    coverage["bpm"].update(through_date=bpm_through, listed_position_players=listed_count,
                           fallback_position_players=len(bpm) - listed_count)
    coverage["rapm"]["through_date"] = max(latest.values()).isoformat()
    for counts in coverage.values():
        counts["missing_games"] = counts["expected_games"] - counts["included_games"]
    print(json.dumps(coverage, sort_keys=True))
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        included = {(gid, metric) for gid, metric, _ in manifest}
        reasons = {(s["game_key"], s["metric"]): s.get("reason") for s in statuses}
        with open(summary_path, "a", encoding="utf-8") as summary:
            print(f"## Ratings coverage through {cutoff}", file=summary)
            for metric, counts in coverage.items():
                missing = counts["missing_games"]
                print(f"\n- {metric.upper()}: {counts['included_games']}/{expected} accepted, "
                      f"{missing} missing", file=summary)
                if missing:
                    print(f"::warning::{metric.upper()} coverage through {cutoff}: {missing} games missing")
            print(f"\n- BPM positions: {listed_count} from rosters, "
                  f"{len(bpm) - listed_count} using position 3", file=summary)
            if any(c["missing_games"] for c in coverage.values()):
                print("\n| Game date | Game ID | Metric | Reason |\n|---|---|---|---|", file=summary)
                for gid, played in sorted(dates.items(), key=lambda game: (game[1], game[0]), reverse=True):
                    for metric in coverage:
                        if (gid, metric) not in included:
                            reason = reasons.get((gid, metric)) or "No accepted inputs"
                            reason = " ".join(reason.split())
                            print(f"Missing {metric.upper()} | {played} | {gid} | {reason}")
                            reason = reason.replace("|", "&#124;").replace("<", "&lt;")
                            print(f"| {played} | {gid} | {metric.upper()} | {reason} |", file=summary)

    if not dry_run:
        store.publish(dict(season=season, through_date=cutoff.isoformat(), published_at=stamp,
                           model_version=MODEL_VERSION,
                           coverage=coverage, input_manifest=manifest), players)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int)
    parser.add_argument("--cutoff", type=date.fromisoformat)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--recheck-season", action="store_true",
                        help="Revalidate previously processed games after applying historical corrections")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not os.environ.get("RATINGS_DATABASE_URL"):
        parser.error("Set the RATINGS_DATABASE_URL Actions secret before publishing")
    cutoff = args.cutoff or (datetime.now(PACIFIC).date() - timedelta(days=1))
    season = args.season or cutoff.year + (cutoff.month >= 7)
    stamp = datetime.now(timezone.utc)
    run_id = os.getenv("GITHUB_RUN_ID", str(uuid4())) + ":" + os.getenv("GITHUB_RUN_ATTEMPT", "1")
    previous, due, last_cutoff, last_version = ([], [], None, None)
    if not args.dry_run:
        previous, due, last_cutoff, last_version = store.load_queue(season, cutoff, stamp.isoformat())
    # A late final may have no row in the retry queue yet. Revisit recent dates
    # after the feed has had time to post the game.
    dates = {cutoff - timedelta(days=offset) for offset in range(3)
             if cutoff - timedelta(days=offset) >= date(season - 1, 7, 1)}
    dates.update(date.fromisoformat(day) for day in due)
    if args.recheck_season or (last_cutoff and last_version != MODEL_VERSION):
        dates.update(date.fromisoformat(game["game_date"]) for game in previous)
        if last_version != MODEL_VERSION and last_cutoff:
            print(f"Revalidating stored games after version change: {last_version} → {MODEL_VERSION}")
    if last_cutoff:
        start = date.fromisoformat(last_cutoff)
        dates.update(start + timedelta(days=i) for i in range(1, (cutoff-start).days+1))
    with tempfile.TemporaryDirectory(prefix="daily-ratings-") as folder:
        scratch = Path(folder)
        inputs = args.inputs or scratch
        if args.inputs is None:
            with ThreadPoolExecutor(max_workers=5) as pool:
                jobs = [pool.submit(download, f"{RELEASES}/ncaa_mbb_{name}/ncaa_mbb_{name}_{season}.csv.gz",
                                    inputs / f"{name}.csv.gz") for name in (*FEEDS, "player_box")]
                for job in jobs:
                    job.result()
        if not last_cutoff:
            dates.update(ncaa_date(r["game_date"]) for r in feed_rows(inputs, "schedule", season)
                         if ncaa_date(r["game_date"]) <= cutoff)
            if dates:
                dates.update(date(season-1, 11, 1)+timedelta(days=i)
                             for i in range(max(0, (cutoff-date(season-1, 11, 1)).days+1)))
        count = Counter()
        pending_writes = []
        dry_games, dry_statuses = [], []
        for game, sources, metrics in collect(inputs, scratch, season, cutoff, dates,
                                              {g["game_key"]: g for g in previous}, stamp):
            count.update(f"{metric}:{result['status']}" for metric, result in metrics.items())
            if args.dry_run:
                dry_games.append(game)
                dry_statuses.extend(dict(value, game_key=game["game_key"], metric=metric)
                                    for metric, value in metrics.items())
            else:
                pending_writes.append(store.game_batch(game, sources, metrics, run_id, stamp.isoformat()))
                if len(pending_writes) == 20:
                    store.query("\n".join(pending_writes))
                    pending_writes.clear()
        if pending_writes:
            store.query("\n".join(pending_writes))
        print(dict(count))
        games, statuses = (dry_games, dry_statuses) if args.dry_run else store.load_season(season, cutoff)
        teams = {r["id"]: r["team"] for r in feed_rows(inputs, "team_ids", season)}
        positions = listed_bpm_positions(feed_rows(inputs, "team_rosters", season), teams)
        fit_and_publish(season, cutoff, games, statuses, teams, stamp.isoformat(),
                        dry_run=args.dry_run, listed_positions=positions)


if __name__ == "__main__":
    main()
