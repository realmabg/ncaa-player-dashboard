"""Read and validate official school game books for the daily Ratings job."""
import csv
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from html import unescape
from itertools import pairwise
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from player_ratings import ROOT, key, unique
from rebuild_espn_rapm import replay, sidearm_game, sidearm_minutes, sidearm_payload

STAT_FIELDS = {
    "two_made": "totalFieldGoalsMade", "two_attempts": "totalFieldGoalsAttempted",
    "threes": "threePointFieldGoalsMade", "three_attempts": "threePointFieldGoalsAttempted",
    "free_throws": "freeThrowsMade", "fta": "freeThrowsAttempted", "points": "totalPointsScored",
    "orb": "offensiveRebounds", "drb": "defensiveRebounds", "assists": "assists",
    "turnovers": "turnovers", "steals": "steals", "blocks": "blockedShots", "fouls": "personalFouls",
}

# The official log reconstructs 21:54. Torvik reports 21.9 and ESPN rounds to
# 22. The school's own printed box lists 23 for this player only.
SCHOOL_REPLAY_MINUTES = {
    ("401924721", "627312", "11483213"): (23, 21.9, (
        "https://barttorvik.com/2027_all_advgames.json.gz",
        "https://www.espn.com/mens-college-basketball/boxscore/_/gameId/401924721",
    )),
}


def text(value):
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value)).split())


def table_rows(table):
    return [[text(cell) for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S)]
            for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.S)]


def legacy_gamebook(html, neutral):
    """Normalize the classic SIDEARM box and play tables to the structured format."""
    title = re.search(r"<title>\s*Men(?:'|&#39;|&apos;)s Basketball .*? on (\d+/\d+/\d{4})", html, re.S)
    if not title or neutral is None:
        raise ValueError("No supported school box score with a confirmed venue")
    tables = re.findall(r"<table\b[^>]*>.*?</table>", html, re.S)
    boxes = [table for table in tables if "sortable-table" in table.split(">", 1)[0]]
    if len(boxes) != 2:
        raise ValueError("School game book does not contain exactly two player boxes")
    book = {"itsWomens": False, "isNeutral": neutral, "periodsWithPlays": [], "legacy": True,
            "gameDate": datetime.strptime(title[1], "%m/%d/%Y").strftime("%m/%d/%y")}
    for side, table in zip(("visiting", "home"), boxes, strict=True):
        caption = text(re.search(r"<caption\b[^>]*>(.*?)</caption>", table, re.S)[1])
        name, score = caption.rsplit(" ", 1)
        if not score.isdigit():
            raise ValueError("School player box has no final score")
        block = {"id": side, "scoreSummary": {"score": score}, "players": []}
        book.update({f"{side}Team": block, f"{side}TeamId": side,
                     f"{side}TeamName": name, f"{side}TeamScore": score})
        for cells in table_rows(table):
            if len(cells) != 15 or not cells[0].isdigit() or cells[3] in {"-", "--"}:
                continue
            jersey, player, starter, mins, fg, threes, ft, reb, _, pf, ast, tov, blk, stl, pts = cells
            player = re.sub(r"^\d+\s+", "", player).upper().replace(", ", ",")
            fgm, fga = fg.split("-")
            tpm, tpa = threes.split("-")
            ftm, fta = ft.split("-")
            orb, drb = reb.split("-")
            stats = dict(zip(STAT_FIELDS.values(), (fgm, fga, tpm, tpa, ftm, fta, pts,
                                                    orb, drb, ast, tov, stl, blk, pf), strict=True))
            minutes, _, seconds = mins.rstrip("+").partition(":")
            stats.update(minutesPlayed=minutes, secondsPlayed=seconds or "0")
            block["players"].append(dict(checkName=player, uniform=jersey, gamePlayed=1,
                                         gameStarted=int(starter == "*"), stats=stats))
    for period, table in enumerate((t for t in tables if 'class="sidearm-table play-by-play"' in t), 1):
        clock = "20:00" if period <= 2 else "5:00"
        plays = []
        for cells in table_rows(table):
            if len(cells) != 9:
                continue
            if re.fullmatch(r"\d{1,2}:\d{2}(?:\.\d+)?", cells[0]):
                clock = cells[0]
            elif cells[0] not in ("--", ""):
                continue
            sides = [(side, cells[index]) for side, index in (("visiting", 1), ("home", 5)) if cells[index]]
            if len(sides) != 1:
                continue
            side, value = sides[0]
            description, _, actor = value.partition(" by ")
            action, _, detail = description.partition(" ")
            actor = actor.split("(", 1)[0].strip().upper().replace(", ", ",")
            plays.append(dict(action=action, type=detail.strip(), teamId=side, time=clock, checkname=actor))
        book["periodsWithPlays"].append({"number": period, "plays": plays})
    return book


