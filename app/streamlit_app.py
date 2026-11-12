"""Ukame Watch dashboard.  Run:  streamlit run app/streamlit_app.py

Reads only data/processed/ (built by tools/build_all.py) plus the live 7-day forecast,
so it still works if the venue Wi-Fi fails (the 7-day watch then says it is unavailable).
"""
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ukame import agent as A  # noqa: E402
from ukame import agent_tools as T  # noqa: E402
from ukame import config as C  # noqa: E402
from ukame.outlook import display_probability  # noqa: E402

P = C.PROCESSED
st.set_page_config(page_title="Ukame Watch", page_icon="🌾", layout="wide")

# ------------------------------------------------------------------ design tokens
INK, INK2, MUTED = "#1B1D1C", "#52514e", "#898781"
JADE = "#0F6E66"
SURFACE, PLANE = "#FCFCFB", "#EEF0EC"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834"]                       # validated categorical slots 1-2
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
# Diverging rainfall scale: red = drier than normal, grey = near normal, blue = wetter.
PCT_BINS = [(50, "#b8302f", "under 50%"), (75, "#e34948", "50-75%"), (90, "#ee9288", "75-90%"),
            (110, "#f0efec", "90-110%"), (150, "#9ec5f4", "110-150%"), (200, "#5598e7", "150-200%"),
            (float("inf"), "#1c5cab", "over 200%")]
LEVEL_STYLE = {  # icon + label + colour: never colour alone
    "None": ("●", "Normal", STATUS["good"]), "Alert": ("▲", "Alert", STATUS["warning"]),
    "Alarm": ("◆", "Alarm", STATUS["serious"]),
    "Not assessed (normal dry season)": ("○", "Dry season", MUTED),
}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800&family=Atkinson+Hyperlegible:wght@400;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, p, li, label {{ font-family: 'Atkinson Hyperlegible', system-ui, sans-serif; }}
h1, h2, h3, .uw-display {{ font-family: 'Archivo', system-ui, sans-serif; font-stretch: 72%; letter-spacing: 0.005em; }}
.block-container {{ padding-top: 3.6rem; max-width: 1360px; }}
.uw-top {{ display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; flex-wrap:wrap;
          border-bottom: 2px solid {INK}; padding-bottom:.6rem; margin-bottom:.8rem; }}
.uw-brand {{ font-family:'Archivo',system-ui; font-stretch:68%; font-weight:800; font-size:2.7rem; line-height:1; color:{INK}; }}
.uw-brand span {{ color:{JADE}; }}
.uw-sub {{ color:{INK2}; font-size:1rem; margin-top:.25rem; }}
.uw-meta {{ text-align:right; color:{INK2}; font-size:.88rem; line-height:1.4; }}
.uw-banner {{ background:{SURFACE}; border-left:4px solid {JADE}; padding:.55rem .9rem; font-size:.92rem; color:{INK};
             margin-bottom:1rem; border-radius:0 6px 6px 0; }}
