"""Tests for the 7-day heavy-rain / heat watch (no network: forecasts are synthetic)."""
import pandas as pd

from ukame import watch as W

THR = {"county": "Wajir", "rain_3day_p99_mm": 60.0, "heat_tmax_p95_c": 40.0}


def forecast(rain, heat=35.0):
    dates = pd.date_range("2026-11-13", periods=len(rain), freq="D")
    return pd.DataFrame({"date": dates, "precipitation_sum": rain, "temperature_2m_max": heat})


def test_no_alert_in_ordinary_week():
    out = W.assess(forecast([5, 0, 3, 0, 0, 2, 1]), THR)
    assert out["heavy_rain_alert"] is False
    assert out["alert_dates"] == []
    assert out["max_3day_forecast_mm"] == 8.0


def test_alert_when_forecast_three_day_total_exceeds_p99():
    out = W.assess(forecast([0, 30, 25, 20, 0, 0, 0]), THR)
    assert out["heavy_rain_alert"] is True
    assert out["max_3day_forecast_mm"] == 75.0
    assert "2026-11-16" in out["alert_dates"]  # 3-day window ending on day 4 (30+25+20)


def test_heat_days_counted_against_county_threshold():
    out = W.assess(forecast([0] * 7, heat=[39, 41, 42, 38, 40, 40.5, 30]), THR)
    assert out["heat_alert_days"] == 3   # strictly above 40.0
    assert out["heat_alert"] is True


def test_output_carries_threshold_and_source_for_citation():
    out = W.assess(forecast([0] * 7), THR)
    assert out["threshold_3day_p99_mm"] == 60.0
    assert "Open-Meteo" in out["source"]
