"""Evidence-backed corrections to the NCAA possession feed."""
from collections import Counter, defaultdict
import csv
from pathlib import Path

# Team-scoped identities verified with official game boxes and rosters.
LINEUP_NAMES = {
    ("627272", "XABIER.LOPEZ.RODRIGUEZ"): "11565040",
    ("627453", "ALEXANDROS.SAMODUROV"): "11953036",
    ("627338", "ERIC.SHEFFIELD"): "11955751",
    ("627488", "CHARLES.DIMMOCK"): "11954695",
    ("627308", "DERRICK.FLORENCE"): "11593023",
    ("627583", "TJ.COPE"): "11953762",
    ("627354", "EESHER.SINGH.SARAI"): "12153191",
    ("627353", "TRE.BLASSINGAME"): "11588988",
    ("627353", "NICK.BYRD"): "11588991",
    ("627394", "CHRIS.JONES"): "11471945",
}
# Stable Torvik IDs identify players missing from the NCAA roster asset.
MISSING_ROSTER_PLAYERS = {
    ("627258", "MACALEAB.RICH"): ("bt:79258", "Macaleab Rich"),
    ("627498", "PHOENIX.WOODSON"): ("bt:145645", "Phoenix Woodson"),
    # The Oregon State game book confirms Sutton and Anglo are distinct players.
    # https://osubeavers.com/sports/mens-basketball/stats/2026-27/mississippi-valley-state/boxscore/22930
    ("627392", "CHANCE.SUTTON"): ("espn:5314772", "Chance Sutton"),
    # LSU's game book and roster confirm #12 before the NCAA roster export lists him.
    # https://lsusports.net/sports/mb/roster/player/rj-luis-jr
    ("627249", "RJ LUIS JR."): ("espn:5106035", "RJ Luis Jr."),
}
# In these games the named player checked in at the same dead ball as the
# phantom TEAM substitutions and was absent from the following lineup.
PLACEHOLDERS = {
    "6644550": ("627402", "06:58", "Rolyns Aligbe", "12145596"),
    "6642801": ("627400", "07:41", "Kellen Hampton", "11940424"),
}
# The school's substitution log identifies a different occupant in these
# first-half possessions. The feed continues to label the slot TEAM.
PLACEHOLDER_ROTATIONS = {
    "6644550": (65, 71, "12145607"),  # Chitikoudis for Aligbe at 03:50.
    "6642801": (74, 78, "11940425"),  # Matingou for Hampton at 01:44.
}
# The first live action follows a substitution in these rows. Correct the
# other slots that the feed carried forward from before the dead ball.
STALE_SLOTS = {
    ("6644550", "65"): {
        ("627402", "11475531"): "12145618",  # Pozzato to Borovicanin
        ("627402", "12145574"): "11479246",  # Nwoko to Milicevic
        ("627450", "12148041"): "12148033",  # Smith to Thompson
    },
    ("6642801", "72"): {("627400", "11940423"): "11940326"},  # Dengdit to Davidson
    ("6642801", "79"): {("627400", "11940325"): "11940423"},  # Adams to Dengdit
}
# Official play-by-play and ESPN agree on the five players at the first
# shot, free throw or turnover after these substitutions.
LATE_SUBSTITUTIONS = {
    ("6656672", "2", "145"): {  # Creighton–Kansas City, 0:14
        "12152238": "11477163", "12152241": "12152245",
    },
    ("6648503", "2", "130"): {"11482418": "11481290"},  # Syracuse–New Haven, 0:17
    ("6635773", "2", "150"): {  # Howard–Alcorn, 0:08
        "12151900": "12151897", "11472864": "11473966", "11478956": "11474138",
        "11633395": "11478833", "11633402": "11481452",
    },
    ("6626618", "2", "151"): {  # Saint Joseph's–Longwood, 0:38
        "11719310": "11719308", "11483291": "11476906", "11955697": "11955686",
        "11955699": "11955687", "11955702": "11955700",
    },
    ("6645019", "4", "171"): {  # Tulane–UT Martin, before the final turnover
        "11590104": "11590108", "11590363": "11590358",
    },
    ("6624390", "1", "60"): {  # New Haven–Army, before the first-half buzzer shot
        "11474181": "11476176", "11477072": "11482351", "11478002": "11646174",
    },
}
# Expected matchup and published score, followed by the school box-score result.
SWAPPED_SCORES = {
    "6613750": ("Coppin St.", "Bradley", (56, 54), (54, 56)),
    "6624357": ("App State", "Merrimack", (49, 63), (63, 49)),
    "6624363": ("UAB", "McNeese", (99, 78), (78, 99)),
}
IOWA_CONTEST = "6638547"
IOWA_SCHEDULE = ("11/10/2026", "Iowa", "Virginia Tech")


