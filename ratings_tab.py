"""The daily BPM and RAPM leaderboard in the Shiny dashboard."""
import asyncio
import html
import json
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
from shiny import reactive, render, ui

from player_projections import STAT_HEADERS, format_projection, projection_values, projections_for_season

CSV_URL = (
    "https://raw.githubusercontent.com/Siddhu-S/ncaa-player-dashboard/"
    "ratings-data/player-ratings.csv"
)
PLAYER_COLUMNS = (
    ("player_name", "Player"),
    ("team", "Team"),
    ("rapm", "RAPM"),
    ("bpm", "BPM"),
)
LOWER_IS_BETTER = {"tov", "personal_tov", "foul"}
SAMPLE_COLUMNS = ("bpm_minutes", "rapm_possessions")
BOARD_LENGTHS = {"100": "100", "250": "250", "500": "500", "0": "All"}
COVERAGE_COLUMNS = {
    "season", "through_date", "bpm_through_date", "rapm_through_date", "expected_games",
    "bpm_games_included", "rapm_games_included", "rapm_excluded_possessions",
}
DEFAULT_BPM_MINUTES = 5
DEFAULT_RAPM_POSSESSIONS = 25


def ratings_filter(control):
    return ui.div({"class": "triton-filter-field"}, control)


def ratings_tab_ui():
    return ui.div(
        {"id": "ratings-tab", "class": "tab-panel"},
        ui.div(
            {"class": "triton-shell"},
            ui.div(
                {"class": "triton-header-card"},
                ui.div("Player Ratings", class_="triton-title"),
                ui.div(ui.output_ui("ratings_status"), class_="triton-lede"),
                ui.div(
                    {"class": "triton-filter-row"},
                    ratings_filter(ui.input_text("ratings_search", "Search player",
                                                 placeholder="Search a player...")),
                    ratings_filter(ui.input_select("ratings_conference", "Conference",
                                                   choices={"": "Any conference"})),
                    ratings_filter(ui.input_select("ratings_team", "Team", choices={"": "Any team"})),
                    ratings_filter(ui.input_select("ratings_limit", "Board length",
                                                   choices=BOARD_LENGTHS, selected="100")),
                ),
                ui.div(
                    {"class": "triton-filter-row triton-filter-row--second"},
                    ratings_filter(ui.input_numeric("ratings_bpm_min", "Min. minutes played",
                                                     DEFAULT_BPM_MINUTES, min=0, step="any")),
                    ratings_filter(ui.input_numeric("ratings_bpm_max", "Max. minutes played",
                                                     None, min=0, step="any")),
                    ratings_filter(ui.input_numeric("ratings_rapm_min", "Min. RAPM possessions",
                                                     DEFAULT_RAPM_POSSESSIONS, min=0, step=1)),
                    ui.div("Minutes are season totals from BPM box scores. Leave the maximum blank for no cap.",
                           class_="triton-results-note"),
                ),
            ),
            ui.div(
                ui.input_radio_buttons("ratings_projection_period", "Projection period",
                                       {"updated": "Rest of season", "preseason": "Preseason"},
                                       selected="updated", inline=True),
                class_="ratings-stat-controls",
            ),
            ui.div(
                {"class": "triton-results-head"},
                ui.output_text("ratings_results_count"),
                ui.a("Open CSV", href=CSV_URL, target="_blank", rel="noopener",
                     class_="triton-results-note ratings-csv-link"),
            ),
            ui.div(ui.output_ui("ratings_table"), class_="triton-table-card"),
        ),
    )


async def fetch_csv():
    try:
        from pyodide.http import pyfetch
    except ModuleNotFoundError:
        def fetch():
            with urlopen(Request(CSV_URL, headers={"Cache-Control": "no-cache"}), timeout=15) as response:
                return response.read()

        return await asyncio.to_thread(fetch)

    response = await pyfetch(CSV_URL, cache="no-cache")
    if not response.ok:
        raise OSError(f"Ratings CSV returned HTTP {response.status}")
    return await response.bytes()


def read_ratings(raw):
    frame = pd.read_csv(BytesIO(raw), keep_default_na=False, na_values=[""])
    if frame.empty or not ({key for key, _ in PLAYER_COLUMNS} | set(SAMPLE_COLUMNS) | COVERAGE_COLUMNS).issubset(frame.columns):
        raise ValueError("Ratings CSV is empty or has missing columns")
    for column in ("bpm", "rapm", "bpm_minutes", "rapm_possessions"):
        frame[column] = pd.to_numeric(frame[column])
    # The 2026–27 Torvik conference list is keyed by the NCAA team names used in the CSV.
    conference_path = Path(__file__).with_name("www") / "ratings_conferences.json"
    by_season = json.loads(conference_path.read_text(encoding="utf-8"))
    conferences = by_season.get(str(int(frame.iloc[0]["season"])), {})
    frame["conference"] = frame["team"].map(conferences)
    return frame


