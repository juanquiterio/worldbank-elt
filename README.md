# World Bank Indicators: ELT Pipeline and Pipeline Health Monitor

A reproducible ELT pipeline over the World Bank public API (Python, dbt, DuckDB), served through a FastAPI backend and a plain HTML/CSS/JS frontend, plus an operational monitor that watches the pipeline's own runs and raises severity-ranked alerts.

This repository holds two portfolio projects that share one backend:

| Project | What it does | Entry points |
|---|---|---|
| **Economic Indicators ELT Pipeline** | Extracts six indicators for every country, models them with dbt, tests them and exports a static snapshot | `run_pipeline.py`, `frontend/index.html` |
| **Pipeline Health Monitor** | Records every pipeline run and evaluates failures, freshness, volume, coverage and null rates | `api/monitor.py`, `frontend/monitor.html` |

<!-- DEMO (uncomment when live)
- Indicators demo: https://worldbank-web.onrender.com/
- Health monitor demo: https://worldbank-web.onrender.com/monitor.html
- The demo runs on a free server that sleeps when idle. The first load can take 30-60 seconds.
-->

<!-- SCREENSHOTS (uncomment when they exist)
![Indicators ranking](docs/img/indicators.png)
![Pipeline health monitor](docs/img/monitor.png)
-->

<!-- VIDEO (uncomment when it exists)
Video walkthrough: UNLISTED_YOUTUBE_URL
-->

## Contents

