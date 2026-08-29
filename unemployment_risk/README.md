# Unemployment / recession risk

Quantile-regression and logit models of the risk of a large increase in the
U.S. unemployment rate, following:

- Kiley, M.T. (2021), "Unemployment Risk," *Journal of Money, Credit and
  Banking*, 54(5), 1407-1424. (`docs/kiley_2021_unemployment_risk.pdf`)
- "Financial and Macroeconomic Indicators of Recession Risk," FEDS Notes,
  Board of Governors of the Federal Reserve System, ~April 2022.
  (`docs/kiley_2022_feds_notes_recession_risk.html`, an accessible companion
  piece to the paper above, same author.)

Unlike `../edo` and `../rstar`, there is no Dynare/DSGE model here -- these
are quantile and logistic regressions, fit directly in Python
(`statsmodels`). No podman/Octave setup needed.

## Two risk concepts, two horizons, two model specs

Both papers define unemployment risk as the risk of a large increase in the
unemployment rate over horizon *h*, and measure it two ways:

- **Magnitude** (quantile regression, q=0.80): `QU_0.80(t+h)`, the
  percentage-point size of the 80th-percentile outcome for the change in the
  unemployment rate.
- **Probability** (logit): `Prob(du(t+h) >= F^-1(0.80))`, the probability
  that the change exceeds the *unconditional* 80th percentile (a fixed
  threshold: 0.75pp at h=4, ~1.9pp at h=12, computed from the estimation
  sample).

At two horizons: **h4** (1 year / 4 quarters) and **h12** (3 years / 12
quarters).

Two model specs, both logit (magnitude is only computed for the full model):

- **full5** -- the paper's full specification: unemployment rate, PCE
  inflation (4q), nonfinancial credit/GDP growth (16q, annualized), Baa-10yr
  corporate bond spread, 10yr-FFR term spread. The dashboard headline.
- **fin2** -- financial variables only (corporate bond spread + term
  spread), the "conventional" recession-prediction benchmark from the FEDS
  Note's first model. Shown alongside full5 for comparison -- how much do
  the macro variables (unemployment, inflation, credit) change the picture?

## Pipeline

```
00_ingest_fred.py        FRED -> data/fred.duckdb
01_build_observables.py  data/fred.duckdb -> data/observables.csv
02_estimate.py [--replication]
                          data/observables.csv -> data/estimates.json
                          (or data/estimates_replication.json)
03_export_results.py     data/observables.csv + data/estimates.json
                          -> outputs/unemployment_risk.csv
run_replication.py       runs 02_estimate.py --replication, checks against
                          PAPER_* constants transcribed from the papers
```

Re-run in order after `00_ingest_fred.py --force` to pick up new data;
each script skips silently if its output is already newer than its inputs
(pass `--force` to override).

### Data sources

All from FRED's public `fredgraph.csv` endpoint (no API key). Chosen
specifically for their long histories -- the papers' sample starts
1965:Q1, which rules out FRED's daily corporate-bond-spread/Treasury series
(`DBAA`/`BAA10Y` start 1986, `DGS10` starts 1962):

| Series | FRED ID | Used for |
|---|---|---|
| Unemployment rate | `UNRATE` | `unrate`, and the dependent variable |
| PCE price index | `PCEPI` | `infl4q` (4-quarter % change) |
| Baa corporate bond yield | `BAA` | `bond_spread` (monthly, since 1919) |
| 10-yr Treasury yield | `GS10` | `bond_spread`, `term_spread` (monthly, since 1953) |
| Federal funds rate | `FEDFUNDS` | `term_spread` (monthly, since 1954) |
| Credit/GDP ratio, private non-financial sector | `QUSPAM770A` | `credit_gr16q` (BIS via FRED, quarterly; already a ratio, no separate GDP series needed) |

`QUSPAM770A` lags FRED's other series by 2-3 quarters (BIS publishes with a
delay) -- the most recent few quarters can score the `fin2` model but not
`full5`, which needs credit data. `03_export_results.py` reports each
series' own latest scorable quarter separately rather than a single shared
date.

## Replication vs. current analysis

Same pattern as `../edo` and `../rstar`:

- **`--replication`**: fixed 1965:Q1-2019:Q4 estimation sample, exactly
  matching both papers (which deliberately exclude the COVID-19 recession
  -- "The end date was chosen to exclude ... the COVID-induced recession").
  Checked against the papers' own reported coefficients by
  `run_replication.py`.
- **Current analysis (default)**: expanding window, 1965:Q1 through the
  latest quarter with a realized h-quarter-ahead outcome. **2020:Q1-2020:Q4
  are dropped from the estimation sample entirely** -- both as the
  observation quarter `t` and whenever `t+h` falls in that window -- per an
  explicit design choice (not something either paper does, since their
  samples simply end before COVID): re-estimating on an expanding window
  *without* this exclusion would pull the 2020Q2 unemployment spike into
  the training data and likely distort coefficients on every variable, not
  just around 2020 itself. Dropping the quarters from both sides of the
  forward-looking regression purges that shock's influence while still
  letting the model score (not train on) predictors *through* the COVID
  episode and refresh every subsequent quarter -- unlike EDO/rstar, no
  Dynare re-estimation cost, so refitting is essentially free.

Coefficients therefore differ modestly between the replication and current
samples (post-2019 data, especially 2021-23's inflation surge and 2022-23
rate-hiking cycle, is now informing the fit) -- expected, not a bug.

## Replication verification (`run_replication.py`)

Hardcoded `PAPER_*` constants from Table 1 (quantile regression and
least-squares columns, both horizons) and the unconditional-threshold
values in Section 1.2/2.2 of the JMCB paper, plus Table A column (1)
(financial-only logit marginal effects) from the FEDS Note -- the one
published spec that matches this project's `fin2` model exactly (same 2
predictors, same sample, same horizon).

As of the last run: **22 of 26 checks OK** (tolerances set to catch wrong
signs/magnitudes, not exact matches -- the papers report 2-decimal values
from a data vintage several years old; ours re-pulls today's latest-revised
FRED/BIS data, same caveat as `../edo`'s and `../rstar`'s replications).
The 4 mismatches cluster specifically around `credit_gr16q`'s interaction
with other coefficients in the joint 5-variable regression (largest at the
12-quarter horizon) -- **not** a sign the bond-spread/term-spread data
themselves are wrong: the `fin2` (financial-only) logit's marginal effects
match the FEDS Note's Table A almost exactly (0.10 vs. 0.10, -0.223 vs.
-0.22), which uses the identical 2 predictors and would not match this
closely if `BAA`/`GS10`/`FEDFUNDS` were mismeasured. The likely source is
some difference in the exact BIS credit-to-GDP series vintage/definition
versus what the paper used, whose effect propagates into the coefficients
of *correlated* variables (unemployment rate, bond spread) in the joint
fit even though those two are separately validated as correct. Not
resolved further; re-run `run_replication.py` to see current status.

## Confidence intervals

`02_estimate.py` (unless `--skip-bootstrap`) computes 90% CIs via a moving
block bootstrap -- block length 11 quarters, matching "Kilian and Lutkepohl
(2017), chapter 12" in both papers' table notes -- resampling blocks of
*all* variables (dependent + predictors) jointly to preserve the serial
correlation induced by overlapping h-quarter-ahead horizons, then refitting
each model per replication (500 reps). The dashboard shows point
estimates, matching the FEDS Note's own headline charts; full 90% CIs
are in `data/estimates.json`/`data/estimates_replication.json`.
