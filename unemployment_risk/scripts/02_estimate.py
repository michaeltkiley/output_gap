#!/usr/bin/env python3
"""Fit the unemployment-risk quantile and logit models from data/observables.csv,
writing data/estimates.json (current-analysis) or data/estimates_replication.json
(--replication).

Two model specs, at two horizons (h4 = 1 year, h12 = 3 years), matching
Kiley (2021), "Unemployment Risk", JMCB 54(5), Section 1.2 equations (2) and (4):

  full5   U(t+h) = a0 + a1*unrate(t) + a2*infl4q(t) + a3*credit_gr16q(t)
                     + a4*bond_spread(t) + a5*term_spread(t)
          The paper's full specification. Fit as both a quantile regression
          (q=0.80, giving the QU_0.80(t+h) risk *magnitude*) and a logit
          predicting Prob(du(t+h) >= unconditional 80th percentile) (risk
          *probability*).
  fin2    Same, but only bond_spread and term_spread -- the "conventional"
          financial-variables-only model from the FEDS Note companion piece
          (docs/kiley_2022_feds_notes_recession_risk.html), logit only, for
          comparison against the full model on the dashboard.

--replication: fixed 1965:Q1-2019:Q4 sample, exactly matching both papers
  (which deliberately exclude the COVID-19 recession). Coefficients here are
  checked against the papers' own reported values by run_replication.py.

default (current analysis): expanding window, 1965:Q1 through the latest
  quarter with a known h-quarter-ahead outcome. 2020:Q1-2020:Q4 are dropped
  from the estimation sample entirely -- both as the observation quarter t
  and whenever t+h falls in that window -- per the user's explicit choice to
  purge the COVID unemployment spike from both sides of the forward-looking
  regressions rather than truncate the sample or re-include it. Coefficients
  therefore shift slightly as new quarters arrive; 03_export_results.py
  re-scores the latest predictors against whatever is current here.

Confidence intervals via a moving-block bootstrap (block length 11 quarters,
matching "Kilian and Lutkepohl (2017), chapter 12" in both papers' table
notes) -- blocks of *all* variables (dependent + predictors) are resampled
jointly with replacement to preserve serial correlation from the overlapping
h-quarter-ahead horizons, then each model is refit on the resampled panel.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

REPO_ROOT = Path(__file__).resolve().parent.parent
OBS_PATH = REPO_ROOT / "data" / "observables.csv"
OUT_PATH = REPO_ROOT / "data" / "estimates.json"
REPLICATION_OUT_PATH = REPO_ROOT / "data" / "estimates_replication.json"

REPLICATION_SAMPLE_START = "1965Q1"
REPLICATION_SAMPLE_END = "2019Q4"
COVID_EXCLUDE = {"2020Q1", "2020Q2", "2020Q3", "2020Q4"}

HORIZONS = {"h4": 4, "h12": 12}
QUANTILE = 0.80
BLOCK_LEN = 11
N_BOOT = 500
RNG_SEED = 20260828

FULL5_VARS = ["unrate", "infl4q", "credit_gr16q", "bond_spread", "term_spread"]
FIN2_VARS = ["bond_spread", "term_spread"]


def load_observables() -> pd.DataFrame:
    df = pd.read_csv(OBS_PATH)
    return df.set_index("date")


def estimation_rows(df: pd.DataFrame, label: str, replication: bool) -> pd.DataFrame:
    """Rows usable to fit the model at horizon `label` -- predictors and the
    realized h-ahead outcome both known, subject to sample-window rules."""
    cols = FULL5_VARS + [f"du_{label}"]
    rows = df[cols].dropna()
    if replication:
        return rows.loc[REPLICATION_SAMPLE_START:REPLICATION_SAMPLE_END]

    h = HORIZONS[label]
    quarters = rows.index.to_series()
    t_period = pd.PeriodIndex(quarters, freq="Q")
    t_plus_h_period = t_period + h
    keep = ~(t_period.astype(str).isin(COVID_EXCLUDE)
             | t_plus_h_period.astype(str).isin(COVID_EXCLUDE))
    return rows.loc[keep]


def threshold_80th(rows: pd.DataFrame, label: str) -> float:
    return float(np.percentile(rows[f"du_{label}"], 80))


def fit_quantreg(rows: pd.DataFrame, label: str, predictors: list[str]) -> dict:
    formula = f"du_{label} ~ " + " + ".join(predictors)
    mod = smf.quantreg(formula, rows)
    res = mod.fit(q=QUANTILE)
    return {"params": res.params.to_dict(), "pseudo_r2": float(res.prsquared)}


def fit_ols(rows: pd.DataFrame, label: str, predictors: list[str]) -> dict:
    formula = f"du_{label} ~ " + " + ".join(predictors)
    res = smf.ols(formula, rows).fit()
    return {"params": res.params.to_dict(), "r2": float(res.rsquared)}


def fit_logit(rows: pd.DataFrame, label: str, predictors: list[str], thresh: float) -> dict:
    y = (rows[f"du_{label}"] >= thresh).astype(int)
    X = sm.add_constant(rows[predictors])
    res = sm.Logit(y, X).fit(disp=0)
    return {"params": res.params.to_dict(), "pseudo_r2": float(res.prsquared)}


def moving_block_bootstrap_indices(n: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = -(-n // BLOCK_LEN)  # ceil
    starts = rng.integers(0, n - BLOCK_LEN + 1, size=n_blocks)
    idx = np.concatenate([np.arange(s, s + BLOCK_LEN) for s in starts])
    return idx[:n]


def bootstrap_ci(rows: pd.DataFrame, label: str, predictors: list[str],
                  kind: str, thresh: float | None, rng: np.random.Generator) -> dict:
    """90% CI for each coefficient via moving-block bootstrap. Returns
    {param_name: [lo, hi]}. Failed/non-converged replications are skipped."""
    n = len(rows)
    boot_params = {p: [] for p in (["Intercept"] + predictors if kind != "logit" else ["const"] + predictors)}
    n_ok = 0
    for _ in range(N_BOOT):
        idx = moving_block_bootstrap_indices(n, rng)
        sample = rows.iloc[idx].reset_index(drop=True)
        try:
            if kind == "quantreg":
                fit = fit_quantreg(sample, label, predictors)
            elif kind == "logit":
                fit = fit_logit(sample, label, predictors, thresh)
            else:
                raise ValueError(kind)
        except Exception:
            continue
        for p, v in fit["params"].items():
            boot_params[p].append(v)
        n_ok += 1
    ci = {}
    for p, vals in boot_params.items():
        if len(vals) < N_BOOT // 4:
            ci[p] = None  # too many failed fits to trust the CI
        else:
            ci[p] = [float(np.percentile(vals, 5)), float(np.percentile(vals, 95))]
    return {"ci_90": ci, "n_boot_ok": n_ok}


def run(replication: bool, skip_bootstrap: bool) -> dict:
    df = load_observables()
    rng = np.random.default_rng(RNG_SEED)
    out = {
        "replication": replication,
        "sample": (f"{REPLICATION_SAMPLE_START}-{REPLICATION_SAMPLE_END}" if replication
                   else "1965Q1-latest (expanding, 2020Q1-2020Q4 excluded both sides)"),
        "quantile": QUANTILE,
        "horizons": {},
    }
    for label in HORIZONS:
        rows = estimation_rows(df, label, replication)
        thresh = threshold_80th(rows, label)
        h_out = {
            "n_obs": len(rows),
            "sample_range": [rows.index.min(), rows.index.max()],
            "threshold_80pct": thresh,
            "full5_quantreg": fit_quantreg(rows, label, FULL5_VARS),
            "full5_ols": fit_ols(rows, label, FULL5_VARS),
            "full5_logit": fit_logit(rows, label, FULL5_VARS, thresh),
            "fin2_logit": fit_logit(rows, label, FIN2_VARS, thresh),
        }
        if not skip_bootstrap:
            h_out["full5_quantreg"]["ci_90"] = bootstrap_ci(
                rows, label, FULL5_VARS, "quantreg", None, rng)["ci_90"]
            h_out["full5_logit"]["ci_90"] = bootstrap_ci(
                rows, label, FULL5_VARS, "logit", thresh, rng)["ci_90"]
            h_out["fin2_logit"]["ci_90"] = bootstrap_ci(
                rows, label, FIN2_VARS, "logit", thresh, rng)["ci_90"]
        out["horizons"][label] = h_out
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replication", action="store_true",
                         help="Fixed 1965:Q1-2019:Q4 sample matching the papers exactly.")
    parser.add_argument("--force", action="store_true", help="rebuild even if up to date")
    parser.add_argument("--skip-bootstrap", action="store_true",
                         help="Skip bootstrap CIs (faster, for dev iteration).")
    args = parser.parse_args()

    out_path = REPLICATION_OUT_PATH if args.replication else OUT_PATH
    if out_path.exists() and not args.force:
        if out_path.stat().st_mtime > OBS_PATH.stat().st_mtime:
            print(f"{out_path} is newer than {OBS_PATH.name}, skipping (use --force to rebuild)")
            return

    result = run(args.replication, args.skip_bootstrap)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out_path}")
    for label, h in result["horizons"].items():
        print(f"\n{label}: n={h['n_obs']} range={h['sample_range']} threshold={h['threshold_80pct']:.3f}")
        print(f"  full5 quantreg params: { {k: round(v, 3) for k, v in h['full5_quantreg']['params'].items()} }")
        print(f"  full5 logit params:    { {k: round(v, 3) for k, v in h['full5_logit']['params'].items()} }")
        print(f"  fin2  logit params:    { {k: round(v, 3) for k, v in h['fin2_logit']['params'].items()} }")


if __name__ == "__main__":
    main()
