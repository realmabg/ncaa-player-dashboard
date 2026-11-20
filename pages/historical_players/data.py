"""Read archived Division I player seasons and the derived comparison tables."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "data" / "historical"


def resolve_csv(name):
    # The compressed tables keep the static Shinylive export below its size limit.
    for folder in (ARCHIVE, ROOT.parent / "historical_comps_output"):
        for filename in (f"{name}.gz", name):
            path = folder / filename
            if path.is_file():
                return path
    return None


def load_historical_neighbors(season, pool_key="all"):
    subset = "big_west_next_year" if pool_key == "big_west_next_year" else "all"
    path = resolve_csv(f"d1_historical_neighbors_{season}_prior_{subset}.csv")
    if path is None:
        return pd.DataFrame()
    df = pd.read_csv(path)
    text_cols = [
        "target_player_name",
        "target_team",
        "match_player_name",
        "match_team",
        "match_conf",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    return df

def load_historical_scores(season):
    path = resolve_csv(f"d1_historical_current_category_scores_{season}.csv")
    if path is None:
        path = resolve_csv("d1_historical_category_scores.csv")
    if path is None:
        return pd.DataFrame()
    df = pd.read_csv(path)
    text_cols = ["season_player_id", "player_name", "team", "conf"]
    numeric_cols = [
        "year",
        "GP",
        "mins_per_game",
        "height_inches",
        "eFG",
        "FT_pct",
        "3P_pct",
        "3P_per_100_team_pos",
        "AST_TOV",
        "AST_pct",
        "Blk_pct",
        "DRB_pct",
        "FTR",
        "ORB_pct",
        "Stl_pct",
        "TOV_pct",
        "assisted_fg_pct",
        "personal_fouls_per_40",
        "rim_assisted_pct",
        "rim_pct",
        "rim_share",
        "mid_pct",
        "mid_share",
        "dunk_pct",
        "dunk_share",
        "stops_per_40",
        "three_assisted_pct",
        "three_share",
        "usg",
        "workload_score",
        "shot_style_score",
        "spacing_score",
        "rim_finishing_score",
        "rebounding_score",
        "defense_score",
        "ballhandling_score",
        "height_score",
        "workload_grade",
        "shot_style_grade",
        "spacing_grade",
        "rim_finishing_grade",
        "rebounding_grade",
        "defense_grade",
        "ballhandling_grade",
        "height_grade",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

def load_historical_player_index(season):
    path = resolve_csv("d1_historical_player_index.csv")
    if path is None:
        return pd.DataFrame()
    df = pd.read_csv(path)
    text_cols = [
        "season_player_id",
        "player_name",
        "team",
        "conf",
        "class",
        "role",
        "pos",
        "archetype",
        "height",
    ]
    numeric_cols = [
        "year",
        "GP",
        "mins_per_game",
        "pts_per_game",
        "ast_per_game",
        "treb_per_game",
        "bpm",
        "height_inches",
        "eFG",
        "FT_pct",
        "3P_pct",
        "3P_per_100_team_pos",
        "AST_TOV",
        "AST_pct",
        "Blk_pct",
        "DRB_pct",
        "FTR",
        "ORB_pct",
        "Stl_pct",
        "TOV_pct",
        "assisted_fg_pct",
        "personal_fouls_per_40",
        "rim_assisted_pct",
        "rim_pct",
        "rim_share",
        "mid_pct",
        "mid_share",
        "dunk_pct",
        "dunk_share",
        "stops_per_40",
        "three_assisted_pct",
        "three_share",
        "usg",
        "workload_score",
        "shot_style_score",
        "spacing_score",
        "rim_finishing_score",
        "rebounding_score",
        "defense_score",
        "ballhandling_score",
        "height_score",
        "workload_grade",
        "shot_style_grade",
        "spacing_grade",
        "rim_finishing_grade",
        "rebounding_grade",
        "defense_grade",
        "ballhandling_grade",
        "height_grade",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "year" in df.columns:
        df = df[df["year"].lt(season)].copy()
    return df
