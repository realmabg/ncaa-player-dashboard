from shiny import App, ui, reactive, render
import asttokens  # noqa: F401 - direct import lets Shinylive install this transitive dependency.
from shinywidgets import output_widget, render_widget
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from os import environ
from pathlib import Path
import html
import json
import math
import re

from data_engine import (
    load_data,
    POS_COLOR, POS_LABEL, POSITIONS, CLASSES, height_str,
)
from pages.division_i.core_v3 import score_current_players
from pages.division_i.data import load_division_i
from pages.division_i.view import make_division_i_tab, snapshot_note
from pages.historical_players.data import (
    load_historical_neighbors, load_historical_player_index, load_historical_scores,
)
from pages.historical_players.view import make_historical_beta_tab
from pages.triton_zone.scoring import (
    TRITON_DEFAULT_WEIGHTS, TRITON_SPECIAL_ARCHETYPES, TRITON_SPECIAL_CRITERIA,
    TRITON_ZONE_METRICS, add_triton_columns, build_triton_spreads,
    compute_triton_frame, compute_triton_special,
)
from pages.triton_zone.view import make_triton_tab
from ratings.page.ratings_tab import CSV_URL as RATINGS_CSV_URL, ratings_tab_server, ratings_tab_ui
from ratings.projections.player_projections import lineup_forecast_payload

HERE = Path(__file__).parent
D1_PREVIEW_SNAPSHOT = environ.get("D1_PREVIEW_SNAPSHOT")
D1_CURRENT_SEASON = 2027 if D1_PREVIEW_SNAPSHOT else 2026
D1_SEASON_LABEL = f"{D1_CURRENT_SEASON - 1}–{D1_CURRENT_SEASON % 100:02}"
BUNDLED_CURRENT_D2_SCHEMA_PATH = HERE / "current_d2_all_players_10mpg_dashboard_schema.csv"
D2_SCHEMA_RELATIVE_PATH = (
    Path("former_D2_player_comparison")
    / "transfer"
    / "current_d2_website_method_bundle"
    / "data"
    / "current_d2_all_players_10mpg_dashboard_schema.csv"
)
LEGACY_D2_PATH = HERE / "d2_data_cleaned.csv"
CORE_V3_MEMBERSHIPS_PATH = HERE / "core_v3_memberships.csv"
CORE_V3_UNSTABLE_PATH = HERE / f"core_v3_under150_unstable_scores_{D1_CURRENT_SEASON}.csv"
HISTORICAL_TABLE_LIMIT = 25
HISTORICAL_CURRENT_COMP_LIMIT = 5
HISTORICAL_CURRENT_COMP_MIN_MPG = 10.0
HISTORICAL_BETA_ARCHETYPES = ["PG / Combo", "2-4 Wing", "F/C Stretch"]
TRITON_TRACKER_DEFAULT_IDEALS = [
    {"player_name": "Hayden Gray", "team": "UC San Diego", "year": 2025},
    {"player_name": "Aniwaniwa Tait-Jones", "team": "UC San Diego", "year": 2025},
    {"player_name": "Tyler McGhie", "team": "UC San Diego", "year": 2025},
]
SIMILARITY_BETA_MOVEMENT = [
    [1, 0, -2, 2, -1],
    [0, 2, -1, 1, 0],
    [2, -1, 0, -2, 1],
]
HISTORICAL_CURRENT_COMP_CACHE = {}
LIVE_BUILD_STAMP = "TEST BUILD 09-03-2026 · triton-tracker"


def resolve_current_d2_schema_path():
    if BUNDLED_CURRENT_D2_SCHEMA_PATH.exists():
        return BUNDLED_CURRENT_D2_SCHEMA_PATH
    for base in (HERE, *HERE.parents):
        candidate = base / D2_SCHEMA_RELATIVE_PATH
        if candidate.exists():
            return candidate
    return LEGACY_D2_PATH


def resolve_core_v3_memberships_path():
    return CORE_V3_MEMBERSHIPS_PATH if CORE_V3_MEMBERSHIPS_PATH.exists() else None


def resolve_core_v3_unstable_path():
    return CORE_V3_UNSTABLE_PATH if CORE_V3_UNSTABLE_PATH.exists() else None


D2 = load_data(
    str(resolve_current_d2_schema_path()),
    id_prefix="d2p",
    min_mpg=10,
)
D1 = load_division_i(HERE, snapshot=D1_PREVIEW_SNAPSHOT, season=D1_CURRENT_SEASON)
D3 = load_data(str(HERE / "d3_data_cleaned.csv"),          id_prefix="d3p")
HISTORICAL_NEIGHBORS = {
    "all": load_historical_neighbors(D1_CURRENT_SEASON, "all"),
    "big_west_next_year": load_historical_neighbors(D1_CURRENT_SEASON, "big_west_next_year"),
}
HISTORICAL_SCORES = load_historical_scores(D1_CURRENT_SEASON)
HISTORICAL_PLAYER_INDEX = load_historical_player_index(D1_CURRENT_SEASON)

d2_df         = D2["df"];  d2_conferences = D2["conferences"]
d2_league_avg = D2["league_avg"];  d2_similar_to = D2["similar_to"]
D2_TOTAL      = len(d2_df)

d1_df         = D1["df"];  d1_conferences = D1["conferences"]
d1_league_avg = D1["league_avg"];  d1_similar_to = D1["similar_to"]
D1_TOTAL      = len(d1_df)

d3_df         = D3["df"];  d3_conferences = D3["conferences"]
d3_league_avg = D3["league_avg"];  d3_similar_to = D3["similar_to"]
D3_TOTAL      = len(d3_df)


def build_historical_current_pool():
    current_players = d1_df.copy()
    current_players["name_key"] = current_players["name"].map(normalize_lookup_key)
    current_players["team_key"] = current_players["team"].map(normalize_lookup_key)
    current_players["team_key_robust"] = current_players["team"].map(normalize_team_lookup_key)
    for compare_key, row_key in CURRENT_TO_COMPARE_KEY.items():
        if compare_key not in current_players.columns:
            current_players[compare_key] = _as_float(np.nan)
        if row_key in current_players.columns:
            current_players[compare_key] = pd.to_numeric(current_players[row_key], errors="coerce")
    current_players["height_inches"] = pd.to_numeric(current_players.get("heightIn"), errors="coerce")
    score_cols = [f"{category_key}_score" for category_key, _label in LEGACY_SIMILARITY_SCORE_CATEGORIES]
    grade_cols = [f"{category_key}_grade" for category_key, _label in LEGACY_SIMILARITY_SCORE_CATEGORIES]
    for col in [*score_cols, *grade_cols]:
        if col not in current_players.columns:
            current_players[col] = np.nan

    if HISTORICAL_SCORES.empty:
        return current_players

    current_scores = HISTORICAL_SCORES[HISTORICAL_SCORES["year"].eq(D1_CURRENT_SEASON)].copy()
    if current_scores.empty:
        return current_players
    current_scores["name_key"] = current_scores["player_name"].map(normalize_lookup_key)
    current_scores["team_key"] = current_scores["team"].map(normalize_lookup_key)
    current_scores["team_key_robust"] = current_scores["team"].map(normalize_team_lookup_key)

    keep_cols = ["name_key", "team_key", "team_key_robust", *score_cols, *grade_cols]
    merged = current_players.merge(
        current_scores[keep_cols],
        on=["name_key", "team_key", "team_key_robust"],
        how="left",
        suffixes=("", "_historical"),
    )
    for col in [*score_cols, *grade_cols]:
        historical_col = f"{col}_historical"
        if historical_col not in merged.columns:
            continue
        merged[col] = merged[historical_col].combine_first(merged[col])
        merged = merged.drop(columns=[historical_col])
    return merged

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
ARCHETYPE_SHORT_LABEL = {
    "PG / Combo Guard": "PG / Combo",
    "2-4 Interchangeable Wing": "2-4 Wing",
    "5 / Stretch 4 / Big Wing": "F/C Stretch",
}
ARCHETYPE_V2_LABELS = {
    "A0": "Perimeter Spacer",
    "A1": "Connecting Guard",
    "A2": "Low-Production Player",
    "A3": "Two-Way Guard",
    "A4": "Scoring Playmaker",
    "A5": "Efficient Play Finisher",
    "A6": "Two-Way Forward",
    "A7": "Traditional Big",
}
ARCHETYPE_V2_ORDER = list(ARCHETYPE_V2_LABELS)
QUALIFICATION_FILTERS = {
    "none": "None",
    "general": "General Player",
    "pg": "PG / Combo Guard",
    "wing": "2-4 Interchangeable Wing",
    "big": "5 / Stretch 4 / Big Wing",
}
QUALIFICATION_FILTER_COLUMNS = {
    "general": "qual_general",
    "pg": "qual_pg_combo",
    "wing": "qual_wing_2_4",
    "big": "qual_stretch_big",
}
TRANSFER_TAG_FILTERS = {
    "transfer_available": "Available transfer",
}
RECRUITING_TAG_FILTERS = {
    "former_247_top_100": "Former 247 Composite Top 100",
    "former_247_top_150": "Former 247 Composite Top 150",
    "former_rivals_top_100": "Former Rivals Industry Top 100",
    "former_rivals_ranked": "Former Rivals Industry Ranked",
    "former_ranked_hs_prospect": "Any former ranked HS prospect",
}
TAG_FILTERS = {**TRANSFER_TAG_FILTERS, **RECRUITING_TAG_FILTERS}
ELIGIBILITY_OPTIONS = {
    1: "1 year used",
    2: "2 years used",
    3: "3 years used",
    4: "4 years used",
    5: "5 years used",
}
QUALIFICATION_CONFIG = {
    "thresholds": {
        "general": {
            "ast_pctile": 70,
            "efg": 0.500,
            "three_pct": 0.300,
            "ast_tov_pctile": 50,
            "guard_dreb_raw": 10,
            "nonguard_dreb_raw": 15,
            "exception_ast_pctile": 85,
            "exception_dreb_pctile": 85,
        },
        "pg": {
            "ast_pctile": 70,
            "ast_tov_pctile": 70,
            "three_pct": 0.330,
            "three_rate": 0.300,
            "exception_two_pct_pctile": 70,
        },
        "wing": {
            "dreb_pctile": 70,
            "three_pct": 0.330,
            "three_rate": 0.300,
            "ast_tov_pctile": 50,
        },
        "big": {
            "height": 79,
            "position": "F/C",
            "dreb_pctile": 70,
            "three_pct": 0.300,
            "three_rate": 0.250,
            "ast_tov_pctile": 50,
        },
    },
    "weights": {
        "pg": {
            "AST_pct_pctile": 0.30,
            "AST_TOV_pctile": 0.30,
            "three_profile_pg_pctile": 0.20,
            "2P_pct_pctile": 0.20,
        },
        "wing": {
            "DRB_pct_pctile": 0.30,
            "eFG_pctile": 0.25,
            "three_profile_wing_pctile": 0.25,
            "AST_TOV_pctile": 0.20,
        },
        "big": {
            "DRB_pct_pctile": 0.40,
            "three_profile_big_pctile": 0.20,
            "eFG_pctile": 0.20,
            "AST_TOV_pctile": 0.20,
        },
    },
}
ARCHETYPE_PCA_FEATURES = [
    "pts_per_40",
    "ts",
    "three_share",
    "ftr",
    "ast_per_40",
    "ast_tov",
    "tov_per_40",
    "orb",
    "drb",
    "stl_per_40",
    "blk_per_40",
    "heightIn",
]


def normalize_lookup_key(value):
    return str(value or "").strip().lower()


def normalize_team_lookup_key(value):
    key = normalize_lookup_key(value)
    key = key.replace("&", " and ")
    key = key.replace("'", "")
    key = re.sub(r"[^a-z0-9]+", " ", key)
    key = re.sub(r"\bsaint\b", "st", key)
    key = re.sub(r"\bstate\b", "st", key)
    key = re.sub(r"\bcalifornia\b", "cal", key)
    key = re.sub(r"\buniversity\b", "u", key)
    key = re.sub(r"\bnorth carolina\b", "nc", key)
    key = re.sub(r"\bsouth carolina\b", "sc", key)
    key = re.sub(r"\btexas a and m\b", "texas am", key)
    key = re.sub(r"\btexas a m\b", "texas am", key)
    key = re.sub(r"\bst\b", "st", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def add_archetype_v2_columns(df):
    memberships_path = resolve_core_v3_memberships_path()
    unstable_path = resolve_core_v3_unstable_path()
    target_columns = [
        *ARCHETYPE_V2_ORDER,
        "archetype_v2_primary_code",
        "archetype_v2_primary_label",
        "archetype_v2_primary_weight",
        "archetype_v2_secondary_code",
        "archetype_v2_secondary_label",
        "archetype_v2_secondary_weight",
        "archetype_v2_available",
        "archetype_v2_unstable",
        "archetype_v2_stability_tier",
        "archetype_v2_stability_note",
    ]

    def finalize_membership_frame(frame, unstable_default=False):
        weight_frame = frame[ARCHETYPE_V2_ORDER].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        frame[ARCHETYPE_V2_ORDER] = weight_frame
        frame["archetype_v2_primary_code"] = weight_frame.idxmax(axis=1)
        frame["archetype_v2_primary_weight"] = weight_frame.max(axis=1)

        def secondary_code(row):
            ordered = row.sort_values(ascending=False)
            return ordered.index[1] if len(ordered.index) > 1 else ordered.index[0]

        frame["archetype_v2_secondary_code"] = weight_frame.apply(secondary_code, axis=1)
        frame["archetype_v2_secondary_weight"] = [
            float(weight_frame.loc[idx, code])
            for idx, code in zip(weight_frame.index, frame["archetype_v2_secondary_code"])
        ]
        frame["archetype_v2_primary_label"] = frame["archetype_v2_primary_code"].map(ARCHETYPE_V2_LABELS)
        frame["archetype_v2_secondary_label"] = frame["archetype_v2_secondary_code"].map(ARCHETYPE_V2_LABELS)
        frame["archetype_v2_available"] = frame["archetype_v2_primary_code"].notna()
        if "archetype_v2_unstable" not in frame.columns:
            frame["archetype_v2_unstable"] = unstable_default
        frame["archetype_v2_unstable"] = frame["archetype_v2_unstable"].fillna(unstable_default).astype(bool)
        if "archetype_v2_stability_tier" not in frame.columns:
            frame["archetype_v2_stability_tier"] = pd.Series(pd.NA, index=frame.index, dtype="object")
        if "archetype_v2_stability_note" not in frame.columns:
            frame["archetype_v2_stability_note"] = pd.Series(pd.NA, index=frame.index, dtype="object")
        return frame

    if D1_PREVIEW_SNAPSHOT:
        current = finalize_membership_frame(score_current_players(df))
        for col in target_columns:
            df[col] = current[col].reindex(df.index)
        for col in ("archetype_v2_available", "archetype_v2_unstable"):
            df[col] = df[col].eq(True)
        return

    if memberships_path is None:
        for col in ARCHETYPE_V2_ORDER:
            df[col] = np.nan
        df["archetype_v2_primary_code"] = pd.Series(pd.NA, index=df.index, dtype="object")
        df["archetype_v2_primary_label"] = pd.Series(pd.NA, index=df.index, dtype="object")
        df["archetype_v2_primary_weight"] = pd.Series(np.nan, index=df.index, dtype="float64")
        df["archetype_v2_secondary_code"] = pd.Series(pd.NA, index=df.index, dtype="object")
        df["archetype_v2_secondary_label"] = pd.Series(pd.NA, index=df.index, dtype="object")
        df["archetype_v2_secondary_weight"] = pd.Series(np.nan, index=df.index, dtype="float64")
        df["archetype_v2_available"] = pd.Series(False, index=df.index, dtype="bool")
        df["archetype_v2_unstable"] = pd.Series(False, index=df.index, dtype="bool")
        df["archetype_v2_stability_tier"] = pd.Series(pd.NA, index=df.index, dtype="object")
        df["archetype_v2_stability_note"] = pd.Series(pd.NA, index=df.index, dtype="object")
        return

    memberships = pd.read_csv(memberships_path)
    memberships["name_key"] = memberships["playerName"].map(normalize_lookup_key)
    memberships["team_key"] = memberships["teamName"].map(normalize_lookup_key)
    memberships["team_key_robust"] = memberships["teamName"].map(normalize_team_lookup_key)
    memberships["minutes"] = pd.to_numeric(memberships["minutes"], errors="coerce").fillna(0)
    memberships = memberships.sort_values("minutes", ascending=False)
    memberships = memberships.drop_duplicates(["name_key", "team_key"], keep="first").copy()

    memberships = finalize_membership_frame(memberships, unstable_default=False)

    if unstable_path is not None:
        unstable = pd.read_csv(unstable_path)
        unstable["name_key"] = unstable["playerName"].map(normalize_lookup_key)
        unstable["team_key"] = unstable["teamName"].map(normalize_lookup_key)
        unstable["team_key_robust"] = unstable["teamName"].map(normalize_team_lookup_key)
        unstable["minutes"] = pd.to_numeric(unstable["minutes"], errors="coerce").fillna(0)
        unstable["archetype_v2_unstable"] = unstable["unstableArchetypeFlag"]
        unstable["archetype_v2_stability_tier"] = unstable["stabilityTier"]
        unstable["archetype_v2_stability_note"] = unstable["stabilityNote"]
        unstable = unstable.sort_values("minutes", ascending=False)
        unstable = unstable.drop_duplicates(["name_key", "team_key"], keep="first").copy()
        unstable = finalize_membership_frame(unstable, unstable_default=True)
        memberships = pd.concat([memberships, unstable], ignore_index=True, sort=False)
        memberships = memberships.sort_values(
            ["archetype_v2_unstable", "minutes"],
            ascending=[True, False],
        )
        memberships = memberships.drop_duplicates(["name_key", "team_key"], keep="first").copy()

    memberships_robust = memberships.drop_duplicates(
        ["name_key", "team_key_robust"], keep="first"
    ).copy()

    merge_cols = [
        "name_key",
        "team_key",
        "team_key_robust",
        *target_columns,
    ]
    memberships = memberships[merge_cols]
    memberships_robust = memberships_robust[merge_cols]

    lookup_df = df[["name", "team"]].copy()
    lookup_df["name_key"] = lookup_df["name"].map(normalize_lookup_key)
    lookup_df["team_key"] = lookup_df["team"].map(normalize_lookup_key)
    lookup_df["team_key_robust"] = lookup_df["team"].map(normalize_team_lookup_key)

    merged = lookup_df.merge(memberships, on=["name_key", "team_key"], how="left")
    missing_mask = merged["archetype_v2_primary_code"].isna()
    if missing_mask.any():
        fallback = lookup_df.loc[missing_mask, ["name_key", "team_key_robust"]].merge(
            memberships_robust.drop(columns=["team_key"]),
            on=["name_key", "team_key_robust"],
            how="left",
        )
        fallback.index = merged.index[missing_mask]
        for col in target_columns:
            merged.loc[missing_mask, col] = merged.loc[missing_mask, col].fillna(fallback[col])

    for col in ARCHETYPE_V2_ORDER:
        df[col] = pd.to_numeric(merged[col], errors="coerce")
    df["archetype_v2_primary_code"] = merged["archetype_v2_primary_code"]
    df["archetype_v2_primary_label"] = merged["archetype_v2_primary_label"]
    df["archetype_v2_primary_weight"] = pd.to_numeric(merged["archetype_v2_primary_weight"], errors="coerce")
    df["archetype_v2_secondary_code"] = merged["archetype_v2_secondary_code"]
    df["archetype_v2_secondary_label"] = merged["archetype_v2_secondary_label"]
    df["archetype_v2_secondary_weight"] = pd.to_numeric(merged["archetype_v2_secondary_weight"], errors="coerce")
    df["archetype_v2_available"] = merged["archetype_v2_available"].fillna(False).astype(bool)
    df["archetype_v2_unstable"] = merged["archetype_v2_unstable"].fillna(False).astype(bool)
    df["archetype_v2_stability_tier"] = merged["archetype_v2_stability_tier"]
    df["archetype_v2_stability_note"] = merged["archetype_v2_stability_note"]


def archetype_v2_label(value):
    return ARCHETYPE_V2_LABELS.get(value, value)


def format_weight_pct(value):
    value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "N/A"
    return f"{value * 100:.1f}%"


def pct_display(value):
    value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "N/A"
    return f"{value * 100:.1f}%"


def make_shot_profile_pie_html(row, player_id):
    rim_made = float(pd.to_numeric(pd.Series([row.get("rim_made_total", 0)]), errors="coerce").iloc[0] or 0)
    three_made = float(pd.to_numeric(pd.Series([row.get("pbp_three_made", 0)]), errors="coerce").iloc[0] or 0)
    mid_made = float(pd.to_numeric(pd.Series([row.get("pbp_mid_made", 0)]), errors="coerce").iloc[0] or 0)
    rim_attempts = float(pd.to_numeric(pd.Series([row.get("rim_attempts_total", 0)]), errors="coerce").iloc[0] or 0)
    mid_attempts = float(pd.to_numeric(pd.Series([row.get("mid_attempts_total", 0)]), errors="coerce").iloc[0] or 0)
    three_attempts = (
        float(pd.to_numeric(pd.Series([row.get("pbp_three_made", 0)]), errors="coerce").iloc[0] or 0)
        + float(pd.to_numeric(pd.Series([row.get("pbp_three_missed", 0)]), errors="coerce").iloc[0] or 0)
    )
    total_attempts = rim_attempts + mid_attempts + three_attempts
    if total_attempts <= 0:
        return ui.div("No FGA.", class_="qual-note")

    def shot_slice_color(label, fg_pct):
        thresholds = {
            "RIM": (0.60, 0.50),
            "3PT": (0.37, 0.32),
            "MID": (0.42, 0.36),
        }
        strong_cutoff, medium_cutoff = thresholds.get(label, (0.50, 0.35))
        if fg_pct >= strong_cutoff:
            return "#2f855a"
        if fg_pct >= medium_cutoff:
            return "#d5a437"
        return "#b95c5c"

    ordered_rows = [
        {
            "label": "RIM",
            "share_pct": (rim_attempts / total_attempts) * 100,
            "fg_pct": float(pd.to_numeric(pd.Series([row.get("rim_fg_pct", 0)]), errors="coerce").iloc[0] or 0),
            "assist_pct": float(pd.to_numeric(pd.Series([row.get("rim_assisted_pct", 0)]), errors="coerce").iloc[0] or 0),
        },
        {
            "label": "3PT",
            "share_pct": (three_attempts / total_attempts) * 100,
            "fg_pct": float(pd.to_numeric(pd.Series([row.get("tp", 0)]), errors="coerce").iloc[0] or 0),
            "assist_pct": float(pd.to_numeric(pd.Series([row.get("three_assisted_pct", 0)]), errors="coerce").iloc[0] or 0),
        },
        {
            "label": "MID",
            "share_pct": (mid_attempts / total_attempts) * 100,
            "fg_pct": float(pd.to_numeric(pd.Series([row.get("mid_fg_pct", 0)]), errors="coerce").iloc[0] or 0),
            "assist_pct": float(pd.to_numeric(pd.Series([row.get("mid_assisted_pct", 0)]), errors="coerce").iloc[0] or 0),
        },
    ]
    segments = [segment for segment in ordered_rows if segment["share_pct"] > 0.05]

    size_w = 280
    size_h = 240
    cx = 140
    cy = 120
    radius = 92
    inside_label_threshold = 8.0

    def polar(angle_deg, r):
        angle = math.radians(angle_deg - 90)
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    def slice_path(start_deg, end_deg):
        start_x, start_y = polar(end_deg, radius)
        end_x, end_y = polar(start_deg, radius)
        large_arc = 1 if (end_deg - start_deg) > 180 else 0
        return (
            f"M {cx:.2f} {cy:.2f} "
            f"L {start_x:.2f} {start_y:.2f} "
            f"A {radius:.2f} {radius:.2f} 0 {large_arc} 0 {end_x:.2f} {end_y:.2f} Z"
        )

    rim_segment = next((segment for segment in segments if segment["label"] == "RIM"), None)
    start_angle = -(rim_segment["share_pct"] / 100) * 180 if rim_segment else 0
    default_readout = "Hover a slice for shot details."
    svg_parts = [
        '<div class="shot-pie-wrap" '
        'style="display:flex;flex-direction:column;gap:10px;width:100%;height:100%;min-height:220px;">',
        '<div class="shot-pie-readout" '
        'style="min-height:34px;background:#2f281d;color:#f3ead7;padding:8px 12px;border-radius:10px;'
        'font-family:var(--sans);font-size:11px;line-height:1.35;display:flex;align-items:center;'
        'justify-content:center;text-align:center;">'
        f'{html.escape(default_readout)}</div>',
        f'<svg viewBox="0 0 {size_w} {size_h}" width="100%" height="100%" '
        'style="flex:1 1 auto;min-height:0;" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Shot profile pie chart">'
    ]

    if len(segments) == 1:
        segment = segments[0]
        label = segment["label"]
        fg_pct = segment["fg_pct"]
        assist_pct = segment["assist_pct"]
        hover = (
            f"{label} · 100.0% of FGA · "
            f"{fg_pct * 100:.1f}% FG · {assist_pct * 100:.1f}% assisted"
        )
        hover_attr = html.escape(hover, quote=True)
        svg_parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{shot_slice_color(label, fg_pct)}" '
            'stroke="#f4ead4" stroke-width="2" '
            f'data-tip="{hover_attr}" '
            'onmousemove="const wrap=this.closest(\'.shot-pie-wrap\');'
            'const readout=wrap&&wrap.querySelector(\'.shot-pie-readout\');'
            'if(readout){readout.textContent=this.dataset.tip;}" '
            'onmouseleave="const wrap=this.closest(\'.shot-pie-wrap\');'
            'const readout=wrap&&wrap.querySelector(\'.shot-pie-readout\');'
            f'if(readout){{readout.textContent=\'{html.escape(default_readout, quote=True)}\';}}">'
            f"<title>{html.escape(hover)}</title>"
            "</circle>"
        )
        svg_parts.append(
            f'<text x="{cx:.2f}" y="{cy:.2f}" fill="#ffffff" font-size="13" '
            'font-family="Inter, sans-serif" font-weight="700" '
            'text-anchor="middle" dominant-baseline="middle">'
            f"{html.escape(label)}</text>"
        )
        svg_parts.append("</svg></div>")
        return ui.HTML("".join(svg_parts))

    current_angle = start_angle
    for segment in segments:
        label = segment["label"]
        share_pct = segment["share_pct"]
        sweep = (share_pct / 100) * 360
        end_angle = current_angle + sweep
        path = slice_path(current_angle, end_angle)
        fg_pct = segment["fg_pct"]
        assist_pct = segment["assist_pct"]
        hover = (
            f"{label} · {share_pct:.1f}% of FGA · "
            f"{fg_pct * 100:.1f}% FG · {assist_pct * 100:.1f}% assisted"
        )
        hover_attr = html.escape(hover, quote=True)
        svg_parts.append(
            f'<path d="{path}" fill="{shot_slice_color(label, fg_pct)}" stroke="#f4ead4" stroke-width="2" '
            f'data-tip="{hover_attr}" '
            'onmousemove="const wrap=this.closest(\'.shot-pie-wrap\');'
            'const readout=wrap&&wrap.querySelector(\'.shot-pie-readout\');'
            'if(readout){readout.textContent=this.dataset.tip;}" '
            'onmouseleave="const wrap=this.closest(\'.shot-pie-wrap\');'
            'const readout=wrap&&wrap.querySelector(\'.shot-pie-readout\');'
            f'if(readout){{readout.textContent=\'{html.escape(default_readout, quote=True)}\';}}">'
            f"<title>{html.escape(hover)}</title>"
            "</path>"
        )

        mid_angle = current_angle + sweep / 2
        if share_pct >= inside_label_threshold:
            tx, ty = polar(mid_angle, radius * 0.58)
            svg_parts.append(
                f'<text x="{tx:.2f}" y="{ty:.2f}" fill="#ffffff" font-size="13" '
                'font-family="Inter, sans-serif" font-weight="700" '
                'text-anchor="middle" dominant-baseline="middle">'
                f"{html.escape(label)}</text>"
            )
        else:
            inner_x, inner_y = polar(mid_angle, radius * 1.04)
            callout_x_raw, callout_y = polar(mid_angle, radius * 1.22)
            direction = 1 if callout_x_raw >= cx else -1
            callout_x = max(32, min(248, callout_x_raw + (direction * 14)))
            anchor = "start" if direction > 0 else "end"
            svg_parts.append(
                f'<path d="M {inner_x:.2f} {inner_y:.2f} L {callout_x:.2f} {callout_y:.2f}" '
                'stroke="#f4ead4" stroke-width="1.5" fill="none" />'
            )
            svg_parts.append(
                f'<text x="{callout_x:.2f}" y="{callout_y:.2f}" fill="#ffffff" font-size="12" '
                'font-family="Inter, sans-serif" font-weight="700" '
                f'text-anchor="{anchor}" dominant-baseline="middle">{html.escape(label)}</text>'
            )
        current_angle = end_angle

    svg_parts.append("</svg></div>")
    return ui.HTML("".join(svg_parts))


add_archetype_v2_columns(d1_df)


