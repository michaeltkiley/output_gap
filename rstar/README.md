# rstar — Equilibrium Real Interest Rate Model

**Data pipeline built and validated.** Mirrors `../edo/`'s structure and
replication-vs-current-analysis pattern.

Semi-structural Kalman-filter model of the equilibrium real interest rate
(r*), following Kiley, M. T., "What Can the Data Tell Us about the
Equilibrium Real Interest Rate?", *International Journal of Central
Banking* (`docs/kiley_2020_equilibrium_real_rate.pdf`; an earlier draft
is at `docs/kiley_rstar_draft_v6.pdf`). Also produces an auxiliary output
gap and trend growth estimate. Much smaller than EDO -- 15 state
variables, 6 observables -- so full MCMC is tractable here in a way it
wasn't for EDO, but regular re-estimation still uses posterior mode only
(see "Estimation approach").

**Validation:** r* comes out at **0.81% (2026:Q2, current-analysis)** and
**0.85% (2017:Q4, replication)** -- both land right on the paper's own
stated finding, "estimates of r* show a gradual decline to a value below
1 percent in recent years."

## Pipeline

1. `scripts/ingest_fred.py` -- FRED: GDPC1, CNP16OV, UNRATE, PCEPILFE,
   FEDFUNDS -> `data/fred.duckdb`.
2. `scripts/ingest_spf.py` -- Philadelphia Fed: SPF median 10-year CPI
   forecast (the live half of `ptr`) -> `data/*_spf_cpi10.csv`.
3. `scripts/build_observables.py` -- builds `data/observables.csv` (or,
   with `--replication`, `data/observables_replication.csv` truncated to
   2017:Q4). See its module docstring for the exact transform/units of
   each of the 6 observables, verified against the original replication
   package's `rstardata.mat`.
4. `models/rg_base_final.mod` -- Dynare model, posterior-mode-only
   estimation (`mode_compute=5, mh_replic=0`) against
   `data/observables.csv`. `models/rg_base_final_replication.mod` is the
   same file pointed at `data/observables_replication.csv`
   (`scripts/run_replication.m` runs it end to end).
5. `scripts/export_results.m` -- pulls `tr`/`yU`/`uU`/`tg` out of `oo_`,
   reconstructs r* = `tr + mean(rff - dp)` (both smoothed/two-sided and
   filtered/one-sided), writes `outputs/rstar.csv` (or
   `outputs/rstar_replication.csv`) + a manifest. `yU` is the output gap;
   `uU` is a *separate* unemployment gap derived from `yU` via Okun's
   law -- easy to mix up (I did, the first time), see "Data notes".
   `mean(rff - dp)` -- the average *realized* real fed funds rate added
   to the stochastic trend `tr` (which Dynare pins near 0 at the start of
   the sample) -- is computed over a **fixed window, 1960:Q1-2007:Q4**
   (`RSTAR_CONST_SAMPLE_START`/`_END` in `export_results.m`), an explicit
   user choice made 2026-08-28: pre-financial-crisis/pre-ZLB, so the
   2008-15 and 2020-21 near-zero-rate years don't pull the constant down
   as the current-analysis sample keeps expanding with each update. This
   replaced an earlier version that averaged over the *entire* available
   sample (1960:Q1 through the latest quarter) -- that version's constant
   was 1.6112pp; the fixed-window constant is 2.5226pp, which shifts the
   whole r* series up by about 0.9pp uniformly (the trend `tr` itself is
   completely unchanged -- only the additive constant moved). Both
   `rff_mean`/`dp_mean` and the fixed window bounds are written to
   `outputs/manifest.json` on every run for a transparent audit trail.
   `export_results.m` also copies the freshly-found posterior mode
   (`<model>/Output/<model>_mode.mat`) to `models/rg_base_final_mode.mat`
   at the end of every run, so the *next* run's `mode_file=` option (in
   both `.mod` files) warm-starts from the most recent mode instead of
   whatever mode happened to exist the first time that file was created
   -- fixed 2026-08-28 (it was silently stale before). In practice this
   didn't change wall-clock time for this model (~2m23s either way, all
   three runs on 2026-08-28) -- Dynare's fixed overhead (steady state,
   symbolic Jacobians, the smoother, variance decomposition) dominates
   for a model this small, not optimizer iteration count -- but it's a
   correctness improvement regardless (a consistent, closer starting
   point) and may matter more after a larger data revision someday.

Local testing follows the same podman/Debian-container pattern as
`../edo/` -- see `../edo/README.md` "Local testing" for the image setup;
run `octave --no-gui --eval "dynare rg_base_final.mod noclearall; run('../scripts/export_results.m');"`
from within `models/` (or `run_replication.m` for the replication mode).

## Estimation approach

