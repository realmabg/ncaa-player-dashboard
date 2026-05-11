from shiny import App, ui, reactive, render
from shinywidgets import output_widget, render_widget
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from pathlib import Path
import html
import re

from data_engine import (
    load_data, load_d1_data,
    POS_COLOR, POS_LABEL, POSITIONS, CLASSES, height_str,
)

HERE = Path(__file__).parent

D2 = load_data(str(HERE / "d2_data_cleaned.csv"),            id_prefix="d2p")
D1 = load_d1_data(str(HERE / "mbb_with_pca.csv"), id_prefix="d1p")
D3 = load_data(str(HERE / "d3_data_cleaned.csv"),          id_prefix="d3p")

d2_df         = D2["df"];  d2_conferences = D2["conferences"]
d2_league_avg = D2["league_avg"];  d2_similar_to = D2["similar_to"]
D2_TOTAL      = len(d2_df)

d1_df         = D1["df"];  d1_conferences = D1["conferences"]
d1_league_avg = D1["league_avg"];  d1_similar_to = D1["similar_to"]
D1_TOTAL      = len(d1_df)

d3_df         = D3["df"];  d3_conferences = D3["conferences"]
d3_league_avg = D3["league_avg"];  d3_similar_to = D3["similar_to"]
D3_TOTAL      = len(d3_df)

ARCHETYPE_LABELS = {
    "score_pg_combo": "PG / Combo Guard",
    "score_wing_2_4": "2-4 Interchangeable Wing",
    "score_stretch_big": "5 / Stretch 4 / Big Wing",
}

ARCHETYPE_COLOR = {
    "PG / Combo Guard": "#4a9eed",
    "2-4 Interchangeable Wing": "#7cc47a",
    "5 / Stretch 4 / Big Wing": "#e8a44a",
}

ARCHETYPE_ORDER = list(ARCHETYPE_COLOR)
ARCHETYPE_PCA_FEATURES = [
    "pct_assist_creation",
    "pct_three_pct",
    "pct_three_rate",
    "pct_ast_tov",
    "pct_efg",
    "pct_dreb_pos_adj",
    "pct_size",
]


def add_archetype_columns(dfs):
    frames = []
    for div, df in dfs:
        tmp = df.copy()
        tmp["_arch_division"] = div
        frames.append(tmp)
    all_df = pd.concat(frames, ignore_index=True)

    def pct(group_cols, col):
        return all_df.groupby(group_cols)[col].rank(pct=True, method="average") * 100

    all_df["pct_assist_creation"] = pct("_arch_division", "assist_creation")
    all_df["pct_three_pct"] = pct("_arch_division", "tp")
    all_df["pct_three_rate"] = pct("_arch_division", "three_share")
    all_df["pct_ast_tov"] = pct("_arch_division", "ast_tov")
    all_df["pct_efg"] = pct("_arch_division", "efg")
    all_df["pct_dreb_pos_adj"] = pct(["_arch_division", "pos"], "dreb_arch")
    all_df["pct_size"] = pct("_arch_division", "heightIn")

    all_df["meets_pg_preferred"] = (
        (all_df["pct_assist_creation"] >= 70)
        & (all_df["tp"] >= 0.330)
        & (all_df["three_share"] >= 0.300)
        & (all_df["ast_tov"] > 1.0)
    )
    all_df["meets_wing_preferred"] = (
        (all_df["pct_dreb_pos_adj"] >= 60)
        & (all_df["tp"] >= 0.330)
        & (all_df["three_share"] >= 0.300)
        & (all_df["ast_tov"] > 1.0)
    )
    all_df["meets_big_preferred"] = (
        (all_df["heightIn"] >= 79)
        & (all_df["pct_dreb_pos_adj"] >= 60)
        & (all_df["tp"] >= 0.300)
        & (all_df["three_share"] >= 0.250)
        & (all_df["ast_tov"] > 1.0)
    )

    all_df["score_pg_combo"] = (
        0.35 * all_df["pct_assist_creation"]
        + 0.20 * all_df["pct_three_pct"]
        + 0.15 * all_df["pct_three_rate"]
        + 0.20 * all_df["pct_ast_tov"]
        + 0.10 * all_df["pct_efg"]
        + np.where(all_df["meets_pg_preferred"], 8, 0)
    ).clip(0, 100)
    all_df["score_wing_2_4"] = (
        0.30 * all_df["pct_dreb_pos_adj"]
        + 0.25 * all_df["pct_three_pct"]
        + 0.20 * all_df["pct_three_rate"]
        + 0.15 * all_df["pct_ast_tov"]
        + 0.10 * all_df["pct_size"]
        + np.where(all_df["meets_wing_preferred"], 8, 0)
    ).clip(0, 100)
    all_df["score_stretch_big"] = (
        0.30 * all_df["pct_dreb_pos_adj"]
        + 0.25 * all_df["pct_size"]
        + 0.20 * all_df["pct_three_pct"]
        + 0.15 * all_df["pct_three_rate"]
        + 0.10 * all_df["pct_ast_tov"]
        + np.where(all_df["meets_big_preferred"], 8, 0)
    ).clip(0, 100)

    score_cols = list(ARCHETYPE_LABELS)
    all_df["primary_score_col"] = all_df[score_cols].idxmax(axis=1)
    all_df["primary_archetype"] = all_df["primary_score_col"].map(ARCHETYPE_LABELS)
    all_df["primary_score"] = all_df[score_cols].max(axis=1)

    X_raw = all_df[ARCHETYPE_PCA_FEATURES].fillna(
        all_df[ARCHETYPE_PCA_FEATURES].median()
    ).to_numpy(dtype=float)
    X_std = np.where(X_raw.std(axis=0) == 0, 1, X_raw.std(axis=0))
    X = (X_raw - X_raw.mean(axis=0)) / X_std
    _u, _s, vt = np.linalg.svd(X, full_matrices=False)
    coords = X @ vt[:4].T
    for i in range(4):
        all_df[f"arch_pca_PC{i+1}"] = coords[:, i]

    arch_cols = [
        "pct_assist_creation", "pct_three_pct", "pct_three_rate",
        "pct_ast_tov", "pct_efg", "pct_dreb_pos_adj", "pct_size",
        "meets_pg_preferred", "meets_wing_preferred", "meets_big_preferred",
        "score_pg_combo", "score_wing_2_4", "score_stretch_big",
        "primary_score_col", "primary_archetype", "primary_score",
        "arch_pca_PC1", "arch_pca_PC2", "arch_pca_PC3", "arch_pca_PC4",
    ]
    by_id = all_df.set_index("id")[arch_cols]
    for _div, df in dfs:
        for col in arch_cols:
            df[col] = df["id"].map(by_id[col])


add_archetype_columns([
    ("D-I", d1_df),
    ("D-II", d2_df),
    ("D-III", d3_df),
])


# ─────────────────────────────────────────────────────────────────────────
# SHARED UI HELPERS
# ─────────────────────────────────────────────────────────────────────────

def stat_box(lbl, val, avg):
    delta = float(val) - float(avg)
    sign  = "+" if delta >= 0 else ""
    cls   = "up" if delta > 0.001 else ("down" if delta < -0.001 else "")
    return ui.div({"class": "stat-cell"},
                  ui.div(str(val), class_="num"),
                  ui.div(lbl,      class_="lbl"),
                  ui.div(f"{sign}{delta:.1f} vs avg", class_=f"delta {cls}"))

def bar_row(lbl, pv, av, mx, fmt=None):
    fmt = fmt or (lambda v: f"{v:.2f}")
    wp  = min(100.0, (pv / mx) * 100) if mx else 0.0
    wa  = min(100.0, (av / mx) * 100) if mx else 0.0
    return ui.div({"class": "cmp-row"},
                  ui.div(lbl, class_="lbl"),
                  ui.div({"class": "cmp-bar"},
                         ui.div({"class": "player-mark", "style": f"left:0;width:{wp:.1f}%"}),
                         ui.div({"class": "avg-mark",    "style": f"left:{wa:.1f}%"})),
                  ui.div(fmt(pv), class_="val"))

def bio_item(label, value, mono=False):
    return ui.div({"class": "bio-item"},
                  ui.div(label, class_="k"),
                  ui.div(value, class_="v mono" if mono else "v"))

def inline_markdown(text):
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text

def simple_markdown_to_html(markdown_text):
    html_parts = []
    list_open = None

    def close_list():
        nonlocal list_open
        if list_open:
            html_parts.append(f"</{list_open}>")
            list_open = None

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            close_list()
            continue

        if stripped.startswith("#"):
            close_list()
            level = min(len(stripped) - len(stripped.lstrip("#")), 3)
            text = stripped[level:].strip()
            html_parts.append(f"<h{level}>{inline_markdown(text)}</h{level}>")
            continue

        if stripped.startswith(">"):
            close_list()
            html_parts.append(f"<blockquote>{inline_markdown(stripped[1:].strip())}</blockquote>")
            continue

        if stripped.startswith("- "):
            if list_open != "ul":
                close_list()
                html_parts.append("<ul>")
                list_open = "ul"
            html_parts.append(f"<li>{inline_markdown(stripped[2:].strip())}</li>")
            continue

        if re.match(r"^\d+\.\s+", stripped):
            if list_open != "ol":
                close_list()
                html_parts.append("<ol>")
                list_open = "ol"
            text = re.sub(r"^\d+\.\s+", "", stripped)
            html_parts.append(f"<li>{inline_markdown(text)}</li>")
            continue

        close_list()
        html_parts.append(f"<p>{inline_markdown(stripped)}</p>")

    close_list()
    return "\n".join(html_parts)

def make_explainer_page():
    md_path = HERE / "archetype_process_explainer.md"
    try:
        content = md_path.read_text(encoding="utf-8")
    except OSError:
        content = "# Archetype Beta Process Explainer\n\nThe explainer file could not be loaded."
    return ui.div(
        {"class": "doc-shell"},
        ui.div({"class": "doc-inner"},
               ui.HTML(simple_markdown_to_html(content))))


