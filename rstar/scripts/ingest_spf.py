#!/usr/bin/env python3
"""Pull the Philadelphia Fed Survey of Professional Forecasters' median
10-year CPI inflation forecast (CPI10) -- the live half of the model's
long-run inflation expectations observable (`ptr`). The public series
starts exactly 1991:Q4; everything before that is the frozen Hoey/BZW
splice in hoey_bzw_ltinf_1960q1_1991q3.csv (see build_observables.py),
which is never refetched -- that survey is defunct.

Usage: python3 ingest_spf.py
"""
import io
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SPF_URL = (
    "https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/"
    "survey-of-professional-forecasters/data-files/files/median_cpi10_level.xlsx"
)


def main():
    resp = requests.get(SPF_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content))
    if not {"YEAR", "QUARTER", "CPI10"}.issubset(df.columns):
        sys.exit(f"Unexpected SPF file columns: {df.columns.tolist()}")

    df = df.dropna(subset=["CPI10"])
    df["date"] = df["YEAR"].astype(int).astype(str) + "Q" + df["QUARTER"].astype(int).astype(str)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / f"{date.today():%Y%m%d}_spf_cpi10.csv"
    df[["date", "CPI10"]].rename(columns={"CPI10": "ptr"}).to_csv(out_path, index=False)
    print(f"Wrote {out_path} ({len(df)} quarters, {df['date'].iloc[0]}..{df['date'].iloc[-1]})")


if __name__ == "__main__":
    main()