`rg_base_final.mod` is the author's own "base" config from the original
replication package -- posterior mode only (`mh_replic=0`), not a
simplification invented for this project. `rg_base_final_mcmc.mod` (full
500,000-draw MCMC, the paper's actual published results) and
`_robust1`/`_robust2.mod` (the paper's own prior-sensitivity checks) are
kept for reference but aren't part of the regular pipeline -- the model
is small enough (15 variables) that MCMC is computationally tractable,
just unnecessary for regular monitoring updates.

**Unlike EDO, this model is meant to be re-estimated (posterior mode)
each regular update**, not run with fixed parameters -- r* is understood
to genuinely evolve, and re-optimizing the mode each time (rather than
smoothing at fixed historical parameters) is standard practice for this
literature.

## Uncertainty

`rg_base_final.mod`'s `estimation(...)` command includes
`smoothed_state_uncertainty`, which turns on Dynare's standard Kalman/
Rauch-Tung-Striebel smoother covariance (`oo_.Smoother.State_uncertainty`)
-- a normal byproduct of linear-Gaussian state-space smoothing, available
at a single fixed parameter vector (the posterior mode) with **no MCMC
required**. Confirmed by direct testing: added ~6 seconds to a ~2m20s
run. `export_results.m` exports it as a &plusmn;1 std dev band around the
smoothed (two-sided) output gap and r* (r*'s variance equals `tr`'s
directly, since r* = tr + a constant).

**This is filtering/smoothing uncertainty only, conditional on the point-
-estimated parameters** -- it does not include parameter uncertainty
(how much the estimate would move if `rhoy1`, `uy`, etc. were themselves
uncertain), so it understates the gap's true uncertainty. That's a
deliberate scope choice, not an oversight: the cheap version of parameter
uncertainty (`oo_.posterior_std_at_mode`, Hessian-based asymptotic
std errors, also free from mode-finding, also confirmed working) doesn't
combine cleanly with the state uncertainty into one band without either a
delta-method approximation or actual MCMC draws (`rg_base_final_mcmc.mod`,
untested runtime, likely tens of minutes at least) -- not attempted here.
No band exists for the one-sided/filtered series; `State_uncertainty` is
smoothed-only. CBO and EDO don't publish or produce a comparable
uncertainty measure for their estimates.

## Data notes

- **Long-run inflation expectations (`ptr`)**: the frozen Hoey/Barclays
  de Zoete Wedd Decision-Makers Poll splice (`scripts/hoey_bzw_ltinf_1960q1_1991q3.csv` --
  that survey is defunct, so this series is fixed, not refetched) through
  1991:Q3, then the Philadelphia Fed
  SPF's median 10-year CPI forecast from 1991:Q4 on, fetched live each
  run. The two sources meet exactly at the boundary (both give
  1991:Q4 = 4.0). Genuinely missing quarters in the Hoey/BZW era are left
  as NaN, not interpolated -- Dynare's Kalman filter handles missing
  observations natively.
- **Sample start**: 1960:Q1, matching "My estimation sample spans from
  1960:Q1 to 2017:Q4" in the published paper.
- **`dp` (core PCE inflation)**: cross-checked against the original
  paper's own data and carries a modest (~0.2-0.3pp), non-systematic
  residual not fully explained by data-vintage drift -- likely a
  differing quarterly-averaging convention for a price index. Flagged
  in `build_observables.py`'s docstring, not resolved.
- **Data vintage**: latest-revised FRED data throughout, matching EDO's
  choice (confirmed with the user 2026-08-28), not real-time (ALFRED)
  vintages.
- **A real Octave gotcha, in case it recurs**: `strsplit(line, ',')`
  collapses consecutive delimiters by default, silently shifting every
  column after an empty field (`ptr` is frequently empty). Always pass
  `'CollapseDelimiters', false`. Found by comparing a manual CSV parse
  against an independent Python read of the same file -- worth doing
  that cross-check again if a future manual parse looks off.
- **`nanmean` is unreliable in this environment**: either undefined, or
  (when Dynare's own path is loaded) resolves to some other function
  entirely -- confirmed by direct testing, not just suspicion. Use an
  explicit `isnan`-filtered `sum/numel` instead.
- **`yU` is the output gap; `uU` is the unemployment gap** -- easy to
  mix up given the naming, and this project did the first time (an
  earlier version of `outputs/rstar.csv` had `uU` mislabeled as
  "output_gap"). `yU` drives `yobs = t1 + yU` directly; `uU` is derived
  from `yU` via Okun's law (`uU = uy*distributed_lag(yU)`) and feeds
  `lur = uU + t3`. Both are exported, correctly labeled. Also note: the
  original replication's `estimation(...)` command only listed
  `uU tr tg` for one-sided (filtered) output -- `yU` had to be added to
  that list to get a one-sided output gap at all.
