"""Shiny layout for Triton Zone."""

from shiny import ui

from data_engine import CLASSES, POSITIONS
from .scoring import TRITON_SPECIAL_ARCHETYPES, TRITON_ZONE_METRICS


TRITON_ARCHETYPE_FILTERS = {
    "all": "All players",
    "zone": "Triton Zone only",
    "stretch_big": TRITON_SPECIAL_ARCHETYPES["stretch_big"]["label"],
    "shooter": TRITON_SPECIAL_ARCHETYPES["shooter"]["label"],
}
# The board renders one table row per player and the public site runs this in
# Pyodide, so the length is capped -- filters, not an unbounded board, are how
# you find one specific player.
TRITON_TABLE_LIMITS = {
    "25": "Top 25",
    "50": "Top 50",
    "100": "Top 100",
    "250": "Top 250",
    "500": "Top 500",
}
TRITON_DEFAULT_MIN_MPG = 10.0
TRITON_DEFAULT_MIN_GP = 5


def triton_threshold_field(metric):
    return ui.div(
        {"class": "triton-threshold-field"},
        ui.div(
            ui.span(metric["label"], class_="triton-threshold-name"),
            ui.span(metric["long"], class_="triton-threshold-hint"),
            class_="triton-threshold-head",
        ),
        ui.input_numeric(
            f"triton_target_{metric['key']}",
            None,
            value=float(metric["target"]),
            min=float(metric["input_min"]),
            max=float(metric["input_max"]),
            step=float(metric["step"]),
        ),
    )


def triton_weight_field(metric):
    return ui.div(
        {"class": "triton-weight-field"},
        ui.div(
            ui.span(metric["label"], class_="triton-threshold-name"),
            ui.output_text(f"triton_weight_share_{metric['key']}", inline=True),
            class_="triton-threshold-head",
        ),
        ui.input_slider(
            f"triton_weight_{metric['key']}",
            None,
            min=0,
            max=40,
            value=float(metric["weight"]),
            step=1,
        ),
    )


def triton_special_field(criterion):
    return ui.div(
        {"class": "triton-threshold-field"},
        ui.div(
            ui.span(criterion["label"], class_="triton-threshold-name"),
            ui.span(
                "inches" if criterion.get("kind") == "height" else "percent",
                class_="triton-threshold-hint",
            ),
            class_="triton-threshold-head",
        ),
        ui.input_numeric(
            f"triton_target_{criterion['key']}",
            None,
            value=float(criterion["target"]),
            min=float(criterion["input_min"]),
            max=float(criterion["input_max"]),
            step=float(criterion["step"]),
        ),
    )