def iowa_reconstruction(game_id, schedule, source_row):
    if game_id != IOWA_CONTEST:
        return None
    if tuple(schedule[field] for field in ("game_date", "home", "away")) != IOWA_SCHEDULE:
        return None
    if (source_row["home_ncaa_team_id"], source_row["away_ncaa_team_id"]) != ("627235", "627342"):
        return None
    if (schedule["home_score"], schedule["away_score"]) not in {("89", "93"), ("88", "93")}:
        return None

    names = {"home": "Iowa", "away": "Virginia Tech"}
    team_ids = {"Iowa": "627235", "Virginia Tech": "627342"}
    metadata = {field: source_row[field] for field in (
        "game_date", "home", "away", "home_ncaa_team_id", "away_ncaa_team_id",
    )}
    path = Path(__file__).with_name("rapm_6638547_possessions.csv")
    rows, shots = [], {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            offense = row["offense"]
            score = {team: int(row[f"{side}_points"]) for side, team in names.items()}
            if row["use_for_rapm"] not in {"0", "1"} or min(score.values()) < 0:
                raise ValueError("Invalid verified Iowa possession")
            possession = (row["period"], row["poss_num"])
            if any(score.values()):
                shots[possession] = [
                    (team, points, "Free Throw" if team != offense else "Scoring plays")
                    for team, points in score.items() if points
                ]
            rows.append(dict(row, **metadata, poss_team=offense,
                             poss_team_ncaa_team_id=team_ids[offense], pts=str(sum(score.values()))))
            for side in names:
                for slot in range(1, 6):
                    rows[-1][f"{side}_{slot}"] = ""
    return rows, shots
# Adjacent fragments of the same possession. Retain the scoring fragment or
# the fragment containing the live sequence rather than a rebound-only stub.
# Each item records period, first possession number, source points, retained index.
SPLIT_POSSESSIONS = {
    "6653278": (("1", 68, (1, 0), 0), ("2", 106, (2, 0), 0),
                ("2", 123, (1, 0), 0), ("2", 146, (0, 0), 1)),
    "6641921": (("2", 82, (1, 0), 0), ("2", 145, (0, 0), 1)),
    "6638551": (("1", 66, (0, 2), 1), ("2", 134, (2, 0), 0),
                ("2", 137, (1, 0), 0)),
}


def placeholder_substitution(event):
    repair = PLACEHOLDERS.get(event["contest_id"])
    if repair is None or event["period"] != "1":
        return None
    team, clock, _, _ = repair
    if event["event_team_ncaa_team_id"] != team or event["clock"] != clock:
        return None
    return event["event_description"]


def colgate_team_basket(event):
    return (
        event["contest_id"] == "6640714" and event["period"] == "2"
        and event["clock"] == "02:07" and event["poss_num"] == "138"
        and event["event_team"] == "Washington"
        and event["event_type"] == "Turnover" and not event["shot_value"]
        and "2pt wrongbasket" in event["event_description"].lower()
    )


def collect_play_evidence(events, cutoff, parse_date):
    shots = defaultdict(lambda: defaultdict(list))
    substitutions = defaultdict(set)
    for event in events:
        if parse_date(event["game_date"]) > cutoff:
            continue
        game = event["contest_id"]
        if substitution := placeholder_substitution(event):
            substitutions[game].add(substitution)
        possession = (event["period"], event["poss_num"])
        if colgate_team_basket(event):
            shots[game][possession].append(("Colgate", 2, "Own basket"))
        elif (
            game == "6630675" and possession == ("1", "13") and event["clock"] == "14:39"
            and event["event_team"] == "Queens (NC)"
            and event["event_type"] == "Wrong Basket (2pt Opp. Team)"
            and (event["home_score"], event["away_score"]) == ("7", "11")
        ):
            # The school game book credits Cam Lowe with the tip-in.
            # https://queensathletics.com/sports/mens-basketball/stats/2026-2027/wofford/boxscore/13477
            shots[game][possession].append(("Wofford", 2, "Missed scoring credit"))
        elif event["event_result"] == "made":
            value = event["shot_value"]
            points = int(value) if value in ("1", "2", "3") else None
            shots[game][possession].append((event["event_team"], points, event["event_type"]))
    return shots, substitutions


def expected_score(game_id, schedule):
    scores = (int(schedule["home_score"]), int(schedule["away_score"]))
    repair = SWAPPED_SCORES.get(game_id)
    if repair and (schedule["home"], schedule["away"], scores) == repair[:3]:
        return repair[3]
    return scores


def placeholder_id(game, team, possession, tag, substitutions):
    period, number = possession
    repair = PLACEHOLDERS.get(game)
    if repair is None or period != "1" or tag != "TEAM" or repair[0] != team:
        return None
    _, _, player, player_id = repair
    needed = {"Team, substitution out", "Team, substitution in", f"{player}, substitution in"}
    if not needed <= substitutions.get(game, set()):
        return None
    start, end, rotation_id = PLACEHOLDER_ROTATIONS[game]
    return rotation_id if number.isdigit() and start <= int(number) <= end else player_id


def updated_slot(game, possession, team, player_id, placeholder_present):
    late_substitutions = LATE_SUBSTITUTIONS.get((game, *possession))
    if late_substitutions and player_id in late_substitutions:
        return late_substitutions[player_id]
    if game == "6640422" and possession[0] == "2" and team == "627487":
        # Both school logs record Brown out at 12:07, Ellison replacing
        # Harris-Smith at 3:51, and Brown replacing Petronio at 2:56.
        number = int(possession[1])
        if player_id == "11484028" and 96 <= number <= 123:
            return "11955874" if number <= 120 else "11478524"
        if player_id == "11955878" and 124 <= number <= 133:
            return "11478524"
    if not placeholder_present or possession[0] != "1":
        return player_id
    return STALE_SLOTS.get((game, possession[1]), {}).get((team, player_id), player_id)


def reconcile_points(possessions, shots, final_score, team_names):
    """Verify final scores by shooting team and return each offense's points."""
    if not shots:
        return None
    points = Counter()
    model_points = []
    seen = set()
    for possession, offense, published_points in possessions:
        events = shots.get(possession, ())
        # Own baskets are recorded separately from the offense's shot count.
        total = 0
        offense_points = 0
        for team, scored, event_type in events:
            if scored is None or team not in team_names:
                return None
            points[team] += scored
            if event_type == "Own basket":
                continue
            if event_type != "Missed scoring credit":
                total += scored
            if team == offense:
                offense_points += scored
            elif event_type != "Free Throw":
                return None
        if total != published_points:
            return None
        seen.add(possession)
        model_points.append(offense_points)
    if any(possession not in seen for possession in shots):
        return None
    if tuple(points[team] for team in team_names) != final_score:
        return None
    return model_points


def merge_split_possessions(game, possessions):
    """Count audited continuation fragments once, using the retained lineup."""
    repairs = SPLIT_POSSESSIONS.get(game, ())
    indexes = {row[0]: i for i, row in enumerate(possessions)}
    removed = set()
    for period, first, expected, retained in repairs:
        i = indexes.get((period, str(first)))
        if i is None or i + 1 == len(possessions):
            continue
        a, b = possessions[i:i + 2]
        if b[0] == (period, str(first + 1)) and a[1] == b[1] and (a[3], b[3]) == expected:
            removed.add(i + (1 - retained))
    return [row for i, row in enumerate(possessions) if i not in removed]
