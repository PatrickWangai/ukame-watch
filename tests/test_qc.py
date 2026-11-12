"""Rainfall quality control: spurious single-day spikes in NASA POWER are checked against ERA5."""
import pandas as pd

from ukame import analysis as A


def daily(rows):
    return pd.DataFrame([{"county": c, "date": pd.Timestamp(d), "precipitation_sum": r,
                          "temperature_2m_max": 33.0, "temperature_2m_min": 20.0} for c, d, r in rows])


def test_spike_that_era5_does_not_see_is_replaced_and_logged():
    d = daily([("Wajir", "2021-11-27", 485.95), ("Wajir", "2021-11-26", 2.0)])
    era5 = pd.DataFrame([{"county": "Wajir", "date": pd.Timestamp("2021-11-27"), "era5_mm": 14.4}])
    clean, flags = A.qc_rainfall(d, era5)
    assert clean.loc[clean["date"] == "2021-11-27", "precipitation_sum"].item() == 14.4
    assert flags.iloc[0]["action"] == "replaced with ERA5"
    assert flags.iloc[0]["original_mm"] == 485.95


def test_heavy_day_that_era5_partly_confirms_is_kept():
    d = daily([("Isiolo", "2023-11-03", 131.2)])
    era5 = pd.DataFrame([{"county": "Isiolo", "date": pd.Timestamp("2023-11-03"), "era5_mm": 26.3}])
    clean, flags = A.qc_rainfall(d, era5)
    assert clean["precipitation_sum"].item() == 131.2
    assert flags.iloc[0]["action"] == "kept (ERA5 confirms rain)"


def test_extreme_day_without_era5_check_is_set_missing():
    d = daily([("Garissa", "2010-05-01", 350.0)])
    clean, flags = A.qc_rainfall(d, pd.DataFrame(columns=["county", "date", "era5_mm"]))
    assert pd.isna(clean["precipitation_sum"].item())
    assert flags.iloc[0]["action"] == "set missing (implausible, no ERA5 check)"


def test_ordinary_days_are_untouched():
    d = daily([("Kitui", "2015-04-01", 40.0)])
    clean, flags = A.qc_rainfall(d, pd.DataFrame(columns=["county", "date", "era5_mm"]))
    assert clean["precipitation_sum"].item() == 40.0
    assert flags.empty
