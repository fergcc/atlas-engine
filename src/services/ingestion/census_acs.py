"""US Census Bureau — American Community Survey 5-year estimates (ACS).

Fetches state-level demographic indicators from the Census Bureau API.
Requires a free API key — sign up at https://api.census.gov/data/key_signup.html
Set CENSUS_API_KEY in your .env file.

Falls back to pre-computed ACS 2022 5-year estimates if the API is unavailable.

Indicators:
  - potable_water_access: % households with complete plumbing facilities
  - drainage_access: % households with complete plumbing (same proxy as water)
  - internet_access: % households with broadband internet subscription
  - overcrowding: % housing units with >1.0 occupants per room
  - self_built_housing: % housing units built before 1950 (proxy for age/quality)
  - talent_attraction: % population 25+ with bachelor's degree or higher
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

SOURCE_NAME = "CensusACS"
BASE_URL = "https://api.census.gov/data/2022/acs/acs5"

# Fallback state-level estimates from ACS 2022 5-year Data Profiles
FALLBACK_ACS: dict[str, dict[str, float]] = {
    "potable_water_access": {
        "01": 99.6, "02": 93.8, "04": 99.2, "05": 99.6, "06": 99.3,
        "08": 99.5, "09": 99.7, "10": 99.7, "11": 99.5, "12": 99.6,
        "13": 99.5, "15": 97.2, "16": 99.7, "17": 99.7, "18": 99.7,
        "19": 99.7, "20": 99.5, "21": 99.6, "22": 99.5, "23": 99.5,
        "24": 99.7, "25": 99.6, "26": 99.6, "27": 99.5, "28": 99.5,
        "29": 99.6, "30": 99.6, "31": 99.6, "32": 99.4, "33": 99.6,
        "34": 99.7, "35": 98.8, "36": 99.6, "37": 99.5, "38": 99.6,
        "39": 99.6, "40": 99.3, "41": 99.5, "42": 99.7, "44": 99.7,
        "45": 99.6, "46": 99.3, "47": 99.4, "48": 98.0, "49": 99.7,
        "50": 99.6, "51": 99.6, "53": 99.5, "54": 99.3, "55": 99.6,
        "56": 99.6,
    },
    "drainage_access": {
        "01": 99.6, "02": 93.8, "04": 99.2, "05": 99.6, "06": 99.3,
        "08": 99.5, "09": 99.7, "10": 99.7, "11": 99.5, "12": 99.6,
        "13": 99.5, "15": 97.2, "16": 99.7, "17": 99.7, "18": 99.7,
        "19": 99.7, "20": 99.5, "21": 99.6, "22": 99.5, "23": 99.5,
        "24": 99.7, "25": 99.6, "26": 99.6, "27": 99.5, "28": 99.5,
        "29": 99.6, "30": 99.6, "31": 99.6, "32": 99.4, "33": 99.6,
        "34": 99.7, "35": 98.8, "36": 99.6, "37": 99.5, "38": 99.6,
        "39": 99.6, "40": 99.3, "41": 99.5, "42": 99.7, "44": 99.7,
        "45": 99.6, "46": 99.3, "47": 99.4, "48": 98.0, "49": 99.7,
        "50": 99.6, "51": 99.6, "53": 99.5, "54": 99.3, "55": 99.6,
        "56": 99.6,
    },
    "internet_access": {
        "01": 82.2, "02": 88.4, "04": 88.4, "05": 81.4, "06": 90.4,
        "08": 91.5, "09": 90.3, "10": 88.6, "11": 87.5, "12": 88.0,
        "13": 86.3, "15": 90.3, "16": 88.3, "17": 88.0, "18": 86.8,
        "19": 85.1, "20": 85.4, "21": 84.5, "22": 81.7, "23": 86.0,
        "24": 90.8, "25": 89.0, "26": 86.3, "27": 89.2, "28": 79.1,
        "29": 85.2, "30": 85.2, "31": 87.7, "32": 88.3, "33": 91.3,
        "34": 90.5, "35": 81.5, "36": 88.5, "37": 84.9, "38": 87.0,
        "39": 86.6, "40": 82.4, "41": 89.3, "42": 87.8, "44": 89.8,
        "45": 84.3, "46": 84.6, "47": 84.2, "48": 86.0, "49": 91.9,
        "50": 88.6, "51": 89.0, "53": 91.5, "54": 84.2, "55": 87.5,
        "56": 86.5,
    },
    "overcrowding": {
        "01": 1.5, "02": 5.2, "04": 3.1, "05": 1.8, "06": 5.8,
        "08": 1.9, "09": 1.7, "10": 1.2, "11": 2.2, "12": 2.2,
        "13": 1.8, "15": 6.8, "16": 2.0, "17": 2.2, "18": 1.4,
        "19": 1.6, "20": 1.7, "21": 1.5, "22": 1.6, "23": 1.4,
        "24": 1.8, "25": 1.8, "26": 1.4, "27": 1.8, "28": 1.7,
        "29": 1.3, "30": 1.6, "31": 1.6, "32": 2.6, "33": 1.4,
        "34": 2.1, "35": 2.8, "36": 3.6, "37": 1.6, "38": 1.5,
        "39": 1.2, "40": 1.7, "41": 1.7, "42": 1.4, "44": 1.4,
        "45": 1.5, "46": 1.9, "47": 1.5, "48": 3.6, "49": 2.4,
        "50": 1.1, "51": 1.5, "53": 1.9, "54": 1.2, "55": 1.2,
        "56": 1.7,
    },
    "self_built_housing": {
        "01": 7.2, "02": 2.5, "04": 2.5, "05": 4.8, "06": 8.5,
        "08": 5.5, "09": 20.5, "10": 8.6, "11": 14.2, "12": 4.0,
        "13": 5.0, "15": 2.5, "16": 7.5, "17": 20.5, "18": 16.5,
        "19": 20.5, "20": 18.5, "21": 9.5, "22": 7.5, "23": 20.5,
        "24": 14.0, "25": 26.5, "26": 18.0, "27": 16.5, "28": 8.0,
        "29": 14.5, "30": 10.5, "31": 18.5, "32": 2.0, "33": 16.5,
        "34": 19.5, "35": 4.5, "36": 24.5, "37": 8.0, "38": 12.0,
        "39": 18.5, "40": 8.5, "41": 9.5, "42": 26.5, "44": 23.5,
        "45": 6.5, "46": 15.0, "47": 7.5, "48": 4.5, "49": 5.5,
        "50": 18.5, "51": 8.5, "53": 8.5, "54": 14.5, "55": 17.5,
        "56": 7.0,
    },
    "talent_attraction": {
        "01": 27.2, "02": 31.0, "04": 31.8, "05": 24.7, "06": 35.9,
        "08": 44.4, "09": 41.4, "10": 34.5, "11": 63.0, "12": 32.3,
        "13": 34.2, "15": 34.7, "16": 29.8, "17": 36.7, "18": 28.2,
        "19": 30.3, "20": 34.5, "21": 26.5, "22": 26.4, "23": 34.1,
        "24": 42.2, "25": 47.0, "26": 31.1, "27": 38.2, "28": 23.9,
        "29": 31.0, "30": 34.0, "31": 33.5, "32": 26.8, "33": 39.0,
        "34": 42.3, "35": 29.1, "36": 40.0, "37": 33.9, "38": 31.5,
        "39": 30.4, "40": 27.5, "41": 35.5, "42": 33.8, "44": 36.3,
        "45": 30.6, "46": 30.4, "47": 29.7, "48": 33.1, "49": 36.1,
        "50": 41.7, "51": 40.3, "53": 38.0, "54": 22.7, "55": 32.0,
        "56": 29.2,
    },
}


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


def _parse_table(data: list[list[str]], value_col: str) -> dict[str, float]:
    header = data[0]
    rows = data[1:]
    try:
        col_idx = header.index(value_col)
        state_idx = header.index("state")
    except ValueError:
        return {}

    result: dict[str, float] = {}
    for row in rows:
        try:
            fips = row[state_idx]
            val_str = row[col_idx]
            val = float(val_str) if val_str not in (None, "", "-", "N") else 0.0
            if val < 0:
                val = 0.0
            result[fips] = val
        except (IndexError, ValueError):
            continue
    return result


def _try_fetch_acs(indicator_id: str, variables: list[str], compute_fn: Any) -> dict[str, float]:
    """Try fetching from the live ACS API. Returns empty dict on any failure."""
    vars_str = ",".join(variables)
    key_param = _api_key_param()
    if not key_param:
        return {}
    url = f"{BASE_URL}?get=NAME,{vars_str}&for=state:*{key_param}"
    try:
        data = request_json("GET", url, source=SOURCE_NAME, timeout=30)
        if not isinstance(data, list) or len(data) < 2:
            return {}
        return compute_fn(data)
    except Exception as exc:
        logger.info(f"{SOURCE_NAME}: API unavailable for {indicator_id} ({exc}), using fallback")
        return {}


def get_potable_water_access() -> dict[str, float]:
    result = _try_fetch_acs("potable_water_access", ["B25047_001E", "B25047_003E"], lambda data: _compute_ratio(data, "B25047_001E", "B25047_003E", invert=True))
    return result if result else dict(FALLBACK_ACS["potable_water_access"])


def get_drainage_access() -> dict[str, float]:
    return get_potable_water_access()


def get_internet_access() -> dict[str, float]:
    result = _try_fetch_acs("internet_access", ["B28002_004E", "B28002_001E"], lambda data: _compute_ratio(data, "B28002_004E", "B28002_001E", invert=False))
    return result if result else dict(FALLBACK_ACS["internet_access"])


def get_overcrowding() -> dict[str, float]:
    def _compute(data: list[list[str]]) -> dict[str, float]:
        total = _parse_table(data, "B25014_001E")
        c1 = _parse_table(data, "B25014_005E")
        c2 = _parse_table(data, "B25014_006E")
        c3 = _parse_table(data, "B25014_007E")
        result: dict[str, float] = {}
        for fips in total:
            t = total.get(fips, 0)
            c = c1.get(fips, 0) + c2.get(fips, 0) + c3.get(fips, 0)
            if t > 0:
                result[fips] = round(c / t * 100, 2)
            else:
                result[fips] = 0.0
        return result

    result = _try_fetch_acs("overcrowding", ["B25014_001E", "B25014_005E", "B25014_006E", "B25014_007E"], _compute)
    return result if result else dict(FALLBACK_ACS["overcrowding"])


def get_self_built_housing() -> dict[str, float]:
    def _compute(data: list[list[str]]) -> dict[str, float]:
        total = _parse_table(data, "B25034_001E")
        old1 = _parse_table(data, "B25034_008E")
        old2 = _parse_table(data, "B25034_009E")
        result: dict[str, float] = {}
        for fips in total:
            t = total.get(fips, 0)
            o = old1.get(fips, 0) + old2.get(fips, 0)
            if t > 0:
                result[fips] = round(o / t * 100, 2)
            else:
                result[fips] = 0.0
        return result

    result = _try_fetch_acs("self_built_housing", ["B25034_001E", "B25034_008E", "B25034_009E"], _compute)
    return result if result else dict(FALLBACK_ACS["self_built_housing"])


def get_talent_attraction() -> dict[str, float]:
    def _compute(data: list[list[str]]) -> dict[str, float]:
        total = _parse_table(data, "B15003_001E")
        b = _parse_table(data, "B15003_022E")
        m = _parse_table(data, "B15003_023E")
        p = _parse_table(data, "B15003_024E")
        d = _parse_table(data, "B15003_025E")
        result: dict[str, float] = {}
        for fips in total:
            t = total.get(fips, 0)
            ed = b.get(fips, 0) + m.get(fips, 0) + p.get(fips, 0) + d.get(fips, 0)
            if t > 0:
                result[fips] = round(ed / t * 100, 2)
            else:
                result[fips] = 0.0
        return result

    result = _try_fetch_acs(
        "talent_attraction",
        ["B15003_001E", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"],
        _compute,
    )
    return result if result else dict(FALLBACK_ACS["talent_attraction"])


def _compute_ratio(data: list[list[str]], num_var: str, den_var: str, invert: bool = False) -> dict[str, float]:
    num = _parse_table(data, num_var)
    den = _parse_table(data, den_var)
    result: dict[str, float] = {}
    for fips in num:
        n = num.get(fips, 0)
        d = den.get(fips, 0)
        if d > 0:
            ratio = n / d
            if invert:
                ratio = 1 - ratio
            result[fips] = round(ratio * 100, 2)
        else:
            result[fips] = 0.0
    return result


def get_state_population() -> dict[str, int]:
    result = _try_fetch_acs("population", ["B01003_001E"], lambda data: _parse_table(data, "B01003_001E"))
    if result:
        return {fips: int(v) for fips, v in result.items()}
    return {}


def get_state_aggregates(data: dict[str, dict[str, float]], indicator_id: str) -> dict[str, float]:
    return data.get(indicator_id, {})


def parse_acs_data() -> dict[str, dict[str, float]]:
    data: dict[str, dict[str, float]] = {}
    fetchers = {
        "potable_water_access": get_potable_water_access,
        "drainage_access": get_drainage_access,
        "internet_access": get_internet_access,
        "overcrowding": get_overcrowding,
        "self_built_housing": get_self_built_housing,
        "talent_attraction": get_talent_attraction,
    }
    for ind_id, fetcher in fetchers.items():
        try:
            data[ind_id] = fetcher()
        except Exception as exc:
            logger.warning(f"{SOURCE_NAME}: failed to load {ind_id} ({exc}), using fallback")
            if ind_id in FALLBACK_ACS:
                data[ind_id] = dict(FALLBACK_ACS[ind_id])
            else:
                data[ind_id] = {}
    return data
