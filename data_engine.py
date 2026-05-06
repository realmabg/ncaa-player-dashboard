"""
data_engine.py — NCAA Player Atlas
Loads and prepares player datasets for D-II (data.csv) and D-I (mbb_with_pca.csv).

Both loaders return the exact same dict shape so app.py needs zero branching.

D-II column set  → load_data()     (original schema)
D-I  column set  → load_d1_data()  (barttorvik/kenpom schema, different names & scales)
"""

import pandas as pd
import numpy as np
import re
from scipy.spatial.distance import cdist

POS_COLOR = {
    "G":   "#2c5e7a",
    "G/F": "#6c8a3a",
    "F":   "#c47a1d",
    "F/C": "#9a3b6a",
    "C":   "#5c4a8a",
}

POS_LABEL = {
    "G":   "Guard",
    "G/F": "Guard / Forward",
    "F":   "Forward",
    "F/C": "Forward / Center",
    "C":   "Center",
}

POSITIONS = ["G", "G/F", "F", "F/C", "C"]
CLASSES   = ["R", "FR", "SO", "JR", "SR"]

SIM_KEYS = ["PC1", "PC2", "PC3", "PC4"]

# D-I role column → our 5-position system
D1_CONF_NAMES = {
    "A10":  "Atlantic 10",        "ACC":  "ACC",
    "AE":   "America East",       "ASun": "ASUN",
    "Amer": "American Athletic",  "B10":  "Big Ten",
    "B12":  "Big 12",             "BE":   "Big East",
    "BSky": "Big Sky",            "BSth": "Big South",
    "BW":   "Big West",           "CAA":  "Coastal Athletic",
    "CUSA": "Conference USA",     "Horz": "Horizon",
    "Ivy":  "Ivy League",         "MAAC": "MAAC",
    "MAC":  "MAC",                "MEAC": "MEAC",
    "MVC":  "Missouri Valley",    "MWC":  "Mountain West",
    "NEC":  "Northeast",          "OVC":  "Ohio Valley",
    "Pat":  "Patriot",            "SB":   "Sun Belt",
    "SC":   "Southern",           "SEC":  "SEC",
    "SWAC": "Southwestern Athletic", "Slnd": "Southland",
    "Sum":  "Summit",             "WAC":  "WAC",
    "WCC":  "West Coast",
}

D1_ROLE_MAP = {
    "Pure PG":    "G",
    "Scoring PG": "G",
    "Combo G":    "G",
    "Wing G":     "G/F",
    "Wing F":     "F",
    "Stretch 4":  "F/C",
    "PF/C":       "F/C",
    "C":          "C",
}


# ─────────────────────────────────────────────────────────────────────────
# SHARED UTILITIES
# ─────────────────────────────────────────────────────────────────────────

def flip_name(s: str) -> str:
    """'Last, First' -> 'First Last' (D-II names). D-I names are already natural order."""
    if not isinstance(s, str):
        return ""
    s = s.strip()
    idx = s.find(",")
    if idx == -1:
        return s
    last  = s[:idx].strip()
    first = s[idx+1:].strip()
    return f"{first} {last}".strip()


def normalize_class(s: str) -> str:
    v = (s or "").lower().replace(".", "").strip()
    if v.startswith("fr"): return "FR"
    if v.startswith("so"): return "SO"
    if v.startswith("jr"): return "JR"
    if v.startswith("sr"): return "SR"
    if v.startswith("r"):  return "R"
    return "SR"


def refine_position(raw: str) -> str:
    r = ("" if pd.isna(raw) else str(raw)).strip().upper()
    if r in ("G", "G/F", "F", "F/C", "C"):
        return r
    if r.startswith("G/F") or r.startswith("GF"): return "G/F"
    if r.startswith("F/C") or r.startswith("FC"): return "F/C"
    if r.startswith("G"): return "G"
    if r.startswith("F"): return "F"
    if r.startswith("C"): return "C"
    return "G"


def height_str(inches: int) -> str:
    ft   = int(inches) // 12
    inch = int(inches) % 12
    return f"{ft}'{inch}\""


def conf_abbr(name: str) -> str:
    if not name:
        return "—"
    words = re.sub(r"[^A-Za-z ]", "", name).split()
    if len(words) == 1:
        return words[0][:5].upper()
    return "".join(w[0] for w in words)[:5].upper()


