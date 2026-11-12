"""Project-wide settings: study area, periods, thresholds, file paths.

Every other module imports from here so that a judge can change one value
(e.g. the normal period) and rebuild everything with `python tools/build_all.py`.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
REFERENCE = ROOT / "data" / "reference"
LOGS = ROOT / "logs"

for _d in (RAW, PROCESSED, LOGS):
    _d.mkdir(parents=True, exist_ok=True)

# Eight arid and semi-arid (ASAL) counties. Names match geoBoundaries KEN ADM1 `shapeName`.
COUNTIES = ["Turkana", "Marsabit", "Wajir", "Mandera", "Garissa", "Isiolo", "Samburu", "Kitui"]

TIMEZONE = "Africa/Nairobi"
HISTORY_START = "1991-01-01"

# WMO standard normal period. Used for climatology and "% of normal".
NORMAL_START, NORMAL_END = 1991, 2020

# Seasonal-outlook evaluation: everything from TEST_START_YEAR onward is held out.
# The challenge requires testing on at least the last 8 years.
TEST_START_YEAR = 2017

# Hazard-indicator settings.
HEAVY_RAIN_WINDOW_DAYS = 3
HEAVY_RAIN_PERCENTILE = 99      # 3-day total vs 99th percentile (training years only)
WET_DAY_MM = 1.0                # a "wet day" has >= 1 mm
HEAVY_DAY_PERCENTILE = 95       # heavy-rain days: wet-day rainfall above the 95th percentile
HEAT_PERCENTILE = 95            # hot days: maximum temperature above the 95th percentile

# Drought indicator: 3-month rainfall as % of the 1991-2020 normal for the same 3 months.
# Classes follow common practice for %-of-normal; documented in docs/limitations.md.
DROUGHT_CLASSES = [  # (upper bound %, label)
    (50, "Severe"),
    (75, "Moderate"),
    (90, "Mild"),
    (float("inf"), "None"),
]

# Data sources (see DATA.md for licences and access dates).
NASA_POWER_DAILY = "https://power.larc.nasa.gov/api/temporal/daily/point"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"  # used only for the ERA5 cross-check
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/KEN/ADM1/"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
DMI_URL = ("https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/"
           "indian/IODMI/mnth.ersstv5.clim19912020.dmi_current.txt")
WORLDPOP_URL = ("https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2020/"
                "KEN/ken_ppp_2020_1km_Aggregated.tif")

# NASA POWER parameter -> our column name
POWER_VARS = {"PRECTOTCORR": "precipitation_sum", "T2M_MAX": "temperature_2m_max", "T2M_MIN": "temperature_2m_min",
              "RH2M": "rh2m_mean"}

# Equal-area projection for areas and centroids (Africa Albers Equal Area Conic).
EQUAL_AREA_CRS = "ESRI:102022"

# Local LLM for the advisory agent (runs through Ollama, no data leaves the machine).
AGENT_MODEL = "qwen2.5:3b"

DISCLAIMER = (
    "Planning-support draft only, not an official warning. Kenya Meteorological Department "
    "warnings and NDMA drought bulletins take priority."
)