def make_detail_modal(player_id, df, league_avg, similar_to_fn, division_label, watchlist):
    row  = df[df["id"] == player_id].iloc[0]
    sims = similar_to_fn(player_id, n_sim=5)
    pc   = POS_COLOR.get(row["pos"], "#888")

    if division_label == "D-I":
        sim_input = "d1_select_similar"
    elif division_label == "D-III":
        sim_input = "d3_select_similar"
    else:
        sim_input = "d2_select_similar"

    ppg_max  = 30 if division_label == "D-I" else 32
    starred  = player_id in watchlist
    star_icon  = "\u2605" if starred else "\u2606"
    star_label = "Remove from watchlist" if starred else "Add to watchlist"
    star_style = "color:var(--accent);" if starred else "color:var(--ink-3);"

    statline = [
        stat_box("MIN", f"{row['mpg']:.1f}", league_avg["mpg"]),
        stat_box("PTS", f"{row['ppg']:.1f}", league_avg["ppg"]),
        stat_box("REB", f"{row['rpg']:.1f}", league_avg["rpg"]),
        stat_box("AST", f"{row['apg']:.1f}", league_avg["apg"]),
        stat_box("STL", f"{row['spg']:.2f}", league_avg["spg"]),
        stat_box("BLK", f"{row['bpg']:.2f}", league_avg["bpg"]),
        stat_box("FG%", f"{row['fg']*100:.1f}", league_avg["fg"] * 100),
        stat_box("3P%", f"{row['tp']*100:.1f}", league_avg["tp"] * 100),
    ]
    bar_defs = [
        ("PPG", row["ppg"], league_avg["ppg"], ppg_max, None),
        ("RPG", row["rpg"], league_avg["rpg"], 14,      None),
        ("APG", row["apg"], league_avg["apg"], 12,      None),
        ("SPG", row["spg"], league_avg["spg"], 4,       None),
        ("BPG", row["bpg"], league_avg["bpg"], 4,       None),
        ("3P%", row["tp"],  league_avg["tp"],  0.55, lambda v: f"{v*100:.1f}%"),
        ("TS%", row["ts"],  league_avg["ts"],  0.75, lambda v: f"{v*100:.1f}%"),
    ]
    bars = [bar_row(l, pv, av, mx, fmt) for l, pv, av, mx, fmt in bar_defs]

    sim_rows = []
    for i, s in enumerate(sims):
        sc = POS_COLOR.get(s["pos"], "#888")
        sim_rows.append(
            ui.div(
                {"class": "sim-row",
                 "onclick": f"Shiny.setInputValue('{sim_input}','{s['id']}',{{priority:'event'}})"},
                ui.div(f"{i+1:02d}", class_="sim-rank"),
                ui.div(
                    ui.div(s["name"], class_="nm"),
                    ui.div(ui.span(s["pos"], class_="pos-badge",
                                   style=f"color:{sc};border-color:{sc}"),
                           ui.span(s["team"]),
                           ui.span(f"· {s['cls']}", style="color:var(--ink-3)"),
                           class_="meta"),
                    class_="sim-main"),
                ui.div(f"{s['similarity']*100:.0f}",
                       ui.span("%", style="font-size:11px;color:var(--ink-3)"),
                       ui.span("match", class_="sim-lbl"),
                       class_="sim-pct")))

    body = ui.div(
        {"id": "detail-body"},
        ui.div({"class": "detail-col"},
               ui.div(
                   {"class": "player-name-row"},
                   ui.div(row["name"], class_="player-name"),
                   ui.tags.button(
                       {"class": "star-btn",
                        "title": star_label,
                        "style": star_style,
                        "onclick": f"Shiny.setInputValue('toggle_watchlist','{player_id}',{{priority:'event'}})"},
                       star_icon)),
               ui.div(ui.span({"class": "team-dot", "style": f"background:{pc}"}),
                      f"{row['team']} · {row['confName']}", class_="player-team"),
               ui.div({"class": "bio-grid"},
                      bio_item("Division", division_label),
                      bio_item("Position", row["pos"]),
                      bio_item("Class",    row["cls"]),
                      bio_item("Height",   height_str(int(row["heightIn"])), mono=True),
                      bio_item("Games",    str(int(row["gp"])), mono=True),
                      bio_item("Min/G",    f"{row['mpg']:.1f}", mono=True))),
        ui.div({"class": "detail-col"},
               ui.div("Season Statline ", ui.span("2025–26", class_="sub"),
                      class_="col-title"),
               ui.div({"class": "statline"}, *statline),
               ui.div("vs. League Average ",
                      ui.span(f"unweighted mean, all {division_label} players", class_="sub"),
                      class_="col-title"),
               *bars,
               ui.div(ui.tags.b("Bar", style="color:var(--ink-2)"),
                      " = player value.  ",
                      ui.tags.b("Tick", style="color:var(--ink-2)"),
                      " = league mean.", class_="bar-note")),
        ui.div({"class": "detail-col"},
               ui.div("Most Similar Players ",
                      ui.span("Euclidean dist. over PC1–PC4 (z-scored)", class_="sub"),
                      class_="col-title"),
               *sim_rows))

    return ui.modal(body,
                    title=ui.HTML(f"Player Profile <b>· {row['name']}</b> "
                                  f'<span class="div-badge">{division_label}</span>'),
                    easy_close=True, size="xl", footer=None)


# ─────────────────────────────────────────────────────────────────────────
# SCATTER HELPERS
# ─────────────────────────────────────────────────────────────────────────

HOVER_TPL = (
    "<b>%{customdata[0]}</b><br>"
    "%{customdata[1]} · %{customdata[2]} · %{customdata[3]}<br>"
    "%{customdata[4]:.1f} PPG · %{customdata[5]:.1f} RPG · %{customdata[6]:.1f} APG"
    "<extra></extra>"
)

def cdata(d):
    return list(zip(d["name"], d["pos"], d["team"], d["cls"],
                    d["ppg"],  d["rpg"], d["apg"],  d["id"]))

ARCH_HOVER_TPL = (
    "<b>%{customdata[0]}</b><br>"
    "%{customdata[1]} · %{customdata[2]} · %{customdata[3]}<br>"
    "%{customdata[4]} · %{customdata[5]:.0f} fit<br>"
    "%{customdata[6]:.1%} 3P · %{customdata[7]:.1%} 3P rate · %{customdata[8]:.2f} A/TO<br>"
    "%{customdata[9]:.0f} ast pctile · %{customdata[10]:.0f} dreb pctile"
    "<extra></extra>"
)

def arch_cdata(d):
    return list(zip(
        d["name"], d["pos"], d["team"], d["cls"],
        d["primary_archetype"], d["primary_score"],
        d["tp"], d["three_share"], d["ast_tov"],
        d["pct_assist_creation"], d["pct_dreb_pos_adj"], d["id"],
    ))

def build_traces(plot_df, selected_id, dimmed_pos, dot_size=9.5, dot_opacity=0.78):
    traces = []
    for pos in POSITIONS:
        sub  = plot_df[plot_df["pos"] == pos]
        if sub.empty: continue
        alpha = 0.06 if pos in dimmed_pos else dot_opacity
        rest  = sub[sub["id"] != selected_id] if selected_id else sub
        sel   = sub[sub["id"] == selected_id] if selected_id else sub.iloc[0:0]
        if not rest.empty:
            traces.append(go.Scatter(
                x=rest["PC1"], y=rest["PC2"], mode="markers",
                marker=dict(size=dot_size, color=POS_COLOR[pos],
                            opacity=alpha, line=dict(width=0)),
                customdata=cdata(rest), hovertemplate=HOVER_TPL,
                name=POS_LABEL[pos], showlegend=False))
        if not sel.empty:
            r = sel.iloc[0]
            traces.append(go.Scatter(
                x=[r["PC1"]], y=[r["PC2"]], mode="markers",
                marker=dict(size=dot_size+16, color="rgba(0,0,0,0)",
                            line=dict(color="#c8a84b", width=1.5)),
                hoverinfo="skip", showlegend=False))
            traces.append(go.Scatter(
                x=[r["PC1"]], y=[r["PC2"]], mode="markers",
                marker=dict(size=dot_size+4, color=POS_COLOR[pos],
                            opacity=1.0, line=dict(color="#0f1623", width=1.8)),
                customdata=[cdata(sel)[0]], hovertemplate=HOVER_TPL,
                showlegend=False))
    return traces

def build_layout(_plot_df):
    axis = dict(gridcolor="rgba(0,0,0,0)", zeroline=True,
                zerolinecolor="#1e2d47", zerolinewidth=1.2,
                tickfont=dict(size=9, family="JetBrains Mono, monospace", color="#4a6080"),
                linecolor="#1e2d47", linewidth=1)
    tf = dict(size=10, family="JetBrains Mono, monospace", color="#4a6080")
    return go.Layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0f1623",
        margin=dict(l=64, r=18, t=16, b=60),
        xaxis=dict(title="← Component 1 →", title_font=tf, **axis),
        yaxis=dict(title="← Component 2 →", title_font=tf, **axis),
        hoverlabel=dict(bgcolor="#1a2540", bordercolor="#c8a84b",
                        font=dict(family="JetBrains Mono, monospace",
                                  size=11.5, color="#c8d4e8")),
        hovermode="closest", dragmode="pan",
        font=dict(family="Inter, sans-serif"), clickmode="event")

def build_arch_traces(plot_df, dimmed_arch, dot_size=9.5, dot_opacity=0.82):
    traces = []
    for arch in ARCHETYPE_ORDER:
        sub = plot_df[plot_df["primary_archetype"] == arch]
        if sub.empty:
            continue
        alpha = 0.08 if arch in dimmed_arch else dot_opacity
        traces.append(go.Scatter(
            x=sub["arch_pca_PC1"],
            y=sub["arch_pca_PC2"],
            mode="markers",
            marker=dict(
                size=dot_size,
                color=ARCHETYPE_COLOR[arch],
                opacity=alpha,
                line=dict(width=0),
            ),
            customdata=arch_cdata(sub),
            hovertemplate=ARCH_HOVER_TPL,
            name=arch,
            showlegend=False,
        ))
    return traces

def build_arch_layout(_plot_df):
    axis = dict(
        gridcolor="rgba(0,0,0,0)",
        zeroline=True,
        zerolinecolor="#1e2d47",
        zerolinewidth=1.2,
        tickfont=dict(size=9, family="JetBrains Mono, monospace", color="#4a6080"),
        linecolor="#1e2d47",
        linewidth=1,
    )
    tf = dict(size=10, family="JetBrains Mono, monospace", color="#4a6080")
    return go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0f1623",
        margin=dict(l=76, r=18, t=16, b=66),
        xaxis=dict(title="PC1 · size ↔ creator guard traits", title_font=tf, **axis),
        yaxis=dict(title="PC2 · shooting / spacing strength", title_font=tf, **axis),
        hoverlabel=dict(
            bgcolor="#1a2540",
            bordercolor="#c8a84b",
            font=dict(family="JetBrains Mono, monospace", size=11.5, color="#c8d4e8"),
        ),
        hovermode="closest",
        dragmode="pan",
        font=dict(family="Inter, sans-serif"),
        clickmode="event",
    )

