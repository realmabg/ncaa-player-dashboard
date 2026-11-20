"""Score current Division I rows against the frozen Core V3 archetypes."""

import json
from pathlib import Path

import numpy as np
import pandas as pd


def solve_memberships(features, model):
    profiles = np.asarray(model["profiles"])
    scaled = (features - model["means"]) / model["standard_deviations"]
    count = len(profiles)
    weights = np.full((len(features), count), 1 / count)
    gram = profiles @ profiles.T
    player_products = scaled @ profiles.T
    ranks = np.arange(1, count + 1)

    # Projected gradient with the same step count and rate as the original
    # out-of-sample scorer. Project each row onto the unit simplex.
    for _ in range(model["steps"]):
        updated = weights - 2 * model["learning_rate"] * (weights @ gram - player_products)
        ordered = np.sort(updated, axis=1)[:, ::-1]
        offsets = (np.cumsum(ordered, axis=1) - 1) / ranks
        last_positive = (ordered > offsets).sum(axis=1) - 1
        weights = np.maximum(updated - offsets[np.arange(len(updated)), last_positive, None], 0)
    return weights


def score_current_players(players):
    model = json.loads(Path(__file__).with_name("core_v3_model.json").read_text())
    minutes = players["gp"] * players["mpg"]
    rim_attempts = players["pbp_rim_made"] + players["pbp_rim_missed"]
    attempts = players[["rim_attempts_total", "mid_attempts_total", "three_attempts_total"]].sum(axis=1)
    rim_assisted = players["pbp_rim_assisted"] / players["pbp_rim_made"].replace(0, np.nan)
    features = pd.DataFrame({
        "ht_inches": players["heightIn"],
        "usg_%": players["usg"] * 100,
        "TS_%": players["ts"] * 100,
        "ORB_%": players["orb_pct"],
        "DRB_%": players["drb_pct"],
        "AST_%": players["ast_pct"],
        "FT_%": players["ft"] * 100,
        "FT_rate": players["ftr"],
        "TP_%": players["tp"] * 100,
        "ast_tov": players["ast_tov"],
        "TOV%": players["tov_pct"],
        "rim_pct_of_total_attempts": (rim_attempts / attempts.replace(0, np.nan)).fillna(0) * 100,
        "rim_%": players["rim_fg_pct"] * 100,
        "mid_pct_of_total_attempts": (players["mid_attempts_total"] / attempts.replace(0, np.nan)).fillna(0) * 100,
        "mid_%": players["mid_fg_pct"] * 100,
        "threePA_per_100": players["3P_per_100_team_pos"],
        "pct_rim_made_assisted": rim_assisted.fillna(0) * 100,
        "pct_three_made_assisted": players["three_assisted_pct"] * 100,
        "pct_total_made_assisted": players["assisted_fg_pct"] * 100,
        "blk_%": players["blk_pct"],
        "stl_%": players["stl_pct"],
        "pf_per_40": players["pf_per_40"],
        "stops_per_40": players["stops_per_40"],
    })
    values = features[model["features"]].to_numpy(dtype=float)
    eligible = minutes.gt(0) & np.isfinite(values).all(axis=1)
    weights = solve_memberships(values[eligible], model)
    scores = pd.DataFrame(weights, index=players.index[eligible], columns=[f"A{i}" for i in range(weights.shape[1])])
    scores["archetype_v2_unstable"] = minutes.lt(150)
    scores["archetype_v2_stability_tier"] = np.select(
        [minutes.loc[eligible].lt(50), minutes.loc[eligible].lt(100), minutes.loc[eligible].lt(150)],
        ["very_unstable", "unstable", "borderline_unstable"],
        default="stable",
    )
    scores["archetype_v2_stability_note"] = "Below 150 minutes of season-to-date play."
    scores.loc[~scores["archetype_v2_unstable"], "archetype_v2_stability_note"] = ""
    return scores
