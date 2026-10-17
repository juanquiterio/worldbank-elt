"""Run the full ELT pipeline, export a static JSON snapshot and log every run."""

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
DBT_DIR = ROOT / "dbt_project"
DB_PATH = ROOT / "data" / "worldbank.duckdb"
EXPORT_DIR = ROOT / "data" / "exports"
RUNS_PATH = EXPORT_DIR / "pipeline_runs.json"
SNAPSHOT_PATH = EXPORT_DIR / "indicators_wide.json"
MAX_RUNS_KEPT = 50

INDICATOR_COLUMNS = [
    "gdp_current_usd",
    "gdp_per_capita_current_usd",
    "inflation_cpi_pct",
    "population_total",
    "unemployment_pct",
    "life_expectancy_years",
]

STAGES = [
    ("extract_indicators", [sys.executable, str(ROOT / "extract" / "worldbank_extract.py")], ROOT),
    ("extract_countries", [sys.executable, str(ROOT / "extract" / "worldbank_countries.py")], ROOT),
    ("dbt_run", ["dbt", "run", "--profiles-dir", "."], DBT_DIR),
    ("dbt_test", ["dbt", "test", "--profiles-dir", "."], DBT_DIR),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_pipeline")


def run_stage(name: str, command: list, cwd: Path) -> dict:
    """Run one stage as a subprocess and return its result record."""
    logger.info("Starting stage: %s", name)
    started = time.time()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    duration = round(time.time() - started, 2)
    status = "success" if result.returncode == 0 else "failed"
    record = {"stage": name, "status": status, "duration_seconds": duration}
    if status == "failed":
        tail = (result.stdout + result.stderr)[-500:]
        record["error_tail"] = tail
        logger.error("Stage %s failed:\n%s", name, tail)
    logger.info("Finished stage %s: %s in %.1fs", name, status, duration)
    return record


def export_snapshot() -> list:
    """Export the wide mart to a static JSON file and return the exported rows."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cursor = con.execute("select * from fct_indicators_wide order by country_code, year")
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        con.close()
    SNAPSHOT_PATH.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def compute_metrics(rows: list) -> dict:
    """Summarize the exported data so the monitor can compare runs."""
    total = len(rows)
    years = [r["year"] for r in rows]
    null_pct = {}
    for column in INDICATOR_COLUMNS:
        nulls = sum(1 for r in rows if r[column] is None)
        null_pct[column] = round(100 * nulls / total, 2) if total else None
    return {
        "rows": total,
        "countries": len({r["country_code"] for r in rows}),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "null_pct_by_indicator": null_pct,
    }


def append_run(record: dict) -> None:
    """Append a run record to the history, keeping only the latest runs."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    history: list = []
    if RUNS_PATH.exists():
        try:
            history = json.loads(RUNS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Could not parse %s, starting a new history", RUNS_PATH.name)
    history.append(record)
    RUNS_PATH.write_text(json.dumps(history[-MAX_RUNS_KEPT:], indent=2), encoding="utf-8")


def main() -> int:
    run_started = datetime.now(timezone.utc)
    started = time.time()
    stage_results: list = []
    overall = "success"
    rows_exported = None
    metrics = None

    for name, command, cwd in STAGES:
        result = run_stage(name, command, cwd)
        stage_results.append(result)
        if result["status"] == "failed":
            overall = "failed"
            break

    if overall == "success":
        try:
            rows = export_snapshot()
            rows_exported = len(rows)
            metrics = compute_metrics(rows)
            logger.info("Exported %d rows to %s", rows_exported, SNAPSHOT_PATH.name)
        except Exception:
            logger.exception("Snapshot export failed")
            overall = "failed"
            stage_results.append({"stage": "export_snapshot", "status": "failed", "duration_seconds": 0})

    append_run(
        {
            "run_started_at": run_started.isoformat(),
            "duration_seconds": round(time.time() - started, 2),
            "status": overall,
            "rows_exported": rows_exported,
            "metrics": metrics,
            "stages": stage_results,
        }
    )
    logger.info("Pipeline finished: %s", overall)
    return 0 if overall == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
