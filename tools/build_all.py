"""One command to rebuild everything from raw data:  python tools/build_all.py [--force]

  1. fetch raw data (cached unless --force)
  2. weather-behaviour analysis: quality checks, climatology, trends, extremes, indicators
  3. validation against documented events
  4. seasonal outlook: train 1991-2016, test 2017 onward, compare with two baselines
  5. ERA5 cross-check, metadata, generated playbook document
All outputs go to data/processed/ and are read by the dashboard and the agent.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import fetch_data  # noqa: E402
from ukame import analysis as A  # noqa: E402
from ukame import config as C  # noqa: E402
from ukame import data as D  # noqa: E402
from ukame import outlook as O  # noqa: E402
from ukame import validation as V  # noqa: E402

P = C.PROCESSED


def save(df: pd.DataFrame, name: str) -> pd.DataFrame:
    df.to_csv(P / f"{name}.csv", index=False)
    print(f"  wrote {name}.csv ({len(df)} rows)")
    return df


def step(title):
    print(f"\n== {title}")


def main(force=False):
    t0 = time.time()
    step("1. Fetch raw data")
    fetch_data.main(force=force)
    D.study_counties().to_file(P / "counties.geojson", driver="GeoJSON")

    step("2. Weather behaviour")
    raw_daily = D.load_weather()
    candidates = raw_daily[raw_daily["precipitation_sum"] > A.QC_CANDIDATE_MM]
    era5 = D.era5_for_days(candidates, pd.read_csv(P / "counties.csv"))
    daily, qc = A.qc_rainfall(raw_daily, era5)
    save(qc, "qc_rainfall_flags")
    print(f"  rainfall QC: {len(qc)} candidate days > {A.QC_CANDIDATE_MM:.0f} mm; "
          f"{(qc['action'] == 'replaced with ERA5').sum()} replaced, "
          f"{qc['action'].str.startswith('set missing').sum()} set missing, {qc['action'].str.startswith('kept').sum()} kept")
    q = save(A.quality_report(daily), "quality_report")
    if (q[["missing_dates", "negative_rain", "tmin_above_tmax", "duplicate_dates"]].sum().sum()) > 0:
        print("  WARNING: quality issues found, see quality_report.csv")
    mon = A.monthly(daily)
    save(mon, "monthly")
    save(A.climatology(mon), "climatology")
    tm = save(A.three_month(mon), "three_month")
    thr = save(A.thresholds(daily), "thresholds")
    dind = A.daily_indicators(daily, thr)
    annual = save(A.annual_extremes(dind), "annual")
    seasons = save(A.season_totals(tm), "season_totals")
    save(A.trends(annual, seasons), "trends")
    save(A.heat_stress(dind), "heat_monthly")
    save(A.heat_by_decade(annual), "heat_decade")
    recent = dind[dind["date"] >= dind["date"].max() - pd.Timedelta(days=120)]
    save(recent[["county", "date", "precipitation_sum", "rain_3day_mm", "rain_3day_p99_mm", "heavy_rain_flag",
                 "temperature_2m_max", "heat_tmax_p95_c", "heat_flag"]], "recent_daily")

    step("3. Validation against documented events")
    events = pd.read_csv(C.REFERENCE / "documented_events.csv")
    dpct = V.regional_drought_pct(tm)
    heavy_m = V.regional_heavy_counts(dind)
    heavy_3m = V.rolling_3m(heavy_m)
    heavy_thr = float(np.nanpercentile(heavy_3m["value"].dropna(), 95))
    print(f"  heavy-rain detection threshold (95th pct of 3-month regional counts): {heavy_thr:.0f} county-days")
    save(V.check_documented(events, dpct, heavy_3m, heavy_thr), "validation_documented")
    top_d = V.match_to_events(V.top_periods(dpct, "value", 3, lowest=True, min_gap_months=12), events, "drought")
    top_h = V.match_to_events(V.top_periods(heavy_3m, "value", 3, lowest=False, min_gap_months=6), events, "heavy_rain")
    save(pd.concat([top_d.assign(hazard="drought", measure="regional mean 3-month % of normal (lowest)"),
                    top_h.assign(hazard="heavy_rain", measure="county-days above p99 in 3 months (highest)")]),
         "validation_top_periods")
    save(dpct, "regional_drought_pct")
    save(heavy_3m, "regional_heavy_3m")

    step("4. Seasonal outlook")
    idx = D.load_indices()
    ds = O.add_targets(O.build_dataset(mon, idx))
    fitted = O.fit(ds)
    pred = O.predict(ds, fitted)
    skill = save(O.evaluate(pred), "outlook_skill")
    save(pred[pred["split"] == "test"][["county", "issue_year", "issue_month", "target_year", "target_end_month",
                                        "season_group", "target_rain_mm", "dry_threshold_mm", "dry",
                                        "p_model", "p_clim", "p_persistence"]], "outlook_predictions")
    save(O.current_outlook(ds, fitted), "outlook_current")
    model_info = {g: {k: v for k, v in f.items() if k != "model"} for g, f in fitted.items()}
    (P / "outlook_model.json").write_text(json.dumps(model_info, indent=2, default=float))
    s = skill[skill["scope"].isin(["all", "season"])].pivot_table(index="name", columns="method", values="bss")
    print("  Brier skill score vs climatology (test 2017+):\n" + s.round(3).to_string())

    step("5. Cross-check, metadata, playbook")
    era5 = D.load_era5_crosscheck()
    if len(era5):  # only on machines that downloaded the full ERA5 files; otherwise keep the committed result
        rows = []
        for c, g in era5.groupby("county"):
            m = g.merge(daily[["county", "date", "precipitation_sum"]], on=["county", "date"], suffixes=("_era5", "_power"))
            mm = m.set_index("date").resample("MS")[["precipitation_sum_era5", "precipitation_sum_power"]].sum()
            rows.append({"county": c, "days_compared": len(m),
                         "daily_correlation": round(m["precipitation_sum_era5"].corr(m["precipitation_sum_power"]), 3),
                         "monthly_correlation": round(mm.iloc[:, 0].corr(mm.iloc[:, 1]), 3),
                         "mean_annual_era5_mm": round(mm.iloc[:, 0].mean() * 12, 0),
                         "mean_annual_power_mm": round(mm.iloc[:, 1].mean() * 12, 0)})
        save(pd.DataFrame(rows), "crosscheck_era5")
    meta = {"data_through": str(daily.groupby("county")["date"].max().min().date()),
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "normal_period": f"{C.NORMAL_START}-{C.NORMAL_END}", "test_start_year": C.TEST_START_YEAR,
            "counties": C.COUNTIES, "agent_model": C.AGENT_MODEL}
    (P / "meta.json").write_text(json.dumps(meta, indent=2))
    write_playbook_md()
    print(f"\nBuild complete in {time.time() - t0:.0f}s. Data through {meta['data_through']}.")


def write_playbook_md():
    pb = json.loads((C.REFERENCE / "playbook.json").read_text())
    src = pb["sources"]
    lines = ["# Ukame Watch action playbook", "",
             "_Generated from `data/reference/playbook.json` by `tools/build_all.py`. Do not edit by hand._", "",
             f"> {pb['note']}", "",
             "Kenya Meteorological Department warnings and NDMA drought bulletins always take priority.", ""]
    for hazard, levels in pb["hazards"].items():
        lines.append(f"## {hazard.replace('_', ' ').title()}")
        for level, body in levels.items():
            lines += ["", f"### {level}", "", f"**Trigger:** {body['trigger']}", "",
                      "| # | Sector | Action | Sources |", "|---|---|---|---|"]
            for i, a in enumerate(body["actions"], 1):
                cites = ", ".join(f"[{s}]({src[s]['url']})" for s in a["sources"])
                lines.append(f"| {i} | {a['sector']} | {a['action']} | {cites} |")
        lines.append("")
    lines += ["## Sources", ""] + [f"- **{k}**: [{v['title']}]({v['url']})" for k, v in src.items()]
    (ROOT / "docs" / "playbook.md").write_text("\n".join(lines) + "\n")
    print("  wrote docs/playbook.md")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
