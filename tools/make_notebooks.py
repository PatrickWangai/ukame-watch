"""Generate and execute the two required notebooks from the tested modules.

Usage: python tools/make_notebooks.py   (run after tools/build_all.py)
"""
from pathlib import Path

import nbformat as nbf
from nbconvert.preprocessors import ExecutePreprocessor

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks"
NB.mkdir(exist_ok=True)

SETUP = """import sys, json, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path.cwd().parent
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd, numpy as np, matplotlib.pyplot as plt
from ukame import config as C
P = C.PROCESSED
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 20)
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#1B1D1C", "#898781", "#e1e0d9"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#c3c2b7",
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
                     "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "figure.dpi": 110})
def pct_colour(p):
    for upper, col in [(50,"#b8302f"),(75,"#e34948"),(90,"#ee9288"),(110,"#d6d5cf"),(150,"#9ec5f4"),(200,"#5598e7"),(1e9,"#1c5cab")]:
        if p < upper: return col
"""


def md(s):
    return nbf.v4.new_markdown_cell(s.strip())


def code(s):
    return nbf.v4.new_code_cell(s.strip())


def weather_notebook():
    return [
        md("""# 01 · Weather behaviour, hazard indicators and validation
**Ukame Watch** · eight arid counties of northern Kenya · Challenge 1: Climate Sentinel

This notebook reads the outputs of `python tools/build_all.py` (which calls the tested functions in
`src/ukame/analysis.py` and `validation.py`). Rainfall and temperature are **NASA POWER (MERRA-2) reanalysis:
model-based, not station data**. Normals: 1991–2020."""),
        code(SETUP),
        md("## 1. Data coverage and quality"),
        code("""counties = pd.read_csv(P/"counties.csv"); pop = pd.read_csv(P/"population.csv")
display(counties.merge(pop[["county","census_2019","worldpop_2020","worldpop_to_census_ratio"]], on="county"))
display(pd.read_csv(P/"quality_report.csv"))"""),
        md("""### Rainfall QC: spurious one-day spikes
NASA POWER contains a few physically implausible days that a second reanalysis (ERA5) does not see.
Candidates (> 100 mm) where ERA5 shows less than 10% of the value are replaced with the ERA5 value."""),
        code("""qc = pd.read_csv(P/"qc_rainfall_flags.csv"); display(qc)
print(qc["action"].value_counts().to_string())
display(pd.read_csv(P/"crosscheck_era5.csv"))"""),
        md("## 2. Monthly climatology (1991–2020 normals)"),
        code("""clim = pd.read_csv(P/"climatology.csv")
fig, axes = plt.subplots(2, 4, figsize=(14, 5.5), sharey=True)
for ax, c in zip(axes.flat, C.COUNTIES):
    g = clim[clim.county == c]
    ax.bar(g.month, g.rain_normal_mm, color=BLUE, width=0.75)
    ax.set_title(c); ax.set_xticks(range(1, 13)); ax.set_xticklabels(list("JFMAMJJASOND"))
axes[0,0].set_ylabel("mm / month"); axes[1,0].set_ylabel("mm / month")
fig.suptitle("Two rainy seasons: Mar–May (long rains) and Oct–Dec (short rains)", x=0.01, ha="left"); plt.tight_layout()"""),
        md("## 3. Seasons and trends (Mann-Kendall test, Sen's slope per decade)"),
        code("""tr = pd.read_csv(P/"trends.csv")
print(f"{tr.significant_5pct.sum()} of {len(tr)} tests significant at p < 0.05 (about {0.05*len(tr):.0f} expected by chance)")
display(tr.pivot_table(index="county", columns="variable", values="sen_slope_per_decade").round(2))
display(tr[tr.significant_5pct][["county","variable","trend","p_value","sen_slope_per_decade"]])"""),
        md("""**Reading:** temperature trends dominate. Hot days and mean maximum temperature rise significantly in most
counties; seasonal rainfall totals show no significant trend in any county."""),
        code("""an = pd.read_csv(P/"annual.csv")
fig, axes = plt.subplots(2, 4, figsize=(14, 5.5), sharey=True)
for ax, c in zip(axes.flat, C.COUNTIES):
    g = an[an.county == c]
    ax.bar(g.year, g.heat_days, color=ORANGE, width=0.8)
    z = np.polyfit(g.year, g.heat_days, 1); ax.plot(g.year, np.polyval(z, g.year), color=INK, lw=1.5)
    ax.set_title(c)
axes[0,0].set_ylabel("hot days / year"); axes[1,0].set_ylabel("hot days / year")
fig.suptitle("Hot days per year (max temperature above the county's 1991–2020 95th percentile)", x=0.01, ha="left"); plt.tight_layout()"""),
        md("## 4. Extremes: longest dry spell, heavy-rain days, maximum 3-day rainfall"),
        code("""display(an.groupby("county")[["longest_dry_spell_days","heavy_rain_days","max_3day_rain_mm"]].agg(["mean","max"]).round(1))
display(pd.read_csv(P/"thresholds.csv"))"""),
        md("""## 5. Hazard indicators
- **Drought:** 3-month rainfall as % of the 1991–2020 normal for the same months (not assessed when the normal is under 30 mm).
- **Heavy rain:** 3-day total above the county's 99th percentile (normal period only).
- **Heat:** max temperature above the county's 95th percentile."""),
        code("""tm = pd.read_csv(P/"three_month.csv")
fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
for ax, (m, name) in zip(axes, [(12, "Short rains (Oct–Dec)"), (5, "Long rains (Mar–May)")]):
    g = tm[(tm.month == m)].pivot_table(index="year", columns="county", values="pct_normal").mean(axis=1)
    ax.bar(g.index, g.values, color=[pct_colour(v) for v in g.values], width=0.8)
    ax.axhline(100, color=INK, ls=":", lw=1); ax.axhline(75, color=MUTED, ls="--", lw=1)
    ax.set_title(name + ": eight-county mean, % of normal"); ax.set_ylabel("% of normal")
plt.tight_layout()"""),
        md("## 6. Validation against documented events"),
        code("""vd = pd.read_csv(P/"validation_documented.csv")
ev = pd.read_csv(C.REFERENCE/"documented_events.csv")[["event_id","listed","source_title"]]
display(vd.merge(ev, on="event_id")[["event_id","label","indicator_value","threshold","detected","listed","source_title"]])
print(f"Detected {vd.detected.sum()} of {len(vd)} documented events")
display(pd.read_csv(P/"validation_top_periods.csv"))
rd = pd.read_csv(P/"regional_drought_pct.csv")
print(f"{(rd.value < 75).sum()} of {len(rd)} rainy seasons fall below the 75% drought signal (false-alarm context)")"""),
        md("""**Honesty notes.** D4, D5 and F5 were added to the event list *after* our indicator flagged those periods,
then verified against independent sources (FAO GIEWS, IFRC). The drought signal fires in more seasons than were
declared disasters: the indicator measures rainfall deficit, not impact."""),
        md("## 7. Current situation"),
        code("""latest = tm[tm.complete_3m].sort_values(["year","month"]).groupby("county").tail(1)
display(latest[["county","window","rain_3m_mm","normal_3m_mm","pct_normal","drought_class"]].round(1))
print(json.loads((P/"meta.json").read_text()))"""),
    ]


