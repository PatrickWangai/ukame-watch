"""Write assistant-data.json: the tool results the in-browser assistant (assistant.html) works from.

The browser assistant has no Python, so this script runs the same tools the laptop agent uses
(src/ukame/agent_tools.py) for every county and saves their outputs. The 7-day watch is not saved:
the page fetches the live forecast itself and applies the same thresholds as src/ukame/watch.py.

Usage: python tools/make_assistant_data.py   (rerun after python tools/build_all.py)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ukame import agent_tools as T  # noqa: E402
from ukame import config as C  # noqa: E402
from ukame import guardrails as G  # noqa: E402
from ukame import watch as W  # noqa: E402

PLAYBOOK_LEVELS = [("drought", "Alert"), ("drought", "Alarm"), ("heavy_rain", "Watch"), ("heavy_rain", "Warning"),
                   ("heat", "Watch"), ("heat", "Warning")]


def _clean(x):
    """Browsers reject NaN in JSON, so missing numbers become null."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def main() -> None:
    store = T.Store()
    thr = store.t("thresholds")
    cty = store.t("counties")
    counties = {}
    for c in C.COUNTIES:
        t = thr[thr["county"] == c].iloc[0]
        row = cty[cty["county"] == c].iloc[0]
        counties[c] = {
            "lat": float(row["lat"]), "lon": float(row["lon"]),
            "thresholds": {"rain_3day_p99_mm": float(t["rain_3day_p99_mm"]),
                           "heat_tmax_p95_c": float(t["heat_tmax_p95_c"])},
            "get_current_status": T.dispatch(store, "get_current_status", {"county": c}),
            "get_seasonal_outlook": T.dispatch(store, "get_seasonal_outlook", {"county": c}),
            "get_heat_stress": T.dispatch(store, "get_heat_stress", {"county": c}),
            "get_population_exposure": T.dispatch(store, "get_population_exposure", {"county": c}),
        }
    playbook = {f"{h}|{lv}": T.dispatch(store, "lookup_playbook", {"hazard": h, "level": lv})
                for h, lv in PLAYBOOK_LEVELS}
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counties": counties,
        "playbook": playbook,
        "other_counties": G.OTHER_KENYAN_COUNTIES,
        "cyclone_refusal": G.CYCLONE_REFUSAL,
        "disclaimer": C.DISCLAIMER,
        "forecast": {"url": C.OPEN_METEO_FORECAST, "timezone": C.TIMEZONE,
                     "heat_watch_days": W.HEAT_WATCH_DAYS, "heat_warning_days": W.HEAT_WARNING_DAYS},
    }
    path = ROOT / "assistant-data.json"
    path.write_text(json.dumps(_clean(json.loads(json.dumps(out, default=str))), indent=1, allow_nan=False))
    print(f"wrote {path.name} ({path.stat().st_size // 1024} KB, {len(counties)} counties)")


if __name__ == "__main__":
    main()
