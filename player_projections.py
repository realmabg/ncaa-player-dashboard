"""Render the verified 2026–27 projections on D-I player profiles."""
from functools import lru_cache
import json
from pathlib import Path

from shiny import ui


@lru_cache(maxsize=1)
def load_projections():
    path = Path(__file__).with_name("www") / "player_projections.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def format_projection(value, unit):
    if value is None:
        return ""
    if unit == "percent":
        return f"{value:.1%}"
    if unit == "ratio":
        return f"{value:.3f}"
    return f"{100 * value:.2f}"


def player_projections_panel(name, team):
    snapshot = load_projections()
    if snapshot is None:
        return None
    player = snapshot["players"].get(team, {}).get(name)
    rates = player["rates"] if player else [(None, None)] * len(snapshot["stats"])
    heading = f"{snapshot['season']} Projections"
    if player:
        heading += f" · {player['team']}"
    return ui.tags.details(
        ui.tags.summary(heading, class_="col-title"),
        ui.div(
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Stat", scope="col"),
                        ui.tags.th("Preseason",
                                   ui.tags.small("Data through", ui.tags.br(), snapshot["preseason_through"]),
                                   scope="col"),
                        ui.tags.th("Updated rest-of-season",
                                   ui.tags.small("Data through", ui.tags.br(), snapshot["updated_through"]),
                                   scope="col"),
                    ),
                ),
                ui.tags.tbody(*[
                    ui.tags.tr(
                        ui.tags.th(stat["label"], scope="row"),
                        ui.tags.td(format_projection(preseason, stat["unit"])),
                        ui.tags.td(format_projection(updated, stat["unit"])),
                    )
                    for stat, (preseason, updated) in zip(snapshot["stats"], rates, strict=True)
                ]),
                aria_label=f"{snapshot['season']} player projections",
            ),
            class_="player-projections-scroll",
        ),
        class_="player-projections",
    )