def parse_gamebook(html, neutral):
    try:
        return sidearm_payload(html)
    except ValueError:
        return legacy_gamebook(html, neutral)


def gamebook_urls(season):
    path = ROOT / f"school_gamebooks_{season}.csv"
    if not path.exists():
        return {}
    urls = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            urls[row["event"]].append(row["url"])
    return urls


def fetch_html(url):
    request = Request(url, headers={"User-Agent": "UCSD-Recruiting-Player-Ratings/1.0"})
    with urlopen(request, timeout=15) as response:
        html = response.read(8_000_001)
    if len(html) > 8_000_000:
        raise ValueError("School game book exceeds size limit")
    return html.decode("utf-8")


def school_schedules():
    with (ROOT / "school_gamebook_sites.csv").open(newline="", encoding="utf-8") as source:
        return {row["team"]: row["schedule"] for row in csv.DictReader(source)}


def school_aliases(season, roster_rows):
    path = ROOT / f"school_player_aliases_{season}.csv"
    if not path.exists():
        return {}
    jerseys = {(row["team_id"], row["player_id"]): row["jersey"] for row in roster_rows}
    with path.open(newline="", encoding="utf-8") as source:
        aliases = {}
        for row in csv.DictReader(source):
            team, player, jersey = row["team_id"], row["player_id"], row["jersey"]
            if jerseys.get((team, player), "").lstrip("0") == jersey.lstrip("0"):
                aliases[team, key(row["name"]), str(int(jersey))] = player
        return aliases


@lru_cache
def schedule_gamebooks(schedule):
    try:
        html = fetch_html(schedule)
    except (OSError, ValueError):
        return ()
    return tuple(dict.fromkeys(
        urljoin(schedule, unescape(path))
        for path in re.findall(r'''href=["'](/sports/[^"']+/stats/[^"']+/boxscore/\d+)["']''', html)
    ))


def candidate_urls(game, teams, exact_urls, schedules):
    yield from exact_urls
    for side, other in (("home", "away"), ("away", "home")):
        schedule = schedules.get(teams[game[f"{side}_team_id"]])
        if not schedule:
            continue
        opponent = key(teams[game[f"{other}_team_id"]])
        for url in reversed(schedule_gamebooks(schedule)):
            if url not in exact_urls and key(urlsplit(url).path.split("/")[-3]) == opponent:
                yield url


def school_gamebook(book, game, teams, player_ids, jersey_ids, roster, aliases):
    if book["itsWomens"] or datetime.strptime(book["gameDate"], "%m/%d/%y").date().isoformat() != game["game_date"]:
        raise ValueError("School game book has the wrong sport or game date")
    scheduled = {game[f"{side}_team_id"]: game[f"{side}_score"] for side in ("home", "away")}
    by_name = {key(teams[team]): team for team in scheduled}
    school_names = {"home": book["homeTeamName"], "away": book["visitingTeamName"]}
    clubs = {side: by_name.get(key(name)) for side, name in school_names.items()}
    if set(clubs.values()) != set(scheduled):
        raise ValueError("School game book does not match the two scheduled teams")
    scores = {"home": book["homeTeamScore"], "away": book["visitingTeamScore"]}
    if any(int(scores[side]) != scheduled[team] for side, team in clubs.items()):
        raise ValueError("School game book does not match the independent final score")

    box, mapped = [], {}
    for side, group in (("home", "homeTeam"), ("away", "visitingTeam")):
        team = clubs[side]
        for row in book[group]["players"]:
            check = row["checkName"]
            if check == "TEAM" or int(row["gamePlayed"]) != 1:
                continue
            last, first = check.rsplit(",", 1)
            name = row.get("playerFirstLastName") or f"{first} {last}"
            jersey = row["uniform"]
            player = player_ids.get((team, key(name)))
            if player is None and jersey.isdigit() and key(first):
                uniform = str(int(jersey))
                player = aliases.get((team, key(name), uniform))
                player = player or jersey_ids.get((team, uniform, key(last), key(first)[0]))
            if player is None:
                raise ValueError(f"School player {name} #{jersey} has no unique NCAA roster ID")
            if (team, check) in mapped or (team, player) in mapped.values():
                raise ValueError(f"School player {name} is duplicated")
            mapped[team, check] = team, player
            stats = {label: int(row["stats"][field]) for label, field in STAT_FIELDS.items()}
            stats["two_made"] -= stats["threes"]
            stats["two_attempts"] -= stats["three_attempts"]
            mins = sidearm_minutes(row["stats"])
            box.append((team, roster[team, player], player, mins, stats))
    return box, mapped, clubs, scheduled


