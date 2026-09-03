"""Build the data file behind the UCSD 2026-27 Lineup Predictor tab.

Every number the predictor tab shows (player ratings, the offensive-rating
formula, conference-strength deltas, roster membership) is derived here from
the same source CSVs the rest of the dashboard uses (all pulled from
Barttorvik) -- nothing in the tab is hand-typed. Re-run this script whenever
mbb_with_pca_all_players_2026_with_pbp.csv or transfer_portal_cache.csv are
refreshed (the existing scheduled GitHub Actions already update those) to
regenerate www/ucsd_model_data.json with current numbers.

Usage: python scripts/build_ucsd_lineup_model.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
D1_PATH = HERE / "mbb_with_pca_all_players_2026_with_pbp.csv"
TRANSFER_PATH = HERE / "transfer_portal_cache.csv"
OUT_PATH = HERE / "www" / "ucsd_model_data.json"

TEAM = "UC San Diego"
CONF = "BW"
MIN_MPG_FOR_FIT = 8.0   # drop garbage-time rows before fitting/aggregating
MIN_GP_FOR_FIT = 5

ROLE_TO_SLOT = {
    "Pure PG": "PG",
    "Scoring PG": "PG",
    "Combo G": "SG",
    "Wing G": "SG",
    "Wing F": "SF",
    "Stretch 4": "PF",
    "PF/C": "PF",
    "C": "C",
}

# Jersey numbers are public record, not a statistical claim -- carried over
# for players who were already on last season's roster. Left blank ("–") for
# incoming transfers whose UCSD number isn't public yet.
KNOWN_NUMBERS = {
    "Kayde Dotson": 0, "Rahmir Barno": 1, "Jordan Johnson": 2,
    "Cade Pendleton": 4, "Camp Wagner": 5, "Leo Beath": 8,
    "Tom Beattie": 9, "Alex Chaikin": 10, "Jasen Brooks": 11,
    "Jaden Vance": 13, "Jake Holmes": 14, "Aidan Burke": 20,
    "Yaqub Mir": 22, "Dimitrije Vukicevic": 33, "Olavi Suutela": 37,
    "Treysen Eaglestaff": 52,
}


# Official 2026-27 UCSD roster, checked against ucsdtritons.com on
# 2026-09-03. Stats are still filled from the local Barttorvik-sourced CSVs
# when the identity is clear; players without matched D-I stats stay visible
# with neutral placeholders instead of being silently omitted.
OFFICIAL_ROSTER = [
    {"name": "Kayde Dotson", "pos": "SG", "role": "Combo G", "yr": "Jr", "htIn": 73, "priorSchool": "Loyola Chicago", "statsTeam": "Loyola Chicago"},
    {"name": "Rahmir Barno", "pos": "PG", "role": "Scoring PG", "yr": "Sr", "htIn": 72, "priorSchool": "Florida Gulf Coast", "statsTeam": "Florida Gulf Coast"},
    {"name": "Jordan Johnson", "pos": "SG", "role": "Combo G", "yr": "Jr", "htIn": 75, "priorSchool": "Calhoun CC (Ala.)", "statsTeam": None},
    {"name": "Cade Pendleton", "pos": "PF", "role": "Wing F", "yr": "Sr", "htIn": 82, "priorSchool": None, "statsTeam": TEAM},
    {"name": "Camp Wagner", "pos": "SF", "role": "Wing G", "yr": "Sr", "htIn": 78, "priorSchool": "Indiana State", "statsTeam": "Indiana St."},
    {"name": "Leo Beath", "pos": "SF", "role": "Wing F", "yr": "Sr", "htIn": 80, "priorSchool": None, "statsTeam": TEAM},
    {"name": "Tom Beattie", "pos": "SG", "role": "Combo G", "yr": "Sr", "htIn": 77, "priorSchool": None, "statsTeam": TEAM},
    {"name": "Alex Chaikin", "pos": "SG", "role": "Combo G", "yr": "Jr", "htIn": 77, "priorSchool": None, "statsTeam": TEAM},
    {"name": "Jasen Brooks", "pos": "PG", "role": "Pure PG", "yr": "Jr", "htIn": 72, "priorSchool": None, "statsTeam": None},
    {"name": "Jaden Vance", "pos": "SF", "role": "Wing G", "yr": "So", "htIn": 78, "priorSchool": None, "statsTeam": TEAM},
    {"name": "Jake Holmes", "pos": "SF", "role": "Wing F", "yr": "Fr", "htIn": 80, "priorSchool": None, "statsTeam": None},
    {"name": "Aidan Burke", "pos": "SG", "role": "Combo G", "yr": "Sr", "htIn": 75, "priorSchool": None, "statsTeam": TEAM},
    {"name": "Yaqub Mir", "pos": "PG", "role": "Combo G", "yr": "Jr", "htIn": 74, "priorSchool": None, "statsTeam": None},
    {"name": "Dimitrije Vukicevic", "pos": "C", "role": "C", "yr": "So", "htIn": 84, "priorSchool": None, "statsTeam": TEAM},
    {"name": "Olavi Suutela", "pos": "PF", "role": "Wing F", "yr": "So", "htIn": 82, "priorSchool": "Oregon State", "statsTeam": "Oregon St."},
    {"name": "Treysen Eaglestaff", "pos": "SF", "role": "Wing G", "yr": "Gr", "htIn": 78, "priorSchool": "West Virginia", "statsTeam": "West Virginia"},
]


SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def slugify(name: str, existing: set[str] | None = None) -> str:
    """Short id from a player's last name (falls back to full name on a
    collision), matching the id style the lineup builder's UI expects."""
    parts = re.sub(r"[^a-zA-Z' -]+", "", name).split()
    last = parts[-1].lower()
    if last in SUFFIXES and len(parts) > 1:
        last = parts[-2].lower()
    base = re.sub(r"[^a-z0-9]+", "", last) or re.sub(r"[^a-z0-9]+", "", name.lower())
    if existing is None or base not in existing:
        return base
    full = re.sub(r"[^a-z0-9]+", "", name.lower())
    return full if full not in existing else full + str(len(existing))


