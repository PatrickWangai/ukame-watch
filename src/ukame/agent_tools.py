"""The six tools the advisory agent can call. Each tool returns a JSON-serialisable dict that carries
its own source and date, so every number in an advisory can be traced back to a tool result.

The agent never does arithmetic: all calculations happen here, in code.
"""
from __future__ import annotations

import json
from typing import Callable

import pandas as pd

from . import config as C
from . import watch as W
from .guardrails import resolve_county

ERA5_SOURCE = ("NASA POWER daily (MERRA-2 reanalysis, bias-corrected rainfall), compared with 1991-2020 normals "
               "(model-based, not station data)")


class Store:
    """Loads the processed outputs written by tools/build_all.py."""

    def __init__(self, processed=C.PROCESSED, reference=C.REFERENCE):
        names = ["three_month", "population", "outlook_current", "outlook_skill", "thresholds",
                 "heat_monthly", "heat_decade", "trends", "counties"]
        self.tables = {n: pd.read_csv(processed / f"{n}.csv") for n in names if (processed / f"{n}.csv").exists()}
        self.playbook = json.loads((reference / "playbook.json").read_text())
        meta = processed / "meta.json"
        self.data_through = json.loads(meta.read_text())["data_through"] if meta.exists() else "unknown"
        self.forecast_fn: Callable | None = None  # set lazily to data.fetch_forecast; tests inject a stub

    def t(self, name: str) -> pd.DataFrame:
        return self.tables[name]


def _unknown(county: str) -> dict:
    return {"error": f"'{county}' is not one of the counties this tool covers. I don't know about it.",
            "available_counties": C.COUNTIES}


def _r(x, nd=1):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def _s(x) -> str:
    """Text from a CSV cell: pandas reads empty cells as NaN, which is truthy, so normalise to ''."""
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)


# ---------------------------------------------------------------- 1. current status
def _level(pct, pct_3m_before) -> str:
    if pd.isna(pct):
        return "Not assessed (normal dry season)"
    if pct < 50 or (pct < 75 and not pd.isna(pct_3m_before) and pct_3m_before < 75):
        return "Alarm"
    if pct < 75:
        return "Alert"
    return "None"


def get_current_status(store: Store, county: str) -> dict:
    """Latest 3-month rainfall vs normal and the drought level for one county."""
    c = resolve_county(county or "")
    if c is None:
        return _unknown(county)
    tm = store.t("three_month")
    g = tm[(tm["county"] == c) & tm["complete_3m"].astype(bool)].sort_values(["year", "month"])
    if g.empty:
        return {"error": f"No data available for {c}. I don't know."}
    latest = g.iloc[-1]
    before = g[(g["year"] * 12 + g["month"]) == (latest["year"] * 12 + latest["month"] - 3)]
    pct_before = before["pct_normal"].iloc[0] if len(before) else float("nan")
    out = {
        "county": c,
        "window": latest["window"],
        "rain_3m_mm": _r(latest["rain_3m_mm"]),
        "normal_3m_mm": _r(latest["normal_3m_mm"]),
        "pct_of_normal": _r(latest["pct_normal"]),
        "drought_class": latest["drought_class"],
        "drought_level": _level(latest["pct_normal"], pct_before),
        "previous_window_pct_of_normal": _r(pct_before),
        "data_through": store.data_through,
        "source": ERA5_SOURCE,
    }
    return out


# ---------------------------------------------------------------- 2. seven-day watch
def get_7day_watch(store: Store, county: str) -> dict:
    """Live 7-day forecast checked against the county's heavy-rain and heat thresholds."""
    c = resolve_county(county or "")
    if c is None:
        return _unknown(county)
    thr = store.t("thresholds")
    thr_row = thr[thr["county"] == c].iloc[0].to_dict()
    cty = store.t("counties")
    row = cty[cty["county"] == c].iloc[0]
    if store.forecast_fn is None:
        from .data import fetch_forecast
        store.forecast_fn = fetch_forecast
    try:
        fc = store.forecast_fn(float(row["lat"]), float(row["lon"]))
    except Exception as e:  # offline, API down
        return {"error": f"Live forecast unavailable ({type(e).__name__}). I don't know the 7-day outlook right now."}
    return W.assess(fc, thr_row)


