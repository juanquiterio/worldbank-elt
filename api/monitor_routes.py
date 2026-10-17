"""Health monitor endpoints, computed from the pipeline run history."""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from monitor import SEVERITY_ORDER, evaluate

RUNS_PATH = Path(__file__).resolve().parent.parent / "data" / "exports" / "pipeline_runs.json"

logger = logging.getLogger("monitor_routes")
router = APIRouter(prefix="/monitor", tags=["monitor"])


def load_runs() -> list:
    """Read the run history from disk so new runs show up without a restart."""
    if not RUNS_PATH.exists():
        return []
    try:
        return json.loads(RUNS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.error("Could not parse %s", RUNS_PATH.name)
        return []


@router.get("/status")
def status() -> dict:
    """Overall pipeline health with alerts and operational metrics."""
    return evaluate(load_runs())


@router.get("/alerts")
def alerts(severity: Optional[str] = None) -> list:
    """Current alerts, optionally filtered by severity."""
    if severity is not None and severity not in SEVERITY_ORDER:
        raise HTTPException(status_code=400, detail=f"Unknown severity. Valid: {sorted(SEVERITY_ORDER)}")
    result = evaluate(load_runs())["alerts"]
    if severity:
        result = [a for a in result if a["severity"] == severity]
    return result


@router.get("/trend")
def trend() -> list:
    """Per-run metrics for charts, oldest first. Runs without metrics are skipped."""
    return [
        {
            "run_started_at": r["run_started_at"],
            "duration_seconds": r["duration_seconds"],
            "rows": r["metrics"]["rows"],
            "countries": r["metrics"]["countries"],
            "year_max": r["metrics"]["year_max"],
            "null_pct_by_indicator": r["metrics"]["null_pct_by_indicator"],
        }
        for r in load_runs()
        if r.get("status") == "success" and r.get("metrics")
    ]
