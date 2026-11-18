"""Rebuild the audited November 2026 RAPM backfill from cached game sources."""
import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from itertools import groupby
from pathlib import Path

from player_ratings import ROOT, feed_rows, game_logs, key, roster_jersey_ids, roster_jersey_key, unique
from rapm_repairs import MISSING_ROSTER_PLAYERS

SOURCE_NOTES = {
    "401925940": ("Utah State's game log records Brown's layup before the "
                  "substitutions at 18:19 in the second half.",
                  "https://utahstateaggies.com/sports/mens-basketball/stats/2026-27/utah-tech/boxscore/16847"),
    "401929003": ("Hawai‘i's game log records Nance's offensive-foul turnover before "
                  "the substitutions at 10:21.",
                  "https://hawaiiathletics.com/boxscore.aspx?id=31833&path=mbball"),
    "401919759": ("School play-by-play orders Jevtic's layup before the substitutions at "
                  "15:54 and Duchamp's entry after the foul at 7:01.",
                  "https://lionathletics.com/boxscore.aspx?id=11083&path=mbball"),
    "401924911": ("UNLV's official play-by-play credits the 1H 3:43 three to Max Majerle.",
                  "https://unlvrebels.com/sports/mens-basketball/stats/2026-27/northern-arizona/boxscore/17950"),
    "401921747": ("Green Bay and ESPN agree on the three scorer credits. Cincinnati and Torvik "
                  "transfer one three from Collins to Colvin. The disputed candidates with both "
                  "players on court have identical RAPM lineups and points.",
                  "https://greenbayphoenix.com/sports/mens-basketball/stats/2026-27/cincinnati/boxscore/10693"),
    "401920371": ("UC San Diego credits the 2H 8:39 three to Leo Beath and records the "
                  "2H 14:48 offensive rebound before substitutions.",
                  "https://ucsdtritons.com/boxscore.aspx?id=12384&path=mbball"),
    "401924951": ("The official log also records an 11-second gap between Houston Christian's "
                  "exit and entry. The possession spanning it is excluded.",
                  "https://goleathernecks.com/boxscore.aspx?id=14882&path=mbball"),
    "401920306": ("The official log records a Georgia Tech defensive rebound and steal at the "
                  "same stoppage. Excluded the intervening Eastern Kentucky turnover observation "
                  "because the control sequence is ambiguous.",
                  "https://ekusports.com/boxscore.aspx?id=9906&path=mbball"),
    "401921809": ("The LSU game book identifies Ahmed Nedal Abdelrahman as #7. ESPN lists "
                  "him as Ahmed Nedal #9.",
                  "https://static.lsusports.net/assets/docs/mb/27stats/ls02.pdf"),
    "401929002": ("Hawai‘i's official box lists Kajus Mikalauskas, who is absent from the Torvik "
                  "game box. He is included in the replay based on the substitutions.",
                  "https://hawaiiathletics.com/boxscore.aspx?id=31831&path=mbball"),
}
# School box scores round these independently verified replay times.
VERIFIED_REPLAY_MINUTES = {
    "401911239": ("https://richmondspiders.com/sports/mens-basketball/stats/2026-27/southern-illinois/boxscore/12124",
                  {"Sam Simmons Jr.": 9, "Brock McClure": 2}),
    "401921086": ("https://umbcretrievers.com/sports/mens-basketball/stats/2026-27/morgan-state-university/boxscore/9692",
                  {"Manok Lual": 3, "Matar Wade": 2}),
}
ESPN_NAME_VARIANTS = {
    # Same-team aliases checked against roster jerseys and Torvik game boxes.
    ("2065", "Daniel Perez-Rouzan"): ("12156694", "23", 76244),
    ("2514", "Mike Parrotta"): ("12157957", "24", 145562),
    ("2115", "Daniel James"): ("11485090", "22", None),
    ("2115", "Matt Goodwin"): ("11938443", "6", 144161),
    ("2916", "Mekhi Conner"): ("12148839", "3", 144871),
    ("324", "Q Williams IV"): ("12146992", "4", 144738),
    ("2378", "JP Ndong"): ("11956726", "2", 144524),
    ("2771", "AJ Lesburt Jr."): ("11634490", "33", 77331),
    ("2771", "Elijah Wilborn"): ("11634485", "5", 78112),
    ("2771", "JP Skoric"): ("11634487", "10", 143923),
    ("2771", "Jacob Moore"): ("11484845", "14", 134306),
    ("2350", "Chris Jeffrey"): ("12151259", "6", 134243),
    ("2350", "Nic Anderson"): ("11482008", "8", 134120),
    ("2698", "Lou Hutchinson III"): ("12148075", "24", 76872),
    ("36", "Pops Dunson"): ("11565248", "2", 143749),
    ("70", "Mo Diao"): ("12149782", "34", 144934),
    ("70", "Will Jenson"): ("11476748", "32", 134466),
    ("2441", "Andy Ramirez"): ("11591223", "22", 143849),
    ("2441", "Brad Ballinger"): ("11591219", "25", 143846),
    ("2569", "Chris Parker"): ("11481808", "55", 135166),
    ("140", "Josh Kori"): ("12154180", "7", 145372),
    ("2572", "Max Blank"): ("11949413", "49", 144251),
    ("2572", "Mike Montano"): ("11949419", "6", 144256),
    ("2640", "Ahmed Nedal"): ("11474386", "9", 134870),
    ("2640", "Ben Vungo"): ("12158490", "5", 79465),
    ("2640", "Trey Lewis"): ("12340852", "12", 145638),
    ("2710", "Tayelor Moore"): ("12158056", "5", 145579),
    ("2320", "Mike Collins"): ("12148395", "7", 134643),
    ("2166", "JaQualon Roberts"): ("11482014", "24", 77890),
    ("2415", "Khali Horton"): ("11956116", "7", 79085),
    ("315", "Tae Blackshear"): ("11638289", "77", 133820),
    ("25", "Semetri Carr"): ("11471986", "3", 135006),
    ("399", "Zacharie Matulu"): ("11481537", "14", 79205),
    # Virginia Tech identifies Efrem “Butta” Johnson and lists him at #33.
    # https://hokiesports.com/news/2026/10/1/butta-johnson-set-to-join-hokies-mens-basketball-roster
    ("259", "Butta Johnson"): ("12155589", "33", None),
    ("257", "Sam Simmons Jr."): ("12151923", "2", 145134),
    ("2400", "Tianhao Wu"): ("12151613", "9", 145098),
    ("264", "BJ Roy"): ("11471842", "3", 135113),
    ("140", "DJ Jackson Jr."): ("12154162", "1", 145366),
    ("294", "Sam Mbingazo"): ("11592282", "35", 143865),
    ("127", "Cam Ward"): ("11471652", "3", 134374),
    ("339", "JR Kemm"): ("12151551", "5", 145087),
    ("94", "Juanma Ruiz"): ("11480811", "17", 134669),
    ("2737", "Anthony Smith III"): ("11939132", "3", 134952),
    ("2737", "Eesher Singh Sarai"): ("12153191", "6", 145291),
    ("2534", "Cheikh Sadibou Ndiaye"): ("11478497", "32", 128265),
    ("2502", "Gantas Krianauskas"): ("12149647", "22", 144919),
    ("2502", "Emil Skytt"): ("12149653", "8", 76032),
    ("249", "Cash Chavis"): ("12151866", "1", 126524),
    ("2751", "Mike Mora"): ("12153860", "1", 145340),
    ("2097", "AJ Wright Jr."): ("12153373", "1", 145300),
    ("2172", "Baba Mbengue"): ("11954700", "21", 126840),
    ("71", "Gustavo Guimares"): ("11477609", "17", 134893),
    # https://lemoynedolphins.com/sports/mens-basketball/stats/2026-27/manhattan-university/boxscore/15877
    ("2363", "Asier Miguel"): ("11480682", "11", None),
    # https://towsontigers.com/sports/mens-basketball/stats/2026-27/umbc/boxscore/29798
    ("119", "Stephon Ashley Wright"): ("12195893", "0", None),
    # https://fgcuathletics.com/sports/mens-basketball/roster/2026-27
    ("526", "BB Washington"): ("11479253", "8", None),
    ("526", "CJ Outlaw"): ("11593006", "45", None),
    # https://ucasports.com/roster.aspx?path=mbball&season=2026-27
    ("2110", "Harry Beauchamp"): ("11475344", "9", None),
    ("2110", "J.C. Shulman"): ("11475506", "4", None),
    ("2110", "R.J. Young"): ("12148184", "0", None),
    ("2110", "Simm-Marten Saadi"): ("12148179", "35", None),
}
ESPN_ROSTER_JERSEYS = {"11474386": "7", "11478497": "23"}
SHOT_CORRECTIONS = {
    "401924911": (1, 223, "5308449", "5108047"),
    "401920371": (2, 519, "5107287", "5106867"),
}


