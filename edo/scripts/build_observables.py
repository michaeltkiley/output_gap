#!/usr/bin/env python3
"""Build the 13 EDO model observables from raw FRED data.

Reads data/fred.duckdb (populated by ingest_fred.py) and writes
data/observables.csv: one row per quarter, one column per *_obs series,
in exactly the units the model's measurement equations expect (see
models/linearized.mod lines ~233-245 and models/linearized_steadystate.m
lines ~139-150): each series is a quarterly log-difference (or log-level
for unemp/AH), expressed in percent (i.e. 100 * ln ratio).

Sample starts 1984-Q4, matching the estimation sample in Kiley (2013),
"Output gaps" (docs/kiley_2013_output_gaps.pdf), and runs through the
latest quarter with complete data.

Two modes:
  (default)       Current-analysis default: every observable is
                   HP-detrended (lambda=128000) and re-anchored to the
                   model's fixed SS constant before being fed to the
                   smoother, so trend growth/inflation/the natural rate of
                   unemployment/trend hours are all allowed to drift
                   instead of being pinned to their 1984:Q4-2011:Q4
                   estimation-sample averages. Adopted because, 15 years
                   past the end of the estimation sample, that fixed-trend
                   assumption increasingly conflates low-frequency drift
                   the model was never built to capture with the
                   business-cycle gap it's meant to measure -- this
                   treatment lets EDO focus on the latter for regular
                   monitoring. Writes data/observables.csv.
  --replication    Reproduces the original Kiley (2013)/EDO replication
                   exactly: raw (undetrended) growth rates and log
                   unemployment rate, and the paper's own padding +
                   lambda=6400 hours treatment (footnote 7). This is the
                   validated proof-of-concept baseline, not the ongoing
                   default -- kept reproducible as a reference point, not
                   because it's expected to be rerun regularly. Writes
                   data/observables_replication.csv.
"""
import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from statsmodels.tsa.filters.hp_filter import hpfilter

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "fred.duckdb"
OUT_PATH = REPO_ROOT / "data" / "observables.csv"

SAMPLE_START = "1984-10-01"  # 1984:Q4, per Kiley (2013) Section on data

# Padding/HP-filter treatment of hours, per Kiley (2013) footnote 7:
# pad 40 quarters approaching the trailing 40-quarter mean at 5%/quarter,
# then HP filter (lambda=6400) the padded series, then trim the pad.
HOURS_PAD_QUARTERS = 40
HOURS_PAD_APPROACH_RATE = 0.05
HOURS_HP_LAMBDA = 6400

# Unemployment: log(UNRATE) is HP-detrended (lambda=128000, a slow-moving
# trend rather than a business-cycle one) instead of compared to the
# model's fixed unempSS=0.06 calibration -- the natural rate has plausibly
# drifted since the 1984:Q4-2011:Q4 estimation sample, so anchoring every
# quarter to a constant 6% overstates/understates the labor-market gap in
# recent data. The detrended series is then re-anchored to unempSS so it
# still lines up with the model's `unemp_obs = unemp + unempSS_obs`
# measurement equation. unempSS is Dynare's actual solved steady-state
# value (models/linearized_steadystate.m), confirmed via M_.params to be
# exactly 0.06, not just the `.mod` file's initial calibration guess.
# Used in both modes -- even --replication keeps this off (see build()),
# this constant is just shared infrastructure.
UNEMPLOYMENT_HP_LAMBDA = 128000
UNEMPSS = 0.06

# --- Current-analysis default: same treatment applied to every observable ---
# For each series, HP-detrend (lambda=128000) whatever series is fed to
# that observable -- the growth-rate series itself for flow observables
# (letting trend growth/trend inflation/the neutral rate drift, the
# natural analogue of a drifting natural rate of unemployment), or the log
# level for AH (hours; this drops the paper's own padding+lambda=6400
# treatment, used only in --replication mode, in favor of the same
# uniform lambda=128000 used everywhere else) -- then re-anchor to the
# model's fixed SS_obs constant so the fed data's level still matches what
# each measurement equation expects. Constants pulled from Dynare's
# M_.params after `dynare linearized.mod noclearall`
# (models/linearized_steadystate.m lines ~139-150); AH has none because
# its measurement equation is bare (`AH_obs = AH`, no additive constant).
DETREND_ALL_LAMBDA = 128000
SS_OBS = {
    "DIFFREALGDP_obs": 0.5020141567,
    "DIFFREALEC_obs": 0.3393445328,
    "DIFFREALEIK_obs": 1.0206981084,
    "DIFFREALECD_obs": 1.0206981084,
    "DIFFREALECH_obs": 0.3393445328,
    "DIFFREALW_obs": 0.3393445328,
    "INFCNA_obs": 0.5000000000,
    "INFCOR_obs": 0.5000000000,
    "INFK_obs": -0.1246752706,
    "R_obs": 1.0341181455,
    "RT2_obs": 1.0648496365,
}