1. [Problem](#problem)
2. [Solution](#solution)
3. [Architecture](#architecture)
4. [Project 1: ELT pipeline](#project-1-elt-pipeline)
5. [Project 3: Pipeline Health Monitor](#project-3-pipeline-health-monitor)
6. [API reference](#api-reference)
7. [Frontends](#frontends)
8. [Repository structure](#repository-structure)
9. [Run locally](#run-locally)
10. [Deployment](#deployment)
11. [Technical decisions](#technical-decisions)
12. [Challenges and learnings](#challenges-and-learnings)
13. [Limitations and next steps](#limitations-and-next-steps)
14. [Data and license](#data-and-license)

## Problem

Economic indicators are easy to download and easy to get wrong.

- **Mixed entities.** The World Bank API returns countries together with regional and income-group aggregates ("World", "Arab World", and so on). Summing or ranking without separating them double counts.
- **Not reproducible.** A one-off download in a notebook cannot be re-run, tested or compared with the previous version.
- **Silent failures.** If an upstream refresh returns fewer rows, a missing year or a column full of nulls, nothing tells you until someone notices a wrong chart.

## Solution

1. **Extract** six indicators for every country, 2000-2025, with pagination, timeouts and retries.
2. **Transform** with dbt on DuckDB: staging views, a wide mart with one row per country and year, and data tests.
3. **Export** a static JSON snapshot so the public demo never depends on live queries.
4. **Serve** the snapshot through a small read-only FastAPI backend.
5. **Monitor** each run: its status, per-stage durations, row and country counts, latest year and null percentage per indicator, compared against previous runs.

Current snapshot:

| Metric | Value |
|---|---|
| Countries (aggregates excluded) | 217 |
| Years | 2000-2025 |
| Country-year rows in the mart | 5,642 |
| Long-format observations in staging | 41,496 (6,916 per indicator) |
| dbt data tests | 5 |
| pytest tests (monitor) | 10 |
| Full pipeline run | about one minute on a 2-core, 4 GB machine |

## Architecture

```text
World Bank API
      |
      v
extract/worldbank_extract.py     6 indicators, paginated, retries    -> data/raw/*.json
extract/worldbank_countries.py   country metadata (region, income)   -> data/raw/countries.json
      |
      v
dbt + DuckDB (data/worldbank.duckdb)
  stg_indicators  (view)   long format, one row per country, indicator, year
  stg_countries   (view)   region, income level, is_aggregate flag
  fct_indicators_wide (table)  one row per country and year, countries only
      |
      v
run_pipeline.py
  runs the stages, then exports:
  data/exports/indicators_wide.json   (static snapshot served by the API)
  data/exports/pipeline_runs.json     (last 50 runs with metrics)
      |
      v
FastAPI (api/)  <--  frontend/index.html    (indicators)
                <--  frontend/monitor.html  (health monitor)
```

Layers and responsibilities:

| Layer | Responsibility | Where |
|---|---|---|
| Extract | Talk to the external API, retry, store raw JSON untouched | `extract/` |
| Transform | Clean, model and test | `dbt_project/` |
| Orchestrate | Run the stages in order, stop on failure, export, log the run | `run_pipeline.py` |
| Serve | Read-only access to snapshot and run history | `api/` |
| Monitor | Evaluate the run history and produce alerts | `api/monitor.py` |
| Present | Static pages that call the API | `frontend/` |

## Project 1: ELT pipeline

### Extraction

Six indicators are downloaded for every entity, 2000-2025:

| Indicator code | Column in the mart | Description |
|---|---|---|
| `NY.GDP.MKTP.CD` | `gdp_current_usd` | GDP (current US$) |
| `NY.GDP.PCAP.CD` | `gdp_per_capita_current_usd` | GDP per capita (current US$) |
| `FP.CPI.TOTL.ZG` | `inflation_cpi_pct` | Inflation, consumer prices (annual %) |
| `SP.POP.TOTL` | `population_total` | Population, total |
| `SL.UEM.TOTL.ZS` | `unemployment_pct` | Unemployment, total (% of labor force) |
| `SP.DYN.LE00.IN` | `life_expectancy_years` | Life expectancy at birth (years) |

Each indicator returns 6,916 records (266 entities x 26 years) in 7 pages of up to 1,000 records. Requests use a 30-second timeout and up to 3 attempts with increasing waits. A failed indicator is logged and counted, and the script exits with a non-zero code so the orchestrator can stop. A separate script downloads country metadata (296 entities).

### Transformation

| Model | Type | Grain | Purpose |
|---|---|---|---|
| `stg_indicators` | view | country, indicator, year | Unions the six JSON files with DuckDB `read_json_auto`, flattens nested fields and casts year and value |
| `stg_countries` | view | country | Region, income level, capital and an `is_aggregate` flag |
| `fct_indicators_wide` | table | country, year | Pivots the six indicators into columns and joins country attributes |

**Separating countries from aggregates.** The country metadata lists 296 entities: 217 countries and 79 aggregates. Aggregates have region id `NA`, and that flag is verified against the data rather than assumed. The mart keeps only countries, which is where the 217 comes from. Of the 5,642 mart rows (217 countries x 26 years), 214 have no GDP value.

### Data tests

Five dbt tests run on every pipeline execution:

| Test | Model and column | What it protects |
|---|---|---|
| `not_null` | `fct_indicators_wide.country_code` | No orphan rows after the join |
| `not_null` | `fct_indicators_wide.year` | Valid time axis |
| `not_null` | `fct_indicators_wide.region_name` | Every country has a region |
| `accepted_values` | `fct_indicators_wide.region_name` | Only the seven known regions (East Asia & Pacific, Europe & Central Asia, Latin America & Caribbean, Middle East, North Africa, Afghanistan & Pakistan, North America, South Asia, Sub-Saharan Africa) |
| singular test | `unique_country_year` | Exactly one row per country and year, so the pivot cannot duplicate rows |

### Orchestration

`run_pipeline.py` runs four stages in order and stops at the first failure:

`extract_indicators` -> `extract_countries` -> `dbt_run` -> `dbt_test`

If all stages pass, it exports the mart to `data/exports/indicators_wide.json` and computes run metrics. Whatever the outcome, it appends a record to `data/exports/pipeline_runs.json`, keeping the latest 50 runs. Failed stages store the last 500 characters of their output as `error_tail`.

### Data quality observations

Missing values differ a lot by indicator in the latest snapshot:

| Indicator | Null rate |
|---|---|
| Population | 0.00% |
| GDP | 3.79% |
| GDP per capita | 3.79% |
| Life expectancy | 3.85% |
| Unemployment | 14.07% |
| Inflation | 16.75% |

## Project 3: Pipeline Health Monitor

The monitor turns the run history into an operational view. It reads `data/exports/pipeline_runs.json` from disk on every request, so a new run appears without restarting the API.

### What each run records

```json
{
  "run_started_at": "2026-10-16T03:15:38.490359+00:00",
  "duration_seconds": 68.54,
  "status": "success",
  "rows_exported": 5642,
  "metrics": {
    "rows": 5642,
    "countries": 217,
    "year_min": 2000,
    "year_max": 2025,
    "null_pct_by_indicator": {
      "gdp_current_usd": 3.79,
      "gdp_per_capita_current_usd": 3.79,
      "inflation_cpi_pct": 16.75,
      "population_total": 0.0,
      "unemployment_pct": 14.07,
      "life_expectancy_years": 3.85
    }
  },
  "stages": [
    {"stage": "extract_indicators", "status": "success", "duration_seconds": 17.0},
    {"stage": "extract_countries", "status": "success", "duration_seconds": 0.8},
    {"stage": "dbt_run", "status": "success", "duration_seconds": 32.7},
    {"stage": "dbt_test", "status": "success", "duration_seconds": 17.9}
  ]
}
```

(Stage durations are rounded.)

### Checks

| Check | Triggers when | Severity |
|---|---|---|
| `no_runs` | The history is empty | critical |
| `no_successful_run` | No run has ever succeeded | critical |
| `failure_streak` | 2 or more consecutive failed runs | critical |
| `last_run_failed` | The latest run failed (reports the failed stage) | high |
| `stale_data` | Last success is older than the critical limit (168 h by default) | critical |
| `stale_data` | Last success is older than the warning limit (48 h by default) | medium |
| `row_count_drop` | Rows fell more than 10% versus the previous successful run | high |
| `year_regression` | The latest year went backwards | high |
| `country_count_drop` | Fewer countries than the previous run | medium |
| `null_spike` | A null rate rose 15 points or more | high |
| `null_spike` | A null rate rose 5 to 15 points | medium |
| `slow_run` | Duration is over 2x the median of earlier successful runs (needs 3 or more) | low |

Data comparisons use the two latest successful runs that have metrics. Older runs without metrics are ignored, never an error.

### Overall status

| Status | Condition |
|---|---|
| `critical` | At least one critical alert |
| `degraded` | At least one high or medium alert, and no critical |
| `healthy` | Nothing, or only low-severity alerts |

All thresholds are constants at the top of `api/monitor.py`. They are heuristics chosen for this dataset, not standards.

### Tests

Ten pytest tests in `tests/test_monitor.py` simulate each situation with synthetic histories: a healthy history, a failed run, a failure streak, stale data at both levels, a row drop, null spikes at both levels, a year regression, a slow run, an empty history and legacy runs without metrics.

## API reference

Base URL: `http://localhost:8005` locally. CORS allows `GET` only.

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness plus snapshot and last-run status. Returns 503 if the snapshot is not loaded |
| `GET /meta` | Indicators (key and label), regions, income levels, year range, country count |
| `GET /countries?region=&income_level=` | Country list, optionally filtered |
| `GET /countries/{code}?start_year=&end_year=` | Yearly series with all six indicators. 404 for unknown codes |
| `GET /ranking?indicator=&year=&limit=&order=&region=` | Top or bottom countries. `limit` 1 to 50 (default 10), `order` is `asc` or `desc`. Without `year`, uses the latest year in which at least 100 countries have data. 400 for unknown indicators |
| `GET /pipeline/runs?limit=` | Latest runs, newest first. `limit` 1 to 50 (default 20) |
| `GET /monitor/status` | Overall status, alert counts, alerts, success rate (last 20 runs), average duration, last run and last success |
| `GET /monitor/alerts?severity=` | Current alerts, optionally filtered by severity |
| `GET /monitor/trend` | Per-run rows, countries, duration and null rates for charts (successful runs with metrics) |

Null values arrive as JSON `null`. Example response from `/monitor/status`:

```json
{
  "status": "healthy",
  "alert_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
  "alerts": [],
  "runs_total": 4,
  "success_rate_pct": 100.0,
  "avg_duration_seconds": 50.1,
  "last_run_at": "2026-10-16T03:15:38.490359+00:00",
  "last_success_at": "2026-10-16T03:15:38.490359+00:00"
}
```

Each alert has `check`, `severity`, `message` and a `details` object with the numbers behind it.

## Frontends

Both pages are single static HTML files with no build step and no dependencies.

**`index.html` (indicators):** indicator selector, year slider, region filter, highest/lowest toggle, top 10 or top 25 ranking with bars, country search, a country detail card with a trend line and the latest value of each indicator, and a collapsible pipeline history.

**`monitor.html` (health monitor):** overall status with the success rate of recent runs, active alerts (the section disappears when nothing is wrong), summary tiles, a strip of recent runs where bar height is duration, per-run stage details with error output, and a trends view with row, country and duration sparklines plus null rates compared with the previous run. It refreshes every 60 seconds.

**Cold start handling.** The hosted backend runs on a free instance that sleeps when idle. Both pages poll `/health` every 3 seconds, change the message after 25 seconds, give up after 2 minutes with a retry button, and only then load data. The visitor never sees a blank page.

## Repository structure

```text
.
├── api/
│   ├── main.py                 # data endpoints, CORS, lifespan loading
│   ├── monitor.py              # health checks (pure functions)
│   ├── monitor_routes.py       # /monitor/* endpoints
│   └── requirements.txt        # runtime dependencies for the API only
├── data/
│   └── exports/                # committed snapshot and run history
├── dbt_project/
│   ├── dbt_project.yml
│   ├── profiles.yml            # DuckDB, single thread
│   ├── models/staging/         # stg_indicators.sql, stg_countries.sql
│   ├── models/marts/           # fct_indicators_wide.sql, schema.yml
│   └── tests/                  # unique_country_year.sql
├── extract/
│   ├── worldbank_extract.py
│   └── worldbank_countries.py
├── frontend/
│   ├── index.html
│   └── monitor.html
├── tests/
│   └── test_monitor.py
├── run_pipeline.py
├── requirements.txt            # pinned versions
├── requirements-dev.txt        # adds pytest
├── .env.example
└── LICENSE
```

Not tracked: `.venv/`, `data/raw/` (regenerated by the extractor), `data/worldbank.duckdb` and dbt build output.

## Run locally

Requirements: Python 3.14 (developed on 3.14.4) and git. No credentials are needed: the World Bank API is public.

```bash
git clone https://github.com/juanquiterio/worldbank-elt.git
cd worldbank-elt
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python run_pipeline.py        # extract, dbt run, dbt test, export, log the run
pytest -q                     # monitor tests

uvicorn main:app --app-dir api --port 8005     # API at http://localhost:8005
cd frontend && python -m http.server 3000      # pages at http://localhost:3000
```

The repository already includes a snapshot in `data/exports/`, so you can start the API without running the pipeline. The committed frontends point to the hosted API: for local use, change the `API_BASE` constant at the top of the script in `frontend/index.html` and `frontend/monitor.html` to `http://localhost:8005`.

Environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `ALLOWED_ORIGINS` | `*` | Comma-separated origins allowed by CORS |
| `FRESHNESS_WARN_HOURS` | `48` | Age of the last success that raises a medium alert |
| `FRESHNESS_CRITICAL_HOURS` | `168` | Age of the last success that raises a critical alert |

Pinned versions: dbt-core 1.12.6, dbt-duckdb 1.11.0, DuckDB 1.5.6, requests 2.34.2, FastAPI 0.143.2, Uvicorn 0.54.0, pytest 9.1.1.

## Deployment

Hosted on Render's free plan with two services:

| Service | Type | Configuration |
|---|---|---|
| `worldbank-api` | Web Service | Build `pip install -r api/requirements.txt`, start `uvicorn main:app --app-dir api --host 0.0.0.0 --port $PORT`, health check `/health` |
| `worldbank-web` | Static Site | Publish directory `frontend` |

The API installs only FastAPI and Uvicorn. pandas, DuckDB and dbt are not needed to serve the snapshot, which keeps it well inside the 512 MB instance. The hosted demo serves a frozen snapshot, so `FRESHNESS_WARN_HOURS` and `FRESHNESS_CRITICAL_HOURS` are raised on the server. Otherwise the monitor would correctly report the old data as stale.

## Technical decisions

| Decision | Why | Trade-off |
|---|---|---|
| DuckDB instead of BigQuery | BigQuery sandbox tables expire after 60 days, a public demo should not depend on live warehouse queries, and DuckDB runs in seconds on modest hardware | No shared warehouse or concurrent writers |
| Static snapshot as the demo source | Render's free disk is ephemeral and memory is limited, so the API only loads two JSON files | Data is as fresh as the last commit |
| Aggregates filtered with country metadata | Avoids double counting, and the rule is checked against the data | Depends on the API's region flag staying stable, which the `accepted_values` test helps guard |
| `unique_country_year` as a singular SQL test | Needs no extra dbt package | Less reusable than a packaged test |
| Monitor as pure functions over the run history | Easy to test with synthetic histories, no database needed | The history is a JSON file capped at 50 runs |
| Run history read from disk per request | New runs show up without restarting the API | Slightly more I/O per request |
| Comparison with the previous run instead of fixed null limits | Null rates differ widely by indicator | A slow drift over many runs would not be caught |
| Frontend polls `/health` before loading data | Free instances sleep, and a blank page looks broken | The first visit still waits for the server |
| Single dbt thread | The development machine has 2 cores and 4 GB of RAM shared with the OS | Slower on larger projects |

## Challenges and learnings

- **Relative paths inside dbt.** The staging views read JSON files with paths relative to `dbt_project/`, so querying them from another directory fails with "no files found". The working directory is part of the contract of the project.
- **Deprecation warnings are worth fixing early.** dbt 1.12 flagged test arguments written at the top level. Moving them under `arguments` produced a clean run.
- **A shared threshold does not fit every column.** Null rates range from 0% to almost 17%, which is why the monitor compares runs with each other instead of using one fixed limit.
- **A monitor needs data about the runs, not only about the data.** Early runs did not store metrics, so the monitor was designed to skip runs without them instead of failing on history.
- **Static demos and freshness do not mix.** A frozen snapshot makes a freshness check fire by design, so the limits are configurable through environment variables.
- **Keep the deployed service small.** Separating the pipeline (run on demand) from the API (read-only) meant the hosted service needs two dependencies.

## Limitations and next steps

- The pipeline runs on demand: there is no scheduler, so the history only grows when someone runs it.
- Alerts are shown in the dashboard only. There are no notifications.
- The API has no authentication, which is fine for public read-only data.
- Thresholds are heuristics and would need tuning with a longer run history.
- Ideas for later: a scheduled run, more indicators, and notifications for critical alerts.

## Data and license

Data: World Bank Open Data. Check the World Bank terms of use for attribution requirements. Code: MIT, see `LICENSE`.
