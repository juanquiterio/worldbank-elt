"""Extract World Bank indicators and store them as raw JSON files."""

import json
import logging
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://api.worldbank.org/v2/country/all/indicator"
START_YEAR = 2000
END_YEAR = 2025
PER_PAGE = 1000
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

INDICATORS = {
    "NY.GDP.MKTP.CD": "gdp_current_usd",
    "NY.GDP.PCAP.CD": "gdp_per_capita_current_usd",
    "FP.CPI.TOTL.ZG": "inflation_cpi_pct",
    "SP.POP.TOTL": "population_total",
    "SL.UEM.TOTL.ZS": "unemployment_pct",
    "SP.DYN.LE00.IN": "life_expectancy_years",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("worldbank_extract")


def fetch_page(indicator: str, page: int) -> tuple[dict, list]:
    """Fetch one page of an indicator, retrying on transient failures."""
    url = f"{BASE_URL}/{indicator}"
    params = {
        "format": "json",
        "date": f"{START_YEAR}:{END_YEAR}",
        "per_page": PER_PAGE,
        "page": page,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
                raise ValueError(f"Unexpected response for {indicator}: {str(payload)[:200]}")
            return payload[0], payload[1]
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "Attempt %d/%d failed for %s page %d: %s",
                attempt, MAX_RETRIES, indicator, page, exc,
            )
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 * attempt)
    raise RuntimeError("unreachable")


def extract_indicator(indicator: str) -> list:
    """Fetch all pages for one indicator and return every record."""
    records: list = []
    page = 1
    while True:
        meta, rows = fetch_page(indicator, page)
        records.extend(rows)
        total_pages = int(meta["pages"])
        logger.info("%s: page %d/%d (%d records so far)", indicator, page, total_pages, len(records))
        if page >= total_pages:
            break
        page += 1
    return records


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for code, name in INDICATORS.items():
        started = time.time()
        try:
            records = extract_indicator(code)
        except Exception:
            logger.exception("Extraction failed for %s", code)
            failures += 1
            continue
        out_path = RAW_DIR / f"{name}.json"
        out_path.write_text(json.dumps(records), encoding="utf-8")
        logger.info(
            "Saved %s (%d records) in %.1fs", out_path.name, len(records), time.time() - started
        )
    if failures:
        logger.error("Finished with %d failed indicator(s)", failures)
        return 1
    logger.info("Extraction finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
