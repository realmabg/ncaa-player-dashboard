"""Load and format the verified projections for the Ratings leaderboard."""
from functools import lru_cache
import json
from pathlib import Path

from .projection_keys import name_key


# Definitions follow the model's exposures. Display units are independent of
# the raw fractional rates stored in the snapshot.
STAT_HEADERS = {
    "three": ("3P%", "Three-point makes ÷ three-point attempts"),
    "two": ("2P%", "Two-point makes ÷ two-point attempts"),
    "ft": ("FT%", "Free throws made ÷ free throws attempted"),
    "ast": ("AST%", "Assists ÷ estimated teammate field goals made while on court"),
    "orb": ("ORB%", "Offensive rebounds ÷ estimated available offensive rebounds while on court"),
    "drb": ("DRB%", "Defensive rebounds ÷ estimated available defensive rebounds while on court"),
    "tov": ("TO/100", "Turnovers per 100 estimated team possessions while on court"),
    "stl": ("STL%", "Steals ÷ estimated opponent possessions while on court"),
    "blk": ("BLK%", "Blocks ÷ estimated opponent two-point attempts while on court"),
    "foul": ("PF/100", "Personal fouls per 100 estimated team possessions while on court"),
    "personal_tov": ("TO%", "Turnovers ÷ estimated personal possessions (usage × on-court team possessions)"),
    "fga": ("FGA/100", "Field-goal attempts per 100 estimated team possessions while on court"),
    "fta": ("FTA/100", "Free-throw attempts per 100 estimated team possessions while on court"),
    "share": ("3PAr", "Three-point attempts ÷ all field-goal attempts, shown as a percentage"),
    "usage": ("USG%", "Estimated share of team possessions used while on court"),
    "three_freq": ("3PA/100", "Three-point attempts per 100 estimated team possessions while on court"),
    "two_freq": ("2PA/100", "Two-point attempts per 100 estimated team possessions while on court"),
    "ftr": ("FTR", "Free-throw attempts ÷ field-goal attempts, shown as a ratio"),
}
PERCENT_DISPLAY = {"stl", "blk"}


@lru_cache(maxsize=1)
def load_projections():
    path = Path(__file__).with_name("player_projections.json")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def format_projection(value, stat):
    if value is None or value != value:
        return ""
    if stat["unit"] == "percent" or stat["key"] in PERCENT_DISPLAY:
        return f"{value:.1%}"
    if stat["unit"] == "ratio":
        return f"{value:.3f}"
    return f"{100 * value:.2f}"


def projections_for_season(season):
    snapshot = load_projections()
    if snapshot is not None and snapshot["season"] == season:
        return snapshot
    return None


def projection_values(snapshot, name, team, mode):
    player_id = snapshot["names"].get(team, {}).get(name_key(name))
    player = snapshot["players"].get(str(player_id))
    if player is None or mode not in player:
        return [None] * len(snapshot["stats"])
    return player[mode]


def lineup_forecast_payload(season, team):
    """Package the Ratings forecast for one team's current roster."""
    snapshot = projections_for_season(season)
    if snapshot is None:
        return None
    wcc_path = Path(__file__).with_name("ucsd_wcc_forecast.json")
    wcc = json.loads(wcc_path.read_text(encoding="utf-8")) if team == "UC San Diego" and wcc_path.is_file() else {}
    same_cutoff = wcc.get("season") == season and wcc.get("through") == snapshot["updated_through"]
    stats = snapshot["stats"]
    players = {}
    wcc_players = {}
    for key, player_id in snapshot["names"].get(team, {}).items():
        player = snapshot["players"].get(str(player_id))
        if player is None:
            continue
        values = player["updated"]
        if all(value is None for value in values):
            continue
        players[key] = dict(zip((stat["key"] for stat in stats), values, strict=True))
        wcc_values = wcc["players"].get(str(player_id)) if same_cutoff else None
        if wcc_values and any(value is not None for value in wcc_values.values()):
            wcc_players[key] = wcc_values
    return {
        "through": snapshot["updated_through"],
        "stats": [
            {"key": stat["key"], "label": STAT_HEADERS[stat["key"]][0],
             "unit": "percent" if stat["key"] in PERCENT_DISPLAY else stat["unit"]}
            for stat in stats
        ],
        "players": players,
        "wcc": wcc_players,
    }