def ratings_tab_server(input, session):
    snapshot = reactive.Value(None)
    sort = reactive.Value(("rapm", False))

    @reactive.extended_task
    async def download_ratings():
        return read_ratings(await asyncio.wait_for(fetch_csv(), timeout=20))

    @reactive.effect
    def preload_ratings():
        download_ratings()

    @reactive.effect
    @reactive.event(input.ratings_sort_click)
    def update_sort():
        column = input.ratings_sort_click()
        frame = stats_board()
        if column not in dict(PLAYER_COLUMNS) and (frame is None or column not in skill_columns(frame)):
            return
        current, ascending = sort.get()
        sort.set((column, not ascending if column == current else column in {"player_name", "team"}))

    @reactive.effect
    @reactive.event(input.active_tab)
    def retry_ratings():
        if input.active_tab() == "ratings" and download_ratings.status() == "error":
            download_ratings()

    @reactive.effect
    def apply_ratings():
        if download_ratings.status() != "success":
            return
        frame = download_ratings.result()
        teams = sorted(frame["team"].dropna().unique())
        conferences = sorted(frame["conference"].dropna().unique())
        with reactive.isolate():
            selected = input.ratings_team()
        ui.update_select("ratings_team", choices={"": "Any team", **{team: team for team in teams}},
                         selected=selected if selected in teams else "", session=session)
        ui.update_select("ratings_conference", choices={"": "Any conference", **{name: name for name in conferences}},
                         selected="", session=session)
        snapshot.set(frame)

    @render.ui
    def ratings_status():
        current = snapshot.get()
        if current is None:
            return ("The ratings CSV is unavailable. Reopen the tab to retry."
                    if download_ratings.status() == "error" else "Loading the daily ratings…")
        meta = current.iloc[0]
        season = int(meta["season"])
        expected = int(meta["expected_games"])
        projections = projections_for_season(season)
        period = projection_period()
        labels = {"updated": "Rest-of-season projections", "preseason": "Preseason projections"}
        return ui.TagList(
            ui.p(f"{season - 1}–{str(season)[-2:]} season · Games through {meta['through_date']}"),
            ui.p(
                f"BPM: {int(meta['bpm_games_included']):,} of {expected:,} games "
                f"through {meta['bpm_through_date']} · "
                f"RAPM: {int(meta['rapm_games_included']):,} of {expected:,} games "
                f"through {meta['rapm_through_date']} "
                f"({int(meta['rapm_excluded_possessions']):,} possessions excluded)"
            ),
            ui.p(
                f"Actual stats through {projections['actual_through']} · "
                f"{labels[period]} through {projections[f'{period}_through']}"
            ) if projections else None,
        )

    @reactive.calc
    def projection_period():
        return input.ratings_projection_period() or "updated"

    @reactive.calc
    def stats_board():
        frame = snapshot.get()
        return with_stat_percentiles(frame, projection_period()) if frame is not None else None

    @reactive.calc
    def ratings_rows():
        frame = stats_board()
        if frame is None:
            return None, 0

        bpm_min = input.ratings_bpm_min()
        bpm_max = input.ratings_bpm_max()
        rapm_min = input.ratings_rapm_min()
        bpm_min = DEFAULT_BPM_MINUTES if bpm_min is None else max(0, bpm_min)
        rapm_min = DEFAULT_RAPM_POSSESSIONS if rapm_min is None else max(0, rapm_min)
        minutes = frame["bpm_minutes"]
        eligible = minutes.fillna(0).ge(bpm_min) & frame["rapm_possessions"].fillna(0).ge(rapm_min)
        if bpm_max is not None:
            eligible &= minutes.le(max(0, bpm_max))
        conference = input.ratings_conference()
        if conference:
            eligible &= frame["conference"].eq(conference)
        frame = frame.loc[eligible]
        team = input.ratings_team()
        if team:
            frame = frame.loc[frame["team"].eq(team)]

        search = input.ratings_search().strip()
        if search:
            matches = frame["player_name"].str.contains(search, case=False, regex=False, na=False)
            frame = frame.loc[matches]

        column, ascending = sort.get()
        if column not in frame:
            column, ascending = "rapm", False
        tie_breakers = [key for key in ("player_name", "team") if key != column]
        ranked = frame.sort_values([column, *tie_breakers], ascending=[ascending] + [True] * len(tie_breakers))
        limit = int(input.ratings_limit() or "100")
        return (ranked.head(limit) if limit else ranked), len(ranked)

    @render.text
    def ratings_results_count():
        rows, total = ratings_rows()
        return "" if rows is None else f"{len(rows):,} of {total:,} matching players"

    @render.ui
    def ratings_table():
        rows, _ = ratings_rows()
        if rows is None:
            return None
        if rows.empty:
            return ui.div("No players match those filters.", class_="triton-empty")
        column, ascending = sort.get()
        if column not in rows:
            column, ascending = "rapm", False
        return ui.HTML(render_ratings_board(rows, column, ascending))


