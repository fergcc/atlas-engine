"""US Census Bureau — SAIPE (Small Area Income and Poverty Estimates).

Fetches state-level poverty estimates from the Census Bureau API.
Uses the same CENSUS_API_KEY as census_acs.py and census_cbp.py.

Indicator:
  - extreme_poverty: % of population below poverty level (all ages)

API: https://api.census.gov/data/timeseries/poverty/saipe
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from src.services.ingestion._http import request_json
from src.services.ingestion.exceptions import MissingCredentialError, SourceUnavailableError

load_dotenv()

logger = logging.getLogger(__name__)

SOURCE_NAME = "CensusSAIPE"
BASE_URL = "https://api.census.gov/data/timeseries/poverty/saipe"

FALLBACK_POVERTY: dict[str, float] = {
    "01": 15.8, "02": 10.5, "04": 13.5, "05": 15.8, "06": 12.2,
    "08": 9.8, "09": 10.0, "10": 10.8, "11": 16.5, "12": 13.0,
    "13": 14.2, "15": 10.2, "16": 10.8, "17": 12.2, "18": 12.8,
    "19": 11.2, "20": 12.5, "21": 16.5, "22": 19.0, "23": 11.5,
    "24": 9.8, "25": 10.5, "26": 13.5, "27": 9.8, "28": 19.5,
    "29": 13.2, "30": 12.5, "31": 11.2, "32": 13.5, "33": 7.5,
    "34": 10.2, "35": 18.5, "36": 13.5, "37": 13.8, "38": 11.2,
    "39": 13.0, "40": 15.2, "41": 12.5, "42": 12.0, "44": 11.0,
    "45": 14.5, "46": 13.2, "47": 14.2, "48": 14.5, "49": 9.0,
    "50": 10.5, "51": 10.5, "53": 10.2, "54": 17.5, "55": 10.8,
    "56": 10.8,
}


def _get_api_key() -> str:
    api_key = os.getenv("CENSUS_API_KEY")
    if not api_key:
        raise MissingCredentialError(
            "CENSUS_API_KEY no está definido. Regístrate (gratis) en "
            "https://api.census.gov/data/key_signup.html"
        )
    return api_key


def get_extreme_poverty() -> dict[str, float]:
    """State-level poverty rate (all ages) from SAIPE, most recent year."""
    try:
        key = _get_api_key()
    except MissingCredentialError:
        logger.info(f"{SOURCE_NAME}: no API key, using fallback")
        return dict(FALLBACK_POVERTY)

    url = (
        f"{BASE_URL}?"
        f"get=NAME,SAEPOVRTALL_PT&"
        f"for=state:*&"
        f"time=2022&"
        f"key={key}"
    )

    try:
        data = request_json("GET", url, source=SOURCE_NAME, timeout=30)
    except Exception as exc:
        logger.info(f"{SOURCE_NAME}: API unavailable ({exc}), using fallback")
        return dict(FALLBACK_POVERTY)

    if not isinstance(data, list) or len(data) < 2:
        logger.info(f"{SOURCE_NAME}: unexpected response format, using fallback")
        return dict(FALLBACK_POVERTY)

    header = data[0]
    rows = data[1:]
    try:
        val_idx = header.index("SAEPOVRTALL_PT")
        state_idx = header.index("state")
    except ValueError:
        logger.info(f"{SOURCE_NAME}: missing columns {header}, using fallback")
        return dict(FALLBACK_POVERTY)

    result: dict[str, float] = {}
    for row in rows:
        try:
            fips = row[state_idx]
            val = float(row[val_idx])
            result[fips] = round(val, 2)
        except (IndexError, ValueError):
            continue

    if result:
        logger.info(f"{SOURCE_NAME}: poverty data for {len(result)} states (live)")
        return result
    return dict(FALLBACK_POVERTY)


def get_state_aggregates(
    data: dict[str, dict[str, float]],
    indicator_id: str,
) -> dict[str, float]:
    return data.get(indicator_id, {})


def parse_saipe_data() -> dict[str, dict[str, float]]:
    return {"extreme_poverty": get_extreme_poverty()}