.uw-board {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:.7rem; margin-bottom:1.2rem; }}
@media (max-width: 1000px) {{ .uw-board {{ grid-template-columns: repeat(2, minmax(0,1fr)); }} }}
.uw-tile {{ background:{SURFACE}; border:1px solid rgba(11,11,11,.10); border-radius:8px; padding:.75rem .85rem .7rem; }}
.uw-tile h4 {{ font-family:'Archivo',system-ui; font-stretch:72%; font-weight:750; font-size:1.35rem; margin:0; color:{INK}; }}
.uw-row {{ display:flex; justify-content:space-between; align-items:baseline; gap:.5rem; }}
.uw-chip {{ font-size:.8rem; font-weight:700; padding:.12rem .5rem; border-radius:999px; border:1.5px solid; white-space:nowrap; }}
.uw-fig {{ font-size:1.55rem; font-weight:700; color:{INK}; line-height:1.15; margin-top:.35rem; }}
.uw-cap {{ font-size:.78rem; color:{INK2}; }}
.uw-strip {{ display:flex; gap:2px; margin:.5rem 0 .15rem; }}
.uw-strip div {{ flex:1; height:14px; border-radius:2px; }}
.uw-flags {{ font-size:.8rem; color:{INK2}; margin-top:.35rem; border-top:1px solid {GRID}; padding-top:.35rem; }}
.uw-flags b {{ color:{INK}; }}
.uw-key {{ display:flex; gap:.9rem; flex-wrap:wrap; font-size:.78rem; color:{INK2}; margin:-.6rem 0 1rem; }}
.uw-key i {{ display:inline-block; width:12px; height:12px; border-radius:2px; margin-right:4px; vertical-align:-1px; }}
.uw-badge {{ display:inline-block; font-weight:700; font-size:.8rem; padding:.15rem .55rem; border-radius:4px; color:#fff; }}
:focus-visible {{ outline: 3px solid {JADE} !important; outline-offset: 2px; }}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ data
@st.cache_resource
def get_store():
    return T.Store()


@st.cache_data
def table(name):
    return pd.read_csv(P / f"{name}.csv")


@st.cache_data(ttl=3600, show_spinner="Fetching the live 7-day forecast…")
def cached_forecast(lat, lon):
    from ukame.data import fetch_forecast
    return fetch_forecast(lat, lon)


@st.cache_data(ttl=3600)
def watch_all():
    store = get_store()
    store.forecast_fn = cached_forecast  # one fetch per county, shared by the alerts and the charts
    return {c: T.get_7day_watch(store, c) for c in C.COUNTIES}


def forecast_df(county):
    cty = table("counties").set_index("county")
    try:
        return cached_forecast(float(cty.loc[county, "lat"]), float(cty.loc[county, "lon"])).copy()
    except Exception:
        return None


@st.cache_data
def county_geojson():
    """Plotly's map engine (d3-geo) expects clockwise outer rings; GeoJSON (RFC 7946) uses counter-clockwise.
    Without re-orienting, each county is drawn as 'the whole world except the county'."""
    from shapely.geometry import MultiPolygon, mapping, shape
    from shapely.geometry.polygon import orient
    gj = json.loads((P / "counties.geojson").read_text())
    for f in gj["features"]:
        g = shape(f["geometry"])
        parts = g.geoms if isinstance(g, MultiPolygon) else [g]
        g = MultiPolygon([orient(p, sign=-1.0) for p in parts])
        f["geometry"] = mapping(g)
    return gj


store = get_store()
meta = json.loads((P / "meta.json").read_text())


_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def window_text(label):
    """'ASO 2026' -> 'Aug–Oct 2026'; 'NDJ 2027' -> 'Nov 2026–Jan 2027'."""
    try:
        code, year = label.split()
        end_m = "JFMAMJJASOND".index(code[-1]) + 1
        end_y = int(year)
        months = [(end_m - k - 1) % 12 for k in (2, 1, 0)]
        start_y = end_y - (1 if months[0] > months[-1] else 0)
        if start_y == end_y:
            return f"{_MON[months[0]]}–{_MON[months[-1]]} {end_y}"
        return f"{_MON[months[0]]} {start_y}–{_MON[months[-1]]} {end_y}"
    except Exception:
        return label


def pct_colour(p):
    if pd.isna(p):
        return "#e1e0d9"
    return next(col for upper, col, _ in PCT_BINS if p < upper)


def base_layout(fig, height=320, title=None, yaxis_title=None):
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=40 if title else 12, b=8), paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE, font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK2, size=12),
        title=dict(text=title, font=dict(size=15, color=INK), x=0, xanchor="left") if title else None,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, font=dict(color=INK2)),
        hoverlabel=dict(bgcolor="#ffffff", font=dict(color=INK)), bargap=0.25)
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=AXIS, tickfont=dict(color=MUTED),
                     title=dict(text=yaxis_title, font=dict(color=MUTED, size=12)))
    return fig


