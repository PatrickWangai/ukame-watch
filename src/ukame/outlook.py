"""Seasonal outlook: will the next 3 months' rainfall fall in the driest third?

Design rules (all enforced by tests/test_outlook.py):
  * Issue time is the end of month m. Features use only what is known then:
    rainfall up to month m, DMI for month m, ONI for the season centred on month m-1.
  * The "driest third" threshold and every other statistic come from training years only.
  * Time-based split: targets ending before TEST_START_YEAR train; the rest test (>= 8 years).
  * Two baselines: climatology (always the base rate) and persistence (P(dry next | dry now)).
  * Separate logistic models per season group, because East African teleconnections differ by season:
    the Indian Ocean Dipole matters most for the Oct-Dec short rains.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import config as C

FEATURES = ["oni", "dmi", "now_pct"]
MIN_WET_WINDOW_MM = 30.0  # target windows drier than this in a typical training year are dry seasons: skip


def season_group(target_end_month: int) -> str:
    if target_end_month in (11, 12, 1):
        return "short_rains"   # SON, OND, NDJ
    if target_end_month in (4, 5, 6):
        return "long_rains"    # FMA, MAM, AMJ
    return "other"


# ---------------------------------------------------------------- dataset
def build_dataset(mon: pd.DataFrame, idx: pd.DataFrame) -> pd.DataFrame:
    """One row per county and issue month, with leakage-free features and the 3-month-ahead target."""
    frames = []
    for county, g in mon.sort_values(["year", "month"]).groupby("county"):
        g = g.reset_index(drop=True)
        rain = g["rain_mm"].where(g["complete"])
        nxt = rain.shift(-1) + rain.shift(-2) + rain.shift(-3)
        frames.append(pd.DataFrame({
            "county": county,
            "issue_year": g["year"], "issue_month": g["month"],
            "rain_now3_mm": rain.rolling(3).sum(),
            "target_rain_mm": nxt,
        }))
    ds = pd.concat(frames, ignore_index=True)
    ds["target_end_month"] = (ds["issue_month"] + 2) % 12 + 1
    ds["target_year"] = ds["issue_year"] + (ds["issue_month"] + 2) // 12
    ds["season_group"] = ds["target_end_month"].map(season_group)

    dmi = idx[["year", "month", "dmi"]].rename(columns={"year": "issue_year", "month": "issue_month"})
    ds = ds.merge(dmi, on=["issue_year", "issue_month"], how="left")
    # ONI season centred on the previous month (the latest one published at issue time).
    prev_month = (ds["issue_month"] - 2) % 12 + 1
    prev_year = ds["issue_year"] - (ds["issue_month"] == 1).astype(int)
    oni = idx[["year", "month", "oni"]].rename(columns={"year": "_y", "month": "_m"})
    ds = ds.assign(_y=prev_year, _m=prev_month).merge(oni, on=["_y", "_m"], how="left").drop(columns=["_y", "_m"])
    return ds.sort_values(["county", "issue_year", "issue_month"]).reset_index(drop=True)


def add_targets(ds: pd.DataFrame, test_start_year: int = C.TEST_START_YEAR) -> pd.DataFrame:
    """Adds training-only thresholds, the binary target, persistence state and the split label."""
    ds = ds.copy().reset_index(drop=True)  # masks below must align with the merged frames
    train = (ds["target_year"] < test_start_year) & ds["target_rain_mm"].notna()

    tgt = ds[train].groupby(["county", "target_end_month"])["target_rain_mm"]
    stats = pd.DataFrame({"dry_threshold_mm": tgt.quantile(1 / 3), "train_median_mm": tgt.median()}).reset_index()
    ds = ds.merge(stats, on=["county", "target_end_month"], how="left")
    ds["dry"] = (ds["target_rain_mm"] <= ds["dry_threshold_mm"]).astype("boolean")
    ds.loc[ds["target_rain_mm"].isna() | ds["dry_threshold_mm"].isna(), "dry"] = pd.NA
    ds["wet_window"] = ds["train_median_mm"] >= MIN_WET_WINDOW_MM

    now = ds[train].groupby(["county", "issue_month"])["rain_now3_mm"]
    nstats = pd.DataFrame({"now_mean_mm": now.mean(), "now_p33_mm": now.quantile(1 / 3)}).reset_index()
    ds = ds.merge(nstats, on=["county", "issue_month"], how="left")
    # In normally dry months (training mean < 10 mm) "% of normal" is meaningless, so recent rainfall counts as
    # normal (100%) - but only when it was actually observed. Missing recent rainfall stays missing.
    ds["now_pct"] = np.where(ds["now_mean_mm"] >= 10, 100 * ds["rain_now3_mm"] / ds["now_mean_mm"], 100.0)
    ds.loc[ds["rain_now3_mm"].isna(), "now_pct"] = np.nan
    ds["now_pct"] = ds["now_pct"].clip(0, 300)
    ds["dry_now"] = ds["rain_now3_mm"] <= ds["now_p33_mm"]

    ds["split"] = np.where(ds["target_year"] < test_start_year, "train", "test")
    return ds.sort_values(["county", "issue_year", "issue_month"]).reset_index(drop=True)


# ---------------------------------------------------------------- metrics
def metrics(y, p, threshold, clim_prob: float) -> dict:
    """Precision/recall/F1 for 'warn when p > threshold', plus Brier score and Brier skill score vs climatology."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    warn = p > threshold
    tp = float(np.sum(warn & (y == 1)))
    fp = float(np.sum(warn & (y == 0)))
    fn = float(np.sum(~warn & (y == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    brier = float(np.mean((p - y) ** 2))
    brier_clim = float(np.mean((clim_prob - y) ** 2))
    bss = 1 - brier / brier_clim if brier_clim > 0 else 0.0
    return {"n": int(len(y)), "events": int(y.sum()), "precision": precision, "recall": recall, "f1": f1,
            "brier": brier, "bss": bss}


# ---------------------------------------------------------------- models
def _usable(ds: pd.DataFrame) -> pd.Series:
    return ds["wet_window"].fillna(False) & ds[FEATURES].notna().all(axis=1)


def fit(ds: pd.DataFrame) -> dict:
    """Fits one logistic model per season group on training rows. Returns models + baseline probabilities."""
    train = ds[_usable(ds) & (ds["split"] == "train") & ds["dry"].notna()]
    fitted = {}
    for group, g in train.groupby("season_group"):
        y = g["dry"].astype(int)
        model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0))
        model.fit(g[FEATURES], y)
        clim = float(y.mean())
        pers_dry = float(g.loc[g["dry_now"], "dry"].astype(int).mean()) if g["dry_now"].any() else clim
        pers_wet = float(g.loc[~g["dry_now"], "dry"].astype(int).mean()) if (~g["dry_now"]).any() else clim
        coefs = {f: round(float(c), 3) for f, c in zip(FEATURES, model[-1].coef_[0])}
        fitted[group] = {"model": model, "clim": clim, "pers_dry": pers_dry, "pers_wet": pers_wet,
                         "n_train": int(len(g)), "coefficients_standardised": coefs}
    return fitted


def predict(ds: pd.DataFrame, fitted: dict) -> pd.DataFrame:
    out = ds[_usable(ds)].copy()
    out["p_model"] = np.nan
    out["p_clim"] = np.nan
    out["p_persistence"] = np.nan
    for group, f in fitted.items():
        m = out["season_group"] == group
        if not m.any():
            continue
        out.loc[m, "p_model"] = f["model"].predict_proba(out.loc[m, FEATURES])[:, 1]
        out.loc[m, "p_clim"] = f["clim"]
        out.loc[m, "p_persistence"] = np.where(out.loc[m, "dry_now"], f["pers_dry"], f["pers_wet"])
    return out


def evaluate(pred: pd.DataFrame) -> pd.DataFrame:
    """Test-period metrics for model and both baselines: overall, per season group, per county."""
    test = pred[(pred["split"] == "test") & pred["dry"].notna()]
    rows = []
    scopes = [("all", "all", test)]
    scopes += [("season", s, g) for s, g in test.groupby("season_group")]
    scopes += [("county", c, g) for c, g in test.groupby("county")]
    scopes += [("county_season", f"{c} | {s}", g) for (c, s), g in test.groupby(["county", "season_group"])]
    for scope, name, g in scopes:
        y = g["dry"].astype(int).to_numpy()
        clim = g["p_clim"].to_numpy()
        for method, col in [("model", "p_model"), ("climatology", "p_clim"), ("persistence", "p_persistence")]:
            p = g[col].to_numpy()
            # Warn when the probability is above that row's climatological base rate ("higher risk than normal").
            # The tiny tolerance stops floating-point noise from making climatology "warn" against itself.
            m = metrics(y, p, threshold=clim + 1e-9, clim_prob=float(np.mean(clim)))
            # Brier skill vs climatology must use each row's own climatological probability.
            brier_clim = float(np.mean((clim - y) ** 2))
            m["bss"] = 1 - m["brier"] / brier_clim if brier_clim > 0 else 0.0
            rows.append({"scope": scope, "name": name, "method": method, **m})
    out = pd.DataFrame(rows)
    for c in ["precision", "recall", "f1", "brier", "bss"]:
        out[c] = out[c].round(3)
    return out


def current_outlook(ds: pd.DataFrame, fitted: dict) -> pd.DataFrame:
    """The latest issuable forecast per county (features available, target in the future)."""
    ready = ds[ds[FEATURES].notna().all(axis=1)]
    latest = ready.sort_values(["issue_year", "issue_month"]).groupby("county").tail(1)
    rows = []
    for _, r in latest.iterrows():
        f = fitted.get(r["season_group"])
        if f is None or not bool(r.get("wet_window", False)):
            rows.append({"county": r["county"], "issue": f"{r['issue_year']}-{r['issue_month']:02d}",
                         "target_window": _target_label(r), "season_group": r["season_group"],
                         "p_dry_model": None, "note": "Target window is a normal dry season: no outlook issued"})
            continue
        p = float(f["model"].predict_proba(pd.DataFrame([r[FEATURES].astype(float)]))[0, 1])
        rows.append({
            "county": r["county"], "issue": f"{r['issue_year']}-{r['issue_month']:02d}",
            "target_window": _target_label(r), "season_group": r["season_group"],
            "p_dry_model": round(p, 3), "p_dry_model_display": display_probability(p),
            "p_dry_climatology": round(f["clim"], 3),
            "p_dry_persistence": round(f["pers_dry"] if r["dry_now"] else f["pers_wet"], 3),
            "oni": r["oni"], "dmi": r["dmi"], "now_pct_of_training_mean": round(float(r["now_pct"]), 1),
            "dry_threshold_mm": round(float(r["dry_threshold_mm"]), 1), "note": "",
        })
    return pd.DataFrame(rows)


_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def target_label(issue_year: int, issue_month: int) -> str:
    """'Nov 2026 - Jan 2027' or 'Mar - May 2026' for the 3 months after the issue month."""
    start_m, start_y = issue_month % 12 + 1, issue_year + (issue_month == 12)
    end_m = (issue_month + 2) % 12 + 1
    end_y = issue_year + (issue_month + 2) // 12
    if start_y == end_y:
        return f"{_MON[start_m - 1]} - {_MON[end_m - 1]} {end_y}"
    return f"{_MON[start_m - 1]} {start_y} - {_MON[end_m - 1]} {end_y}"


def display_probability(p: float) -> str:
    """Logistic models extrapolate when predictors are extreme (e.g. a record El Nino), so we never show
    probabilities below 5% or above 95% as if they were exact."""
    if p < 0.05:
        return "under 5%"
    if p > 0.95:
        return "over 95%"
    return f"{p * 100:.0f}%"


def _target_label(r) -> str:
    return target_label(int(r["issue_year"]), int(r["issue_month"]))