@dataclass(frozen=True)
class Play:
    period: int
    clock: float
    kind: str
    team: str = ""
    player: str = ""
    points: int = 0
    last_free_throw: bool = False
    single_free_throw: bool = False
    and_one: bool = False


def seconds(value):
    minutes, _, rest = value.rpartition(":")
    return int(minutes or 0) * 60 + float(rest)


def espn_game(summary, event=""):
    game = summary["header"]["competitions"][0]
    teams = {club["homeAway"]: club["id"] for club in game["competitors"]}
    final = {club["id"]: int(club["score"]) for club in game["competitors"]}
    players = {}
    for block in summary["boxscore"]["players"]:
        team = block["team"]["id"]
        for stats in block["statistics"]:
            if "MIN" not in stats["labels"]:
                continue
            for row in stats["athletes"]:
                if row.get("didNotPlay") or not row["stats"]:
                    continue
                athlete = row["athlete"]
                box = dict(zip(stats["labels"], row["stats"]))
                players[team, athlete["id"]] = (
                    athlete["displayName"], athlete.get("jersey", ""), row["starter"],
                    float(box["MIN"]), int(box["PTS"]),
                )
    plays = []
    kinds = {"586": "off_rebound", "587": "def_rebound", "598": "turnover",
             "521": "technical", "412": "end", "449": "dead_rebound", "607": "steal",
             "618": "block", "519": "foul"}
    for row in summary.get("plays", []):
        play_type = row["type"]["id"]
        text = row["text"]
        kind = kinds.get(play_type, "")
        last = single = False
        if play_type == "584":
            kind = "in" if "subbing in" in text else "out" if "subbing out" in text else "bad_sub"
        elif play_type == "540":
            kind = "free_throw"
            attempt = re.search(r"free throw (\d+) of (\d+)", text)
            if attempt is None:
                raise ValueError(f"unrecognized free throw: {text}")
            last = attempt[1] == attempt[2]
            single = attempt[1] == attempt[2] == "1"
        elif row.get("shootingPlay"):
            kind = "shot"
        elif play_type == "615" and "Jump Ball won" in text:
            kind = "jump"
        if kind:
            actors = row.get("participants", [])
            player = actors[0]["athlete"]["id"] if actors else ""
            plays.append(Play(row["period"]["number"], seconds(row["clock"]["displayValue"]),
                              kind, row.get("team", {}).get("id", ""), player,
                              int(row["scoreValue"]) if row.get("scoringPlay") else 0, last, single))
        elif row.get("scoringPlay"):
            raise ValueError(f"unrecognized scoring play: {text}")
    if event in SHOT_CORRECTIONS:
        period, clock, original, corrected = SHOT_CORRECTIONS[event]
        index, = (i for i, p in enumerate(plays) if
                  (p.period, p.clock, p.player, p.points) == (period, clock, original, 3))
        team = plays[index].team
        plays[index] = replace(plays[index], player=corrected)
        for player, delta in ((original, -3), (corrected, 3)):
            name, jersey, starter, minutes, points = players[team, player]
            players[team, player] = name, jersey, starter, minutes, points + delta
    if event == "401920371":
        index, = (i for i, p in enumerate(plays) if (p.period, p.clock, p.kind, p.player) ==
                  (2, 888, "out", "5243038"))
        if (plays[index + 1].kind, plays[index + 1].clock) != ("off_rebound", 888):
            raise ValueError("UC San Diego substitution sequence changed")
        plays[index:index + 2] = reversed(plays[index:index + 2])
    moves = {
        "401919759": ((1, 954, "shot", None), (1, 421, "foul", None)),
        "401929003": ((1, 621, "turnover", "foul"),),
        "401925940": ((2, 1099, "shot", None),),
    }
    for period, clock, kind, after in moves.get(event, ()):
        indices = [i for i, p in enumerate(plays) if (p.period, p.clock) == (period, clock)]
        index, = (i for i in indices if plays[i].kind == kind)
        destination = indices[0] if after is None else next(
            i + 1 for i in indices if plays[i].kind == after
        )
        plays.insert(destination, plays.pop(index))
    # ESPN can give the basket and its continuation free throw different clocks.
    # Only use the next live action in the same period, stopping at technicals.
    following = None
    for i in range(len(plays) - 1, -1, -1):
        play = plays[i]
        if (play.kind == "shot" and play.points and following and following.single_free_throw
                and (following.period, following.team, following.player)
                == (play.period, play.team, play.player)):
            plays[i] = replace(play, and_one=True)
        if play.kind not in {"in", "out", "foul", "dead_rebound", "block", "steal"}:
            following = play
    return teams, final, players, plays


