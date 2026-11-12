"""Tests for the agent's tools, using a small in-memory store (no network, no files)."""
import pandas as pd
import pytest

from ukame import agent_tools as T


@pytest.fixture
def store():
    s = T.Store.__new__(T.Store)  # bypass file loading
    s.tables = {
        "three_month": pd.DataFrame([
            {"county": "Wajir", "year": 2026, "month": 7, "window": "MJJ 2026", "rain_3m_mm": 30.0,
             "normal_3m_mm": 60.0, "pct_normal": 50.0, "drought_class": "Moderate", "complete_3m": True},
            {"county": "Wajir", "year": 2026, "month": 10, "window": "ASO 2026", "rain_3m_mm": 20.0,
             "normal_3m_mm": 50.0, "pct_normal": 40.0, "drought_class": "Severe", "complete_3m": True},
            {"county": "Kitui", "year": 2026, "month": 10, "window": "ASO 2026", "rain_3m_mm": 90.0,
             "normal_3m_mm": 100.0, "pct_normal": 90.0, "drought_class": "None", "complete_3m": True},
        ]),
        "population": pd.DataFrame([
            {"county": "Wajir", "population": 800000, "census_2019": 800000, "worldpop_2020": 1700000, "area_km2": 56000.0, "density_per_km2": 14.3, "worldpop_to_census_ratio": 2.12},
            {"county": "Kitui", "population": 1100000, "census_2019": 1100000, "worldpop_2020": 1270000, "area_km2": 30000.0, "density_per_km2": 36.7, "worldpop_to_census_ratio": 1.15},
        ]),
        "outlook_current": pd.DataFrame([
            {"county": "Wajir", "issue": "2026-10", "target_window": "NDJ 2027", "season_group": "short_rains",
             "p_dry_model": 0.12, "p_dry_climatology": 0.34, "p_dry_persistence": 0.4, "note": ""},
        ]),
        "outlook_skill": pd.DataFrame([
            {"scope": "county_season", "name": "Wajir | short_rains", "method": "model", "bss": 0.21, "f1": 0.6,
             "n": 30},
            {"scope": "county_season", "name": "Wajir | short_rains", "method": "persistence", "bss": -0.1,
             "f1": 0.3, "n": 30},
        ]),
    }
    s.playbook = {"sources": {"S1": {"title": "Source one", "url": "https://example.org/1"}},
                  "hazards": {"drought": {"Alarm": {"trigger": "t", "actions": [
                      {"sector": "Water", "action": "Fix boreholes", "sources": ["S1"]}]}}}}
    s.data_through = "2026-11-06"
    s.forecast_fn = None
    return s


def test_unknown_county_returns_error_listing_covered_counties(store):
    out = T.get_current_status(store, "Atlantis")
    assert "error" in out
    assert "Wajir" in out["available_counties"]


def test_current_status_reports_latest_window_with_level(store):
    out = T.get_current_status(store, "wajir")
    assert out["county"] == "Wajir"
    assert out["window"] == "ASO 2026"
    assert out["pct_of_normal"] == 40.0
    assert out["drought_level"] == "Alarm"   # below 50% of normal
    assert "NASA POWER" in out["source"]


def test_current_status_alert_vs_none(store):
    assert T.get_current_status(store, "Kitui")["drought_level"] == "None"


def test_outlook_includes_skill_and_baselines(store):
    out = T.get_seasonal_outlook(store, "Wajir")
    assert out["p_dry_model"] == 0.12
    assert out["p_dry_climatology"] == 0.34
    assert out["test_skill"]["model_bss"] == 0.21
    assert out["test_skill"]["persistence_bss"] == -0.1


def test_population_exposure_for_one_county(store):
    out = T.get_population_exposure(store, "Kitui")
    assert out["population"] == 1100000
    assert out["worldpop_2020_estimate"] == 1270000


def test_population_exposure_by_drought_class_across_counties(store):
    out = T.get_population_exposure(store, None)
    assert out["by_drought_class"]["Severe"] == 800000
    assert out["by_drought_class"]["None"] == 1100000


def test_playbook_returns_actions_with_resolved_citations(store):
    out = T.lookup_playbook(store, "drought", "Alarm")
    assert out["actions"][0]["action"] == "Fix boreholes"
    assert out["actions"][0]["citations"][0]["url"] == "https://example.org/1"


def test_playbook_unknown_level_is_an_error(store):
    assert "error" in T.lookup_playbook(store, "drought", "Panic")


def test_dispatch_routes_by_name_and_rejects_unknown_tools(store):
    assert T.dispatch(store, "get_population_exposure", {"county": "Wajir"})["population"] == 800000
    assert "error" in T.dispatch(store, "rm_rf", {})
