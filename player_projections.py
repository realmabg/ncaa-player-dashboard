"""Load and format the verified projections for the Ratings leaderboard."""
from functools import lru_cache
import json
from pathlib import Path

from projection_keys import name_key


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
    path = Path(__file__).with_name("www") / "player_projections.json"
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
    if player is None:
        return [None] * len(snapshot["stats"])
    return player[mode]