def memphis_game(html, teams):
    """Read the school's structured box score and play-by-play payload."""
    encoded = json.loads(re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)[1])

    def decode(index):
        if index < 0:
            return None
        value = encoded[index]
        if isinstance(value, dict):
            return {field: decode(ref) for field, ref in value.items()}
        if isinstance(value, list):
            return [decode(ref) for ref in value]
        return value

    box = decode(next(i for i, row in enumerate(encoded)
                      if isinstance(row, dict) and "periodsWithPlays" in row))
    clubs = {box["homeTeamId"]: teams["home"], box["visitingTeamId"]: teams["away"]}
    final, players = {}, {}
    for side in ("homeTeam", "visitingTeam"):
        block = box[side]
        team = clubs[block["id"]]
        final[team] = int(block["scoreSummary"]["score"])
        for row in block["players"]:
            if not int(row["gamePlayed"]) or row["checkName"] == "TEAM":
                continue
            last, first = row["checkName"].split(",", 1)
            players[team, row["checkName"]] = (
                f"{first} {last}", row["uniform"], bool(int(row["gameStarted"])),
                float(row["stats"]["minutesPlayed"]), int(row["stats"]["totalPointsScored"]),
            )

    plays = []
    for period in box["periodsWithPlays"]:
        number = int(period["number"])
        for row in period["plays"]:
            action, detail = row["action"], row["type"]
            points = 0
            if action in {"GOOD", "MISS"}:
                kind = "free_throw" if detail == "FT" else "shot"
                if action == "GOOD":
                    points = 1 if detail == "FT" else 3 if detail == "3PTR" else 2
            elif action == "SUB":
                kind = detail.lower()
            elif action == "REBOUND":
                kind = {"DEF": "def_rebound", "OFF": "off_rebound", "DEADB": "dead_rebound"}[detail]
            else:
                kind = {"TURNOVER": "turnover", "FOUL": "foul", "STEAL": "steal",
                        "BLOCK": "block"}.get(action)
            if kind:
                team = clubs.get(row["teamId"], "")
                player = row["checkname"]
                if player == "TEAM":
                    player = ""
                plays.append(Play(number, seconds(row["time"]), kind, team, player, points))
        plays.append(Play(number, 0, "end"))
    # The school reports individual attempts. At a dead ball, consecutive
    # attempts by the same shooter are one trip.
    for i, play in enumerate(plays):
        if play.kind == "free_throw":
            following = next((p for p in plays[i + 1:] if p.kind not in
                              {"in", "out", "dead_rebound", "foul"}), None)
            same_trip = following and (following.kind, following.period, following.clock,
                                       following.team, following.player) == (
                "free_throw", play.period, play.clock, play.team, play.player)
            plays[i] = replace(play, last_free_throw=not same_trip)
    return final, players, plays


