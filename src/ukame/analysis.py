"""Weather-behaviour analysis and hazard indicators.

All thresholds come from the 1991-2020 normal period (config.NORMAL_START..NORMAL_END),
so they never use information from the seasonal-outlook test years.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pymannkendall as mk

from . import config as C

MONTH_ABBR = "JFMAMJJASOND"


def window_label(end_month: int, year: int) -> str:
    """3-month window label, e.g. end_month=12 -> 'OND 2023'."""
    months = [(end_month - k - 1) % 12 for k in (2, 1, 0)]
    return "".join(MONTH_ABBR[m] for m in months) + f" {year}"


# ---------------------------------------------------------------- quality checks
def quality_report(daily: pd.DataFrame) -> pd.DataFrame:
    """Coverage, missing values and physically impossible values, per county."""
    rows = []
    for county, g in daily.groupby("county"):
        expected = pd.date_range(g["date"].min(), g["date"].max(), freq="D")
        rows.append({
            "county": county,
            "first_date": g["date"].min().date(),
            "last_date": g["date"].max().date(),
            "days": len(g),
            "missing_dates": len(expected.difference(g["date"])),
            "missing_rain": int(g["precipitation_sum"].isna().sum()),
            "missing_tmax": int(g["temperature_2m_max"].isna().sum()),
            "negative_rain": int((g["precipitation_sum"] < 0).sum()),
            "tmin_above_tmax": int((g["temperature_2m_min"] > g["temperature_2m_max"]).sum()),
            "duplicate_dates": int(g["date"].duplicated().sum()),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- monthly + climatology
def monthly(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.assign(year=daily["date"].dt.year, month=daily["date"].dt.month)
    m = d.groupby(["county", "year", "month"]).agg(
        rain_mm=("precipitation_sum", "sum"),
        tmax_c=("temperature_2m_max", "mean"),
        tmin_c=("temperature_2m_min", "mean"),
        days=("precipitation_sum", "count"),
    ).reset_index()
    m["days_in_month"] = pd.to_datetime(dict(year=m.year, month=m.month, day=1)).dt.days_in_month
    m["complete"] = m["days"] == m["days_in_month"]
    return m


def in_normal(df: pd.DataFrame) -> pd.Series:
    return df["year"].between(C.NORMAL_START, C.NORMAL_END)


def climatology(mon: pd.DataFrame) -> pd.DataFrame:
    """1991-2020 monthly normals per county."""
    base = mon[in_normal(mon) & mon["complete"]]
    return base.groupby(["county", "month"]).agg(
        rain_normal_mm=("rain_mm", "mean"),
        rain_p33_mm=("rain_mm", lambda s: s.quantile(1 / 3)),
        rain_p67_mm=("rain_mm", lambda s: s.quantile(2 / 3)),
        tmax_normal_c=("tmax_c", "mean"),
        tmin_normal_c=("tmin_c", "mean"),
    ).reset_index()


# ---------------------------------------------------------------- drought indicator
MIN_NORMAL_3M_MM = 30.0  # below this the window is a normal dry season: % of normal is not meaningful


def drought_class(pct: float) -> str:
    if pd.isna(pct):
        return "Dry season (not assessed)"
    for upper, label in C.DROUGHT_CLASSES:
        if pct < upper:
            return label
    return "None"


def three_month(mon: pd.DataFrame) -> pd.DataFrame:
    """Rolling 3-month rainfall, its 1991-2020 normal, and % of normal (the drought indicator)."""
    out = []
    for county, g in mon.sort_values(["year", "month"]).groupby("county"):
        g = g.copy()
        g["rain_3m_mm"] = g["rain_mm"].rolling(3).sum()
        g["complete_3m"] = g["complete"].rolling(3).sum() == 3
        out.append(g)
    df = pd.concat(out)
    normals = (df[in_normal(df) & df["complete_3m"]]
               .groupby(["county", "month"])["rain_3m_mm"].mean().rename("normal_3m_mm").reset_index())
    df = df.merge(normals, on=["county", "month"], how="left")
    df["pct_normal"] = np.where(df["normal_3m_mm"] >= MIN_NORMAL_3M_MM,
                                100 * df["rain_3m_mm"] / df["normal_3m_mm"], np.nan)
    df.loc[~df["complete_3m"], "pct_normal"] = np.nan
    df["drought_class"] = df["pct_normal"].map(drought_class)
    df["window"] = [window_label(m, y) for m, y in zip(df["month"], df["year"])]
    return df.sort_values(["county", "year", "month"]).reset_index(drop=True)


# ---------------------------------------------------------------- daily thresholds + extremes
def longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def thresholds(daily: pd.DataFrame) -> pd.DataFrame:
    """Per-county extreme thresholds from the 1991-2020 normal period."""
    rows = []
    for county, g in daily.groupby("county"):
        g = g.sort_values("date")
        base = g[g["date"].dt.year.between(C.NORMAL_START, C.NORMAL_END)]
        r3 = base["precipitation_sum"].rolling(C.HEAVY_RAIN_WINDOW_DAYS).sum()
        wet = base.loc[base["precipitation_sum"] >= C.WET_DAY_MM, "precipitation_sum"]
        rows.append({
            "county": county,
            "heavy_day_p95_mm": round(wet.quantile(C.HEAVY_DAY_PERCENTILE / 100), 1),
            "rain_3day_p99_mm": round(r3.quantile(C.HEAVY_RAIN_PERCENTILE / 100), 1),
            "heat_tmax_p95_c": round(base["temperature_2m_max"].quantile(C.HEAT_PERCENTILE / 100), 1),
        })
    return pd.DataFrame(rows)


def daily_indicators(daily: pd.DataFrame, thr: pd.DataFrame) -> pd.DataFrame:
    """Adds the heavy-rain (3-day total vs p99) and heat (Tmax vs p95) flags to daily data."""
    d = daily.merge(thr, on="county").sort_values(["county", "date"])
    d["rain_3day_mm"] = d.groupby("county")["precipitation_sum"].transform(
        lambda s: s.rolling(C.HEAVY_RAIN_WINDOW_DAYS).sum())
    d["heavy_rain_flag"] = d["rain_3day_mm"] > d["rain_3day_p99_mm"]
    d["heavy_day"] = d["precipitation_sum"] > d["heavy_day_p95_mm"]
    d["heat_flag"] = d["temperature_2m_max"] > d["heat_tmax_p95_c"]
    return d


def annual_extremes(dind: pd.DataFrame) -> pd.DataFrame:
    """Per county-year: totals, longest dry spell, heavy-rain days, max 3-day rain, heat days."""
    d = dind.assign(year=dind["date"].dt.year)
    full_years = d.groupby(["county", "year"])["date"].transform("count") >= 365
    d = d[full_years]
    return d.groupby(["county", "year"]).apply(lambda g: pd.Series({
        "annual_rain_mm": g["precipitation_sum"].sum(),
        "longest_dry_spell_days": longest_run((g["precipitation_sum"] < C.WET_DAY_MM).to_numpy()),
        "heavy_rain_days": int(g["heavy_day"].sum()),
        "max_3day_rain_mm": g["rain_3day_mm"].max(),
        "heat_days": int(g["heat_flag"].sum()),
        "mean_tmax_c": g["temperature_2m_max"].mean(),
    }), include_groups=False).reset_index()


# ---------------------------------------------------------------- trends
def season_totals(tm: pd.DataFrame) -> pd.DataFrame:
    """Long rains (MAM) and short rains (OND) totals per county-year."""
    s = tm[tm["month"].isin([5, 12]) & tm["complete_3m"]].copy()
    s["season"] = s["month"].map({5: "MAM_rain_mm", 12: "OND_rain_mm"})
    return s.pivot_table(index=["county", "year"], columns="season", values="rain_3m_mm").reset_index()


def trends(annual: pd.DataFrame, seasons: pd.DataFrame) -> pd.DataFrame:
    """Mann-Kendall test + Sen's slope (per decade) for each county and variable.

    Note: 8 counties x 8 variables = 64 tests, so ~3 'significant' results are expected
    by chance at p<0.05. We report p-values rather than hiding this.
    """
    data = annual.merge(seasons, on=["county", "year"], how="left")
    variables = ["annual_rain_mm", "MAM_rain_mm", "OND_rain_mm", "longest_dry_spell_days",
                 "heavy_rain_days", "max_3day_rain_mm", "heat_days", "mean_tmax_c"]
    rows = []
    for county, g in data.groupby("county"):
        g = g.sort_values("year")
        for var in variables:
            s = g[var].dropna()
            if len(s) < 10:
                continue
            res = mk.original_test(s.to_numpy())
            rows.append({
                "county": county, "variable": var, "years": f"{g['year'].min()}-{g['year'].max()}",
                "n": len(s), "trend": res.trend, "p_value": round(res.p, 4),
                "sen_slope_per_decade": round(res.slope * 10, 3),
                "significant_5pct": res.p < 0.05,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- heat stress (replaces cyclone module inland)
def heat_stress(dind: pd.DataFrame) -> pd.DataFrame:
    """Monthly hot days per county (maximum temperature above the county's 1991-2020 p95)."""
    d = dind.assign(year=dind["date"].dt.year, month=dind["date"].dt.month)
    return d.groupby(["county", "year", "month"]).agg(
        heat_days=("heat_flag", "sum"), tmax_max_c=("temperature_2m_max", "max")).reset_index()


def heat_by_decade(annual: pd.DataFrame) -> pd.DataFrame:
    a = annual.assign(decade=(annual["year"] // 10) * 10)
    return a.groupby(["county", "decade"])["heat_days"].mean().round(1).reset_index(name="mean_heat_days_per_year")
