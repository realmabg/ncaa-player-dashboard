"""Shiny layout for the completed-season player archive."""

import math

import pandas as pd
from shiny import ui

from data_engine import POSITIONS


def historical_slider_range(player_index, column: str, step: float):
    if player_index.empty or column not in player_index.columns:
        return (0, 0)
    vals = pd.to_numeric(player_index[column], errors="coerce").dropna()
    if vals.empty:
        return (0, 0)
    lo = math.floor(vals.min() / step) * step
    hi = math.ceil(vals.max() / step) * step
    return (float(lo), float(hi))



def make_historical_beta_tab(player_index, archetypes):
    years = sorted(player_index["year"].dropna().astype(int).unique(), reverse=True) if not player_index.empty else []
    conferences = sorted(filter(None, player_index["conf"].unique())) if not player_index.empty else []
    teams = sorted(filter(None, player_index["team"].unique())) if not player_index.empty else []
    height_min, height_max = historical_slider_range(player_index, "height_inches", 1)
    mpg_min, mpg_max = historical_slider_range(player_index, "mins_per_game", 0.5)
    ppg_min, ppg_max = historical_slider_range(player_index, "pts_per_game", 0.1)
    apg_min, apg_max = historical_slider_range(player_index, "ast_per_game", 0.1)
    rpg_min, rpg_max = historical_slider_range(player_index, "treb_per_game", 0.1)
    bpm_min, bpm_max = historical_slider_range(player_index, "bpm", 0.1)
    return ui.div(
        {"id": "hist-tab", "class": "tab-panel"},
        ui.div(
            {"class": "historical-shell"},
            ui.div(
                {"class": "historical-header-card"},
                ui.div("Historical Players", class_="historical-title"),
                ui.div("Search player", class_="historical-search-label"),
                ui.input_text("hist_q", None, placeholder="Search a past player..."),
                ui.div(
                    {"class": "historical-filter-row"},
                    ui.div(
                        {"class": "historical-filter-field"},
                        ui.div("Season", class_="historical-filter-title"),
                        ui.input_selectize(
                            "hist_season",
                            None,
                            choices={str(year): str(year) for year in years},
                            selected=[],
                            multiple=True,
                            options={
                                "placeholder": "\u00a0\u00a0Any season",
                                "plugins": ["remove_button"],
                            },
                        ),
                    ),
                    ui.div(
                        {"class": "historical-filter-field"},
                        ui.div("Conference", class_="historical-filter-title"),
                        ui.input_selectize(
                            "hist_conf",
                            None,
                            choices={conf: conf for conf in conferences},
                            selected=[],
                            multiple=True,
                            options={
                                "placeholder": "\u00a0\u00a0Any conference",
                                "plugins": ["remove_button"],
                            },
                        ),
                    ),
                    ui.div(
                        {"class": "historical-filter-field"},
                        ui.div("Team", class_="historical-filter-title"),
                        ui.input_selectize(
                            "hist_team",
                            None,
                            choices={team: team for team in teams},
                            selected=[],
                            multiple=True,
                            options={
                                "placeholder": "\u00a0\u00a0Any team",
                                "plugins": ["remove_button"],
                            },
                        ),
                    ),
                    ui.div(
                        {"class": "historical-filter-field"},
                        ui.div("Pos", class_="historical-filter-title"),
                        ui.input_selectize(
                            "hist_pos",
                            None,
                            choices={pos: pos for pos in POSITIONS},
                            selected=[],
                            multiple=True,
                            options={
                                "placeholder": "\u00a0\u00a0Any position",
                                "plugins": ["remove_button"],
                            },
                        ),
                    ),
                    ui.div(
                        {"class": "historical-filter-field"},
                        ui.div("Archetype", class_="historical-filter-title"),
                        ui.input_selectize(
                            "hist_archetype",
                            None,
                            choices={arch: arch for arch in archetypes},
                            selected=[],
                            multiple=True,
                            options={
                                "placeholder": "\u00a0\u00a0Any archetype",
                                "plugins": ["remove_button"],
                            },
                        ),
                    ),
                    ui.div(
                        {"class": "historical-filter-field historical-filter-field--slider"},
                        ui.div("Height range", class_="historical-filter-title"),
                        ui.input_slider(
                            "hist_height",
                            None,
                            min=int(height_min),
                            max=int(height_max),
                            value=[int(height_min), int(height_max)],
                            step=1,
                        ),
                    ),
                    ui.div(
                        {"class": "historical-filter-field historical-filter-field--slider"},
                        ui.div("Minutes minimum", class_="historical-filter-title"),
                        ui.input_slider(
                            "hist_mpg_min",
                            None,
                            min=float(mpg_min),
                            max=float(mpg_max),
                            value=max(5.0, float(mpg_min)),
                            step=0.5,
                        ),
                    ),
                ),
                ui.tags.details(
                    {"class": "historical-more-filters"},
                    ui.tags.summary("Additional filters"),
                    ui.div(
                        {"class": "historical-filter-row historical-filter-row--additional"},
                        ui.div(
                            {"class": "historical-filter-field historical-filter-field--slider"},
                            ui.div("MPG minimum", class_="historical-filter-title"),
                            ui.input_slider(
                                "hist_mpg_extra_min",
                                None,
                                min=float(mpg_min),
                                max=float(mpg_max),
                                value=float(mpg_min),
                                step=0.5,
                            ),
                        ),
                        ui.div(
                            {"class": "historical-filter-field historical-filter-field--slider"},
                            ui.div("APG minimum", class_="historical-filter-title"),
                            ui.input_slider(
                                "hist_apg_min",
                                None,
                                min=float(apg_min),
                                max=float(apg_max),
                                value=float(apg_min),
                                step=0.1,
                            ),
                        ),
                        ui.div(
                            {"class": "historical-filter-field historical-filter-field--slider"},
                            ui.div("PPG minimum", class_="historical-filter-title"),
                            ui.input_slider(
                                "hist_ppg_min",
                                None,
                                min=float(ppg_min),
                                max=float(ppg_max),
                                value=float(ppg_min),
                                step=0.1,
                            ),
                        ),
                        ui.div(
                            {"class": "historical-filter-field historical-filter-field--slider"},
                            ui.div("RPG minimum", class_="historical-filter-title"),
                            ui.input_slider(
                                "hist_rpg_min",
                                None,
                                min=float(rpg_min),
                                max=float(rpg_max),
                                value=float(rpg_min),
                                step=0.1,
                            ),
                        ),
                        ui.div(
                            {"class": "historical-filter-field historical-filter-field--slider"},
                            ui.div("BPM minimum", class_="historical-filter-title"),
                            ui.input_slider(
                                "hist_bpm_min",
                                None,
                                min=float(bpm_min),
                                max=float(bpm_max),
                                value=float(bpm_min),
                                step=0.1,
                            ),
                        ),
                    ),
                ),
            ),
            ui.div(
                {"class": "historical-results-head"},
                ui.output_text("hist_results_count"),
                ui.div("Click a row to open a profile and load current-player comps.", class_="historical-results-note"),
            ),
            ui.output_ui("historical_table_ui"),
            ui.output_ui("historical_current_comps_ui"),
        ),
    )