def replay(plays, players, final):
    lineups = {team: {player for (club, player), row in players.items() if club == team and row[2]}
               for team in final}
    if any(len(lineup) != 5 for lineup in lineups.values()):
        raise ValueError("missing starters")
    other = dict(zip(final, reversed(tuple(final))))
    minutes, scoring, player_points, actor_errors = (Counter() for _ in range(4))
    possessions = []
    bad_seconds = 0
    offense, anchor, points, disputed = "", None, 0, False
    technical = Counter()
    technical_clock = None
    technical_points = Counter()
    previous = None

    def tick(elapsed):
        nonlocal bad_seconds, disputed
        if elapsed < 0:
            raise ValueError("game clock reversed")
        for team, lineup in lineups.items():
            if len(lineup) != 5:
                bad_seconds += elapsed
                disputed |= elapsed > 0
            for player in lineup:
                minutes[team, player] += elapsed / 60

    def finish():
        nonlocal offense, anchor, points, disputed
        if anchor is not None:
            action, lineup = anchor
            possessions.append((action, offense, points, lineup, disputed))
        offense, anchor, points, disputed = "", None, 0, False

    for period, half in groupby(plays, key=lambda p: p.period):
        clock = 1200 if period <= 2 else 300
        if previous is not None and period != previous + 1:
            raise ValueError("missing period")
        previous = period
        for time, at_clock in groupby(half, key=lambda p: p.clock):
            block = list(at_clock)
            tick(clock - time)
            clock = time
            if technical_clock != time:
                technical.clear()
            for i, play in enumerate(block):
                kind, team, player = play.kind, play.team, play.player
                if kind in {"in", "out", "bad_sub"}:
                    if (team, player) not in players or kind == "bad_sub":
                        raise ValueError("unknown substitution")
                    if (player in lineups[team]) != (kind == "out"):
                        raise ValueError("conflicting substitution")
                    if kind == "in":
                        lineups[team].add(player)
                    else:
                        lineups[team].remove(player)
                    continue
                if play.points:
                    scoring[team] += play.points
                    player_points[team, player] += play.points
                if kind == "technical":
                    technical[other[team]] += 2
                    technical_clock = time
                    continue
                if kind == "free_throw" and technical[team]:
                    technical[team] -= 1
                    technical_points[team] += play.points
                    continue
                if kind == "end":
                    finish()
                    continue
                if kind == "jump":
                    if offense and team != offense:
                        finish()
                    continue
                if kind not in {"shot", "free_throw", "turnover", "off_rebound", "def_rebound"}:
                    continue
                if team not in lineups:
                    raise ValueError("live play missing team")
                wrong_actor = player and player not in lineups[team]
                if wrong_actor:
                    actor_errors[period, time, team, kind, player] += 1
                owner = other[team] if kind == "def_rebound" else team
                if offense and owner != offense:
                    finish()
                if kind == "def_rebound" and anchor is None:
                    # A duplicated rebound or one without a preceding attempt
                    # leaves no recorded shot to close.
                    continue
                offense = owner
                snapshot = tuple((club, tuple(sorted(ids))) for club, ids in lineups.items())
                invalid = bool(wrong_actor) or any(len(ids) != 5 for _, ids in snapshot)
                disputed |= invalid
                if anchor is None:
                    anchor = (play, snapshot)
                points += play.points
                and_one = play.and_one or (kind == "shot" and play.points and any(
                    p.kind == "free_throw" and p.team == team and p.player == player
                    and p.last_free_throw for p in block[i + 1:]
                ))
                if kind in {"turnover", "def_rebound"} or (kind == "shot" and play.points and not and_one) or (
                    kind == "free_throw" and play.last_free_throw and play.points
                ):
                    finish()
        tick(clock)
        finish()
        technical.clear()

    if scoring != final:
        raise ValueError(f"final score mismatch {dict(scoring)} vs {final}")
    if any(player_points[p] != row[4] for p, row in players.items()) or set(player_points) - players.keys():
        raise ValueError("individual play-by-play scoring disagrees with player box")
    recovered_points = Counter(technical_points)
    for _, team, points, _, _ in possessions:
        recovered_points[team] += points
    if recovered_points != final:
        raise ValueError("possession points do not reconcile")
    return possessions, minutes, bad_seconds, actor_errors, technical_points