def _build_output(df: pd.DataFrame, id_prefix: str) -> dict:
    """
    Common finalisation: assign IDs, z-score PCs, compute league avgs,
    build conference table, attach similarity function.
    Called by both loaders after they've normalised column names.
    """
    df = df[df["name"].str.len() > 0].copy().reset_index(drop=True)
    df["id"] = [id_prefix + str(i) for i in range(len(df))]

    # ── Mahalanobis setup ────────────────────────────────────────
    PC_mat = df[SIM_KEYS].values.astype(float)
    cov    = np.cov(PC_mat, rowvar=False)
    # Regularise: add small diagonal to avoid singular matrix
    # (can happen with tiny datasets or near-constant PCs)
    cov   += np.eye(len(SIM_KEYS)) * 1e-6
    VI     = np.linalg.inv(cov)          # inverse covariance matrix
    '''
    # z-score PCs for similarity
    for k in SIM_KEYS:
        mu = df[k].mean()
        sd = df[k].std() or 1
        df[f"_z_{k}"] = (df[k] - mu) / sd

    Z_cols = [f"_z_{k}" for k in SIM_KEYS]
    Z      = df[Z_cols].values
'''
    # league averages
    avg_cols = ["ppg","rpg","apg","spg","bpg","tov","fg","tp","ft","ts","usg","mpg"]
    league_avg = {c: float(df[c].mean()) for c in avg_cols}

    # conference table
    conf_df = (
        df[["conf","confName","team"]]
        .drop_duplicates()
        .groupby(["conf","confName"])["team"]
        .apply(lambda s: sorted(s.unique().tolist()))
        .reset_index()
        .rename(columns={"team": "teams"})
        .sort_values("confName")
        .reset_index(drop=True)
    )
    conferences = conf_df.to_dict("records")

    # similarity closure
    def similar_to(player_id: str, n_sim: int = 5):
        idx = df.index[df["id"] == player_id]
        if len(idx) == 0:
            return []
        i    = idx[0]
        vec  = PC_mat[i].reshape(1, -1)          # (1, 4)

        # cdist with Mahalanobis returns shape (1, N)
        dists = cdist(vec, PC_mat, metric="mahalanobis", VI=VI).flatten()
        dists[i] = np.inf

        sorted_idx = np.argsort(dists)
        ref_idx    = min(len(dists) - 1, max(20, n_sim * 4))
        ref_dist   = dists[sorted_idx[ref_idx]] or 1.0

        results = []
        for j in sorted_idx[:n_sim]:
            row = df.iloc[j]
            results.append({
                "id":         row["id"],
                "name":       row["name"],
                "pos":        row["pos"],
                "team":       row["team"],
                "cls":        row["cls"],
                "ppg":        row["ppg"],
                "rpg":        row["rpg"],
                "apg":        row["apg"],
                "similarity": float(max(0, 1 - dists[j] / ref_dist)),
                "distance":   float(dists[j]),
            })
        return results
    
    return {
        "df":          df,
        "conferences": conferences,
        "positions":   POSITIONS,
        "classes":     CLASSES,
        "league_avg":  league_avg,
        "similar_to":  similar_to,
        "height_str":  height_str,
    }

# ─────────────────────────────────────────────────────────────────────────
# D-II LOADER  (original schema)
# ─────────────────────────────────────────────────────────────────────────

def load_data(csv_path: str, id_prefix: str = "d2p") -> dict:
    """
    Load D-II dataset (data.csv).
    Column names match the original D-II schema produced by the cleaning pipeline.
    Percentages are already 0-1 fractions.
    """
    raw = pd.read_csv(csv_path)

    def n(col):
        return pd.to_numeric(raw.get(col, 0), errors="coerce").fillna(0)

    df = pd.DataFrame()
    df["name"]         = raw["Player Name"].apply(flip_name)
    df["pos"]          = raw["Position"].apply(refine_position)
    df["cls"]          = raw["Year"].apply(normalize_class)
    df["team"]         = raw["Team"].str.strip()
    df["confName"]     = raw["Conference"].str.strip()
    df["conf"]         = df["confName"].apply(conf_abbr)
    df["heightIn"]     = pd.to_numeric(raw["Height"], errors="coerce").fillna(72).round().astype(int)
    df["gp"]           = n("GP").round().astype(int)
    df["mpg"]          = n("MPG")
    df["ppg"]          = n("PPG")
    df["rpg"]          = n("RPG")
    df["apg"]          = n("APG")
    df["spg"]          = n("SPG")
    df["bpg"]          = n("BPG")
    df["tov"]          = n("TOPG")
    df["orb"]          = n("ORBPG")
    df["drb"]          = n("DRBPG")
    df["fg"]           = n("FG%")          # 0-1
    df["tp"]           = n("3PT%")         # 0-1
    df["ft"]           = n("FT%")          # 0-1
    df["ts"]           = n("TS_pct")       # 0-1
    df["usg"]          = n("usg")          # 0-1 or percentage — keep as-is
    df["efg"]          = n("eFG")
    df["three_share"]  = n("three_share")
    df["ast_tov"]      = n("AST_TOV")
    df["PC1"]          = n("PC1")
    df["PC2"]          = n("PC2")
    df["PC3"]          = n("PC3")
    df["PC4"]          = n("PC4")

    return _build_output(df, id_prefix)