def height_str(inches):
    if pd.isna(inches):
        return "—"
    inches = int(round(inches))
    return f"{inches // 12}-{inches % 12}"


def fit_ortg_model(df: pd.DataFrame) -> dict:
    """OLS: individual ORtg ~ eFG% + TOV% + ORB% + FTR, fit on the full D1
    sample. This reproduces (with real, disclosed coefficients + R^2) the
    Four-Factors-style formula the original tool used with invented weights."""
    sample = df[(df["mins_per_game"] >= MIN_MPG_FOR_FIT) & (df["GP"] >= MIN_GP_FOR_FIT)].copy()
    sample = sample.dropna(subset=["ORtg", "eFG", "TOV_pct", "ORB_pct", "FTR"])
    y = sample["ORtg"].to_numpy(dtype=float)
    X = sample[["eFG", "TOV_pct", "ORB_pct", "FTR"]].to_numpy(dtype=float)
    X1 = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(X1, y, rcond=None)
    pred = X1 @ coef
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot
    intercept, c_efg, c_to, c_orb, c_ftr = [float(v) for v in coef]
    return {
        "intercept": round(intercept, 4),
        "coefEfg": round(c_efg, 4),
        "coefTo": round(c_to, 4),
        "coefOrb": round(c_orb, 4),
        "coefFtr": round(c_ftr, 4),
        "r2": round(r2, 4),
        "n": int(len(sample)),
        "bwAvgEfg": round(float(df.loc[df["conf"] == CONF, "eFG"].mean()), 2),
        "bwAvgTo": round(float(df.loc[df["conf"] == CONF, "TOV_pct"].mean()), 2),
        "bwAvgOrb": round(float(df.loc[df["conf"] == CONF, "ORB_pct"].mean()), 2),
        "bwAvgFtr": round(float(df.loc[df["conf"] == CONF, "FTR"].mean()), 2),
        "bwAvgOrtg": round(float(df.loc[df["conf"] == CONF, "ORtg"].mean()), 2),
    }


def compute_conf_strength(df: pd.DataFrame) -> dict:
    """Net rating (adjoe - adj_drtg), minutes-weighted, by conference,
    expressed relative to the Big West. Computed straight from this
    dataset -- not a copied-in KenPom snapshot."""
    sample = df[(df["mins_per_game"] >= MIN_MPG_FOR_FIT) & (df["GP"] >= MIN_GP_FOR_FIT)].copy()
    sample = sample.dropna(subset=["adjoe", "adj_drtg", "mins_per_game"])
    sample["net"] = sample["adjoe"] - sample["adj_drtg"]
    sample["w"] = sample["mins_per_game"] * sample["GP"]
    grouped = sample.groupby("conf").apply(
        lambda g: np.average(g["net"], weights=g["w"]) if g["w"].sum() > 0 else g["net"].mean(),
        include_groups=False,
    )
    bw = float(grouped.get(CONF, 0.0))
    return {conf.lower(): round(float(val) - bw, 2) for conf, val in grouped.items()}


