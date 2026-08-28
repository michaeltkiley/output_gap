#!/usr/bin/env python3
"""Score every quarter's predictors (including the most recent quarters,
where the h-ahead outcome isn't yet realized) against the current-analysis
coefficients from data/estimates.json, writing outputs/unemployment_risk.csv.

Two things per horizon (h4 = 1yr, h12 = 3yr):
  prob_full5   Prob(du(t+h) >= threshold) from the full 5-variable logit --
               the headline "risk of a large increase in unemployment" gauge.
  prob_fin2    Same, from the financial-only (term spread + credit spread)
               logit -- the conventional-recession-prediction comparison line.
  magnitude    QU_0.80(t+h) from the full 5-variable quantile regression --
               the implied size (percentage points) of the tail move, not
               just its probability.

Fitted/scored using data/observables.csv's full history against whatever
coefficients 02_estimate.py most recently produced (expanding window,
2020Q1-2020Q4 excluded from estimation -- but *not* excluded from scoring,
so the dashboard still shows what the model would have said through the
COVID episode itself, it just wasn't fit on it).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
OBS_PATH = REPO_ROOT / "data" / "observables.csv"
ESTIMATES_PATH = REPO_ROOT / "data" / "estimates.json"
OUT_PATH = REPO_ROOT / "outputs" / "unemployment_risk.csv"

FULL5_VARS = ["unrate", "infl4q", "credit_gr16q", "bond_spread", "term_spread"]
FIN2_VARS = ["bond_spread", "term_spread"]


def logistic(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def score_logit(df: pd.DataFrame, predictors: list[str], params: dict) -> pd.Series:
    z = params["const"] + sum(df[v] * params[v] for v in predictors)
    return pd.Series(logistic(z), index=df.index)


def score_linear(df: pd.DataFrame, predictors: list[str], params: dict) -> pd.Series:
    z = params["Intercept"] + sum(df[v] * params[v] for v in predictors)
    return pd.Series(z, index=df.index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even if up to date")
    args = parser.parse_args()

    if OUT_PATH.exists() and not args.force:
        newest_input = max(OBS_PATH.stat().st_mtime, ESTIMATES_PATH.stat().st_mtime)
        if OUT_PATH.stat().st_mtime > newest_input:
            print(f"{OUT_PATH} is newer than its inputs, skipping (use --force to rebuild)")
            return

    df = pd.read_csv(OBS_PATH).set_index("date")
    estimates = json.loads(ESTIMATES_PATH.read_text())

    out = pd.DataFrame(index=df.index)
    for label, h_est in estimates["horizons"].items():
        full5_rows = df[FULL5_VARS].dropna().index
        fin2_rows = df[FIN2_VARS].dropna().index
        out.loc[full5_rows, f"prob_full5_{label}"] = score_logit(
            df.loc[full5_rows], FULL5_VARS, h_est["full5_logit"]["params"])
        out.loc[fin2_rows, f"prob_fin2_{label}"] = score_logit(
            df.loc[fin2_rows], FIN2_VARS, h_est["fin2_logit"]["params"])
        out.loc[full5_rows, f"magnitude_full5_{label}"] = score_linear(
            df.loc[full5_rows], FULL5_VARS, h_est["full5_quantreg"]["params"])
        out[f"threshold_{label}"] = h_est["threshold_80pct"]

    out = out.dropna(how="all")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.reset_index().rename(columns={"date": "date"}).to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH} ({len(out)} quarters, {out.index.min()}..{out.index.max()})")

    print("\nLatest scored quarter per series (availability differs -- e.g. BIS "
          "credit/GDP data lags FRED's other series by a few quarters):")
    for label in estimates["horizons"]:
        for col in (f"prob_full5_{label}", f"prob_fin2_{label}", f"magnitude_full5_{label}"):
            s = out[col].dropna()
            last_date, last_val = s.index[-1], s.iloc[-1]
            unit = "pp" if col.startswith("magnitude") else ""
            fmt = f"{last_val:+.2f}{unit}" if unit else f"{last_val:.1%}"
            print(f"  {col:22s} {last_date}: {fmt}")


if __name__ == "__main__":
    main()