def add_archetype_columns(dfs):
    frames = []
    for div, df in dfs:
        tmp = df.copy()
        tmp["_arch_division"] = div
        frames.append(tmp)
    all_df = pd.concat(frames, ignore_index=True)

    def pct(group_cols, col):
        return all_df.groupby(group_cols)[col].rank(pct=True, method="average") * 100

    all_df["AST_pct_pctile"] = pct("_arch_division", "assist_creation")
    all_df["3P_pct_pctile"] = pct("_arch_division", "tp")
    all_df["3P_rate_pctile"] = pct("_arch_division", "three_share")
    all_df["AST_TOV_pctile"] = pct("_arch_division", "ast_tov")
    all_df["eFG_pctile"] = pct("_arch_division", "efg")
    all_df["DRB_pct_pctile"] = pct("_arch_division", "dreb_arch")
    all_df["2P_pct_pctile"] = pct("_arch_division", "two_pct")
    all_df["pct_assist_creation"] = all_df["AST_pct_pctile"]
    all_df["pct_three_pct"] = all_df["3P_pct_pctile"]
    all_df["pct_three_rate"] = all_df["3P_rate_pctile"]
    all_df["pct_ast_tov"] = all_df["AST_TOV_pctile"]
    all_df["pct_efg"] = all_df["eFG_pctile"]
    all_df["pct_dreb_pos_adj"] = pct(["_arch_division", "pos"], "dreb_arch")
    all_df["pct_size"] = pct("_arch_division", "heightIn")
    all_df["three_profile"] = (all_df["3P_pct_pctile"] + all_df["3P_rate_pctile"]) / 2

    t = QUALIFICATION_CONFIG["thresholds"]
    is_guard = all_df["pos"].isin(["G", "G/F"])
    has_true_dreb_pct = all_df["dreb_source"].eq("DRB_pct")
    dreb_raw_standard = np.where(
        has_true_dreb_pct,
        np.where(
            is_guard,
            all_df["dreb_arch"] >= t["general"]["guard_dreb_raw"],
            all_df["dreb_arch"] >= t["general"]["nonguard_dreb_raw"],
        ),
        all_df["DRB_pct_pctile"] >= t["general"]["ast_tov_pctile"],
    )

    all_df["qual_general_standard"] = (
        (all_df["AST_pct_pctile"] >= t["general"]["ast_pctile"])
        & (all_df["efg"] >= t["general"]["efg"])
        & (all_df["tp"] >= t["general"]["three_pct"])
        & (all_df["AST_TOV_pctile"] >= t["general"]["ast_tov_pctile"])
        & dreb_raw_standard
    )
    all_df["qual_general_exception"] = (
        (all_df["AST_pct_pctile"] >= t["general"]["exception_ast_pctile"])
        & (all_df["DRB_pct_pctile"] >= t["general"]["exception_dreb_pctile"])
        & (all_df["AST_TOV_pctile"] >= t["general"]["ast_tov_pctile"])
    )
    all_df["qual_general"] = all_df["qual_general_standard"] | all_df["qual_general_exception"]

    all_df["qual_pg_standard_path"] = (
        (all_df["AST_pct_pctile"] >= t["pg"]["ast_pctile"])
        & (all_df["AST_TOV_pctile"] >= t["pg"]["ast_tov_pctile"])
        & (all_df["tp"] >= t["pg"]["three_pct"])
        & (all_df["three_share"] >= t["pg"]["three_rate"])
    )
    all_df["qual_pg_exception_path"] = (
        (all_df["AST_pct_pctile"] >= t["pg"]["ast_pctile"])
        & (all_df["AST_TOV_pctile"] >= t["pg"]["ast_tov_pctile"])
        & (all_df["2P_pct_pctile"] >= t["pg"]["exception_two_pct_pctile"])
    )
    all_df["qual_pg_standard"] = all_df["qual_pg_standard_path"] & all_df["qual_general"]
    all_df["qual_pg_exception"] = all_df["qual_pg_exception_path"] & all_df["qual_general"]
    all_df["qual_pg_combo"] = all_df["qual_pg_standard"] | all_df["qual_pg_exception"]

    all_df["qual_wing_standard_path"] = (
        (all_df["DRB_pct_pctile"] >= t["wing"]["dreb_pctile"])
        & (all_df["tp"] >= t["wing"]["three_pct"])
        & (all_df["three_share"] >= t["wing"]["three_rate"])
        & (all_df["AST_TOV_pctile"] >= t["wing"]["ast_tov_pctile"])
    )
    all_df["qual_wing_standard"] = all_df["qual_wing_standard_path"] & all_df["qual_general"]
    all_df["qual_wing_2_4"] = all_df["qual_wing_standard"]

    all_df["qual_big_standard_path"] = (
        (all_df["pos"] == t["big"]["position"])
        & (all_df["heightIn"] >= t["big"]["height"])
        & (all_df["DRB_pct_pctile"] >= t["big"]["dreb_pctile"])
        & (all_df["tp"] >= t["big"]["three_pct"])
        & (all_df["three_share"] >= t["big"]["three_rate"])
        & (all_df["AST_TOV_pctile"] >= t["big"]["ast_tov_pctile"])
    )
    all_df["qual_big_standard"] = all_df["qual_big_standard_path"] & all_df["qual_general"]
    all_df["qual_stretch_big"] = all_df["qual_big_standard"]

    def passed_params(row, checks, qualified_col, path_label):
        passed = [label for label, ok in checks if bool(ok)]
        prefix = f"Qualified: {path_label}. " if bool(row[qualified_col]) else "Passed parameters: "
        if not passed:
            return prefix + "None yet."
        return prefix + ", ".join(passed) + "."

    all_df["qual_general_reason"] = all_df.apply(
        lambda r: passed_params(
            r,
            [
                ("AST% percentile", r["AST_pct_pctile"] >= t["general"]["ast_pctile"]),
                ("eFG%", r["efg"] >= t["general"]["efg"]),
                ("3P%", r["tp"] >= t["general"]["three_pct"]),
                ("AST/TO percentile", r["AST_TOV_pctile"] >= t["general"]["ast_tov_pctile"]),
                ("DREB requirement", dreb_raw_standard[r.name]),
                ("Exception AST% percentile", r["AST_pct_pctile"] >= t["general"]["exception_ast_pctile"]),
                ("Exception DREB percentile", r["DRB_pct_pctile"] >= t["general"]["exception_dreb_pctile"]),
            ],
            "qual_general",
            "standard baseline path" if r["qual_general_standard"] else "creation plus rebounding exception path",
        ),
        axis=1,
    )
    all_df["qual_pg_reason"] = all_df.apply(
        lambda r: passed_params(
            r,
            [
                ("General Player baseline", r["qual_general"]),
                ("AST% percentile", r["AST_pct_pctile"] >= t["pg"]["ast_pctile"]),
                ("AST/TO percentile", r["AST_TOV_pctile"] >= t["pg"]["ast_tov_pctile"]),
                ("3P%", r["tp"] >= t["pg"]["three_pct"]),
                ("3P rate", r["three_share"] >= t["pg"]["three_rate"]),
                ("2P% percentile exception", r["2P_pct_pctile"] >= t["pg"]["exception_two_pct_pctile"]),
            ],
            "qual_pg_combo",
            "standard guard path" if r["qual_pg_standard"] else "2P efficiency exception path",
        ),
        axis=1,
    )
    all_df["qual_wing_reason"] = all_df.apply(
        lambda r: passed_params(
            r,
            [
                ("General Player baseline", r["qual_general"]),
                ("DREB percentile", r["DRB_pct_pctile"] >= t["wing"]["dreb_pctile"]),
                ("3P%", r["tp"] >= t["wing"]["three_pct"]),
                ("3P rate", r["three_share"] >= t["wing"]["three_rate"]),
                ("AST/TO percentile", r["AST_TOV_pctile"] >= t["wing"]["ast_tov_pctile"]),
            ],
            "qual_wing_2_4",
            "2-4 wing path",
        ),
        axis=1,
    )
    all_df["qual_big_reason"] = all_df.apply(
        lambda r: passed_params(
            r,
            [
                ("General Player baseline", r["qual_general"]),
                ("F/C classification", r["pos"] == t["big"]["position"]),
                ("height", r["heightIn"] >= t["big"]["height"]),
                ("DREB percentile", r["DRB_pct_pctile"] >= t["big"]["dreb_pctile"]),
                ("3P%", r["tp"] >= t["big"]["three_pct"]),
                ("3P rate", r["three_share"] >= t["big"]["three_rate"]),
                ("AST/TO percentile", r["AST_TOV_pctile"] >= t["big"]["ast_tov_pctile"]),
            ],
            "qual_stretch_big",
            "F/C stretch path",
        ),
        axis=1,
    )

    # Display scores stay available for every player so the map still uses the highest fit.
    all_df["score_pg_combo"] = (
        0.30 * all_df["AST_pct_pctile"]
        + 0.30 * all_df["AST_TOV_pctile"]
        + 0.20 * all_df["three_profile"]
        + 0.20 * all_df["2P_pct_pctile"]
    ).clip(0, 100)
    all_df["score_wing_2_4"] = (
        0.30 * all_df["DRB_pct_pctile"]
        + 0.25 * all_df["eFG_pctile"]
        + 0.25 * all_df["three_profile"]
        + 0.20 * all_df["AST_TOV_pctile"]
    ).clip(0, 100)
    all_df["score_stretch_big"] = (
        0.40 * all_df["DRB_pct_pctile"]
        + 0.20 * all_df["three_profile"]
        + 0.20 * all_df["eFG_pctile"]
        + 0.20 * all_df["AST_TOV_pctile"]
    ).clip(0, 100)

    for key, qual_col, score_col in [
        ("pg", "qual_pg_combo", "score_pg_combo"),
        ("wing", "qual_wing_2_4", "score_wing_2_4"),
        ("big", "qual_stretch_big", "score_stretch_big"),
    ]:
        pool = all_df[qual_col]
        all_df[f"{score_col}_qualified_pool"] = np.nan
        if pool.any():
            for feature in QUALIFICATION_CONFIG["weights"][key]:
                raw_col = feature.replace(f"_{key}", "")
                if raw_col in ("three_profile_pctile", "three_profile"):
                    values = all_df.loc[pool, "three_profile"]
                else:
                    values = all_df.loc[pool, raw_col]
                all_df.loc[pool, feature] = values.rank(pct=True, method="average") * 100
            pool_score = sum(
                weight * all_df.loc[pool, feature]
                for feature, weight in QUALIFICATION_CONFIG["weights"][key].items()
            )
            all_df.loc[pool, f"{score_col}_qualified_pool"] = pool_score.clip(0, 100)

    all_df["meets_pg_preferred"] = all_df["qual_pg_combo"]
    all_df["meets_wing_preferred"] = all_df["qual_wing_2_4"]
    all_df["meets_big_preferred"] = all_df["qual_stretch_big"]

    score_cols = list(ARCHETYPE_LABELS)
    primary_scores = all_df[score_cols].copy()
    primary_scores.loc[all_df["heightIn"] < t["big"]["height"], "score_stretch_big"] = -np.inf
    all_df["primary_score_col"] = primary_scores.idxmax(axis=1)
    all_df["primary_archetype"] = all_df["primary_score_col"].map(ARCHETYPE_LABELS)
    all_df["primary_score"] = primary_scores.max(axis=1)

    X_raw = all_df[ARCHETYPE_PCA_FEATURES].fillna(
        all_df[ARCHETYPE_PCA_FEATURES].median()
    ).to_numpy(dtype=float)
    X_std = np.where(X_raw.std(axis=0) == 0, 1, X_raw.std(axis=0))
    X = (X_raw - X_raw.mean(axis=0)) / X_std
    _u, _s, vt = np.linalg.svd(X, full_matrices=False)
    coords = X @ vt[:4].T
    # Orient axes for readability: PC1 trends interior/rebounding-positive,
    # and PC2 trends creator-negative / taller-defender-positive.
    if vt[0, ARCHETYPE_PCA_FEATURES.index("heightIn")] < 0:
        coords[:, 0] *= -1
    pc2_creator_polarity = (
        vt[1, ARCHETYPE_PCA_FEATURES.index("ast_per_40")]
        + vt[1, ARCHETYPE_PCA_FEATURES.index("ast_tov")]
        + 0.5 * vt[1, ARCHETYPE_PCA_FEATURES.index("pts_per_40")]
        - vt[1, ARCHETYPE_PCA_FEATURES.index("heightIn")]
        - vt[1, ARCHETYPE_PCA_FEATURES.index("blk_per_40")]
    )
    if pc2_creator_polarity > 0:
        coords[:, 1] *= -1
    for i in range(4):
        all_df[f"arch_pca_PC{i+1}"] = coords[:, i]

    arch_cols = [
        "AST_pct_pctile", "AST_TOV_pctile", "DRB_pct_pctile", "2P_pct_pctile",
        "3P_pct_pctile", "3P_rate_pctile", "eFG_pctile", "three_profile",
        "pct_assist_creation", "pct_three_pct", "pct_three_rate",
        "pct_ast_tov", "pct_efg", "pct_dreb_pos_adj", "pct_size",
        "qual_general", "qual_general_standard", "qual_general_exception",
        "qual_pg_combo", "qual_pg_standard", "qual_pg_exception",
        "qual_pg_standard_path", "qual_pg_exception_path",
        "qual_wing_2_4", "qual_wing_standard", "qual_wing_standard_path",
        "qual_stretch_big", "qual_big_standard", "qual_big_standard_path",
        "qual_general_reason", "qual_pg_reason", "qual_wing_reason", "qual_big_reason",
        "score_pg_combo_qualified_pool", "score_wing_2_4_qualified_pool",
        "score_stretch_big_qualified_pool",
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

TRITON_METRIC_SPREADS = build_triton_spreads(d1_df)
add_triton_columns(d1_df, spreads=TRITON_METRIC_SPREADS)


def triton_format_value(metric, value):
    num = _as_float(value)
    if not np.isfinite(num):
        return "—"
    if metric.get("kind") == "height":
        return height_str(int(round(num)))
    if metric.get("kind") == "pct":
        return f"{num:.1f}%"
    return f"{num:.1f}"


def triton_format_target(metric, target):
    num = _as_float(target)
    if not np.isfinite(num):
        return "—"
    if metric.get("kind") == "height":
        return height_str(int(round(num)))
    if metric.get("kind") == "pct":
        return f"{num:g}%"
    return f"{num:g}"


def archetype_label(value):
    return ARCHETYPE_SHORT_LABEL.get(value, value)


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
        content = "# Archetype Guide\n\nThe explainer file could not be loaded."
    return ui.div(
        {"class": "doc-shell"},
        ui.div({"class": "doc-inner"},
               ui.HTML(simple_markdown_to_html(content))))


def historical_row_by_season_player_id(season_player_id):
    if not season_player_id or HISTORICAL_PLAYER_INDEX.empty:
        return None
    rows = HISTORICAL_PLAYER_INDEX[
        HISTORICAL_PLAYER_INDEX["season_player_id"].eq(str(season_player_id).strip())
    ]
    if rows.empty:
        return None
    return rows.iloc[0]


def similarity_beta_ideal_row(ideal):
    if HISTORICAL_PLAYER_INDEX.empty:
        return None
    row_id = str(ideal.get("season_player_id", "") or "").strip()
    if row_id:
        return historical_row_by_season_player_id(row_id)
    player_key = normalize_lookup_key(ideal.get("player_name"))
    team_key = normalize_lookup_key(ideal.get("team"))
    year = _as_float(ideal.get("year"))
    rows = HISTORICAL_PLAYER_INDEX[
        HISTORICAL_PLAYER_INDEX["player_name"].map(normalize_lookup_key).eq(player_key)
    ].copy()
    if np.isfinite(year) and "year" in rows.columns:
        rows = rows[pd.to_numeric(rows["year"], errors="coerce").eq(year)].copy()
    exact = rows[rows["team"].map(normalize_lookup_key).eq(team_key)].copy()
    if not exact.empty:
        return exact.iloc[0]
    if not rows.empty:
        return rows.iloc[0]
    return None


def similarity_beta_metric(row, key, fallback="—"):
    if row is None:
        return fallback
    if key == "height_inches":
        return _format_compare_value(key, row.get(key))
    num = _as_float(row.get(key))
    if not np.isfinite(num):
        return fallback
    return f"{num:.1f}"


def similarity_beta_comp_metric(comp, key):
    num = _as_float(comp.get(key))
    if not np.isfinite(num):
        return "—"
    return f"{num:.1f}"


def similarity_beta_movement(board_index: int, rank_index: int):
    board = SIMILARITY_BETA_MOVEMENT[board_index % len(SIMILARITY_BETA_MOVEMENT)]
    delta = board[rank_index % len(board)]
    if delta > 0:
        return ("up", f"↑ {delta}")
    if delta < 0:
        return ("down", f"↓ {abs(delta)}")
    return ("flat", "—")


def similarity_beta_compare_payload(row, comp, *, return_to: str = ""):
    if row is None or not comp.get("player_id"):
        return "{}"
    payload = {
        "source_id": str(row.get("season_player_id", "") or "").strip(),
        "target_id": str(comp.get("player_id", "") or "").strip(),
    }
    if return_to:
        payload["return_to"] = return_to
    return json.dumps(payload)


def similarity_beta_rows(row, comps, board_index: int, *, compact: bool = True, return_to: str = ""):
    rows = []
    for i, comp in enumerate(comps):
        movement_class, movement_label = similarity_beta_movement(board_index, i)
        payload = similarity_beta_compare_payload(row, comp, return_to=return_to)
        rows.append(
            ui.div(
                {
                    "class": "similarity-beta-row similarity-beta-row--clickable",
                    "onclick": f"Shiny.setInputValue('hist_open_compare',{payload},{{priority:'event'}})",
                    "title": f"Compare {row.get('player_name', 'ideal player') if row is not None else 'ideal player'} to {comp['name']}",
                },
                ui.div(str(comp["rank"]), class_="similarity-beta-rank"),
                ui.div(movement_label, class_=f"similarity-beta-move {movement_class}"),
                ui.div(
                    ui.div(comp["name"], class_="similarity-beta-player"),
                    ui.div(
                        " · ".join([bit for bit in [comp.get("team", ""), comp.get("conf", ""), comp.get("cls", "")] if bit]),
                        class_="similarity-beta-team",
                    ),
                    class_="similarity-beta-player-cell",
                ),
                ui.div(similarity_beta_comp_metric(comp, "pts_per_game"), class_="similarity-beta-stat"),
                ui.div(similarity_beta_comp_metric(comp, "ast_per_game"), class_="similarity-beta-stat"),
                ui.div(similarity_beta_comp_metric(comp, "treb_per_game"), class_="similarity-beta-stat"),
            )
        )
    if not rows:
        rows.append(
            ui.div(
                "No current-player matches are available for this ideal player yet.",
                class_="similarity-beta-empty",
            )
        )
    return rows


def similarity_beta_ideal_header(row, ideal):
    ideal_name = str(
        (row.get("player_name", "") if row is not None else "")
        or ideal.get("player_name", "")
        or "Ideal Player"
    )
    ideal_meta = historical_profile_subtitle(row) if row is not None else ""
    if not ideal_meta:
        ideal_bits = [
            str(ideal.get("team", "")),
            str(int(ideal.get("year"))) if np.isfinite(_as_float(ideal.get("year"))) else "",
        ]
        ideal_meta = " · ".join([bit for bit in ideal_bits if bit])
    return ideal_name, ideal_meta


def similarity_beta_table_head():
    return ui.div(
        {"class": "similarity-beta-table-head"},
        ui.div("#"),
        ui.div("Δ"),
        ui.div("Current player"),
        ui.div("PPG"),
        ui.div("APG"),
        ui.div("RPG"),
    )


def triton_tracker_ideals(saved_ids):
    defaults = triton_tracker_default_ideals()
    saved = triton_tracker_saved_ideals(saved_ids, seen=triton_tracker_ideal_ids(defaults))
    return [*defaults, *saved]


def triton_tracker_ideal_ids(ideals):
    row_ids = set()
    for ideal in ideals:
        row = similarity_beta_ideal_row(ideal)
        if row is not None:
            row_ids.add(str(row.get("season_player_id", "") or "").strip())
    return row_ids


def triton_tracker_default_ideals():
    ideals = []
    seen = set()
    for ideal in TRITON_TRACKER_DEFAULT_IDEALS:
        row = similarity_beta_ideal_row(ideal)
        if row is None:
            continue
        row_id = str(row.get("season_player_id", "") or "").strip()
        if row_id in seen:
            continue
        ideals.append(ideal)
        seen.add(row_id)
    return ideals


def triton_tracker_saved_ideals(saved_ids, seen=None):
    ideals = []
    seen = set(seen or set())
    seen_saved = set()
    ordered_saved = []
    for value in saved_ids:
        row_id = str(value).strip()
        if row_id and row_id not in seen_saved:
            ordered_saved.append(row_id)
            seen_saved.add(row_id)
    for row_id in ordered_saved:
        if row_id in seen:
            continue
        if historical_row_by_season_player_id(row_id) is None:
            continue
        ideals.append({"season_player_id": row_id})
        seen.add(row_id)
    return ideals


def similarity_beta_card(ideal, board_index: int):
    row = similarity_beta_ideal_row(ideal)
    comps = historical_current_comps_for_player(
        row,
        n_comp=HISTORICAL_CURRENT_COMP_LIMIT,
        exclude_low_sample=True,
    ) if row is not None else []
    ideal_name, ideal_meta = similarity_beta_ideal_header(row, ideal)
    rows = similarity_beta_rows(row, comps, board_index)
    row_id = str(row.get("season_player_id", "") or "").strip() if row is not None else ""

    return ui.div(
        {"class": "similarity-beta-card"},
        ui.div(
            {"class": "similarity-beta-card-head"},
            ui.div(
                ui.div(ideal_name, class_="similarity-beta-ideal-name"),
                ui.div(ideal_meta, class_="similarity-beta-ideal-meta"),
            ),
            ui.div("Ideal", class_="similarity-beta-pill"),
        ),
        ui.div(
            {"class": "similarity-beta-ideal-stats"},
            ui.div(ui.span("HT"), ui.tags.b(similarity_beta_metric(row, "height_inches"))),
            ui.div(ui.span("PPG"), ui.tags.b(similarity_beta_metric(row, "pts_per_game"))),
            ui.div(ui.span("APG"), ui.tags.b(similarity_beta_metric(row, "ast_per_game"))),
            ui.div(ui.span("RPG"), ui.tags.b(similarity_beta_metric(row, "treb_per_game"))),
        ),
        similarity_beta_table_head(),
        ui.div({"class": "similarity-beta-table"}, *rows),
        ui.tags.button(
            "View longer list",
            class_="similarity-beta-more",
            onclick=f"Shiny.setInputValue('sim_beta_open_long_list',{json.dumps(row_id)},{{priority:'event'}})",
        ),
    )


def make_similarity_beta_long_list_modal(source_id: str):
    row = historical_row_by_season_player_id(source_id)
    if row is None:
        return None
    comps = historical_current_comps_for_player(
        row,
        n_comp=25,
        exclude_low_sample=True,
    )
    ideal_name, ideal_meta = similarity_beta_ideal_header(row, {})
    rows = similarity_beta_rows(row, comps, 0, compact=False, return_to="triton_tracker_long_list")
    body = ui.div(
        {"class": "similarity-beta-long-list"},
        ui.div(
            ui.div(ideal_name, class_="similarity-beta-ideal-name"),
            ui.div(ideal_meta, class_="similarity-beta-ideal-meta"),
            class_="similarity-beta-long-head",
        ),
        similarity_beta_table_head(),
        ui.div({"class": "similarity-beta-table similarity-beta-table--long"}, *rows),
    )
    return ui.modal(
        body,
        title=ui.HTML(f"Longer Similarity List <b>· {html.escape(ideal_name)}</b>"),
        easy_close=True,
        size="l",
    )


def make_similarity_beta_tab():
    return ui.div(
        {"id": "sim-beta-tab", "class": "tab-panel"},
        ui.output_ui("triton_tracker_ui"),
    )


def make_triton_tracker_content(saved_ids):
    pinned_ideals = triton_tracker_default_ideals()
    saved_ideals = triton_tracker_saved_ideals(
        saved_ids,
        seen=triton_tracker_ideal_ids(pinned_ideals),
    )
    saved_body = (
        ui.div(
            {"class": "similarity-beta-grid similarity-beta-grid--tracked"},
            *[
                similarity_beta_card(ideal, i + len(pinned_ideals))
                for i, ideal in enumerate(saved_ideals)
            ],
        )
        if saved_ideals
        else ui.div(
            "No historical ideals saved yet. Add one from Historical Players (Beta).",
            class_="similarity-beta-tracked-empty",
        )
    )
    return ui.div(
        {"class": "similarity-beta-shell"},
        ui.div(
            {"class": "similarity-beta-topbar"},
            ui.div(
                ui.div("Triton Tracker", class_="similarity-beta-title"),
                ui.div(
                    "Save historical ideal players, then rank the current D-I pool by the tier-weighted similarity model.",
                    class_="similarity-beta-subtitle",
                ),
            ),
            ui.div("Movement = change since last refresh", class_="similarity-beta-refresh-note"),
        ),
        ui.div(
            {"class": "similarity-beta-section-head"},
            ui.div("Pinned UCSD ideals"),
            ui.div("Always shown", class_="similarity-beta-section-count"),
        ),
        ui.div(
            {"class": "similarity-beta-grid"},
            *[
                similarity_beta_card(ideal, i)
                for i, ideal in enumerate(pinned_ideals)
            ],
        ),
        ui.div(
            {"class": "similarity-beta-section-head"},
            ui.div("Tracked historical ideals"),
            ui.div(f"{len(saved_ideals)} saved", class_="similarity-beta-section-count"),
        ),
        saved_body,
    )


SIMILARITY_METRIC_LABELS = {
    "mahalanobis": "Mahalanobis dist. over PC1-PC4",
    "euclidean": "Euclidean dist. over PC1-PC4",
}
SIMILARITY_VIEW_LABELS = {
    "current": "Current players",
    "historical": "Historical comps",
}
SIMILARITY_HISTORICAL_POOL_LABELS = {
    "all": "All",
    "big_west_next_year": "Played in Big West next year",
}
LEGACY_SIMILARITY_SCORE_CATEGORIES = [
    ("workload", "Workload"),
    ("shot_style", "Shot Style"),
    ("spacing", "Spacing"),
    ("rim_finishing", "Rim / Finishing"),
    ("rebounding", "Rebounding"),
    ("defense", "Defense"),
    ("ballhandling", "Ballhandling"),
    ("height", "Height"),
]
SIMILARITY_COMPARE_CATEGORIES = [
    (
        "profile_workload",
        "Tier 1 · Height / Shot Type / Workload",
        [
            ("height_inches", "Height"),
            ("rim_share", "Rim shot rate"),
            ("mid_share", "Midrange shot rate"),
            ("three_share", "3PT shot rate"),
            ("dunk_share", "Dunk rate"),
            ("usg", "USG%"),
            ("FTR", "FTR"),
        ],
    ),
    (
        "shot_creation",
        "Tier 2 · How They Take Shots",
        [
            ("assisted_fg_pct", "Total assisted FG%"),
            ("three_assisted_pct", "3PT assisted%"),
            ("rim_assisted_pct", "Rim/dunk assisted%"),
        ],
    ),
    (
        "ballhandling",
        "Tier 3 · Ballhandling",
        [
            ("AST_pct", "AST%"),
            ("TOV_pct", "TOV%"),
            ("AST_TOV", "AST/TO"),
        ],
    ),
    (
        "efficiency",
        "Tier 4 · Efficiency",
        [
            ("eFG", "eFG%"),
            ("FT_pct", "FT%"),
            ("3P_pct", "3PT%"),
            ("rim_pct", "Rim%"),
            ("mid_pct", "Midrange%"),
            ("dunk_pct", "Dunk%"),
        ],
    ),
    (
        "rebounding",
        "Tier 5 · Rebounding",
        [
            ("ORB_pct", "ORB%"),
            ("DRB_pct", "DRB%"),
        ],
    ),
    (
        "defense",
        "Tier 6 · Defense",
        [
            ("Blk_pct", "BLK%"),
            ("Stl_pct", "STL%"),
            ("stops_per_40", "Stops/40"),
            ("personal_fouls_per_40", "PF/40"),
        ],
    ),
]
SIMILARITY_COMPARE_PERCENT_KEYS = {
    "assisted_fg_pct",
    "three_share",
    "rim_share",
    "mid_share",
    "dunk_share",
    "three_assisted_pct",
    "rim_assisted_pct",
    "eFG",
    "FT_pct",
    "3P_pct",
    "rim_pct",
    "mid_pct",
    "dunk_pct",
}
SIMILARITY_COMPARE_RAW_PERCENT_KEYS = {
    "usg",
    "ORB_pct",
    "DRB_pct",
    "AST_pct",
    "TOV_pct",
    "Blk_pct",
    "Stl_pct",
}
SIMILARITY_COMPARE_MIXED_SCALE_PERCENT_KEYS = {
    *SIMILARITY_COMPARE_PERCENT_KEYS,
    "usg",
}
SIMILARITY_TIER_WEIGHTS = {
    "profile_workload": 6 / 21,
    "shot_creation": 5 / 21,
    "ballhandling": 4 / 21,
    "efficiency": 3 / 21,
    "rebounding": 2 / 21,
    "defense": 1 / 21,
}
SIMILARITY_TIER_STAT_WEIGHTS = {
    "profile_workload": {
        "height_inches": 0.140,
        "rim_share": 0.130,
        "mid_share": 0.153,
        "three_share": 0.124,
        "dunk_share": 0.139,
        "usg": 0.163,
        "FTR": 0.150,
    },
    "shot_creation": {
        "assisted_fg_pct": 0.310,
        "three_assisted_pct": 0.356,
        "rim_assisted_pct": 0.334,
    },
    "ballhandling": {
        "AST_pct": 0.317,
        "TOV_pct": 0.375,
        "AST_TOV": 0.307,
    },
    "efficiency": {
        "eFG": 0.141,
        "FT_pct": 0.170,
        "3P_pct": 0.168,
        "rim_pct": 0.164,
        "mid_pct": 0.175,
        "dunk_pct": 0.182,
    },
    "rebounding": {
        "ORB_pct": 0.500,
        "DRB_pct": 0.500,
    },
    "defense": {
        "Blk_pct": 0.256,
        "Stl_pct": 0.244,
        "stops_per_40": 0.221,
        "personal_fouls_per_40": 0.279,
    },
}


def _as_float(value):
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(num) if pd.notna(num) else np.nan


def _format_compare_value(stat_key: str, value: object) -> str:
    num = _as_float(value)
    if not np.isfinite(num):
        return "\u2014"
    if stat_key == "height_inches":
        return height_str(int(round(num)))
    if stat_key in SIMILARITY_COMPARE_PERCENT_KEYS:
        if abs(num) <= 1:
            return f"{num * 100:.1f}%"
        return f"{num:.1f}%"
    if stat_key in SIMILARITY_COMPARE_RAW_PERCENT_KEYS:
        if stat_key in SIMILARITY_COMPARE_MIXED_SCALE_PERCENT_KEYS and abs(num) <= 1:
            num *= 100
        return f"{num:.1f}%"
    if stat_key in {"AST_TOV", "FTR", "3P_per_100_team_pos", "personal_fouls_per_40", "stops_per_40"}:
        return f"{num:.2f}"
    return f"{num:.1f}"

CURRENT_TO_COMPARE_KEY = {
    "usg": "usg",
    "3P_per_100_team_pos": "3P_per_100_team_pos",
    "assisted_fg_pct": "assisted_fg_pct",
    "three_share": "three_share",
    "rim_share": "rim_share",
    "mid_share": "mid_share",
    "dunk_share": "dunk_share",
    "three_assisted_pct": "three_assisted_pct",
    "rim_assisted_pct": "rim_assisted_pct",
    "eFG": "efg",
    "FT_pct": "ft",
    "3P_pct": "tp",
    "rim_pct": "rim_fg_pct",
    "mid_pct": "mid_fg_pct",
    "dunk_pct": "dunk_pct",
    "FTR": "ftr",
    "ORB_pct": "orb_pct",
    "DRB_pct": "drb_pct",
    "Blk_pct": "blk_pct",
    "Stl_pct": "stl_pct",
    "personal_fouls_per_40": "pf_per_40",
    "stops_per_40": "stops_per_40",
    "AST_pct": "ast_pct",
    "AST_TOV": "ast_tov",
    "TOV_pct": "tov_pct",
}
HISTORICAL_COMPARE_SCORE_COLUMNS = [
    f"{category_key}_score" for category_key, _label in LEGACY_SIMILARITY_SCORE_CATEGORIES
]
HISTORICAL_COMPARE_GRADE_COLUMNS = [
    f"{category_key}_grade" for category_key, _label in LEGACY_SIMILARITY_SCORE_CATEGORIES
]
HISTORICAL_COMPARE_FALLBACK_COLUMNS = [*CURRENT_TO_COMPARE_KEY.keys(), "height_inches"]


def _similarity_model_value(stat_key: str, value: object):
    num = _as_float(value)
    if not np.isfinite(num):
        return np.nan
    if stat_key in SIMILARITY_COMPARE_MIXED_SCALE_PERCENT_KEYS and abs(num) <= 1:
        return num * 100
    return num


def _similarity_model_series(stat_key: str, values) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype("float64")
    if stat_key in SIMILARITY_COMPARE_MIXED_SCALE_PERCENT_KEYS:
        numeric = numeric.where(numeric.abs() > 1, numeric * 100)
    return numeric


def _build_current_similarity_norms(pool: pd.DataFrame) -> dict:
    stat_keys = {
        stat_key
        for stat_weights in SIMILARITY_TIER_STAT_WEIGHTS.values()
        for stat_key in stat_weights
        if stat_key in pool.columns
    }
    norms = {}
    for stat_key in stat_keys:
        col = _similarity_model_series(stat_key, pool[stat_key])
        mean = col.mean(skipna=True)
        std = col.std(skipna=True, ddof=0)
        if not np.isfinite(mean) or not np.isfinite(std) or std <= 1e-8:
            continue
        norms[stat_key] = {
            "mean": float(mean),
            "std": float(std),
            "z": (col - mean) / std,
        }
    return norms


def _apply_tier_similarity_distance(row, pool):
    working = pool.copy()
    working["historical_distance"] = np.nan
    working["historical_shared_stats"] = 0
    tier_distance_cols = []

    for tier_key, stat_weights in SIMILARITY_TIER_STAT_WEIGHTS.items():
        usable_stats = []
        source_values = []
        pool_columns = []
        weights = []

        for stat_key, stat_weight in stat_weights.items():
            if stat_key not in working.columns:
                continue
            source_value = _similarity_model_value(stat_key, row.get(stat_key))
            if not np.isfinite(source_value):
                continue
            norm = HISTORICAL_CURRENT_SIMILARITY_NORMS.get(stat_key, {})
            mean = norm.get("mean", np.nan)
            std = norm.get("std", np.nan)
            pool_z_col = norm.get("z")
            if pool_z_col is None or not np.isfinite(mean) or not np.isfinite(std) or std <= 1e-8:
                col = _similarity_model_series(stat_key, working[stat_key])
                mean = col.mean(skipna=True)
                std = col.std(skipna=True, ddof=0)
                if not np.isfinite(mean) or not np.isfinite(std) or std <= 1e-8:
                    continue
                pool_z = (col - mean) / std
            else:
                pool_z = pool_z_col.reindex(working.index)
            if pool_z.isna().all():
                continue
            usable_stats.append(stat_key)
            source_values.append((source_value - mean) / std)
            pool_columns.append(pool_z)
            weights.append(float(stat_weight))

        if not usable_stats:
            continue

        tier_values = pd.concat(pool_columns, axis=1)
        tier_values.columns = usable_stats
        tier_weights = np.array(weights, dtype=float)
        tier_weights = tier_weights / tier_weights.sum()
        source_z = np.array(source_values, dtype=float)
        pool_z = tier_values.to_numpy(dtype=float)
        overlap = np.isfinite(pool_z)
        weighted_overlap = overlap * tier_weights
        overlap_weight = weighted_overlap.sum(axis=1)
        diffs = pool_z - source_z
        weighted_sq = np.where(overlap, np.square(diffs) * tier_weights, 0.0).sum(axis=1)
        tier_distance = np.where(
            overlap_weight > 0,
            np.sqrt(weighted_sq / overlap_weight),
            np.nan,
        )
        distance_col = f"{tier_key}_tier_distance"
        working[distance_col] = tier_distance
        working["historical_shared_stats"] += overlap.sum(axis=1)
        tier_distance_cols.append((distance_col, SIMILARITY_TIER_WEIGHTS[tier_key]))

    if not tier_distance_cols:
        return pd.DataFrame()

    final_distance = np.zeros(len(working), dtype=float)
    final_weight = np.zeros(len(working), dtype=float)
    for distance_col, tier_weight in tier_distance_cols:
        values = pd.to_numeric(working[distance_col], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(values)
        final_distance[mask] += values[mask] * float(tier_weight)
        final_weight[mask] += float(tier_weight)
    valid = (final_weight > 0) & working["historical_shared_stats"].ge(3).to_numpy(dtype=bool)
    working.loc[valid, "historical_distance"] = final_distance[valid] / final_weight[valid]
    working["historical_distance_method"] = "tier_weighted"
    return working[valid].copy()


def _current_compare_profile_from_row(row):
    profile = {
        "player_name": row["name"],
        "team": row["team"],
        "conf": row.get("confName", row.get("conf", "")),
        "year": D1_CURRENT_SEASON,
        "player_id": row["id"],
        "subtitle": f"{row['team']} \u00b7 {row['cls']}",
        "height_inches": _as_float(row.get("heightIn")),
    }
    for compare_key, row_key in CURRENT_TO_COMPARE_KEY.items():
        profile[compare_key] = _as_float(row.get(row_key))
    return profile


HISTORICAL_CURRENT_POOL = build_historical_current_pool()
HISTORICAL_CURRENT_SIMILARITY_NORMS = _build_current_similarity_norms(HISTORICAL_CURRENT_POOL)
def _profile_from_neighbor_payload(payload, prefix: str, player_id: str = "", subtitle: str = "", year: int | None = None):
    profile = {
        "player_name": str(payload.get(f"{prefix}_name", "")).strip(),
        "team": str(payload.get(f"{prefix}_team", "")).strip(),
        "conf": str(payload.get(f"{prefix}_conf", "")).strip(),
        "year": year,
        "player_id": player_id,
        "subtitle": subtitle,
    }
    for category_key, _, stats in SIMILARITY_COMPARE_CATEGORIES:
        grade_key = f"{prefix}_{category_key}_grade"
        if grade_key in payload:
            profile[f"{category_key}_grade"] = _as_float(payload.get(grade_key))
        for stat_key, _label in stats:
            key = f"{prefix}_{stat_key}"
            profile[stat_key] = _as_float(payload.get(key))
    return profile


def format_season_short(year: object) -> str:
    num = _as_float(year)
    if not np.isfinite(num):
        return ""
    return f"'{int(round(num)) % 100:02d}"


def inches_display(value: object) -> str:
    num = _as_float(value)
    if not np.isfinite(num):
        return "\u2014"
    return height_str(int(round(num)))


def historical_profile_subtitle(row) -> str:
    bits = [
        str(row.get("team", "") or "").strip(),
        format_season_short(row.get("year")),
        str(row.get("conf", "") or "").strip(),
    ]
    return " \u00b7 ".join([bit for bit in bits if bit])


def historical_compare_profile_from_row(row):
    profile = {
        "player_name": str(row.get("player_name", "") or "").strip(),
        "team": str(row.get("team", "") or "").strip(),
        "conf": str(row.get("conf", "") or "").strip(),
        "year": _as_float(row.get("year")),
        "player_id": "",
        "subtitle": historical_profile_subtitle(row),
        "height_inches": _as_float(row.get("height_inches")),
    }
    for stat_key, _row_key in CURRENT_TO_COMPARE_KEY.items():
        profile[stat_key] = _as_float(row.get(stat_key))
    for grade_key in HISTORICAL_COMPARE_GRADE_COLUMNS:
        profile[grade_key] = _as_float(row.get(grade_key))
    return profile


def historical_current_comp_cards(
    row,
    *,
    exclude_low_sample: bool = False,
    open_mode: str = "profile",
):
    comps = historical_current_comps_for_player(row, exclude_low_sample=exclude_low_sample)
    cards = []
    for comp in comps:
        badge_color = ARCHETYPE_COLOR.get(
            comp["profile"].get("primary_archetype", ""),
            POS_COLOR.get(comp.get("pos", ""), "#888"),
        )
        if open_mode == "compare":
            payload = json.dumps(
                {
                    "source_id": str(row.get("season_player_id", "") or "").strip(),
                    "target_id": comp["player_id"],
                }
            )
            onclick = f"Shiny.setInputValue('hist_open_compare',{payload},{{priority:'event'}})"
        else:
            onclick = f"Shiny.setInputValue('hist_open_current_profile','{comp['player_id']}',{{priority:'event'}})"
        cards.append(
            ui.div(
                {
                    "class": "historical-comp-card",
                    "onclick": onclick,
                },
                ui.div(f"{comp['rank']:02d}", class_="historical-comp-rank"),
                ui.div(comp["name"], class_="historical-comp-name"),
                ui.div(
                    ui.span(comp.get("archetype", ""), class_="pos-badge", style=f"color:{badge_color};border-color:{badge_color}") if comp.get("archetype") else ui.span(),
                    ui.span(comp["team"]),
                    ui.span(f"· {comp.get('cls', '')}") if comp.get("cls") else ui.span(),
                    class_="historical-comp-meta",
                ),
                ui.div(f"distance {comp['distance']:.2f}", class_="historical-comp-distance"),
            )
        )
    return cards


def make_historical_profile_modal(row, *, exclude_low_sample: bool = False, triton_tracker_ids=None):
    source_profile = historical_compare_profile_from_row(row)
    year = source_profile["year"]
    season = f"{int(year) - 1}–{int(year) % 100:02}" if np.isfinite(year) else "Unknown season"
    initial_current_comp_cards = historical_current_comp_cards(
        row,
        exclude_low_sample=exclude_low_sample,
        open_mode="compare",
    )
    triton_tracker_ids = set(triton_tracker_ids or [])
    row_id = str(row.get("season_player_id", "") or "").strip()
    is_tracked = row_id in triton_tracker_ids
    tracker_label = "Remove from Triton Tracker" if is_tracked else "Add to Triton Tracker"
    tracker_class = "triton-tracker-toggle is-tracked" if is_tracked else "triton-tracker-toggle"
    tracker_onclick = (
        f"window.ucsdToggleTritonTracker && window.ucsdToggleTritonTracker({json.dumps(row_id)}, this);"
    )
    pc = ARCHETYPE_COLOR.get(str(row.get("archetype", "") or ""), POS_COLOR.get(str(row.get("pos", "") or ""), "#888"))
    meta_badges = []
    for value in (
        str(row.get("pos", "") or "").strip(),
        str(row.get("archetype", "") or "").strip(),
        str(row.get("class", "") or "").strip(),
        str(row.get("role", "") or "").strip(),
    ):
        if value:
            meta_badges.append(ui.span(value, class_="pos-badge", style="color:var(--ink-2);border-color:var(--rule)"))

    summary_items = [
        ("Season", season, True),
        ("Conference", str(row.get("conf", "") or "—"), False),
        ("Team", str(row.get("team", "") or "—"), False),
        ("Pos", str(row.get("pos", "") or "—"), False),
        ("Archetype", str(row.get("archetype", "") or "—"), False),
        ("Class", str(row.get("class", "") or "—"), False),
        ("Role", str(row.get("role", "") or "—"), False),
        ("Height", _format_compare_value("height_inches", row.get("height_inches")), True),
        ("Games", str(int(row["GP"])) if pd.notna(row.get("GP")) else "—", True),
        ("MPG", f"{_as_float(row.get('mins_per_game')):.1f}" if pd.notna(_as_float(row.get("mins_per_game"))) else "—", True),
        ("PPG", f"{_as_float(row.get('pts_per_game')):.1f}" if pd.notna(_as_float(row.get("pts_per_game"))) else "—", True),
        ("APG", f"{_as_float(row.get('ast_per_game')):.1f}" if pd.notna(_as_float(row.get("ast_per_game"))) else "—", True),
        ("RPG", f"{_as_float(row.get('treb_per_game')):.1f}" if pd.notna(_as_float(row.get("treb_per_game"))) else "—", True),
        ("BPM", f"{_as_float(row.get('bpm')):.1f}" if pd.notna(_as_float(row.get("bpm"))) else "—", True),
    ]
    grade_rows = []
    for category_key, category_label in LEGACY_SIMILARITY_SCORE_CATEGORIES:
        grade_value = _as_float(source_profile.get(f"{category_key}_grade"))
        if not np.isfinite(grade_value):
            grade_value = 0.0
        grade_rows.append(
            ui.div(
                {"class": "arch-score-row"},
                ui.div(
                    ui.span(category_label, class_="arch-score-name"),
                    ui.span(f"{grade_value:.0f}", class_="arch-score-value"),
                    class_="arch-score-head",
                ),
                ui.div(
                    {"class": "arch-score-track"},
                    ui.div(
                        {
                            "class": "arch-score-fill",
                            "style": f"width:{max(0.0, min(100.0, grade_value)):.1f}%;background:{pc};",
                        }
                    ),
                ),
            )
        )

    stat_sections = []
    for _category_key, category_label, stats in SIMILARITY_COMPARE_CATEGORIES:
        rows = []
        for stat_key, stat_label in stats:
            rows.append(
                ui.div(
                    {"class": "compare-stat-row", "style": "grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);"},
                    ui.div(stat_label, class_="compare-stat-label"),
                    ui.div(_format_compare_value(stat_key, source_profile.get(stat_key)), class_="compare-stat-value"),
                )
            )
        stat_sections.append(
            ui.div(
                ui.div(category_label, class_="compare-section-title"),
                *rows,
                class_="compare-section historical-profile-section",
            )
        )

    body = ui.div(
        {"class": "historical-profile-grid"},
        ui.div(
            {"class": "historical-profile-col"},
            ui.div(
                ui.div(source_profile["player_name"], class_="player-name"),
                ui.div(
                    ui.tags.button(
                        "Close",
                        class_="historical-profile-close",
                        **{"data-bs-dismiss": "modal", "type": "button"},
                    ),
                    ui.tags.button(
                        tracker_label,
                        class_=tracker_class,
                        onclick=tracker_onclick,
                    ) if row_id else ui.span(),
                    class_="historical-profile-actions",
                ),
                class_="historical-profile-name-row",
            ),
            ui.div(
                ui.span({"class": "team-dot", "style": f"background:{pc}"}),
                source_profile["subtitle"],
                class_="player-team",
            ),
            ui.div(*meta_badges, class_="player-team", style="margin-top:8px;flex-wrap:wrap;") if meta_badges else ui.div(),
            ui.div(
                {"class": "bio-grid"},
                *[bio_item(label, value, mono=mono) for label, value, mono in summary_items],
            ),
            ui.div(
                ui.div("Similarity Grades", class_="col-title"),
                *grade_rows,
                class_="arch-score-panel",
            ),
        ),
        ui.div(
            {"class": "historical-profile-col historical-profile-col--stats"},
            ui.div("Similarity Inputs", class_="col-title"),
            *stat_sections,
        ),
        ui.div(
            {"class": "historical-profile-col"},
            ui.div(
                ui.div(
                    {"class": "historical-profile-comps-head"},
                    ui.div(f"{D1_SEASON_LABEL} Player Comparisons", class_="col-title"),
                    ui.div(
                        ui.input_checkbox(
                            "hist_modal_exclude_low_sample_current",
                            f"Exclude current comps under {int(HISTORICAL_CURRENT_COMP_MIN_MPG)} MPG",
                            value=exclude_low_sample,
                        ),
                        class_="historical-profile-comps-controls",
                    ),
                ),
                ui.div(
                    {
                        "class": (
                            "historical-comp-list historical-comp-list--initial"
                            if initial_current_comp_cards
                            else "qual-note historical-comp-list--initial"
                        )
                    },
                    *(
                        initial_current_comp_cards
                        if initial_current_comp_cards
                        else ["No current-player comps are available for this profile yet."]
                    ),
                ),
                class_="arch-score-panel historical-profile-comps",
            ),
        ),
    )
    return ui.modal(
        body,
        title=ui.span(
            f"{season} Historical Profile ",
            ui.tags.b(f"· {source_profile['player_name']}"),
        ),
        easy_close=True,
        size="xl",
    )


def historical_current_comps_for_player(
    row,
    n_comp: int = HISTORICAL_CURRENT_COMP_LIMIT,
    exclude_low_sample: bool = False,
):
    cache_key = (
        str(row.get("season_player_id", "") or "").strip(),
        int(n_comp),
        bool(exclude_low_sample),
    )
    if cache_key[0]:
        cached = HISTORICAL_CURRENT_COMP_CACHE.get(cache_key)
        if cached is not None:
            return [dict(comp) for comp in cached]

    if HISTORICAL_CURRENT_POOL.empty:
        return []
    pool = HISTORICAL_CURRENT_POOL.copy()
    if exclude_low_sample:
        pool = pool[pool["mpg"].fillna(0).ge(HISTORICAL_CURRENT_COMP_MIN_MPG)].copy()
        if pool.empty:
            return []
    source_name_key = normalize_lookup_key(row.get("player_name"))
    source_team_key = normalize_lookup_key(row.get("team"))
    pool = pool[
        ~(
            pool["name"].map(normalize_lookup_key).eq(source_name_key)
            & pool["team"].map(normalize_lookup_key).eq(source_team_key)
        )
    ].copy()
    if pool.empty:
        return []

    pool = _apply_tier_similarity_distance(row, pool)
    if pool.empty:
        return []

    sort_cols = ["historical_distance"]
    ascending = [True]
    if "historical_shared_stats" in pool.columns:
        sort_cols.append("historical_shared_stats")
        ascending.append(False)
    sort_cols.append("mpg")
    ascending.append(False)
    pool = pool.sort_values(sort_cols, ascending=ascending).head(n_comp)
    comps = []
    for idx, comp in pool.iterrows():
        comps.append(
            {
                "rank": len(comps) + 1,
                "player_id": comp["id"],
                "name": comp["name"],
                "team": comp["team"],
                "conf": comp.get("confName", comp.get("conf", "")),
                "cls": comp.get("cls", ""),
                "pos": comp.get("pos", ""),
                "archetype": archetype_label(comp.get("primary_archetype", "")),
                "mins_per_game": _as_float(comp.get("mins_per_game")),
                "pts_per_game": _as_float(comp.get("ppg")),
                "ast_per_game": _as_float(comp.get("apg")),
                "treb_per_game": _as_float(comp.get("rpg")),
                "distance": float(comp["historical_distance"]),
                "subtitle": f"{comp['team']} \u00b7 {comp.get('cls', '')}".strip(),
                "profile": _current_compare_profile_from_row(comp),
            }
        )
    if cache_key[0]:
        HISTORICAL_CURRENT_COMP_CACHE[cache_key] = [dict(comp) for comp in comps]
    return comps


def _current_d1_compare_profile(row):
    return _current_compare_profile_from_row(row)


def _compare_header_name(profile) -> str:
    name = str(profile.get("player_name", "")).strip() or "Player"
    year = pd.to_numeric(pd.Series([profile.get("year")]), errors="coerce").iloc[0]
    if pd.isna(year):
        return name
    year_suffix = int(year) % 100
    return f"{name} '{year_suffix:02d}"


def make_similarity_compare_modal(
    source_profile,
    target_profile,
    comparison_origin: str = "historical",
    future_profile=None,
    return_source_id: str = "",
):
    profiles = [source_profile, target_profile]
    if future_profile and str(future_profile.get("player_name", "")).strip():
        profiles.append(future_profile)

    compare_grid_cols = f"minmax(0, 1.2fr) {' '.join(['minmax(0, 1fr)' for _ in profiles])}"

    category_sections = []
    omitted_missing_rows = 0
    for category_key, category_label, stats in SIMILARITY_COMPARE_CATEGORIES:
        stat_rows = []
        for stat_key, stat_label in stats:
            if all(not np.isfinite(_as_float(profile.get(stat_key))) for profile in profiles):
                omitted_missing_rows += 1
                continue
            row_children = [ui.div(stat_label, class_="compare-stat-label")]
            for profile in profiles:
                row_children.append(
                    ui.div(
                        _format_compare_value(stat_key, profile.get(stat_key)),
                        class_="compare-stat-value",
                    )
                )
            stat_rows.append(
                ui.div(
                    {"class": "compare-stat-row", "style": f"grid-template-columns:{compare_grid_cols};"},
                    *row_children,
                )
            )
        if not stat_rows:
            continue
        category_sections.append(
            ui.div(
                ui.div(category_label, class_="compare-section-title"),
                ui.div(
                    {"class": "compare-stat-head", "style": f"grid-template-columns:{compare_grid_cols};"},
                    ui.div("Stat", class_="compare-stat-label"),
                    *[ui.div(_compare_header_name(profile), class_="compare-stat-player") for profile in profiles],
                ),
                *stat_rows,
                class_="compare-section",
            )
        )

    missing_note = (
        ui.div(
            "Stats missing for both compared players are hidden.",
            class_="compare-missing-note",
        )
        if omitted_missing_rows
        else ui.div()
    )

    footer_buttons = []
    if source_profile.get("player_id"):
        footer_buttons.append(
            ui.tags.button(
                {
                    "class": "pill-btn active",
                    "onclick": (
                        "window.__compareModalNavigating = true;"
                        f"Shiny.setInputValue('modal_compare_back','{source_profile.get('player_id', '')}',{{priority:'event'}})"
                    ),
                },
                "Back to player",
            )
        )
    if target_profile.get("player_id"):
        footer_buttons.append(
            ui.tags.button(
                {
                    "class": "pill-btn",
                    "onclick": (
                        "window.__compareModalNavigating = true;"
                        f"Shiny.setInputValue('modal_compare_open_target','{target_profile['player_id']}',{{priority:'event'}})"
                    ),
                },
                "Open compared player",
            )
        )

    if comparison_origin == "triton_tracker_long_list" and return_source_id:
        close_input = "sim_beta_open_long_list"
        close_value = return_source_id
    else:
        close_input = "modal_compare_back"
        close_value = source_profile.get("player_id", "")

    body = ui.div(
        {"id": "compare-detail-body"},
        ui.tags.script(
            ui.HTML(
                f"""
                setTimeout(function() {{
                  const modal = document.querySelector('.modal.show');
                  if (!modal || modal.dataset.compareDismissBound === '1') return;
                  modal.dataset.compareDismissBound = '1';
                  window.__compareModalNavigating = false;
                  modal.addEventListener('hidden.bs.modal', function() {{
                    if (window.__compareModalNavigating) {{
                      window.__compareModalNavigating = false;
                      return;
                    }}
                    Shiny.setInputValue({json.dumps(close_input)}, {json.dumps(close_value)}, {{priority:'event'}});
                  }}, {{ once: true }});
                }}, 0);
                """
            )
        ),
        ui.div(
            {
                "class": "compare-player-grid",
                "style": f"grid-template-columns:repeat({len(profiles)}, minmax(0, 1fr));",
            },
            *[
                ui.div(
                    ui.div(
                        ui.div(profile["player_name"], class_="compare-player-name"),
                        ui.tags.button(
                            {
                                "class": "pill-btn compare-player-inline-btn",
                                "onclick": (
                                    "window.__compareModalNavigating = true;"
                                    f"Shiny.setInputValue('modal_compare_open_target','{profile['player_id']}',{{priority:'event'}})"
                                ),
                            },
                            "Full stats",
                        ) if (
                            comparison_origin in {"historical", "triton_tracker_long_list"}
                            and idx == 1
                            and profile.get("player_id")
                        ) else ui.div(),
                        class_="compare-player-head",
                    ),
                    ui.div(profile.get("subtitle", ""), class_="compare-player-sub"),
                    ui.div(
                        f"Height: {_format_compare_value('height_inches', profile.get('height_inches'))}",
                        class_="compare-player-sub",
                    ),
                    class_="compare-player-card",
                )
                for idx, profile in enumerate(profiles)
            ],
        ),
        ui.div(
            {"class": "compare-modal-shell"},
            missing_note,
            *category_sections,
        ),
    )

    subtitle = "Current comps profile view" if comparison_origin == "current" else "Historical comps profile view"
    return ui.modal(
        body,
        title=ui.HTML(
            f"Similarity Comparison <b>\u00b7 {source_profile['player_name']}</b> "
            f"<span class=\"sub\" style=\"margin-left:10px;\">{subtitle}</span>"
        ),
        easy_close=True,
        size="xl",
        footer=ui.div({"class": "compare-footer"}, *footer_buttons),
    )


def historical_comps_for_player(row, n_comp: int = 5, pool_key: str = "all"):
    neighbors_df = HISTORICAL_NEIGHBORS.get(pool_key, HISTORICAL_NEIGHBORS["all"])
    if neighbors_df.empty:
        return []
    matches = neighbors_df[
        neighbors_df["target_player_name"].eq(str(row["name"]).strip())
        & neighbors_df["target_team"].eq(str(row["team"]).strip())
    ].copy()
    if matches.empty:
        return []
    matches = matches[
        ~(
            matches["match_player_name"].eq(str(row["name"]).strip())
            & matches["match_team"].eq(str(row["team"]).strip())
        )
    ].copy()
    if matches.empty:
        return []
    matches = matches.sort_values(["match_rank", "distance"]).head(n_comp).reset_index(drop=True)
    ref_dist = float(matches["distance"].max()) if "distance" in matches.columns else 0.0
    if not np.isfinite(ref_dist) or ref_dist <= 0:
        ref_dist = 1.0
    comps = []
    for _, comp in matches.iterrows():
        comp_payload = {
            "rank": int(comp.get("match_rank", len(comps) + 1)),
            "name": comp.get("match_player_name", ""),
            "team": comp.get("match_team", ""),
            "season": int(comp.get("match_season", 0)) if pd.notna(comp.get("match_season", np.nan)) else None,
            "conf": comp.get("match_conf", ""),
            "distance": float(comp.get("distance", np.nan)),
            "target_name": comp.get("target_player_name", ""),
            "target_team": comp.get("target_team", ""),
            "target_conf": comp.get("target_conf", ""),
            "next_name": comp.get("next_player_name", ""),
            "next_team": comp.get("next_team", ""),
            "next_conf": comp.get("next_conf", ""),
            "next_season": int(comp.get("next_season", 0)) if pd.notna(comp.get("next_season", np.nan)) else None,
        }
        for category_key, _category_label, stats in SIMILARITY_COMPARE_CATEGORIES:
            for stat_key, _stat_label in stats:
                comp_payload[f"target_{stat_key}"] = comp.get(f"target_{stat_key}", np.nan)
                comp_payload[f"match_{stat_key}"] = comp.get(f"match_{stat_key}", np.nan)
                comp_payload[f"next_{stat_key}"] = comp.get(f"next_{stat_key}", np.nan)
            comp_payload[f"target_{category_key}_grade"] = comp.get(
                f"target_{category_key}_grade", np.nan
            )
            comp_payload[f"match_{category_key}_grade"] = comp.get(
                f"match_{category_key}_grade", np.nan
            )
            comp_payload[f"next_{category_key}_grade"] = comp.get(
                f"next_{category_key}_grade", np.nan
            )
        comps.append(comp_payload)
    return comps


def make_detail_modal(player_id, df, league_avg, similar_to_fn, division_label, watchlist,
                      similarity_metric="mahalanobis", similarity_view="current",
                      historical_pool="all"):
    row  = df[df["id"] == player_id].iloc[0]
    if similarity_metric not in SIMILARITY_METRIC_LABELS:
        similarity_metric = "mahalanobis"
    if similarity_view not in SIMILARITY_VIEW_LABELS:
        similarity_view = "current"
    if historical_pool not in SIMILARITY_HISTORICAL_POOL_LABELS:
        historical_pool = "all"
    sims = similar_to_fn(player_id, n_sim=5, metric=similarity_metric)
    historical_comps = (
        historical_comps_for_player(row, pool_key=historical_pool)
        if division_label == "D-I"
        else []
    )
    pc   = ARCHETYPE_COLOR.get(row["primary_archetype"], POS_COLOR.get(row["pos"], "#888"))

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
    is_low_sample = bool(row.get("low_sample_size", False))

    rim_assisted_pct = pd.to_numeric(pd.Series([row.get("rim_assisted_pct", np.nan)]), errors="coerce").iloc[0]
    mid_assisted_pct = pd.to_numeric(pd.Series([row.get("mid_assisted_pct", np.nan)]), errors="coerce").iloc[0]
    three_assisted_pct = pd.to_numeric(pd.Series([row.get("three_assisted_pct", np.nan)]), errors="coerce").iloc[0]
    assisted_fg_pct = pd.to_numeric(pd.Series([row.get("assisted_fg_pct", np.nan)]), errors="coerce").iloc[0]
    rim_made_total = pd.to_numeric(pd.Series([row.get("rim_made_total", np.nan)]), errors="coerce").iloc[0]
    mid_made_total = pd.to_numeric(pd.Series([row.get("pbp_mid_made", np.nan)]), errors="coerce").iloc[0]
    three_made_total = pd.to_numeric(pd.Series([row.get("pbp_three_made", np.nan)]), errors="coerce").iloc[0]
    total_made = rim_made_total + mid_made_total + three_made_total
    rim_fgm_share = (rim_made_total / total_made) if total_made else 0.0
    mid_fgm_share = (mid_made_total / total_made) if total_made else 0.0
    three_fgm_share = (three_made_total / total_made) if total_made else 0.0

    pf_value = pd.to_numeric(pd.Series([row.get("pf", np.nan)]), errors="coerce").iloc[0]
    season_statline = [
        stat_box("MIN", f"{row['mpg']:.1f}", league_avg["mpg"]),
        stat_box("PTS", f"{row['ppg']:.1f}", league_avg["ppg"]),
        stat_box("REB", f"{row['rpg']:.1f}", league_avg["rpg"]),
        stat_box("AST", f"{row['apg']:.1f}", league_avg["apg"]),
        stat_box("TOV", f"{row['tov']:.1f}", league_avg["tov"]),
        stat_box("FOUL", f"{pf_value:.1f}", league_avg["pf"]) if pd.notna(pf_value) else ui.div(),
        stat_box("STL", f"{row['spg']:.2f}", league_avg["spg"]),
        stat_box("BLK", f"{row['bpg']:.2f}", league_avg["bpg"]),
        stat_box("FG%", f"{row['fg']*100:.1f}", league_avg["fg"] * 100),
        stat_box("3P%", f"{row['tp']*100:.1f}", league_avg["tp"] * 100),
        stat_box("FT%", f"{row['ft']*100:.1f}", league_avg["ft"] * 100),
    ]
    bpm_value = pd.to_numeric(pd.Series([row.get("bpm", np.nan)]), errors="coerce").iloc[0]
    porpag_value = pd.to_numeric(pd.Series([row.get("porpag", np.nan)]), errors="coerce").iloc[0]
    has_archetype_v2 = bool(row.get("archetype_v2_available", False)) or pd.notna(
        row.get("archetype_v2_primary_label", pd.NA)
    )
    if pd.notna(assisted_fg_pct):
        season_statline.append(stat_box("AST'D FG%", f"{assisted_fg_pct*100:.1f}", 0))
    efficiency_statline = []
    if division_label == "D-I":
        efficiency_defs = [
            ("eFG%", row.get("efg", np.nan), league_avg.get("efg", 0), True),
            ("ORB%", row.get("orb_pct", np.nan), league_avg.get("orb_pct", 0), False),
            ("DRB%", row.get("drb_pct", np.nan), league_avg.get("drb_pct", 0), False),
            ("AST%", row.get("ast_pct", np.nan), league_avg.get("ast_pct", 0), False),
            ("STL%", row.get("stl_pct", np.nan), league_avg.get("stl_pct", 0), False),
            ("BLK%", row.get("blk_pct", np.nan), league_avg.get("blk_pct", 0), False),
            ("3P%", row.get("tp", np.nan), league_avg.get("tp", 0), True),
            ("USG%", row.get("usg", np.nan), league_avg.get("usg", 0), True),
            ("FT%", row.get("ft", np.nan), league_avg.get("ft", 0), True),
            ("FTR", row.get("ftr", np.nan), league_avg.get("ftr", 0), False),
            ("TOV%", row.get("tov_pct", np.nan), league_avg.get("tov_pct", 0), False),
            ("PF/40", row.get("pf_per_40", np.nan), league_avg.get("pf_per_40", 0), False),
        ]
        for label, value, avg_value, as_percent in efficiency_defs:
            num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
            avg_num = pd.to_numeric(pd.Series([avg_value]), errors="coerce").iloc[0]
            if pd.isna(num):
                continue
            if as_percent:
                efficiency_statline.append(stat_box(label, f"{num*100:.1f}", float(avg_num) * 100))
            else:
                efficiency_statline.append(stat_box(label, f"{num:.1f}", float(avg_num)))
    stat_view_id = f"stat-view-{player_id}"
    season_panel_id = f"season-statline-{player_id}"
    eff_panel_id = f"efficiency-statline-{player_id}"
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
    archetype_scores = []
    for score_col, arch in ARCHETYPE_LABELS.items():
        score = float(row[score_col])
        color = ARCHETYPE_COLOR[arch]
        primary_cls = " primary" if arch == row["primary_archetype"] else ""
        archetype_scores.append(
            ui.div(
                {"class": f"arch-score-row{primary_cls}"},
                ui.div(
                    ui.span(archetype_label(arch), class_="arch-score-name"),
                    ui.span(f"{score:.0f}", class_="arch-score-value"),
                    class_="arch-score-head",
                ),
                ui.div(
                    {"class": "arch-score-track"},
                    ui.div(
                        {"class": "arch-score-fill",
                         "style": f"width:{score:.1f}%;background:{color};"}
                    ),
                ),
            )
        )
    qualification_notes = [
        ("General", row["qual_general_reason"]),
        ("PG", row["qual_pg_reason"]),
        ("2-4 Wing", row["qual_wing_reason"]),
        ("Big", row["qual_big_reason"]),
    ]
    qualification_note_ui = [
        ui.div(ui.tags.b(f"{label}: "), str(note), class_="qual-note")
        for label, note in qualification_notes
    ]
    archetype_v2_scores = []
    if division_label == "D-I" and has_archetype_v2:
        for code in ARCHETYPE_V2_ORDER:
            score = pd.to_numeric(pd.Series([row.get(code, np.nan)]), errors="coerce").iloc[0]
            if pd.isna(score):
                continue
            archetype_v2_scores.append(
                ui.div(
                    {"class": "arch-score-row"},
                    ui.div(
                        ui.span(archetype_v2_label(code), class_="arch-score-name"),
                        ui.span(f"{score * 100:.1f}%", class_="arch-score-value"),
                        class_="arch-score-head",
                    ),
                    ui.div(
                        {"class": "arch-score-track"},
                        ui.div(
                            {"class": "arch-score-fill",
                             "style": f"width:{score * 100:.1f}%;background:#2f855a;"}
                        ),
                    ),
                )
            )
    player_tags = []
    if is_low_sample:
        player_tags.append("Low sample size")
    if bool(row.get("archetype_v2_unstable", False)):
        player_tags.append("Unstable archetype")
    if bool(row.get("transfer_available", False)):
        transfer_from = row.get("transfer_from") or row["team"]
        player_tags.append(f"Available transfer from {transfer_from}")
    recruiting_summary = str(row.get("recruiting_summary", "") or "").strip()
    if recruiting_summary:
        player_tags.extend(recruiting_summary.split("; "))
    player_tag_ui = [
        ui.span(
            tag,
            class_="sample-badge" if tag in {"Low sample size", "Unstable archetype"} else "pos-badge",
            style=""
            if tag in {"Low sample size", "Unstable archetype"}
            else "color:var(--accent);border-color:var(--accent)",
        )
        for tag in player_tags
    ]

    shot_profile_summary = [
        ("Rim Assisted", rim_assisted_pct, f"{pct_display(rim_fgm_share)} of FGM"),
        ("Mid Assisted", mid_assisted_pct, f"{pct_display(mid_fgm_share)} of FGM"),
        ("3PT Assisted", three_assisted_pct, f"{pct_display(three_fgm_share)} of FGM"),
    ]
    shot_profile_cards = [
        ui.div(
            {"class": "shot-profile-card"},
            ui.div(label, class_="k"),
            ui.div(pct_display(value), class_="v"),
            ui.div(note, class_="s"),
        )
        for label, value, note in shot_profile_summary
    ]

    sim_rows = []
    for i, s in enumerate(sims):
        sim_row = df[df["id"] == s["id"]]
        sim_arch = sim_row.iloc[0]["primary_archetype"] if not sim_row.empty else None
        sim_badge = archetype_label(sim_arch) if sim_arch else s["pos"]
        sc = ARCHETYPE_COLOR.get(sim_arch, POS_COLOR.get(s["pos"], "#888"))
        compare_payload = json.dumps({
            "mode": "current",
            "source_id": player_id,
            "target_id": s["id"],
        })
        current_click = (
            f"Shiny.setInputValue('open_similarity_compare',{compare_payload},{{priority:'event'}})"
            if division_label == "D-I"
            else f"Shiny.setInputValue('{sim_input}','{s['id']}',{{priority:'event'}})"
        )
        sim_rows.append(
            ui.div(
                {"class": "sim-row",
                 "onclick": current_click},
                ui.div(f"{i+1:02d}", class_="sim-rank"),
                ui.div(
                    ui.div(s["name"], class_="nm"),
                    ui.div(ui.span(sim_badge, class_="pos-badge",
                                   style=f"color:{sc};border-color:{sc}"),
                           ui.span(s["team"]),
                           ui.span(f"· {s['cls']}", style="color:var(--ink-3)"),
                           class_="meta"),
                    class_="sim-main"),
                ui.div(f"{s['similarity']*100:.0f}",
                       ui.span("%", style="font-size:11px;color:var(--ink-3)"),
                       ui.span("match", class_="sim-lbl"),
                       class_="sim-pct")))

    historical_rows = []
    for comp in historical_comps:
        meta_bits = [comp["team"]]
        if comp["season"]:
            meta_bits.append(f"· {comp['season']}")
        if comp["conf"]:
            meta_bits.append(f"· {comp['conf']}")
        compare_payload = json.dumps({
            "mode": "historical",
            "historical_pool": historical_pool,
            "source_id": player_id,
            "target_name": comp["name"],
            "target_team": comp["team"],
            "target_season": comp["season"],
            "target_conf": comp["conf"],
            "next_name": comp.get("next_name", ""),
            "next_team": comp.get("next_team", ""),
            "next_conf": comp.get("next_conf", ""),
            "next_season": comp.get("next_season"),
            "target_name_current": comp.get("target_name", ""),
            "target_team_current": comp.get("target_team", ""),
            "target_conf_current": comp.get("target_conf", ""),
            **{
                key: comp.get(key)
                for category_key, _category_label, stats in SIMILARITY_COMPARE_CATEGORIES
                for key in (
                    [f"target_{category_key}_grade", f"match_{category_key}_grade", f"next_{category_key}_grade"]
                    + [f"target_{stat_key}" for stat_key, _ in stats]
                    + [f"match_{stat_key}" for stat_key, _ in stats]
                    + [f"next_{stat_key}" for stat_key, _ in stats]
                )
            },
        })
        historical_rows.append(
            ui.div(
                {
                    "class": "sim-row historical",
                    "onclick": f"Shiny.setInputValue('open_similarity_compare',{compare_payload},{{priority:'event'}})",
                },
                ui.div(f"{comp['rank']:02d}", class_="sim-rank"),
                ui.div(
                    ui.div(comp["name"], class_="nm"),
                    ui.div(*[ui.span(bit) for bit in meta_bits], class_="meta"),
                    class_="sim-main",
                ),
                ui.div("Compare", class_="sim-action"),
            )
        )

    show_historical = similarity_view == "historical" and division_label == "D-I"
    current_section = ui.div(
        {"style": "display:none;" if show_historical else "display:block;"},
        ui.div(
            ui.input_radio_buttons(
                "modal_similarity_metric",
                None,
                choices={
                    "mahalanobis": "Mahalanobis",
                    "euclidean": "Euclidean",
                },
                selected=similarity_metric,
                inline=True,
            ),
            class_="sim-metric-control",
        ),
        *sim_rows,
    )
    historical_empty = ui.div(
        "Historical comps are not available for this player yet.",
        class_="qual-note",
    )
    historical_section = ui.div(
        {"style": "display:block;" if show_historical else "display:none;"},
        *(historical_rows if historical_rows else [historical_empty]),
    )
    similarity_sub = (
        (
            "D-I only · players who played in the Big West the following season"
            if historical_pool == "big_west_next_year"
            else "D-I only · full historical pool"
        )
        if show_historical
        else SIMILARITY_METRIC_LABELS[similarity_metric]
    )

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
               ui.div(*player_tag_ui, class_="player-team", style="margin-top:8px;flex-wrap:wrap;")
               if player_tag_ui else ui.div(),
               ui.div({"class": "bio-grid"},
                      bio_item("Division", division_label),
                      bio_item("Archetype", row["archetype_v2_primary_label"])
                      if division_label == "D-I" and has_archetype_v2 else None,
                      bio_item("UCSD Position", archetype_label(row["primary_archetype"])),
                      bio_item("Class",    row["cls"]),
                      bio_item("Eligibility Used", str(int(row["eligibility"])), mono=True),
                      bio_item("Height",   height_str(int(row["heightIn"])), mono=True),
                      bio_item("Games",    str(int(row["gp"])), mono=True),
                      bio_item("Min/G",    f"{row['mpg']:.1f}", mono=True),
                      bio_item("BPM",      f"{bpm_value:.1f}" if pd.notna(bpm_value) else "N/A", mono=True),
                      bio_item("PORPAG",   f"{porpag_value:.2f}" if pd.notna(porpag_value) else "N/A", mono=True)),
               ui.div(
                   ui.div("Archetype", class_="col-title"),
                   ui.div(
                       ui.div(ui.tags.b("Primary: "), f"{row['archetype_v2_primary_label']} ({format_weight_pct(row['archetype_v2_primary_weight'])})", class_="qual-note"),
                       ui.div(ui.tags.b("Secondary: "), f"{row['archetype_v2_secondary_label']} ({format_weight_pct(row['archetype_v2_secondary_weight'])})", class_="qual-note"),
                   ) if division_label == "D-I" and has_archetype_v2 else ui.div(
                       "Unavailable for this player.",
                       class_="qual-note",
                   ),
                   *archetype_v2_scores,
                   class_="arch-score-panel",
               ),
               ui.div(
                   ui.div("UCSD Position", class_="col-title"),
                   *archetype_scores,
                   class_="arch-score-panel",
               ),
               ui.div(
                   ui.div("Passed Qualification Parameters", class_="col-title"),
                   *qualification_note_ui,
                   class_="arch-score-panel",
               )),
        ui.div({"class": "detail-col"},
               ui.div(
                   {"class": "statline-header"},
                   ui.div("Season Statline ", ui.span(
                       D1_SEASON_LABEL if division_label == "D-I" else "2025–26", class_="sub"
                   ), class_="col-title"),
                   ui.div(
                       {"class": "statline-toggle",
                        "id": stat_view_id},
                       ui.tags.button(
                           "Season",
                           class_="pill-btn active",
                           onclick=(
                               "const root=this.parentElement;"
                               f"document.getElementById('{season_panel_id}').style.display='grid';"
                               f"document.getElementById('{eff_panel_id}').style.display='none';"
                               "root.querySelectorAll('.pill-btn').forEach(btn=>btn.classList.remove('active'));"
                               "this.classList.add('active');"
                           ),
                       ),
                       ui.tags.button(
                           "Efficiency",
                           class_="pill-btn",
                           onclick=(
                               "const root=this.parentElement;"
                               f"document.getElementById('{season_panel_id}').style.display='none';"
                               f"document.getElementById('{eff_panel_id}').style.display='grid';"
                               "root.querySelectorAll('.pill-btn').forEach(btn=>btn.classList.remove('active'));"
                               "this.classList.add('active');"
                           ),
                       ) if efficiency_statline else ui.div(),
                   ) if efficiency_statline else ui.div(),
               ),
               ui.div({"class": "statline", "id": season_panel_id, "style": "display:grid;"}, *season_statline),
               ui.div({"class": "statline", "id": eff_panel_id, "style": "display:none;"}, *efficiency_statline),
               ui.div("vs. League Average ",
                      ui.span(f"unweighted mean, all {division_label} players", class_="sub"),
                      class_="col-title"),
               *bars,
               ui.div(ui.tags.b("Bar", style="color:var(--ink-2)"),
                      " = player value.  ",
                      ui.tags.b("Tick", style="color:var(--ink-2)"),
                      " = league mean.", class_="bar-note"),
               ui.div(
                   ui.div("Shot Profile", ui.span("rate · fg% · assisted%", class_="sub"), class_="col-title"),
                   ui.div(
                       {"class": "shot-profile-shell"},
                       ui.div({"class": "shot-profile-pie"}, make_shot_profile_pie_html(row, player_id)),
                       ui.div({"class": "shot-profile-assists"}, *shot_profile_cards),
                   ),
               )),
        ui.div({"class": "detail-col"},
               ui.div("Most Similar Players ",
                      ui.span(similarity_sub, class_="sub"),
                      class_="col-title"),
               ui.div(
                   ui.input_radio_buttons(
                       "modal_similarity_view",
                       None,
                       choices=(
                           SIMILARITY_VIEW_LABELS
                           if division_label == "D-I"
                           else {"current": SIMILARITY_VIEW_LABELS["current"]}
                       ),
                       selected=similarity_view if division_label == "D-I" else "current",
                       inline=True,
                   ),
                   class_="sim-metric-control",
               ),
               ui.div(
                   {
                       "style": "display:block;" if show_historical and division_label == "D-I" else "display:none;"
                   },
                   ui.input_radio_buttons(
                       "modal_similarity_pool",
                       None,
                       choices=SIMILARITY_HISTORICAL_POOL_LABELS,
                       selected=historical_pool,
                       inline=True,
                   ),
                   class_="sim-metric-control",
               ),
               current_section,
               historical_section))

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
    return list(zip(d["name"], d["primary_archetype"].map(archetype_label), d["team"], d["cls"],
                    d["ppg"],  d["rpg"], d["apg"],  d["id"]))

