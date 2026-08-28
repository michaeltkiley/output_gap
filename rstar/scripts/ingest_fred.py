#!/usr/bin/env python3
"""Pull raw FRED series used by the r* model into data/fred.duckdb.

Uses FRED's public fredgraph.csv endpoint (no API key required). Latest
revised vintage only -- matches the ../edo project's choice.
"""
import argparse
import csv
import io
import sys
from pathlib import Path

import duckdb
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "fred.duckdb"

# FRED series ID -> short local name.
FRED_SERIES = {
    "GDPC1": "real_gdp",
    "CNP16OV": "population_16_over",
    "UNRATE": "unemployment_rate",
    "PCEPILFE": "pce_core_price_index",
    "FEDFUNDS": "fed_funds_rate",
}

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch_series(series_id: str) -> list[tuple[str, float]]:
    resp = requests.get(FRED_CSV_URL.format(series_id=series_id), timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    header = next(reader)
    if len(header) != 2 or header[1] != series_id:
        raise ValueError(f"unexpected response for {series_id}: {resp.text[:200]!r}")
    rows = []
    for row in reader:
        if len(row) != 2:
            continue
        date, value = row
        if value in (".", ""):
            continue
        rows.append((date, float(value)))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="refetch even if already updated today"
    )
    args = parser.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS fred_raw (
            series_id VARCHAR,
            obs_date DATE,
            value DOUBLE,
            fetched_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (series_id, obs_date)
        )
        """
    )

    already_today = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT series_id FROM fred_raw WHERE fetched_at::DATE = current_date"
        ).fetchall()
    }

    for series_id, name in FRED_SERIES.items():
        if series_id in already_today and not args.force:
            print(f"skip  {series_id:12s} ({name}) -- already fetched today")
            continue
        try:
            rows = fetch_series(series_id)
        except Exception as e:
            print(f"FAIL  {series_id:12s} ({name}): {e}", file=sys.stderr)
            continue
        con.executemany(
            """
            INSERT INTO fred_raw (series_id, obs_date, value)
            VALUES (?, ?, ?)
            ON CONFLICT (series_id, obs_date) DO UPDATE SET
                value = excluded.value, fetched_at = now()
            """,
            [(series_id, d, v) for d, v in rows],
        )
        print(f"OK    {series_id:12s} ({name}): {len(rows)} obs, "
              f"{rows[0][0]}..{rows[-1][0]}")

    con.close()


if __name__ == "__main__":
    main()
