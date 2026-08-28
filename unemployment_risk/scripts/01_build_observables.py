#!/usr/bin/env python3
"""Build the predictor/dependent-variable panel for the unemployment-risk
models from data/fred.duckdb (00_ingest_fred.py), writing data/observables.csv.

Variable construction follows the definitions in Kiley (2021), "Unemployment
Risk", JMCB 54(5) (docs/kiley_2021_unemployment_risk.pdf), Table 1 notes and
Section 1.1/1.2:

  unrate       U(t): civilian unemployment rate, quarterly average, percent.
  infl4q       4*pi(t): 4-quarter percent change in the PCE price index
               (quarterly-averaged level), percent.
  credit_gr16q 16*(c(t)/y(t)): percent change in the BIS nonfinancial
               private-sector credit-to-GDP ratio from 4 years (16 quarters)
               earlier, log difference, annualized (divided by 4), percent.
               QUSPAM770A is already the credit/GDP ratio -- no separate GDP
               series needed.
  bond_spread  r_bbb(t) - r_tsy(t): Baa corporate bond yield minus the 10-yr
               Treasury yield, quarterly average of monthly series, percent.
               Uses BAA/GS10 (long monthly series back to 1919/1953) rather
               than FRED's DBAA/BAA10Y/DGS10 (which only start in 1986/1986/
               1962) so the 1965:Q1 paper sample is fully covered.
  term_spread  r_tsy(t) - r_ffr(t): 10-yr Treasury yield minus the federal
               funds rate, quarterly average of monthly series, percent.
  du_h4        U(t+4) - U(t): change in the unemployment rate 4 quarters
               ahead, percent. NaN for the last 4 quarters (not yet knowable).
  du_h12       U(t+12) - U(t): change in the unemployment rate 12 quarters
               ahead, percent. NaN for the last 12 quarters.

Sample starts 1965:Q1, matching "data from 1965:Q1 to 2019:Q4" (JMCB paper)
and "the beginning of the period for which the relevant prediction data is
available" (FEDS Note). Runs through the latest quarter with complete
predictor data; 02_estimate.py handles the replication-vs-current-analysis
estimation-sample windowing (fixed 1965:Q1-2019:Q4 vs. expanding-window with
2020:Q1-2020:Q4 dropped) and the 80th-percentile threshold computation --
both are estimation-sample properties, not observable-construction ones.
"""
import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "fred.duckdb"
OUT_PATH = REPO_ROOT / "data" / "observables.csv"

SAMPLE_START = "1965-01-01"
HORIZONS = {"h4": 4, "h12": 12}
CREDIT_LAG_Q = 16


def load_wide(con) -> pd.DataFrame:
    df = con.execute("SELECT series_id, obs_date, value FROM fred_raw").fetchdf()
    wide = df.pivot(index="obs_date", columns="series_id", values="value")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def to_quarterly_mean(monthly: pd.Series) -> pd.Series:
    return monthly.resample("QS").mean()


def build(con) -> pd.DataFrame:
    w = load_wide(con)

    unrate_q = to_quarterly_mean(w["UNRATE"])
    pcepi_q = to_quarterly_mean(w["PCEPI"])
    baa_q = to_quarterly_mean(w["BAA"])
    gs10_q = to_quarterly_mean(w["GS10"])
    fedfunds_q = to_quarterly_mean(w["FEDFUNDS"])
    credit_gdp_q = w["QUSPAM770A"].resample("QS").mean()  # already quarterly

    obs = pd.DataFrame(index=unrate_q.index)
    obs["unrate"] = unrate_q
    obs["infl4q"] = 100 * np.log(pcepi_q / pcepi_q.shift(4))
    obs["credit_gr16q"] = (
        100 * np.log(credit_gdp_q / credit_gdp_q.shift(CREDIT_LAG_Q)) / 4
    )
    obs["bond_spread"] = baa_q - gs10_q
    obs["term_spread"] = gs10_q - fedfunds_q

    for label, h in HORIZONS.items():
        obs[f"du_{label}"] = obs["unrate"].shift(-h) - obs["unrate"]

    obs = obs.loc[SAMPLE_START:]
    return obs


def sanity_check(obs: pd.DataFrame):
    print("\nSanity summary:")
    cols = ["unrate", "infl4q", "credit_gr16q", "bond_spread", "term_spread",
            "du_h4", "du_h12"]
    print(f"{'series':13s} {'n':>5s} {'n_nan':>6s} {'mean':>8s} {'std':>8s} "
          f"{'min':>8s} {'max':>8s}")
    for col in cols:
        s = obs[col]
        print(f"{col:13s} {len(s):5d} {s.isna().sum():6d} {s.mean():8.3f} "
              f"{s.std():8.3f} {s.min():8.3f} {s.max():8.3f}")
    checks = {
        "unrate": (obs["unrate"].mean(), 3.0, 9.0),
        "infl4q": (obs["infl4q"].mean(), 0.0, 5.0),
        "bond_spread": (obs["bond_spread"].mean(), 0.5, 3.0),
        "term_spread": (obs["term_spread"].mean(), -1.0, 3.0),
    }
    print("\nPlausibility bounds:")
    for name, (val, lo, hi) in checks.items():
        status = "OK" if lo <= val <= hi else "CHECK"
        print(f"  {status:5s} {name}: {val:.3f} (expected [{lo}, {hi}])")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even if up to date")
    args = parser.parse_args()

    if OUT_PATH.exists() and not args.force:
        if OUT_PATH.stat().st_mtime > DB_PATH.stat().st_mtime:
            print(f"{OUT_PATH} is newer than {DB_PATH.name}, skipping (use --force to rebuild)")
            return

    con = duckdb.connect(str(DB_PATH), read_only=True)
    obs = build(con)
    con.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = obs.reset_index().rename(columns={obs.index.name or "index": "date"})
    out["date"] = out["date"].dt.to_period("Q").astype(str)
    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH} ({len(out)} quarters, {out['date'].iloc[0]}..{out['date'].iloc[-1]})")

    sanity_check(obs)


if __name__ == "__main__":
    main()
