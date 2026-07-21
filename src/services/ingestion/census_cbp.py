"""US Census Bureau — County Business Patterns (CBP) state-level aggregates.

Fetches state-level establishment counts from the Census Bureau API.
Requires a free API key — sign up at https://api.census.gov/data/key_signup.html
Set CENSUS_API_KEY in your .env file.

Falls back to pre-computed estimates if API is unavailable.

Indicators:
  - foreign_capital_presence: manufacturing establishments (NAICS 31-33)
  - daycare_services: child day care services establishments (NAICS 624410)
  - innovation_economic_units: scientific R&D + computer systems design
    establishments (NAICS 5417 + 5415)
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

SOURCE_NAME = "CensusCBP"
BASE_URL = "https://api.census.gov/data/2022/cbp"

_NAICS_MANUFACTURING = "31-33"
_NAICS_DAYCARE = "624410"
_NAICS_RD = "5417"
_NAICS_CSD = "5415"

# Fallback state-level manufacturing establishment counts (2022 CBP)
# Values rounded to nearest 100 for readability
FALLBACK_CBP: dict[str, dict[str, int]] = {
    "foreign_capital_presence": {
        "01": 5800, "02": 800, "04": 5200, "05": 4200, "06": 36000,
        "08": 5600, "09": 5100, "10": 900, "11": 200, "12": 18000,
        "13": 8800, "15": 800, "16": 2700, "17": 16000, "18": 8400,
        "19": 3300, "20": 3400, "21": 4800, "22": 3200, "23": 2300,
        "24": 5200, "25": 8100, "26": 12900, "27": 8800, "28": 2800,
        "29": 6700, "30": 1700, "31": 2200, "32": 2600, "33": 3000,
        "34": 9400, "35": 1700, "36": 18400, "37": 9400, "38": 1100,
        "39": 16400, "40": 3600, "41": 6300, "42": 15900, "44": 1100,
        "45": 4600, "46": 1200, "47": 7000, "48": 21000, "49": 3600,
        "50": 1400, "51": 6500, "53": 7300, "54": 1700, "55": 12000,
        "56": 700,
    },
    "daycare_services": {
        "01": 1900, "02": 300, "04": 1600, "05": 1200, "06": 11000,
        "08": 1500, "09": 1200, "10": 400, "11": 200, "12": 5700,
        "13": 2900, "15": 300, "16": 700, "17": 4600, "18": 2100,
        "19": 900, "20": 1000, "21": 1400, "22": 1100, "23": 600,
        "24": 1800, "25": 2600, "26": 3100, "27": 2200, "28": 900,
        "29": 2000, "30": 500, "31": 700, "32": 700, "33": 800,
        "34": 2900, "35": 600, "36": 6400, "37": 3000, "38": 400,
        "39": 4600, "40": 1100, "41": 1700, "42": 4600, "44": 400,
        "45": 1500, "46": 400, "47": 2000, "48": 7400, "49": 800,
        "50": 400, "51": 2000, "53": 2100, "54": 500, "55": 2800,
        "56": 300,
    },
    "innovation_economic_units": {
        "01": 3100, "02": 500, "04": 3100, "05": 1100, "06": 26000,
        "08": 4900, "09": 2800, "10": 900, "11": 800, "12": 10800,
        "13": 5800, "15": 400, "16": 900, "17": 7200, "18": 3400,
        "19": 1500, "20": 1600, "21": 1900, "22": 1500, "23": 1200,
        "24": 4500, "25": 5400, "26": 5800, "27": 4800, "28": 900,
        "29": 3200, "30": 800, "31": 1000, "32": 1600, "33": 2000,
        "34": 5600, "35": 2800, "36": 10200, "37": 5200, "38": 500,
        "39": 7400, "40": 1600, "41": 3200, "42": 7800, "44": 800,
        "45": 2300, "46": 500, "47": 3100, "48": 14700, "49": 2800,
        "50": 700, "51": 6600, "53": 6200, "54": 800, "55": 3800,
        "56": 300,
    },
}


_MANUFACTURING_CACHE: dict[str, int] | None = None
_DAYCARE_CACHE: dict[str, int] | None = None
_RD_CACHE: dict[str, int] | None = None
_CSD_CACHE: dict[str, int] | None = None


def _get_api_key() -> str:
    api_key = os.getenv("CENSUS_API_KEY")
    if not api_key:
        raise MissingCredentialError(
            "CENSUS_API_KEY no está definido. Regístrate (gratis) en "
            "https://api.census.gov/data/key_signup.html "
            "y agrega la key a tu archivo .env"
        )
    return api_key


def _api_key_param() -> str:
    try:
        return f"&key={_get_api_key()}"
    except MissingCredentialError:
        return ""


def _query_cbp(naics: str, label: str) -> dict[str, int] | None:
    """Query the CBP API. Returns None on failure (API key missing, network, etc)."""
    key_param = _api_key_param()
    if not key_param:
        return None
    url = f"{BASE_URL}?get=NAME,ESTAB,EMP&for=state:*&NAICS2017={naics}{key_param}"
    try:
        data = request_json("GET", url, source=SOURCE_NAME, timeout=30)
        if not isinstance(data, list) or len(data) < 2:
            return None
        header = data[0]
        rows = data[1:]
        try:
            estab_idx = header.index("ESTAB")
            state_idx = header.index("state")
        except ValueError:
            return None

        result: dict[str, int] = {}
        for row in rows:
            try:
                fips = row[state_idx]
                estab = int(float(row[estab_idx])) if row[estab_idx] not in (None, "", "N") else 0
                result[fips] = result.get(fips, 0) + estab
            except (IndexError, ValueError):
                continue
        if result:
            logger.info(f"{SOURCE_NAME}: {label} for {len(result)} states (live)")
            return result
    except Exception as exc:
        logger.info(f"{SOURCE_NAME}: API unavailable for {label} ({exc})")
    return None


def get_foreign_capital_presence() -> dict[str, float]:
    global _MANUFACTURING_CACHE
    if _MANUFACTURING_CACHE is not None:
        return {k: float(v) for k, v in _MANUFACTURING_CACHE.items()}
    live = _query_cbp(_NAICS_MANUFACTURING, "manufacturing")
    if live:
        _MANUFACTURING_CACHE = live
    else:
        _MANUFACTURING_CACHE = dict(FALLBACK_CBP["foreign_capital_presence"])
        logger.info(f"{SOURCE_NAME}: using fallback for manufacturing ({len(_MANUFACTURING_CACHE)} states)")
    return {k: float(v) for k, v in _MANUFACTURING_CACHE.items()}


def get_daycare_services() -> dict[str, float]:
    global _DAYCARE_CACHE
    if _DAYCARE_CACHE is not None:
        return {k: float(v) for k, v in _DAYCARE_CACHE.items()}
    live = _query_cbp(_NAICS_DAYCARE, "daycare")
    if live:
        _DAYCARE_CACHE = live
    else:
        _DAYCARE_CACHE = dict(FALLBACK_CBP["daycare_services"])
        logger.info(f"{SOURCE_NAME}: using fallback for daycare ({len(_DAYCARE_CACHE)} states)")
    return {k: float(v) for k, v in _DAYCARE_CACHE.items()}


def get_innovation_economic_units() -> dict[str, float]:
    global _RD_CACHE, _CSD_CACHE
    live_rd = _query_cbp(_NAICS_RD, "R&D")
    live_csd = _query_cbp(_NAICS_CSD, "CSD")
    if live_rd and live_csd:
        _RD_CACHE = live_rd
        _CSD_CACHE = live_csd
    else:
        _RD_CACHE = {}
        _CSD_CACHE = {}
        fallback = FALLBACK_CBP["innovation_economic_units"]
        logger.info(f"{SOURCE_NAME}: using fallback for innovation ({len(fallback)} states)")
        return {k: float(v) for k, v in fallback.items()}

    result: dict[str, float] = {}
    all_fips = set(_RD_CACHE.keys()) | set(_CSD_CACHE.keys())
    for fips in all_fips:
        result[fips] = float(_RD_CACHE.get(fips, 0) + _CSD_CACHE.get(fips, 0))
    return result


def get_state_counts(
    data: dict[str, dict[str, int]],
    indicator_id: str,
) -> dict[str, int]:
    return data.get(indicator_id, {})


def get_cbp_counts() -> dict[str, dict[str, int]] | None:
    data: dict[str, dict[str, int]] = {}
    fetchers: dict[str, Any] = {
        "foreign_capital_presence": get_foreign_capital_presence,
        "daycare_services": get_daycare_services,
        "innovation_economic_units": get_innovation_economic_units,
    }
    for ind_id, fetcher in fetchers.items():
        try:
            raw = fetcher()
            data[ind_id] = {k: int(v) for k, v in raw.items()}
        except Exception as exc:
            logger.warning(f"{SOURCE_NAME}: failed to load {ind_id} ({exc}), using fallback")
            fallback = FALLBACK_CBP.get(ind_id, {})
            data[ind_id] = dict(fallback)
    return data if data else None
