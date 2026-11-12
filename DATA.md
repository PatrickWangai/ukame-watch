# Data sources

Every dataset used by Ukame Watch, how we access it, its licence, and what we use it for.
All raw files are downloaded by `python tools/fetch_data.py` into `data/raw/` (not committed to git).

**Access date for all sources: 12 November 2026** (the first day of the hackathon).

| # | Dataset | Provider | Access | Licence | Used for |
|---|---|---|---|---|---|
| 1 | Daily rainfall, max/min temperature and apparent max temperature, 1991-01-01 to ~5 days ago | [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), **ERA5 reanalysis** (ECMWF / Copernicus Climate Change Service), `models=era5` | `archive-api.open-meteo.com/v1/archive`, one point per county | CC BY 4.0 (Open-Meteo data); ERA5 under the Copernicus licence | Climatology, trends, extremes, all hazard indicators, outlook targets |
| 2 | 7-day daily forecast (rainfall, apparent max temperature) | [Open-Meteo Forecast API](https://open-meteo.com/en/docs) (blend of national weather-service models) | `api.open-meteo.com/v1/forecast`, live call, not cached | CC BY 4.0 | Short-range heavy-rain and heat watch |
| 3 | Kenya county boundaries (ADM1), simplified | [geoBoundaries](https://www.geoboundaries.org/) gbOpen KEN ADM1 (source: RCMRD GeoPortal / Africa GeoPortal, 2020) | geoBoundaries API | Public domain | Maps, county representative points, population zonal sums |
| 4 | Population count 2020, 1 km | [WorldPop](https://www.worldpop.org/) Global 2000-2020 1 km unconstrained, `ken_ppp_2020_1km_Aggregated.tif` (people per pixel) | `data.worldpop.org` | CC BY 4.0 | Population exposure per county |
| 5 | Oceanic Niño Index (ENSO), monthly 3-month running mean, 1950-present | [NOAA Climate Prediction Center](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php) | `cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` | US Government work, public domain | Seasonal outlook predictor |
| 6 | Dipole Mode Index (Indian Ocean Dipole), monthly, ERSST, 1991-2020 base, 1950-present | [NOAA CPC Indian Ocean monitoring](https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/indian/IODMI/) | `mnth.ersstv5.clim19912020.dmi_current.txt` | US Government work, public domain | Seasonal outlook predictor |
| 7 | Documented drought and flood events | Climate.gov, World Weather Attribution, ACAPS, UN OCHA / ReliefWeb, Wainwright et al. (2020) | See `data/reference/documented_events.csv` (one URL per event) | Cited, not redistributed | Validating the hazard indicators |
| 8 | Action playbook sources | NDMA, Kenya Red Cross / IFRC early action protocols, ACAPS, UN OCHA, WHO, Kenya Meteorological Department | See `data/reference/playbook.json` | Cited, not redistributed | Playbook actions |

## Important caveats

- **Rainfall and temperature are model-based, not station measurements.** ERA5 is a reanalysis: a weather
  model constrained by observations. It is about 0.25° (~28 km) resolution. Reanalysis rainfall in East Africa
  has known biases, especially for convective storms. We use it because it is complete, consistent from
  1991 to today, and free. See `docs/limitations.md`.
- **One grid point per county.** Each county is represented by the ERA5 cell at its interior centroid
  (computed in an equal-area projection). Counties like Turkana (~68,000 km²) contain very different climates;
  a single point cannot represent all of them.
- **Why we pin `models=era5`.** Open-Meteo's default blends a higher-resolution model from 2017 onward, which
  would create an artificial break in the record right at the start of our test period.
- **WorldPop 2020** is a modelled population estimate, not a census count.
- **No personal data** is used anywhere. All data is public and aggregated.

## Rate limits and quirks

- Open-Meteo's free tier allows 10,000 API calls per day for non-commercial use; a 35-year request counts as
  several calls. Eight counties is well within the limit. The fetcher waits 1 s between counties and backs off on HTTP 429.
- NOAA PSL's long DMI file (`dmi.had.long.data`) lagged by five months when we checked (last value May 2026), so we use the
  CPC ERSST DMI file instead, which was current to October 2026.
- ERA5 on Open-Meteo lags real time by about 5 days, so "current status" uses data up to that date.
