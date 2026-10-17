"""Health checks over the pipeline run history."""

import os
import statistics
from datetime import datetime, timezone
from typing import Optional

FRESHNESS_WARN_HOURS = float(os.getenv("FRESHNESS_WARN_HOURS", "48"))
FRESHNESS_CRITICAL_HOURS = float(os.getenv("FRESHNESS_CRITICAL_HOURS", "168"))
ROW_DROP_PCT = 10.0
NULL_SPIKE_POINTS = 5.0
NULL_SPIKE_HIGH_POINTS = 15.0
SLOW_FACTOR = 2.0
MIN_RUNS_FOR_SLOW_CHECK = 3
FAILURE_STREAK_CRITICAL = 2

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _alert(check: str, severity: str, message: str, **details) -> dict:
    return {"check": check, "severity": severity, "message": message, "details": details}


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def _successful(runs: list) -> list:
    return [r for r in runs if r.get("status") == "success"]


def check_failures(runs: list) -> list:
    """Alert on a failed latest run, escalating when failures repeat."""
    streak = 0
    for run in reversed(runs):
        if run.get("status") == "failed":
            streak += 1
        else:
            break
    if streak == 0:
        return []
    last = runs[-1]
    failed_stage = next(
        (s["stage"] for s in last.get("stages", []) if s.get("status") == "failed"),
        "unknown",
    )
    if streak >= FAILURE_STREAK_CRITICAL:
        return [_alert(
            "failure_streak", "critical",
            f"{streak} consecutive pipeline failures (latest at stage '{failed_stage}').",
            streak=streak, failed_stage=failed_stage,
        )]
    return [_alert(
        "last_run_failed", "high",
        f"The latest run failed at stage '{failed_stage}'.",
        failed_stage=failed_stage,
    )]


def check_freshness(runs: list, now: datetime) -> list:
    """Alert when the last successful run is too old."""
    successes = _successful(runs)
    if not successes:
        return [_alert("no_successful_run", "critical", "No successful run in the history.")]
    age_hours = (now - _parse(successes[-1]["run_started_at"])).total_seconds() / 3600
    details = {"hours_since_last_success": round(age_hours, 1)}
    if age_hours > FRESHNESS_CRITICAL_HOURS:
        return [_alert(
            "stale_data", "critical",
            f"Data is {age_hours:.0f} hours old (limit {FRESHNESS_CRITICAL_HOURS:.0f}).",
            **details,
        )]
    if age_hours > FRESHNESS_WARN_HOURS:
        return [_alert(
            "stale_data", "medium",
            f"Data is {age_hours:.0f} hours old (warning at {FRESHNESS_WARN_HOURS:.0f}).",
            **details,
        )]
    return []


def check_data_changes(runs: list) -> list:
    """Compare the two latest successful runs: volume, coverage and nulls."""
    with_metrics = [r for r in _successful(runs) if r.get("metrics")]
    if len(with_metrics) < 2:
        return []
    prev, latest = with_metrics[-2]["metrics"], with_metrics[-1]["metrics"]
    alerts: list = []

    if prev["rows"] > 0:
        drop = 100 * (prev["rows"] - latest["rows"]) / prev["rows"]
        if drop > ROW_DROP_PCT:
            alerts.append(_alert(
                "row_count_drop", "high",
                f"Row count fell {drop:.1f}% ({prev['rows']} to {latest['rows']}).",
                previous=prev["rows"], current=latest["rows"],
            ))

    if latest["countries"] < prev["countries"]:
        alerts.append(_alert(
            "country_count_drop", "medium",
            f"Countries fell from {prev['countries']} to {latest['countries']}.",
            previous=prev["countries"], current=latest["countries"],
        ))

    if (
        latest.get("year_max") is not None
        and prev.get("year_max") is not None
        and latest["year_max"] < prev["year_max"]
    ):
        alerts.append(_alert(
            "year_regression", "high",
            f"Latest year went back from {prev['year_max']} to {latest['year_max']}.",
            previous=prev["year_max"], current=latest["year_max"],
        ))

    for indicator, now_pct in latest["null_pct_by_indicator"].items():
        before_pct = prev["null_pct_by_indicator"].get(indicator)
        if now_pct is None or before_pct is None:
            continue
        rise = now_pct - before_pct
        if rise >= NULL_SPIKE_HIGH_POINTS:
            severity = "high"
        elif rise >= NULL_SPIKE_POINTS:
            severity = "medium"
        else:
            continue
        alerts.append(_alert(
            "null_spike", severity,
            f"Nulls in {indicator} rose {rise:.1f} points ({before_pct}% to {now_pct}%).",
            indicator=indicator, previous=before_pct, current=now_pct,
        ))
    return alerts


def check_slow_run(runs: list) -> list:
    """Alert when the latest successful run is much slower than usual."""
    if not runs or runs[-1].get("status") != "success":
        return []
    previous = [r["duration_seconds"] for r in _successful(runs[:-1])]
    if len(previous) < MIN_RUNS_FOR_SLOW_CHECK:
        return []
    typical = statistics.median(previous)
    duration = runs[-1]["duration_seconds"]
    if typical > 0 and duration > SLOW_FACTOR * typical:
        return [_alert(
            "slow_run", "low",
            f"Run took {duration:.0f}s, typical is {typical:.0f}s.",
            duration_seconds=duration, typical_seconds=typical,
        )]
    return []


def evaluate(runs: list, now: Optional[datetime] = None) -> dict:
    """Run every check and return the overall status with sorted alerts."""
    now = now or datetime.now(timezone.utc)
    if not runs:
        alerts = [_alert("no_runs", "critical", "No pipeline runs recorded.")]
    else:
        alerts = (
            check_failures(runs)
            + check_freshness(runs, now)
            + check_data_changes(runs)
            + check_slow_run(runs)
        )
    alerts.sort(key=lambda a: SEVERITY_ORDER[a["severity"]])

    severities = {a["severity"] for a in alerts}
    if "critical" in severities:
        status = "critical"
    elif severities & {"high", "medium"}:
        status = "degraded"
    else:
        status = "healthy"

    counts = {s: sum(1 for a in alerts if a["severity"] == s) for s in SEVERITY_ORDER}
    recent = runs[-20:]
    successes = _successful(runs)
    return {
        "status": status,
        "evaluated_at": now.isoformat(),
        "alert_counts": counts,
        "alerts": alerts,
        "runs_total": len(runs),
        "success_rate_pct": (
            round(100 * len(_successful(recent)) / len(recent), 1) if recent else None
        ),
        "avg_duration_seconds": (
            round(statistics.mean(r["duration_seconds"] for r in successes), 1)
            if successes else None
        ),
        "last_run_at": runs[-1]["run_started_at"] if runs else None,
        "last_success_at": successes[-1]["run_started_at"] if successes else None,
    }
