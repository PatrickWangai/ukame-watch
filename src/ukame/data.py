"""Download and load all raw data. Every fetch caches to data/raw/ so reruns are offline-safe.

Sources and licences are listed in DATA.md.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from . import config as C

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "ukame-watch/0.1 (hackathon research prototype)"


def _get(url: str, params: dict | None = None, retries: int = 5, timeout: int = 120) -> requests.Response:
    """GET with exponential backoff: venue Wi-Fi is slow and APIs rate-limit."""
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            if r.status_code == 429:  # rate limited
                time.sleep(30 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 3)
    raise RuntimeError(f"Failed to fetch {url}")


# ---------------------------------------------------------------- boundaries
def fetch_boundaries(force: bool = False) -> gpd.GeoDataFrame:
    """Kenya county (ADM1) polygons from geoBoundaries (public domain)."""
    path = C.RAW / "ken_adm1.geojson"
    if force or not path.exists():
        meta = _get(C.GEOBOUNDARIES_API).json()
        path.write_bytes(_get(meta["simplifiedGeometryGeoJSON"]).content)
    return gpd.read_file(path)


def study_counties() -> gpd.GeoDataFrame:
    """The 8 study counties, with an interior representative point computed in an equal-area projection."""
    gdf = fetch_boundaries()
    gdf = gdf[gdf["shapeName"].isin(C.COUNTIES)][["shapeName", "shapeISO", "geometry"]]
    gdf = gdf.rename(columns={"shapeName": "county", "shapeISO": "iso"}).reset_index(drop=True)
    missing = set(C.COUNTIES) - set(gdf["county"])
    if missing:
        raise ValueError(f"Counties not found in boundary file: {missing}")
    projected = gdf.to_crs(C.EQUAL_AREA_CRS)
    centroids = projected.geometry.centroid
    # Use the centroid when it falls inside the county, otherwise a guaranteed-interior point.
    points = [c if poly.contains(c) else poly.representative_point()
              for c, poly in zip(centroids, projected.geometry)]
    pts = gpd.GeoSeries(points, crs=C.EQUAL_AREA_CRS).to_crs("EPSG:4326")
    gdf["lat"] = pts.y.round(4)
    gdf["lon"] = pts.x.round(4)
    gdf["area_km2"] = (projected.geometry.area / 1e6).round(0)
    return gdf


# ---------------------------------------------------------------- daily weather
def fetch_weather(county: str, lat: float, lon: float, force: bool = False) -> pd.DataFrame:
    """Daily NASA POWER data (MERRA-2 reanalysis; PRECTOTCORR is bias-corrected rainfall), 1991 to ~3 days ago.

    One source for every county keeps comparisons fair. NASA POWER marks missing days with -999;
    we convert those to NaN and drop trailing days that are not yet available.
    """
    path = C.RAW / f"weather_{county.lower()}.csv"
    if path.exists() and not force:
        return pd.read_csv(path, parse_dates=["date"])
    end = date.today() - timedelta(days=1)
    params = {
        "parameters": ",".join(C.POWER_VARS), "community": "AG",
        "latitude": lat, "longitude": lon,
        "start": C.HISTORY_START.replace("-", ""), "end": end.strftime("%Y%m%d"), "format": "JSON",
    }
    js = _get(C.NASA_POWER_DAILY, params=params, timeout=300).json()
    params_data = js["properties"]["parameter"]
    df = pd.DataFrame({C.POWER_VARS[k]: pd.Series(v) for k, v in params_data.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(-999.0, np.nan).rename_axis("date").reset_index()
    last_valid = df.dropna(subset=["precipitation_sum", "temperature_2m_max"])["date"].max()
    df = df[df["date"] <= last_valid]
    df.insert(0, "county", county)
    df.to_csv(path, index=False)
    return df


def era5_for_days(candidates: pd.DataFrame, counties: pd.DataFrame) -> pd.DataFrame:
    """ERA5 daily rainfall for specific (county, date) pairs, used to check suspicious NASA POWER spikes.

    Looks first in the full ERA5 files we already have, then in a cache, then asks Open-Meteo for just
    those days (tiny requests). Results are cached in data/raw/qc_era5_checks.csv so rebuilds are offline-safe.
    """
    cols = ["county", "date", "era5_mm"]
    cache_path = C.REFERENCE / "qc_era5_checks.csv"  # committed, so a fresh clone reproduces QC offline
    frames = [pd.DataFrame(columns=cols)]
    full = load_era5_crosscheck()
    if len(full):
        frames.append(full.rename(columns={"precipitation_sum": "era5_mm"})[cols])
    if cache_path.exists():
        frames.append(pd.read_csv(cache_path, parse_dates=["date"])[cols])
    have = pd.concat(frames, ignore_index=True)
    have["date"] = pd.to_datetime(have["date"])
    have = have.drop_duplicates(["county", "date"])
    keys = set(zip(have["county"], have["date"]))
    pos = counties.set_index("county")
    new_rows = []
    for c, dt in zip(candidates["county"], candidates["date"]):
        if (c, dt) in keys:
            continue
        try:
            js = _get(C.OPEN_METEO_ARCHIVE, retries=2, timeout=60, params={
                "latitude": pos.loc[c, "lat"], "longitude": pos.loc[c, "lon"], "models": "era5",
                "start_date": dt.date().isoformat(), "end_date": dt.date().isoformat(),
                "daily": "precipitation_sum", "timezone": C.TIMEZONE}).json()
            new_rows.append({"county": c, "date": dt, "era5_mm": js["daily"]["precipitation_sum"][0]})
        except Exception:
            continue  # no check possible: qc_rainfall falls back to the plausibility limit
        time.sleep(0.5)
    if new_rows:
        have = pd.concat([have, pd.DataFrame(new_rows, columns=cols)], ignore_index=True)
    want = candidates[["county", "date"]].merge(have[cols], on=["county", "date"], how="inner")
    if len(want):  # keep every value used for QC in the committed cache
        old = pd.read_csv(cache_path, parse_dates=["date"]) if cache_path.exists() else pd.DataFrame(columns=cols)
        pd.concat([old, want], ignore_index=True).drop_duplicates(["county", "date"]).sort_values(
            ["county", "date"]).to_csv(cache_path, index=False)
    return want.reset_index(drop=True)


def load_era5_crosscheck() -> pd.DataFrame:
    """ERA5 (Open-Meteo) daily rainfall for the counties downloaded before the archive API rate-limited us.

    Used only to cross-check NASA POWER rainfall against a second, independent reanalysis.
    """
    frames = []
    for path in sorted(C.RAW.glob("era5_*.csv")):
        frames.append(pd.read_csv(path, parse_dates=["date"])[["county", "date", "precipitation_sum"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_weather() -> pd.DataFrame:
    """All counties' daily weather in one long table."""
    frames = [pd.read_csv(C.RAW / f"weather_{c.lower()}.csv", parse_dates=["date"]) for c in C.COUNTIES]
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------- climate indices
_ONI_SEASON_TO_MONTH = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
                        "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}


