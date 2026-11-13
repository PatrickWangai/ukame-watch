# Ukame Watch: submission report

**Zetech Alumni × Student Hackathon 2026 · ML & Data Science track · Challenge 1: Climate Sentinel**

Drought, heavy-rain and heat early-warning support for eight arid counties of northern Kenya (Turkana,
Marsabit, Wajir, Mandera, Garissa, Isiolo, Samburu, Kitui; 5.6 million people, KNBS 2019 census).
Planning-support tool only: Kenya Meteorological Department warnings and NDMA drought bulletins take priority.

## Links

| What | Where |
|---|---|
| **Live site** (story page; preloads the dashboard) | https://patrickwangai.github.io/ukame-watch/ |
| **Dashboard only** (runs in the browser; first load 1–2 minutes) | https://patrickwangai.github.io/ukame-watch/dashboard.html |
| **Code repository** (public) | https://github.com/PatrickWangai/ukame-watch |
| **README** (setup, results, architecture, SDG statement, stack) | [README.md](README.md) |
| **Backup demo video** (2 min 57 s, captioned) | https://patrickwangai.github.io/ukame-watch/docs/ukame-watch-demo.mp4 |
| **Grand Finale slides** (PDF) | https://patrickwangai.github.io/ukame-watch/docs/ukame-watch-finale-slides.pdf |
| **Grand Finale slides with speaker notes** (PDF) | https://patrickwangai.github.io/ukame-watch/docs/ukame-watch-finale-slides-with-notes.pdf |

The live demo has every feature except the AI assistant, which needs a local model. Run it on a laptop
with `ollama pull qwen2.5:3b` (see README).

## Required submission items (general rules)

| # | Item | Status | Where |
|---|---|---|---|
| 1 | GitHub repository with code | Done | https://github.com/PatrickWangai/ukame-watch |
| 2 | README with setup and run instructions | Done | [README.md](README.md), "Quick start" |
| 3 | Backup demo video, 2–3 minutes | Done | https://patrickwangai.github.io/ukame-watch/docs/ukame-watch-demo.mp4 (also in the repo: [docs/ukame-watch-demo.mp4](docs/ukame-watch-demo.mp4)) |
| 4 | Live demo URL | Done | https://patrickwangai.github.io/ukame-watch/ |
| 5 | Team member details | Done | Patrick Wangai, Faith Githaiga, Monchari Leah, Dedan Mugambi; roles in [README.md](README.md), "Team" |
| 6 | Alumni Contribution note | Not applicable: the organisers told us no alumni collaborator is needed for our team | — |
| 7 | SDG impact statement | Done | [README.md](README.md), "SDG impact statement" (SDG 13.1, 2.4, 1.5, 11.5) |
| 8 | Technology stack | Done | [README.md](README.md), "Technology stack" |
| 9 | AI-tool disclosure (and every model cited, per track rules) | Done | [README.md](README.md), "Models used and how" and "AI assistance disclosure" |
| 10 | Known limitations | Done | [docs/limitations.md](docs/limitations.md) |

## Challenge 1 core requirements: where each one is met

| # | Requirement | Evidence |
|---|---|---|
| 1 | 30+ years of daily rainfall and temperature for 8+ locations; boundaries, population, ENSO index; rainfall stated as model-based | NASA POWER daily 1991-01-01 to 2026-11-09 for 8 counties; geoBoundaries; KNBS census + WorldPop raster; NOAA ONI and IOD. [DATA.md](DATA.md) |
| 2 | Climatology, seasons, trends with significance tests, extremes | [notebooks/01_weather_behaviour.ipynb](notebooks/01_weather_behaviour.ipynb); [trends.csv](data/processed/trends.csv) (Mann-Kendall + Sen's slope); dry spells, heavy-rain days, max 3-day rain in [annual.csv](data/processed/annual.csv) |
| 3 | Drought indicator (3-month % of normal) and heavy-rain indicator (3-day vs 99th percentile), validated against documented events | All 10 documented events detected; worst 3 droughts and worst 3 heavy-rain periods all match documented events. [validation_documented.csv](data/processed/validation_documented.csv), [validation_top_periods.csv](data/processed/validation_top_periods.csv), sources in [documented_events.csv](data/reference/documented_events.csv) |
| 4 | Cyclone exposure (coastal) or, inland, a heat-stress indicator | Inland counties: hot days above each county's 95th percentile; +5 to +10 per decade, significant in 7 of 8 counties. [heat_monthly.csv](data/processed/heat_monthly.csv), dashboard "Heat stress" tab |
| 5 | Interactive hazard map with population overlay; projected coordinates | Dashboard map with layers for rainfall vs normal, population density and hot days; equal-area projection for county areas and centroids ([src/ukame/data.py](src/ukame/data.py)) |
| 6 | Seasonal outlook: driest third, time-based split (8+ test years), training-only thresholds, climatology and persistence baselines, per-location metrics | Train 1991–2016, test 2017–2026. Oct–Dec: Brier skill +0.12, F1 0.61 vs persistence 0.46. Mar–May: −0.05, no skill, stated openly. [notebooks/02_forecasting.ipynb](notebooks/02_forecasting.ipynb), [outlook_skill.csv](data/processed/outlook_skill.csv) |
| 7 | Live 7-day forecast flagged against each location's 99th percentile | [src/ukame/watch.py](src/ukame/watch.py); dashboard "7-day watch" tab |
| 8 | AI agent: 5+ tools, cites every number, official warnings take priority, drafts need approval; tested on 5+ questions incl. unanswerable, non-existent district, cyclone path, forced "no risk" | 6 tools, code-level guardrails, sources listed on every advisory, human approval. 8-question log: [logs/agent_eval.md](logs/agent_eval.md); code in [src/ukame/agent.py](src/ukame/agent.py) |
| 9 | One-page playbook (5–8 cited actions per hazard and level) and limitations note | [docs/playbook.md](docs/playbook.md), [docs/limitations.md](docs/limitations.md) |
| 10 | Dashboard for a district disaster manager | Live demo above; [app/streamlit_app.py](app/streamlit_app.py) |

## Data quality findings

- **11 impossible rainfall days** in NASA POWER (e.g. 608.5 mm in Turkana on 31 Dec 2020; ERA5: 1.0 mm),
  replaced after an ERA5 check. One genuine flood day kept. [qc_rainfall_flags.csv](data/processed/qc_rainfall_flags.csv)
- **WorldPop overstates the north-east** (Mandera 3.07× the 2019 census), so exposure uses the census.
- **A public table is wrong**: Wikipedia lists Turkana's 2019 population as 1,504,976; KNBS-based sources give 926,976.

## How a judge can verify in five minutes

```bash
git clone https://github.com/PatrickWangai/ukame-watch.git && cd ukame-watch
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python tools/build_all.py           # rebuilds every result from public data (~1 minute)
pytest                              # 92 tests
streamlit run app/streamlit_app.py  # the dashboard
```

A fresh clone reproduces the same validation and forecast-skill results.

## Still to do before the 15:00 freeze

- [x] Record and link the backup demo video (item 3)
- [x] Add team names (item 5)
- [ ] A team member approves at least one advisory in the dashboard, so the agent log shows a human approval