def school_possessions(book, mapped, clubs, final, roster, player_ids, *, event=""):
    def actor_key(name):
        last, _, first = name.rpartition(",")
        return key(f"{first} {last}" if last else first)

    names = unique(((team, actor_key(name)), name) for team, name in mapped)
    box_by_id = {player: name for (_, name), player in mapped.items()}

    def resolve_actor(team, name):
        normalized = actor_key(name)
        match = names.get((team, normalized))
        if match is None:
            match = box_by_id.get((team, player_ids.get((team, normalized))))
        if match is None and book.get("legacy") and len(name) == 20:
            candidates = [full for club, full in mapped if club == team and full.startswith(name)]
            match = candidates[0] if len(candidates) == 1 else None
        return match or name

    school_final, players, plays = sidearm_game(book, clubs, resolve_actor=resolve_actor)
    periods = [int(period["number"]) for period in book["periodsWithPlays"] if period["plays"]]
    if school_final != final or len(periods) < 2 or periods != list(range(1, len(periods) + 1)):
        raise ValueError("School play-by-play is missing or has the wrong final score")
    # Scorekeepers can record a player checking in and immediately back out at
    # the same dead ball. An adjacent pair for a non-participant changes no lineup.
    appearances = Counter((play.team, play.player) for play in plays if play.player)
    zero_stints = set()
    for index, (entry, exit) in enumerate(pairwise(plays)):
        actor = (entry.team, entry.player)
        if (entry.player and entry.kind == "in" and exit.kind == "out"
                and actor not in players and appearances[actor] == 2
                and (entry.period, entry.clock, *actor) == (exit.period, exit.clock, exit.team, exit.player)):
            zero_stints.update((index, index + 1))
    plays = [play for index, play in enumerate(plays) if index not in zero_stints]
    observations, minutes, bad_seconds, _, _ = replay(plays, players, final)
    if bad_seconds:
        raise ValueError("School play-by-play does not reproduce box-score playing times")
    minute_review = []
    for actor, row in players.items():
        played = minutes[actor]
        if abs(played - row[3]) <= 1:
            continue
        team, player = mapped[actor]
        verified = SCHOOL_REPLAY_MINUTES.get((event, team, player))
        if verified is None or row[3] != verified[0] or abs(played - verified[1]) > 0.05:
            raise ValueError("School play-by-play does not reproduce box-score playing times")
        minute_review.append(dict(player_id=player, school_minutes=row[3], replay_minutes=round(played, 3),
                                  verified_minutes=verified[1], source_urls=verified[2]))
    possessions, counts, excluded = [], Counter(), 0
    for action, offense, points, lineup, disputed in observations:
        if disputed:
            excluded += 1
            continue
        lineup_by_team = dict(lineup)
        defense = next(team for team in final if team != offense)
        ordered = tuple(player for team in (offense, defense)
                        for player in sorted(mapped[team, actor] for actor in lineup_by_team[team]))
        if len({player for _, player in ordered}) != 10:
            raise ValueError("School play-by-play does not resolve ten distinct players")
        counts[offense] += 1
        possessions.append([action.period, action.clock, ordered, points, [roster[p] for p in ordered]])
    if min(counts[team] for team in final) < 40 or abs(counts[clubs["home"]] - counts[clubs["away"]]) > 3:
        raise ValueError("School play-by-play has unbalanced possession counts")
    return possessions, excluded, minute_review
