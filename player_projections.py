"""Load and format the verified projections for the Ratings leaderboard."""
from functools import lru_cache
import json
from pathlib import Path

from projection_keys import name_key


@lru_cache(maxsize=1)
def load_projections():
    path = Path(__file__).with_name("www") / "player_projections.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def format_projection(value, unit):
    if value is None or value != value:
        return ""
    if unit == "percent":
        return f"{value:.1%}"
    if unit == "ratio":
        return f"{value:.3f}"
    return f"{100 * value:.2f}"


def projections_for_season(season):
    snapshot = load_projections()
    if snapshot is not None and snapshot["season"] == season:
        return snapshot
    return None


def projection_values(snapshot, name, team):
    player_id = snapshot["names"].get(team, {}).get(name_key(name))
    player = snapshot["players"].get(str(player_id))
    if player is None:
        return [None] * (2 * len(snapshot["stats"]))
    return [value for pair in player["rates"] for value in pair]
