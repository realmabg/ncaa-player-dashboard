"""Render the verified 2026–27 projections on the Ratings tab."""
from functools import lru_cache
import json
from pathlib import Path

from shiny import ui

from projection_keys import name_key


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


def player_projections_panel(name, team, season):
    snapshot = load_projections()
    if snapshot is None or snapshot["season"] != season:
        return ui.div("Projections are unavailable for this season.", class_="triton-empty")
    player_id = snapshot["names"].get(team, {}).get(name_key(name))
    player = snapshot["players"].get(str(player_id))
    rates = player["rates"] if player else [(None, None)] * len(snapshot["stats"])
    season_label = f"{season - 1}–{season % 100:02d}"
    forecast_team = player["team"] if player else team
    return ui.tags.details(
        ui.tags.summary(f"{name} · {forecast_team} · {season_label} projections",
                        class_="triton-title"),
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
                aria_label=f"{name} player projections",
            ),
            class_="player-projections-scroll",
        ),
        class_="player-projections triton-table-card",
        open=True,
    )
