"""Step 1 of the pipeline: download every raw dataset into data/raw/ (cached; safe to rerun).

Usage:  python tools/fetch_data.py [--force]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ukame import config as C  # noqa: E402
from ukame import data as D  # noqa: E402


def main(force: bool = False) -> None:
    t0 = time.time()
    counties = D.study_counties()
    counties.drop(columns="geometry").to_csv(C.PROCESSED / "counties.csv", index=False)
    print(f"[boundaries] {len(counties)} counties")

    for _, row in counties.iterrows():
        df = D.fetch_weather(row["county"], row["lat"], row["lon"], force=force)
        print(f"[weather] {row['county']:<9} {len(df):>6} days  {df['date'].min().date()} -> {df['date'].max().date()}")
        time.sleep(1)  # be polite to the free API

    idx = D.load_indices()
    print(f"[indices] ONI+DMI {idx['year'].min()}-{idx['year'].max()}  "
          f"latest ONI {D.fetch_oni().iloc[-1].to_dict()}  latest DMI {D.fetch_dmi().iloc[-1].to_dict()}")

    pop = D.fetch_population(force=force)
    pop.to_csv(C.PROCESSED / "population.csv", index=False)
    print(f"[population] census 2019 total {pop['population'].sum():,}; WorldPop 2020 total {pop['worldpop_2020'].sum():,}")
    print(pop[["county", "census_2019", "worldpop_2020", "worldpop_to_census_ratio"]].to_string(index=False))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
