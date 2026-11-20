"""Triton Zone thresholds and scoring for the shared Division I snapshot."""

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────
# TRITON ZONE / TRITON WAR
# ─────────────────────────────────────────────────────────────────────────
#
# The coaching staff defined a "Triton Zone": seven statistical targets a
# player should clear to fit how UCSD wants to play. Triton WAR turns those
# same seven targets into one 0-100 fit score so the whole country can be
# ranked by them rather than only split into pass/fail.
#
# Each metric is stored in this app on its own scale (3P% as 0-1, TOV% as
# 0-100, ...), so every metric carries the multiplier that puts it back into
# the units the staff speaks in -- whole percentage points. Targets and
# weights below are the defaults; both are adjustable in the tracker tab
# because the staff expects to keep tuning them (eFG% in particular was added
# after the fact).

TRITON_ZONE_METRICS = [
    {
        "key": "efg",
        "col": "efg",
        "label": "eFG%",
        "long": "Effective FG%",
        "scale": 100.0,
        "target": 50.0,
        "kind": "pct",
        "higher_is_better": True,
        "weight": 20.0,
        "input_min": 35.0,
        "input_max": 70.0,
        "step": 0.5,
    },
    {
        "key": "three_pct",
        "col": "tp",
        "label": "3PT%",
        "long": "Three-point percentage",
        "scale": 100.0,
        "target": 36.0,
        "kind": "pct",
        "higher_is_better": True,
        "weight": 18.0,
        "input_min": 25.0,
        "input_max": 50.0,
        "step": 0.5,
    },
    {
        "key": "three_rate",
        "col": "three_share",
        "label": "3PA/FGA",
        "long": "Three-point rate",
        "scale": 100.0,
        "target": 45.0,
        "kind": "pct",
        "higher_is_better": True,
        "weight": 15.0,
        "input_min": 10.0,
        "input_max": 90.0,
        "step": 1.0,
    },
    {
        "key": "tov_pct",
        "col": "tov_pct",
        "label": "TOV%",
        "long": "Turnover rate (lower is better)",
        "scale": 1.0,
        "target": 15.0,
        "kind": "pct",
        "higher_is_better": False,
        "weight": 15.0,
        "input_min": 5.0,
        "input_max": 30.0,
        "step": 0.5,
    },
    {
        "key": "two_pct",
        "col": "two_pct",
        "label": "2PT%",
        "long": "Two-point percentage",
        "scale": 100.0,
        "target": 55.0,
        "kind": "pct",
        "higher_is_better": True,
        "weight": 12.0,
        "input_min": 35.0,
        "input_max": 75.0,
        "step": 0.5,
    },
    {
        "key": "drb_pct",
        "col": "drb_pct",
        "label": "DRB%",
        "long": "Defensive rebound rate",
        "scale": 1.0,
        "target": 15.0,
        "kind": "pct",
        "higher_is_better": True,
        "weight": 12.0,
        "input_min": 2.0,
        "input_max": 35.0,
        "step": 0.5,
    },
    {
        "key": "orb_pct",
        "col": "orb_pct",
        "label": "ORB%",
        "long": "Offensive rebound rate",
        "scale": 1.0,
        "target": 6.0,
        "kind": "pct",
        "higher_is_better": True,
        "weight": 8.0,
        "input_min": 0.0,
        "input_max": 20.0,
        "step": 0.5,
    },
]
TRITON_METRIC_BY_KEY = {metric["key"]: metric for metric in TRITON_ZONE_METRICS}
TRITON_METRIC_KEYS = [metric["key"] for metric in TRITON_ZONE_METRICS]
TRITON_DEFAULT_TARGETS = {metric["key"]: metric["target"] for metric in TRITON_ZONE_METRICS}
TRITON_DEFAULT_WEIGHTS = {metric["key"]: metric["weight"] for metric in TRITON_ZONE_METRICS}