def fetch_oni(force: bool = False) -> pd.DataFrame:
    """NOAA CPC Oceanic Nino Index (ENSO). Each 3-month season is assigned to its centre month."""
    path = C.RAW / "oni.txt"
    if force or not path.exists():
        path.write_text(_get(C.ONI_URL).text)
    df = pd.read_csv(path, sep=r"\s+")
    df["month"] = df["SEAS"].map(_ONI_SEASON_TO_MONTH)
    df = df.rename(columns={"YR": "year", "ANOM": "oni"})[["year", "month", "oni"]]
    return df.dropna().astype({"year": int, "month": int})


def fetch_dmi(force: bool = False) -> pd.DataFrame:
    """NOAA CPC Dipole Mode Index (Indian Ocean Dipole), ERSST, 1991-2020 climatology."""
    path = C.RAW / "dmi.txt"
    if force or not path.exists():
        path.write_text(_get(C.DMI_URL).text)
    rows = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
            year, month, _, _, dmi = parts
            rows.append((int(year), int(month), float(dmi)))
    df = pd.DataFrame(rows, columns=["year", "month", "dmi"])
    return df[df["dmi"] > -99]


def load_indices() -> pd.DataFrame:
    """Monthly ONI and DMI merged on (year, month)."""
    return fetch_oni().merge(fetch_dmi(), on=["year", "month"], how="outer").sort_values(["year", "month"])


# ---------------------------------------------------------------- population
def fetch_population(force: bool = False) -> pd.DataFrame:
    """Population per county: official KNBS 2019 census totals, with WorldPop 2020 raster sums for comparison.

    WorldPop's unconstrained 2020 estimate is up to ~3x the 2019 census in the north-east (Mandera, Wajir,
    Garissa), so we use the census for exposure numbers and keep WorldPop only to show the discrepancy.
    """
    from rasterstats import zonal_stats

    tif = C.RAW / "ken_ppp_2020_1km.tif"
    if force or not tif.exists():
        tif.write_bytes(_get(C.WORLDPOP_URL, timeout=600).content)
    counties = study_counties()
    stats = zonal_stats(counties.to_crs("EPSG:4326"), str(tif), stats=["sum"], nodata=-99999)
    wp = counties[["county", "area_km2"]].copy()
    wp["worldpop_2020"] = [int(round(s["sum"] or 0)) for s in stats]
    census = pd.read_csv(C.REFERENCE / "census_2019.csv")[["county", "census_2019"]]
    return combine_population(wp, census)


def combine_population(worldpop: pd.DataFrame, census: pd.DataFrame) -> pd.DataFrame:
    out = worldpop.merge(census, on="county", how="left")
    missing = out.loc[out["census_2019"].isna(), "county"].tolist()
    if missing:
        raise ValueError(f"No census figure for: {missing}")
    out["census_2019"] = out["census_2019"].astype(int)
    out["population"] = out["census_2019"]
    out["population_source"] = "KNBS 2019 census"
    out["worldpop_to_census_ratio"] = (out["worldpop_2020"] / out["census_2019"]).round(2)
    out["density_per_km2"] = (out["population"] / out["area_km2"]).round(1)
    return out


# ---------------------------------------------------------------- 7-day forecast
def fetch_forecast(lat: float, lon: float, days: int = 7) -> pd.DataFrame:
    """Live 7-day daily forecast from Open-Meteo (not cached: always current)."""
    params = {"latitude": lat, "longitude": lon, "forecast_days": days, "timezone": C.TIMEZONE,
              "daily": "precipitation_sum,temperature_2m_max"}
    js = _get(C.OPEN_METEO_FORECAST, params=params, timeout=60).json()
    df = pd.DataFrame(js["daily"]).rename(columns={"time": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df


def write_json(obj, name: str) -> None:
    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (pd.Timestamp, date)):
            return o.isoformat()
        raise TypeError(type(o))
    (C.PROCESSED / name).write_text(json.dumps(obj, indent=2, default=default))