# ------------------------------------------------------------------ header
st.markdown(f"""
<div class="uw-top">
  <div><div class="uw-brand">Ukame <span>Watch</span></div>
  <div class="uw-sub">Drought, heavy-rain and heat early warning for eight arid counties of northern Kenya</div></div>
  <div class="uw-meta">Weather data through <b>{pd.Timestamp(meta['data_through']):%d %b %Y}</b><br>
  Normals {meta['normal_period']} · Population: KNBS 2019 census</div>
</div>
<div class="uw-banner"><b>Planning support only — not an official warning.</b> Kenya Meteorological Department
warnings and NDMA drought bulletins take priority. Advisories from this tool are drafts until a named person approves them.</div>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ situation board
tm = table("three_month")
oc = table("outlook_current").set_index("county")
pop = table("population").set_index("county")
watches = watch_all()
statuses = {c: T.get_current_status(store, c) for c in C.COUNTIES}

tiles = []
for c in C.COUNTIES:
    s = statuses[c]
    icon, label, colour = LEVEL_STYLE.get(s["drought_level"], ("○", s["drought_level"], MUTED))
    seasons = tm[(tm["county"] == c) & tm["month"].isin([5, 12]) & tm["pct_normal"].notna()].tail(8)
    strip = "".join(f'<div style="background:{pct_colour(r.pct_normal)}" title="{window_text(r.window)}: {r.pct_normal:.0f}% of normal"></div>'
                    for r in seasons.itertuples())
    w = watches[c]
    if "error" in w:
        flags = "7-day watch: <b>unavailable offline</b>"
    else:
        rain = "<b>heavy rain watch</b>" if w["heavy_rain_alert"] else "no heavy rain"
        heat = f"<b>heat {w['heat_level'].lower()}</b>" if w["heat_level"] != "None" else "no heat alert"
        flags = f"Next 7 days: {rain} · {heat}"
    pct = "—" if s["pct_of_normal"] is None else f"{s['pct_of_normal']:.0f}%"
    out = oc.loc[c]
    outlook_txt = out["p_dry_model_display"] if isinstance(out.get("p_dry_model_display"), str) else "not issued"
    tiles.append(f"""
<div class="uw-tile" role="group" aria-label="{c}: drought level {label}">
  <div class="uw-row"><h4>{c}</h4>
    <span class="uw-chip" style="color:{INK};border-color:{colour};background:{colour}22">{icon} Drought: {label.lower()}</span></div>
  <div class="uw-fig">{pct} <span class="uw-cap">of normal rain, {window_text(s['window'])}</span></div>
  <div class="uw-strip" aria-hidden="true">{strip}</div>
  <div class="uw-row uw-cap"><span>Last 8 rainy seasons →</span><span>{int(pop.loc[c, 'population']):,} people</span></div>
  <div class="uw-flags">Risk of a very dry {out['target_window'].replace(' - ', '–')}: <b>{outlook_txt}</b><br>{flags}</div>
</div>""")
st.markdown(f'<div class="uw-board">{"".join(tiles)}</div>', unsafe_allow_html=True)
st.markdown('<div class="uw-key">' + "".join(f'<span><i style="background:{col}"></i>{lab}</span>' for _, col, lab in PCT_BINS)
            + '<span>— season rainfall as % of the 1991–2020 normal</span></div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ map + county focus
left, right = st.columns([1.05, 1])
with left:
    gj = county_geojson()
    cty = table("counties")
    vals = [statuses[c]["pct_of_normal"] for c in cty["county"]]
    fig = go.Figure()
    for upper, col, lab in PCT_BINS:
        idx = [i for i, v in enumerate(vals) if v is not None and next(u for u, _, _ in PCT_BINS if v < u) == upper]
        if not idx:
            continue
        fig.add_trace(go.Choropleth(
            geojson=gj, featureidkey="properties.county", locations=cty["county"].iloc[idx],
            z=[1] * len(idx), colorscale=[[0, col], [1, col]], showscale=False, name=lab, showlegend=True,
            marker_line_color="#ffffff", marker_line_width=1.5,
            customdata=[[c, vals[i], statuses[c]["drought_level"], int(pop.loc[c, "population"])]
                        for i, c in zip(idx, cty["county"].iloc[idx])],
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:.0f}% of normal rain<br>"
                          "Drought level: %{customdata[2]}<br>Population: %{customdata[3]:,}<extra></extra>"))
    fig.add_trace(go.Scattergeo(lon=cty["lon"], lat=cty["lat"], text=cty["county"], mode="text",
                                textfont=dict(color=INK, size=12), hoverinfo="skip", showlegend=False))
    fig.update_geos(fitbounds="locations", visible=False, bgcolor=SURFACE)
    base_layout(fig, height=430, title=f"Rainfall vs normal, {window_text(statuses['Wajir']['window'])}")
    fig.update_layout(legend=dict(orientation="v", y=0.02, yanchor="bottom", x=0.0, xanchor="left", title=None))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

with right:
    county = st.selectbox("County in focus", C.COUNTIES, index=C.COUNTIES.index("Wajir"))
    s = statuses[county]
    st.markdown(f"### {county}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Rain vs normal", "—" if s["pct_of_normal"] is None else f"{s['pct_of_normal']:.0f}%", help=window_text(s["window"]))
    m2.metric("Drought level", LEVEL_STYLE.get(s["drought_level"], ("", s["drought_level"], ""))[1])
    m3.metric("Population (2019)", f"{int(pop.loc[county, 'population']):,}")
    mon = table("monthly")
    clim = table("climatology")
    g = mon[(mon["county"] == county)].tail(24).merge(clim[clim["county"] == county], on=["county", "month"])
    g["label"] = pd.to_datetime(dict(year=g.year, month=g.month, day=1))
    fig = go.Figure()
    fig.add_bar(x=g["label"], y=g["rain_mm"], name="Rainfall", marker_color=SERIES[0],
                marker=dict(cornerradius=4), hovertemplate="%{x|%b %Y}: %{y:.0f} mm<extra>Rainfall</extra>")
    fig.add_scatter(x=g["label"], y=g["rain_normal_mm"], name="1991–2020 normal", mode="lines",
                    line=dict(color=INK2, width=2, dash="dot"), hovertemplate="%{x|%b}: normal %{y:.0f} mm<extra></extra>")
    base_layout(fig, height=300, title="Monthly rainfall, last 24 months", yaxis_title="mm")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("Partial current month shown as rainfall to date. Rainfall is NASA POWER (MERRA-2) reanalysis, not station data.")

# ------------------------------------------------------------------ tabs
tabs = st.tabs(["Season history", "Seasonal outlook", "7-day watch", "Heat stress", "Track record",
                "Draft an advisory", "Method & limits"])

# ---- season history
with tabs[0]:
    st.markdown(f"#### {county}: every rainy season since 1991")
    st.caption("Each bar is one season's rainfall as % of its 1991–2020 normal. Red bars are failed seasons; "
               "the dotted line is normal (100%).")
    events = pd.read_csv(C.REFERENCE / "documented_events.csv")
    for month, name in [(12, "Short rains (Oct–Dec)"), (5, "Long rains (Mar–May)")]:
        h = tm[(tm["county"] == county) & (tm["month"] == month)].dropna(subset=["pct_normal"])
        fig = go.Figure(go.Bar(x=h["year"], y=h["pct_normal"], marker_color=[pct_colour(v) for v in h["pct_normal"]],
                               marker_line_color="rgba(11,11,11,.25)", marker_line_width=0.5,
                               hovertemplate="%{x}: %{y:.0f}% of normal<extra></extra>", showlegend=False))
        fig.add_hline(y=100, line=dict(color=INK2, width=1.5, dash="dot"))
        for e in events.itertuples():
            ys, ye = pd.Timestamp(e.start), pd.Timestamp(e.end)
            in_season = any((pd.Timestamp(year=y, month=month, day=1) >= ys - pd.offsets.MonthBegin(2)) and
                            (pd.Timestamp(year=y, month=month, day=1) <= ye) for y in range(ys.year, ye.year + 1))
            if in_season:
                yr = ye.year if month == 5 or ye.month >= month else ys.year
                fig.add_annotation(x=yr, y=1.0, yref="paper", text=e.event_id, showarrow=False,
                                   font=dict(size=10, color=INK2), yanchor="bottom")
        base_layout(fig, height=230, title=name, yaxis_title="% of normal")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("Labels above bars mark documented events (see Track record). "
               + " · ".join(f"{e.event_id}: {e.label}" for e in events.itertuples()))

# ---- seasonal outlook
with tabs[1]:
    o = table("outlook_current")
    sk = table("outlook_skill")
    st.markdown(f"#### Chance the next three months fall in the driest third: {o['target_window'].iloc[0]}")
    st.caption("Climatology (the dotted line) is about one in three by definition. Below it means a drier-than-usual "
               "season is less likely than normal. Values under 5% are shown as 'under 5%': the model is extrapolating "
               "from a very strong El Niño and positive Indian Ocean Dipole, so exact small numbers are not meaningful. "
               "In testing, forecasts below 20% still verified dry about a quarter of the time: read 'under 5%' as "
               "'clearly below the usual one in three', not as a guarantee of good rains.")
    oo = o.sort_values("p_dry_model")
    fig = go.Figure(go.Bar(y=oo["county"], x=oo["p_dry_model"] * 100, orientation="h", marker_color=SERIES[0],
                           marker=dict(cornerradius=4), text=oo["p_dry_model_display"], textposition="outside",
                           textfont=dict(color=INK), hovertemplate="%{y}: %{text}<extra></extra>", showlegend=False))
    clim_p = float(o["p_dry_climatology"].iloc[0]) * 100
    fig.add_vline(x=clim_p, line=dict(color=INK2, dash="dot", width=1.5),
                  annotation_text=f"climatology {clim_p:.0f}%", annotation_position="top")
    base_layout(fig, height=320)
    fig.update_xaxes(range=[0, 100], title=dict(text="% chance", font=dict(color=MUTED)), showgrid=True, gridcolor=GRID)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.markdown("#### Did the model beat the baselines? Test years 2017 onward")
    st.caption("Brier skill score against climatology: above 0 means better than always forecasting the long-run odds. "
               "The model has skill for the October–December short rains, which are driven by the Indian Ocean Dipole "
               "and El Niño, and **no skill for the March–May long rains**. We report that rather than hide it.")
    cs = sk[(sk["scope"] == "county_season") & (sk["method"] == "model")].copy()
    cs[["county", "season"]] = cs["name"].str.split(" \\| ", expand=True)
    fig = go.Figure()
    for i, (season, lab) in enumerate([("short_rains", "Short rains (Oct–Jan targets)"), ("long_rains", "Long rains (Feb–Jun targets)")]):
        d = cs[cs["season"] == season].set_index("county").reindex(C.COUNTIES)
        fig.add_bar(x=d.index, y=d["bss"], name=lab, marker_color=SERIES[i], marker=dict(cornerradius=4),
                    hovertemplate="%{x}: BSS %{y:.2f}<extra>" + lab + "</extra>")
    fig.add_hline(y=0, line=dict(color=AXIS, width=1.5))
    base_layout(fig, height=320, yaxis_title="Brier skill score")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    summ = sk[sk["scope"].isin(["all", "season"])].copy()
    summ["name"] = summ["name"].map({"all": "All wet windows", "short_rains": "Short rains", "long_rains": "Long rains",
                                     "other": "Other wet windows"})
    st.dataframe(summ.rename(columns={"name": "Season", "method": "Method", "n": "Forecasts", "events": "Dry seasons"})
                 [["Season", "Method", "Forecasts", "Dry seasons", "precision", "recall", "f1", "brier", "bss"]],
                 hide_index=True, width="stretch")

# ---- 7-day watch
with tabs[2]:
    w = watches[county]
    st.markdown(f"#### {county}: live 7-day forecast against the county's own extremes")
    if "error" in w:
        st.warning(w["error"])
    else:
        fc = forecast_df(county)
        if fc is not None:
            fc["rain3"] = fc["precipitation_sum"].rolling(3).sum()
            c1, c2 = st.columns(2)
            fig = go.Figure()
            fig.add_bar(x=fc["date"], y=fc["precipitation_sum"], name="Daily rain", marker_color=SERIES[0],
                        marker=dict(cornerradius=4), hovertemplate="%{x|%a %d %b}: %{y:.1f} mm<extra>Daily</extra>")
            fig.add_scatter(x=fc["date"], y=fc["rain3"], name="3-day total", mode="lines+markers",
                            line=dict(color=SERIES[1], width=2), marker=dict(size=8),
                            hovertemplate="%{x|%a %d %b}: %{y:.1f} mm<extra>3-day total</extra>")
            fig.add_hline(y=w["threshold_3day_p99_mm"], line=dict(color=INK2, dash="dot"),
                          annotation_text=f"heavy-rain threshold {w['threshold_3day_p99_mm']:.0f} mm (99th pct)")
            c1.plotly_chart(base_layout(fig, 300, "Rainfall", "mm"), width="stretch", config={"displayModeBar": False})
            fig = go.Figure()
            fig.add_scatter(x=fc["date"], y=fc["temperature_2m_max"], name="Max temperature", mode="lines+markers",
                            line=dict(color=SERIES[1], width=2), marker=dict(size=8),
                            hovertemplate="%{x|%a %d %b}: %{y:.1f} °C<extra></extra>")
            fig.add_hline(y=w["heat_threshold_p95_c"], line=dict(color=INK2, dash="dot"),
                          annotation_text=f"hot-day threshold {w['heat_threshold_p95_c']:.1f} °C (95th pct)")
            c2.plotly_chart(base_layout(fig, 300, "Maximum temperature", "°C"), width="stretch",
                            config={"displayModeBar": False})
    rows = []
    for c, ww in watches.items():
        if "error" in ww:
            rows.append({"County": c, "Heavy rain": "unavailable", "Max 3-day (mm)": None, "Threshold (mm)": None,
                         "Hot days": None, "Heat level": "unavailable"})
        else:
            rows.append({"County": c, "Heavy rain": "Watch" if ww["heavy_rain_alert"] else "None",
                         "Max 3-day (mm)": ww["max_3day_forecast_mm"], "Threshold (mm)": ww["threshold_3day_p99_mm"],
                         "Hot days": ww["heat_alert_days"], "Heat level": ww["heat_level"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Forecast: Open-Meteo (live). Thresholds: NASA POWER 1991–2020. Different models can be biased against "
               "each other, so treat alerts as prompts to check KMD forecasts, not as warnings.")

# ---- heat stress
with tabs[3]:
    an = table("annual")
    tr = table("trends")
    a = an[an["county"] == county]
    t = tr[(tr["county"] == county) & (tr["variable"] == "heat_days")].iloc[0]
    st.markdown(f"#### {county}: hot days per year")
    st.caption(f"A hot day has a maximum temperature above {county}'s 1991–2020 95th percentile "
               f"({table('thresholds').set_index('county').loc[county, 'heat_tmax_p95_c']:.1f} °C). "
               f"Trend (Mann-Kendall, Sen's slope): **{t['sen_slope_per_decade']:+.1f} hot days per decade**, "
               f"p = {t['p_value']:.3f}. This inland region replaces the challenge's cyclone module with heat stress.")
    fig = go.Figure(go.Bar(x=a["year"], y=a["heat_days"], marker_color=SERIES[1], marker=dict(cornerradius=4),
                           hovertemplate="%{x}: %{y} hot days<extra></extra>", showlegend=False))
    st.plotly_chart(base_layout(fig, 300, yaxis_title="hot days"), width="stretch", config={"displayModeBar": False})
    ht = tr[tr["variable"].isin(["heat_days", "mean_tmax_c"])].pivot_table(
        index="county", columns="variable", values=["sen_slope_per_decade", "p_value"])
    ht.columns = [f"{v} ({m})" for m, v in ht.columns]
    st.dataframe(ht.round(3), width="stretch")
    st.caption("We ran 64 trend tests (8 counties × 8 variables), so about 3 'significant' results are expected by chance. "
               "Heat trends are significant in 7 of 8 counties, far more than chance; most rainfall trends are not.")

# ---- track record
with tabs[4]:
    st.markdown("#### Does the indicator catch real disasters?")
    vd = table("validation_documented")
    ev = pd.read_csv(C.REFERENCE / "documented_events.csv")[["event_id", "listed"]]
    vd = vd.merge(ev, on="event_id")
    st.dataframe(vd[["event_id", "label", "indicator_value", "threshold", "detected", "listed", "source_url"]]
                 .rename(columns={"event_id": "Event", "label": "Documented event", "indicator_value": "Indicator",
                                  "threshold": "Detect if", "detected": "Detected", "listed": "When listed",
                                  "source_url": "Source"}),
                 hide_index=True, width="stretch",
                 column_config={"Source": st.column_config.LinkColumn("Source"),
                                "Indicator": st.column_config.NumberColumn(format="%.0f")})
    st.markdown("#### The three worst periods in our data — do they match documented events?")
    st.dataframe(table("validation_top_periods"), hide_index=True, width="stretch")
    st.caption("Three events (D4, D5, F5) were added after our indicator flagged those periods, then verified against "
               "independent sources. We mark them so the check is not mistaken for a blind test.")
    rd = table("regional_drought_pct")
    rd["season"] = rd["month"].map({5: "MAM", 12: "OND"})
    rd["label"] = rd["season"] + " " + rd["year"].astype(str)  # compact on a 70-season axis
    fig = go.Figure(go.Bar(x=rd["label"], y=rd["value"], marker_color=[pct_colour(v) for v in rd["value"]],
                           marker_line_color="rgba(11,11,11,.25)", marker_line_width=0.5,
                           hovertemplate="%{x}: %{y:.0f}% of normal (8-county mean)<extra></extra>"))
    fig.add_hline(y=75, line=dict(color=INK2, dash="dot"), annotation_text="drought signal: below 75%")
    base_layout(fig, 280, "Eight-county mean rainfall, every rainy season", "% of normal")
    fig.update_xaxes(tickangle=-60, tickfont=dict(size=9))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    flagged = int((rd["value"] < 75).sum())
    st.caption(f"{flagged} of {len(rd)} rainy seasons fall below 75% of normal. Not every flagged season is a documented "
               "disaster: the indicator measures rainfall, not impact, so it is a prompt for checking, not a declaration.")
    st.markdown("#### Cross-check against a second reanalysis (ERA5)")
    if (P / "crosscheck_era5.csv").exists():
        st.dataframe(table("crosscheck_era5"), hide_index=True, width="stretch")
    else:
        st.info("ERA5 cross-check not built on this machine (needs data/raw/era5_*.csv).")
    st.caption("NASA POWER and ERA5 agree on month-to-month patterns but disagree on amounts in this arid region. "
               "That is why every indicator uses % of normal within one dataset rather than absolute millimetres.")

# ---- advisory
with tabs[5]:
    st.markdown("#### Draft an advisory")
    st.caption(f"The assistant uses a small local model ({C.AGENT_MODEL}, via Ollama; nothing leaves this computer). "
               "It can only use six tools, every call is logged, numbers are checked against tool outputs, and the "
               "draft is not final until a named person approves it.")
    examples = [f"What is the current drought situation in {county}, and what should the county prepare?",
                f"Is there a heavy-rain or heat alert for {county} in the next 7 days?",
                f"How many people live in {county}, and what is the drought outlook?"]
    pick = st.radio("Example questions", examples, index=0, label_visibility="collapsed")
    q = st.text_area("Your question", value=pick, height=80)
    if st.button("Draft advisory", type="primary"):
        with st.spinner("Calling tools and drafting… (about 20–60 seconds on this laptop)"):
            try:
                st.session_state["draft"] = A.answer(q, store)
            except Exception as e:
                st.error(f"The local model is not available ({type(e).__name__}). Start it with `ollama serve`, "
                         f"then check `ollama list` shows {C.AGENT_MODEL}.")
    d = st.session_state.get("draft")
    if d:
        colour = {"draft": JADE, "needs_review": STATUS["critical"], "refusal": INK2}.get(d["status"], INK2)
        label = {"draft": "Draft — awaiting approval", "needs_review": "Needs review — check flagged items",
                 "refusal": "Refused / out of scope"}.get(d["status"], d["status"])
        st.markdown(f'<span class="uw-badge" style="background:{colour}">{label}</span>', unsafe_allow_html=True)
        st.markdown(d["text"])
        if d["checks"]["ungrounded_numbers"]:
            st.error("Numbers not found in any tool output: " + ", ".join(d["checks"]["ungrounded_numbers"]))
        if d["checks"]["absolute_claim_blocked"]:
            st.warning("The model tried to state there was no risk. That statement was blocked and replaced.")
        with st.expander(f"Tool calls ({len(d['tool_calls'])}) — every number above should appear here"):
            for tc in d["tool_calls"]:
                st.markdown(f"**{tc['tool']}** `{json.dumps(tc['arguments'])}`")
                st.json(tc["result"], expanded=False)
        if d["status"] != "refusal":
            c1, c2, c3 = st.columns([2, 1, 1])
            who = c1.text_input("Your name and role (recorded with the decision)", key="approver")
            if c2.button("Approve", disabled=not who):
                A.record_decision(d, who, "approved")
                st.success(f"Approved by {who}. Recorded in logs/advisories.jsonl.")
            if c3.button("Reject", disabled=not who):
                A.record_decision(d, who, "rejected")
                st.info(f"Rejected by {who}. Recorded in logs/advisories.jsonl.")
    log = C.LOGS / "advisories.jsonl"
    if log.exists():
        st.markdown("##### Decision log")
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        st.dataframe(pd.DataFrame(rows)[["decided_at", "decision", "approver", "question"]].iloc[::-1],
                     hide_index=True, width="stretch")

# ---- method & limits
with tabs[6]:
    lim = ROOT / "docs" / "limitations.md"
    st.markdown(lim.read_text() if lim.exists() else "See README.md and DATA.md.")