def make_triton_tab(d1_df):
    conf_choices = {conf: conf for conf in sorted(d1_df["confName"].dropna().unique())}
    team_choices = {team: team for team in sorted(d1_df["team"].dropna().unique())}
    return ui.div(
        {"id": "triton-tab", "class": "tab-panel"},
        ui.div(
            {"class": "triton-shell"},
            ui.div(
                {"class": "triton-header-card"},
                ui.div("Triton Zone", class_="triton-title"),
                ui.div(
                    "Every D-I player scored against the staff's Triton Zone targets and ranked "
                    "by the weighted fit. Hitting a target is worth 70 on that metric, clearing it "
                    "comfortably earns up to 100, so the board separates players who merely qualify "
                    "from players who live in the zone.",
                    class_="triton-lede",
                ),
                ui.div(
                    {"class": "triton-filter-row"},
                    ui.div(
                        {"class": "triton-filter-field"},
                        ui.div("Search player", class_="triton-filter-title"),
                        ui.input_text("triton_q", None, placeholder="Search a player..."),
                    ),
                    ui.div(
                        {"class": "triton-filter-field"},
                        ui.div("Conference", class_="triton-filter-title"),
                        ui.input_selectize(
                            "triton_conf",
                            None,
                            choices=conf_choices,
                            selected=[],
                            multiple=True,
                            options={"placeholder": "  Any conference",
                                     "plugins": ["remove_button"]},
                        ),
                    ),
                    ui.div(
                        {"class": "triton-filter-field"},
                        ui.div("Team", class_="triton-filter-title"),
                        ui.input_selectize(
                            "triton_team",
                            None,
                            choices=team_choices,
                            selected=[],
                            multiple=True,
                            options={"placeholder": "  Any team",
                                     "plugins": ["remove_button"]},
                        ),
                    ),
                    ui.div(
                        {"class": "triton-filter-field"},
                        ui.div("Pos", class_="triton-filter-title"),
                        ui.input_selectize(
                            "triton_pos",
                            None,
                            choices={pos: pos for pos in POSITIONS},
                            selected=[],
                            multiple=True,
                            options={"placeholder": "  Any position",
                                     "plugins": ["remove_button"]},
                        ),
                    ),
                    ui.div(
                        {"class": "triton-filter-field"},
                        ui.div("Class", class_="triton-filter-title"),
                        ui.input_selectize(
                            "triton_cls",
                            None,
                            choices={cls: cls for cls in CLASSES},
                            selected=[],
                            multiple=True,
                            options={"placeholder": "  Any class",
                                     "plugins": ["remove_button"]},
                        ),
                    ),
                ),
                ui.div(
                    {"class": "triton-filter-row triton-filter-row--second"},
                    ui.div(
                        {"class": "triton-filter-field triton-filter-field--wide"},
                        ui.div("Archetype filter", class_="triton-filter-title"),
                        ui.input_radio_buttons(
                            "triton_archetype",
                            None,
                            choices=TRITON_ARCHETYPE_FILTERS,
                            selected="all",
                            inline=True,
                        ),
                        ui.input_checkbox(
                            "triton_require_zone",
                            "Archetype must also clear the full Triton Zone",
                            value=False,
                        ),
                    ),
                    ui.div(
                        {"class": "triton-filter-field triton-filter-field--slider"},
                        ui.div("Minutes per game minimum", class_="triton-filter-title"),
                        ui.input_slider(
                            "triton_min_mpg", None,
                            min=0, max=35, value=TRITON_DEFAULT_MIN_MPG, step=0.5,
                        ),
                    ),
                    ui.div(
                        {"class": "triton-filter-field triton-filter-field--slider"},
                        ui.div("Games played minimum", class_="triton-filter-title"),
                        ui.input_slider(
                            "triton_min_gp", None,
                            min=0, max=35, value=TRITON_DEFAULT_MIN_GP, step=1,
                        ),
                    ),
                    ui.div(
                        {"class": "triton-filter-field triton-filter-field--slider"},
                        ui.div("Zone checks cleared minimum", class_="triton-filter-title"),
                        ui.input_slider(
                            "triton_min_checks", None,
                            min=0, max=len(TRITON_ZONE_METRICS), value=0, step=1,
                        ),
                    ),
                    ui.div(
                        {"class": "triton-filter-field"},
                        ui.div("Board length", class_="triton-filter-title"),
                        ui.input_select(
                            "triton_limit", None,
                            choices=TRITON_TABLE_LIMITS, selected="100",
                        ),
                    ),
                ),
                ui.tags.details(
                    {"class": "triton-more"},
                    ui.tags.summary("Triton Zone thresholds"),
                    ui.div(
                        "The staff's targets. Every one is adjustable — a player clears a metric at "
                        "the target and scores higher the further past it they get.",
                        class_="triton-more-note",
                    ),
                    ui.div(
                        {"class": "triton-threshold-grid"},
                        *[triton_threshold_field(metric) for metric in TRITON_ZONE_METRICS],
                    ),
                    ui.div("Archetype criteria", class_="triton-more-subhead"),
                    *[
                        ui.div(
                            ui.div(
                                ui.span(archetype["label"], class_="triton-more-arch"),
                                ui.span(archetype["note"], class_="triton-threshold-hint"),
                                class_="triton-more-archhead",
                            ),
                            ui.div(
                                {"class": "triton-threshold-grid"},
                                *[triton_special_field(c) for c in archetype["criteria"]],
                            ),
                        )
                        for archetype in TRITON_SPECIAL_ARCHETYPES.values()
                    ],
                    ui.input_action_button(
                        "triton_reset_thresholds", "Reset thresholds", class_="triton-reset-btn"
                    ),
                ),
                ui.tags.details(
                    {"class": "triton-more"},
                    ui.tags.summary("Triton Zone weights"),
                    ui.div(
                        "How much each metric counts toward the score. Weights are normalised, so "
                        "only their sizes relative to each other matter — the percentage beside each "
                        "label is its real share of the score.",
                        class_="triton-more-note",
                    ),
                    ui.div(
                        {"class": "triton-threshold-grid triton-threshold-grid--weights"},
                        *[triton_weight_field(metric) for metric in TRITON_ZONE_METRICS],
                    ),
                    ui.input_action_button(
                        "triton_reset_weights", "Reset weights", class_="triton-reset-btn"
                    ),
                ),
            ),
            ui.div(
                {"class": "triton-results-head"},
                ui.output_text("triton_results_count"),
                ui.div(
                    "Click a row to open the player profile. Green cells clear the target.",
                    class_="triton-results-note",
                ),
            ),
            ui.output_ui("triton_table_ui"),
        ),
    )