def skill_columns(frame):
    return [column for column in frame.columns if column.startswith("skill_")]


def with_stat_percentiles(frame, period):
    projections = projections_for_season(int(frame.iloc[0]["season"]))
    directions = {"bpm": True, "rapm": True}
    if projections:
        stats = projections["stats"]
        keys = [f"skill_{i}" for i in range(len(stats))]
        names_and_teams = list(frame[["player_name", "team"]].itertuples(index=False, name=None))
        stat_columns = []
        for mode, columns in (("actual", keys), (period, [f"proj_{key}" for key in keys])):
            values = [
                projection_values(projections, name, team, mode) if pd.notna(name) and pd.notna(team)
                else [None] * len(keys)
                for name, team in names_and_teams
            ]
            stat_columns.append(pd.DataFrame(values, columns=columns, index=frame.index, dtype=float))
        frame = pd.concat([frame, *stat_columns], axis=1)
        directions.update({key: stat["key"] not in LOWER_IS_BETTER
                           for key, stat in zip(keys, stats, strict=True)})
    percentiles = {}
    for column, higher_is_better in directions.items():
        values = frame[column]
        ranks = values.rank(ascending=higher_is_better)
        size = values.count()
        percentiles[f"pct_{column}"] = (ranks - 1) * 100 / (size - 1) if size > 1 else ranks * 0 + 50
    return frame.assign(**percentiles)


def stat_cell(value, percentile, *, projection=None):
    if not value and not projection:
        return '<td class="ratings-stat-cell"></td>'
    number = f'<span class="ratings-stat-value">{value}</span>'
    rank = ""
    if pd.notna(percentile):
        rounded = round(percentile)
        tone = "high" if rounded >= 75 else "low" if rounded < 25 else "mid"
        suffix = "th" if 11 <= rounded % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(rounded % 10, "th")
        ordinal = f"{rounded}{suffix}"
        label = f"{rounded}%" if projection is None else ordinal
        rank = f'<span class="ratings-percentile {tone}" title="{ordinal} percentile">{label}</span>'
    if projection is None:
        return f'<td class="ratings-stat-cell">{number}{rank}</td>'
    forecast = (
        '<span class="ratings-projection"><span class="ratings-projection-label">Proj.</span>'
        f'{projection}</span>' if projection else ""
    )
    return (f'<td class="ratings-stat-cell ratings-skill-cell">{number}'
            f'<div class="ratings-stat-details">{forecast}{rank}</div></td>')


def sort_header(column, label, sort_column, ascending, *, definition=None):
    sort_attr = marker = ""
    if column == sort_column:
        direction = "ascending" if ascending else "descending"
        sort_attr = f' aria-sort="{direction}"'
        marker = " ↑" if ascending else " ↓"
    cell_class = ' class="ratings-player-column"' if column == "player_name" else ""
    click = f"Shiny.setInputValue('ratings_sort_click','{column}',{{priority:'event'}})"
    title = f' title="{html.escape(definition, quote=True)}"' if definition else ""
    return (f'<th scope="col"{cell_class}{sort_attr}{title}>'
            f'<button type="button" onclick="{click}">'
            f'{label}{marker}</button></th>')


def render_ratings_board(rows, sort_column, ascending):
    projections = projections_for_season(int(rows.iloc[0]["season"]))
    stats = projections["stats"] if projections else []
    keys = skill_columns(rows)
    parts = ['<table class="triton-table" aria-label="Player Ratings">'
             '<thead><tr><th scope="col" class="triton-col-rank">#</th>']
    for column, label in PLAYER_COLUMNS:
        parts.append(sort_header(column, label, sort_column, ascending))
    for key, stat in zip(keys, stats, strict=True):
        label, definition = STAT_HEADERS[stat["key"]]
        parts.append(sort_header(key, label, sort_column, ascending, definition=definition))
    parts.append("</tr></thead><tbody>")
    for rank, record in enumerate(rows.itertuples(index=False), start=1):
        player = html.escape(str(record.player_name)) if pd.notna(record.player_name) else "—"
        team = html.escape(str(record.team)) if pd.notna(record.team) else "—"
        parts.append(f'<tr><td class="triton-col-rank">{rank}</td>'
                     f'<td class="ratings-player-column"><div class="triton-table-player">{player}</div></td>'
                     f'<td class="ratings-team-column">{team}</td>')
        for column in ("rapm", "bpm"):
            value = getattr(record, column)
            parts.append(stat_cell(f"{value:+.2f}" if pd.notna(value) else "",
                                   getattr(record, f"pct_{column}")))
        for key, stat in zip(keys, stats, strict=True):
            value = format_projection(getattr(record, key), stat)
            projection = format_projection(getattr(record, f"proj_{key}"), stat)
            parts.append(stat_cell(value, getattr(record, f"pct_{key}"), projection=projection))
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)
