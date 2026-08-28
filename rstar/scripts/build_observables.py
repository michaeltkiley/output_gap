#!/usr/bin/env python3
"""Build the 6 r* model observables from raw FRED/SPF data.

Reads data/fred.duckdb (ingest_fred.py) + the latest data/*_spf_cpi10.csv
(ingest_spf.py) + the frozen hoey_bzw_ltinf_1960q1_1991q3.csv, and writes
data/observables.csv: one row per quarter, one column per observable, in
the units models/rg_base_final.mod's equations expect (verified against
the original replication package's rstardata.mat -- see rstar/README.md):

  dyobs  4*100*ln((GDP_t/POP_t)/(GDP_{t-1}/POP_{t-1}))  -- annualized
         per-capita real GDP growth, percent.
  lur    UNRATE, quarterly average, percent, raw level (not logged --
         the model's own `lur = uU + t3` equation is additive).
  dp     4*100*ln(PCEPILFE_t/PCEPILFE_{t-1}), quarterly average basis --
         annualized core PCE inflation, percent. Cross-checked against
         rstardata.mat: matches other series closely but carries a modest
         (~0.2-0.3pp), non-systematic residual likely from a differing
         quarterly-averaging convention for a price index -- flagged, not
         resolved; see the sanity_check() output.
  ptr    Long-run inflation expectations, percent, raw level: the frozen
         Hoey/Barclays de Zoete Wedd Decision-Makers Poll splice through
         1991:Q3, then the Philadelphia Fed SPF median 10-year CPI
         forecast (CPI10) from 1991:Q4 on -- the exact date the public
         SPF series begins (confirmed: both sources give 1991:Q4=4.0).
         Genuinely missing quarters in the Hoey/BZW era are left NaN, not
         interpolated -- Dynare's Kalman filter handles missing
         observations natively.
  rff    FEDFUNDS, quarterly average, percent, raw level.
  tr     Not real data. A pure-random-walk state in the model
         (`tr = tr(-1) + e_tr`) with no separate steady-state anchor; the
         original replication pins its level by setting the first 5
         observations to 0 and everything else to missing, then
         reconstructs the actual r* series afterward as
         `tr + mean(rff - dp)` (see run_replication.m / export_results.m).
         Reproduced exactly here, not reinterpreted.

Sample starts 1960:Q1, matching "My estimation sample spans from 1960:Q1
to 2017:Q4" in Kiley, M.T., "What Can the Data Tell Us about the
Equilibrium Real Interest Rate?", IJCB (docs/kiley_2020_equilibrium_real_rate.pdf).
Runs through the latest quarter with complete data (current-analysis
default); --replication truncates to 2017:Q4 to match the paper exactly.
"""
import argparse
import glob
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "fred.duckdb"
OUT_PATH = REPO_ROOT / "data" / "observables.csv"
HOEY_BZW_PATH = REPO_ROOT / "scripts" / "hoey_bzw_ltinf_1960q1_1991q3.csv"

SAMPLE_START = "1960-01-01"
REPLICATION_SAMPLE_END = "2017-10-01"  # 2017:Q4
TR_INIT_QUARTERS = 5  # first 5 obs of tr fixed at 0, matching data_create.m


def load_wide(con):
    df = con.execute("SELECT series_id, obs_date, value FROM fred_raw").fetchdf()
    wide = df.pivot(index="obs_date", columns="series_id", values="value")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def to_quarterly_mean(monthly: pd.Series) -> pd.Series:
    return monthly.resample("QS").mean()


def log_growth_annualized_pct(level: pd.Series) -> pd.Series:
    return 4 * 100 * np.log(level / level.shift(1))


def latest_spf_file() -> Path:
    candidates = sorted(glob.glob(str(REPO_ROOT / "data" / "*_spf_cpi10.csv")))
    if not candidates:
        raise SystemExit("No SPF data found -- run ingest_spf.py first")
    return Path(candidates[-1])


def quarter_label_to_date(label: str) -> pd.Timestamp:
    y, q = int(label[:4]), int(label[5])
    month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
    return pd.Timestamp(year=y, month=month, day=1)


def build_ptr() -> pd.Series:
    hoey = pd.read_csv(HOEY_BZW_PATH)
    hoey["date"] = hoey["date"].apply(quarter_label_to_date)
    hoey = hoey.set_index("date")["ptr"]

    spf = pd.read_csv(latest_spf_file())
    spf["date"] = spf["date"].apply(quarter_label_to_date)
    spf = spf.set_index("date")["ptr"]

    return pd.concat([hoey, spf[~spf.index.isin(hoey.index)]]).sort_index()


def build(con, sample_end: str | None) -> pd.DataFrame:
    w = load_wide(con)

    monthly_q = pd.DataFrame(
        {
            "UNRATE": to_quarterly_mean(w["UNRATE"]),
            "FEDFUNDS": to_quarterly_mean(w["FEDFUNDS"]),
            "PCEPILFE": to_quarterly_mean(w["PCEPILFE"]),
            "CNP16OV": to_quarterly_mean(w["CNP16OV"]),
        }
    )
    gdp = w["GDPC1"].dropna()

    per_capita_gdp = gdp / monthly_q["CNP16OV"].reindex(gdp.index)

    obs = pd.DataFrame(index=w.index)
    obs["dyobs"] = log_growth_annualized_pct(per_capita_gdp)
    obs["lur"] = monthly_q["UNRATE"]
    obs["dp"] = log_growth_annualized_pct(monthly_q["PCEPILFE"])
    obs["rff"] = monthly_q["FEDFUNDS"]

    ptr = build_ptr()
    obs["ptr"] = ptr.reindex(obs.index)

    obs = obs.loc[SAMPLE_START:]
    if sample_end:
        obs = obs.loc[:sample_end]
    obs = obs.dropna(how="all")
    last_complete = obs[["dyobs", "lur", "dp", "rff"]].dropna().index.max()
    obs = obs.loc[:last_complete]

    # tr: synthetic initialization series, not real data (see module docstring).
    tr = pd.Series(np.nan, index=obs.index)
    tr.iloc[:TR_INIT_QUARTERS] = 0.0
    obs["tr"] = tr

    return obs[["dyobs", "lur", "dp", "ptr", "rff", "tr"]]


def sanity_check(obs: pd.DataFrame):
    print("\nSanity summary:")
    print(f"{'series':8s} {'n':>5s} {'n_nan':>6s} {'mean':>8s} {'std':>8s} {'min':>8s} {'max':>8s}")
    for col in obs.columns:
        s = obs[col]
        print(f"{col:8s} {len(s):5d} {s.isna().sum():6d} {s.mean():8.3f} {s.std():8.3f} "
              f"{s.min():8.3f} {s.max():8.3f}")
    checks = {
        "dyobs": (obs["dyobs"].mean(), -1.0, 4.0),
        "lur": (obs["lur"].mean(), 3.0, 8.0),
        "dp": (obs["dp"].mean(), 0.0, 5.0),
        "rff": (obs["rff"].mean(), 0.0, 8.0),
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
        help="Truncate to 2017:Q4, matching the paper's estimation sample exactly. "
             "Writes to data/observables_replication.csv instead of the default file.",
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
    obs = build(con, sample_end=REPLICATION_SAMPLE_END if args.replication else None)
    con.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = obs.reset_index().rename(columns={"obs_date": "date"})
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
