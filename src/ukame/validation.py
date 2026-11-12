"""Validate the hazard indicators against documented droughts and floods.

Two checks, as the challenge asks:
  1. Find the 3 worst drought periods and 3 worst heavy-rain periods in our indicators, and see
     whether each matches a documented event.
  2. For each documented event, check whether our indicator flagged it.
"""
from __future__ import annotations

import pandas as pd

DROUGHT_DETECT_PCT = 75.0  # regional 3-month rainfall below 75% of normal = drought signal


def _mi(year, month):
    return year * 12 + month - 1


def top_periods(df: pd.DataFrame, col: str, n: int = 3, lowest: bool = True, min_gap_months: int = 12) -> pd.DataFrame:
    """The n most extreme months, each at least `min_gap_months` from the others (distinct events)."""
    d = df.dropna(subset=[col]).sort_values(col, ascending=lowest)
    picked = []
    for r in d.itertuples(index=False):
        idx = _mi(r.year, r.month)
        if all(abs(idx - _mi(p.year, p.month)) >= min_gap_months for p in picked):
            picked.append(r)
        if len(picked) == n:
            break
    return pd.DataFrame(picked, columns=d.columns).reset_index(drop=True)


RAINY_SEASON_END_MONTHS = (5, 12)  # MAM long rains, OND short rains: drought = a failed rainy season


def regional_drought_pct(tm: pd.DataFrame, min_counties: int = 5, months=RAINY_SEASON_END_MONTHS) -> pd.DataFrame:
    """Mean % of normal across counties for each 3-month window ending in `months`
    (only where most counties are assessed)."""
    tm = tm[tm["month"].isin(months)] if months else tm
    g = tm.dropna(subset=["pct_normal"]).groupby(["year", "month"])["pct_normal"]
    out = pd.DataFrame({"value": g.mean(), "n_counties": g.count()}).reset_index()
    return out[out["n_counties"] >= min_counties].reset_index(drop=True)


def regional_heavy_counts(dind: pd.DataFrame) -> pd.DataFrame:
    """Monthly number of county-days with a heavy-rain flag (3-day total above the county p99)."""
    d = dind.assign(year=dind["date"].dt.year, month=dind["date"].dt.month)
    return d.groupby(["year", "month"])["heavy_rain_flag"].sum().astype(int).reset_index(name="value")


def rolling_3m(monthly: pd.DataFrame) -> pd.DataFrame:
    m = monthly.sort_values(["year", "month"]).copy()
    m["value"] = m["value"].rolling(3).sum()
    return m


def check_documented(events: pd.DataFrame, drought_pct: pd.DataFrame, heavy_counts: pd.DataFrame,
                     heavy_threshold: float) -> pd.DataFrame:
    rows = []
    for e in events.itertuples(index=False):
        start, end = pd.Timestamp(e.start), pd.Timestamp(e.end)
        lo, hi = _mi(start.year, start.month), _mi(end.year, end.month)
        if e.hazard == "drought":
            s = drought_pct[(drought_pct.apply(lambda r: lo <= _mi(r.year, r.month) <= hi, axis=1))] \
                if len(drought_pct) else drought_pct
            value = float(s["value"].min()) if len(s) else None
            detected = value is not None and value < DROUGHT_DETECT_PCT
            indicator, threshold = "lowest regional 3-month % of normal in window", f"< {DROUGHT_DETECT_PCT:.0f}%"
        else:
            s = heavy_counts[(heavy_counts.apply(lambda r: lo <= _mi(r.year, r.month) <= hi, axis=1))] \
                if len(heavy_counts) else heavy_counts
            value = int(s["value"].sum()) if len(s) else 0
            detected = value >= heavy_threshold
            indicator, threshold = "county-days with 3-day rain above p99 in window", f">= {heavy_threshold:g}"
        rows.append({"event_id": e.event_id, "hazard": e.hazard, "label": e.label, "start": e.start, "end": e.end,
                     "indicator": indicator, "indicator_value": value, "threshold": threshold,
                     "detected": detected, "source_url": e.source_url})
    return pd.DataFrame(rows)


def match_to_events(top: pd.DataFrame, events: pd.DataFrame, hazard: str) -> pd.DataFrame:
    """For each of our top periods (window ending in year/month), name the documented event it overlaps, if any."""
    ev = events[events["hazard"] == hazard]
    out = []
    for r in top.itertuples(index=False):
        # A 3-month window ending at (year, month) covers months m-2..m.
        w_hi = _mi(r.year, r.month)
        w_lo = w_hi - 2
        match = ""
        for e in ev.itertuples(index=False):
            s, t = pd.Timestamp(e.start), pd.Timestamp(e.end)
            if w_lo <= _mi(t.year, t.month) and _mi(s.year, s.month) <= w_hi:
                match = f"{e.event_id}: {e.label}"
                break
        out.append({"window_end": f"{r.year}-{r.month:02d}", "value": round(float(r.value), 1),
                    "matches_documented_event": match or "no documented event in our list"})
    return pd.DataFrame(out)