# ---------------------------------------------------------------- 3. seasonal outlook
def get_seasonal_outlook(store: Store, county: str) -> dict:
    """Probability that the next 3 months fall in the driest third, with the model's tested skill."""
    c = resolve_county(county or "")
    if c is None:
        return _unknown(county)
    oc = store.t("outlook_current")
    r = oc[oc["county"] == c]
    if r.empty:
        return {"error": f"No outlook available for {c}. I don't know."}
    r = r.iloc[0].to_dict()
    sk = store.t("outlook_skill")
    s = sk[(sk["scope"] == "county_season") & (sk["name"] == f"{c} | {r['season_group']}")].set_index("method")
    skill = {}
    if "model" in s.index:
        skill = {"model_bss": _r(s.loc["model", "bss"], 3), "model_f1": _r(s.loc["model", "f1"], 3),
                 "n_test_forecasts": int(s.loc["model", "n"])}
    if "persistence" in s.index:
        skill.update({"persistence_bss": _r(s.loc["persistence", "bss"], 3),
                      "persistence_f1": _r(s.loc["persistence", "f1"], 3)})
    m_bss, p_bss = skill.get("model_bss"), skill.get("persistence_bss")
    has_skill = m_bss is not None and m_bss > 0 and (p_bss is None or m_bss > p_bss)
    return {
        "county": c, "issued_after": r["issue"], "target_window": r["target_window"],
        "season_group": r["season_group"],
        "p_dry_model": _r(r.get("p_dry_model"), 2),
        "chance_of_driest_third": _s(r.get("p_dry_model_display")) or "not issued",
        "p_dry_climatology": _r(r.get("p_dry_climatology"), 2),
        "p_dry_persistence": _r(r.get("p_dry_persistence"), 2),
        "test_skill": skill,
        "skill_metric": "Brier skill score (BSS) vs climatology: above 0 = better than climatology; F1 for warnings",
        "model_beats_baselines_in_test": has_skill,
        "note": _s(r.get("note")) or ("" if has_skill else
                                  "The model did not beat the baselines for this county and season in testing; "
                                  "treat the probability as no better than climatology."),
        "method": "Logistic regression on ENSO (ONI), Indian Ocean Dipole (DMI) and recent rainfall; trained 1991-2016, tested 2017 onward",
    }


# ---------------------------------------------------------------- 4. heat stress (inland replacement for cyclone exposure)
def get_heat_stress(store: Store, county: str) -> dict:
    """Hot days (max temperature above the county's 1991-2020 95th percentile): latest month, normal, trend."""
    c = resolve_county(county or "")
    if c is None:
        return _unknown(county)
    hm = store.t("heat_monthly")
    g = hm[hm["county"] == c].sort_values(["year", "month"])
    if "complete" in g:
        g_done = g[g["complete"].astype(bool)]
        g = g_done if len(g_done) else g
    latest = g.iloc[-1]  # latest COMPLETE month: a partial month would understate heat
    normal = g[(g["month"] == latest["month"]) & g["year"].between(C.NORMAL_START, C.NORMAL_END)]["heat_days"].mean()
    dec = store.t("heat_decade")
    tr = store.t("trends")
    t = tr[(tr["county"] == c) & (tr["variable"] == "heat_days")]
    thr = store.t("thresholds")
    return {
        "county": c,
        "latest_month": f"{int(latest['year'])}-{int(latest['month']):02d}",
        "heat_days_latest_month": int(latest["heat_days"]),
        "normal_heat_days_same_month_1991_2020": _r(normal),
        "hot_day_threshold_tmax_c": _r(thr[thr["county"] == c]["heat_tmax_p95_c"].iloc[0]),
        "mean_heat_days_per_year_by_decade": {int(k): _r(v) for k, v in
                                              dec[dec["county"] == c].set_index("decade")["mean_heat_days_per_year"].items()},
        "trend_heat_days_per_decade": _r(t["sen_slope_per_decade"].iloc[0], 2) if len(t) else None,
        "trend_p_value": _r(t["p_value"].iloc[0], 4) if len(t) else None,
        "source": ERA5_SOURCE,
    }


# ---------------------------------------------------------------- 5. population exposure
def get_population_exposure(store: Store, county: str | None = None) -> dict:
    """Population of one county, or population grouped by current drought class across all counties."""
    pop = store.t("population")
    src = ("KNBS 2019 Kenya Population and Housing Census (official county totals). WorldPop 2020 1 km "
           "estimate shown for comparison only: it is much higher than the census in the north-east.")
    if county:
        c = resolve_county(county)
        if c is None:
            return _unknown(county)
        r = pop[pop["county"] == c].iloc[0]
        return {"county": c, "population": int(r["population"]), "population_year": 2019,
                "worldpop_2020_estimate": int(r["worldpop_2020"]),
                "worldpop_to_census_ratio": _r(r["worldpop_to_census_ratio"], 2),
                "area_km2": _r(r["area_km2"], 0), "density_per_km2": _r(r["density_per_km2"]), "source": src}
    by_class, by_level = {}, {}
    for _, r in pop.iterrows():
        st = get_current_status(store, r["county"])
        if "error" in st:
            continue
        by_class[st["drought_class"]] = by_class.get(st["drought_class"], 0) + int(r["population"])
        by_level[st["drought_level"]] = by_level.get(st["drought_level"], 0) + int(r["population"])
    return {"by_drought_class": by_class, "by_drought_level": by_level,
            "total_population_2019_census": int(pop["population"].sum()), "source": src}


