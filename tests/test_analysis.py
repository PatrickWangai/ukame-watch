"""Tests for the weather-behaviour analysis and hazard indicators (synthetic data, no network)."""
import numpy as np
import pandas as pd
import pytest

from ukame import analysis as A
from ukame import config as C


def synthetic_daily(county="Testland", start="1991-01-01", end="2023-12-31", rain=2.0, tmax=35.0):
    dates = pd.date_range(start, end, freq="D")
    return pd.DataFrame({
        "county": county, "date": dates,
        "precipitation_sum": rain, "temperature_2m_max": tmax,
        "temperature_2m_min": 20.0,
    })


def test_window_label_names_the_three_months_ending_at_end_month():
    assert A.window_label(12, 2023) == "OND 2023"
    assert A.window_label(5, 2024) == "MAM 2024"
    assert A.window_label(2, 2011) == "DJF 2011"


@pytest.mark.parametrize("pct,expected", [
    (40, "Severe"), (60, "Moderate"), (85, "Mild"), (120, "None"), (np.nan, "Dry season (not assessed)"),
])
def test_drought_class_bands(pct, expected):
    assert A.drought_class(pct) == expected


def test_longest_run_counts_consecutive_true_values():
    assert A.longest_run(np.array([True, True, False, True, True, True, False])) == 3
    assert A.longest_run(np.array([False, False])) == 0


def test_three_month_pct_normal_is_100_when_every_year_is_identical():
    mon = A.monthly(synthetic_daily(rain=2.0))  # ~60 mm/month, identical every year
    tm = A.three_month(mon)
    assessed = tm["pct_normal"].dropna()
    assert len(assessed) > 0
    assert assessed.round(6).between(99, 101).all()


def test_three_month_half_rain_in_one_year_gives_about_50_pct():
    daily = synthetic_daily(rain=2.0)
    dry = daily["date"].dt.year == 2022
    daily.loc[dry, "precipitation_sum"] = 1.0
    tm = A.three_month(A.monthly(daily))
    row = tm[(tm["year"] == 2022) & (tm["month"] == 12)].iloc[0]
    assert row["pct_normal"] == pytest.approx(50, abs=1)
    assert row["drought_class"] == "Moderate"


def test_three_month_dry_season_is_not_assessed():
    """Arid counties have near-zero normals in dry months; % of normal would be meaningless."""
    mon = A.monthly(synthetic_daily(rain=0.1))  # ~9 mm per 3 months < MIN_NORMAL_3M_MM
    tm = A.three_month(mon)
    assert tm["pct_normal"].isna().all()
    assert (tm["drought_class"] == "Dry season (not assessed)").all()


def test_thresholds_use_normal_period_only():
    daily = synthetic_daily(tmax=35.0)
    # A huge heat spike after the normal period must NOT move the threshold.
    daily.loc[daily["date"].dt.year > C.NORMAL_END, "temperature_2m_max"] = 50.0
    thr = A.thresholds(daily)
    assert thr.loc[0, "heat_tmax_p95_c"] == pytest.approx(35.0)


def test_heavy_rain_flag_fires_on_extreme_three_day_total():
    daily = synthetic_daily(rain=1.0)
    daily.loc[daily["date"] == "2023-04-10", "precipitation_sum"] = 200.0
    thr = A.thresholds(daily)
    d = A.daily_indicators(daily, thr)
    flagged = d.loc[d["heavy_rain_flag"], "date"].dt.strftime("%Y-%m-%d").tolist()
    assert "2023-04-10" in flagged
    assert len(flagged) == 3  # the 3 rolling windows containing the spike


def test_quality_report_counts_missing_dates_and_bad_values():
    daily = synthetic_daily(start="2020-01-01", end="2020-01-10")
    daily = daily.drop(index=4)
    daily.loc[0, "precipitation_sum"] = -1.0
    q = A.quality_report(daily).iloc[0]
    assert q["missing_dates"] == 1
    assert q["negative_rain"] == 1