def build_traces(
    plot_df,
    selected_id,
    dimmed_arch,
    dot_size=9.5,
    dot_opacity=0.78,
    compress_pc1_tail=False,
    compress_pc2_tail=False,
    clip_x_range=None,
    clip_y_range=None,
):
    traces = []
    for arch in ARCHETYPE_ORDER:
        sub  = plot_df[plot_df["primary_archetype"] == arch]
        if sub.empty: continue
        alpha = 0.06 if arch in dimmed_arch else dot_opacity
        rest  = sub[sub["id"] != selected_id] if selected_id else sub
        sel   = sub[sub["id"] == selected_id] if selected_id else sub.iloc[0:0]
        rest_x = compress_positive_tail(rest["arch_pca_PC1"]) if compress_pc1_tail else rest["arch_pca_PC1"]
        rest_y = compress_negative_tail(rest["arch_pca_PC2"]) if compress_pc2_tail else rest["arch_pca_PC2"]
        if clip_x_range is not None:
            rest_x = pd.Series(
                np.clip(np.asarray(rest_x, dtype=float), clip_x_range[0], clip_x_range[1]),
                index=rest.index,
            )
        if clip_y_range is not None:
            rest_y = pd.Series(
                np.clip(np.asarray(rest_y, dtype=float), clip_y_range[0], clip_y_range[1]),
                index=rest.index,
            )
        if not rest.empty:
            traces.append(go.Scatter(
                x=rest_x, y=rest_y, mode="markers",
                marker=dict(size=dot_size, color=ARCHETYPE_COLOR[arch],
                            opacity=alpha, line=dict(width=0)),
                customdata=cdata(rest), hovertemplate=HOVER_TPL,
                name=archetype_label(arch), showlegend=False))
        if not sel.empty:
            r = sel.iloc[0]
            sel_x = float(compress_positive_tail([r["arch_pca_PC1"]])[0]) if compress_pc1_tail else r["arch_pca_PC1"]
            sel_y = float(compress_negative_tail([r["arch_pca_PC2"]])[0]) if compress_pc2_tail else r["arch_pca_PC2"]
            if clip_x_range is not None:
                sel_x = float(np.clip(sel_x, clip_x_range[0], clip_x_range[1]))
            if clip_y_range is not None:
                sel_y = float(np.clip(sel_y, clip_y_range[0], clip_y_range[1]))
            traces.append(go.Scatter(
                x=[sel_x], y=[sel_y], mode="markers",
                marker=dict(size=dot_size+16, color="rgba(0,0,0,0)",
                            line=dict(color="#c8a84b", width=1.5)),
                hoverinfo="skip", showlegend=False))
            traces.append(go.Scatter(
                x=[sel_x], y=[sel_y], mode="markers",
                marker=dict(size=dot_size+4, color=ARCHETYPE_COLOR[arch],
                            opacity=1.0, line=dict(color="#0f1623", width=1.8)),
                customdata=[cdata(sel)[0]], hovertemplate=HOVER_TPL,
                showlegend=False))
    return traces


