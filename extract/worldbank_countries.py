"""Extract World Bank country metadata (region, income level) as raw JSON."""

import json
import logging
import sys
import time
from pathlib import Path

import requests

URL = "https://api.worldbank.org/v2/country"
PER_PAGE = 500
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("worldbank_countries")


def fetch_page(page: int) -> tuple[dict, list]:
    """Fetch one page of country metadata, retrying on transient failures."""
    params = {"format": "json", "per_page": PER_PAGE, "page": page}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(URL, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
                raise ValueError(f"Unexpected response: {str(payload)[:200]}")
            return payload[0], payload[1]
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Attempt %d/%d failed for page %d: %s", attempt, MAX_RETRIES, page, exc)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 * attempt)
    raise RuntimeError("unreachable")


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    records: list = []
    page = 1
    try:
        while True:
            meta, rows = fetch_page(page)
            records.extend(rows)
            total_pages = int(meta["pages"])
            logger.info("countries: page %d/%d (%d records so far)", page, total_pages, len(records))
            if page >= total_pages:
                break
            page += 1
    except Exception:
        logger.exception("Country metadata extraction failed")
        return 1
    out_path = RAW_DIR / "countries.json"
    out_path.write_text(json.dumps(records), encoding="utf-8")
    logger.info("Saved %s (%d records)", out_path.name, len(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