def hp_detrend_reanchor(series: pd.Series, ss_constant: float, lamb: int) -> pd.Series:
    """Generic version of unemployment_gap_pct: HP-detrend `series`
    (already in the units fed to the model) and re-anchor to `ss_constant`.
    """
    s = series.dropna()
    _, trend = hpfilter(s, lamb=lamb)
    return (s - trend) + ss_constant


def load_wide(con):
    df = con.execute("SELECT series_id, obs_date, value FROM fred_raw").fetchdf()
    wide = df.pivot(index="obs_date", columns="series_id", values="value")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def to_quarterly_mean(monthly: pd.Series) -> pd.Series:
    q = monthly.resample("QS").mean()
    return q


def log_growth_pct(level: pd.Series) -> pd.Series:
    """Quarter-over-quarter log growth, in percent.

    `level` must already be a clean quarterly-frequency series (no gaps
    from being read off a mixed monthly/quarterly wide table) -- callers
    should pass it through `.dropna()` first if it came from a column
    that's only populated at quarter starts.
    """
    return 100 * np.log(level / level.shift(1))


def quarterly_rate_to_log_pct(annual_pct: pd.Series) -> pd.Series:
    """Annualized simple rate (e.g. FEDFUNDS, in percent) -> 100*ln(1+i/4)."""
    return 100 * np.log(1 + (annual_pct / 100) / 4)


def unemployment_gap_pct(unrate_quarterly: pd.Series) -> pd.Series:
    """log(UNRATE/100), HP-detrended (long trend), re-anchored to unempSS.

    Filtered over the full available history (not just the output sample)
    so the trend estimate near 1984:Q4 isn't distorted by starting the
    filter there.
    """
    log_u = np.log(unrate_quarterly.dropna() / 100)
    _, trend = hpfilter(log_u, lamb=UNEMPLOYMENT_HP_LAMBDA)
    detrended = log_u - trend
    return 100 * (detrended + np.log(UNEMPSS))


def hours_gap_pct(hours_index: pd.Series) -> pd.Series:
    h = np.log(hours_index.dropna())
    target = h.iloc[-HOURS_PAD_QUARTERS:].mean()
    pad_dates = pd.date_range(
        h.index[-1] + pd.DateOffset(months=3), periods=HOURS_PAD_QUARTERS, freq="QS"
    )
    gap0 = h.iloc[-1] - target
    pad_values = target + gap0 * (1 - HOURS_PAD_APPROACH_RATE) ** np.arange(
        1, HOURS_PAD_QUARTERS + 1
    )
    padded = pd.concat([h, pd.Series(pad_values, index=pad_dates)])
    _, trend = hpfilter(padded, lamb=HOURS_HP_LAMBDA)
    trend = trend.loc[h.index]
    return 100 * (h - trend)


def build(con, replication: bool = False) -> pd.DataFrame:
    w = load_wide(con)

    monthly_q = pd.DataFrame(
        {
            "UNRATE": to_quarterly_mean(w["UNRATE"]),
            "FEDFUNDS": to_quarterly_mean(w["FEDFUNDS"]),
            "GS2": to_quarterly_mean(w["GS2"]),
            "PCEPI": to_quarterly_mean(w["PCEPI"]),
            "PCEPILFE": to_quarterly_mean(w["PCEPILFE"]),
        }
    )

    # Genuinely-quarterly source columns only have real values at
    # quarter-start months; drop the monthly gaps introduced by pivoting
    # them alongside monthly series, so shift(1) below means "previous
    # quarter" rather than "previous row".
    q = {
        name: w[name].dropna()
        for name in [
            "GDPC1", "DNDGRA3Q086SBEA", "PCNDGC96", "DSERRA3Q086SBEA",
            "PCESVC96", "DDURRA3Q086SBEA", "A008RA3Q086SBEA",
            "A011RA3Q086SBEA", "COMPNFB", "GDPDEF", "DDURRG3Q086SBEA",
        ]
    }

    # Nondurables+services real level: prefer actual chain-dollar sum
    # (available 2007+); extend back using the components' own long-history
    # chain-type quantity indexes, rescaled to dollars at the first
    # overlapping quarter (standard chain-linking practice).
    overlap = q["PCNDGC96"].index.min()
    scale_ndg = q["PCNDGC96"].loc[overlap] / q["DNDGRA3Q086SBEA"].loc[overlap]
    scale_svc = q["PCESVC96"].loc[overlap] / q["DSERRA3Q086SBEA"].loc[overlap]
    ndg_svc_from_index = (
        q["DNDGRA3Q086SBEA"] * scale_ndg + q["DSERRA3Q086SBEA"] * scale_svc
    )
    ndg_svc_actual = q["PCNDGC96"] + q["PCESVC96"]
    ndg_svc = ndg_svc_actual.combine_first(ndg_svc_from_index)

    real_wage = q["COMPNFB"] / q["GDPDEF"]

    obs = pd.DataFrame(index=w.index)
    obs["DIFFREALGDP_obs"] = log_growth_pct(q["GDPC1"])
    obs["DIFFREALEC_obs"] = log_growth_pct(ndg_svc)
    obs["DIFFREALEIK_obs"] = log_growth_pct(q["A008RA3Q086SBEA"])
    obs["DIFFREALECD_obs"] = log_growth_pct(q["DDURRA3Q086SBEA"])
    obs["DIFFREALECH_obs"] = log_growth_pct(q["A011RA3Q086SBEA"])
    obs["DIFFREALW_obs"] = log_growth_pct(real_wage)
    obs["INFCNA_obs"] = log_growth_pct(monthly_q["PCEPI"])
    obs["INFCOR_obs"] = log_growth_pct(monthly_q["PCEPILFE"])
    obs["INFK_obs"] = log_growth_pct(q["DDURRG3Q086SBEA"])
    obs["R_obs"] = quarterly_rate_to_log_pct(monthly_q["FEDFUNDS"])
    obs["RT2_obs"] = quarterly_rate_to_log_pct(monthly_q["GS2"])

    if replication:
        # Paper-exact: raw log unemployment rate compared to the model's
        # fixed unempSS via its own measurement equation, no detrending.
        obs["unemp_obs"] = 100 * np.log(monthly_q["UNRATE"] / 100)
        # Paper-exact hours treatment (Kiley 2013 footnote 7).
        obs["AH_obs"] = hours_gap_pct(w["HOANBS"])
    else:
        obs["unemp_obs"] = unemployment_gap_pct(w["UNRATE"].resample("QS").mean())
        # Growth/rate observables: re-detrend the already-constructed
        # series (each already computed above) and re-anchor to the
        # model's fixed constant.
        for name, ss in SS_OBS.items():
            obs[name] = hp_detrend_reanchor(obs[name], ss, DETREND_ALL_LAMBDA)
        # Hours: detrend the log level directly (no padding, no SS to
        # re-add), replacing the paper's padding+lambda=6400 treatment.
        log_h = np.log(w["HOANBS"].dropna())
        _, h_trend = hpfilter(log_h, lamb=DETREND_ALL_LAMBDA)
        obs["AH_obs"] = 100 * (log_h - h_trend)

    obs = obs.loc[SAMPLE_START:]
    obs = obs.dropna(how="all")
    last_complete = obs.dropna().index.max()
    obs = obs.loc[:last_complete]
    return obs


