# EDO output gap → auto-updating dashboard

One of (eventually) several output-gap approaches feeding a dashboard on
michaeltkiley.github.io. This one runs the Federal Reserve Board's EDO
model (Chung, Kiley & Laforte) at its published posterior-mode parameter
values and Kalman-smooths current FRED data through it each update, using
the model's `GAP` (Beveridge-Nelson) and `PFGAP` (production-function)
variables -- the same two concepts discussed in Kiley (2013), "Output
gaps" (`docs/kiley_2013_output_gaps.pdf`).

## Status

- **Replication (proof of concept): validated, complete.** Running the
  EDO replication-package parameters through `calib_smoother` against
  current FRED data reproduces sensible, business-cycle-consistent output
  gaps (e.g. sharply positive pre-2008, deeply negative at the 2009 and
  2020 troughs). Reproducible on demand via `--replication` (see below);
  not part of the regular pipeline.
- **Current-analysis default: every observable HP-detrended (see
  "Detrending approach" below).** The estimation sample ends 2011:Q4;
  15 years on, comparing current data to a fixed 1984:Q4-2011:Q4-average
  trend increasingly conflates low-frequency drift the model was never
  built to capture with the business-cycle gap it's meant to measure.
  Detrending every observable and re-anchoring to the model's own
  constants lets EDO focus on extracting the business-cycle signal for
  regular monitoring. This is what `data/observables.csv` /
  `outputs/output_gap.csv` contain by default, and what the scheduled
  GitHub Actions run produces.

## Pipeline

Four independently-rerunnable stages, in order:

1. `scripts/ingest_fred.py` -- pulls the 13 raw FRED series the model
   needs into `data/fred.duckdb` (idempotent; `--force` to refetch).
2. `scripts/build_observables.py` -- applies the exact transformations
   Kiley (2013) and the model's measurement equations expect (quarterly
   log growth rates, an HP-filtered hours trend, etc.) and writes
   `data/observables.csv`. Add `--replication` to instead write
   `data/observables_replication.csv`, the paper-exact construction (see
   "Detrending approach").
3. `models/linearized.mod` -- Dynare model file. Its final line runs
   `calib_smoother` against `data/observables.csv` at the fixed
   parameter values already in the file (no re-estimation; see
   "Estimation approach" below). `models/linearized_replication.mod` is
   the same file pointed at `data/observables_replication.csv` instead,
   for reproducing the replication reference (`scripts/run_replication.m`
   runs it end to end).
4. `scripts/export_results.m` -- pulls the smoothed `GAP`/`PFGAP` series
   out of Dynare's `oo_` structure and writes `outputs/output_gap.csv`
   + `outputs/manifest.json` for the website (or, for the replication
   run, `outputs/output_gap_replication.csv` +
   `..._replication_manifest.json`).

## Detrending approach

Every one of the 13 observables is HP-detrended (lambda=128000, a
slow-moving trend, not a business-cycle one) and re-anchored to the
model's own fixed steady-state constant before being fed to
`calib_smoother`: growth-rate observables (GDP, consumption, investment,
wages, inflation, ...) have their growth-rate series itself detrended,
letting trend growth/trend inflation/the neutral rate of interest drift
instead of assuming the 1984:Q4-2011:Q4 sample average holds forever;
unemployment and hours are detrended in logs and re-anchored the same
way. This replaces the paper's own hours-only padding+lambda=6400
treatment (footnote 7) with one uniform treatment applied everywhere.
Constants pulled from Dynare's actual solved `M_.params`, not read off
the `.mod`/`.m` source text (steady states can be recomputed by the
steady-state file at runtime). See `scripts/build_observables.py`'s
module docstring and inline comments for the exact formulas.

**Caveat worth keeping in mind:** letting every observable's trend drift
mechanically shrinks whatever gap the model recovers, since a flexible
enough trend absorbs persistent developments a fixed-parameter model
would otherwise call "gap." In practice this treatment also pulls the
`GAP`/`PFGAP` correlation up substantially (0.24 -> 0.94 in levels,
full sample) -- i.e. it narrows the distinction between the two gap
concepts, not just their levels. Worth an occasional gut-check against
the `--replication` baseline.

## Estimation approach

The `.mod` files ship with parameters already estimated (via MCMC) over
1984:Q4-2011:Q4. Every scheduled run just re-smooths at those fixed
values against updated data -- fast (~seconds), and avoids burning CI
minutes on MCMC.

## Data

`scripts/build_observables.py`'s module docstring and inline comments
document the FRED series and transformations used; the underlying
requirements come from Kiley (2013)'s data appendix and the model's own
`_obs` measurement equations (`models/linearized.mod` lines ~233-245,
`models/linearized_steadystate.m` lines ~139-150). Latest-revised FRED
data throughout, not real-time (ALFRED) vintages.

