"""Population: official census totals are used for exposure; WorldPop is kept for comparison."""
import pandas as pd
import pytest

from ukame import data as D


def test_combine_population_prefers_census_and_reports_worldpop_ratio():
    wp = pd.DataFrame({"county": ["Mandera", "Kitui"], "area_km2": [26000.0, 30000.0],
                       "worldpop_2020": [2_600_000, 1_200_000]})
    census = pd.DataFrame({"county": ["Mandera", "Kitui"], "census_2019": [867_457, 1_136_187]})
    out = D.combine_population(wp, census).set_index("county")
    assert out.loc["Mandera", "population"] == 867_457
    assert out.loc["Mandera", "worldpop_to_census_ratio"] == pytest.approx(3.0, abs=0.01)
    assert out.loc["Kitui", "density_per_km2"] == pytest.approx(37.9, abs=0.1)


def test_combine_population_fails_loudly_if_a_county_lacks_census_data():
    wp = pd.DataFrame({"county": ["Wajir"], "area_km2": [1.0], "worldpop_2020": [1]})
    with pytest.raises(ValueError):
        D.combine_population(wp, pd.DataFrame({"county": [], "census_2019": []}))


def test_era5_for_days_handles_fresh_clone_with_no_era5_files(tmp_path, monkeypatch):
    from ukame import config as C
    monkeypatch.setattr(C, "RAW", tmp_path)
    monkeypatch.setattr(C, "REFERENCE", tmp_path)
    monkeypatch.setattr(D, "_get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline")))
    cands = pd.DataFrame({"county": ["Wajir"], "date": [pd.Timestamp("2021-11-27")]})
    out = D.era5_for_days(cands, pd.DataFrame({"county": ["Wajir"], "lat": [1.7], "lon": [40.0]}))
    assert list(out.columns) == ["county", "date", "era5_mm"] and out.empty


def test_era5_for_days_finds_values_in_full_era5_files_and_caches_them(tmp_path, monkeypatch):
    from ukame import config as C
    monkeypatch.setattr(C, "RAW", tmp_path)
    monkeypatch.setattr(C, "REFERENCE", tmp_path)
    pd.DataFrame({"county": ["Wajir"], "date": ["2021-11-27"], "precipitation_sum": [14.4]}).to_csv(
        tmp_path / "era5_wajir.csv", index=False)
    cands = pd.DataFrame({"county": ["Wajir"], "date": [pd.Timestamp("2021-11-27")]})
    out = D.era5_for_days(cands, pd.DataFrame({"county": ["Wajir"], "lat": [1.7], "lon": [40.0]}))
    assert out["era5_mm"].tolist() == [14.4]
    assert (tmp_path / "qc_era5_checks.csv").exists()