def build_trace_id_map(plot_df, selected_id, dimmed_arch):
    trace_ids = []
    for arch in ARCHETYPE_ORDER:
        sub = plot_df[plot_df["primary_archetype"] == arch]
        if sub.empty:
            continue
        rest = sub[sub["id"] != selected_id] if selected_id else sub
        sel = sub[sub["id"] == selected_id] if selected_id else sub.iloc[0:0]
        if not rest.empty:
            trace_ids.append(rest["id"].astype(str).tolist())
        if not sel.empty:
            selected_ids = sel["id"].astype(str).tolist()
            trace_ids.append(selected_ids)
            trace_ids.append(selected_ids)
    return trace_ids


def resolve_clicked_player_id(plot_df, selected_id, dimmed_arch, trace_index, point_index):
    trace_map = build_trace_id_map(plot_df, selected_id, dimmed_arch)
    if trace_index is None or point_index is None:
        return None
    try:
        trace_ids = trace_map[int(trace_index)]
        return trace_ids[int(point_index)] if 0 <= int(point_index) < len(trace_ids) else None
    except (IndexError, ValueError, TypeError):
        return None

def compress_negative_tail(values, threshold=-4.0, scale=2.0):
    arr = np.asarray(values, dtype=float)
    out = arr.copy()
    mask = np.isfinite(arr) & (arr < threshold)
    out[mask] = threshold - scale * np.log1p(threshold - arr[mask])
    if isinstance(values, pd.Series):
        return pd.Series(out, index=values.index)
    return out


def compress_positive_tail(values, threshold=4.0, scale=2.0):
    arr = np.asarray(values, dtype=float)
    out = arr.copy()
    mask = np.isfinite(arr) & (arr > threshold)
    out[mask] = threshold + scale * np.log1p(arr[mask] - threshold)
    if isinstance(values, pd.Series):
        return pd.Series(out, index=values.index)
    return out


def clipped_series(values, clip_range):
    if clip_range is None:
        return values
    arr = np.asarray(values, dtype=float)
    out = np.clip(arr, clip_range[0], clip_range[1])
    if isinstance(values, pd.Series):
        return pd.Series(out, index=values.index)
    return out


def d2_pc2_tick_spec(series):
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    base_ticks = [-50, -40, -30, -20, -10, -5, 0]
    upper = float(vals.max())
    if upper >= 1:
        base_ticks.extend([1, 2, 3, 4, 5])
    tick_vals = []
    tick_text = []
    low_bound = float(vals.min()) - 1e-9
    high_bound = upper + 1e-9
    for tick in base_ticks:
        if low_bound <= tick <= high_bound:
            tick_vals.append(float(compress_negative_tail([tick])[0]))
            tick_text.append(str(int(tick)) if float(tick).is_integer() else f"{tick:g}")
    return {"tickmode": "array", "tickvals": tick_vals, "ticktext": tick_text}


def d2_pc1_tick_spec(series):
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    base_ticks = [-10, -5, 0, 5, 10, 15, 20]
    low_bound = float(vals.min()) - 1e-9
    high_bound = float(vals.max()) + 1e-9
    tick_vals = []
    tick_text = []
    for tick in base_ticks:
        if low_bound <= tick <= high_bound:
            tick_vals.append(float(compress_positive_tail([tick])[0]))
            tick_text.append(str(int(tick)) if float(tick).is_integer() else f"{tick:g}")
    return {"tickmode": "array", "tickvals": tick_vals, "ticktext": tick_text}


def robust_axis_range(series, selected_value=None, min_span=1.0, pad_ratio=0.08):
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return [-1.0, 1.0]
    lo = float(vals.min())
    hi = float(vals.max())
    lo = min(lo, 0.0)
    hi = max(hi, 0.0)
    if selected_value is not None and pd.notna(selected_value):
        selected_value = float(selected_value)
        lo = min(lo, selected_value)
        hi = max(hi, selected_value)
    span = hi - lo
    if span < min_span:
        mid = (hi + lo) / 2.0
        half = min_span / 2.0
        lo, hi = mid - half, mid + half
        span = hi - lo
    pad = max(span * pad_ratio, min_span * 0.05)
    return [lo - pad, hi + pad]


def build_layout(
    _plot_df,
    selected_id=None,
    compress_pc1_tail=False,
    compress_pc2_tail=False,
    fixed_x_range=None,
    fixed_y_range=None,
    clip_x_range=None,
    clip_y_range=None,
):
    axis = dict(gridcolor="rgba(0,0,0,0)", zeroline=True,
                zerolinecolor="#1e2d47", zerolinewidth=1.2,
                tickfont=dict(size=9, family="JetBrains Mono, monospace", color="#4a6080"),
                linecolor="#1e2d47", linewidth=1)
    tf = dict(size=10, family="JetBrains Mono, monospace", color="#4a6080")
    selected_row = _plot_df[_plot_df["id"] == selected_id] if selected_id else _plot_df.iloc[0:0]
    selected_x = selected_row["arch_pca_PC1"].iloc[0] if not selected_row.empty else None
    selected_y = selected_row["arch_pca_PC2"].iloc[0] if not selected_row.empty else None
    x_series = compress_positive_tail(_plot_df["arch_pca_PC1"]) if compress_pc1_tail else _plot_df["arch_pca_PC1"]
    x_selected = float(compress_positive_tail([selected_x])[0]) if compress_pc1_tail and selected_x is not None else selected_x
    x_series = clipped_series(x_series, clip_x_range)
    if clip_x_range is not None and x_selected is not None:
        x_selected = float(np.clip(x_selected, clip_x_range[0], clip_x_range[1]))
    x_range = fixed_x_range if fixed_x_range is not None else robust_axis_range(x_series, selected_value=x_selected)
    y_series = compress_negative_tail(_plot_df["arch_pca_PC2"]) if compress_pc2_tail else _plot_df["arch_pca_PC2"]
    y_selected = float(compress_negative_tail([selected_y])[0]) if compress_pc2_tail and selected_y is not None else selected_y
    y_series = clipped_series(y_series, clip_y_range)
    if clip_y_range is not None and y_selected is not None:
        y_selected = float(np.clip(y_selected, clip_y_range[0], clip_y_range[1]))
    y_range = fixed_y_range if fixed_y_range is not None else robust_axis_range(y_series, selected_value=y_selected)
    x_axis_extra = d2_pc1_tick_spec(_plot_df["arch_pca_PC1"]) if compress_pc1_tail else {}
    y_axis_extra = d2_pc2_tick_spec(_plot_df["arch_pca_PC2"]) if compress_pc2_tail else {}
    return go.Layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0f1623",
        margin=dict(l=64, r=18, t=16, b=60),
        xaxis=dict(
            title="PC1 · spacing ↔ rebounding",
            title_font=tf,
            range=x_range,
            **(x_axis_extra or {}),
            **axis,
        ),
        yaxis=dict(
            title="PC2 · lead guards ↔ rim protectors",
            title_font=tf,
            range=y_range,
            **(y_axis_extra or {}),
            **axis,
        ),
        hoverlabel=dict(bgcolor="#1a2540", bordercolor="#c8a84b",
                        font=dict(family="JetBrains Mono, monospace",
                                  size=11.5, color="#c8d4e8")),
        hovermode="closest", dragmode="pan",
        font=dict(family="Inter, sans-serif"), clickmode="event")