def reconstruct(inputs, sources, match_file, destination, report_file, season=2027, *, use_torvik=True):
    team_names = {row["id"]: row["team"] for row in feed_rows(inputs, "team_ids", season)}
    espn_to_ncaa = unique(
        (row[f"{side}_espn_team_id"], row[f"{side}_ncaa_team_id"])
        for row in feed_rows(inputs, "pbp", season) for side in ("home", "away")
        if row[f"{side}_espn_team_id"] and row[f"{side}_ncaa_team_id"] in team_names
    )
    team_by_name = unique((key(name), team) for team, name in team_names.items())
    roster = list(feed_rows(inputs, "team_rosters", season))
    ncaa_players = unique(
        ((row["team_id"], key(name)), row["player_id"])
        for row in roster for name in (row["name"], row["player"], row["clean_name"])
        if name and row["player_id"]
    )
    jersey_ids = roster_jersey_ids(roster)
    roster_by_id = {(row["team_id"], row["player_id"]): row for row in roster}
    for (team, name), (player, _) in MISSING_ROSTER_PLAYERS.items():
        ncaa_players.setdefault((team, key(name)), player)
    box_games = defaultdict(dict)
    for row in game_logs(inputs, season, False) if use_torvik else ():
        box_games[row[0], row[47], row[5]][key(row[48])] = row

    with match_file.open(newline="", encoding="utf-8") as source:
        matches = list(csv.DictReader(source))
    reports, output = [], []
    for match in matches:
        event = match["espn_event_id"]
        report = {field: match[field] for field in
                  ("date", "home_team", "away_team", "espn_event_id", "source", "play_by_play_url")}
        reports.append(report)
        try:
            summary = json.loads((sources / f"{event}.json").read_text())
            teams, final, players, plays = espn_game(summary, event)
            if match["source"] == "University of Memphis":
                final, players, plays = memphis_game((sources / "memphis.html").read_text(), teams)
            if not plays:
                raise ValueError("source play-by-play is empty")
            team_ids = {}
            boxes = {}
            for side, opposite in (("home", "away"), ("away", "home")):
                club = teams[side]
                team = match[f"{side}_team"]
                team_id = espn_to_ncaa.get(club) or team_by_name.get(key(team))
                if not team_id:
                    raise ValueError(f"unmapped team {team} (ESPN {club})")
                team_ids[club] = team_id
                boxes[club] = box_games[match["date"].replace("-", ""), team, match[f"{opposite}_team"]]
                if final[club] != int(match[f"box_{side}"]) or (
                    use_torvik and sum(int(row[33]) for row in boxes[club].values()) != final[club]
                ):
                    raise ValueError(f"independent team score mismatch for {team}")

            observations, minutes, bad_seconds, actor_errors, tech = replay(plays, players, final)
            if event in SOURCE_NOTES:
                report["source_review"], report["review_source_url"] = SOURCE_NOTES[event]
            if event == "401920306":
                index, = (i for i, (p, _, _, _, _) in enumerate(observations)
                          if (p.period, p.clock, p.kind, p.player) == (1, 747, "turnover", "5461520"))
                action, owner, points, lineup, _ = observations[index]
                observations[index] = action, owner, points, lineup, True
            mapped = {}
            missing = set()
            discrepancies = []
            box_by_id = {club: {row[51]: row for row in rows.values()} for club, rows in boxes.items()}
            for (club, player), (name, jersey, _, source_minutes, source_points) in players.items():
                pk = key(name)
                target = ncaa_players.get((team_ids[club], pk))
                box = boxes[club].get(pk)
                if event == "401918987" and pk == "sebaswilliamsadams":
                    box = box_by_id[club].get(134430)
                    target = ncaa_players.get((team_ids[club], key("Sebastian Williams-Adams")))
                variant = ESPN_NAME_VARIANTS.get((club, name))
                if variant:
                    target, source_jersey, box_id = variant
                    box = box_by_id[club].get(box_id)
                    roster_row = roster_by_id.get((team_ids[club], target))
                    official_jersey = ESPN_ROSTER_JERSEYS.get(target, source_jersey)
                    if jersey != source_jersey or not roster_row or roster_row["jersey"] != official_jersey:
                        raise ValueError(f"Roster jersey mismatch for {name}")
                if target is None:
                    target = jersey_ids.get(roster_jersey_key(team_ids[club], jersey, name))
                if target is None:
                    missing.add((club, name, jersey))
                else:
                    mapped[club, player] = target
                actual = minutes[club, player]
                if box is not None and int(box[33]) != source_points:
                    known_difference = {"5105401": 3, "4894452": -3}.get(player)
                    if event != "401921747" or source_points - int(box[33]) != known_difference:
                        raise ValueError(f"Independent player scoring mismatch for {name}")
                if use_torvik and box is None and (source_points or (actual > 1 and target)):
                    raise ValueError(f"Missing player box for {name}")
                diff = None if box is None else round(actual - float(box[8]), 3)
                discrepancies.append((round(actual - source_minutes, 3), diff, name, actual))
            report["reconstructed"] = len(observations)
            report["technical_points"] = sum(tech.values())
            report["non_five_player_seconds"] = bad_seconds
            report["actor_conflicts"] = sum(actor_errors.values())
            report["source_max_minute_error"] = max(abs(row[0]) for row in discrepancies)
            report["torvik_max_minute_error"] = max((abs(row[1]) for row in discrepancies if row[1] is not None), default=None)
            school_url, school_minutes = VERIFIED_REPLAY_MINUTES.get(event, (None, {}))
            timing_disputes = [
                (source_diff, box_diff, name)
                for source_diff, box_diff, name, actual in discrepancies
                if abs(source_diff if box_diff is None else box_diff) > 1
                and (name not in school_minutes or abs(actual - school_minutes[name]) > 0.5)
            ]
            if school_url and not timing_disputes:
                report["source_review"] = "Official school box corroborates disputed replay minutes"
                report["review_source_url"] = school_url
            report["minute_review"] = "; ".join(
                f"{name} ({source_diff:+.2f} source, {box_diff if box_diff is not None else 'unavailable'} Torvik)"
                for source_diff, box_diff, name in timing_disputes
            )
            counts = Counter(owner for _, owner, _, _, _ in observations)
            report["home_possessions"] = counts[teams["home"]]
            report["away_possessions"] = counts[teams["away"]]
            report["excluded_lineup_possessions"] = sum(disputed for _, _, _, _, disputed in observations)
            report["issue"] = ""
            if missing:
                report["issue"] = "Identity review: " + ", ".join(
                    f"{name} #{jersey} (ESPN team {team})" for team, name, jersey in sorted(missing)
                )
                continue
            if len(set((team_ids[club], pid) for (club, _), pid in mapped.items())) != len(mapped):
                raise ValueError("two source athletes map to one NCAA player")
            if (bad_seconds and (event, bad_seconds) != ("401924951", 11)) or report["minute_review"]:
                report["issue"] = "Lineup timing requires review"
                continue
            kept = Counter(owner for _, owner, _, _, disputed in observations if not disputed)
            if min(kept[team] for team in final) < 40 or abs(kept[teams["home"]] - kept[teams["away"]]) > 3:
                report["issue"] = "Unbalanced possession counts"
                continue

            game_rows = []
            for action, owner, points, lineup, disputed in observations:
                if disputed:
                    continue
                by_side = dict(lineup)
                ids = [mapped[club, player] for club in (owner, next(t for t in final if t != owner))
                       for player in by_side[club]]
                if len(set(ids)) != 10:
                    raise ValueError("non-unique NCAA lineup")
                game_rows.append((event, match["date"], team_ids[teams["home"]], team_ids[teams["away"]],
                                  final[teams["home"]], final[teams["away"]],
                                  action.period, action.clock, team_ids[owner], points, *ids))
            report["used"] = len(game_rows)
            output.extend(game_rows)
        except (KeyError, StopIteration, ValueError) as error:
            report["issue"] = str(error)

    columns = ("event", "date", "home_team_id", "away_team_id", "home_score", "away_score",
               "period", "clock", "offense", "points",
               *(f"{side}_{i}" for side in ("offense", "defense") for i in range(1, 6)))
    with gzip.open(destination, "wt", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(output)
    with report_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(dict.fromkeys(k for row in reports for k in row)))
        writer.writeheader()
        writer.writerows(reports)
    print(f"Backfill contains {len(output)} possessions from {sum(bool(r.get('used')) for r in reports)} "
          f"of {len(matches)} games")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True, help="Local NCAA and Torvik provider files")
    parser.add_argument("--sources", type=Path, required=True, help="ESPN summaries and memphis.html")
    parser.add_argument("--matches", type=Path, default=ROOT / "espn_lineup_coverage_through_2026-11-10.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "rapm_backfill_2027.csv.gz")
    parser.add_argument("--report", type=Path, default=ROOT / "rapm_backfill_audit_through_2026-11-10.csv")
    args = parser.parse_args()
    reconstruct(args.inputs, args.sources, args.matches, args.output, args.report)