## Local testing

Dynare isn't packaged for Fedora, so local testing uses a throwaway
Debian container via `podman` (rootless, no sudo needed), since
Debian/Ubuntu package Dynare with working precompiled Octave bindings
directly -- this broadly matches what the GitHub Actions workflow does,
though the actual runner is Ubuntu (`ubuntu-latest`), not Debian bookworm
-- close enough for the apt-based install, but the two distros pull in
different JRE package versions (see "Known issues" below), so a fix
validated only in this Debian container isn't guaranteed to carry over
without checking.

```bash
podman build -t output-gap-dynare - <<'EOF'
FROM debian:bookworm
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    dynare octave octave-io ca-certificates python3 python3-pip python3-venv \
    && apt-get clean
# The dynare package pulls in a JRE for unused xls/reporting features.
# On some CPUs/runners its startup CPU-feature probing segfaults as soon
# as Dynare's estimation code loads -- remove it, we don't need it.
# Matched by glob, not a pinned version: the exact JRE differs by distro
# (Debian bookworm here pulls openjdk-17-jre; Ubuntu 24.04, what the
# actual GitHub Actions runner uses, pulls openjdk-21-jre instead -- see
# "Known issues" below).
RUN DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq default-jre \
    default-jre-headless 'openjdk-*-jre*' ant ant-optional \
    && apt-get autoremove -y -qq && apt-get clean
EOF

pip install -r scripts/requirements.txt   # or run this inside the container
python3 scripts/ingest_fred.py
python3 scripts/build_observables.py               # current-analysis default
python3 scripts/build_observables.py --replication # + the replication reference

podman run --rm -v "$(pwd)/models:/work/models:Z" -v "$(pwd)/data:/work/data:Z" \
  -v "$(pwd)/outputs:/work/outputs:Z" -v "$(pwd)/scripts:/work/scripts:Z" \
  -w /work/models output-gap-dynare \
  octave --no-gui --eval "dynare linearized.mod noclearall; run('../scripts/export_results.m');"

# replication reference:
podman run --rm -v "$(pwd)/models:/work/models:Z" -v "$(pwd)/data:/work/data:Z" \
  -v "$(pwd)/outputs:/work/outputs:Z" -v "$(pwd)/scripts:/work/scripts:Z" \
  -w /work/models output-gap-dynare \
  octave --no-gui ../scripts/run_replication.m
```

## Known issues / compatibility notes

- `models/linearized_steadystate.m` was written for Dynare 4 (2016) and
  needed two mechanical fixes for modern Dynare (5.3, current in Debian
  bookworm): the steady-state file calling convention changed (now
  `(ys, exo, M_, options)` returning `[ys, params, check]`, previously
  `(ys, exo)` returning `[ys, check]`), and `M_.param_names` changed from
  a padded char-matrix to a cell array. Both are fixed in the file as
  committed. `models/Dynare_edo.mod` / `Dynare_edo_steadystate.m`
  (the nonlinear, levels version) have **not** been updated and are not
  currently used by the pipeline.
- See "Local testing" above re: the Java/JVM segfault workaround --
  it's not optional, `calib_smoother` reliably crashes (SIGSEGV, exit
  139) without it in this environment. The exact JRE package to remove
  differs by distro -- Debian bookworm (the local podman container)
  pulls `openjdk-17-jre`; Ubuntu 24.04 (the actual `ubuntu-latest`
  GitHub Actions runner) pulls `openjdk-21-jre` instead. First deployed
  with only the 17 variant listed, which segfaulted in CI despite
  working locally; confirmed by reproducing the exact failure in a real
  `ubuntu:24.04` container (2026-08-28) and fixed by matching the
  removal with a glob (`'openjdk-*-jre*'`) instead of a pinned version.
  That still wasn't the whole story: even with the apt-installed JRE
  correctly removed, CI kept segfaulting. A `gdb`-captured backtrace
  (2026-08-28) landed in `/usr/lib/jvm/temurin-17-jdk-amd64/lib/server/
  libjvm.so`, `VM_Version::get_processor_features()` -- the exact same
  JVM CPU-feature-probing crash, but from a **different Java entirely**:
  `ubuntu-latest`'s runner image ships several pre-installed JDKs baked
  into `/usr/lib/jvm/` for language-toolchain support, unrelated to and
  untouched by `apt-get remove`. `octave-io` reaches for a system JVM
  via `JAVA_HOME` regardless of apt state (for its xlsx/POI support) and
  finds one of these. Not reproducible in a bare `ubuntu:24.04` podman
  container locally, since that image doesn't have this runner toolcache
  at all -- which is exactly why the apt-only fix looked sufficient
  locally but wasn't in CI. Fixed by deleting `/usr/lib/jvm/*` outright
  as a separate step, in addition to (not instead of) the apt removal.