def arch_legend_html(dimmed_arch):
    parts = []
    for arch in ARCHETYPE_ORDER:
        cls = "legend-item dim" if arch in dimmed_arch else "legend-item"
        col = ARCHETYPE_COLOR[arch]
        parts.append(
            f'<div class="{cls}" onclick="Shiny.setInputValue(\'toggle_arch_dim\','
            f'\'{arch}\',{{priority:\'event\'}})">'
            f'<span class="swatch" style="background:{col}"></span>'
            f'<span>{arch}</span></div>')
    parts.append('<span class="legend-hint">beta archetype PCA</span>')
    return "".join(parts)

RADAR_STATS = [
    ("scoring", "Scoring", "ppg", "PPG", "{:.1f}"),
    ("rebounding", "Rebounding", "rpg", "RPG", "{:.1f}"),
    ("playmaking", "Playmaking", "apg", "APG", "{:.1f}"),
    ("takeaways", "Takeaways", "spg", "SPG", "{:.2f}"),
    ("rim_defense", "Rim Defense", "bpg", "BPG", "{:.2f}"),
    ("efficiency", "Efficiency", "ts", "TS%", "{:.1%}"),
]
DEFAULT_RADAR_STAT_KEYS = [key for key, *_ in RADAR_STATS]
RADAR_STAT_LOOKUP = {key: stat for key, *stat in RADAR_STATS}

RADAR_PALETTE = [
    "#c8a84b", "#4a9eed", "#7cc47a", "#e8a44a",
    "#d86f74", "#8d7cc4", "#38a6a5", "#c47a1d",
]

def percentile_value(series, value):
    vals = pd.to_numeric(series, errors="coerce").dropna().sort_values().to_numpy()
    if len(vals) == 0:
        return 0.0
    return float(np.searchsorted(vals, float(value), side="right") / len(vals) * 100)

def hex_to_rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

def watchlist_rows(player_ids):
    rows = []
    for pid in player_ids:
        if pid.startswith("d1"):
            df_, div_ = d1_df, "D-I"
        elif pid.startswith("d3"):
            df_, div_ = d3_df, "D-III"
        else:
            df_, div_ = d2_df, "D-II"
        row_ = df_[df_["id"] == pid]
        if row_.empty:
            continue
        rows.append((pid, row_.iloc[0], df_, div_))
    return sorted(rows, key=lambda x: (x[3], str(x[1]["name"])))

def make_watchlist_radar(player_ids, stat_keys=None):
    fig = go.Figure()
    rows = watchlist_rows(player_ids)
    stat_keys = DEFAULT_RADAR_STAT_KEYS if stat_keys is None else stat_keys
    stats = [RADAR_STAT_LOOKUP[key] for key in stat_keys if key in RADAR_STAT_LOOKUP]

    if not rows or not stats:
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig

    theta = [s[0] for s in stats]
    theta_closed = theta + [theta[0]]

    for i, (_pid, r, df_, div_) in enumerate(rows):
        values = [percentile_value(df_[col], r[col]) for _, col, _, _ in stats]
        values_closed = values + [values[0]]
        actual = [fmt.format(float(r[col])) for _, col, _, fmt in stats]
        actual_closed = actual + [actual[0]]
        labels = [label for _, _, label, _ in stats]
        labels_closed = labels + [labels[0]]
        color = RADAR_PALETTE[i % len(RADAR_PALETTE)]

        fig.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=theta_closed,
            mode="lines+markers",
            name=f"{r['name']} · {div_}",
            line=dict(color=color, width=2.4),
            marker=dict(
                size=8,
                color=color,
                opacity=1,
                line=dict(color="#0f1623", width=1.6),
            ),
            fill="none",
            opacity=1,
            customdata=list(zip(labels_closed, actual_closed)),
            hovertemplate=(
                "<b>%{fullData.name}</b><br>"
                "%{customdata[0]}: %{customdata[1]}<br>"
                "Division percentile: %{r:.0f}"
                "<extra></extra>"
            ),
        ))

    fig.update_layout(
        template=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=34, r=34, t=22, b=22),
        showlegend=True,
        legend=dict(
            orientation="v",
            x=1.04,
            y=0.5,
            xanchor="left",
            yanchor="middle",
            font=dict(size=10, family="JetBrains Mono, monospace", color="#f4f7fb"),
            bgcolor="rgba(0,0,0,0)",
        ),
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                range=[0, 100],
                tickvals=[25, 50, 75, 100],
                tickfont=dict(size=9, family="JetBrains Mono, monospace", color="#f4f7fb"),
                gridcolor="rgba(244,247,251,0.24)",
                linecolor="rgba(244,247,251,0.34)",
                angle=90,
            ),
            angularaxis=dict(
                tickfont=dict(size=11, family="Inter, sans-serif", color="#ffffff"),
                gridcolor="rgba(244,247,251,0.24)",
                linecolor="rgba(244,247,251,0.34)",
            ),
        ),
        hoverlabel=dict(
            bgcolor="#1a2540",
            bordercolor="#c8a84b",
            font=dict(family="JetBrains Mono, monospace", size=11, color="#c8d4e8"),
        ),
        font=dict(family="Inter, sans-serif"),
    )
    return fig

def legend_html(dimmed_pos):
    parts = []
    for pos in POSITIONS:
        cls = "legend-item dim" if pos in dimmed_pos else "legend-item"
        col = POS_COLOR[pos]
        parts.append(
            f'<div class="{cls}" onclick="Shiny.setInputValue(\'toggle_dim\','
            f'\'{pos}\',{{priority:\'event\'}})">'
            f'<span class="swatch" style="background:{col}"></span>'
            f'<span>{pos} · {POS_LABEL[pos]}</span></div>')
    parts.append('<span class="legend-hint"></span>')
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────
# SIDEBAR / PLOT AREA BUILDERS
# ─────────────────────────────────────────────────────────────────────────

def make_sidebar(prefix, df, conferences):
    mpg_max = max(38,  int(df["mpg"].max())  + 2)
    ppg_max = max(28,  int(df["ppg"].max())  + 2)
    apg_max = max(9,   int(df["apg"].max())  + 1)
    efg_max = round(max(0.80, float(df["efg"].max())), 2)
    tp_max  = round(max(0.60, float(df["tp"].max())),  2)
    ato_max = round(max(6.0,  float(df["ast_tov"].max())), 1)
    h_min   = max(60, int(df["heightIn"].min()))
    h_max   = max(87, int(df["heightIn"].max()))
    conf_choices = {c["conf"]: c["confName"]
                    for c in sorted(conferences, key=lambda x: x["confName"])}

    return ui.div(
        {"class": "sidebar"},
        ui.div("Filters", class_="sb-title"),
        ui.div(ui.div("Search by name", class_="sb-section-head"),
               ui.input_text(f"{prefix}_q", None, placeholder="e.g. Marcus Jackson"),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Position"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_pos',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_positions", None,
                                       choices={p: p for p in POSITIONS}),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Class"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_cls',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_classes", None,
                                       choices={c: c for c in CLASSES}),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Conference"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_conf',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_confs", None, choices=conf_choices),
               class_="sb-section"),
        ui.div(ui.div("Team", class_="sb-section-head"),
               ui.input_select(f"{prefix}_team", None,
                   choices=["All teams"] + sorted(df["team"].unique().tolist())),
               class_="sb-section"),
        ui.div(ui.div("Minutes per game", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_mpg", None, min=10, max=mpg_max,
                               value=[10, mpg_max], step=1, post=" min"),
               class_="sb-section"),
        ui.div(ui.div("Points per game", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ppg_range", None, min=0, max=ppg_max,
                               value=[0, ppg_max], step=1, post=" pts"),
               class_="sb-section"),
        ui.div(ui.div("eFG%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_efg", None, min=0.0, max=efg_max,
                               value=[0.0, efg_max], step=0.01),
               class_="sb-section"),
        ui.div(ui.div("3P%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_tp_range", None, min=0.0, max=tp_max,
                               value=[0.0, tp_max], step=0.01),
               class_="sb-section"),
        ui.div(ui.div("3P Share", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_three_share", None, min=0.0, max=1.0,
                               value=[0.0, 1.0], step=0.01),
               class_="sb-section"),
        ui.div(ui.div("Assists per game", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_apg_range", None, min=0.0, max=float(apg_max),
                               value=[0.0, float(apg_max)], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("AST / TOV ratio", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ast_tov", None, min=0.0, max=ato_max,
                               value=[0.0, ato_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("Height", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_height", None, min=h_min, max=h_max,
                               value=[h_min, h_max], step=1),
               class_="sb-section"),
        ui.div({"class": "sb-count"},
               ui.span("Showing", class_="lbl"),
               ui.output_text(f"{prefix}_filter_count")),
    )


def make_plot_area(prefix):
    return ui.div(
        {"class": "plot-area"},
        ui.div({"class": "plot-toolbar"},
               ui.div(ui.HTML(""), class_="plot-headline"),
               ui.output_ui(f"{prefix}_plot_meta")),
        ui.div({"class": "legend-bar"},
               ui.output_ui(f"{prefix}_legend_ui")),
        ui.div({"class": "scatter-wrap"},
               output_widget(f"{prefix}_scatter")),
    )

def make_arch_sidebar(prefix, df, conferences):
    conf_choices = {c["conf"]: c["confName"]
                    for c in sorted(conferences, key=lambda x: x["confName"])}
    return ui.div(
        {"class": "sidebar"},
        ui.div("Beta Filters", class_="sb-title"),
        ui.div(ui.div("Search by name", class_="sb-section-head"),
               ui.input_text(f"{prefix}_q", None, placeholder="e.g. Marcus Jackson"),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Archetype"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_arch',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_archetypes", None,
                                       choices={a: a for a in ARCHETYPE_ORDER}),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Position"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_pos',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_positions", None,
                                       choices={p: p for p in POSITIONS}),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Class"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_cls',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_classes", None,
                                       choices={c: c for c in CLASSES}),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Conference"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_conf',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_confs", None, choices=conf_choices),
               class_="sb-section"),
        ui.div(ui.div("Team", class_="sb-section-head"),
               ui.input_select(f"{prefix}_team", None,
                   choices=["All teams"] + sorted(df["team"].unique().tolist())),
               class_="sb-section"),
        ui.div(ui.div("Archetype score", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_score", None, min=0, max=100,
                               value=[0, 100], step=1),
               class_="sb-section"),
        ui.div(ui.div("3P%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_tp_range", None, min=0.0, max=0.75,
                               value=[0.0, 0.75], step=0.01),
               class_="sb-section"),
        ui.div(ui.div("3P Share", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_three_share", None, min=0.0, max=1.0,
                               value=[0.0, 1.0], step=0.01),
               class_="sb-section"),
        ui.div(ui.div("AST / TOV ratio", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ast_tov", None, min=0.0, max=8.0,
                               value=[0.0, 8.0], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("Height", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_height", None, min=60, max=90,
                               value=[60, 90], step=1),
               class_="sb-section"),
        ui.div({"class": "sb-count"},
               ui.span("Showing", class_="lbl"),
               ui.output_text(f"{prefix}_filter_count")),
    )