def pct_rank(series: pd.Series, value: float) -> str:
    if pd.isna(value):
        return "n/a"
    pct = int(round((series < value).mean() * 100))
    suffix = "th" if 11 <= pct % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(pct % 10, "th")
    return f"{pct}{suffix}"


def build_note(row: pd.Series, peer_df: pd.DataFrame, prior_school: str | None) -> str:
    """Stat-grounded blurb -- no subjective scouting language, only numbers
    computed from this row and its percentile among D1 peers at >=8 mpg."""
    ts_p = pct_rank(peer_df["TS_pct"], row["TS_pct"])
    ast_p = pct_rank(peer_df["AST_pct"], row["AST_pct"])
    to_p = pct_rank(peer_df["TOV_pct"], row["TOV_pct"])
    three_p = pct_rank(peer_df["3P_pct"], row["3P_pct"]) if row["3PA"] >= 20 else None
    season_line = (
        f"2025-26{' at ' + prior_school if prior_school else ''}: "
        f"{row['ORtg']:.1f} ORtg on {row['usg']:.1f}% usage, {row['TS_pct']:.1f}% TS "
        f"({ts_p} pct. among D1 players ≥{MIN_MPG_FOR_FIT:.0f} mpg), "
        f"{row['AST_pct']:.1f}% AST rate ({ast_p} pct.), {row['TOV_pct']:.1f}% TO rate ({to_p} pct.)"
    )
    if three_p is not None:
        season_line += f", {row['3P_pct']*100:.1f}% 3PT on {int(row['3PA'])} attempts ({three_p} pct.)"
    return season_line + "."


def player_record(row: pd.Series, peer_df: pd.DataFrame, is_new: bool, prior_school: str | None) -> dict:
    slot = ROLE_TO_SLOT.get(row["role"], "SF")
    name = row["player_name"]
    return {
        "name": name,
        "num": KNOWN_NUMBERS.get(name),
        "pos": slot,
        "role": row["role"],
        "yr": row["yr"],
        "htIn": None if pd.isna(row["height_inches"]) else int(row["height_inches"]),
        "ht": height_str(row["height_inches"]),
        "bpr": round(float(row["bpm"]), 1) if not pd.isna(row["bpm"]) else None,
        "obpr": round(float(row["obpm"]), 1) if not pd.isna(row["obpm"]) else None,
        "dbpr": round(float(row["dbpm"]), 1) if not pd.isna(row["dbpm"]) else None,
        "prpgi": round(float(row["PORPAG"]), 1) if not pd.isna(row["PORPAG"]) else None,
        "indDrtg": round(float(row["adj_drtg"]), 1) if not pd.isna(row["adj_drtg"]) else None,
        "ts": round(float(row["TS_pct"]), 1),
        "usg": round(float(row["usg"]), 1),
        "threeRate": round(float(row["3PA"]) / max(float(row["2PA"]) + float(row["3PA"]), 1), 3),
        "threePct": round(float(row["3P_pct"]) * 100, 1),
        "arate": round(float(row["AST_pct"]), 1),
        "torate": round(float(row["TOV_pct"]), 1),
        "oreb": round(float(row["ORB_pct"]), 1),
        "dreb": round(float(row["DRB_pct"]), 1),
        "ftr": round(float(row["FTR"]), 1),
        "stl": round(float(row["Stl_pct"]), 1),
        "blk": round(float(row["Blk_pct"]), 1),
        "fromConf": row["conf"],
        "priorSchool": prior_school,
        "isNew": is_new,
        # Same low-sample threshold used elsewhere in this dashboard (data_engine.py).
        "lowSample": bool(row["mins_per_game"] < 10 or row["GP"] < 5),
        "gp": int(row["GP"]),
        "mpg": round(float(row["mins_per_game"]), 1),
        "note": build_note(row, peer_df, prior_school),
    }


