"""Tests for indicator validation against documented events."""
import pandas as pd

from ukame import validation as V


def regional(values):
    """Monthly regional series: dict of 'YYYY-MM' -> value."""
    rows = [{"year": int(k[:4]), "month": int(k[5:]), "value": v} for k, v in values.items()]
    return pd.DataFrame(rows)


def test_top_periods_picks_distinct_extremes_separated_by_gap():
    s = regional({"2010-12": 30, "2011-01": 32, "2011-02": 35, "2016-12": 40, "2021-12": 45, "2005-12": 80})
    top = V.top_periods(s, "value", n=3, lowest=True, min_gap_months=12)
    assert [f"{r.year}-{r.month:02d}" for r in top.itertuples()] == ["2010-12", "2016-12", "2021-12"]


def test_top_periods_highest_mode():
    s = regional({"1997-12": 900, "2019-12": 700, "2019-11": 650, "2023-12": 600, "2001-05": 10})
    top = V.top_periods(s, "value", n=3, lowest=False, min_gap_months=6)
    assert [f"{r.year}-{r.month:02d}" for r in top.itertuples()] == ["1997-12", "2019-12", "2023-12"]


def test_documented_drought_is_hit_when_indicator_drops_below_threshold_in_window():
    events = pd.DataFrame([{"event_id": "D1", "hazard": "drought", "label": "x", "start": "2010-10-01",
                            "end": "2011-06-30", "source_url": "u"}])
    pct = regional({"2010-12": 40.0, "2011-05": 70.0, "2012-05": 120.0})
    out = V.check_documented(events, drought_pct=pct, heavy_counts=regional({}), heavy_threshold=5)
    row = out.iloc[0]
    assert bool(row["detected"]) is True
    assert row["indicator_value"] == 40.0


def test_documented_flood_missed_when_too_few_heavy_days():
    events = pd.DataFrame([{"event_id": "F1", "hazard": "heavy_rain", "label": "x", "start": "2024-03-01",
                            "end": "2024-05-31", "source_url": "u"}])
    heavy = regional({"2024-03": 1, "2024-04": 2, "2024-05": 1})
    out = V.check_documented(events, drought_pct=regional({}), heavy_counts=heavy, heavy_threshold=5)
    assert bool(out.iloc[0]["detected"]) is False
    assert out.iloc[0]["indicator_value"] == 4


def test_regional_drought_pct_can_be_limited_to_rainy_season_windows():
    tm = pd.DataFrame([{"county": f"C{i}", "year": 2011, "month": m, "pct_normal": 50.0}
                       for i in range(5) for m in (2, 5, 12)])
    out = V.regional_drought_pct(tm, months=(5, 12))
    assert sorted(out["month"].tolist()) == [5, 12]
