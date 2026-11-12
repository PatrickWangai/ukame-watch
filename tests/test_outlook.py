"""Tests for the seasonal outlook: leakage-free features, training-only thresholds, honest metrics."""
import numpy as np
import pandas as pd
import pytest

from ukame import outlook as O


def monthly_rain(county="Testland", years=range(1991, 2026), rain=None):
    rows = []
    for y in years:
        for m in range(1, 13):
            r = rain(y, m) if rain else 50.0
            rows.append({"county": county, "year": y, "month": m, "rain_mm": r, "complete": True})
    return pd.DataFrame(rows)


def indices(years=range(1990, 2027)):
    rows = [{"year": y, "month": m, "oni": y + m / 100, "dmi": -(y + m / 100)} for y in years for m in range(1, 13)]
    return pd.DataFrame(rows)


def test_target_is_sum_of_the_next_three_months():
    mon = monthly_rain(rain=lambda y, m: float(m))  # rain equals month number
    ds = O.build_dataset(mon, indices())
    row = ds[(ds["issue_year"] == 2000) & (ds["issue_month"] == 9)].iloc[0]
    assert row["target_rain_mm"] == 10 + 11 + 12  # Oct + Nov + Dec
    assert row["target_end_month"] == 12


def test_target_wraps_across_the_year_end():
    mon = monthly_rain(rain=lambda y, m: float(m))
    ds = O.build_dataset(mon, indices())
    row = ds[(ds["issue_year"] == 2000) & (ds["issue_month"] == 11)].iloc[0]
    assert row["target_rain_mm"] == 12 + 1 + 2  # Dec 2000 + Jan + Feb 2001
    assert row["target_end_month"] == 2 and row["target_year"] == 2001


def test_features_only_use_information_available_at_issue_time():
    mon = monthly_rain()
    ds = O.build_dataset(mon, indices())
    row = ds[(ds["issue_year"] == 2000) & (ds["issue_month"] == 9)].iloc[0]
    # DMI for the issue month itself; ONI for the 3-month season centred on the previous month.
    assert row["dmi"] == pytest.approx(-(2000 + 9 / 100))
    assert row["oni"] == pytest.approx(2000 + 8 / 100)


def test_dry_threshold_uses_training_years_only():
    # Test-period years are extremely dry; if they leaked into the tercile, the threshold would drop.
    mon = monthly_rain(rain=lambda y, m: 1.0 if y >= 2017 else 50.0 + (y % 3) * 20)
    ds = O.add_targets(O.build_dataset(mon, indices()), test_start_year=2017)
    train = ds[ds["target_year"] < 2017]
    thr = ds["dry_threshold_mm"].iloc[0]
    assert thr == pytest.approx(train.loc[train["target_end_month"] == ds["target_end_month"].iloc[0],
                                          "target_rain_mm"].quantile(1 / 3))
    assert thr > 3 * 1.0  # far above the all-dry test-period totals
    assert ds.loc[ds["target_year"] >= 2017, "dry"].all()


def test_metrics_on_a_known_case():
    y = np.array([1, 1, 0, 0])
    p = np.array([0.9, 0.2, 0.6, 0.1])
    m = O.metrics(y, p, threshold=0.5, clim_prob=0.5)
    assert m["precision"] == pytest.approx(0.5)   # 1 TP, 1 FP
    assert m["recall"] == pytest.approx(0.5)      # 1 TP, 1 FN
    assert m["f1"] == pytest.approx(0.5)
    assert m["brier"] == pytest.approx(((0.1**2) + (0.8**2) + (0.6**2) + (0.1**2)) / 4)
    assert m["bss"] == pytest.approx(1 - m["brier"] / 0.25)


def test_climatology_forecast_has_zero_skill_by_definition():
    y = np.array([1, 0, 0, 1, 0, 0])
    p = np.full(6, 1 / 3)
    assert O.metrics(y, p, threshold=1 / 3, clim_prob=1 / 3)["bss"] == pytest.approx(0)


def test_metrics_report_zero_not_nan_when_no_warnings_issued():
    y = np.array([1, 0, 0])
    m = O.metrics(y, np.zeros(3), threshold=0.5, clim_prob=1 / 3)
    assert m["precision"] == 0 and m["recall"] == 0 and m["f1"] == 0


def test_season_group_assignment():
    assert O.season_group(12) == "short_rains"   # OND
    assert O.season_group(5) == "long_rains"     # MAM
    assert O.season_group(8) == "other"


def test_target_label_spells_out_months_and_years():
    assert O.target_label(issue_year=2026, issue_month=10) == "Nov 2026 - Jan 2027"
    assert O.target_label(issue_year=2026, issue_month=2) == "Mar - May 2026"


def test_display_probability_floors_and_caps_extremes():
    assert O.display_probability(0.013) == "under 5%"
    assert O.display_probability(0.97) == "over 95%"
    assert O.display_probability(0.334) == "33%"


def test_climatology_baseline_never_warns_despite_floating_point_means():
    clim = 0.35064935064935066  # mean of many copies of this can round to slightly less than itself
    n = 224
    pred = pd.DataFrame({"split": "test", "dry": pd.array([True, False] * (n // 2), dtype="boolean"),
                         "season_group": "short_rains", "county": "X",
                         "p_model": 0.5, "p_clim": clim, "p_persistence": 0.3})
    ev = O.evaluate(pred)
    row = ev[(ev["scope"] == "all") & (ev["method"] == "climatology")].iloc[0]
    assert row["recall"] == 0.0
