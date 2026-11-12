# Data sources

Every dataset Ukame Watch uses, how we access it, its licence and what we use it for. Raw files are
downloaded by `python tools/build_all.py` into `data/raw/` (not committed). **Access date for all sources:
12 November 2026.**

| # | Dataset | Provider and access | Licence | Used for |
|---|---|---|---|---|
| 1 | Daily rainfall (`PRECTOTCORR`, bias-corrected), max/min temperature, humidity, 1991-01-01 to 2026-11-09, one point per county | [NASA POWER](https://power.larc.nasa.gov/) daily point API (MERRA-2 reanalysis), `power.larc.nasa.gov/api/temporal/daily/point` | Free and open; acknowledgement requested: *"These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded through the NASA Earth Science/Applied Science Program."* | Climatology, trends, extremes, all hazard indicators, outlook targets |
| 2 | Daily rainfall, ERA5 reanalysis | [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), `models=era5` (full 1991-2026 record for Turkana and Marsabit; single days for QC) | Open-Meteo data CC BY 4.0; ERA5 under the Copernicus licence | Independent cross-check; quality control of suspicious days |
| 3 | 7-day daily forecast (rainfall, max temperature) | [Open-Meteo Forecast API](https://open-meteo.com/en/docs), live, not cached | CC BY 4.0 | 7-day heavy-rain and heat watch |
| 4 | Kenya county boundaries (ADM1), simplified | [geoBoundaries](https://www.geoboundaries.org/) gbOpen KEN ADM1 (source: RCMRD GeoPortal / Africa GeoPortal, 2020) | Public domain | Map, county representative points, population sums |
| 5 | County population, 2019 census | KNBS *2019 Kenya Population and Housing Census, Volume I* (figures in `data/reference/census_2019.csv`) | Official statistics, cited | Population exposure (primary) |
| 6 | Population count 2020, 1 km | [WorldPop](https://www.worldpop.org/) Global 2000-2020 unconstrained, `ken_ppp_2020_1km_Aggregated.tif` | CC BY 4.0 | Comparison with the census only |
| 7 | Oceanic Niño Index (ENSO), 1950-present | [NOAA Climate Prediction Center](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php), `oni.ascii.txt` | US Government work, public domain | Outlook predictor |
| 8 | Dipole Mode Index (Indian Ocean Dipole), ERSST, 1991-2020 base, 1950-present | [NOAA CPC Indian Ocean monitoring](https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/indian/IODMI/) | US Government work, public domain | Outlook predictor |
| 9 | Documented drought and flood events | Climate.gov, World Weather Attribution, ACAPS, UN OCHA / ReliefWeb, FAO GIEWS, IFRC, Wainwright et al. 2020 (one URL per event in `data/reference/documented_events.csv`) | Cited, not redistributed | Validating the indicators |
| 10 | Playbook sources | NDMA, Kenya Red Cross / IFRC early action protocols, ACAPS, UN OCHA, WHO, KMD (`data/reference/playbook.json`) | Cited, not redistributed | Playbook actions |

## Data quality: what we found and what we did

| Issue | Evidence | Action |
|---|---|---|
| **Spurious one-day rainfall spikes in NASA POWER** | 12 days above 100 mm; e.g. Turkana 31 Dec 2020: NASA POWER 608.5 mm, ERA5 1.0 mm. Spikes cluster on the same dates across counties (processing artifacts, not storms) | 11 days where ERA5 shows less than 10% of the value were replaced with the ERA5 value; Isiolo 3 Nov 2023 (131 mm, ERA5 26 mm, during documented floods) kept. Log: `data/processed/qc_rainfall_flags.csv` |
| **Reanalyses disagree on rainfall amounts** | NASA POWER vs ERA5: monthly correlation 0.72 (Marsabit) and 0.70 (Turkana), daily ~0.34; Marsabit annual mean 330 mm vs 132 mm | All indicators use % of normal within one dataset, never absolute amounts. `data/processed/crosscheck_era5.csv` |
| **WorldPop far above the census in the north-east** | WorldPop 2020 / census 2019: Mandera 3.07×, Wajir 2.23×, Garissa 1.94× | Census used for exposure; ratio shown in the app |
| **A public table with a wrong census figure** | Wikipedia "Counties of Kenya" lists Turkana as 1,504,976; KNBS-based sources give 926,976 | KNBS figure used; noted in `census_2019.csv` |
| **Completeness** | `data/processed/quality_report.csv`: no missing dates, negative rainfall, Tmin > Tmax or duplicate dates in 8 × 13,097 days | None needed |

## Why these sources

- **NASA POWER instead of Open-Meteo ERA5 for the history.** We started with ERA5, but Open-Meteo's archive API
  rate-limited us after two counties (each 35-year request counts as hundreds of API calls). Using one source for
  every county keeps comparisons fair, so we switched all eight counties to NASA POWER and kept the two ERA5
  counties as a cross-check. NASA POWER was also more current (data to 9 Nov 2026).
- **CPC instead of NOAA PSL for the Indian Ocean Dipole.** The PSL long DMI file stopped at May 2026; the CPC file
  runs to October 2026.
- **Model-based, not station data.** Reanalysis is a weather model constrained by observations. It is complete and
  consistent from 1991, but it is not a rain gauge. See `docs/limitations.md`.

No personal data is used anywhere.