# Special archetypes the staff wants filtered on top of the zone. Each entry
# is an extra set of gates -- a player still carries a Triton WAR score, the
# archetype only narrows who is eligible to appear.
TRITON_SPECIAL_ARCHETYPES = {
    "stretch_big": {
        "label": "Stretch Big",
        "note": "Size that still shoots it: 6'9\" or taller, 34%+ from three on a 40%+ three-point rate.",
        "criteria": [
            {
                "key": "stretch_height",
                "col": "heightIn",
                "label": "Height",
                "scale": 1.0,
                "target": 81.0,
                "higher_is_better": True,
                "kind": "height",
                "input_min": 72.0,
                "input_max": 88.0,
                "step": 1.0,
            },
            {
                "key": "stretch_three_pct",
                "col": "tp",
                "label": "3PT%",
                "scale": 100.0,
                "target": 34.0,
                "higher_is_better": True,
                "kind": "pct",
                "input_min": 20.0,
                "input_max": 50.0,
                "step": 0.5,
            },
            {
                "key": "stretch_three_rate",
                "col": "three_share",
                "label": "3PA/FGA",
                "scale": 100.0,
                "target": 40.0,
                "higher_is_better": True,
                "kind": "pct",
                "input_min": 10.0,
                "input_max": 90.0,
                "step": 1.0,
            },
        ],
    },
    "shooter": {
        "label": "3PT Specialist",
        "note": "Volume shooter: 65%+ of shots from three at better than 35%.",
        "criteria": [
            {
                "key": "shooter_three_rate",
                "col": "three_share",
                "label": "3PA/FGA",
                "scale": 100.0,
                "target": 65.0,
                "higher_is_better": True,
                "kind": "pct",
                "input_min": 30.0,
                "input_max": 95.0,
                "step": 1.0,
            },
            {
                "key": "shooter_three_pct",
                "col": "tp",
                "label": "3PT%",
                "scale": 100.0,
                "target": 35.0,
                "higher_is_better": True,
                "kind": "pct",
                "input_min": 20.0,
                "input_max": 50.0,
                "step": 0.5,
            },
        ],
    },
}
TRITON_SPECIAL_CRITERIA = [
    criterion
    for archetype in TRITON_SPECIAL_ARCHETYPES.values()
    for criterion in archetype["criteria"]
]
TRITON_SPECIAL_DEFAULT_TARGETS = {
    criterion["key"]: criterion["target"] for criterion in TRITON_SPECIAL_CRITERIA
}

# Sub-scores are anchored on the target rather than on a raw percentile, so a
# player who clears every target always lands in the same place no matter how
# the rest of the country shoots that year. The spread below only controls how
# fast a sub-score moves away from the target: one spread past it earns the
# full 100, one and a half short of it bottoms out at 0.
TRITON_SUBSCORE_AT_TARGET = 70.0
TRITON_SPREAD_ABOVE = 1.0
TRITON_SPREAD_BELOW = 1.5
TRITON_SCORE_POOL_MIN_MPG = 10.0


def _triton_metric_series(df, metric):
    """Metric values converted into the whole-percentage-point units the staff
    states targets in (3P% 0-1 becomes 36.0, TOV% is already 15.0)."""
    values = pd.to_numeric(df.get(metric["col"]), errors="coerce")
    if values is None:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return values.astype("float64") * float(metric["scale"])


