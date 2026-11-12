# Limitations: read this before acting on anything Ukame Watch shows

**Ukame Watch is a planning-support tool, not an official warning system.** Kenya Meteorological Department (KMD)
forecasts and warnings, and National Drought Management Authority (NDMA) drought bulletins, always take priority.
Every advisory from the assistant is a draft until a named person approves it.

## Data

- **Rainfall and temperature are model-based, not station measurements.** The history comes from NASA POWER
  (MERRA-2 reanalysis, ~50 km grid). Reanalysis rainfall in arid East Africa is uncertain. Against a second
  reanalysis (ERA5), monthly rainfall correlates at 0.72 in Marsabit and 0.70 in Turkana, but daily rainfall
  only at about 0.34, and the two disagree on annual totals (Marsabit: 330 mm vs 132 mm). That is why every
  indicator uses **% of each dataset's own normal**, never absolute millimetres.
- **One grid point per county.** Turkana alone covers about 70,000 km². A single point cannot capture rain that
  falls in one part of a county and not another.
- **Data errors exist and we fix the ones we find.** We found 11 physically implausible NASA POWER rainfall days
  (up to 608 mm in one day in Turkana; ERA5 shows 1 mm). They are replaced with the ERA5 value and listed in
  `data/processed/qc_rainfall_flags.csv`. After the fix, Turkana's monthly agreement with ERA5 rose from
  0.49 to 0.70, independent evidence the flagged days were errors. Smaller errors may remain undetected.
- **Population uses the 2019 census.** WorldPop's 2020 estimate is up to 3 times higher in Mandera, Wajir and
  Garissa, and Turkana leaders disputed the census as too low. Exposure numbers are approximate in both directions.

## Indicators

- **Drought = rainfall deficit only.** The tool does not see pasture, livestock condition, water prices or
  malnutrition, which NDMA uses to set phases. It therefore issues only *Alert* and *Alarm*; *Emergency* and
  *Recovery* are NDMA decisions.
- **Dry seasons are not assessed.** When a 3-month window normally gets under 30 mm, "% of normal" is
  meaningless (a 5 mm shower can read as 300%), so the tool says "dry season" instead.
- **Validation is encouraging but small.** All 10 documented events we checked were flagged, but 20 of 71 rainy
  seasons fall below the 75% drought signal, and not all of those were declared disasters. Three events (D4, D5,
  F5) were added to our list *after* the indicator flagged them, then verified independently; we label them so.
- **Hot days are a temperature measure, not a heat-health index.** Without reliable humidity at the time of peak
  heat we use maximum temperature above each county's 95th percentile. Hot days are increasing significantly in
  7 of 8 counties (about +5 to +10 per decade).

## Seasonal outlook

- **Skill exists only for the October-December short rains.** On held-out years (2017 onward) the model's Brier
  skill score against climatology is +0.12 for the short rains and −0.05 for the March-May long rains, where it is
  worse than climatology. Treat long-rains outlooks as having no skill.
- **The test period was unusually dry.** 51% of short-rains test seasons fell in the training-period driest third
  (35% expected), consistent with the failed seasons of 2020-2022 and 2024-2025. Skill estimates from 28 forecasts
  per county are noisy.
- **Low probabilities are over-confident.** In testing, forecasts below 20% verified as dry seasons 26% of the
  time. Read "under 5%" as "clearly lower than the usual one-in-three", not as a guarantee of good rains.
- **Extreme predictors push the model outside its experience.** In November 2026 the Oceanic Niño Index is +2.46 and
  the Dipole Mode Index +0.95, stronger than almost all training years. The model then says "under 5%"; we never show
  smaller numbers because they are not meaningful.

## 7-day watch

- **Forecast and thresholds come from different models.** The live forecast (Open-Meteo) and the thresholds
  (NASA POWER) may be biased against each other, so a heavy-rain watch is a prompt to check KMD, not a warning.

## Assistant (AI agent)

- **Small local model.** Qwen 2.5 3B runs on a laptop so no data leaves the device, but it can misread tool outputs.
  Code-level guardrails catch the main failure modes (invented numbers, "no risk" claims, cyclone-track requests,
  uncovered counties), and code adds the cited playbook actions when a hazard level is active. Other errors remain
  possible, which is why a person must approve every advisory.
- **Cyclone paths are out of scope.** For tropical cyclones, follow KMD and the WMO Regional Specialized
  Meteorological Centre La Réunion.

## Reporting errors

Open an issue on the GitHub repository with the county, date and what looked wrong, or tell the team at the demo.
Confirmed data errors are added to the QC log and the indicators are rebuilt with `python tools/build_all.py`.