def make_arch_plot_area(prefix, title):
    return ui.div(
        {"class": "plot-area"},
        ui.div({"class": "plot-toolbar"},
               ui.div(title, class_="plot-headline"),
               ui.output_ui(f"{prefix}_plot_meta")),
        ui.div({"class": "legend-bar"},
               ui.output_ui(f"{prefix}_legend_ui")),
        ui.div({"class": "scatter-wrap"},
               output_widget(f"{prefix}_scatter")),
    )


# ─────────────────────────────────────────────────────────────────────────
# APP UI
# ─────────────────────────────────────────────────────────────────────────

app_ui = ui.page_fluid(
    ui.tags.head(
        ui.tags.link(rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;0,8..60,700;1,8..60,400;1,8..60,500&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"),
        ui.include_css(str(HERE / "www" / "styles.css"), method="inline"),
        ui.tags.style("""
            /* ── Tab bar ─────────────────────────────────────── */
            #tab-switcher {
                display:flex; gap:4px; align-items:center;
                padding:0 28px; background:var(--bg);
                border-bottom:1px solid var(--rule);
                height:38px; flex-shrink:0;
                overflow-x:auto; overflow-y:hidden; white-space:nowrap;
            }
            .tab-btn {
                font-family:var(--sans); font-size:11px; font-weight:600;
                letter-spacing:.10em; text-transform:uppercase;
                color:var(--ink-3); background:none; border:none;
                border-bottom:2px solid transparent;
                padding:0 14px; height:38px; cursor:pointer;
                flex:0 0 auto;
                transition:color .15s, border-color .15s;
            }
            .tab-btn:hover     { color:var(--ink-2); }
            .tab-btn.active-d1 { color:#4a9eed;       border-bottom-color:#4a9eed; }
            .tab-btn.active-d2 { color:var(--accent);  border-bottom-color:var(--accent); }
            .tab-btn.active-d3 { color:#e8a44a;        border-bottom-color:#e8a44a; }
            .tab-btn.active-a1 { color:#4a9eed;        border-bottom-color:#4a9eed; }
            .tab-btn.active-a2 { color:#7cc47a;        border-bottom-color:#7cc47a; }
            .tab-btn.active-a3 { color:#e8a44a;        border-bottom-color:#e8a44a; }
            .tab-btn.active-info { color:var(--ink);    border-bottom-color:var(--ink); }
            .tab-btn.active-wl { color:#7cc47a;         border-bottom-color:#7cc47a; }
            .tab-sep { width:1px; height:16px; background:var(--rule-2); margin:0 4px; }

            /* watchlist badge on tab button */
            .wl-badge {
                display:inline-block; background:#7cc47a; color:#0f1623;
                font-size:9px; font-weight:800; font-family:var(--mono);
                border-radius:8px; padding:1px 5px; margin-left:5px;
                vertical-align:middle; line-height:14px;
            }

            /* star button inside modal */
            .player-name-row {
                display:flex; align-items:flex-start; gap:10px; margin-bottom:3px;
            }
            .star-btn {
                background:none; border:none; cursor:pointer;
                font-size:24px; line-height:1; padding:2px 0 0 0;
                flex-shrink:0; transition:color .15s, transform .1s;
            }
            .star-btn:hover { transform:scale(1.2); }

            /* watchlist tab layout */
            .wl-shell {
                display:flex; flex-direction:column; height:100%; overflow:hidden;
            }
            .wl-header {
                display:flex; align-items:baseline; gap:14px;
                padding:14px 28px 10px; border-bottom:1px solid var(--rule);
                flex-shrink:0;
            }
            .wl-title {
                font-family:var(--serif); font-size:20px; font-weight:600;
            }
            .wl-empty {
                flex:1; display:flex; flex-direction:column;
                align-items:center; justify-content:center;
                color:var(--ink-3); font-family:var(--mono); font-size:12px;
                gap:10px;
            }
            .wl-empty .wl-star { font-size:36px; opacity:.3; }
            .wl-grid {
                flex:1; overflow-y:auto;
                display:grid;
                grid-template-columns:repeat(auto-fill, minmax(300px, 1fr));
                gap:12px; padding:18px 24px; align-content:start;
            }
            .wl-radar-wrap {
                border-bottom:1px solid var(--rule);
                padding:14px 24px 10px;
                flex-shrink:0;
                background:var(--bg);
            }
            .wl-radar-head {
                display:flex; justify-content:space-between; align-items:baseline;
                margin-bottom:6px; gap:12px;
            }
            .wl-radar-tools {
                display:grid; grid-template-columns:minmax(170px, 1fr) minmax(170px, 1fr) minmax(240px, 1.25fr);
                align-items:start; gap:14px; border-top:1px solid var(--rule);
                padding-top:8px; margin-top:4px;
            }
            .wl-radar-picker {
                display:contents;
            }
            .wl-radar-field .shiny-input-container {
                margin:0; width:100%;
            }
            .wl-radar-field-title {
                font-family:var(--sans); font-size:9px; font-weight:700;
                letter-spacing:.14em; text-transform:uppercase;
                color:var(--ink-3); margin-bottom:4px;
            }
            .wl-radar-field .selectize-input {
                min-height:30px !important;
                border:1px solid var(--rule-2) !important;
                border-radius:0 !important;
                background:var(--bg-2) !important;
                color:var(--ink) !important;
                box-shadow:none !important;
                font-family:var(--mono) !important;
                font-size:10px !important;
                padding:4px 7px !important;
            }
            .wl-radar-field .selectize-input input {
                color:var(--ink) !important;
                font-family:var(--mono) !important; font-size:10px !important;
            }
            .wl-radar-field .selectize-input .item {
                background:rgba(200,168,75,.16) !important;
                border:1px solid rgba(200,168,75,.45) !important;
                border-radius:2px !important;
                color:#f4f7fb !important;
                padding:1px 5px !important;
                margin:1px 3px 1px 0 !important;
            }
            .wl-radar-field .selectize-dropdown {
                background:var(--bg-2) !important;
                border:1px solid var(--rule-2) !important;
                color:var(--ink) !important;
                font-family:var(--mono) !important;
                font-size:10px !important;
            }
            .wl-radar-field .selectize-dropdown .active {
                background:rgba(200,168,75,.18) !important;
                color:#fff !important;
            }
            .wl-radar-stat-checks .shiny-options-group {
                display:grid !important;
                grid-template-columns:repeat(3, minmax(0, 1fr));
                gap:4px 10px !important;
            }
            .wl-radar-stat-checks .shiny-input-container {
                margin-top:8px;
            }
            .wl-radar-stat-checks .checkbox {
                margin:0 !important;
            }
            .wl-radar-stat-checks .checkbox label {
                display:flex !important; align-items:center !important;
                gap:6px !important; margin:0 !important;
                font-family:var(--mono) !important; font-size:10px !important;
                color:var(--ink-2) !important; line-height:1.25;
                cursor:pointer;
            }
            .wl-radar-stat-checks .checkbox input[type="checkbox"] {
                margin:0 !important;
                accent-color:var(--accent);
            }
            .wl-radar-stat-checks .checkbox:has(input:checked) label {
                color:#f4f7fb !important;
            }
            .wl-radar-title {
                font-family:var(--sans); font-size:10px; font-weight:700;
                letter-spacing:.16em; text-transform:uppercase; color:var(--ink-3);
            }
            .wl-radar-note {
                font-family:var(--mono); font-size:9.5px; color:var(--ink-3);
            }
            .wl-radar {
                height:320px;
                min-height:260px;
            }
            .wl-radar .modebar {
                display:none !important;
            }
            .wl-radar .main-svg,
            .wl-radar .plot-container,
            .wl-radar .svg-container {
                background:transparent !important;
            }
            .wl-card {
                background:var(--bg-2); border:1px solid var(--rule-2);
                padding:14px 16px; display:flex; flex-direction:column; gap:8px;
                cursor:pointer; transition:border-color .15s;
                position:relative;
            }
            .wl-card:hover { border-color:var(--ink-2); }
            .wl-card-name {
                font-family:var(--serif); font-size:16px; font-weight:600;
                line-height:1.1; padding-right:28px;
            }
            .wl-card-meta {
                font-size:11px; color:var(--ink-2);
                display:flex; gap:6px; align-items:center;
            }
            .wl-card-stats {
                display:grid; grid-template-columns:repeat(4,1fr);
                gap:4px 0; margin-top:4px;
                border-top:1px solid var(--rule); padding-top:8px;
            }
            .wl-stat { display:flex; flex-direction:column; }
            .wl-stat .n { font-family:var(--serif); font-size:15px; font-weight:600; }
            .wl-stat .l {
                font-size:8.5px; letter-spacing:.1em; text-transform:uppercase;
                color:var(--ink-3); margin-top:1px;
            }
            .wl-remove {
                position:absolute; top:10px; right:10px;
                background:none; border:none; cursor:pointer;
                color:var(--ink-3); font-size:16px; line-height:1; padding:2px;
                transition:color .15s;
            }
            .wl-remove:hover { color:var(--accent); }

            /* ── Tab panels ────────────────────────────────────── */
            #tab-content {
                flex:1; overflow:hidden;
                display:flex; flex-direction:column;
            }
            .tab-panel {
                flex:0; height:0; overflow:hidden;
                display:flex; flex-direction:column;
                min-height:0;
            }
            .tab-panel.active {
                flex:1; height:auto; overflow:hidden;
            }

            /* ── Guide / documentation page ────────────────────── */
            .doc-shell {
                flex:1; overflow-y:auto; background:var(--bg);
                padding:26px 28px 56px;
            }
            .doc-inner {
                max-width:880px; margin:0 auto;
                color:var(--ink-2); font-family:var(--sans);
                line-height:1.62; font-size:14px;
            }
            .doc-inner h1 {
                font-family:var(--serif); font-size:34px; line-height:1.05;
                color:var(--ink); font-weight:600; margin:0 0 20px;
                border-bottom:2px solid var(--ink); padding-bottom:12px;
            }
            .doc-inner h2 {
                font-family:var(--serif); font-size:22px; color:var(--ink);
                font-weight:600; margin:30px 0 10px;
                border-top:1px solid var(--rule); padding-top:18px;
            }
            .doc-inner h3 {
                font-family:var(--sans); font-size:12px; color:var(--ink);
                font-weight:800; text-transform:uppercase; letter-spacing:.13em;
                margin:22px 0 8px;
            }
            .doc-inner p { margin:0 0 12px; }
            .doc-inner ul,
            .doc-inner ol { margin:0 0 14px 22px; padding:0; }
            .doc-inner li { margin:4px 0; padding-left:2px; }
            .doc-inner strong { color:var(--ink); font-weight:700; }
            .doc-inner code {
                font-family:var(--mono); font-size:12px;
                color:#f4f7fb; background:var(--bg-2);
                border:1px solid var(--rule-2); padding:1px 5px;
            }
            .doc-inner blockquote {
                border-left:3px solid var(--accent);
                margin:14px 0; padding:8px 14px;
                background:rgba(200,168,75,.08); color:var(--ink);
                font-family:var(--serif); font-size:16px;
            }

            /* ── Body / sidebar / plot shared layout ─────────── */
            .body-grid {
                display:grid; grid-template-columns:220px 1fr;
                flex:1; overflow:hidden; height:100%;
            }
            .sidebar {
                overflow-y:auto; border-right:1px solid var(--rule);
                padding:16px 14px 32px;
                background:var(--bg);
            }
            .plot-area    { display:flex; flex-direction:column; overflow:hidden; }
            .plot-toolbar {
                display:flex; justify-content:space-between; align-items:center;
                padding:8px 18px 4px; border-bottom:1px solid var(--rule); flex-shrink:0;
            }
            .legend-bar {
                padding:6px 18px; border-bottom:1px solid var(--rule);
                display:flex; gap:12px; flex-shrink:0;
            }
            .scatter-wrap { flex:1; overflow:hidden; }

            /* ── Sidebar inputs ── */
            .sidebar .form-control,
            .sidebar .selectize-input,
            .sidebar select {
                border:1px solid var(--rule-2) !important; border-radius:0 !important;
                background:var(--bg) !important; color:var(--ink) !important;
                font-family:var(--sans) !important; font-size:12.5px !important;
                box-shadow:none !important; padding:6px 8px !important;
            }
            .sidebar .irs--shiny .irs-bar    { background:var(--accent) !important; border-top:none; border-bottom:none; }
            .sidebar .irs--shiny .irs-handle { background:var(--bg) !important; border:2px solid var(--accent) !important; border-radius:50% !important; }
            .sidebar .irs--shiny .irs-line   { background:var(--rule-2) !important; border:none; }
            .sidebar .irs--shiny .irs-from,
            .sidebar .irs--shiny .irs-to,
            .sidebar .irs--shiny .irs-single { background:var(--accent) !important; color:#0f1623 !important; font-family:var(--mono); font-size:10px; font-weight:700; border-radius:0 !important; }
            .sidebar .irs--shiny .irs-min,
            .sidebar .irs--shiny .irs-max   { font-family:var(--mono); font-size:9.5px; color:var(--ink-2); }

            /* ── Checkbox groups ── */
            .sidebar .shiny-input-container { margin-bottom:0; }
            .sidebar .checkbox input[type="checkbox"] { display:none !important; }
            .sidebar .checkbox label {
                display:flex !important; align-items:center !important;
                gap:6px !important; cursor:pointer;
                font-family:var(--mono) !important; font-size:10.5px !important;
                font-weight:400 !important; color:var(--ink-2) !important;
                padding:3px 2px !important; margin:0 !important;
                border:none !important; background:transparent !important;
                border-bottom:1px dotted var(--rule);
                white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
                max-width:200px; line-height:1.3;
                transition:color .1s;
            }
            .sidebar .checkbox label:hover { color:var(--ink) !important; }
            .sidebar .checkbox input[type="checkbox"]:checked + span,
            .sidebar .checkbox input[type="checkbox"]:checked ~ span {
                color:var(--ink) !important; font-weight:700 !important;
            }
            .sidebar .checkbox label::before {
                content:""; display:inline-block; flex-shrink:0;
                width:7px; height:7px; border-radius:50%;
                border:1px solid var(--rule-2); background:transparent;
                transition:background .1s, border-color .1s;
            }
            .sidebar .checkbox input[type="checkbox"]:checked ~ label::before,
            .sidebar .checkbox:has(input:checked) label::before {
                background:var(--accent); border-color:var(--accent);
            }
            .sidebar .shiny-options-group {
                display:flex !important; flex-direction:column !important;
                gap:0 !important; flex-wrap:nowrap !important;
            }
            .sidebar .checkbox {
                display:block !important; width:100%; margin:0 !important;
            }
            .sidebar [id$="_confs"] .checkbox label {
                font-size:10px !important;
                max-width:195px !important;
            }

            /* ── Division badge in modal ── */
            .div-badge {
                font-size:10px; font-weight:700; letter-spacing:.12em;
                text-transform:uppercase; border-radius:3px;
                padding:2px 7px; margin-left:6px;
                background:var(--bg-2); color:var(--ink-2); vertical-align:middle;
            }
        """),
        ui.tags.script("""
            function switchTab(tab) {
                document.querySelectorAll('.tab-panel').forEach(function(p) {
                    p.classList.remove('active');
                });
                document.querySelectorAll('.tab-btn').forEach(function(b) {
                    b.classList.remove('active-d1','active-d2','active-d3','active-a1','active-a2','active-a3','active-info','active-wl');
                });
                document.getElementById(tab+'-tab').classList.add('active');
                document.getElementById('btn-'+tab).classList.add('active-'+tab);

                requestAnimationFrame(function() {
                    requestAnimationFrame(function() {
                        var panel = document.getElementById(tab+'-tab');
                        if (!panel) return;
                        panel.querySelectorAll('.js-plotly-plot').forEach(function(el) {
                            if (window.Plotly) Plotly.Plots.resize(el);
                        });
                    });
                });
            }
        """),
    ),

    ui.div({"id": "atlas-shell"},

        ui.div({"id": "masthead"},
            ui.div({"class": "mast-left"},
                   ui.div(ui.HTML('NCAA Men\'s Basketball <span class="dot"></span> 2025–26'),
                          class_="kicker"),
                   ui.div(ui.HTML("Player <em>Dashboard</em>"), class_="atlas-title")),
            ui.div({"class": "mast-meta"},
                   ui.div(ui.div(str(D1_TOTAL),                class_="mast-stat-num"),
                          ui.div("D-I Players",                class_="mast-stat-lbl"), class_="mast-stat"),
                   ui.div(ui.div(str(d1_df["team"].nunique()),  class_="mast-stat-num"),
                          ui.div("D-I Teams",                  class_="mast-stat-lbl"), class_="mast-stat"),
                   ui.div(ui.div(str(D2_TOTAL),                class_="mast-stat-num"),
                          ui.div("D-II Players",               class_="mast-stat-lbl"), class_="mast-stat"),
                   ui.div(ui.div(str(d2_df["team"].nunique()),  class_="mast-stat-num"),
                          ui.div("D-II Teams",                 class_="mast-stat-lbl"), class_="mast-stat"),
                   ui.div(ui.div(str(D3_TOTAL),                class_="mast-stat-num"),
                          ui.div("D-III Players",              class_="mast-stat-lbl"), class_="mast-stat"),
                   ui.div(ui.div(str(d3_df["team"].nunique()),  class_="mast-stat-num"),
                          ui.div("D-III Teams",                class_="mast-stat-lbl"), class_="mast-stat")),
        ),

        ui.div({"id": "tab-switcher"},
               ui.tags.button("Division I",   id="btn-d1", class_="tab-btn",
                              onclick="switchTab('d1')"),
               ui.div({"class": "tab-sep"}),
               ui.tags.button("Division II",  id="btn-d2", class_="tab-btn active-d2",
                              onclick="switchTab('d2')"),
               ui.div({"class": "tab-sep"}),
               ui.tags.button("Division III", id="btn-d3", class_="tab-btn",
                              onclick="switchTab('d3')"),
               ui.div({"class": "tab-sep"}),
               ui.tags.button("D-I Archetype Beta", id="btn-a1", class_="tab-btn",
                              onclick="switchTab('a1')"),
               ui.div({"class": "tab-sep"}),
               ui.tags.button("D-II Archetype Beta", id="btn-a2", class_="tab-btn",
                              onclick="switchTab('a2')"),
               ui.div({"class": "tab-sep"}),
               ui.tags.button("D-III Archetype Beta", id="btn-a3", class_="tab-btn",
                              onclick="switchTab('a3')"),
               ui.div({"class": "tab-sep"}),
               ui.tags.button("Archetype Guide", id="btn-info", class_="tab-btn",
                              onclick="switchTab('info')"),
               ui.div({"class": "tab-sep"}),
               ui.tags.button(
                   ui.HTML('Watchlist <span id="wl-badge" class="wl-badge" style="display:none">0</span>'),
                   id="btn-wl", class_="tab-btn",
                   onclick="switchTab('wl')")),

        ui.div({"id": "tab-content"},

            ui.div({"id": "d1-tab", "class": "tab-panel"},
                   ui.div({"class": "body-grid"},
                          make_sidebar("d1", d1_df, d1_conferences),
                          make_plot_area("d1"))),

            ui.div({"id": "d2-tab", "class": "tab-panel active"},
                   ui.div({"class": "body-grid"},
                          make_sidebar("d2", d2_df, d2_conferences),
                          make_plot_area("d2"))),

            ui.div({"id": "d3-tab", "class": "tab-panel"},
                   ui.div({"class": "body-grid"},
                          make_sidebar("d3", d3_df, d3_conferences),
                          make_plot_area("d3"))),

            ui.div({"id": "a1-tab", "class": "tab-panel"},
                   ui.div({"class": "body-grid"},
                          make_arch_sidebar("a1", d1_df, d1_conferences),
                          make_arch_plot_area("a1", "Division I Archetype Beta"))),

            ui.div({"id": "a2-tab", "class": "tab-panel"},
                   ui.div({"class": "body-grid"},
                          make_arch_sidebar("a2", d2_df, d2_conferences),
                          make_arch_plot_area("a2", "Division II Archetype Beta"))),

            ui.div({"id": "a3-tab", "class": "tab-panel"},
                   ui.div({"class": "body-grid"},
                          make_arch_sidebar("a3", d3_df, d3_conferences),
                          make_arch_plot_area("a3", "Division III Archetype Beta"))),

            ui.div({"id": "info-tab", "class": "tab-panel"},
                   make_explainer_page()),

            ui.div({"id": "wl-tab", "class": "tab-panel"},
                   ui.div({"class": "wl-shell"},
                          ui.div({"class": "wl-header"},
                                 ui.div("Watchlist", class_="wl-title"),
                                 ui.output_text("wl_count")),
                          ui.div(
                              {"class": "wl-radar-wrap"},
                              ui.div(
                                  {"class": "wl-radar-head"},
                                  ui.div("Radar Comparison", class_="wl-radar-title"),
                                  ui.div("percentile within each player's division", class_="wl-radar-note"),
                              ),
                              ui.div({"class": "wl-radar"}, output_widget("watchlist_radar")),
                              ui.div(
                                  {"class": "wl-radar-tools"},
                                  ui.output_ui("wl_radar_picker"),
                              ),
                          ),
                          ui.output_ui("watchlist_ui"))),
        ),
    ),

    ui.output_ui("d1_modal_trigger"),
    ui.output_ui("d2_modal_trigger"),
    ui.output_ui("d3_modal_trigger"),
)


# ─────────────────────────────────────────────────────────────────────────
# SERVER
# ─────────────────────────────────────────────────────────────────────────

def server(input, output, session):

    d1_sel    = reactive.Value(None)
    d1_dim    = reactive.Value(set())
    d2_sel    = reactive.Value(None)
    d2_dim    = reactive.Value(set())
    d3_sel    = reactive.Value(None)
    d3_dim    = reactive.Value(set())
    a1_dim    = reactive.Value(set())
    a2_dim    = reactive.Value(set())
    a3_dim    = reactive.Value(set())
    watchlist = reactive.Value(set())
    radar_selected = reactive.Value([])
    radar_stat_selected = reactive.Value(DEFAULT_RADAR_STAT_KEYS)
    modal_req = reactive.Value(None)

    d1_fig = go.FigureWidget()
    d2_fig = go.FigureWidget()
    d3_fig = go.FigureWidget()
    a1_fig = go.FigureWidget()
    a2_fig = go.FigureWidget()
    a3_fig = go.FigureWidget()

    def sync_radar_selection(player_ids):
        available = [pid for pid, *_ in watchlist_rows(player_ids)]
        selected = [pid for pid in radar_selected.get() if pid in available][:2]
        for pid in available:
            if len(selected) >= 2:
                break
            if pid not in selected:
                selected.append(pid)
        radar_selected.set(selected)

    # ── Watchlist toggle ──────────────────────────────────────────────────
    @reactive.effect
    @reactive.event(input.toggle_watchlist)
    def _toggle_watchlist():
        pid  = input.toggle_watchlist()
        curr = set(watchlist.get())
        curr.discard(pid) if pid in curr else curr.add(pid)
        watchlist.set(curr)
        sync_radar_selection(curr)
        import random
        modal_req.set((pid, random.random()))

    # ── Legend dim (shared toggle_dim input across all three tabs) ────────
    @reactive.effect
    @reactive.event(input.toggle_dim)
    def _all_dim():
        pos = input.toggle_dim()
        for rv in (d1_dim, d2_dim, d3_dim):
            curr = set(rv.get())
            curr.discard(pos) if pos in curr else curr.add(pos)
            rv.set(curr)

    @reactive.effect
    @reactive.event(input.toggle_arch_dim)
    def _all_arch_dim():
        arch = input.toggle_arch_dim()
        for rv in (a1_dim, a2_dim, a3_dim):
            curr = set(rv.get())
            curr.discard(arch) if arch in curr else curr.add(arch)
            rv.set(curr)

    # ── Single modal opener — handles d1p / d2p / d3p prefixes ───────────
    @reactive.effect
    @reactive.event(modal_req)
    def _open_modal():
        req = modal_req.get()
        if not req: return
        pid, _ = req
        wl = watchlist.get()
        if pid.startswith("d1"):
            df_, la_, sf_, div_ = d1_df, d1_league_avg, d1_similar_to, "D-I"
        elif pid.startswith("d3"):
            df_, la_, sf_, div_ = d3_df, d3_league_avg, d3_similar_to, "D-III"
        else:
            df_, la_, sf_, div_ = d2_df, d2_league_avg, d2_similar_to, "D-II"
        row = df_[df_["id"] == pid]
        if row.empty: return
        ui.modal_show(make_detail_modal(pid, df_, la_, sf_, div_, wl))

    # ── Open modal from watchlist card ────────────────────────────────────
    @reactive.effect
    @reactive.event(input.wl_open_player)
    def _wl_open_player():
        pid = input.wl_open_player()
        if not pid: return
        import random
        modal_req.set((pid, random.random()))

    # ═══════════════════════════════════════════════════════════════════════
    # D-I
    # ═══════════════════════════════════════════════════════════════════════

    @reactive.effect
    @reactive.event(input.d1_clear_pos)
    def _d1_clear_pos():
        ui.update_checkbox_group("d1_positions", selected=[])

    @reactive.effect
    @reactive.event(input.d1_clear_cls)
    def _d1_clear_cls():
        ui.update_checkbox_group("d1_classes", selected=[])

    @reactive.effect
    @reactive.event(input.d1_clear_conf)
    def _d1_clear_conf():
        ui.update_checkbox_group("d1_confs", selected=[])
        ui.update_select("d1_team", selected="All teams")

    @reactive.effect
    @reactive.event(input.d1_select_similar)
    def _d1_select_similar():
        sid = input.d1_select_similar()
        if sid:
            d1_sel.set(sid)
            ui.modal_remove()
            import random
            modal_req.set((sid, random.random()))

    @reactive.calc
    def d1_filtered():
        d = d1_df.copy()
        q = (input.d1_q() or "").strip().lower()
        if q: d = d[d["name"].str.lower().str.contains(q, na=False)]
        ps = list(input.d1_positions() or [])
        if ps: d = d[d["pos"].isin(ps)]
        cs = list(input.d1_classes() or [])
        if cs: d = d[d["cls"].isin(cs)]
        xs = list(input.d1_confs() or [])
        if xs: d = d[d["conf"].isin(xs)]
        t = input.d1_team()
        if t and t != "All teams": d = d[d["team"] == t]
        lo, hi = input.d1_mpg();         d = d[(d["mpg"]         >= lo) & (d["mpg"]         <= hi)]
        lo, hi = input.d1_ppg_range();   d = d[(d["ppg"]         >= lo) & (d["ppg"]         <= hi)]
        lo, hi = input.d1_efg();         d = d[(d["efg"]         >= lo) & (d["efg"]         <= hi)]
        lo, hi = input.d1_tp_range();    d = d[(d["tp"]          >= lo) & (d["tp"]          <= hi)]
        lo, hi = input.d1_three_share(); d = d[(d["three_share"]  >= lo) & (d["three_share"]  <= hi)]
        lo, hi = input.d1_apg_range();   d = d[(d["apg"]         >= lo) & (d["apg"]         <= hi)]
        lo, hi = input.d1_ast_tov();     d = d[(d["ast_tov"]     >= lo) & (d["ast_tov"]     <= hi)]
        lo, hi = input.d1_height();      d = d[(d["heightIn"]    >= lo) & (d["heightIn"]    <= hi)]
        return d

    @reactive.calc
    def d1_plot_df():
        ids = set(d1_filtered()["id"])
        sid = d1_sel.get()
        if sid: ids.add(sid)
        return d1_df[d1_df["id"].isin(ids)]

    @output
    @render.text
    def d1_filter_count():
        return f"{len(d1_filtered())} / {D1_TOTAL}"

    @output
    @render.ui
    def d1_legend_ui():
        return ui.HTML(legend_html(d1_dim.get()))

    @output
    @render.ui
    def d1_plot_meta():
        sid = d1_sel.get()
        if sid is not None:
            row = d1_df[d1_df["id"] == sid]
            if not row.empty:
                return ui.div(ui.HTML(f'<span class="accent">●</span> {row.iloc[0]["name"]} selected'), class_="plot-meta")
        return ui.div("Hover a dot for details · click to expand", class_="plot-meta")

    @render_widget
    def d1_scatter():
        return d1_fig

    @reactive.effect
    def _d1_sync():
        traces = build_traces(d1_plot_df(), d1_sel.get(), d1_dim.get())
        layout = build_layout(d1_plot_df())
        with d1_fig.batch_update():
            d1_fig.data = []
            for t in traces: d1_fig.add_trace(t)
            d1_fig.update_layout(layout)
        for trace in d1_fig.data:
            if hasattr(trace, "customdata") and trace.customdata is not None and len(trace.customdata):
                trace.on_click(_d1_clicked)

    def _d1_clicked(trace, points, selector):
        if not points or not points.point_inds: return
        cd = trace.customdata[points.point_inds[0]]
        if cd is not None and len(cd) >= 8:
            import random
            d1_sel.set(str(cd[7]))
            modal_req.set((str(cd[7]), random.random()))

    @output
    @render.ui
    def d1_modal_trigger():
        return ui.div()

    # ═══════════════════════════════════════════════════════════════════════
    # D-II
    # ═══════════════════════════════════════════════════════════════════════

    @reactive.effect
    @reactive.event(input.d2_clear_pos)
    def _d2_clear_pos():
        ui.update_checkbox_group("d2_positions", selected=[])

    @reactive.effect
    @reactive.event(input.d2_clear_cls)
    def _d2_clear_cls():
        ui.update_checkbox_group("d2_classes", selected=[])

    @reactive.effect
    @reactive.event(input.d2_clear_conf)
    def _d2_clear_conf():
        ui.update_checkbox_group("d2_confs", selected=[])
        ui.update_select("d2_team", selected="All teams")

    @reactive.effect
    @reactive.event(input.d2_select_similar)
    def _d2_select_similar():
        sid = input.d2_select_similar()
        if sid:
            d2_sel.set(sid)
            ui.modal_remove()
            import random
            modal_req.set((sid, random.random()))

    @reactive.calc
    def d2_filtered():
        d = d2_df.copy()
        q = (input.d2_q() or "").strip().lower()
        if q: d = d[d["name"].str.lower().str.contains(q, na=False)]
        ps = list(input.d2_positions() or [])
        if ps: d = d[d["pos"].isin(ps)]
        cs = list(input.d2_classes() or [])
        if cs: d = d[d["cls"].isin(cs)]
        xs = list(input.d2_confs() or [])
        if xs: d = d[d["conf"].isin(xs)]
        t = input.d2_team()
        if t and t != "All teams": d = d[d["team"] == t]
        lo, hi = input.d2_mpg();         d = d[(d["mpg"]         >= lo) & (d["mpg"]         <= hi)]
        lo, hi = input.d2_ppg_range();   d = d[(d["ppg"]         >= lo) & (d["ppg"]         <= hi)]
        lo, hi = input.d2_efg();         d = d[(d["efg"]         >= lo) & (d["efg"]         <= hi)]
        lo, hi = input.d2_tp_range();    d = d[(d["tp"]          >= lo) & (d["tp"]          <= hi)]
        lo, hi = input.d2_three_share(); d = d[(d["three_share"]  >= lo) & (d["three_share"]  <= hi)]
        lo, hi = input.d2_apg_range();   d = d[(d["apg"]         >= lo) & (d["apg"]         <= hi)]
        lo, hi = input.d2_ast_tov();     d = d[(d["ast_tov"]     >= lo) & (d["ast_tov"]     <= hi)]
        lo, hi = input.d2_height();      d = d[(d["heightIn"]    >= lo) & (d["heightIn"]    <= hi)]
        return d

    @reactive.calc
    def d2_plot_df():
        ids = set(d2_filtered()["id"])
        sid = d2_sel.get()
        if sid: ids.add(sid)
        return d2_df[d2_df["id"].isin(ids)]

    @output
    @render.text
    def d2_filter_count():
        return f"{len(d2_filtered())} / {D2_TOTAL}"

    @output
    @render.ui
    def d2_legend_ui():
        return ui.HTML(legend_html(d2_dim.get()))

    @output
    @render.ui
    def d2_plot_meta():
        sid = d2_sel.get()
        if sid is not None:
            row = d2_df[d2_df["id"] == sid]
            if not row.empty:
                return ui.div(ui.HTML(f'<span class="accent">●</span> {row.iloc[0]["name"]} selected'), class_="plot-meta")
        return ui.div("Hover a dot for details · click to expand", class_="plot-meta")

    @render_widget
    def d2_scatter():
        return d2_fig

    @reactive.effect
    def _d2_sync():
        traces = build_traces(d2_plot_df(), d2_sel.get(), d2_dim.get())
        layout = build_layout(d2_plot_df())
        with d2_fig.batch_update():
            d2_fig.data = []
            for t in traces: d2_fig.add_trace(t)
            d2_fig.update_layout(layout)
        for trace in d2_fig.data:
            if hasattr(trace, "customdata") and trace.customdata is not None and len(trace.customdata):
                trace.on_click(_d2_clicked)

    def _d2_clicked(trace, points, selector):
        if not points or not points.point_inds: return
        cd = trace.customdata[points.point_inds[0]]
        if cd is not None and len(cd) >= 8:
            import random
            d2_sel.set(str(cd[7]))
            modal_req.set((str(cd[7]), random.random()))

    @output
    @render.ui
    def d2_modal_trigger():
        return ui.div()

    # ═══════════════════════════════════════════════════════════════════════
    # D-III
    # ═══════════════════════════════════════════════════════════════════════

    @reactive.effect
    @reactive.event(input.d3_clear_pos)
    def _d3_clear_pos():
        ui.update_checkbox_group("d3_positions", selected=[])

    @reactive.effect
    @reactive.event(input.d3_clear_cls)
    def _d3_clear_cls():
        ui.update_checkbox_group("d3_classes", selected=[])

    @reactive.effect
    @reactive.event(input.d3_clear_conf)
    def _d3_clear_conf():
        ui.update_checkbox_group("d3_confs", selected=[])
        ui.update_select("d3_team", selected="All teams")

    @reactive.effect
    @reactive.event(input.d3_select_similar)
    def _d3_select_similar():
        sid = input.d3_select_similar()
        if sid:
            d3_sel.set(sid)
            ui.modal_remove()
            import random
            modal_req.set((sid, random.random()))

    @reactive.calc
    def d3_filtered():
        d = d3_df.copy()
        q = (input.d3_q() or "").strip().lower()
        if q: d = d[d["name"].str.lower().str.contains(q, na=False)]
        ps = list(input.d3_positions() or [])
        if ps: d = d[d["pos"].isin(ps)]
        cs = list(input.d3_classes() or [])
        if cs: d = d[d["cls"].isin(cs)]
        xs = list(input.d3_confs() or [])
        if xs: d = d[d["conf"].isin(xs)]
        t = input.d3_team()
        if t and t != "All teams": d = d[d["team"] == t]
        lo, hi = input.d3_mpg();         d = d[(d["mpg"]         >= lo) & (d["mpg"]         <= hi)]
        lo, hi = input.d3_ppg_range();   d = d[(d["ppg"]         >= lo) & (d["ppg"]         <= hi)]
        lo, hi = input.d3_efg();         d = d[(d["efg"]         >= lo) & (d["efg"]         <= hi)]
        lo, hi = input.d3_tp_range();    d = d[(d["tp"]          >= lo) & (d["tp"]          <= hi)]
        lo, hi = input.d3_three_share(); d = d[(d["three_share"]  >= lo) & (d["three_share"]  <= hi)]
        lo, hi = input.d3_apg_range();   d = d[(d["apg"]         >= lo) & (d["apg"]         <= hi)]
        lo, hi = input.d3_ast_tov();     d = d[(d["ast_tov"]     >= lo) & (d["ast_tov"]     <= hi)]
        lo, hi = input.d3_height();      d = d[(d["heightIn"]    >= lo) & (d["heightIn"]    <= hi)]
        return d

    @reactive.calc
    def d3_plot_df():
        ids = set(d3_filtered()["id"])
        sid = d3_sel.get()
        if sid: ids.add(sid)
        return d3_df[d3_df["id"].isin(ids)]

    @output
    @render.text
    def d3_filter_count():
        return f"{len(d3_filtered())} / {D3_TOTAL}"

    @output
    @render.ui
    def d3_legend_ui():
        return ui.HTML(legend_html(d3_dim.get()))

    @output
    @render.ui
    def d3_plot_meta():
        sid = d3_sel.get()
        if sid is not None:
            row = d3_df[d3_df["id"] == sid]
            if not row.empty:
                return ui.div(ui.HTML(f'<span class="accent">●</span> {row.iloc[0]["name"]} selected'), class_="plot-meta")
        return ui.div("Hover a dot for details · click to expand", class_="plot-meta")

    @render_widget
    def d3_scatter():
        return d3_fig

    @reactive.effect
    def _d3_sync():
        traces = build_traces(d3_plot_df(), d3_sel.get(), d3_dim.get())
        layout = build_layout(d3_plot_df())
        with d3_fig.batch_update():
            d3_fig.data = []
            for t in traces: d3_fig.add_trace(t)
            d3_fig.update_layout(layout)
        for trace in d3_fig.data:
            if hasattr(trace, "customdata") and trace.customdata is not None and len(trace.customdata):
                trace.on_click(_d3_clicked)

    def _d3_clicked(trace, points, selector):
        if not points or not points.point_inds: return
        cd = trace.customdata[points.point_inds[0]]
        if cd is not None and len(cd) >= 8:
            import random
            d3_sel.set(str(cd[7]))
            modal_req.set((str(cd[7]), random.random()))

    @output
    @render.ui
    def d3_modal_trigger():
        return ui.div()

    # ═══════════════════════════════════════════════════════════════════════
    # ARCHETYPE BETA DASHBOARDS
    # ═══════════════════════════════════════════════════════════════════════

    def arch_filtered(prefix, df):
        d = df.copy()
        q = (getattr(input, f"{prefix}_q")() or "").strip().lower()
        if q:
            d = d[d["name"].str.lower().str.contains(q, na=False)]
        archs = list(getattr(input, f"{prefix}_archetypes")() or [])
        if archs:
            d = d[d["primary_archetype"].isin(archs)]
        ps = list(getattr(input, f"{prefix}_positions")() or [])
        if ps:
            d = d[d["pos"].isin(ps)]
        cs = list(getattr(input, f"{prefix}_classes")() or [])
        if cs:
            d = d[d["cls"].isin(cs)]
        xs = list(getattr(input, f"{prefix}_confs")() or [])
        if xs:
            d = d[d["conf"].isin(xs)]
        t = getattr(input, f"{prefix}_team")()
        if t and t != "All teams":
            d = d[d["team"] == t]
        lo, hi = getattr(input, f"{prefix}_score")()
        d = d[(d["primary_score"] >= lo) & (d["primary_score"] <= hi)]
        lo, hi = getattr(input, f"{prefix}_tp_range")()
        d = d[(d["tp"] >= lo) & (d["tp"] <= hi)]
        lo, hi = getattr(input, f"{prefix}_three_share")()
        d = d[(d["three_share"] >= lo) & (d["three_share"] <= hi)]
        lo, hi = getattr(input, f"{prefix}_ast_tov")()
        d = d[(d["ast_tov"] >= lo) & (d["ast_tov"] <= hi)]
        lo, hi = getattr(input, f"{prefix}_height")()
        d = d[(d["heightIn"] >= lo) & (d["heightIn"] <= hi)]
        return d

    @reactive.effect
    @reactive.event(input.a1_clear_arch)
    def _a1_clear_arch():
        ui.update_checkbox_group("a1_archetypes", selected=[])

    @reactive.effect
    @reactive.event(input.a1_clear_pos)
    def _a1_clear_pos():
        ui.update_checkbox_group("a1_positions", selected=[])

    @reactive.effect
    @reactive.event(input.a1_clear_cls)
    def _a1_clear_cls():
        ui.update_checkbox_group("a1_classes", selected=[])

    @reactive.effect
    @reactive.event(input.a1_clear_conf)
    def _a1_clear_conf():
        ui.update_checkbox_group("a1_confs", selected=[])
        ui.update_select("a1_team", selected="All teams")

    @reactive.calc
    def a1_filtered():
        return arch_filtered("a1", d1_df)

    @output
    @render.text
    def a1_filter_count():
        return f"{len(a1_filtered())} / {D1_TOTAL}"

    @output
    @render.ui
    def a1_legend_ui():
        return ui.HTML(arch_legend_html(a1_dim.get()))

    @output
    @render.ui
    def a1_plot_meta():
        return ui.div("PC1 = size vs creator traits · PC2 = shooting / spacing", class_="plot-meta")

    @render_widget
    def a1_scatter():
        return a1_fig

    @reactive.effect
    def _a1_sync():
        with a1_fig.batch_update():
            a1_fig.data = []
            for t in build_arch_traces(a1_filtered(), a1_dim.get()):
                a1_fig.add_trace(t)
            a1_fig.update_layout(build_arch_layout(a1_filtered()))

    @reactive.effect
    @reactive.event(input.a2_clear_arch)
    def _a2_clear_arch():
        ui.update_checkbox_group("a2_archetypes", selected=[])

    @reactive.effect
    @reactive.event(input.a2_clear_pos)
    def _a2_clear_pos():
        ui.update_checkbox_group("a2_positions", selected=[])

    @reactive.effect
    @reactive.event(input.a2_clear_cls)
    def _a2_clear_cls():
        ui.update_checkbox_group("a2_classes", selected=[])

    @reactive.effect
    @reactive.event(input.a2_clear_conf)
    def _a2_clear_conf():
        ui.update_checkbox_group("a2_confs", selected=[])
        ui.update_select("a2_team", selected="All teams")

    @reactive.calc
    def a2_filtered():
        return arch_filtered("a2", d2_df)

    @output
    @render.text
    def a2_filter_count():
        return f"{len(a2_filtered())} / {D2_TOTAL}"

    @output
    @render.ui
    def a2_legend_ui():
        return ui.HTML(arch_legend_html(a2_dim.get()))

    @output
    @render.ui
    def a2_plot_meta():
        return ui.div("PC1 = size vs creator traits · PC2 = shooting / spacing", class_="plot-meta")

    @render_widget
    def a2_scatter():
        return a2_fig

    @reactive.effect
    def _a2_sync():
        with a2_fig.batch_update():
            a2_fig.data = []
            for t in build_arch_traces(a2_filtered(), a2_dim.get()):
                a2_fig.add_trace(t)
            a2_fig.update_layout(build_arch_layout(a2_filtered()))

    @reactive.effect
    @reactive.event(input.a3_clear_arch)
    def _a3_clear_arch():
        ui.update_checkbox_group("a3_archetypes", selected=[])

    @reactive.effect
    @reactive.event(input.a3_clear_pos)
    def _a3_clear_pos():
        ui.update_checkbox_group("a3_positions", selected=[])

    @reactive.effect
    @reactive.event(input.a3_clear_cls)
    def _a3_clear_cls():
        ui.update_checkbox_group("a3_classes", selected=[])

    @reactive.effect
    @reactive.event(input.a3_clear_conf)
    def _a3_clear_conf():
        ui.update_checkbox_group("a3_confs", selected=[])
        ui.update_select("a3_team", selected="All teams")

    @reactive.calc
    def a3_filtered():
        return arch_filtered("a3", d3_df)

    @output
    @render.text
    def a3_filter_count():
        return f"{len(a3_filtered())} / {D3_TOTAL}"

    @output
    @render.ui
    def a3_legend_ui():
        return ui.HTML(arch_legend_html(a3_dim.get()))

    @output
    @render.ui
    def a3_plot_meta():
        return ui.div("PC1 = size vs creator traits · PC2 = shooting / spacing", class_="plot-meta")

    @render_widget
    def a3_scatter():
        return a3_fig

    @reactive.effect
    def _a3_sync():
        with a3_fig.batch_update():
            a3_fig.data = []
            for t in build_arch_traces(a3_filtered(), a3_dim.get()):
                a3_fig.add_trace(t)
            a3_fig.update_layout(build_arch_layout(a3_filtered()))

    # ═══════════════════════════════════════════════════════════════════════
    # WATCHLIST
    # ═══════════════════════════════════════════════════════════════════════

    @output
    @render.text
    def wl_count():
        n = len(watchlist.get())
        return f"{n} player{'s' if n != 1 else ''}"

    def sync_radar_player_slots():
        available = [pid for pid, *_ in watchlist_rows(watchlist.get())]
        selected = []
        for pid in (input.wl_radar_player_1(), input.wl_radar_player_2()):
            if pid and pid in available and pid not in selected:
                selected.append(pid)
        radar_selected.set(selected[:2])

    @reactive.effect
    @reactive.event(input.wl_radar_player_1)
    def _wl_radar_player_1_changed():
        sync_radar_player_slots()

    @reactive.effect
    @reactive.event(input.wl_radar_player_2)
    def _wl_radar_player_2_changed():
        sync_radar_player_slots()

    @reactive.effect
    @reactive.event(input.wl_radar_stats)
    def _wl_radar_stats_changed():
        selected = [
            key for key in list(input.wl_radar_stats() or [])
            if key in RADAR_STAT_LOOKUP
        ]
        radar_stat_selected.set(selected)

    @output
    @render.ui
    def wl_radar_picker():
        rows = watchlist_rows(watchlist.get())
        if not rows:
            return ui.div({"class": "wl-radar-picker"})

        selected = [pid for pid in radar_selected.get() if pid in {row[0] for row in rows}][:2]
        player_choices = {
            "": "Select player...",
            **{
                pid: f"{r['name']} · {div_}"
                for pid, r, _df, div_ in rows
            },
        }
        stat_selected = [
            key for key in radar_stat_selected.get()
            if key in RADAR_STAT_LOOKUP
        ]
        stat_choices = {
            key: label
            for key, label, _col, _short_label, _fmt in RADAR_STATS
        }
        return ui.div(
            {"class": "wl-radar-picker"},
            ui.div(
                {"class": "wl-radar-field"},
                ui.div("Player 1", class_="wl-radar-field-title"),
                ui.input_selectize(
                    "wl_radar_player_1",
                    None,
                    choices=player_choices,
                    selected=selected[0] if len(selected) >= 1 else "",
                    options={
                        "placeholder": "Search player 1...",
                    },
                ),
            ),
            ui.div(
                {"class": "wl-radar-field"},
                ui.div("Player 2", class_="wl-radar-field-title"),
                ui.input_selectize(
                    "wl_radar_player_2",
                    None,
                    choices=player_choices,
                    selected=selected[1] if len(selected) >= 2 else "",
                    options={
                        "placeholder": "Search player 2...",
                    },
                ),
            ),
            ui.div(
                {"class": "wl-radar-field wl-radar-stat-checks"},
                ui.div("Stats", class_="wl-radar-field-title"),
                ui.input_checkbox_group(
                    "wl_radar_stats",
                    None,
                    choices=stat_choices,
                    selected=stat_selected,
                ),
            ),
        )

    @output
    @render.ui
    def watchlist_ui():
        wl = watchlist.get()
        if not wl:
            return ui.div(
                ui.tags.script("var b=document.getElementById('wl-badge');if(b){b.style.display='none';}"),
                ui.div({"class": "wl-empty"},
                       ui.div("☆", class_="wl-star"),
                       ui.div("No players starred yet."),
                       ui.div("Open any player profile and click ☆ to add them here.",
                              style="color:var(--ink-3);max-width:280px;text-align:center;line-height:1.5")))

        cards = []
        for pid in wl:
            if pid.startswith("d1"):
                df_, div_ = d1_df, "D-I"
            elif pid.startswith("d3"):
                df_, div_ = d3_df, "D-III"
            else:
                df_, div_ = d2_df, "D-II"
            row_ = df_[df_["id"] == pid]
            if row_.empty:
                continue
            r   = row_.iloc[0]
            pc_ = POS_COLOR.get(r["pos"], "#888")
            open_js = f"Shiny.setInputValue('wl_open_player','{pid}',{{priority:'event'}})"
            cards.append(
                ui.div(
                    {"class": "wl-card", "onclick": open_js},
                    ui.tags.button(
                        {"class": "wl-remove",
                         "title": "Remove from watchlist",
                         "onclick": f"event.stopPropagation();Shiny.setInputValue('toggle_watchlist','{pid}',{{priority:'event'}})"},
                        "★"),
                    ui.div(r["name"], class_="wl-card-name"),
                    ui.div(
                        ui.span(r["pos"], class_="pos-badge",
                                style=f"color:{pc_};border-color:{pc_}"),
                        ui.span(r["team"]),
                        ui.span(f"· {r['cls']} · {div_}", style="color:var(--ink-3)"),
                        class_="wl-card-meta"),
                    ui.div({"class": "wl-card-stats"},
                           ui.div(ui.div(f"{r['ppg']:.1f}", class_="n"),
                                  ui.div("PPG", class_="l"), class_="wl-stat"),
                           ui.div(ui.div(f"{r['rpg']:.1f}", class_="n"),
                                  ui.div("RPG", class_="l"), class_="wl-stat"),
                           ui.div(ui.div(f"{r['apg']:.1f}", class_="n"),
                                  ui.div("APG", class_="l"), class_="wl-stat"),
                           ui.div(ui.div(f"{r['fg']*100:.0f}%", class_="n"),
                                  ui.div("FG%", class_="l"), class_="wl-stat")),
                ))

        n   = len(wl)
        vis = "inline-block" if n else "none"
        js  = f"var b=document.getElementById('wl-badge');if(b){{b.textContent='{n}';b.style.display='{vis}';}}"
        return ui.div(
            ui.tags.script(js),
            ui.div({"class": "wl-grid"}, *cards))

    @output
    @render_widget
    def watchlist_radar():
        selected = [pid for pid in radar_selected.get() if pid in watchlist.get()][:2]
        stats = [key for key in radar_stat_selected.get() if key in RADAR_STAT_LOOKUP]
        return make_watchlist_radar(selected, stats)


app = App(app_ui, server, static_assets=HERE / "www")
