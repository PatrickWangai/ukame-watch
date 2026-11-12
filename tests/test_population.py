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