def _triton_spread(values):
    """Robust half-interquantile spread, with a std fallback for thin columns."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 1.0
    spread = (clean.quantile(0.84) - clean.quantile(0.16)) / 2.0
    if not np.isfinite(spread) or spread <= 0:
        spread = float(clean.std(ddof=0))
    if not np.isfinite(spread) or spread <= 0:
        return 1.0
    return float(spread)


def build_triton_spreads(df):
    """One spread per metric, measured once over the rotation-level D-I pool so
    the scale of a score does not move when the user filters the table."""
    mpg = pd.to_numeric(df.get("mpg"), errors="coerce")
    pool = df[mpg.fillna(0) >= TRITON_SCORE_POOL_MIN_MPG] if mpg is not None else df
    if pool.empty:
        pool = df
    return {
        metric["key"]: _triton_spread(_triton_metric_series(pool, metric))
        for metric in TRITON_ZONE_METRICS
    }


def triton_subscore(values, target, spread, higher_is_better):
    """0-100 fit on one metric. Hitting the target is worth 70; a full spread
    beyond it reaches 100, and one and a half spreads short of it reaches 0.
    The curve is continuous at the target, so nudging a threshold nudges the
    score instead of flipping it."""
    numeric = pd.to_numeric(values, errors="coerce").astype("float64")
    spread = float(spread) if np.isfinite(spread) and spread > 0 else 1.0
    z = (numeric - float(target)) / spread
    if not higher_is_better:
        z = -z
    above = TRITON_SUBSCORE_AT_TARGET + (100.0 - TRITON_SUBSCORE_AT_TARGET) * np.clip(
        z / TRITON_SPREAD_ABOVE, 0.0, 1.0
    )
    below = TRITON_SUBSCORE_AT_TARGET * np.clip(1.0 + z / TRITON_SPREAD_BELOW, 0.0, 1.0)
    scored = np.where(z >= 0, above, below)
    return pd.Series(np.where(np.isnan(z), np.nan, scored), index=numeric.index, dtype="float64")


def compute_triton_frame(df, targets=None, weights=None, spreads=None):
    """Per-metric values, pass flags and sub-scores plus the weighted Triton WAR
    for every row of df. Returned as its own frame so callers can either attach
    the columns or use them for a one-off ranking."""
    targets = {**TRITON_DEFAULT_TARGETS, **(targets or {})}
    weights = {**TRITON_DEFAULT_WEIGHTS, **(weights or {})}
    spreads = spreads if spreads is not None else build_triton_spreads(df)

    out = pd.DataFrame(index=df.index)
    weighted_total = pd.Series(0.0, index=df.index, dtype="float64")
    weight_total = 0.0
    passes = pd.Series(0, index=df.index, dtype="int64")
    zone = pd.Series(True, index=df.index)

    for metric in TRITON_ZONE_METRICS:
        key = metric["key"]
        values = _triton_metric_series(df, metric)
        target = float(targets.get(key, metric["target"]))
        sub = triton_subscore(values, target, spreads.get(key, 1.0), metric["higher_is_better"])
        if metric["higher_is_better"]:
            ok = values >= target
        else:
            ok = values <= target
        ok = ok.fillna(False)
        weight = max(0.0, float(weights.get(key, metric["weight"])))
        out[f"triton_val_{key}"] = values
        out[f"triton_sub_{key}"] = sub
        out[f"triton_ok_{key}"] = ok
        weighted_total = weighted_total.add(sub.fillna(0.0) * weight, fill_value=0.0)
        weight_total += weight
        passes = passes + ok.astype("int64")
        zone = zone & ok

    out["triton_checks_passed"] = passes
    out["triton_checks_total"] = len(TRITON_ZONE_METRICS)
    out["triton_zone"] = zone
    if weight_total > 0:
        out["triton_war"] = (weighted_total / weight_total).clip(0, 100)
    else:
        out["triton_war"] = pd.Series(np.nan, index=df.index, dtype="float64")
    return out


def compute_triton_special(df, special_targets=None):
    """Pass flags for the Stretch Big / 3PT Specialist gates."""
    special_targets = {**TRITON_SPECIAL_DEFAULT_TARGETS, **(special_targets or {})}
    out = pd.DataFrame(index=df.index)
    for arch_key, archetype in TRITON_SPECIAL_ARCHETYPES.items():
        meets = pd.Series(True, index=df.index)
        for criterion in archetype["criteria"]:
            values = _triton_metric_series(df, criterion)
            target = float(special_targets.get(criterion["key"], criterion["target"]))
            ok = (values >= target) if criterion["higher_is_better"] else (values <= target)
            ok = ok.fillna(False)
            out[f"triton_ok_{criterion['key']}"] = ok
            meets = meets & ok
        out[f"triton_is_{arch_key}"] = meets
    return out


def add_triton_columns(df, *, spreads):
    """Attach the default-threshold Triton WAR columns so a player profile can
    show the score without the tracker tab being open."""
    frame = compute_triton_frame(df, spreads=spreads)
    for col in frame.columns:
        df[col] = frame[col]
    special = compute_triton_special(df)
    for col in special.columns:
        df[col] = special[col]