# ---------------------------------------------------------------- 6. playbook
_HAZARD_ALIASES = {"drought": "drought", "heavy_rain": "heavy_rain", "heavy rain": "heavy_rain", "flood": "heavy_rain",
                   "floods": "heavy_rain", "rain": "heavy_rain", "heat": "heat", "heat stress": "heat"}


def lookup_playbook(store: Store, hazard: str, level: str) -> dict:
    """Cited preparedness actions for a hazard and level."""
    h = _HAZARD_ALIASES.get((hazard or "").strip().lower())
    hazards = store.playbook["hazards"]
    if h is None or h not in hazards:
        return {"error": f"Unknown hazard '{hazard}'.", "available": list(hazards)}
    levels = hazards[h]
    lv = next((k for k in levels if k.lower() == (level or "").strip().lower()), None)
    if lv is None:
        return {"error": f"Unknown level '{level}' for {h}.", "available_levels": list(levels)}
    src = store.playbook["sources"]
    return {
        "hazard": h, "level": lv, "trigger": levels[lv]["trigger"],
        "actions": [{"sector": a["sector"], "action": a["action"],
                     "citations": [{"id": s, **src[s]} for s in a["sources"]]} for a in levels[lv]["actions"]],
        "note": store.playbook.get("note", ""),
    }


# ---------------------------------------------------------------- dispatch + schemas
TOOLS = {
    "get_current_status": get_current_status,
    "get_7day_watch": get_7day_watch,
    "get_seasonal_outlook": get_seasonal_outlook,
    "get_heat_stress": get_heat_stress,
    "get_population_exposure": get_population_exposure,
    "lookup_playbook": lookup_playbook,
}


def dispatch(store: Store, name: str, args: dict) -> dict:
    import inspect
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"Unknown tool '{name}'.", "available_tools": list(TOOLS)}
    try:
        inspect.signature(fn).bind(store, **(args or {}))
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
    try:
        return fn(store, **(args or {}))
    except Exception as e:  # a tool failure must become an "I don't know", never a crash
        return {"error": f"{name} could not run ({type(e).__name__}: {e}). I don't know."}


def _county_param(required=True):
    p = {"type": "object", "properties": {"county": {"type": "string", "description": "County name, e.g. Wajir",
                                                     "enum": C.COUNTIES}}}
    if required:
        p["required"] = ["county"]
    return p


TOOL_SPECS = [
    {"type": "function", "function": {"name": "get_current_status", "description":
        "Latest 3-month rainfall as % of the 1991-2020 normal and the drought level for a county.",
        "parameters": _county_param()}},
    {"type": "function", "function": {"name": "get_7day_watch", "description":
        "Live 7-day forecast: heavy-rain and heat alerts for a county against its own extreme thresholds.",
        "parameters": _county_param()}},
    {"type": "function", "function": {"name": "get_seasonal_outlook", "description":
        "Probability that the next 3 months are in the driest third, with tested skill vs baselines.",
        "parameters": _county_param()}},
    {"type": "function", "function": {"name": "get_heat_stress", "description":
        "Heat-stress days for a county: latest month vs normal, change by decade and trend.",
        "parameters": _county_param()}},
    {"type": "function", "function": {"name": "get_population_exposure", "description":
        "Population of a county, or (with no county) population grouped by current drought class.",
        "parameters": _county_param(required=False)}},
    {"type": "function", "function": {"name": "lookup_playbook", "description":
        "Cited preparedness actions. hazard: drought | heavy_rain | heat. level: drought Alert|Alarm, "
        "heavy_rain Watch|Warning, heat Watch|Warning.",
        "parameters": {"type": "object", "properties": {
            "hazard": {"type": "string", "enum": ["drought", "heavy_rain", "heat"]},
            "level": {"type": "string", "enum": ["Alert", "Alarm", "Watch", "Warning"]}},
            "required": ["hazard", "level"]}}},
]