def forecast_notebook():
    return [
        md("""# 02 · Seasonal outlook: will the next three months fall in the driest third?
**Ukame Watch** · Challenge 1: Climate Sentinel

Built by `src/ukame/outlook.py` (tested in `tests/test_outlook.py`). The rules that keep this honest:
1. **Issue time = end of month m.** Features use only what is known then: rainfall to month m, the Dipole Mode
   Index (DMI) for month m, and the Oceanic Niño Index (ONI) for the season centred on month m−1.
2. **Training-only thresholds.** "Driest third" = the training-period 33rd percentile for that county and window.
3. **Time-based split.** Targets ending ≤ 2016 train; ≥ 2017 test (10 seasons, more than the required 8 years).
4. **Two baselines.** Climatology (always the base rate) and persistence (P(dry next | dry now) from training).
5. **Separate models per season group**, because East African teleconnections differ by season."""),
        code(SETUP + "\nfrom ukame import data as D, analysis as A, outlook as O"),
        md("## 1. Build the dataset"),
        code("""mon = pd.read_csv(P/"monthly.csv"); idx = D.load_indices()
ds = O.add_targets(O.build_dataset(mon, idx))
print(ds.split.value_counts().to_string())
display(ds[ds.wet_window.fillna(False)].groupby(["season_group","split"]).agg(rows=("dry","size"), dry_share=("dry", lambda s: s.astype(float).mean())).round(3))"""),
        md("""The test period was drier than training: about half of the short-rains test seasons fell in the training
driest third (35% expected), consistent with the failed seasons of 2020–2022 and 2024–2025."""),
        md("## 2. Fit and inspect the models"),
        code("""fitted = O.fit(ds)
for g, f in fitted.items():
    print(f"{g:<12} n_train={f['n_train']:<5} climatology={f['clim']:.3f}  persistence: dry->{f['pers_dry']:.3f} wet->{f['pers_wet']:.3f}")
    print("             standardised coefficients:", f["coefficients_standardised"])"""),
        md("""**Reading:** for the short rains the Dipole Mode Index has the largest coefficient (negative: a positive
Indian Ocean Dipole makes a dry season less likely), followed by ENSO. This matches the published physics of the
East African short rains. For the long rains, recent rainfall dominates and the climate indices add little."""),
        md("## 3. Test-period skill vs baselines (2017 onward)"),
        code("""pred = O.predict(ds, fitted); sk = O.evaluate(pred)
display(sk[sk.scope.isin(["all","season"])].set_index(["name","method"])[["n","events","precision","recall","f1","brier","bss"]])"""),
        code("""cs = sk[(sk.scope=="county_season") & (sk.method=="model")].copy()
cs[["county","season"]] = cs["name"].str.split(" \\\\| ", expand=True)
piv = cs.pivot_table(index="county", columns="season", values="bss").reindex(C.COUNTIES)
display(piv.round(3))
fig, ax = plt.subplots(figsize=(11, 3.8)); x = np.arange(len(C.COUNTIES)); w = 0.38
ax.bar(x - w/2, piv["short_rains"], w, color=BLUE, label="Short rains (Oct–Jan targets)")
ax.bar(x + w/2, piv["long_rains"], w, color=ORANGE, label="Long rains (Feb–Jun targets)")
ax.axhline(0, color=INK, lw=1); ax.set_xticks(x); ax.set_xticklabels(C.COUNTIES); ax.set_ylabel("Brier skill score")
ax.set_title("Model skill vs climatology by county, test 2017+ (above 0 = better than climatology)"); ax.legend(frameon=False)
plt.tight_layout()"""),
        md("""**Conclusion.** The model beats both baselines for the October–December short rains in all eight counties
(Brier skill score above 0 and above persistence). For the March–May long rains it has **no skill**: the Brier skill
score is negative overall. The app labels long-rains outlooks accordingly."""),
        md("## 4. Reliability: do the probabilities mean what they say?"),
        code("""t = pred[(pred.split=="test") & pred.dry.notna()].copy(); t["y"] = t.dry.astype(int)
t["bin"] = pd.cut(t.p_model, [0, .2, .35, .5, .65, 1.0])
rel = t.groupby("bin", observed=True).agg(forecasts=("y","size"), mean_forecast=("p_model","mean"), observed_dry=("y","mean")).round(3)
display(rel)"""),
        md("""**Reading (calibration).** The model is reasonably calibrated in the middle range but **over-confident at
low probabilities**: forecasts below 20% verified as dry seasons about a quarter of the time. Part of this is the
unusually dry test period. So a forecast of "under 5%" should be read as "clearly lower than the usual one in three",
not as near-certainty of good rains."""),
        md("## 5. The current outlook"),
        code("""cur = O.current_outlook(ds, fitted)
display(cur[["county","issue","target_window","season_group","p_dry_model","p_dry_model_display","p_dry_climatology","p_dry_persistence","oni","dmi"]])"""),
        md("""In November 2026 the ONI is +2.46 (strong El Niño) and the DMI +0.95 (positive Indian Ocean Dipole), so the
model expects a wet short-rains season and gives every county a very low chance of a driest-third season. These
predictor values are near the edge of the training range, so the app shows "under 5%" rather than exact small
numbers. A wet season raises **flood** risk: see the 7-day watch."""),
    ]


def build(name, cells):
    nb = nbf.v4.new_notebook()
    nb["cells"] = cells
    nb["metadata"]["kernelspec"] = {"name": "ukame", "display_name": "Python 3 (ukame-watch)", "language": "python"}
    ExecutePreprocessor(timeout=600, kernel_name="ukame").preprocess(nb, {"metadata": {"path": str(NB)}})
    nbf.write(nb, NB / name)
    print("wrote", NB / name)


if __name__ == "__main__":
    build("01_weather_behaviour.ipynb", weather_notebook())
    build("02_forecasting.ipynb", forecast_notebook())