# ─────────────────────────────────────────────────────────────────────────
# D-I LOADER  (barttorvik/kenpom schema)
# ─────────────────────────────────────────────────────────────────────────
#
# Key differences from D-II schema:
#   - column names are snake_case, all lowercase
#   - player_name is already "First Last" (no flip needed)
#   - conf is already abbreviated (e.g. "B10", "SEC") — no full name available
#   - no Position column; use role -> 5-category mapping
#   - TS_pct, eFG are 0-100 scale  →  divide by 100
#   - 3P_pct, FT_pct are 0-1 scale →  keep as-is
#   - usg is 0-100 scale           →  divide by 100
#   - PCs are arch_PC1/2/3 + val_PC1 (four components, different names)
#   - No FG% column; use eFG/100 as proxy (best available overall shooting %)

def load_d1_data(csv_path: str, id_prefix: str = "d1p") -> dict:
    """
    Load D-I dataset (mbb_with_pca.csv).
    Remaps column names and rescales percentages to match the shared schema
    expected by app.py helpers.
    """
    raw = pd.read_csv(csv_path)

    def n(col):
        return pd.to_numeric(raw.get(col, 0), errors="coerce").fillna(0)

    df = pd.DataFrame()

    # Identity
    df["name"]     = raw["player_name"].str.strip()
    df["team"]     = raw["team"].str.strip()
    df["conf"]     = raw["conf"].str.strip()
    df["confName"] = df["conf"].map(D1_CONF_NAMES).fillna(df["conf"])

    # Position — map role to 5-category system
    df["pos"] = raw["role"].map(D1_ROLE_MAP).fillna("G")

    # Class
    df["cls"] = raw["yr"].apply(normalize_class)

    # Height — already in inches
    df["heightIn"] = pd.to_numeric(raw["height_inches"], errors="coerce").fillna(78).round().astype(int)

    # Counting / rate stats (already per-game)
    df["gp"]  = n("GP").round().astype(int)
    df["mpg"] = n("mins_per_game")
    df["ppg"] = n("pts_per_game")
    df["rpg"] = n("treb_per_game")
    df["apg"] = n("ast_per_game")
    df["spg"] = n("stl_per_game")
    df["bpg"] = n("blk_per_game")
    df["orb"] = n("oreb_per_game")
    df["drb"] = n("dreb_per_game")

    # Assist-to-turnover (raw tov col is TOV_per_24; use AST_TOV ratio directly)
    df["ast_tov"] = n("AST_TOV")
    # Reconstruct tov per-game from AST_TOV ratio and apg (apg / ast_tov, guarded)
    df["tov"] = (df["apg"] / df["ast_tov"].replace(0, np.nan)).fillna(0)

    # Shooting percentages — D-I has mixed scales:
    #   eFG, TS_pct  → 0-100  →  /100
    #   3P_pct, FT_pct → 0-1  →  keep
    df["fg"]  = n("eFG") / 100.0        # best proxy for overall FG; eFG scaled 0-100
    df["tp"]  = n("3P_pct")             # already 0-1
    df["ft"]  = n("FT_pct")             # already 0-1
    df["ts"]  = n("TS_pct") / 100.0     # scaled 0-100 → 0-1
    df["efg"] = n("eFG") / 100.0        # 0-1 for slider

    # Usage — 0-100 in D-I → /100 for consistency with D-II (both end up ~0.19 mean)
    df["usg"] = n("usg") / 100.0

    # 3P share — already 0-1
    df["three_share"] = n("three_share")

    # PCs — four components with different names in this dataset
    #   arch_PC1, arch_PC2, arch_PC3  →  PC1, PC2, PC3   (archetype / style)
    #   val_PC1                        →  PC4             (value / performance)
    df["PC1"] = n("arch_PC1")
    df["PC2"] = n("arch_PC2")
    df["PC3"] = n("arch_PC3")
    df["PC4"] = n("val_PC1")

    return _build_output(df, id_prefix)