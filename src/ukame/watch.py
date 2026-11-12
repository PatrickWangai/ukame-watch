"""Short-range watch: does the live 7-day forecast cross each county's heavy-rain or heat threshold?"""
from __future__ import annotations

import pandas as pd

HEAT_WATCH_DAYS = 3
HEAT_WARNING_DAYS = 5


def assess(fc: pd.DataFrame, thr: dict) -> dict:
    """Compare a 7-day forecast with the county's 1991-2020 thresholds.

    Heavy rain: any forecast 3-day total above the 99th-percentile 3-day total.
    Heat: number of forecast days with maximum temperature above the 95th percentile.
    """
    fc = fc.sort_values("date").reset_index(drop=True)
    rain3 = fc["precipitation_sum"].rolling(3).sum()
    p99 = float(thr["rain_3day_p99_mm"])
    alert_mask = rain3 > p99
    alert_dates = fc.loc[alert_mask, "date"].dt.strftime("%Y-%m-%d").tolist()

    heat_p95 = float(thr["heat_tmax_p95_c"])
    heat_days = int((fc["temperature_2m_max"] > heat_p95).sum())
    heat_level = "Warning" if heat_days >= HEAT_WARNING_DAYS else "Watch" if heat_days >= HEAT_WATCH_DAYS else "None"

    return {
        "county": thr["county"],
        "forecast_start": fc["date"].min().strftime("%Y-%m-%d"),
        "forecast_end": fc["date"].max().strftime("%Y-%m-%d"),
        "max_3day_forecast_mm": round(float(rain3.max()), 1) if rain3.notna().any() else None,
        "threshold_3day_p99_mm": p99,
        "heavy_rain_alert": bool(alert_mask.any()),
        "heavy_rain_level": "Watch" if alert_mask.any() else "None",
        "alert_dates": alert_dates,
        "forecast_total_7day_mm": round(float(fc["precipitation_sum"].sum()), 1),
        "heat_alert_days": heat_days,
        "heat_threshold_p95_c": heat_p95,
        "max_forecast_tmax_c": round(float(fc["temperature_2m_max"].max()), 1),
        "heat_alert": heat_days >= HEAT_WATCH_DAYS,
        "heat_level": heat_level,
        "source": "Open-Meteo 7-day forecast (live) vs NASA POWER 1991-2020 county thresholds",
    }
