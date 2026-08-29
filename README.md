# output_gap

Multiple structural approaches to estimating the U.S. output gap and the
equilibrium real interest rate, each independently pipelined, feeding two
public dashboards.

This repo is the **compute layer**: it holds the three models, runs
each on its own schedule, and commits fresh outputs. It does not serve
a webpage itself.

- **`edo/`** — the Federal Reserve Board's EDO model (Chung, Kiley &
  Laforte). Kalman-smooths current FRED data against fixed posterior-mode
  parameters. Produces the Beveridge-Nelson (`GAP`) and production-function
  (`PFGAP`) gaps discussed in Kiley (2013), "Output gaps." See
  `edo/README.md`.
- **`rstar/`** — Kiley's semi-structural equilibrium real interest rate
  (r*) model. Produces an r* estimate and an auxiliary output gap. See
  `rstar/README.md`.
- **`unemployment_risk/`** — quantile and logit models of the risk of a
  large increase in the unemployment rate, following Kiley (2021),
  "Unemployment Risk," and its FEDS Notes companion piece. No DSGE/Dynare
  here -- pure Python (`statsmodels`) regressions. See
  `unemployment_risk/README.md`.

Each model subdirectory is self-contained: its own `data/`, `scripts/`,
`models/` (or equivalent), and `outputs/`, independently rerunnable, with
its own `.gitignore` for regenerated files.

## The two public dashboards

`dashboard/` (Resource Utilization and Risk) and `equilibrium_rate/`
(Equilibrium Real Interest Rate) have graduated out of this repo into
their own top-level repos, matching `termprem`/`monetary_policy_surprises`'s
shape -- each with its own `docs/index.html` served via GitHub Pages:

- **`michaeltkiley/resource_utilization`** — reads `edo/outputs/output_gap.csv`,
  `rstar/outputs/rstar.csv`, and `unemployment_risk/outputs/unemployment_risk.csv`
  from this repo, plus its own live CBO fetch.
- **`michaeltkiley/equilibrium_rate`** — reads `rstar/outputs/rstar.csv`
  from this repo, plus its own live FRED/Laubach-Williams/SPF ingests.

This repo holds the model internals and data pipelines; the two page
repos only read its computed CSV outputs and don't carry any of the
underlying estimation code.

## Deployment

Each model's GitHub Actions workflow (`.github/workflows/*.yml`) runs on
its own schedule, commits its outputs back to this repo, then fires a
`repository_dispatch` at the relevant page repo(s) to trigger a rebuild:

| Workflow | Schedule | Commits | Dispatches to |
|---|---|---|---|
| `edo-output-gap.yml` | 1st of month, 13:17 UTC | `edo/` | `resource_utilization` |
| `rstar-output-gap.yml` | 1st of month, 13:23 UTC | `rstar/` | `resource_utilization`, `equilibrium_rate` |
| `unemployment-risk.yml` | 10th of month, 13:17 UTC | `unemployment_risk/` | `resource_utilization` |

All three also support `workflow_dispatch` (manual run from the Actions
tab) and re-run automatically on a `push` that touches their own
`models/`/`scripts/` paths.
