"""Static-data API for the World Bank ELT pipeline."""

import json
import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from monitor_routes import load_runs, router as monitor_router

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "data" / "exports"
SNAPSHOT_PATH = EXPORT_DIR / "indicators_wide.json"
RUNS_PATH = EXPORT_DIR / "pipeline_runs.json"
MIN_COUNTRIES_FOR_DEFAULT_YEAR = 100

INDICATORS = {
    "gdp_current_usd": "GDP (current US$)",
    "gdp_per_capita_current_usd": "GDP per capita (current US$)",
    "inflation_cpi_pct": "Inflation, consumer prices (annual %)",
    "population_total": "Population, total",
    "unemployment_pct": "Unemployment, total (% of labor force)",
    "life_expectancy_years": "Life expectancy at birth (years)",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("api")

store: dict = {"rows": [], "by_country": {}, "countries": [], "runs": []}


def load_data() -> None:
    """Load the exported JSON files into memory."""
    rows: list = []
    runs: list = []
    if SNAPSHOT_PATH.exists():
        rows = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    else:
        logger.error("Snapshot not found: %s", SNAPSHOT_PATH)
    if RUNS_PATH.exists():
        try:
            runs = json.loads(RUNS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error("Could not parse %s", RUNS_PATH.name)

    by_country: dict = {}
    countries: dict = {}
    for row in rows:
        by_country.setdefault(row["country_code"], []).append(row)
        countries.setdefault(
            row["country_code"],
            {
                "country_code": row["country_code"],
                "country_name": row["country_name"],
                "region_name": row["region_name"],
                "income_level": row["income_level"],
            },
        )
    for series in by_country.values():
        series.sort(key=lambda r: r["year"])

    store["rows"] = rows
    store["by_country"] = by_country
    store["countries"] = sorted(countries.values(), key=lambda c: c["country_name"])
    store["runs"] = runs
    logger.info("Loaded %d rows, %d countries, %d runs", len(rows), len(countries), len(runs))


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_data()
    yield


app = FastAPI(title="World Bank Indicators API", version="1.0.0", lifespan=lifespan)
app.include_router(monitor_router)

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def check_indicator(indicator: str) -> None:
    if indicator not in INDICATORS:
        raise HTTPException(status_code=400, detail=f"Unknown indicator. Valid: {sorted(INDICATORS)}")


def latest_complete_year(indicator: str) -> Optional[int]:
    """Latest year where the indicator has data for enough countries."""
    counts = Counter(r["year"] for r in store["rows"] if r[indicator] is not None)
    years = [y for y, c in counts.items() if c >= MIN_COUNTRIES_FOR_DEFAULT_YEAR]
    return max(years) if years else None


@app.get("/health")
def health() -> dict:
    """Liveness check with data and pipeline status."""
    if not store["rows"]:
        raise HTTPException(status_code=503, detail="Snapshot not loaded")
    last_run = store["runs"][-1] if store["runs"] else None
    return {
        "status": "ok",
        "rows_loaded": len(store["rows"]),
        "countries_loaded": len(store["by_country"]),
        "last_run_status": last_run["status"] if last_run else None,
        "last_run_at": last_run["run_started_at"] if last_run else None,
    }


@app.get("/meta")
def meta() -> dict:
    """Indicators, regions, income levels and year range for building filters."""
    years = [r["year"] for r in store["rows"]]
    return {
        "indicators": [{"key": k, "label": v} for k, v in INDICATORS.items()],
        "regions": sorted({c["region_name"] for c in store["countries"]}),
        "income_levels": sorted({c["income_level"] for c in store["countries"]}),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "countries_count": len(store["countries"]),
    }


@app.get("/countries")
def countries(region: Optional[str] = None, income_level: Optional[str] = None) -> list:
    """List countries, optionally filtered by region or income level."""
    result = store["countries"]
    if region:
        result = [c for c in result if c["region_name"] == region]
    if income_level:
        result = [c for c in result if c["income_level"] == income_level]
    return result


@app.get("/countries/{country_code}")
def country_series(
    country_code: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> dict:
    """Yearly series with all six indicators for one country."""
    code = country_code.upper()
    series = store["by_country"].get(code)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Country {code} not found")
    if start_year is not None:
        series = [r for r in series if r["year"] >= start_year]
    if end_year is not None:
        series = [r for r in series if r["year"] <= end_year]
    info = next(c for c in store["countries"] if c["country_code"] == code)
    return {"country": info, "series": series}


@app.get("/ranking")
def ranking(
    indicator: str,
    year: Optional[int] = None,
    limit: int = Query(10, ge=1, le=50),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    region: Optional[str] = None,
) -> dict:
    """Top or bottom countries for one indicator in one year."""
    check_indicator(indicator)
    if year is None:
        year = latest_complete_year(indicator)
    if year is None:
        raise HTTPException(status_code=404, detail="No data for this indicator")
    rows = [r for r in store["rows"] if r["year"] == year and r[indicator] is not None]
    if region:
        rows = [r for r in rows if r["region_name"] == region]
    rows.sort(key=lambda r: r[indicator], reverse=(order == "desc"))
    return {
        "indicator": indicator,
        "year": year,
        "order": order,
        "items": [
            {
                "country_code": r["country_code"],
                "country_name": r["country_name"],
                "region_name": r["region_name"],
                "value": r[indicator],
            }
            for r in rows[:limit]
        ],
    }


@app.get("/pipeline/runs")
def pipeline_runs(limit: int = Query(20, ge=1, le=50)) -> list:
    """Latest pipeline runs, newest first."""
    return list(reversed(load_runs()))[:limit]
