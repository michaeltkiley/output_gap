#!/usr/bin/env python3
"""Verify the replication pipeline against values reported in the source
papers. Runs 01_build_observables.py + 02_estimate.py --replication if
needed, then compares computed coefficients/thresholds/marginal effects to
the PAPER_* constants below, reporting OK/MISMATCH per value.

PAPER_* constants are transcribed directly from:
  - Kiley (2021), "Unemployment Risk", JMCB 54(5), Table 1 (quantile
    regression and least-squares columns) and Section 1.2/2.2 (the two
    unconditional 80th-percentile thresholds).
  - The FEDS Note companion piece (docs/kiley_2022_feds_notes_recession_risk.html),
    Table A, column (1) -- the financial-variables-only logit, the one
    published spec that matches our fin2 model exactly (same 2 predictors,
    same 1965:Q1-2019:Q4 sample, same 4-quarter horizon).

The papers report values to 2 decimal places and their own sample reflects
a data vintage from ~2019-2022; ours re-pulls the latest-revised FRED/BIS
data today, so exact matches aren't expected -- tolerances below are set
to flag genuine discrepancies (wrong sign, wrong order of magnitude, wrong
variable) while tolerating the level of drift already seen from data
revisions in ../edo and ../rstar.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
OBS_PATH = REPO_ROOT / "data" / "observables.csv"

# --- PAPER_* constants -------------------------------------------------

PAPER_THRESHOLD_H4 = 0.75    # "3/4 percentage point" (4-quarter horizon)
PAPER_THRESHOLD_H12 = 1.9    # "1.9 percentage points" (12-quarter horizon)

# Table 1: QU_0.80(t+h) quantile regression, {a1..a5}, R2
PAPER_QUANTREG_H4 = {"unrate": -0.12, "infl4q": 0.26, "credit_gr16q": 0.16,
                      "bond_spread": 0.62, "term_spread": -0.23}
PAPER_QUANTREG_H4_R2 = 0.38
PAPER_QUANTREG_H12 = {"unrate": -0.68, "infl4q": 0.45, "credit_gr16q": 0.39,
                       "bond_spread": 0.55, "term_spread": -0.10}
PAPER_QUANTREG_H12_R2 = 0.43

# Table 1: E{U(t+h)} least squares, {a1..a5}, R2
PAPER_OLS_H4 = {"unrate": -0.48, "infl4q": 0.15, "credit_gr16q": 0.07,
                "bond_spread": 0.57, "term_spread": -0.23}
PAPER_OLS_H4_R2 = 0.25
PAPER_OLS_H12 = {"unrate": -0.79, "infl4q": 0.31, "credit_gr16q": 0.22,
                  "bond_spread": 0.49, "term_spread": -0.20}
PAPER_OLS_H12_R2 = 0.61

# FEDS Note Table A, column (1): financial-only logit marginal effects
# (1-sd scaled), h=4, pseudo-R2
PAPER_FIN2_LOGIT_ME_H4 = {"bond_spread": 0.10, "term_spread": -0.22}
PAPER_FIN2_LOGIT_PSEUDO_R2_H4 = 0.38

TOL_COEF = 0.15
TOL_THRESHOLD = 0.30
TOL_R2 = 0.10
TOL_ME = 0.05


def check(label: str, computed: float, paper: float, tol: float) -> bool:
    ok = abs(computed - paper) <= tol
    status = "OK     " if ok else "MISMATCH"
    print(f"  {status} {label:28s} computed={computed:+.3f}  paper={paper:+.3f}  "
          f"diff={computed - paper:+.3f}  (tol={tol})")
    return ok


def check_dict(prefix: str, computed: dict, paper: dict, tol: float) -> bool:
    all_ok = True
    for k, v in paper.items():
        all_ok &= check(f"{prefix}.{k}", computed[k], v, tol)
    return all_ok


def logit_marginal_effects(res, X: pd.DataFrame, predictors: list[str]) -> dict:
    xbar = X.mean().to_frame().T
    phat = float(res.predict(xbar).iloc[0])
    dens = phat * (1 - phat)
    return {v: float(res.params[v] * dens * X[v].std()) for v in predictors}


def main():
    if not OBS_PATH.exists():
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "01_build_observables.py")], check=True)
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "02_estimate.py"),
                     "--replication", "--skip-bootstrap", "--force"], check=True)

    import importlib.util
    spec = importlib.util.spec_from_file_location("est02", SCRIPTS_DIR / "02_estimate.py")
    est = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(est)

    df = est.load_observables()
    all_ok = True

    for label, paper_thresh, paper_qr, paper_qr_r2, paper_ols, paper_ols_r2 in [
        ("h4", PAPER_THRESHOLD_H4, PAPER_QUANTREG_H4, PAPER_QUANTREG_H4_R2,
         PAPER_OLS_H4, PAPER_OLS_H4_R2),
        ("h12", PAPER_THRESHOLD_H12, PAPER_QUANTREG_H12, PAPER_QUANTREG_H12_R2,
         PAPER_OLS_H12, PAPER_OLS_H12_R2),
    ]:
        print(f"\n=== {label} ({est.HORIZONS[label]} quarters ahead) ===")
        rows = est.estimation_rows(df, label, replication=True)
        thresh = est.threshold_80th(rows, label)
        all_ok &= check(f"{label}.threshold_80pct", thresh, paper_thresh, TOL_THRESHOLD)

        qr = est.fit_quantreg(rows, label, est.FULL5_VARS)
        all_ok &= check_dict(f"{label}.quantreg", qr["params"], paper_qr, TOL_COEF)
        all_ok &= check(f"{label}.quantreg.pseudo_r2", qr["pseudo_r2"], paper_qr_r2, TOL_R2)

        ols = est.fit_ols(rows, label, est.FULL5_VARS)
        all_ok &= check_dict(f"{label}.ols", ols["params"], paper_ols, TOL_COEF)
        all_ok &= check(f"{label}.ols.r2", ols["r2"], paper_ols_r2, TOL_R2)

    print(f"\n=== h4 fin2 logit marginal effects vs FEDS Note Table A col.(1) ===")
    rows = est.estimation_rows(df, "h4", replication=True)
    thresh = est.threshold_80th(rows, "h4")
    y = (rows["du_h4"] >= thresh).astype(int)
    X = sm.add_constant(rows[est.FIN2_VARS])
    res = sm.Logit(y, X).fit(disp=0)
    me = logit_marginal_effects(res, X, est.FIN2_VARS)
    all_ok &= check_dict("h4.fin2_logit.me", me, PAPER_FIN2_LOGIT_ME_H4, TOL_ME)
    all_ok &= check("h4.fin2_logit.pseudo_r2", res.prsquared, PAPER_FIN2_LOGIT_PSEUDO_R2_H4, TOL_R2)

    print(f"\n{'ALL CHECKS OK' if all_ok else 'SOME CHECKS MISMATCHED'} "
          f"(sample: {rows.index.min()}..{rows.index.max()}, "
          f"today's FRED/BIS vintage vs. the papers' own ~2019-2022 vintage)")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
