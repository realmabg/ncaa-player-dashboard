"""The daily BPM and RAPM leaderboard in the Shiny dashboard."""
import asyncio
import html
from io import BytesIO
from urllib.request import Request, urlopen

import pandas as pd
from shiny import reactive, render, ui

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
                    ratings_filter(ui.input_select("ratings_team", "Team", choices={"": "Any team"})),
                    ratings_filter(ui.input_numeric("ratings_bpm_min", "Min. BPM minutes",
                                                     DEFAULT_BPM_MINUTES, min=0, step=1)),
                    ratings_filter(ui.input_numeric("ratings_rapm_min", "Min. RAPM possessions",
                                                     DEFAULT_RAPM_POSSESSIONS, min=0, step=1)),
                    ratings_filter(ui.input_select("ratings_limit", "Board length",
                                                   choices=BOARD_LENGTHS, selected="100")),
                ),
            ),
            ui.div(
                {"class": "triton-results-head"},
                ui.output_text("ratings_results_count"),
                ui.a("Open CSV", href=CSV_URL, target="_blank", rel="noopener",
                     class_="triton-results-note ratings-csv-link"),
            ),
            ui.output_ui("ratings_table"),
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
    return frame


def ratings_tab_server(input, session):
    snapshot = reactive.Value(None)
    error = reactive.Value(False)
    sort = reactive.Value(("rapm", False))

    @reactive.effect
    @reactive.event(input.ratings_sort_click)
    def update_sort():
        column = input.ratings_sort_click()
        if column not in dict(PLAYER_COLUMNS):
            return
        current, ascending = sort.get()
        sort.set((column, not ascending if column == current else column in {"player_name", "team"}))

    @reactive.effect
    @reactive.event(input.active_tab)
    async def refresh_ratings():
        if input.active_tab() != "ratings":
            return
        try:
            raw = await asyncio.wait_for(fetch_csv(), timeout=20)
            frame = read_ratings(raw)
            teams = sorted(frame["team"].dropna().unique())
            selected = input.ratings_team()
            ui.update_select("ratings_team", choices={"": "Any team", **{team: team for team in teams}},
                             selected=selected if selected in teams else "", session=session)
            snapshot.set(frame)
            error.set(False)
        except (OSError, ValueError, RuntimeError):
            error.set(True)

    @render.ui
    def ratings_status():
        current = snapshot.get()
        if current is None:
            return ("The ratings CSV is unavailable. Reopen the tab to retry."
                    if error.get() else "Loading the daily ratings…")
        meta = current.iloc[0]
        season = int(meta["season"])
        expected = int(meta["expected_games"])
        return ui.TagList(
            ui.p(f"{season - 1}–{str(season)[-2:]} season · Games through {meta['through_date']}"),
            ui.p(
                f"BPM: {int(meta['bpm_games_included']):,} of {expected:,} games "
                f"through {meta['bpm_through_date']} · "
                f"RAPM: {int(meta['rapm_games_included']):,} of {expected:,} games "
                f"through {meta['rapm_through_date']} "
                f"({int(meta['rapm_excluded_possessions']):,} possessions excluded)"
            ),
            ui.p("Refresh failed. Showing the last loaded snapshot.") if error.get() else None,
        )

    @reactive.calc
    def ratings_rows():
        frame = snapshot.get()
        if frame is None:
            return None, 0

        bpm_min = input.ratings_bpm_min()
        rapm_min = input.ratings_rapm_min()
        bpm_min = DEFAULT_BPM_MINUTES if bpm_min is None else max(0, bpm_min)
        rapm_min = DEFAULT_RAPM_POSSESSIONS if rapm_min is None else max(0, rapm_min)
        frame = frame.loc[
            frame["bpm_minutes"].fillna(0).ge(bpm_min)
            & frame["rapm_possessions"].fillna(0).ge(rapm_min)
        ]
        team = input.ratings_team()
        if team:
            frame = frame.loc[frame["team"].eq(team)]

        search = input.ratings_search().strip()
        if search:
            matches = frame["player_name"].str.contains(search, case=False, regex=False, na=False)
            matches |= frame["team"].str.contains(search, case=False, regex=False, na=False)
            frame = frame.loc[matches]

        column, ascending = sort.get()
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
        return ui.HTML(render_ratings_board(rows, *sort.get()))


def render_ratings_board(rows, sort_column, ascending):
    parts = ['<div class="triton-table-card"><table class="triton-table" aria-label="Player Ratings">'
             '<thead><tr><th scope="col" class="triton-col-rank">#</th>']
    for column, label in PLAYER_COLUMNS:
        marker = ""
        sort_attr = ""
        if column == sort_column:
            direction = "ascending" if ascending else "descending"
            sort_attr = f' aria-sort="{direction}"'
            marker = " ↑" if ascending else " ↓"
        click = f"Shiny.setInputValue('ratings_sort_click','{column}',{{priority:'event'}})"
        parts.append(f'<th scope="col"{sort_attr}><button type="button" onclick="{click}">'
                     f"{label}{marker}</button></th>")
    parts.append("</tr></thead><tbody>")
    for rank, record in enumerate(rows.itertuples(index=False), start=1):
        player = html.escape(str(record.player_name)) if pd.notna(record.player_name) else "—"
        team = html.escape(str(record.team)) if pd.notna(record.team) else "—"
        parts.append(f'<tr><td class="triton-col-rank">{rank}</td>'
                     f'<td><div class="triton-table-player">{player}</div></td><td>{team}</td>')
        for value in (record.rapm, record.bpm):
            score = f"{value:+.2f}" if pd.notna(value) else "—"
            parts.append(f'<td><span class="triton-war-value">{score}</span></td>')
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)