RADAR_STATS = [
    ("ppg", "PPG", "ppg", "PPG", "{:.1f}"),
    ("rpg", "RPG", "rpg", "RPG", "{:.1f}"),
    ("apg", "APG", "apg", "APG", "{:.1f}"),
    ("spg", "SPG", "spg", "SPG", "{:.2f}"),
    ("bpg", "BPG", "bpg", "BPG", "{:.2f}"),
    ("ts", "TS%", "ts", "TS%", "{:.1%}"),
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

# localStorage keys for the browser-side watchlist. Bump the suffix if the
# stored shape ever changes so old payloads are ignored rather than misread.
WATCHLIST_STORAGE_KEY = "ucsd_watchlist_player_ids_v1"
WATCHLIST_LINEUP_STORAGE_KEY = "ucsd_watchlist_lineup_candidates_v1"
TRITON_TRACKER_STORAGE_KEY = "ucsd_triton_tracker_historical_ids_v1"
if D1_PREVIEW_SNAPSHOT:
    WATCHLIST_STORAGE_KEY += "_d1_preview"
    WATCHLIST_LINEUP_STORAGE_KEY += "_d1_preview"
    TRITON_TRACKER_STORAGE_KEY += "_d1_preview"


def watchlist_rows(player_ids):
    rows = []
    for pid in player_ids:
        if not isinstance(pid, str):
            continue
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


def _lineup_text(value, default=""):
    if pd.isna(value):
        return default
    text = str(value).strip()
    return text if text else default


def _lineup_number(value, default=0.0, scale_small=False):
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return float(default)
    num = float(num)
    if scale_small and abs(num) <= 1.5:
        num *= 100.0
    return num


def build_watchlist_lineup_candidates(player_ids):
    candidates = []
    for pid, row, _df, div_ in watchlist_rows(player_ids):
        team = _lineup_text(row.get("team"), "Unknown Team")
        conf = _lineup_text(row.get("conf"), "")
        ht_in = int(round(_lineup_number(row.get("heightIn"), default=0)))
        ht = _lineup_text(row.get("ht"), height_str(ht_in) if ht_in > 0 else "—")
        bpm = _lineup_number(row.get("bpm"), default=row.get("bpr", 0))
        adj_bpm = _lineup_number(row.get("adj_bpm"), default=bpm)
        three_pct = _lineup_number(row.get("tp"), default=0, scale_small=True)
        ts_pct = _lineup_number(row.get("ts"), default=0, scale_small=True)
        ftr = _lineup_number(row.get("ftr"), default=0)
        ind_drtg = _lineup_number(row.get("adj_drtg"), default=row.get("indDrtg", 102.5))
        candidate = {
            "lineupId": f"watchlist_{pid}",
            "sourceId": pid,
            "name": _lineup_text(row.get("name"), "Unknown Player"),
            "team": team,
            "conf": conf,
            "division": div_,
            "num": _lineup_text(row.get("num"), "–"),
            "pos": _lineup_text(row.get("pos"), "G/F"),
            "yr": _lineup_text(row.get("cls"), ""),
            "ht": ht,
            "htIn": ht_in,
            "bpr": bpm,
            "adjBpr": adj_bpm,
            "obpr": _lineup_number(row.get("obpm"), default=row.get("obpr", 0)),
            "dbpr": _lineup_number(row.get("dbpm"), default=row.get("dbpr", 0)),
            "ts": ts_pct,
            "usg": _lineup_number(row.get("usg"), default=0, scale_small=True),
            "threeRate": _lineup_number(row.get("three_share"), default=0),
            "threePct": three_pct,
            "arate": _lineup_number(row.get("assist_creation"), default=0),
            "torate": _lineup_number(row.get("tov_pct"), default=0),
            "stl": _lineup_number(row.get("stl_pct"), default=row.get("stl_arch", 0)),
            "blk": _lineup_number(row.get("blk_pct"), default=row.get("blk_arch", 0)),
            "dreb": _lineup_number(row.get("drb_pct"), default=row.get("dreb_arch", 0)),
            "oreb": _lineup_number(row.get("orb_pct"), default=row.get("orb", 0)),
            "ftr": ftr,
            "indDrtg": ind_drtg,
            "note": (
                f"<strong>{html.escape(_lineup_text(row.get('name'), 'Unknown Player'))}"
                f" — {html.escape(team)}"
                f"{f' ({html.escape(conf)})' if conf else ''}"
                f" · {html.escape(div_)} · {html.escape(_lineup_text(row.get('cls'), ''))}"
                f" · {html.escape(ht)}</strong><br>"
                f"BPM: {adj_bpm:+.1f} · TS%: {ts_pct:.1f}"
                f" · 3PT%: {three_pct:.1f} · DRtg: {ind_drtg:.1f}"
            ),
        }
        candidates.append(candidate)
    return candidates

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

def legend_html(dimmed_arch):
    parts = []
    for arch in ARCHETYPE_ORDER:
        cls = "legend-item dim" if arch in dimmed_arch else "legend-item"
        col = ARCHETYPE_COLOR[arch]
        parts.append(
            f'<div class="{cls}" onclick="Shiny.setInputValue(\'toggle_dim\','
            f'\'{arch}\',{{priority:\'event\'}})">'
            f'<span class="swatch" style="background:{col}"></span>'
            f'<span>{archetype_label(arch)}</span></div>')
    parts.append('<span class="legend-hint"></span>')
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────
# SIDEBAR / PLOT AREA BUILDERS
# ─────────────────────────────────────────────────────────────────────────

def make_sidebar(prefix, df, conferences):
    def slider_range(col, step=1):
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        lo = float(np.floor(vals.min() / step) * step)
        hi = float(np.ceil(vals.max() / step) * step)
        if step >= 1:
            return int(lo), int(hi)
        decimals = len(str(step).split(".")[1].rstrip("0"))
        return round(lo, decimals), round(hi, decimals)

    mpg_min, mpg_max = slider_range("mpg", 0.1)
    ppg_min, ppg_max = slider_range("ppg", 0.1)
    efg_min, efg_max = slider_range("efg", 0.01)
    orb_pct_min, orb_pct_max = slider_range("orb_pct", 0.01) if "orb_pct" in df.columns and pd.to_numeric(df["orb_pct"], errors="coerce").notna().any() else (0, 1)
    drb_pct_min, drb_pct_max = slider_range("drb_pct", 0.01) if "drb_pct" in df.columns and pd.to_numeric(df["drb_pct"], errors="coerce").notna().any() else (0, 1)
    ast_pct_min, ast_pct_max = slider_range("ast_pct", 0.01) if "ast_pct" in df.columns and pd.to_numeric(df["ast_pct"], errors="coerce").notna().any() else (0, 1)
    stl_pct_min, stl_pct_max = slider_range("stl_pct", 0.01) if "stl_pct" in df.columns and pd.to_numeric(df["stl_pct"], errors="coerce").notna().any() else (0, 1)
    blk_pct_min, blk_pct_max = slider_range("blk_pct", 0.01) if "blk_pct" in df.columns and pd.to_numeric(df["blk_pct"], errors="coerce").notna().any() else (0, 1)
    tp_min, tp_max = slider_range("tp", 0.01)
    ft_min, ft_max = slider_range("ft", 0.01) if "ft" in df.columns and pd.to_numeric(df["ft"], errors="coerce").notna().any() else (0, 1)
    usg_min, usg_max = slider_range("usg", 0.01) if "usg" in df.columns and pd.to_numeric(df["usg"], errors="coerce").notna().any() else (0, 1)
    ftr_min, ftr_max = slider_range("ftr", 0.01) if "ftr" in df.columns and pd.to_numeric(df["ftr"], errors="coerce").notna().any() else (0, 1)
    tov_pct_min, tov_pct_max = slider_range("tov_pct", 0.01) if "tov_pct" in df.columns and pd.to_numeric(df["tov_pct"], errors="coerce").notna().any() else (0, 1)
    pf40_min, pf40_max = slider_range("pf_per_40", 0.1) if "pf_per_40" in df.columns and pd.to_numeric(df["pf_per_40"], errors="coerce").notna().any() else (0, 1)
    three_share_min, three_share_max = slider_range("three_share", 0.01)
    rim_share_min, rim_share_max = slider_range("rim_share", 0.01) if "rim_share" in df.columns else (0, 1)
    mid_share_min, mid_share_max = slider_range("mid_share", 0.01) if "mid_share" in df.columns else (0, 1)
    apg_min, apg_max = slider_range("apg", 0.1)
    ato_min, ato_max = slider_range("ast_tov", 0.1)
    assisted_fg_pct_min, assisted_fg_pct_max = slider_range("assisted_fg_pct", 0.01) if "assisted_fg_pct" in df.columns else (0, 1)
    rim_fg_pct_min, rim_fg_pct_max = slider_range("rim_fg_pct", 0.01) if "rim_fg_pct" in df.columns else (0, 1)
    mid_fg_pct_min, mid_fg_pct_max = slider_range("mid_fg_pct", 0.01) if "mid_fg_pct" in df.columns else (0, 1)
    rim_ast_pct_min, rim_ast_pct_max = slider_range("rim_assisted_pct", 0.01) if "rim_assisted_pct" in df.columns else (0, 1)
    mid_ast_pct_min, mid_ast_pct_max = slider_range("mid_assisted_pct", 0.01) if "mid_assisted_pct" in df.columns else (0, 1)
    three_ast_pct_min, three_ast_pct_max = slider_range("three_assisted_pct", 0.01) if "three_assisted_pct" in df.columns else (0, 1)
    rpg_min, rpg_max = slider_range("rpg", 0.1)
    tov_min, tov_max = slider_range("tov", 0.1)
    pf_min, pf_max = slider_range("pf", 0.1) if "pf" in df.columns and pd.to_numeric(df["pf"], errors="coerce").notna().any() else (0, 1)
    drb_min, drb_max = slider_range("drb", 0.1)
    bpg_min, bpg_max = slider_range("bpg", 0.1)
    spg_min, spg_max = slider_range("spg", 0.1)
    h_min, h_max = slider_range("heightIn", 1)
    eligibility_min, eligibility_max = slider_range("eligibility", 1)
    has_bpm = pd.to_numeric(df["bpm"], errors="coerce").notna().any() if "bpm" in df.columns else False
    has_porpag = pd.to_numeric(df["porpag"], errors="coerce").notna().any() if "porpag" in df.columns else False
    bpm_min, bpm_max = slider_range("bpm", 0.1) if has_bpm else (0, 0)
    porpag_min, porpag_max = slider_range("porpag", 0.1) if has_porpag else (0, 0)
    conf_choices = {c["conf"]: c["confName"]
                    for c in sorted(conferences, key=lambda x: x["confName"])}
    transfer_tag_choices = {
        key: label
        for key, label in TRANSFER_TAG_FILTERS.items()
        if prefix == "d1" and key in df.columns
    }
    recruiting_tag_choices = {
        "none": "None",
        **{
            key: label
            for key, label in RECRUITING_TAG_FILTERS.items()
            if prefix == "d1" and key in df.columns
        },
    }
    transfer_tag_filter = (
        ui.div({"class": "sb-section tag-filter-section"},
               ui.div("Transfer Status", class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_transfer_tags", None, choices=transfer_tag_choices),
        )
        if transfer_tag_choices else ui.div()
    )
    recruiting_tag_filter = (
        ui.div({"class": "sb-section tag-filter-section"},
               ui.div("Former Ranked Recruit", class_="sb-section-head"),
               ui.input_select(f"{prefix}_recruiting_tag", None,
                               choices=recruiting_tag_choices, selected="none"),
        )
        if len(recruiting_tag_choices) > 1 else ui.div()
    )
    bpm_filter = (
        ui.div(ui.div("BPM", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_bpm", None, min=bpm_min, max=bpm_max,
                               value=[bpm_min, bpm_max], step=0.1),
               class_="sb-section")
        if has_bpm else ui.div()
    )
    porpag_filter = (
        ui.div(ui.div("PORPAG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_porpag", None, min=porpag_min, max=porpag_max,
                               value=[porpag_min, porpag_max], step=0.1),
               class_="sb-section")
        if has_porpag else ui.div()
    )
    has_archetype_v2 = prefix == "d1" and "archetype_v2_primary_code" in df.columns
    archetype_v2_filter = (
        ui.div(
            ui.div(
                ui.span("Archetype"),
                ui.tags.button(
                    "clear",
                    class_="clear-btn",
                    onclick=f"Shiny.setInputValue('{prefix}_clear_arch_v2',Math.random())",
                ),
                class_="sb-section-head",
            ),
            ui.input_checkbox_group(
                f"{prefix}_archetypes_v2",
                None,
                choices={code: archetype_v2_label(code) for code in ARCHETYPE_V2_ORDER},
            ),
            class_="sb-section",
        )
        if has_archetype_v2 else ui.div()
    )
    archetype_v2_score_filter = (
        ui.div(
            ui.div("Minimum archetype score", class_="sb-section-head"),
            ui.input_slider(
                f"{prefix}_score_v2_min",
                None,
                min=0,
                max=100,
                value=0,
                step=1,
            ),
            class_="sb-section",
        )
        if has_archetype_v2 else ui.div()
    )
    low_sample_toggle = (
        ui.div(
            ui.div("Sample Size", class_="sb-section-head"),
            ui.input_checkbox(f"{prefix}_exclude_low_sample", "Exclude low sample size", value=False),
            ui.input_checkbox(f"{prefix}_exclude_unstable_archetypes", "Exclude unstable archetypes", value=False),
            class_="sb-section",
        )
        if prefix == "d1" and "low_sample_size" in df.columns else ui.div()
    )
    shot_profile_filters = (
        ui.div(
            ui.div("Overall Assisted FG%", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_assisted_fg_pct", None, min=assisted_fg_pct_min, max=assisted_fg_pct_max,
                            value=[assisted_fg_pct_min, assisted_fg_pct_max], step=0.01),
            ui.div("Rim Share", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_rim_share", None, min=rim_share_min, max=rim_share_max,
                            value=[rim_share_min, rim_share_max], step=0.01),
            ui.div("Mid Share", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_mid_share", None, min=mid_share_min, max=mid_share_max,
                            value=[mid_share_min, mid_share_max], step=0.01),
            ui.div("Rim FG%", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_rim_fg_pct", None, min=rim_fg_pct_min, max=rim_fg_pct_max,
                            value=[rim_fg_pct_min, rim_fg_pct_max], step=0.01),
            ui.div("Mid FG%", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_mid_fg_pct", None, min=mid_fg_pct_min, max=mid_fg_pct_max,
                            value=[mid_fg_pct_min, mid_fg_pct_max], step=0.01),
            ui.div("Rim Assisted%", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_rim_assisted_pct", None, min=rim_ast_pct_min, max=rim_ast_pct_max,
                            value=[rim_ast_pct_min, rim_ast_pct_max], step=0.01),
            ui.div("Mid Assisted%", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_mid_assisted_pct", None, min=mid_ast_pct_min, max=mid_ast_pct_max,
                            value=[mid_ast_pct_min, mid_ast_pct_max], step=0.01),
            ui.div("3PT Assisted%", class_="sb-section-head"),
            ui.input_slider(f"{prefix}_three_assisted_pct", None, min=three_ast_pct_min, max=three_ast_pct_max,
                            value=[three_ast_pct_min, three_ast_pct_max], step=0.01),
            class_="sb-section",
        )
        if prefix == "d1" and "assisted_fg_pct" in df.columns else ui.div()
    )

    return ui.div(
        {"class": "sidebar"},
        ui.div("Filters", class_="sb-title"),
        snapshot_note(D1["retrieved_at"]) if prefix == "d1" and D1_PREVIEW_SNAPSHOT else None,
        low_sample_toggle,
        ui.div(ui.div("Search by name", class_="sb-section-head"),
               ui.input_text(f"{prefix}_q", None, placeholder="e.g. Marcus Jackson"),
               class_="sb-section"),
        ui.div(ui.div("Qualified UCSD Position", class_="sb-section-head"),
               ui.input_select(
                   f"{prefix}_qualification_filter",
                   None,
                   choices=QUALIFICATION_FILTERS,
                   selected="none",
               ),
               class_="sb-section"),
        transfer_tag_filter,
        recruiting_tag_filter,
        ui.div(ui.div(ui.span("Most Similar UCSD Position"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_arch',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_archetypes", None,
                                       choices={a: archetype_label(a) for a in ARCHETYPE_ORDER}),
               class_="sb-section"),
        ui.div(ui.div("Minimum UCSD Position Score", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_score_min", None, min=0, max=100,
                               value=0, step=1),
               class_="sb-section"),
        archetype_v2_filter,
        archetype_v2_score_filter,
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
        ui.div(ui.div(ui.span("Eligibility Used"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_eligibility',Math.random())"),
                      class_="sb-section-head"),
               ui.input_slider(f"{prefix}_eligibility", None,
                               min=eligibility_min, max=eligibility_max,
                               value=[eligibility_min, eligibility_max], step=1),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Conference"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_conf',Math.random())"),
                      class_="sb-section-head"),
               ui.input_checkbox_group(f"{prefix}_confs", None, choices=conf_choices),
               class_="sb-section"),
        ui.div(ui.div(ui.span("Team"),
                      ui.tags.button("clear", class_="clear-btn",
                          onclick=f"Shiny.setInputValue('{prefix}_clear_team',Math.random())"),
                      class_="sb-section-head"),
               ui.input_selectize(
                   f"{prefix}_team",
                   None,
                   choices=sorted(df["team"].unique().tolist()),
                   multiple=True,
                   options={"placeholder": "Search teams..."},
               ),
               class_="sb-section"),
        ui.div(ui.div("MPG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_mpg", None, min=mpg_min, max=mpg_max,
                               value=[mpg_min, mpg_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("PPG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ppg_range", None, min=ppg_min, max=ppg_max,
                               value=[ppg_min, ppg_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("eFG%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_efg", None, min=efg_min, max=efg_max,
                               value=[efg_min, efg_max], step=0.01),
               class_="sb-section"),
        ui.div(ui.div("ORB%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_orb_pct", None, min=orb_pct_min, max=orb_pct_max,
                               value=[orb_pct_min, orb_pct_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "orb_pct" in df.columns and pd.to_numeric(df["orb_pct"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("DRB%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_drb_pct", None, min=drb_pct_min, max=drb_pct_max,
                               value=[drb_pct_min, drb_pct_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "drb_pct" in df.columns and pd.to_numeric(df["drb_pct"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("AST%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ast_pct", None, min=ast_pct_min, max=ast_pct_max,
                               value=[ast_pct_min, ast_pct_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "ast_pct" in df.columns and pd.to_numeric(df["ast_pct"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("STL%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_stl_pct", None, min=stl_pct_min, max=stl_pct_max,
                               value=[stl_pct_min, stl_pct_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "stl_pct" in df.columns and pd.to_numeric(df["stl_pct"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("BLK%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_blk_pct", None, min=blk_pct_min, max=blk_pct_max,
                               value=[blk_pct_min, blk_pct_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "blk_pct" in df.columns and pd.to_numeric(df["blk_pct"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("3P%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_tp_range", None, min=tp_min, max=tp_max,
                               value=[tp_min, tp_max], step=0.01),
               class_="sb-section"),
        ui.div(ui.div("FT%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ft_range", None, min=ft_min, max=ft_max,
                               value=[ft_min, ft_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "ft" in df.columns and pd.to_numeric(df["ft"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("USG%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_usg_range", None, min=usg_min, max=usg_max,
                               value=[usg_min, usg_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "usg" in df.columns and pd.to_numeric(df["usg"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("FTR", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ftr_range", None, min=ftr_min, max=ftr_max,
                               value=[ftr_min, ftr_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "ftr" in df.columns and pd.to_numeric(df["ftr"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("TOV%", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_tov_pct_range", None, min=tov_pct_min, max=tov_pct_max,
                               value=[tov_pct_min, tov_pct_max], step=0.01),
               class_="sb-section")
        if prefix == "d1" and "tov_pct" in df.columns and pd.to_numeric(df["tov_pct"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("PF/40", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_pf40_range", None, min=pf40_min, max=pf40_max,
                               value=[pf40_min, pf40_max], step=0.1),
               class_="sb-section")
        if prefix == "d1" and "pf_per_40" in df.columns and pd.to_numeric(df["pf_per_40"], errors="coerce").notna().any() else ui.div(),
        ui.div(ui.div("3P Share", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_three_share", None, min=three_share_min, max=three_share_max,
                               value=[three_share_min, three_share_max], step=0.01),
               class_="sb-section"),
        shot_profile_filters,
        ui.div(ui.div("APG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_apg_range", None, min=apg_min, max=apg_max,
                               value=[apg_min, apg_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("TOV/G", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_tov_range", None, min=tov_min, max=tov_max,
                               value=[tov_min, tov_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("Fouls/G", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_pf_range", None, min=pf_min, max=pf_max,
                               value=[pf_min, pf_max], step=0.1),
               class_="sb-section")
        if prefix == "d1" and "pf" in df.columns and pd.to_numeric(df["pf"], errors="coerce").notna().any() else ui.div(),
        bpm_filter,
        porpag_filter,
        ui.div(ui.div("AST/TOV ratio", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_ast_tov", None, min=ato_min, max=ato_max,
                               value=[ato_min, ato_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("RPG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_rpg_range", None, min=rpg_min, max=rpg_max,
                               value=[rpg_min, rpg_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("DRPG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_drb_range", None, min=drb_min, max=drb_max,
                               value=[drb_min, drb_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("BPG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_bpg_range", None, min=bpg_min, max=bpg_max,
                               value=[bpg_min, bpg_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("SPG", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_spg_range", None, min=spg_min, max=spg_max,
                               value=[spg_min, spg_max], step=0.1),
               class_="sb-section"),
        ui.div(ui.div("Height", class_="sb-section-head"),
               ui.input_slider(f"{prefix}_height", None, min=h_min, max=h_max,
                               value=[h_min, h_max], step=1),
               class_="sb-section"),
        ui.div(
            {"class": "sb-count"},
            ui.div(
                ui.span("Showing", class_="lbl"),
                ui.output_text(f"{prefix}_filter_count"),
            ),
            ui.div(
                ui.span("Filtered Out", class_="lbl"),
                ui.output_text(f"{prefix}_filtered_out_count"),
            ),
        ),
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

def apply_qualification_filter(df, mode):
    mode = mode or "none"
    qual_col = QUALIFICATION_FILTER_COLUMNS.get(mode)
    if qual_col is None or qual_col not in df.columns:
        return df
    return df[df[qual_col]]

def apply_archetype_score_filter(df, mode, min_score):
    mode = mode or "none"
    score_col = {
        "pg": "score_pg_combo_qualified_pool",
        "wing": "score_wing_2_4_qualified_pool",
        "big": "score_stretch_big_qualified_pool",
    }.get(mode, "primary_score")
    if score_col not in df.columns:
        score_col = "primary_score"
    scores = pd.to_numeric(df[score_col], errors="coerce").fillna(-1)
    return df[scores >= min_score]


def apply_archetype_v2_score_filter(df, min_score):
    if "archetype_v2_primary_weight" not in df.columns:
        return df
    if float(min_score or 0) <= 0:
        return df
    scores = pd.to_numeric(df["archetype_v2_primary_weight"], errors="coerce").fillna(-1) * 100
    return df[scores >= min_score]

def apply_tag_filters(df, tags):
    valid_tags = [tag for tag in tags or [] if tag in df.columns]
    if not valid_tags:
        return df
    for tag in valid_tags:
        df = df[df[tag].fillna(False)]
    return df

def apply_single_tag_filter(df, tag):
    if tag and tag != "none" and tag in df.columns:
        return df[df[tag].fillna(False)]
    return df


def qualification_diagnostic_items(df, mode):
    mode = mode or "none"
    total = len(df)
    if mode == "none" or total == 0:
        return []

    def item(label, mask):
        passed = int(mask.fillna(False).sum())
        removed = total - passed
        return {
            "label": label,
            "passed": passed,
            "removed": removed,
            "removed_pct": removed / total * 100,
            "remaining_pct": passed / total * 100,
        }

    t = QUALIFICATION_CONFIG["thresholds"]
    if mode == "general":
        is_guard = df["pos"].isin(["G", "G/F"])
        has_true_dreb_pct = df["dreb_source"].eq("DRB_pct")
        dreb_ok = np.where(
            has_true_dreb_pct,
            np.where(
                is_guard,
                df["dreb_arch"] >= t["general"]["guard_dreb_raw"],
                df["dreb_arch"] >= t["general"]["nonguard_dreb_raw"],
            ),
            df["DRB_pct_pctile"] >= t["general"]["ast_tov_pctile"],
        )
        return [
            item("AST% pctile >= 70", df["AST_pct_pctile"] >= t["general"]["ast_pctile"]),
            item("eFG% >= 50", df["efg"] >= t["general"]["efg"]),
            item("3P% >= 30", df["tp"] >= t["general"]["three_pct"]),
            item("AST/TO pctile >= 50", df["AST_TOV_pctile"] >= t["general"]["ast_tov_pctile"]),
            item("DREB requirement", pd.Series(dreb_ok, index=df.index)),
            item("General filter", df["qual_general"]),
        ]
    if mode == "pg":
        return [
            item("AST% pctile >= 70", df["AST_pct_pctile"] >= t["pg"]["ast_pctile"]),
            item("AST/TO pctile >= 70", df["AST_TOV_pctile"] >= t["pg"]["ast_tov_pctile"]),
            item("3P% >= 33", df["tp"] >= t["pg"]["three_pct"]),
            item("3P rate >= 30", df["three_share"] >= t["pg"]["three_rate"]),
            item("2P% pctile >= 70", df["2P_pct_pctile"] >= t["pg"]["exception_two_pct_pctile"]),
            item("PG filter", df["qual_pg_combo"]),
        ]
    if mode == "wing":
        return [
            item("DREB pctile >= 70", df["DRB_pct_pctile"] >= t["wing"]["dreb_pctile"]),
            item("3P% >= 33", df["tp"] >= t["wing"]["three_pct"]),
            item("3P rate >= 30", df["three_share"] >= t["wing"]["three_rate"]),
            item("AST/TO pctile >= 50", df["AST_TOV_pctile"] >= t["wing"]["ast_tov_pctile"]),
            item("Wing filter", df["qual_wing_2_4"]),
        ]
    if mode == "big":
        return [
            item("Height >= 6'7\"", df["heightIn"] >= t["big"]["height"]),
            item("DREB pctile >= 70", df["DRB_pct_pctile"] >= t["big"]["dreb_pctile"]),
            item("3P% >= 30", df["tp"] >= t["big"]["three_pct"]),
            item("3P rate >= 25", df["three_share"] >= t["big"]["three_rate"]),
            item("AST/TO pctile >= 50", df["AST_TOV_pctile"] >= t["big"]["ast_tov_pctile"]),
            item("Big filter", df["qual_stretch_big"]),
        ]
    return []

def make_qualification_diagnostics(df, mode):
    items = qualification_diagnostic_items(df, mode)
    if not items:
        return ui.div()
    rows = [
        ui.div(
            f"{x['label']}: {x['passed']} pass, {x['removed']} removed "
            f"({x['removed_pct']:.0f}% removed, {x['remaining_pct']:.0f}% remain)",
            class_="qual-diag-row",
        )
        for x in items
    ]
    extras = []
    if mode == "general":
        extras = [
            ui.div(
                f"Standard path: {int(df['qual_general_standard'].sum())} · "
                f"Exception path: {int(df['qual_general_exception'].sum())}",
                class_="qual-diag-row",
            )
        ]
    elif mode == "pg":
        extras = [
            ui.div(
                f"Standard path: {int(df['qual_pg_standard'].sum())} · "
                f"Exception path: {int(df['qual_pg_exception'].sum())}",
                class_="qual-diag-row",
            )
        ]
    return ui.div(
        ui.div("Threshold diagnostics", class_="qual-diag-title"),
        *rows,
        *extras,
        class_="qual-diag",
    )

# ─────────────────────────────────────────────────────────────────────────
# APP UI
# ─────────────────────────────────────────────────────────────────────────

def dashboard_tab(tab, label, *, selected=False):
    return ui.tags.button(
        label, id=f"btn-{tab}", type="button",
        class_=f"tab-btn active-{tab}" if selected else "tab-btn",
        aria_controls=f"{tab}-tab", aria_current="page" if selected else None,
        onclick=f"switchTab('{tab}')",
    )


def dashboard_menu(label, *pages, primary=None):
    return ui.div(
        primary,
        ui.tags.details(
            ui.tags.summary(
                label if primary is None else None,
                ui.span("▾", class_="tab-menu-caret", aria_hidden="true"),
                class_="tab-btn tab-menu-toggle",
                aria_label=f"{label} pages" if primary is not None else None,
            ),
            ui.div(*pages, class_="tab-menu-pages"),
            class_="tab-menu",
        ),
        class_="tab-group tab-group-more" if primary is None else "tab-group",
    )


app_ui = ui.page_fluid(
    ui.tags.head(
        ui.tags.link(rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;0,8..60,700;1,8..60,400;1,8..60,500&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"),
        ui.include_css(str(HERE / "www" / "styles.css"), method="inline"),
        ui.include_css(str(HERE / "ratings" / "page" / "styles.css"), method="inline"),
        ui.tags.style("""
            /* ── Tab bar ─────────────────────────────────────── */
            #tab-switcher {
                position:relative; z-index:2;
                display:flex; flex-wrap:wrap; gap:0 4px; align-items:center;
                padding:0 28px; background:var(--bg);
                border-bottom:1px solid var(--rule);
                min-height:38px; flex-shrink:0; white-space:nowrap;
            }
            .tab-btn {
                font-family:var(--sans); font-size:11px; font-weight:600;
                letter-spacing:.10em; text-transform:uppercase;
                color:var(--ink-2); background:none; border:none;
                border-bottom:2px solid transparent;
                padding:0 14px; height:38px; cursor:pointer;
                flex:0 0 auto;
                transition:color .15s, border-color .15s;
            }
            .tab-btn:hover     { color:var(--ink); }
            .tab-btn.active-d1 { color:#4a9eed;       border-bottom-color:#4a9eed; }
            .tab-btn.active-ratings { color:var(--accent); border-bottom-color:var(--accent); }
            .tab-btn.active-d2 { color:var(--accent);  border-bottom-color:var(--accent); }
            .tab-btn.active-d3 { color:#e8a44a;        border-bottom-color:#e8a44a; }
            .tab-btn.active-info { color:var(--ink);    border-bottom-color:var(--ink); }
            .tab-btn.active-wl { color:#7cc47a;         border-bottom-color:#7cc47a; }
            .tab-btn.active-ucsd { color:var(--accent); border-bottom-color:var(--accent); }
            .tab-btn.active-hist { color:#c9d6f0;       border-bottom-color:#c9d6f0; }
            .tab-btn.active-sim-beta { color:#f0cb67;   border-bottom-color:#f0cb67; }
            .tab-btn.active-triton { color:#c8a84b;     border-bottom-color:#c8a84b; }
            .tab-group { display:flex; position:relative; align-items:center; }
            .tab-group > .tab-btn { padding-right:4px; }
            .tab-menu-toggle { display:flex; align-items:center; gap:6px; list-style:none; }
            .tab-menu-toggle::-webkit-details-marker { display:none; }
            .tab-group:not(.tab-group-more) .tab-menu-toggle { padding:0 10px 0 6px; }
            .tab-menu-caret { display:inline-block; }
            .tab-menu[open] .tab-menu-caret { transform:rotate(180deg); }
            .tab-group:has(.tab-menu [aria-current="page"]) > .tab-btn,
            .tab-group-more:has([aria-current="page"]) .tab-menu-toggle {
                color:var(--accent); border-bottom-color:var(--accent);
            }
            .tab-menu-pages {
                position:absolute; top:100%; left:0; min-width:100%;
                display:grid; gap:2px; padding:6px;
                border:1px solid var(--rule); border-radius:8px;
                background:var(--bg-2); box-shadow:0 8px 24px #0004;
            }
            .tab-group-more .tab-menu-pages { left:auto; right:0; }
            .tab-menu-pages .tab-btn { text-align:left; border-radius:4px; }
            .tab-menu-pages .tab-btn:hover { background:var(--bg); }
            #tab-switcher .tab-btn:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
            @media (max-width: 760px) {
                #tab-switcher { padding:0 8px; }
                .tab-group { position:static; }
                .tab-menu-pages, .tab-group-more .tab-menu-pages {
                    left:8px; right:8px; min-width:0;
                }
            }
            .build-stamp {
                display:inline-flex; align-items:center; width:fit-content;
                margin-top:10px; padding:6px 10px;
                border:1px solid #8a5f0e; border-radius:999px;
                color:#f0cb67; background:rgba(138,95,14,.12);
                font-family:var(--mono); font-size:10px; font-weight:700;
                letter-spacing:.12em; text-transform:uppercase;
            }

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
            #detail-body, .detail-col, .player-name, .sim-main .nm, .sim-action,
            .wl-card-name, .wl-stat .n, .wl-title {
                color:var(--ink);
            }
            .star-btn {
                background:none; border:none; cursor:pointer;
                font-size:24px; line-height:1; padding:2px 0 0 0;
                flex-shrink:0; transition:color .15s, transform .1s;
            }
            .star-btn:hover { transform:scale(1.2); }
            .statline-toggle .pill-btn {
                background:transparent;
                color:var(--ink-3);
                border:1px solid var(--rule);
                border-radius:999px;
                padding:6px 12px;
                font-family:var(--sans);
                font-size:10px;
                font-weight:700;
                letter-spacing:.10em;
                text-transform:uppercase;
                cursor:pointer;
                transition:all .15s ease;
            }
            .statline-toggle .pill-btn.active {
                color:var(--bg);
                background:var(--accent);
                border-color:var(--accent);
            }
            .statline-header {
                display:flex;
                justify-content:space-between;
                align-items:flex-end;
                gap:12px;
                border-bottom:1px solid var(--ink-2);
                padding-bottom:10px;
                margin-bottom:18px;
            }
            .statline-header .col-title {
                border-bottom:none;
                padding-bottom:0;
                margin-bottom:0;
            }
            .statline-header .statline-toggle {
                display:flex;
                gap:8px;
                align-items:center;
            }
            .sample-badge {
                display:inline-block;
                margin-top:8px;
                padding:4px 8px;
                border-radius:999px;
                background:rgba(200,168,75,.18);
                color:#f0d58a;
                border:1px solid rgba(200,168,75,.45);
                font-family:var(--mono);
                font-size:10px;
                letter-spacing:.08em;
                text-transform:uppercase;
            }
            .pill-btn {
                background:transparent;
                color:var(--ink-3);
                border:1px solid var(--rule);
                border-radius:999px;
                padding:6px 12px;
                font-family:var(--sans);
                font-size:10px;
                font-weight:700;
                letter-spacing:.10em;
                text-transform:uppercase;
                cursor:pointer;
                transition:all .15s ease;
            }
            .pill-btn:hover {
                color:var(--ink);
                border-color:var(--ink-2);
            }
            .pill-btn.active {
                color:var(--bg);
                background:var(--accent);
                border-color:var(--accent);
            }
            .shot-profile-shell {
                display:grid;
                grid-template-columns:220px 1fr;
                gap:14px;
                align-items:start;
                margin-top:8px;
            }
            .shot-profile-pie {
                background:rgba(255,255,255,0.02);
                border:1px solid var(--rule);
                padding:8px;
            }
            .shot-profile-assists {
                display:grid;
                gap:8px;
                height:220px;
                grid-template-rows:repeat(3, 1fr);
            }
            .shot-profile-card {
                border:1px solid var(--rule);
                background:rgba(255,255,255,0.02);
                padding:8px 10px;
                display:flex;
                flex-direction:column;
                justify-content:center;
            }
            .shot-profile-card .k {
                font-size:10px;
                letter-spacing:.12em;
                text-transform:uppercase;
                color:var(--ink-3);
                margin-bottom:4px;
            }
            .shot-profile-card .v {
                font-family:var(--serif);
                font-size:18px;
                color:var(--ink);
                line-height:1;
            }
            .shot-profile-card .s {
                color:var(--ink-2);
                font-size:11px;
                line-height:1.4;
                margin-top:6px;
            }
            .sim-action {
                min-width:84px;
                text-align:right;
                align-self:center;
                font-family:var(--mono);
                font-size:11px;
                font-weight:600;
                letter-spacing:.08em;
                text-transform:uppercase;
                color:var(--ink-3);
            }
            #compare-detail-body {
                display:flex;
                flex-direction:column;
                height:min(78vh, calc(100vh - 148px));
                max-height:calc(100vh - 148px);
                min-height:0;
            }
            .compare-modal-shell {
                display:grid;
                gap:14px;
                flex:1 1 auto;
                min-height:0;
                height:100%;
                max-height:100%;
                overflow-y:auto !important;
                overscroll-behavior:contain;
                -webkit-overflow-scrolling:touch;
                padding-right:6px;
            }
            .compare-player-grid {
                display:grid;
                grid-template-columns:repeat(2, minmax(0, 1fr));
                gap:12px;
                flex:0 0 auto;
                margin-bottom:14px;
            }
            .compare-player-card,
            .compare-section {
                border:1px solid var(--rule);
                background:rgba(255,255,255,0.02);
                padding:12px 14px;
            }
            .compare-player-head {
                display:flex;
                align-items:flex-start;
                justify-content:space-between;
                gap:12px;
            }
            .compare-player-name {
                font-family:var(--serif);
                font-size:26px;
                font-weight:600;
                line-height:1.05;
                color:var(--ink);
                margin-bottom:6px;
            }
            .compare-player-inline-btn {
                white-space:nowrap;
                flex:0 0 auto;
            }
            .historical-profile-name-row {
                display:flex;
                flex-direction:column-reverse;
                align-items:stretch;
                gap:14px;
                margin-bottom:4px;
            }
            .historical-profile-name-row .player-name {
                min-width:0;
                margin-bottom:0;
                overflow-wrap:normal;
                word-break:normal;
                hyphens:auto;
            }
            .historical-profile-actions {
                display:flex;
                align-items:flex-start;
                gap:8px;
                flex-wrap:wrap;
                justify-content:flex-start;
                max-width:100%;
            }
            .historical-profile-close {
                flex:0 0 auto;
                margin-top:2px;
                border:1px solid var(--rule-2);
                background:rgba(73,106,164,.10);
                color:var(--ink);
                min-height:40px;
                padding:10px 14px;
                cursor:pointer;
                font-family:var(--mono);
                font-size:11px;
                font-weight:800;
                letter-spacing:.12em;
                text-transform:uppercase;
            }
            .historical-profile-close:hover {
                border-color:var(--ink-2);
                background:rgba(73,106,164,.18);
            }
            .triton-tracker-toggle {
                flex:0 0 auto;
                margin-top:2px;
                white-space:nowrap;
                border:1px solid rgba(240,203,103,.88);
                background:rgba(240,203,103,.16);
                color:#f6d776;
                min-height:40px;
                padding:10px 12px;
                font-family:var(--mono);
                font-size:10px;
                font-weight:800;
                letter-spacing:.10em;
                text-transform:uppercase;
                cursor:pointer;
                box-shadow:0 0 0 1px rgba(240,203,103,.08), 0 10px 24px rgba(0,0,0,.18);
                transition:background .14s ease, color .14s ease, border-color .14s ease, transform .14s ease;
            }
            .triton-tracker-toggle:hover {
                transform:translateY(-1px);
                background:rgba(240,203,103,.24);
                border-color:#f6d776;
            }
            .triton-tracker-toggle.is-tracked {
                background:#f0cb67;
                color:#101722;
                border-color:#f0cb67;
            }
            @media (max-width: 780px) {
                .historical-profile-actions {
                    justify-content:flex-start;
                }
            }
            .compare-player-sub {
                color:var(--ink-3);
                font-size:12px;
            }
            .compare-missing-note {
                border:1px dashed rgba(240,203,103,.34);
                background:rgba(240,203,103,.06);
                color:var(--ink-3);
                font-family:var(--mono);
                font-size:11px;
                letter-spacing:.04em;
                padding:9px 11px;
            }
            .compare-section-title {
                font-size:11px;
                font-weight:700;
                letter-spacing:.14em;
                text-transform:uppercase;
                color:var(--ink-3);
                margin-bottom:10px;
            }
            .compare-grade-row,
            .compare-stat-head,
            .compare-stat-row,
            .compare-footer {
                display:grid;
                grid-template-columns:minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr);
                gap:10px;
                align-items:center;
            }
            .compare-grade-row {
                grid-template-columns:minmax(0, 1fr) minmax(0, 1fr);
                margin-bottom:10px;
            }
            .compare-grade-pill {
                display:inline-flex;
                align-items:center;
                justify-content:center;
                padding:6px 8px;
                border:1px solid var(--rule);
                background:rgba(255,255,255,0.02);
                font-family:var(--mono);
                font-size:11px;
                color:var(--ink-2);
            }
            .compare-stat-head {
                padding-bottom:8px;
                border-bottom:1px solid var(--rule);
                margin-bottom:4px;
                color:var(--ink-3);
                font-size:10px;
                font-weight:700;
                letter-spacing:.12em;
                text-transform:uppercase;
            }
            .compare-stat-row {
                padding:8px 0;
                border-bottom:1px solid rgba(255,255,255,0.04);
            }
            .compare-stat-row:last-child {
                border-bottom:none;
                padding-bottom:0;
            }
            .compare-stat-label {
                color:var(--ink-2);
            }
            .compare-stat-player,
            .compare-stat-value {
                text-align:right;
                color:var(--ink);
                font-family:var(--mono);
            }
            .compare-footer {
                grid-template-columns:repeat(2, max-content);
                justify-content:flex-end;
            }

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
            #sim-beta-tab.tab-panel.active {
                overflow-y:auto;
                -webkit-overflow-scrolling:touch;
            }
            #hist-tab.tab-panel.active {
                overflow-y:auto;
                -webkit-overflow-scrolling:touch;
            }
            #triton-tab.tab-panel.active {
                overflow-y:auto;
                -webkit-overflow-scrolling:touch;
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
            .sidebar .selectize-input.items {
                min-height:38px !important; display:flex !important;
                flex-wrap:wrap !important; gap:4px !important; align-items:center !important;
            }
            .sidebar .selectize-input > .item {
                background:var(--accent) !important; color:var(--bg) !important;
                border:none !important; border-radius:2px !important;
                padding:2px 7px !important; text-shadow:none !important;
            }
            .sidebar .selectize-input > input { color:var(--ink) !important; }
            .sidebar .selectize-dropdown {
                background:var(--bg) !important; border:1px solid var(--rule-2) !important;
                color:var(--ink) !important;
            }
            .sidebar .selectize-dropdown .option {
                color:var(--ink) !important; background:var(--bg) !important;
            }
            .sidebar .selectize-dropdown .active {
                background:var(--bg-2) !important; color:var(--ink) !important;
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
            .sidebar .tag-filter-section .checkbox label {
                align-items:flex-start !important;
                max-width:100% !important;
                white-space:normal !important;
                overflow:visible !important;
                text-overflow:clip !important;
                line-height:1.35 !important;
                padding-top:5px !important;
                padding-bottom:5px !important;
            }
            .sidebar .tag-filter-section .checkbox label::before {
                margin-top:.35em;
            }

            /* ── Division badge in modal ── */
            .div-badge {
                font-size:10px; font-weight:700; letter-spacing:.12em;
                text-transform:uppercase; border-radius:3px;
                padding:2px 7px; margin-left:6px;
                background:var(--bg-2); color:var(--ink-2); vertical-align:middle;
            }

            /* ── Similarity beta tab ── */
            .similarity-beta-shell {
                padding:26px 28px 34px;
                display:flex;
                flex-direction:column;
                gap:14px;
                min-height:max-content;
            }
            #triton_tracker_ui.recalculating,
            #triton_tracker_ui.recalculating .similarity-beta-shell {
                opacity:1 !important;
                pointer-events:auto !important;
            }
            .similarity-beta-topbar {
                display:flex;
                justify-content:space-between;
                align-items:flex-end;
                gap:22px;
                border:1px solid var(--rule);
                background:rgba(19,27,41,.72);
                padding:22px 24px;
            }
            .similarity-beta-title {
                color:var(--ink);
                font-family:var(--serif);
                font-size:44px;
                line-height:1;
            }
            .similarity-beta-subtitle {
                margin-top:8px;
                color:var(--ink-3);
                font-family:var(--sans);
                font-size:13px;
                max-width:640px;
            }
            .similarity-beta-refresh-note {
                color:#f0cb67;
                font-family:var(--mono);
                font-size:11px;
                text-transform:uppercase;
                letter-spacing:.10em;
                white-space:nowrap;
            }
            .similarity-beta-grid {
                display:grid;
                grid-template-columns:repeat(3, minmax(0, 1fr));
                gap:16px;
            }
            .similarity-beta-card {
                min-width:0;
                border:1px solid var(--rule);
                background:rgba(19,27,41,.72);
                padding:18px;
            }
            .similarity-beta-section-head {
                display:flex;
                justify-content:space-between;
                align-items:center;
                gap:12px;
                margin:10px 0 0;
                color:var(--ink-2);
                font-family:var(--mono);
                font-size:12px;
                font-weight:800;
                letter-spacing:.14em;
                text-transform:uppercase;
            }
            .similarity-beta-section-count {
                color:#f0cb67;
                font-size:11px;
            }
            .similarity-beta-tracked-empty {
                border:1px dashed rgba(240,203,103,.36);
                background:rgba(240,203,103,.05);
                color:var(--ink-3);
                font-family:var(--mono);
                font-size:12px;
                letter-spacing:.04em;
                padding:16px 18px;
            }
            .similarity-beta-card-head {
                display:flex;
                justify-content:space-between;
                align-items:flex-start;
                gap:14px;
                padding-bottom:14px;
                border-bottom:1px solid rgba(89,113,154,.24);
            }
            .similarity-beta-ideal-name {
                color:var(--ink);
                font-family:var(--serif);
                font-size:28px;
                line-height:1.05;
            }
            .similarity-beta-ideal-meta,
            .similarity-beta-team {
                margin-top:5px;
                color:var(--ink-3);
                font-family:var(--mono);
                font-size:11px;
                line-height:1.35;
            }
            .similarity-beta-pill {
                flex:0 0 auto;
                color:#f0cb67;
                border:1px solid rgba(240,203,103,.44);
                background:rgba(240,203,103,.08);
                border-radius:999px;
                padding:5px 8px;
                font-family:var(--mono);
                font-size:10px;
                font-weight:700;
                letter-spacing:.10em;
                text-transform:uppercase;
            }
            .similarity-beta-ideal-stats {
                display:grid;
                grid-template-columns:repeat(4, minmax(0, 1fr));
                gap:10px;
                margin:14px 0 16px;
            }
            .similarity-beta-ideal-stats div {
                border:1px solid rgba(89,113,154,.24);
                background:rgba(10,16,27,.35);
                padding:9px 10px;
                min-width:0;
            }
            .similarity-beta-ideal-stats span {
                display:block;
                color:var(--ink-3);
                font-family:var(--mono);
                font-size:10px;
                letter-spacing:.08em;
                text-transform:uppercase;
            }
            .similarity-beta-ideal-stats b {
                display:block;
                margin-top:4px;
                color:var(--ink);
                font-family:var(--sans);
                font-size:17px;
                font-weight:700;
            }
            .similarity-beta-table-head,
            .similarity-beta-row {
                display:grid;
                grid-template-columns:32px 42px minmax(0, 1fr) 48px 48px 48px;
                gap:10px;
                align-items:center;
            }
            .similarity-beta-table-head {
                color:var(--ink-2);
                font-family:var(--sans);
                font-size:10px;
                font-weight:700;
                letter-spacing:.10em;
                text-transform:uppercase;
                padding-bottom:8px;
                border-bottom:1px solid rgba(89,113,154,.24);
            }
            .similarity-beta-table {
                display:grid;
                gap:0;
            }
            .similarity-beta-row {
                min-height:64px;
                border-bottom:1px solid rgba(89,113,154,.16);
            }
            .similarity-beta-row--clickable {
                cursor:pointer;
                transition:background .14s ease, border-color .14s ease;
            }
            .similarity-beta-row--clickable:hover {
                background:rgba(73,106,164,.12);
                border-color:rgba(201,214,240,.32);
            }
            .similarity-beta-row:last-child {
                border-bottom:none;
            }
            .similarity-beta-rank {
                color:var(--ink);
                font-family:var(--serif);
                font-size:24px;
                line-height:1;
            }
            .similarity-beta-move {
                font-family:var(--mono);
                font-size:13px;
                font-weight:700;
            }
            .similarity-beta-move.up { color:#7cc47a; }
            .similarity-beta-move.down { color:#e06f5f; }
            .similarity-beta-move.flat { color:var(--ink-3); }
            .similarity-beta-player-cell {
                min-width:0;
            }
            .similarity-beta-player {
                color:var(--ink);
                font-family:var(--sans);
                font-size:17px;
                line-height:1.18;
                overflow:hidden;
                text-overflow:ellipsis;
                white-space:nowrap;
            }
            .similarity-beta-stat {
                color:var(--ink-2);
                font-family:var(--mono);
                font-size:12px;
                text-align:right;
            }
            .similarity-beta-empty {
                padding:18px 0 2px;
                color:var(--ink-3);
                font-family:var(--sans);
                font-size:13px;
            }
            .similarity-beta-more {
                width:100%;
                margin-top:14px;
                border:1px solid rgba(240,203,103,.38);
                background:rgba(240,203,103,.08);
                color:#f0cb67;
                min-height:38px;
                cursor:pointer;
                font-family:var(--mono);
                font-size:11px;
                font-weight:700;
                letter-spacing:.10em;
                text-transform:uppercase;
                transition:background .14s ease, border-color .14s ease;
            }
            .similarity-beta-more:hover {
                background:rgba(240,203,103,.14);
                border-color:rgba(240,203,103,.62);
            }
            .similarity-beta-long-list {
                display:grid;
                gap:14px;
                max-height:min(76vh, 760px);
                overflow:auto;
                padding:4px 2px 8px;
            }
            .similarity-beta-long-head {
                border:1px solid var(--rule);
                background:rgba(19,27,41,.72);
                padding:16px 18px;
            }
            .similarity-beta-table--long .similarity-beta-row {
                min-height:58px;
            }
            @media (max-width: 1180px) {
                .similarity-beta-grid {
                    grid-template-columns:repeat(2, minmax(0, 1fr));
                }
            }
            @media (max-width: 760px) {
                .similarity-beta-grid {
                    grid-template-columns:1fr;
                }
                .similarity-beta-shell {
                    padding:18px 16px 24px;
                }
                .similarity-beta-topbar {
                    flex-direction:column;
                    align-items:flex-start;
                    padding:18px;
                }
                .similarity-beta-title {
                    font-size:34px;
                }
                .similarity-beta-refresh-note {
                    white-space:normal;
                }
                .similarity-beta-card {
                    padding:14px;
                }
                .similarity-beta-table-head,
                .similarity-beta-row {
                    grid-template-columns:28px 38px minmax(0, 1fr) 38px 38px 38px;
                }
            }

        """),
        ui.include_css(str(HERE / "pages" / "division_i" / "styles.css"), method="inline"),
        ui.include_css(str(HERE / "pages" / "triton_zone" / "styles.css"), method="inline"),
        ui.include_css(str(HERE / "pages" / "historical_players" / "styles.css"), method="inline"),
        ui.tags.script("""
            var scatterConfigs = {
                d1_scatter: { inputId: 'd1_plot_click' },
                d2_scatter: { inputId: 'd2_plot_click' },
                d3_scatter: { inputId: 'd3_plot_click' }
            };

            function emitScatterSelection(outputId, payload, extra) {
                var cfg = scatterConfigs[outputId];
                if (!cfg || !window.Shiny || !window.Shiny.setInputValue || !payload) return;
                window.Shiny.setInputValue(cfg.inputId, payload, {priority:'event'});
            }

            function pointPayloadFromTarget(wrapper, point) {
                var trace = point.closest('.scatterlayer .trace');
                if (!trace) return null;
                var traceEls = Array.from(wrapper.querySelectorAll('.scatterlayer .trace'));
                var traceIndex = traceEls.indexOf(trace);
                if (traceIndex < 0) return null;
                var pointEls = Array.from(trace.querySelectorAll('.points path'));
                var pointIndex = pointEls.indexOf(point);
                if (pointIndex < 0) return null;
                return { trace_index: traceIndex, point_index: pointIndex };
            }

            function nearestPointPayload(wrapper, clientX, clientY, maxDistance) {
                var traceEls = Array.from(wrapper.querySelectorAll('.scatterlayer .trace'));
                var best = null;
                traceEls.forEach(function(traceEl, traceIndex) {
                    var pointEls = Array.from(traceEl.querySelectorAll('.points path'));
                    pointEls.forEach(function(pointEl, pointIndex) {
                        var rect = pointEl.getBoundingClientRect();
                        var cx = rect.left + rect.width / 2;
                        var cy = rect.top + rect.height / 2;
                        var dx = cx - clientX;
                        var dy = cy - clientY;
                        var distSq = dx * dx + dy * dy;
                        if (!best || distSq < best.distSq) {
                            best = {
                                trace_index: traceIndex,
                                point_index: pointIndex,
                                distSq: distSq
                            };
                        }
                    });
                });
                if (!best) return null;
                if (best.distSq > maxDistance * maxDistance) return null;
                return {
                    trace_index: best.trace_index,
                    point_index: best.point_index
                };
            }

            function bindPlotlyScatterClicks() {
                Object.keys(scatterConfigs).forEach(function(outputId) {
                    var wrapper = document.getElementById(outputId);
                    var graph = wrapper ? wrapper.querySelector('.js-plotly-plot') : null;
                    if (!graph || graph.dataset.codexPlotlyClickBound === '1' || typeof graph.on !== 'function') {
                        return;
                    }
                    graph.on('plotly_hover', function(ev) {
                        var pt = ev && ev.points && ev.points[0];
                        if (!pt) return;
                        var custom = pt.customdata;
                        var playerId = Array.isArray(custom) ? custom[7] : null;
                        graph.dataset.codexHoverPlayerId = playerId || '';
                        graph.dataset.codexHoverTraceIndex = String(pt.curveNumber ?? '');
                        graph.dataset.codexHoverPointIndex = String(pt.pointNumber ?? '');
                        graph.dataset.codexHoverAt = String(Date.now());
                    });
                    graph.on('plotly_unhover', function() {
                        graph.dataset.codexHoverPlayerId = '';
                        graph.dataset.codexHoverTraceIndex = '';
                        graph.dataset.codexHoverPointIndex = '';
                        graph.dataset.codexHoverAt = '0';
                    });
                    graph.dataset.codexPlotlyClickBound = '1';
                });
            }

            function inchesToDisplay(value) {
                var num = Number(value);
                if (!Number.isFinite(num)) return '';
                var whole = Math.round(num);
                var feet = Math.floor(whole / 12);
                var inches = whole % 12;
                return feet + "'" + inches + '"';
            }

            function updateHistoricalHeightSliderLabels() {
                var input = document.getElementById('hist_height');
                if (!input) return;
                var shell = input.parentElement;
                if (!shell) return;
                var from = shell.querySelector('.irs-from');
                var to = shell.querySelector('.irs-to');
                var single = shell.querySelector('.irs-single');
                var raw = String(input.value || '');
                if (!raw) return;
                var parts = raw.split(';');
                if (parts.length >= 1 && from) {
                    from.textContent = inchesToDisplay(parts[0]);
                }
                if (parts.length >= 2 && to) {
                    to.textContent = inchesToDisplay(parts[1]);
                } else if (parts.length >= 1 && single) {
                    single.textContent = inchesToDisplay(parts[0]);
                }
            }

            function styleHistoricalSelectize() {
                document.querySelectorAll('.historical-header-card .selectize-control').forEach(function(control) {
                    var input = control.querySelector('.selectize-input');
                    if (input) {
                        input.style.padding = '14px 42px 14px 22px';
                        input.style.minHeight = '56px';
                        input.style.boxSizing = 'border-box';
                        input.style.display = 'flex';
                        input.style.alignItems = 'center';
                        input.style.alignContent = 'center';
                        input.style.gap = '8px';
                        input.style.border = '1px solid rgba(89,113,154,.34)';
                        input.style.background = 'rgba(10,16,27,.7)';
                    }
                    control.querySelectorAll('.selectize-input > input').forEach(function(textInput) {
                        textInput.style.padding = '0';
                        textInput.style.margin = '0';
                        textInput.style.lineHeight = '1.45';
                        textInput.style.textIndent = '0';
                    });
                    control.querySelectorAll('.selectize-input > .item').forEach(function(item) {
                        item.style.margin = '3px 4px 3px 0';
                    });
                    var caret = control.querySelector('.selectize-input.dropdown-active, .selectize-input.input-active, .selectize-input');
                    if (caret) {
                        caret.style.paddingRight = '42px';
                    }
                });
            }

            function initHistoricalHeightSliderFormatting() {
                var input = document.getElementById('hist_height');
                if (!input || input.dataset.codexHeightLabelsBound === '1') return;
                var sync = function() {
                    window.requestAnimationFrame(updateHistoricalHeightSliderLabels);
                };
                input.addEventListener('change', sync);
                input.addEventListener('input', sync);
                var shell = input.parentElement;
                if (shell && window.MutationObserver) {
                    var observer = new MutationObserver(sync);
                    observer.observe(shell, { childList: true, subtree: true, characterData: true });
                }
                input.dataset.codexHeightLabelsBound = '1';
                sync();
            }

            function historicalScrollState() {
                var panel = document.getElementById('hist-tab');
                var table = document.querySelector('.historical-results-table-card');
                return {
                    panelTop: panel ? panel.scrollTop : 0,
                    tableTop: table ? table.scrollTop : 0,
                    tableLeft: table ? table.scrollLeft : 0
                };
            }

            function restoreHistoricalScrollState(state) {
                if (!state) return;
                var restore = function() {
                    var panel = document.getElementById('hist-tab');
                    var table = document.querySelector('.historical-results-table-card');
                    if (panel) panel.scrollTop = state.panelTop || 0;
                    if (table) {
                        table.scrollTop = state.tableTop || 0;
                        table.scrollLeft = state.tableLeft || 0;
                    }
                };
                restore();
                window.requestAnimationFrame(function() {
                    restore();
                    window.requestAnimationFrame(restore);
                });
            }

            window.ucsdOpenHistoricalProfile = function(rowId) {
                window.__historicalScrollState = historicalScrollState();
                if (window.Shiny && window.Shiny.setInputValue) {
                    window.Shiny.setInputValue('hist_select_row', rowId, {priority:'event'});
                }
                restoreHistoricalScrollState(window.__historicalScrollState);
            };

            function bindDocumentScatterClicks() {
                if (!document.body || document.body.dataset.codexGlobalScatterBound === '1') return;
                document.addEventListener('click', function(ev) {
                    var target = ev.target;
                    if (!(target instanceof Element)) return;
                    var wrapper = target.closest('#d1_scatter, #d2_scatter, #d3_scatter');
                    if (!wrapper) return;
                    var cfg = scatterConfigs[wrapper.id];
                    if (!cfg) return;
                    var graph = wrapper.querySelector('.js-plotly-plot');
                    var hoverPlayerId = graph ? (graph.dataset.codexHoverPlayerId || '') : '';
                    var hoverTraceIndex = graph ? graph.dataset.codexHoverTraceIndex : '';
                    var hoverPointIndex = graph ? graph.dataset.codexHoverPointIndex : '';
                    var hoverAt = graph ? Number(graph.dataset.codexHoverAt || '0') : 0;
                    if (hoverPlayerId && hoverAt && Date.now() - hoverAt < 2000) {
                        window.Shiny.setInputValue(cfg.inputId, {
                            player_id: hoverPlayerId,
                            trace_index: hoverTraceIndex === '' ? null : Number(hoverTraceIndex),
                            point_index: hoverPointIndex === '' ? null : Number(hoverPointIndex)
                        }, {priority:'event'});
                        return;
                    }
                    var point = target.closest('.scatterlayer .points path');
                    var payload = point ? pointPayloadFromTarget(wrapper, point) : null;
                    if (!payload) {
                        payload = nearestPointPayload(wrapper, ev.clientX, ev.clientY, 18);
                    }
                    if (payload && window.Shiny && window.Shiny.setInputValue) {
                        window.Shiny.setInputValue(cfg.inputId, payload, {priority:'event'});
                    }
                }, true);
                document.body.dataset.codexGlobalScatterBound = '1';
            }

            function closeTabMenus(except = null) {
                document.querySelectorAll('#tab-switcher details[open]').forEach(function(menu) {
                    if (menu !== except) menu.open = false;
                });
            }

            document.addEventListener('toggle', function(ev) {
                if (ev.target.matches('#tab-switcher details[open]')) closeTabMenus(ev.target);
            }, true);
            document.addEventListener('click', function(ev) {
                if (!ev.target.closest('#tab-switcher .tab-menu')) closeTabMenus();
            });
            document.addEventListener('keydown', function(ev) {
                if (ev.key !== 'Escape') return;
                var menu = document.querySelector('#tab-switcher details[open]');
                if (!menu) return;
                if (menu.contains(document.activeElement)) menu.querySelector('summary').focus();
                closeTabMenus();
            });

            function switchTab(tab) {
                var button = document.getElementById('btn-'+tab);
                var menu = button.closest('details');
                if (menu) menu.querySelector('summary').focus();
                closeTabMenus();
                document.querySelectorAll('.tab-panel').forEach(function(p) {
                    p.classList.remove('active');
                });
                var previous = document.querySelector('#tab-switcher [aria-current="page"]');
                if (previous) {
                    previous.classList.remove('active-' + previous.id.slice(4));
                    previous.removeAttribute('aria-current');
                }
                document.getElementById(tab+'-tab').classList.add('active');
                button.classList.add('active-'+tab);
                button.setAttribute('aria-current', 'page');
                if (tab === 'ucsd') {
                    var lineupFrame = document.getElementById('ucsd-lineup-frame');
                    if (lineupFrame && !lineupFrame.hasAttribute('src')) {
                        lineupFrame.src = lineupFrame.dataset.src;
                    }
                }
                if (window.Shiny && window.Shiny.setInputValue) {
                    window.Shiny.setInputValue('active_tab', tab, {priority: 'event'});
                    if (tab === 'sim-beta' && window.ucsdSyncTritonTracker) {
                        window.ucsdSyncTritonTracker(true);
                    }
                    window.Shiny.setInputValue(
                        tab === 'sim-beta' ? 'triton_tracker_visible' : 'triton_tracker_hidden',
                        Date.now(),
                        {priority: 'event'}
                    );
                }

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

            function initScatterBindings() {
                bindPlotlyScatterClicks();
                bindDocumentScatterClicks();
                styleHistoricalSelectize();
                initHistoricalHeightSliderFormatting();
                updateHistoricalHeightSliderLabels();
                if (window.Shiny && window.Shiny.setInputValue && document.body.dataset.codexSelectionsReset !== '1') {
                    window.Shiny.setInputValue('reset_all_selections', Math.random(), {priority: 'event'});
                    document.body.dataset.codexSelectionsReset = '1';
                }
            }

            document.addEventListener('DOMContentLoaded', initScatterBindings);
            document.addEventListener('shiny:connected', initScatterBindings);
            document.addEventListener('shiny:value', function(ev) {
                bindPlotlyScatterClicks();
                styleHistoricalSelectize();
                if (ev && ev.target && ev.target.id === 'hist_height') {
                    window.requestAnimationFrame(updateHistoricalHeightSliderLabels);
                }
                initHistoricalHeightSliderFormatting();
                if (window.__historicalScrollState) {
                    restoreHistoricalScrollState(window.__historicalScrollState);
                }
            }, true);
            window.setInterval(styleHistoricalSelectize, 1000);
            window.setInterval(updateHistoricalHeightSliderLabels, 1000);
        """),

        # The public site is a serverless shinylive export, so the watchlist
        # can only outlive a visit in the browser itself. On connect we hand
        # the stored ids back to the server, which owns the set from then on
        # and re-persists it through the watchlist_persist output below. The
        # message is sent even when nothing is stored -- the server waits for
        # it before saving, so a fresh (empty) session cannot overwrite a
        # real watchlist before the restore lands.
        ui.tags.script(f"""
            (function() {{
                var KEY = {json.dumps(WATCHLIST_STORAGE_KEY)};
                function restoreWatchlist() {{
                    if (!window.Shiny || !window.Shiny.setInputValue || !document.body) return;
                    if (document.body.dataset.ucsdWatchlistRestored === '1') return;
                    document.body.dataset.ucsdWatchlistRestored = '1';
                    var ids = [];
                    try {{
                        var raw = localStorage.getItem(KEY);
                        if (raw) {{
                            var parsed = JSON.parse(raw);
                            if (Array.isArray(parsed)) {{
                                ids = parsed.filter(function(v) {{ return typeof v === 'string'; }});
                            }}
                        }}
                    }} catch (err) {{ ids = []; }}
                    // sent as an object so an empty watchlist is still a
                    // truthy, non-null payload the server acts on
                    window.Shiny.setInputValue('watchlist_restore', {{ids: ids}}, {{priority: 'event'}});
                }}
                // Shiny's connect event reaches jQuery and native listeners
                // differently across builds, so poll for a live connection
                // instead of trusting any single hook to fire.
                document.addEventListener('shiny:connected', restoreWatchlist);
                var tries = 0;
                var timer = window.setInterval(function() {{
                    if (document.body && document.body.dataset.ucsdWatchlistRestored === '1') {{
                        window.clearInterval(timer);
                        return;
                    }}
                    var app = window.Shiny && window.Shiny.shinyapp;
                    var live = app && (typeof app.isConnected !== 'function' || app.isConnected());
                    if (document.body && live && window.Shiny.setInputValue) {{
                        restoreWatchlist();
                        window.clearInterval(timer);
                        return;
                    }}
                    if (++tries > 600) {{ window.clearInterval(timer); }}
                }}, 100);
            }})();
        """),
        ui.tags.script(f"""
            (function() {{
                var KEY = {json.dumps(TRITON_TRACKER_STORAGE_KEY)};
                function readIds() {{
                    var ids = [];
                    try {{
                        var raw = localStorage.getItem(KEY);
                        if (raw) {{
                            var parsed = JSON.parse(raw);
                            if (Array.isArray(parsed)) {{
                                ids = parsed.filter(function(v) {{ return typeof v === 'string' && v.trim(); }});
                            }}
                        }}
                    }} catch (err) {{ ids = []; }}
                    return ids;
                }}
                function writeIds(ids) {{
                    try {{
                        localStorage.setItem(KEY, JSON.stringify(ids));
                    }} catch (err) {{}}
                }}
                var lastSentIds = null;
                function syncTritonTracker(force) {{
                    if (!window.Shiny || !window.Shiny.setInputValue || !document.body) return;
                    var ids = readIds();
                    var signature = JSON.stringify(ids);
                    if (!force && document.body.dataset.ucsdTritonTrackerRestored === '1' && signature === lastSentIds) return;
                    document.body.dataset.ucsdTritonTrackerRestored = '1';
                    lastSentIds = signature;
                    window.Shiny.setInputValue(
                        'triton_tracker_restore',
                        {{ids: ids, nonce: Date.now()}},
                        {{priority: 'event'}}
                    );
                }}
                window.ucsdSyncTritonTracker = syncTritonTracker;
                window.ucsdToggleTritonTracker = function(id, button) {{
                    if (!id) return;
                    var ids = readIds();
                    var idx = ids.indexOf(id);
                    var isTracked = idx === -1;
                    if (isTracked) {{
                        ids.push(id);
                    }} else {{
                        ids.splice(idx, 1);
                    }}
                    writeIds(ids);
                    if (button) {{
                        button.classList.toggle('is-tracked', isTracked);
                        button.textContent = isTracked ? 'Remove from Triton Tracker' : 'Add to Triton Tracker';
                    }}
                    if (window.Shiny && window.Shiny.setInputValue) {{
                        syncTritonTracker(true);
                        window.Shiny.setInputValue(
                            'toggle_triton_tracker_direct',
                            {{id: id, tracked: isTracked, nonce: Date.now()}},
                            {{priority: 'event'}}
                        );
                    }}
                }};
                document.addEventListener('shiny:connected', function() {{ syncTritonTracker(false); }});
                var tries = 0;
                var timer = window.setInterval(function() {{
                    var app = window.Shiny && window.Shiny.shinyapp;
                    var live = app && (typeof app.isConnected !== 'function' || app.isConnected());
                    if (document.body && live && window.Shiny.setInputValue) {{
                        syncTritonTracker(false);
                        tries = 0;
                        return;
                    }}
                    if (++tries > 600) {{ window.clearInterval(timer); }}
                }}, 1000);
            }})();
        """),
    ),

    ui.div({"id": "atlas-shell"},

        ui.div({"id": "masthead"},
            ui.div({"class": "mast-left"},
                   ui.div("NCAA Men's Basketball ", ui.span(class_="dot"), f" {D1_SEASON_LABEL}",
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

        ui.tags.nav(
            dashboard_tab("d1", "Division I", selected=True),
            dashboard_tab("ratings", "Ratings"),
            dashboard_menu("Triton Tracker", dashboard_tab("hist", "Historical Players (beta)"),
                           primary=dashboard_tab("sim-beta", "Triton Tracker")),
            dashboard_tab("triton", "Triton Zone"),
            dashboard_tab("info", "Archetype Guide"),
            dashboard_menu(
                "UCSD 26–27 (beta)",
                dashboard_tab("wl", ui.HTML('Watchlist <span id="wl-badge" class="wl-badge" style="display:none">0</span>')),
                primary=dashboard_tab("ucsd", "UCSD 26–27 (beta)"),
            ),
            dashboard_menu("More", dashboard_tab("d2", "Division II"), dashboard_tab("d3", "Division III")),
            id="tab-switcher", aria_label="Dashboard pages",
        ),

        ui.div({"id": "tab-content"},

            make_division_i_tab(make_sidebar("d1", d1_df, d1_conferences), make_plot_area("d1")),

            ratings_tab_ui(),

            ui.div({"id": "d2-tab", "class": "tab-panel"},
                   ui.div({"class": "body-grid"},
                          make_sidebar("d2", d2_df, d2_conferences),
                          make_plot_area("d2"))),

            ui.div({"id": "d3-tab", "class": "tab-panel"},
                   ui.div({"class": "body-grid"},
                          make_sidebar("d3", d3_df, d3_conferences),
                          make_plot_area("d3"))),

            make_similarity_beta_tab(),

            make_triton_tab(d1_df),

            make_historical_beta_tab(HISTORICAL_PLAYER_INDEX, HISTORICAL_BETA_ARCHETYPES),

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

            ui.div(
                {"id": "ucsd-tab", "class": "tab-panel"},
                ui.tags.iframe(
                    {
                        "data-lineup-forecast": json.dumps(
                            lineup_forecast_payload(2027, "UC San Diego"),
                            allow_nan=False, separators=(",", ":"),
                        ),
                        "data-ratings-csv": RATINGS_CSV_URL,
                        "data-src": "lineup/index.html?v=20261116m",
                    },
                    id="ucsd-lineup-frame",
                    title="UCSD lineup predictor",
                    style="flex:1; width:100%; min-height:0; border:none;",
                ),
            ),
        ),

        ui.div({"id": "site-footer"}, "Developed at UC San Diego · © 2026"),
    ),

    ui.output_ui("d1_modal_trigger"),
    ui.output_ui("d2_modal_trigger"),
    ui.output_ui("d3_modal_trigger"),
    ui.output_ui("watchlist_lineup_data"),
    ui.output_ui("watchlist_lineup_sync"),
    ui.output_ui("watchlist_persist"),
    ui.output_ui("triton_tracker_persist"),
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
    watchlist = reactive.Value(set())
    ratings_tab_server(
        input, session,
        watchlisted_players=lambda: (row for _, row, _, div in watchlist_rows(watchlist.get()) if div == "D-I"),
        team_key=normalize_team_lookup_key,
    )
    # Flipped once the browser has handed back its stored watchlist, so the
    # empty starting set is never written over what was already saved.
    watchlist_restored = reactive.Value(False)
    triton_tracker_ids = reactive.Value(set())
    triton_tracker_restored = reactive.Value(False)
    triton_tracker_visible_state = reactive.Value(False)
    radar_selected = reactive.Value([])
    radar_stat_selected = reactive.Value(DEFAULT_RADAR_STAT_KEYS)
    modal_req = reactive.Value(None)
    modal_player = reactive.Value(None)
    modal_similarity_metric = reactive.Value("mahalanobis")
    modal_similarity_view = reactive.Value("current")
    modal_similarity_pool = reactive.Value("all")
    compare_req = reactive.Value(None)
    hist_selected = reactive.Value(None)
    hist_modal_selected = reactive.Value(None)
    hist_modal_exclude_low_sample_state = reactive.Value(False)
    hist_sort_col = reactive.Value("bpm")
    hist_sort_dir = reactive.Value("desc")

    d1_fig = go.FigureWidget()
    d2_fig = go.FigureWidget()
    d3_fig = go.FigureWidget()

    def default_slider_range(df, column, step):
        vals = pd.to_numeric(df[column], errors="coerce").dropna()
        if vals.empty:
            return (0, 0)
        lo = float(np.floor(vals.min() / step) * step)
        hi = float(np.ceil(vals.max() / step) * step)
        if step >= 1:
            return (int(lo), int(hi))
        decimals = len(str(step).split(".")[1].rstrip("0"))
        return (round(lo, decimals), round(hi, decimals))

    def safe_range_input(current, df, column, step):
        default_lo, default_hi = default_slider_range(df, column, step)
        if not isinstance(current, (list, tuple)) or len(current) != 2:
            return (default_lo, default_hi)
        try:
            cur_lo = float(current[0])
            cur_hi = float(current[1])
        except (TypeError, ValueError):
            return (default_lo, default_hi)
        if not np.isfinite(cur_lo) or not np.isfinite(cur_hi) or cur_hi < cur_lo:
            return (default_lo, default_hi)
        # Shinylive sometimes hydrates range sliders to a collapsed zero range on first load.
        if (
            cur_lo == 0.0
            and cur_hi == 0.0
            and (default_lo != 0 or default_hi != 0)
        ):
            return (default_lo, default_hi)
        return (cur_lo, cur_hi)

    def historical_row_by_id(season_player_id):
        return historical_row_by_season_player_id(season_player_id)

    @reactive.calc
    def hist_filtered():
        d = HISTORICAL_PLAYER_INDEX.copy()
        if d.empty:
            return d
        q = (input.hist_q() or "").strip().lower()
        if q:
            d = d[d["player_name"].str.lower().str.contains(q, na=False)]
        seasons = [pd.to_numeric(value, errors="coerce") for value in list(input.hist_season() or [])]
        seasons = [float(value) for value in seasons if pd.notna(value)]
        if seasons:
            d = d[d["year"].isin(seasons)]
        confs = [str(value).strip() for value in list(input.hist_conf() or []) if str(value).strip()]
        if confs:
            d = d[d["conf"].isin(confs)]
        teams = [str(value).strip() for value in list(input.hist_team() or []) if str(value).strip()]
        if teams:
            d = d[d["team"].isin(teams)]
        positions = [str(value).strip() for value in list(input.hist_pos() or []) if str(value).strip()]
        if positions:
            d = d[d["pos"].isin(positions)]
        archetypes = [str(value).strip() for value in list(input.hist_archetype() or []) if str(value).strip()]
        if archetypes:
            d = d[d["archetype"].isin(archetypes)]
        lo, hi = safe_range_input(input.hist_height(), HISTORICAL_PLAYER_INDEX, "height_inches", 1)
        d = d[d["height_inches"].between(lo, hi, inclusive="both")]
        mpg_min = pd.to_numeric(pd.Series([input.hist_mpg_min()]), errors="coerce").iloc[0]
        if pd.notna(mpg_min):
            d = d[d["mins_per_game"].ge(float(mpg_min))]
        mpg_extra_min = pd.to_numeric(pd.Series([input.hist_mpg_extra_min()]), errors="coerce").iloc[0]
        if pd.notna(mpg_extra_min):
            d = d[d["mins_per_game"].ge(float(mpg_extra_min))]
        apg_min = pd.to_numeric(pd.Series([input.hist_apg_min()]), errors="coerce").iloc[0]
        if pd.notna(apg_min):
            d = d[d["ast_per_game"].ge(float(apg_min))]
        ppg_min = pd.to_numeric(pd.Series([input.hist_ppg_min()]), errors="coerce").iloc[0]
        if pd.notna(ppg_min):
            d = d[d["pts_per_game"].ge(float(ppg_min))]
        rpg_min = pd.to_numeric(pd.Series([input.hist_rpg_min()]), errors="coerce").iloc[0]
        if pd.notna(rpg_min):
            d = d[d["treb_per_game"].ge(float(rpg_min))]
        bpm_min = pd.to_numeric(pd.Series([input.hist_bpm_min()]), errors="coerce").iloc[0]
        if pd.notna(bpm_min):
            d = d[d["bpm"].ge(float(bpm_min))]
        sort_col = hist_sort_col.get()
        sort_dir = hist_sort_dir.get()
        ascending = sort_dir == "asc"
        if sort_col == "player_name":
            d = d.sort_values(["player_name", "year", "mins_per_game"], ascending=[ascending, False, False], na_position="last")
        else:
            d = d.sort_values([sort_col, "mins_per_game", "player_name"], ascending=[ascending, False, True], na_position="last")
        return d

    @reactive.calc
    def hist_display_rows():
        d = hist_filtered()
        if d.empty:
            return d
        return d.head(HISTORICAL_TABLE_LIMIT).copy()

    @reactive.effect
    def _hist_keep_selection_fresh():
        rows = hist_display_rows()
        selected = hist_selected.get()
        if rows.empty:
            if selected is not None:
                hist_selected.set(None)
            return
        row_ids = set(rows["season_player_id"].astype(str))
        if selected not in row_ids:
            hist_selected.set(str(rows.iloc[0]["season_player_id"]))

    def d1_home_view_active():
        q = (input.d1_q() or "").strip()
        qual_mode = input.d1_qualification_filter() or "none"
        transfer_tags = list(input.d1_transfer_tags() or [])
        recruiting_tag = input.d1_recruiting_tag() or "none"
        archetypes = list(input.d1_archetypes() or [])
        archetypes_v2 = list(input.d1_archetypes_v2() or [])
        positions = list(input.d1_positions() or [])
        classes = list(input.d1_classes() or [])
        confs = list(input.d1_confs() or [])
        teams = list(input.d1_team() or [])

        if any([
            q,
            qual_mode != "none",
            transfer_tags,
            recruiting_tag != "none",
            archetypes,
            archetypes_v2,
            positions,
            classes,
            confs,
            teams,
            bool(input.d1_exclude_low_sample()),
            bool(input.d1_exclude_unstable_archetypes()),
            d1_sel.get() is not None,
            bool(d1_dim.get()),
        ]):
            return False

        def is_full_range(current, column, step):
            lo, hi = default_slider_range(d1_df, column, step)
            cur_lo, cur_hi = safe_range_input(current, d1_df, column, step)
            return abs(float(cur_lo) - lo) < 1e-9 and abs(float(cur_hi) - hi) < 1e-9

        return all([
            is_full_range(input.d1_mpg(), "mpg", 0.1),
            is_full_range(input.d1_ppg_range(), "ppg", 0.1),
            is_full_range(input.d1_rpg_range(), "rpg", 0.1),
            is_full_range(input.d1_tov_range(), "tov", 0.1),
            is_full_range(input.d1_pf_range(), "pf", 0.1),
            is_full_range(input.d1_drb_range(), "drb", 0.1),
            is_full_range(input.d1_efg(), "efg", 0.01),
            is_full_range(input.d1_orb_pct(), "orb_pct", 0.01),
            is_full_range(input.d1_drb_pct(), "drb_pct", 0.01),
            is_full_range(input.d1_ast_pct(), "ast_pct", 0.01),
            is_full_range(input.d1_stl_pct(), "stl_pct", 0.01),
            is_full_range(input.d1_blk_pct(), "blk_pct", 0.01),
            is_full_range(input.d1_tp_range(), "tp", 0.01),
            is_full_range(input.d1_ft_range(), "ft", 0.01),
            is_full_range(input.d1_usg_range(), "usg", 0.01),
            is_full_range(input.d1_ftr_range(), "ftr", 0.01),
            is_full_range(input.d1_tov_pct_range(), "tov_pct", 0.01),
            is_full_range(input.d1_pf40_range(), "pf_per_40", 0.1),
            is_full_range(input.d1_three_share(), "three_share", 0.01),
            is_full_range(input.d1_rim_share(), "rim_share", 0.01),
            is_full_range(input.d1_mid_share(), "mid_share", 0.01),
            is_full_range(input.d1_assisted_fg_pct(), "assisted_fg_pct", 0.01),
            is_full_range(input.d1_rim_fg_pct(), "rim_fg_pct", 0.01),
            is_full_range(input.d1_mid_fg_pct(), "mid_fg_pct", 0.01),
            is_full_range(input.d1_rim_assisted_pct(), "rim_assisted_pct", 0.01),
            is_full_range(input.d1_mid_assisted_pct(), "mid_assisted_pct", 0.01),
            is_full_range(input.d1_three_assisted_pct(), "three_assisted_pct", 0.01),
            is_full_range(input.d1_apg_range(), "apg", 0.1),
            is_full_range(input.d1_bpm(), "bpm", 0.1),
            is_full_range(input.d1_porpag(), "porpag", 0.1),
            is_full_range(input.d1_spg_range(), "spg", 0.1),
            is_full_range(input.d1_bpg_range(), "bpg", 0.1),
            is_full_range(input.d1_ast_tov(), "ast_tov", 0.1),
            is_full_range(input.d1_height(), "heightIn", 1),
            tuple(safe_range_input(input.d1_eligibility(), d1_df, "eligibility", 1)) == (
                *default_slider_range(d1_df, "eligibility", 1),
            ),
            float(input.d1_score_min() or 0) == 0.0,
            float(input.d1_score_v2_min() or 0) == 0.0,
        ])

    def d1_filters_are_default():
        q = (input.d1_q() or "").strip()
        qual_mode = input.d1_qualification_filter() or "none"
        transfer_tags = list(input.d1_transfer_tags() or [])
        recruiting_tag = input.d1_recruiting_tag() or "none"
        archetypes = list(input.d1_archetypes() or [])
        archetypes_v2 = list(input.d1_archetypes_v2() or [])
        positions = list(input.d1_positions() or [])
        classes = list(input.d1_classes() or [])
        confs = list(input.d1_confs() or [])
        teams = list(input.d1_team() or [])

        if any([
            q,
            qual_mode != "none",
            transfer_tags,
            recruiting_tag != "none",
            archetypes,
            archetypes_v2,
            positions,
            classes,
            confs,
            teams,
            bool(input.d1_exclude_low_sample()),
            bool(input.d1_exclude_unstable_archetypes()),
        ]):
            return False

        def is_full_range(current, column, step):
            lo, hi = default_slider_range(d1_df, column, step)
            cur_lo, cur_hi = safe_range_input(current, d1_df, column, step)
            return abs(float(cur_lo) - lo) < 1e-9 and abs(float(cur_hi) - hi) < 1e-9

        return all([
            is_full_range(input.d1_mpg(), "mpg", 0.1),
            is_full_range(input.d1_ppg_range(), "ppg", 0.1),
            is_full_range(input.d1_rpg_range(), "rpg", 0.1),
            is_full_range(input.d1_tov_range(), "tov", 0.1),
            is_full_range(input.d1_pf_range(), "pf", 0.1),
            is_full_range(input.d1_drb_range(), "drb", 0.1),
            is_full_range(input.d1_efg(), "efg", 0.01),
            is_full_range(input.d1_orb_pct(), "orb_pct", 0.01),
            is_full_range(input.d1_drb_pct(), "drb_pct", 0.01),
            is_full_range(input.d1_ast_pct(), "ast_pct", 0.01),
            is_full_range(input.d1_stl_pct(), "stl_pct", 0.01),
            is_full_range(input.d1_blk_pct(), "blk_pct", 0.01),
            is_full_range(input.d1_tp_range(), "tp", 0.01),
            is_full_range(input.d1_ft_range(), "ft", 0.01),
            is_full_range(input.d1_usg_range(), "usg", 0.01),
            is_full_range(input.d1_ftr_range(), "ftr", 0.01),
            is_full_range(input.d1_tov_pct_range(), "tov_pct", 0.01),
            is_full_range(input.d1_pf40_range(), "pf_per_40", 0.1),
            is_full_range(input.d1_three_share(), "three_share", 0.01),
            is_full_range(input.d1_rim_share(), "rim_share", 0.01),
            is_full_range(input.d1_mid_share(), "mid_share", 0.01),
            is_full_range(input.d1_assisted_fg_pct(), "assisted_fg_pct", 0.01),
            is_full_range(input.d1_rim_fg_pct(), "rim_fg_pct", 0.01),
            is_full_range(input.d1_mid_fg_pct(), "mid_fg_pct", 0.01),
            is_full_range(input.d1_rim_assisted_pct(), "rim_assisted_pct", 0.01),
            is_full_range(input.d1_mid_assisted_pct(), "mid_assisted_pct", 0.01),
            is_full_range(input.d1_three_assisted_pct(), "three_assisted_pct", 0.01),
            is_full_range(input.d1_apg_range(), "apg", 0.1),
            is_full_range(input.d1_bpm(), "bpm", 0.1),
            is_full_range(input.d1_porpag(), "porpag", 0.1),
            is_full_range(input.d1_spg_range(), "spg", 0.1),
            is_full_range(input.d1_bpg_range(), "bpg", 0.1),
            is_full_range(input.d1_ast_tov(), "ast_tov", 0.1),
            is_full_range(input.d1_height(), "heightIn", 1),
            tuple(safe_range_input(input.d1_eligibility(), d1_df, "eligibility", 1)) == (
                *default_slider_range(d1_df, "eligibility", 1),
            ),
            float(input.d1_score_min() or 0) == 0.0,
            float(input.d1_score_v2_min() or 0) == 0.0,
        ])

    def apply_d1_range_filter(df, current, column, step):
        lo, hi = safe_range_input(current, d1_df, column, step)
        default_lo, default_hi = default_slider_range(d1_df, column, step)
        if abs(float(lo) - default_lo) < 1e-9 and abs(float(hi) - default_hi) < 1e-9:
            return df
        return df[(df[column] >= lo) & (df[column] <= hi)]

    def sync_scatter(fig, plot_df, selected_id, dimmed_arch, click_handler):
        compress_pc1_tail = fig is d2_fig
        compress_pc2_tail = fig is d2_fig
        d1_default_view = fig is d1_fig and d1_filters_are_default()
        fixed_x_range = [-5, 6.5] if d1_default_view else None
        fixed_y_range = [-4.5, 6] if d1_default_view else None
        clip_x_range = [-4.5, 6] if d1_default_view else None
        clip_y_range = [-4, 5.5] if d1_default_view else None
        traces = build_traces(
            plot_df,
            selected_id,
            dimmed_arch,
            compress_pc1_tail=compress_pc1_tail,
            compress_pc2_tail=compress_pc2_tail,
            clip_x_range=clip_x_range,
            clip_y_range=clip_y_range,
        )
        layout = build_layout(
            plot_df,
            selected_id=selected_id,
            compress_pc1_tail=compress_pc1_tail,
            compress_pc2_tail=compress_pc2_tail,
            fixed_x_range=fixed_x_range,
            fixed_y_range=fixed_y_range,
            clip_x_range=clip_x_range,
            clip_y_range=clip_y_range,
        )
        with fig.batch_update():
            fig.data = []
            for trace in traces:
                fig.add_trace(trace)
            fig.update_layout(layout)

    def sync_radar_selection(player_ids):
        available = [pid for pid, *_ in watchlist_rows(player_ids)]
        selected = [pid for pid in radar_selected.get() if pid in available][:2]
        for pid in available:
            if len(selected) >= 2:
                break
            if pid not in selected:
                selected.append(pid)
        radar_selected.set(selected)

    # ── Watchlist restore from browser storage ────────────────────────────
    @reactive.effect
    @reactive.event(input.watchlist_restore)
    def _restore_watchlist():
        payload = input.watchlist_restore() or {}
        stored = payload.get("ids") if isinstance(payload, dict) else None
        if not isinstance(stored, (list, tuple)):
            stored = []
        # Rosters change between data refreshes; drop ids that no longer
        # resolve to a player rather than carrying dead cards forward.
        restored = {pid for pid, *_ in watchlist_rows(stored)}
        watchlist.set(restored)
        sync_radar_selection(restored)
        watchlist_restored.set(True)

    @output
    @render.ui
    def watchlist_persist():
        if not watchlist_restored.get():
            return None
        ids_json = json.dumps(sorted(watchlist.get())).replace("</", "<\\/")
        return ui.tags.script(f"""
        (function() {{
          try {{
            localStorage.setItem({json.dumps(WATCHLIST_STORAGE_KEY)}, JSON.stringify({ids_json}));
          }} catch (err) {{}}
        }})();
        """)

    # ── Triton Tracker restore from browser storage ──────────────────────
    @reactive.effect
    @reactive.event(input.triton_tracker_restore)
    def _restore_triton_tracker():
        payload = input.triton_tracker_restore() or {}
        stored = payload.get("ids") or [] if isinstance(payload, dict) else []
        restored = {
            str(row_id).strip()
            for row_id in stored
            if historical_row_by_id(str(row_id).strip()) is not None
        }
        triton_tracker_ids.set(restored)
        triton_tracker_restored.set(True)

    @output
    @render.ui
    def triton_tracker_persist():
        if not triton_tracker_restored.get():
            return None
        ids_json = json.dumps(sorted(triton_tracker_ids.get())).replace("</", "<\\/")
        return ui.tags.script(f"""
        (function() {{
          try {{
            localStorage.setItem({json.dumps(TRITON_TRACKER_STORAGE_KEY)}, JSON.stringify({ids_json}));
          }} catch (err) {{}}
        }})();
        """)

    @reactive.effect
    @reactive.event(input.toggle_triton_tracker)
    def _toggle_triton_tracker():
        row_id = str(input.toggle_triton_tracker() or "").strip()
        if not row_id or historical_row_by_id(row_id) is None:
            return
        curr = set(triton_tracker_ids.get())
        curr.discard(row_id) if row_id in curr else curr.add(row_id)
        triton_tracker_ids.set(curr)

    @reactive.effect
    @reactive.event(input.toggle_triton_tracker_direct)
    def _toggle_triton_tracker_direct():
        payload = input.toggle_triton_tracker_direct() or {}
        if not isinstance(payload, dict):
            return
        row_id = str(payload.get("id", "") or "").strip()
        if not row_id or historical_row_by_id(row_id) is None:
            return
        curr = set(triton_tracker_ids.get())
        if bool(payload.get("tracked")):
            curr.add(row_id)
        else:
            curr.discard(row_id)
        triton_tracker_ids.set(curr)

    @reactive.effect
    @reactive.event(input.triton_tracker_visible)
    def _triton_tracker_visible():
        triton_tracker_visible_state.set(True)

    @reactive.effect
    @reactive.event(input.triton_tracker_hidden)
    def _triton_tracker_hidden():
        triton_tracker_visible_state.set(False)

    @output
    @render.ui
    def triton_tracker_ui():
        return make_triton_tracker_content(triton_tracker_ids.get())

    # ── Watchlist toggle ──────────────────────────────────────────────────
    @reactive.effect
    @reactive.event(input.toggle_watchlist)
    def _toggle_watchlist():
        pid = input.toggle_watchlist()
        if not watchlist_rows([pid]):
            return
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
    @reactive.event(input.reset_all_selections)
    def _reset_all_selections():
        d1_sel.set(None)
        d2_sel.set(None)
        d3_sel.set(None)
        ui.modal_remove()

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
        metric_ = modal_similarity_metric.get()
        view_ = modal_similarity_view.get()
        pool_ = modal_similarity_pool.get()
        row = df_[df_["id"] == pid]
        if row.empty: return
        modal_player.set(pid)
        ui.modal_show(make_detail_modal(pid, df_, la_, sf_, div_, wl, metric_, view_, pool_))

    @reactive.effect
    @reactive.event(input.modal_similarity_metric)
    def _modal_similarity_metric_changed():
        metric = input.modal_similarity_metric()
        if metric not in SIMILARITY_METRIC_LABELS:
            metric = "mahalanobis"
        if metric == modal_similarity_metric.get():
            return
        modal_similarity_metric.set(metric)
        pid = modal_player.get()
        if pid:
            import random
            modal_req.set((pid, random.random()))

    @reactive.effect
    @reactive.event(input.modal_similarity_view)
    def _modal_similarity_view_changed():
        view = input.modal_similarity_view()
        if view not in SIMILARITY_VIEW_LABELS:
            view = "current"
        if view == modal_similarity_view.get():
            return
        modal_similarity_view.set(view)
        pid = modal_player.get()
        if pid:
            import random
            modal_req.set((pid, random.random()))

    @reactive.effect
    @reactive.event(input.modal_similarity_pool)
    def _modal_similarity_pool_changed():
        pool = input.modal_similarity_pool()
        if pool not in SIMILARITY_HISTORICAL_POOL_LABELS:
            pool = "all"
        if pool == modal_similarity_pool.get():
            return
        modal_similarity_pool.set(pool)
        pid = modal_player.get()
        if pid:
            import random
            modal_req.set((pid, random.random()))

    @reactive.effect
    @reactive.event(input.open_similarity_compare)
    def _open_similarity_compare():
        payload = input.open_similarity_compare()
        if not payload:
            return
        source_id = str(payload.get("source_id", "")).strip()
        if not source_id:
            return
        source_rows = d1_df[d1_df["id"] == source_id]
        if source_rows.empty:
            return
        source_row = source_rows.iloc[0]
        source_profile = _current_d1_compare_profile(source_row)
        compare_mode = str(payload.get("mode", "historical")).strip() or "historical"
        future_profile = None
        if compare_mode == "current":
            target_id = str(payload.get("target_id", "")).strip()
            target_rows = d1_df[d1_df["id"] == target_id]
            if target_rows.empty:
                return
            target_profile = _current_d1_compare_profile(target_rows.iloc[0])
        else:
            source_profile = _profile_from_neighbor_payload(
                payload,
                "target",
                player_id=source_id,
                subtitle=f"{source_row['team']} \u00b7 {source_row['cls']}",
                year=D1_CURRENT_SEASON,
            )
            source_profile.update({
                "player_name": source_row["name"],
                "team": source_row["team"],
                "conf": source_row.get("confName", source_row.get("conf", "")),
                "height_inches": _as_float(source_row.get("heightIn")),
                "PC1": _as_float(source_row.get("PC1")),
                "PC2": _as_float(source_row.get("PC2")),
                "PC3": _as_float(source_row.get("PC3")),
                "PC4": _as_float(source_row.get("PC4")),
            })
            target_profile = _profile_from_neighbor_payload(
                payload,
                "match",
                subtitle=" \u00b7 ".join(
                    [
                        str(payload.get("target_team", "") or payload.get("match_team", "")).strip(),
                    ]
                ),
            )
            subtitle_bits = [
                str(payload.get("target_team", "") or payload.get("match_team", "")).strip(),
                str(payload.get("target_season", "") or "").strip(),
                str(payload.get("target_conf", "") or "").strip(),
            ]
            target_profile.update({
                "player_name": str(payload.get("target_name", "")).strip(),
                "team": str(payload.get("target_team", "")).strip(),
                "conf": str(payload.get("target_conf", "")).strip(),
                "year": payload.get("target_season"),
                "subtitle": " \u00b7 ".join([bit for bit in subtitle_bits if bit]),
            })
            next_name = str(payload.get("next_name", "")).strip()
            if next_name and str(payload.get("historical_pool", "")).strip() == "big_west_next_year":
                next_subtitle_bits = [
                    str(payload.get("next_team", "")).strip(),
                    str(payload.get("next_season", "") or "").strip(),
                    str(payload.get("next_conf", "")).strip(),
                ]
                future_profile = _profile_from_neighbor_payload(
                    payload,
                    "next",
                    subtitle=" \u00b7 ".join([bit for bit in next_subtitle_bits if bit]),
                    year=_as_float(payload.get("next_season")),
                )
                future_profile.update({
                    "player_name": next_name,
                    "team": str(payload.get("next_team", "")).strip(),
                    "conf": str(payload.get("next_conf", "")).strip(),
                    "year": payload.get("next_season"),
                    "subtitle": " \u00b7 ".join([bit for bit in next_subtitle_bits if bit]),
                })
        compare_req.set(payload)
        ui.modal_show(
            make_similarity_compare_modal(
                source_profile,
                target_profile,
                compare_mode,
                future_profile=future_profile,
            )
        )

    @reactive.effect
    @reactive.event(input.modal_compare_back)
    def _modal_compare_back():
        pid = str(input.modal_compare_back() or "").strip()
        if not pid:
            return
        import random
        modal_req.set((pid, random.random()))

    @reactive.effect
    @reactive.event(input.modal_compare_open_target)
    def _modal_compare_open_target():
        pid = str(input.modal_compare_open_target() or "").strip()
        if not pid:
            return
        import random
        modal_req.set((pid, random.random()))

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
    @reactive.event(input.d1_clear_arch)
    def _d1_clear_arch():
        ui.update_checkbox_group("d1_archetypes", selected=[])

    @reactive.effect
    @reactive.event(input.d1_clear_arch_v2)
    def _d1_clear_arch_v2():
        ui.update_checkbox_group("d1_archetypes_v2", selected=[])

    @reactive.effect
    @reactive.event(input.d1_clear_cls)
    def _d1_clear_cls():
        ui.update_checkbox_group("d1_classes", selected=[])

    @reactive.effect
    @reactive.event(input.d1_clear_eligibility)
    def _d1_clear_eligibility():
        vals = pd.to_numeric(d1_df["eligibility"], errors="coerce").dropna()
        if not vals.empty:
            ui.update_slider("d1_eligibility", value=[int(vals.min()), int(vals.max())])

    @reactive.effect
    @reactive.event(input.d1_clear_conf)
    def _d1_clear_conf():
        ui.update_checkbox_group("d1_confs", selected=[])

    @reactive.effect
    @reactive.event(input.d1_clear_team)
    def _d1_clear_team():
        ui.update_selectize("d1_team", selected=[])

    @reactive.effect
    @reactive.event(input.d1_select_similar)
    def _d1_select_similar():
        sid = input.d1_select_similar()
        if sid:
            d1_sel.set(sid)
            ui.modal_remove()
            import random
            modal_req.set((sid, random.random()))

    @reactive.effect
    @reactive.event(input.d1_plot_click)
    def _d1_plot_click():
        payload = input.d1_plot_click() or {}
        sid = None
        if isinstance(payload, dict):
            sid = payload.get("player_id")
            if not sid:
                sid = resolve_clicked_player_id(
                    d1_plot_df(),
                    d1_sel.get(),
                    d1_dim.get(),
                    payload.get("trace_index"),
                    payload.get("point_index"),
                )
        if sid:
            import random
            d1_sel.set(sid)
            modal_req.set((sid, random.random()))

    @reactive.calc
    def d1_filtered():
        d = d1_df.copy()
        qual_mode = input.d1_qualification_filter()
        d = apply_qualification_filter(d, qual_mode)
        if bool(input.d1_exclude_low_sample()):
            d = d[~d["low_sample_size"].fillna(False)]
        if bool(input.d1_exclude_unstable_archetypes()):
            d = d[~d["archetype_v2_unstable"].fillna(False)]
        q = (input.d1_q() or "").strip().lower()
        if q: d = d[d["name"].str.lower().str.contains(q, na=False)]
        d = apply_tag_filters(d, list(input.d1_transfer_tags() or []))
        d = apply_single_tag_filter(d, input.d1_recruiting_tag())
        archs = list(input.d1_archetypes() or [])
        if archs: d = d[d["primary_archetype"].isin(archs)]
        d = apply_archetype_score_filter(d, qual_mode, input.d1_score_min())
        archs_v2 = list(input.d1_archetypes_v2() or [])
        if archs_v2: d = d[d["archetype_v2_primary_code"].isin(archs_v2)]
        d = apply_archetype_v2_score_filter(d, input.d1_score_v2_min())
        ps = list(input.d1_positions() or [])
        if ps: d = d[d["pos"].isin(ps)]
        cs = list(input.d1_classes() or [])
        if cs: d = d[d["cls"].isin(cs)]
        d = apply_d1_range_filter(d, input.d1_eligibility(), "eligibility", 1)
        xs = list(input.d1_confs() or [])
        if xs: d = d[d["conf"].isin(xs)]
        teams = list(input.d1_team() or [])
        if teams: d = d[d["team"].isin(teams)]
        d = apply_d1_range_filter(d, input.d1_mpg(), "mpg", 0.1)
        d = apply_d1_range_filter(d, input.d1_ppg_range(), "ppg", 0.1)
        d = apply_d1_range_filter(d, input.d1_rpg_range(), "rpg", 0.1)
        d = apply_d1_range_filter(d, input.d1_tov_range(), "tov", 0.1)
        d = apply_d1_range_filter(d, input.d1_pf_range(), "pf", 0.1)
        d = apply_d1_range_filter(d, input.d1_drb_range(), "drb", 0.1)
        d = apply_d1_range_filter(d, input.d1_efg(), "efg", 0.01)
        d = apply_d1_range_filter(d, input.d1_orb_pct(), "orb_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_drb_pct(), "drb_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_ast_pct(), "ast_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_stl_pct(), "stl_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_blk_pct(), "blk_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_tp_range(), "tp", 0.01)
        d = apply_d1_range_filter(d, input.d1_ft_range(), "ft", 0.01)
        d = apply_d1_range_filter(d, input.d1_usg_range(), "usg", 0.01)
        d = apply_d1_range_filter(d, input.d1_ftr_range(), "ftr", 0.01)
        d = apply_d1_range_filter(d, input.d1_tov_pct_range(), "tov_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_pf40_range(), "pf_per_40", 0.1)
        d = apply_d1_range_filter(d, input.d1_three_share(), "three_share", 0.01)
        d = apply_d1_range_filter(d, input.d1_rim_share(), "rim_share", 0.01)
        d = apply_d1_range_filter(d, input.d1_mid_share(), "mid_share", 0.01)
        d = apply_d1_range_filter(d, input.d1_assisted_fg_pct(), "assisted_fg_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_rim_fg_pct(), "rim_fg_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_mid_fg_pct(), "mid_fg_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_rim_assisted_pct(), "rim_assisted_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_mid_assisted_pct(), "mid_assisted_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_three_assisted_pct(), "three_assisted_pct", 0.01)
        d = apply_d1_range_filter(d, input.d1_apg_range(), "apg", 0.1)
        d = apply_d1_range_filter(d, input.d1_bpm(), "bpm", 0.1)
        d = apply_d1_range_filter(d, input.d1_porpag(), "porpag", 0.1)
        d = apply_d1_range_filter(d, input.d1_spg_range(), "spg", 0.1)
        d = apply_d1_range_filter(d, input.d1_bpg_range(), "bpg", 0.1)
        d = apply_d1_range_filter(d, input.d1_ast_tov(), "ast_tov", 0.1)
        d = apply_d1_range_filter(d, input.d1_height(), "heightIn", 1)
        if d.empty and d1_filters_are_default():
            return d1_df.copy()
        if d.empty and q:
            name_matches = d1_df[d1_df["name"].str.lower().str.contains(q, na=False)]
            if not name_matches.empty:
                return name_matches
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
    @render.text
    def d1_filtered_out_count():
        return str(max(0, D1_TOTAL - len(d1_filtered())))

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

    @output
    @render.text
    def d1_trace_map():
        return json.dumps(build_trace_id_map(d1_plot_df(), d1_sel.get(), d1_dim.get()))

    @render_widget
    def d1_scatter():
        return d1_fig

    @reactive.effect
    def _d1_sync():
        sync_scatter(d1_fig, d1_plot_df(), d1_sel.get(), d1_dim.get(), _d1_clicked)

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
    @reactive.event(input.d2_clear_arch)
    def _d2_clear_arch():
        ui.update_checkbox_group("d2_archetypes", selected=[])

    @reactive.effect
    @reactive.event(input.d2_clear_cls)
    def _d2_clear_cls():
        ui.update_checkbox_group("d2_classes", selected=[])

    @reactive.effect
    @reactive.event(input.d2_clear_eligibility)
    def _d2_clear_eligibility():
        vals = pd.to_numeric(d2_df["eligibility"], errors="coerce").dropna()
        if not vals.empty:
            ui.update_slider("d2_eligibility", value=[int(vals.min()), int(vals.max())])

    @reactive.effect
    @reactive.event(input.d2_clear_conf)
    def _d2_clear_conf():
        ui.update_checkbox_group("d2_confs", selected=[])

    @reactive.effect
    @reactive.event(input.d2_clear_team)
    def _d2_clear_team():
        ui.update_selectize("d2_team", selected=[])

    @reactive.effect
    @reactive.event(input.d2_select_similar)
    def _d2_select_similar():
        sid = input.d2_select_similar()
        if sid:
            d2_sel.set(sid)
            ui.modal_remove()
            import random
            modal_req.set((sid, random.random()))

    @reactive.effect
    @reactive.event(input.d2_plot_click)
    def _d2_plot_click():
        payload = input.d2_plot_click() or {}
        sid = None
        if isinstance(payload, dict):
            sid = payload.get("player_id")
            if not sid:
                sid = resolve_clicked_player_id(
                    d2_plot_df(),
                    d2_sel.get(),
                    d2_dim.get(),
                    payload.get("trace_index"),
                    payload.get("point_index"),
                )
        if sid:
            import random
            d2_sel.set(sid)
            modal_req.set((sid, random.random()))

    @reactive.calc
    def d2_filtered():
        d = d2_df.copy()
        qual_mode = input.d2_qualification_filter()
        d = apply_qualification_filter(d, qual_mode)
        q = (input.d2_q() or "").strip().lower()
        if q: d = d[d["name"].str.lower().str.contains(q, na=False)]
        archs = list(input.d2_archetypes() or [])
        if archs: d = d[d["primary_archetype"].isin(archs)]
        d = apply_archetype_score_filter(d, qual_mode, input.d2_score_min())
        ps = list(input.d2_positions() or [])
        if ps: d = d[d["pos"].isin(ps)]
        cs = list(input.d2_classes() or [])
        if cs: d = d[d["cls"].isin(cs)]
        lo, hi = input.d2_eligibility(); d = d[(d["eligibility"] >= lo) & (d["eligibility"] <= hi)]
        xs = list(input.d2_confs() or [])
        if xs: d = d[d["conf"].isin(xs)]
        teams = list(input.d2_team() or [])
        if teams: d = d[d["team"].isin(teams)]
        lo, hi = input.d2_mpg();         d = d[(d["mpg"]         >= lo) & (d["mpg"]         <= hi)]
        lo, hi = input.d2_ppg_range();   d = d[(d["ppg"]         >= lo) & (d["ppg"]         <= hi)]
        lo, hi = input.d2_rpg_range();   d = d[(d["rpg"]         >= lo) & (d["rpg"]         <= hi)]
        lo, hi = input.d2_tov_range();   d = d[(d["tov"]         >= lo) & (d["tov"]         <= hi)]
        lo, hi = input.d2_drb_range();   d = d[(d["drb"]         >= lo) & (d["drb"]         <= hi)]
        lo, hi = input.d2_efg();         d = d[(d["efg"]         >= lo) & (d["efg"]         <= hi)]
        lo, hi = input.d2_tp_range();    d = d[(d["tp"]          >= lo) & (d["tp"]          <= hi)]
        lo, hi = input.d2_three_share(); d = d[(d["three_share"]  >= lo) & (d["three_share"]  <= hi)]
        lo, hi = input.d2_apg_range();   d = d[(d["apg"]         >= lo) & (d["apg"]         <= hi)]
        lo, hi = input.d2_spg_range();   d = d[(d["spg"]         >= lo) & (d["spg"]         <= hi)]
        lo, hi = input.d2_bpg_range();   d = d[(d["bpg"]         >= lo) & (d["bpg"]         <= hi)]
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
    @render.text
    def d2_filtered_out_count():
        return str(max(0, D2_TOTAL - len(d2_filtered())))

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

    @output
    @render.text
    def d2_trace_map():
        return json.dumps(build_trace_id_map(d2_plot_df(), d2_sel.get(), d2_dim.get()))

    @render_widget
    def d2_scatter():
        return d2_fig

    @reactive.effect
    def _d2_sync():
        sync_scatter(d2_fig, d2_plot_df(), d2_sel.get(), d2_dim.get(), _d2_clicked)

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
    @reactive.event(input.d3_clear_arch)
    def _d3_clear_arch():
        ui.update_checkbox_group("d3_archetypes", selected=[])

    @reactive.effect
    @reactive.event(input.d3_clear_cls)
    def _d3_clear_cls():
        ui.update_checkbox_group("d3_classes", selected=[])

    @reactive.effect
    @reactive.event(input.d3_clear_eligibility)
    def _d3_clear_eligibility():
        vals = pd.to_numeric(d3_df["eligibility"], errors="coerce").dropna()
        if not vals.empty:
            ui.update_slider("d3_eligibility", value=[int(vals.min()), int(vals.max())])

    @reactive.effect
    @reactive.event(input.d3_clear_conf)
    def _d3_clear_conf():
        ui.update_checkbox_group("d3_confs", selected=[])

    @reactive.effect
    @reactive.event(input.d3_clear_team)
    def _d3_clear_team():
        ui.update_selectize("d3_team", selected=[])

    @reactive.effect
    @reactive.event(input.d3_select_similar)
    def _d3_select_similar():
        sid = input.d3_select_similar()
        if sid:
            d3_sel.set(sid)
            ui.modal_remove()
            import random
            modal_req.set((sid, random.random()))

    @reactive.effect
    @reactive.event(input.d3_plot_click)
    def _d3_plot_click():
        payload = input.d3_plot_click() or {}
        sid = None
        if isinstance(payload, dict):
            sid = payload.get("player_id")
            if not sid:
                sid = resolve_clicked_player_id(
                    d3_plot_df(),
                    d3_sel.get(),
                    d3_dim.get(),
                    payload.get("trace_index"),
                    payload.get("point_index"),
                )
        if sid:
            import random
            d3_sel.set(sid)
            modal_req.set((sid, random.random()))

    @reactive.calc
    def d3_filtered():
        d = d3_df.copy()
        qual_mode = input.d3_qualification_filter()
        d = apply_qualification_filter(d, qual_mode)
        q = (input.d3_q() or "").strip().lower()
        if q: d = d[d["name"].str.lower().str.contains(q, na=False)]
        archs = list(input.d3_archetypes() or [])
        if archs: d = d[d["primary_archetype"].isin(archs)]
        d = apply_archetype_score_filter(d, qual_mode, input.d3_score_min())
        ps = list(input.d3_positions() or [])
        if ps: d = d[d["pos"].isin(ps)]
        cs = list(input.d3_classes() or [])
        if cs: d = d[d["cls"].isin(cs)]
        lo, hi = input.d3_eligibility(); d = d[(d["eligibility"] >= lo) & (d["eligibility"] <= hi)]
        xs = list(input.d3_confs() or [])
        if xs: d = d[d["conf"].isin(xs)]
        teams = list(input.d3_team() or [])
        if teams: d = d[d["team"].isin(teams)]
        lo, hi = input.d3_mpg();         d = d[(d["mpg"]         >= lo) & (d["mpg"]         <= hi)]
        lo, hi = input.d3_ppg_range();   d = d[(d["ppg"]         >= lo) & (d["ppg"]         <= hi)]
        lo, hi = input.d3_rpg_range();   d = d[(d["rpg"]         >= lo) & (d["rpg"]         <= hi)]
        lo, hi = input.d3_tov_range();   d = d[(d["tov"]         >= lo) & (d["tov"]         <= hi)]
        lo, hi = input.d3_drb_range();   d = d[(d["drb"]         >= lo) & (d["drb"]         <= hi)]
        lo, hi = input.d3_efg();         d = d[(d["efg"]         >= lo) & (d["efg"]         <= hi)]
        lo, hi = input.d3_tp_range();    d = d[(d["tp"]          >= lo) & (d["tp"]          <= hi)]
        lo, hi = input.d3_three_share(); d = d[(d["three_share"]  >= lo) & (d["three_share"]  <= hi)]
        lo, hi = input.d3_apg_range();   d = d[(d["apg"]         >= lo) & (d["apg"]         <= hi)]
        lo, hi = input.d3_spg_range();   d = d[(d["spg"]         >= lo) & (d["spg"]         <= hi)]
        lo, hi = input.d3_bpg_range();   d = d[(d["bpg"]         >= lo) & (d["bpg"]         <= hi)]
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
    @render.text
    def d3_filtered_out_count():
        return str(max(0, D3_TOTAL - len(d3_filtered())))

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

    @output
    @render.text
    def d3_trace_map():
        return json.dumps(build_trace_id_map(d3_plot_df(), d3_sel.get(), d3_dim.get()))

    @render_widget
    def d3_scatter():
        return d3_fig

    @reactive.effect
    def _d3_sync():
        sync_scatter(d3_fig, d3_plot_df(), d3_sel.get(), d3_dim.get(), _d3_clicked)

    @reactive.effect
    @reactive.event(input.active_tab)
    def _refresh_active_tab():
        tab = input.active_tab() or "d2"
        if tab == "d1":
            sync_scatter(d1_fig, d1_plot_df(), d1_sel.get(), d1_dim.get(), _d1_clicked)
        elif tab == "d3":
            sync_scatter(d3_fig, d3_plot_df(), d3_sel.get(), d3_dim.get(), _d3_clicked)
        elif tab == "d2":
            sync_scatter(d2_fig, d2_plot_df(), d2_sel.get(), d2_dim.get(), _d2_clicked)

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

    @reactive.effect
    @reactive.event(input.hist_sort_click)
    def _hist_sort_click():
        col = str(input.hist_sort_click() or "").strip()
        valid = {
            "player_name",
            "year",
            "conf",
            "team",
            "pos",
            "archetype",
            "mins_per_game",
            "pts_per_game",
            "ast_per_game",
            "treb_per_game",
            "bpm",
        }
        if col not in valid:
            return
        if hist_sort_col.get() == col:
            hist_sort_dir.set("asc" if hist_sort_dir.get() == "desc" else "desc")
        else:
            hist_sort_col.set(col)
            hist_sort_dir.set("asc" if col == "player_name" else "desc")

    # ── Triton WAR tracker ────────────────────────────────────────────────
    triton_sort_col = reactive.Value("triton_war")
    triton_sort_dir = reactive.Value("desc")
    triton_selected = reactive.Value(None)

    def _triton_numeric_input(input_id, fallback):
        try:
            value = input[input_id]()
        except Exception:
            return float(fallback)
        num = _as_float(value)
        return float(num) if np.isfinite(num) else float(fallback)

    @reactive.calc
    def triton_targets():
        return {
            metric["key"]: _triton_numeric_input(f"triton_target_{metric['key']}", metric["target"])
            for metric in TRITON_ZONE_METRICS
        }

    @reactive.calc
    def triton_special_targets():
        return {
            criterion["key"]: _triton_numeric_input(
                f"triton_target_{criterion['key']}", criterion["target"]
            )
            for criterion in TRITON_SPECIAL_CRITERIA
        }

    @reactive.calc
    def triton_weights():
        weights = {
            metric["key"]: max(
                0.0, _triton_numeric_input(f"triton_weight_{metric['key']}", metric["weight"])
            )
            for metric in TRITON_ZONE_METRICS
        }
        # Every weight dragged to zero would make the score undefined, so fall
        # back to the staff's defaults rather than showing an empty board.
        if sum(weights.values()) <= 0:
            return dict(TRITON_DEFAULT_WEIGHTS)
        return weights

    @reactive.calc
    def triton_scored():
        frame = compute_triton_frame(
            d1_df, targets=triton_targets(), weights=triton_weights(),
            spreads=TRITON_METRIC_SPREADS
        )
        special = compute_triton_special(d1_df, special_targets=triton_special_targets())
        keep = [
            "id", "name", "team", "conf", "confName", "pos", "cls",
            "heightIn", "mpg", "gp", "low_sample_size",
        ]
        base = d1_df[[col for col in keep if col in d1_df.columns]].copy()
        return pd.concat([base, frame, special], axis=1)

    @reactive.calc
    def triton_filtered():
        df = triton_scored()

        query = str(input.triton_q() or "").strip().lower()
        if query:
            df = df[
                df["name"].str.lower().str.contains(query, na=False)
                | df["team"].str.lower().str.contains(query, na=False)
            ]

        confs = list(input.triton_conf() or [])
        if confs:
            df = df[df["confName"].isin(confs)]
        teams = list(input.triton_team() or [])
        if teams:
            df = df[df["team"].isin(teams)]
        positions = list(input.triton_pos() or [])
        if positions:
            df = df[df["pos"].isin(positions)]
        classes = list(input.triton_cls() or [])
        if classes:
            df = df[df["cls"].isin(classes)]

        min_mpg = _as_float(input.triton_min_mpg())
        if np.isfinite(min_mpg):
            df = df[pd.to_numeric(df["mpg"], errors="coerce").fillna(0) >= min_mpg]
        min_gp = _as_float(input.triton_min_gp())
        if np.isfinite(min_gp):
            df = df[pd.to_numeric(df["gp"], errors="coerce").fillna(0) >= min_gp]
        min_checks = _as_float(input.triton_min_checks())
        if np.isfinite(min_checks) and min_checks > 0:
            df = df[df["triton_checks_passed"] >= int(min_checks)]

        archetype = str(input.triton_archetype() or "all")
        if archetype == "zone":
            df = df[df["triton_zone"]]
        elif archetype in TRITON_SPECIAL_ARCHETYPES:
            df = df[df[f"triton_is_{archetype}"]]
            if bool(input.triton_require_zone()):
                df = df[df["triton_zone"]]

        return df

    @reactive.calc
    def triton_ranked():
        df = triton_filtered().copy()
        if df.empty:
            return df
        # Rank is always the Triton WAR order, so re-sorting the board by a
        # column does not renumber the board itself.
        df = df.sort_values("triton_war", ascending=False, kind="mergesort")
        df["triton_rank"] = np.arange(1, len(df) + 1)
        sort_col = triton_sort_col.get()
        if sort_col not in df.columns:
            sort_col = "triton_war"
        ascending = triton_sort_dir.get() == "asc"
        df = df.sort_values(sort_col, ascending=ascending, kind="mergesort", na_position="last")
        return df

    @reactive.calc
    def triton_display_rows():
        df = triton_ranked()
        try:
            limit = int(str(input.triton_limit() or "100"))
        except (TypeError, ValueError):
            limit = 100
        return df.head(limit) if limit > 0 else df

    @reactive.effect
    @reactive.event(input.triton_sort_click)
    def _triton_sort_click():
        col = str(input.triton_sort_click() or "").strip()
        if not col:
            return
        if triton_sort_col.get() == col:
            triton_sort_dir.set("asc" if triton_sort_dir.get() == "desc" else "desc")
        else:
            triton_sort_col.set(col)
            triton_sort_dir.set("asc" if col in {"name", "team", "confName"} else "desc")

    @reactive.effect
    @reactive.event(input.triton_select_row)
    def _triton_select_row():
        pid = str(input.triton_select_row() or "").strip()
        if not pid:
            return
        triton_selected.set(pid)
        import random
        modal_req.set((pid, random.random()))

    @reactive.effect
    @reactive.event(input.triton_reset_thresholds)
    def _triton_reset_thresholds():
        for metric in TRITON_ZONE_METRICS:
            ui.update_numeric(f"triton_target_{metric['key']}", value=float(metric["target"]))
        for criterion in TRITON_SPECIAL_CRITERIA:
            ui.update_numeric(f"triton_target_{criterion['key']}", value=float(criterion["target"]))

    @reactive.effect
    @reactive.event(input.triton_reset_weights)
    def _triton_reset_weights():
        for metric in TRITON_ZONE_METRICS:
            ui.update_slider(f"triton_weight_{metric['key']}", value=float(metric["weight"]))

    def _make_triton_weight_share(metric_key):
        @output(id=f"triton_weight_share_{metric_key}")
        @render.text
        def _weight_share():
            weights = triton_weights()
            total = sum(weights.values())
            if total <= 0:
                return "—"
            return f"{weights.get(metric_key, 0.0) / total * 100:.0f}% of score"

        return _weight_share

    for _metric in TRITON_ZONE_METRICS:
        _make_triton_weight_share(_metric["key"])

    @output
    @render.text
    def triton_results_count():
        total = len(triton_filtered())
        shown = len(triton_display_rows())
        return f"{shown} of {total} matching players"

    @output
    @render.ui
    def triton_table_ui():
        rows = triton_display_rows()
        if rows.empty:
            return ui.div(
                "No D-I players match those filters. Loosen the thresholds or the archetype filter.",
                class_="triton-empty",
            )

        selected = str(triton_selected.get() or "")
        sort_col = triton_sort_col.get()
        sort_dir = triton_sort_dir.get()
        targets = triton_targets()
        checks_total = len(TRITON_ZONE_METRICS)

        dash = "\u2014"

        def sort_header(label, col, extra_cls=""):
            marker = ""
            if sort_col == col:
                marker = " \u2193" if sort_dir == "desc" else " \u2191"
            cls = ' class="' + extra_cls + '"' if extra_cls else ""
            click = "Shiny.setInputValue('triton_sort_click','" + col + "',{priority:'event'})"
            return (
                "<th" + cls + '><button onclick="' + click + '">'
                + html.escape(label) + marker + "</button></th>"
            )

        head = ['<th class="triton-col-rank">#</th>']
        head.append(sort_header("Player", "name"))
        head.append(sort_header("Conference", "confName"))
        head.append(sort_header("Ht", "heightIn"))
        head.append(sort_header("MPG", "mpg"))
        head.append(sort_header("Triton Zone", "triton_war", "triton-col-war"))
        head.append(sort_header("Zone", "triton_checks_passed"))
        head.extend(
            sort_header(metric["label"], f"triton_val_{metric['key']}")
            for metric in TRITON_ZONE_METRICS
        )
        head.append("<th>Archetype</th>")

        metric_titles = {
            metric["key"]: html.escape(
                f"{metric['long']} \u00b7 target "
                + ("\u2265 " if metric["higher_is_better"] else "\u2264 ")
                + triton_format_target(metric, targets.get(metric["key"], metric["target"]))
            )
            for metric in TRITON_ZONE_METRICS
        }
        archetype_labels = {
            arch_key: html.escape(archetype["label"])
            for arch_key, archetype in TRITON_SPECIAL_ARCHETYPES.items()
        }

        # The board can run to hundreds of rows and the public site executes
        # this in Pyodide, where building a Shiny tag object per cell is an
        # order of magnitude slower than emitting the markup directly.
        parts = [
            '<div class="triton-table-card"><table class="triton-table"><thead><tr>',
            "".join(head),
            "</tr></thead><tbody>",
        ]
        for record in rows.to_dict("records"):
            pid = str(record["id"])
            row_cls = "triton-row is-selected" if pid == selected else "triton-row"
            meta = " \u00b7 ".join(
                bit
                for bit in (
                    str(record.get("team", "") or "").strip(),
                    str(record.get("cls", "") or "").strip(),
                    str(record.get("pos", "") or "").strip(),
                )
                if bit
            )
            war = _as_float(record.get("triton_war"))
            war_text = f"{war:.1f}" if np.isfinite(war) else dash
            war_width = min(100.0, max(0.0, war)) if np.isfinite(war) else 0.0
            mpg = _as_float(record.get("mpg"))
            passed = int(record.get("triton_checks_passed", 0) or 0)
            zone_cls = "triton-zone-badge is-full" if passed >= checks_total else "triton-zone-badge"

            click = (
                "Shiny.setInputValue('triton_select_row',"
                + html.escape(json.dumps(pid))
                + ",{priority:'event'})"
            )
            parts.append('<tr class="' + row_cls + '" onclick="' + click + '">')
            parts.append(f'<td class="triton-col-rank">{int(record["triton_rank"])}</td>')
            parts.append(
                '<td><div class="triton-table-player">'
                f'{html.escape(str(record["name"]))}</div>'
                + (f'<div class="triton-table-meta">{html.escape(meta)}</div>' if meta else "")
                + "</td>"
            )
            conf_text = str(record.get("confName", "") or "").strip() or dash
            parts.append("<td>" + html.escape(conf_text) + "</td>")
            parts.append(f"<td>{inches_display(record.get('heightIn'))}</td>")
            mpg_text = f"{mpg:.1f}" if np.isfinite(mpg) else dash
            parts.append("<td>" + mpg_text + "</td>")
            parts.append(
                '<td class="triton-col-war">'
                f'<div class="triton-war-value">{war_text}</div>'
                f'<div class="triton-war-track"><div class="triton-war-fill" '
                f'style="width:{war_width:.1f}%"></div></div></td>'
            )
            parts.append(f'<td><span class="{zone_cls}">{passed}/{checks_total}</span></td>')
            for metric in TRITON_ZONE_METRICS:
                key = metric["key"]
                cell_cls = (
                    "triton-metric is-pass"
                    if bool(record.get(f"triton_ok_{key}", False))
                    else "triton-metric is-miss"
                )
                parts.append(
                    f'<td><span class="{cell_cls}" title="{metric_titles[key]}">'
                    f'{triton_format_value(metric, record.get(f"triton_val_{key}"))}</span></td>'
                )
            tags = [
                f'<span class="triton-arch-tag">{label}</span>'
                for arch_key, label in archetype_labels.items()
                if bool(record.get(f"triton_is_{arch_key}", False))
            ]
            if bool(record.get("low_sample_size", False)):
                tags.append('<span class="triton-arch-tag is-warn">Low sample</span>')
            parts.append(
                '<td><div class="triton-arch-tags">' + "".join(tags) + "</div></td>"
                if tags
                else "<td>" + dash + "</td>"
            )
            parts.append("</tr>")

        parts.append("</tbody></table></div>")
        return ui.HTML("".join(parts))

    @reactive.effect
    @reactive.event(input.hist_select_row)
    def _hist_select_row():
        row_id = str(input.hist_select_row() or "").strip()
        if not row_id:
            return
        source_row = historical_row_by_id(row_id)
        if source_row is None:
            return
        modal_player.set(None)
        modal_req.set(None)
        hist_selected.set(row_id)
        hist_modal_selected.set(row_id)
        hist_modal_exclude_low_sample_state.set(False)
        ui.modal_show(
            make_historical_profile_modal(
                source_row,
                exclude_low_sample=bool(hist_modal_exclude_low_sample_state.get()),
                triton_tracker_ids=triton_tracker_ids.get(),
            )
        )

    @reactive.effect
    @reactive.event(input.hist_open_current_profile)
    def _hist_open_current_profile():
        pid = str(input.hist_open_current_profile() or "").strip()
        if not pid:
            return
        import random
        modal_req.set((pid, random.random()))

    @reactive.effect
    @reactive.event(input.hist_modal_exclude_low_sample_current)
    def _hist_modal_exclude_low_sample_current():
        value = bool(input.hist_modal_exclude_low_sample_current())
        hist_modal_exclude_low_sample_state.set(value)

    @output
    @render.ui
    def hist_modal_current_comps_ui():
        row_id = str(hist_modal_selected.get() or "").strip()
        source_row = historical_row_by_id(row_id)
        if source_row is None:
            return ui.div("Choose a historical player to load current-player comps.", class_="qual-note")
        exclude_low_sample = bool(input.hist_modal_exclude_low_sample_current())
        cards = historical_current_comp_cards(
            source_row,
            exclude_low_sample=exclude_low_sample,
            open_mode="compare",
        )
        if not cards:
            return ui.div("No current-player comps are available for this profile yet.", class_="qual-note")
        return ui.div({"class": "historical-comp-list"}, *cards)

    @reactive.effect
    @reactive.event(input.hist_open_compare)
    def _hist_open_compare():
        payload = input.hist_open_compare() or {}
        if not isinstance(payload, dict):
            return
        source_id = str(payload.get("source_id", "") or "").strip()
        target_id = str(payload.get("target_id", "") or "").strip()
        source_row = historical_row_by_id(source_id)
        if source_row is None or not target_id:
            return
        target_rows = d1_df[d1_df["id"].eq(target_id)]
        if target_rows.empty:
            return
        source_profile = historical_compare_profile_from_row(source_row)
        target_profile = _current_compare_profile_from_row(target_rows.iloc[0])
        return_to = str(payload.get("return_to", "") or "").strip()
        compare_origin = "triton_tracker_long_list" if return_to == "triton_tracker_long_list" else "historical"
        compare_req.set(payload)
        ui.modal_show(
            make_similarity_compare_modal(
                source_profile,
                target_profile,
                compare_origin,
                return_source_id=source_id if compare_origin == "triton_tracker_long_list" else "",
            )
        )

    @reactive.effect
    @reactive.event(input.sim_beta_open_long_list)
    def _sim_beta_open_long_list():
        source_id = str(input.sim_beta_open_long_list() or "").strip()
        if not source_id:
            return
        modal = make_similarity_beta_long_list_modal(source_id)
        if modal is not None:
            ui.modal_show(modal)

    @output
    @render.text
    def hist_results_count():
        total = len(hist_filtered())
        shown = len(hist_display_rows())
        return f"{shown} of {total} matching players"

    @output
    @render.text
    def hist_height_range_label():
        lo, hi = safe_range_input(input.hist_height(), HISTORICAL_PLAYER_INDEX, "height_inches", 1)
        return f"{inches_display(lo)} to {inches_display(hi)}"

    @output
    @render.ui
    def historical_table_ui():
        rows = hist_display_rows()
        if rows.empty:
            return ui.div("No historical players match those filters.", class_="historical-empty")

        selected = str(hist_selected.get() or "")
        sort_col = hist_sort_col.get()
        sort_dir = hist_sort_dir.get()

        def sort_label(label, col):
            marker = ""
            if sort_col == col:
                marker = " ↓" if sort_dir == "desc" else " ↑"
            return ui.tags.button(
                f"{label}{marker}",
                onclick=f"Shiny.setInputValue('hist_sort_click','{col}',{{priority:'event'}})",
            )

        body_rows = []
        for _, row in rows.iterrows():
            row_id = str(row["season_player_id"])
            selected_cls = " is-selected" if row_id == selected else ""
            name_meta = " · ".join([bit for bit in [str(row.get("class", "")).strip(), str(row.get("role", "")).strip()] if bit])
            body_rows.append(
                ui.tags.tr(
                    {
                        "class": f"historical-row{selected_cls}",
                        "onclick": f"window.ucsdOpenHistoricalProfile && window.ucsdOpenHistoricalProfile({json.dumps(row_id)})",
                    },
                    ui.tags.td(
                        ui.div(str(row["player_name"]), class_="historical-table-player"),
                        ui.div(name_meta, class_="historical-table-meta") if name_meta else ui.div(),
                    ),
                    ui.tags.td(str(int(row["year"])) if pd.notna(row["year"]) else "\u2014"),
                    ui.tags.td(str(row.get("conf", "") or "\u2014")),
                    ui.tags.td(str(row.get("team", "") or "\u2014")),
                    ui.tags.td(str(row.get("pos", "") or "\u2014")),
                    ui.tags.td(str(row.get("archetype", "") or "\u2014")),
                    ui.tags.td(_format_compare_value("height_inches", row.get("height_inches"))),
                    ui.tags.td(f"{_as_float(row.get('mins_per_game')):.1f}" if pd.notna(_as_float(row.get("mins_per_game"))) else "\u2014"),
                    ui.tags.td(f"{_as_float(row.get('pts_per_game')):.1f}" if pd.notna(_as_float(row.get("pts_per_game"))) else "\u2014"),
                    ui.tags.td(f"{_as_float(row.get('ast_per_game')):.1f}" if pd.notna(_as_float(row.get("ast_per_game"))) else "\u2014"),
                    ui.tags.td(f"{_as_float(row.get('treb_per_game')):.1f}" if pd.notna(_as_float(row.get("treb_per_game"))) else "\u2014"),
                    ui.tags.td(f"{_as_float(row.get('bpm')):.1f}" if pd.notna(_as_float(row.get("bpm"))) else "\u2014"),
                )
            )

        return ui.div(
            {"class": "historical-table-card historical-results-table-card"},
            ui.tags.table(
                {"class": "historical-table"},
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th(sort_label("Name", "player_name")),
                        ui.tags.th(sort_label("Year", "year")),
                        ui.tags.th(sort_label("Conference", "conf")),
                        ui.tags.th(sort_label("Team", "team")),
                        ui.tags.th(sort_label("Pos", "pos")),
                        ui.tags.th(sort_label("Archetype", "archetype")),
                        ui.tags.th("Height"),
                        ui.tags.th(sort_label("MPG", "mins_per_game")),
                        ui.tags.th(sort_label("PPG", "pts_per_game")),
                        ui.tags.th(sort_label("APG", "ast_per_game")),
                        ui.tags.th(sort_label("RPG", "treb_per_game")),
                        ui.tags.th(sort_label("BPM", "bpm")),
                    )
                ),
                ui.tags.tbody(*body_rows),
            ),
        )

    @output
    @render.ui
    def historical_current_comps_ui():
        row_id = str(hist_selected.get() or "").strip()
        source_row = historical_row_by_id(row_id)
        if source_row is None:
            return ui.div("Choose a historical player to load current-player comps.", class_="historical-empty")
        exclude_low_sample = bool(input.hist_exclude_low_sample_current())
        cards = historical_current_comp_cards(
            source_row,
            exclude_low_sample=exclude_low_sample,
            open_mode="compare",
        )
        if not cards:
            return ui.div("No current-player comps are available for that historical profile yet.", class_="historical-empty")

        return ui.div(
            {"class": "historical-comps-card"},
            ui.div(
                {"class": "historical-comps-head"},
                ui.div(
                    ui.div("Current players most like this profile", class_="historical-comps-title"),
                    ui.div(historical_profile_subtitle(source_row), class_="historical-comps-subtitle"),
                ),
                ui.div(
                    ui.input_checkbox(
                        "hist_exclude_low_sample_current",
                        f"Exclude current comps under {int(HISTORICAL_CURRENT_COMP_MIN_MPG)} MPG",
                        value=False,
                    ),
                    class_="historical-comps-toggle",
                ),
            ),
            ui.div({"class": "historical-comp-list"}, *cards),
        )

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
        for pid, r, _, div_ in watchlist_rows(wl):
            pc_ = ARCHETYPE_COLOR.get(r["primary_archetype"], POS_COLOR.get(r["pos"], "#888"))
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
                        ui.span(archetype_label(r["primary_archetype"]), class_="pos-badge",
                                style=f"color:{pc_};border-color:{pc_}"),
                        ui.span(
                            str(r["archetype_v2_primary_label"]),
                            class_="pos-badge",
                            style="color:#2f855a;border-color:#2f855a",
                        ) if div_ == "D-I" and bool(r.get("archetype_v2_available", False)) else ui.span(),
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
    @render.ui
    def watchlist_lineup_data():
        payload = build_watchlist_lineup_candidates(watchlist.get())
        payload_json = json.dumps(payload).replace("</", "<\\/")
        return ui.div(
            payload_json,
            id="watchlist-lineup-data",
            style="display:none;",
            **{"data-count": str(len(payload))}
        )

    @output
    @render.ui
    def watchlist_lineup_sync():
        payload = build_watchlist_lineup_candidates(watchlist.get())
        payload_json = json.dumps(payload).replace("</", "<\\/")
        script = f"""
        (function() {{
          const payload = {payload_json};
          try {{
            localStorage.setItem({json.dumps(WATCHLIST_LINEUP_STORAGE_KEY)}, JSON.stringify(payload));
          }} catch (err) {{}}
          const frame = document.getElementById('ucsd-lineup-frame');
          if (frame && frame.contentWindow) {{
            frame.contentWindow.postMessage({{
              type: 'ucsd-watchlist-lineup-sync',
              payload
            }}, window.location.origin);
          }}
        }})();
        """
        return ui.tags.script(script)

    @output
    @render_widget
    def watchlist_radar():
        selected = [pid for pid in radar_selected.get() if pid in watchlist.get()][:2]
        stats = [key for key in radar_stat_selected.get() if key in RADAR_STAT_LOOKUP]
        return make_watchlist_radar(selected, stats)


app = App(app_ui, server, static_assets=HERE / "www")