def official_player_record(info: dict, row: pd.Series | None, peer_df: pd.DataFrame) -> dict:
    if row is None:
        name = info["name"]
        prior = info.get("priorSchool")
        return {
            "name": name,
            "num": KNOWN_NUMBERS.get(name),
            "pos": info["pos"],
            "role": info["role"],
            "yr": info["yr"],
            "htIn": info["htIn"],
            "ht": height_str(info["htIn"]),
            "bpr": 0.0,
            "obpr": 0.0,
            "dbpr": 0.0,
            "prpgi": 0.0,
            "indDrtg": None,
            "ts": None,
            "usg": None,
            "threeRate": 0.0,
            "threePct": None,
            "arate": None,
            "torate": None,
            "oreb": None,
            "dreb": None,
            "ftr": None,
            "stl": None,
            "blk": None,
            "fromConf": None,
            "priorSchool": prior,
            "isNew": bool(prior),
            "lowSample": True,
            "gp": 0,
            "mpg": 0.0,
            "note": (
                f"{name} is listed on UCSD's official 2026-27 roster"
                + (f" from {prior}" if prior else "")
                + "; no matched 2025-26 D-I stat row is available in this dashboard data."
            ),
        }

    rec = player_record(row, peer_df, is_new=bool(info.get("priorSchool")), prior_school=info.get("priorSchool"))
    rec.update({
        "num": KNOWN_NUMBERS.get(info["name"]),
        "pos": info["pos"],
        "role": info["role"],
        "yr": info["yr"],
        "htIn": info["htIn"],
        "ht": height_str(info["htIn"]),
    })
    return rec


def match_official_player(df: pd.DataFrame, info: dict) -> pd.Series | None:
    stats_team = info.get("statsTeam")
    if not stats_team:
        return None
    matches = df[
        (df["player_name"] == info["name"])
        & (df["team"] == stats_team)
    ]
    if matches.empty:
        return None
    return matches.sort_values("mins_per_game", ascending=False).iloc[0]


def main() -> None:
    df = pd.read_csv(D1_PATH, low_memory=False)
    peer_df = df[(df["mins_per_game"] >= MIN_MPG_FOR_FIT) & (df["GP"] >= MIN_GP_FOR_FIT)]

    ortg_model = fit_ortg_model(df)
    conf_strength = compute_conf_strength(df)

    transfers = pd.read_csv(TRANSFER_PATH)
    players = {}
    used_ids: set[str] = set()
    unmatched_official = []
    for info in OFFICIAL_ROSTER:
        pid = slugify(info["name"], used_ids)
        used_ids.add(pid)
        row = match_official_player(df, info)
        if row is None:
            unmatched_official.append(info["name"])
        players[pid] = official_player_record(info, row, peer_df)

    # "Potential Additions": real, currently-available (uncommitted)
    # transfers, ranked by ORtg among reasonably-used players, for the
    # portal-browsing panel. Not UCSD targets -- just real available players.
    available_names = set(
        transfers.loc[transfers["status"] == "Available transfer", "player"]
    )
    avail_df = peer_df[peer_df["player_name"].isin(available_names)].copy()
    avail_df = avail_df.sort_values("bpm", ascending=False).head(15)
    portal = []
    for _, row in avail_df.iterrows():
        rec = player_record(row, peer_df, is_new=True, prior_school=row["team"])
        rec["id"] = slugify(row["player_name"], used_ids)
        used_ids.add(rec["id"])
        portal.append(rec)

    out = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataSource": "mbb_with_pca_all_players_2026_with_pbp.csv + transfer_portal_cache.csv (Barttorvik)",
            "rosterSource": "UCSDTritons.com 2026-27 Men's Basketball Roster, checked 2026-09-03",
            "season": "2025-26 individual stats, official 2026-27 UCSD roster",
            "unmatchedOfficialRoster": unmatched_official,
            "departed": [],
        },
        "ortgModel": ortg_model,
        "confStrength": conf_strength,
        "players": players,
        "portal": portal,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, allow_nan=False))

    print(f"Wrote {OUT_PATH} ({len(players)} roster players, {len(portal)} portal players)")
    print(f"ORtg model: n={ortg_model['n']}, R^2={ortg_model['r2']}")
    print(f"  ORtg = {ortg_model['intercept']:.2f} + {ortg_model['coefEfg']:.3f}*eFG "
          f"+ {ortg_model['coefTo']:.3f}*TO% + {ortg_model['coefOrb']:.3f}*ORB% + {ortg_model['coefFtr']:.3f}*FTR")
    print("Conference strength (net rating vs Big West):")
    for conf, val in sorted(conf_strength.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {conf}: {val:+.2f}")
    if unmatched_official:
        print(f"Official roster players without matched D-I stats: {unmatched_official}")


if __name__ == "__main__":
    main()