def sanity_check(obs: pd.DataFrame):
    print("\nSanity summary (1984:Q4-present, percent per quarter unless noted):")
    print(f"{'series':16s} {'mean':>8s} {'std':>8s} {'min':>8s} {'max':>8s}")
    for col in obs.columns:
        s = obs[col]
        print(f"{col:16s} {s.mean():8.3f} {s.std():8.3f} {s.min():8.3f} {s.max():8.3f}")
    # Rough plausibility bounds -- not exact paper targets (the paper does
    # not publish per-series sample means), just a check that nothing is
    # off by an order of magnitude or has the wrong sign.
    checks = {
        "DIFFREALGDP_obs": (obs["DIFFREALGDP_obs"].mean(), 0.0, 1.5),
        "INFCNA_obs": (obs["INFCNA_obs"].mean(), 0.0, 1.5),
        "unemp_obs": (obs["unemp_obs"].mean(), -320.0, -250.0),  # 100*ln(rate), rate in [4%,8%]
        "R_obs": (obs["R_obs"].mean(), 0.0, 2.0),
    }
    print("\nPlausibility bounds:")
    for name, (val, lo, hi) in checks.items():
        status = "OK" if lo <= val <= hi else "CHECK"
        print(f"  {status:5s} {name}: {val:.3f} (expected [{lo}, {hi}])")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even if up to date")
    parser.add_argument(
        "--replication", action="store_true",
        help="Reproduce the original Kiley (2013)/EDO replication exactly (no "
             "detrending beyond the paper's own hours treatment). Writes to "
             "data/observables_replication.csv instead of the default file.",
    )
    args = parser.parse_args()

    out_path = REPO_ROOT / "data" / "observables_replication.csv" if args.replication else OUT_PATH

    if out_path.exists() and not args.force:
        db_mtime = DB_PATH.stat().st_mtime
        out_mtime = out_path.stat().st_mtime
        if out_mtime > db_mtime:
            print(f"{out_path} is newer than {DB_PATH.name}, skipping (use --force to rebuild)")
            return

    con = duckdb.connect(str(DB_PATH), read_only=True)
    obs = build(con, replication=args.replication)
    con.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = obs.reset_index().rename(columns={"obs_date": "date"})
    # Dynare's dseries CSV reader expects "Variables ->" in the corner cell
    # and dates as e.g. "1984Q4" (see modules/reporting/test/db_q.csv in
    # the Dynare distribution).
    out["date"] = out["date"].dt.to_period("Q").astype(str)
    out.to_csv(out_path, index=False)
    with open(out_path) as f:
        content = f.read()
    content = content.replace("date,", "Variables ->,", 1)
    with open(out_path, "w") as f:
        f.write(content)
    print(f"Wrote {out_path} ({len(out)} quarters, {out['date'].iloc[0]}..{out['date'].iloc[-1]})")

    sanity_check(obs)


if __name__ == "__main__":
    main()
