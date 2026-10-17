"""Tests for the pipeline health checks."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from monitor import evaluate  # noqa: E402

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
INDICATORS = [
    "gdp_current_usd",
    "gdp_per_capita_current_usd",
    "inflation_cpi_pct",
    "population_total",
    "unemployment_pct",
    "life_expectancy_years",
]


def make_run(
    hours_ago,
    status="success",
    rows=5642,
    countries=217,
    year_max=2025,
    null_overrides=None,
    duration=40.0,
    with_metrics=True,
    failed_stage="dbt_test",
):
    started = NOW - timedelta(hours=hours_ago)
    nulls = {name: 3.0 for name in INDICATORS}
    nulls.update(null_overrides or {})
    metrics = None
    stages = [{"stage": "dbt_test", "status": "success", "duration_seconds": 10}]
    if status == "failed":
        stages = [{"stage": failed_stage, "status": "failed", "duration_seconds": 5}]
    elif with_metrics:
        metrics = {
            "rows": rows,
            "countries": countries,
            "year_min": 2000,
            "year_max": year_max,
            "null_pct_by_indicator": nulls,
        }
    return {
        "run_started_at": started.isoformat(),
        "duration_seconds": duration,
        "status": status,
        "rows_exported": rows if status == "success" else None,
        "metrics": metrics,
        "stages": stages,
    }


def by_check(result):
    return {a["check"]: a for a in result["alerts"]}


def test_healthy_history_has_no_alerts():
    runs = [make_run(4), make_run(3), make_run(2), make_run(1)]
    result = evaluate(runs, NOW)
    assert result["status"] == "healthy"
    assert result["alerts"] == []
    assert result["success_rate_pct"] == 100.0


def test_failed_latest_run_is_high():
    runs = [make_run(3), make_run(2), make_run(1, status="failed")]
    result = evaluate(runs, NOW)
    alerts = by_check(result)
    assert alerts["last_run_failed"]["severity"] == "high"
    assert alerts["last_run_failed"]["details"]["failed_stage"] == "dbt_test"
    assert result["status"] == "degraded"


def test_failure_streak_is_critical():
    runs = [make_run(3), make_run(2, status="failed"), make_run(1, status="failed")]
    result = evaluate(runs, NOW)
    assert by_check(result)["failure_streak"]["severity"] == "critical"
    assert result["status"] == "critical"


def test_stale_data_warning_and_critical():
    warn = evaluate([make_run(60)], NOW)
    assert by_check(warn)["stale_data"]["severity"] == "medium"
    assert warn["status"] == "degraded"
    critical = evaluate([make_run(200)], NOW)
    assert by_check(critical)["stale_data"]["severity"] == "critical"
    assert critical["status"] == "critical"


def test_row_count_drop_is_high():
    runs = [make_run(2), make_run(1, rows=4000)]
    result = evaluate(runs, NOW)
    assert by_check(result)["row_count_drop"]["severity"] == "high"


def test_null_spike_severity_levels():
    medium = evaluate([make_run(2), make_run(1, null_overrides={"inflation_cpi_pct": 10.0})], NOW)
    assert by_check(medium)["null_spike"]["severity"] == "medium"
    high = evaluate([make_run(2), make_run(1, null_overrides={"inflation_cpi_pct": 25.0})], NOW)
    assert by_check(high)["null_spike"]["severity"] == "high"


def test_year_regression_is_high():
    runs = [make_run(2), make_run(1, year_max=2024)]
    result = evaluate(runs, NOW)
    assert by_check(result)["year_regression"]["severity"] == "high"


def test_slow_run_is_low_and_keeps_status_healthy():
    runs = [make_run(5), make_run(4), make_run(3), make_run(1, duration=120.0)]
    result = evaluate(runs, NOW)
    assert by_check(result)["slow_run"]["severity"] == "low"
    assert result["status"] == "healthy"


def test_empty_history_is_critical():
    result = evaluate([], NOW)
    assert by_check(result)["no_runs"]["severity"] == "critical"
    assert result["status"] == "critical"


def test_legacy_runs_without_metrics_do_not_crash():
    runs = [make_run(3, with_metrics=False), make_run(2, with_metrics=False), make_run(1)]
    result = evaluate(runs, NOW)
    assert result["status"] == "healthy"
