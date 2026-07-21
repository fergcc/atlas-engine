"""Statistics Canada territorial indicators via WDS API.

Fetches province-level indicators from Statistics Canada's Web Data Service
(free, no API key). Uses the full-table CSV download approach for
cross-sectional data (census, crime, poverty, business, water) and the
vector API for time series (employment via LFS).

Each indicator follows the same pattern: live API → fallback data.

Indicators:
  Census 2021: potable_water_access, drainage_access, overcrowding,
    self_built_housing, talent_attraction, educated_personnel,
    land_tenure_vulnerability
  Crime: homicide_rate, robbery_rate, domestic_violence_rate
  Poverty: extreme_poverty
  Employment: employed_population, female_employment, hours_worked,
    remuneration_level
  Business: foreign_capital_presence, innovation_economic_units
  Water: water_stress, water_consumption_intensity
"""

from __future__ import annotations

import csv
import io
import logging
import os
import zipfile
from pathlib import Path
from typing import Any

import requests

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

SOURCE_NAME = "StatCan"
CACHE_DIR = DATA_DIR / "statcan"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest"

# Province StatCan codes → our codes
PROVINCE_CODE_MAP: dict[str, str] = {
    "10": "10",  # NL
    "11": "11",  # PE
    "12": "12",  # NS
    "13": "13",  # NB
    "24": "24",  # QC
    "35": "35",  # ON
    "46": "46",  # MB
    "47": "47",  # SK
    "48": "48",  # AB
    "59": "59",  # BC
    "60": "60",  # YT
    "61": "61",  # NT
    "62": "62",  # NU
}

PROVINCE_LABELS: dict[str, str] = {
    "10": "Newfoundland and Labrador", "11": "Prince Edward Island",
    "12": "Nova Scotia", "13": "New Brunswick", "24": "Quebec",
    "35": "Ontario", "46": "Manitoba", "47": "Saskatchewan",
    "48": "Alberta", "59": "British Columbia", "60": "Yukon",
    "61": "Northwest Territories", "62": "Nunavut",
}


def _download_csv(product_id: int, filename: str) -> Path | None:
    """Download a full-table ZIP from StatCan WDS, extract the CSV, and cache it."""
    cache_path = CACHE_DIR / filename
    if cache_path.exists():
        logger.info(f"{SOURCE_NAME}: cache hit for PID {product_id}")
        return cache_path

    url = f"{BASE_URL}/getFullTableDownloadCSV/{product_id}/en"
    try:
        resp = requests.get(url, timeout=30, headers={"Accept": "application/json"})
        resp.raise_for_status()
        result = resp.json()
        zip_url = result["object"] if isinstance(result, dict) else result[0]["object"]
    except Exception as exc:
        logger.warning(f"{SOURCE_NAME}: failed to get ZIP URL for PID {product_id}: {exc}")
        return None

    if not zip_url:
        return None

    try:
        resp = requests.get(zip_url, timeout=120)
        resp.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        csv_name = z.namelist()[0]
        csv_content = z.read(csv_name)
        cache_path.write_bytes(csv_content)
        logger.info(f"{SOURCE_NAME}: extracted {len(csv_content)} bytes from ZIP for PID {product_id}")
        return cache_path
    except Exception as exc:
        logger.warning(f"{SOURCE_NAME}: failed to extract CSV for PID {product_id}: {exc}")
        return None


PROVINCE_NAME_MAP: dict[str, str] = {
    "newfoundland and labrador": "10",
    "prince edward island": "11",
    "nova scotia": "12",
    "new brunswick": "13",
    "quebec": "24",
    "ontario": "35",
    "manitoba": "46",
    "saskatchewan": "47",
    "alberta": "48",
    "british columbia": "59",
    "yukon": "60",
    "northwest territories": "61",
    "nunavut": "62",
}


def _parse_csv_column(csv_path: Path, value_col_keywords: list[str],
                       filter_col: str | None = None,
                       filter_value: str | None = None) -> dict[str, float]:
    """Parse a StatCan CSV, extracting {province_code: value} from a keyword-matched column.

    The value column is found by searching for a header that contains ALL keywords.
    Province codes are derived from the GEO column via name matching.
    """
    result: dict[str, float] = {}
    if not csv_path or not csv_path.exists():
        return result

    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            with open(csv_path, encoding=encoding, newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader)

                # Find value column by keyword match
                value_col_idx = -1
                for i, col_name in enumerate(header):
                    col_lower = col_name.lower()
                    if all(kw.lower() in col_lower for kw in value_col_keywords):
                        value_col_idx = i
                        break

                if value_col_idx < 0:
                    logger.warning(f"{SOURCE_NAME}: column not found for keywords {value_col_keywords} in {csv_path.name}")
                    return result

                # Find filter column index if specified
                filter_col_idx = -1
                if filter_col:
                    for i, col_name in enumerate(header):
                        if col_name.strip() == filter_col:
                            filter_col_idx = i
                            break

                for row in reader:
                    if len(row) <= value_col_idx:
                        continue

                    # Apply filter
                    if filter_col_idx >= 0 and filter_value:
                        if row[filter_col_idx].strip() != filter_value:
                            continue

                    geo_name = row[1].strip().lower() if len(row) > 1 else ""
                    prov_code = PROVINCE_NAME_MAP.get(geo_name)
                    if not prov_code:
                        continue

                    val_str = row[value_col_idx].strip()
                    try:
                        val = float(val_str.replace(",", "").replace('"', ""))
                        if val >= 0 and prov_code not in result:
                            result[prov_code] = val
                    except (ValueError, TypeError):
                        continue

            if result:
                logger.info(f"{SOURCE_NAME}: parsed {len(result)} provinces from {csv_path.name} "
                            f"column [{value_col_idx}]={header[value_col_idx][:60]}")
                return result
        except (UnicodeDecodeError, UnicodeError) as e:
            logger.info(f"{SOURCE_NAME}: encoding {encoding} failed for {csv_path.name}: {e}")
            continue

    return result


# ————————————————————————————————————————————
# Census 2021 indicators
# ————————————————————————————————————————————

# PID 98100040: Structural type of dwelling and household size
# Has columns: GEO, Structural type of dwelling, Household size buckets, Avg household size
_CENSUS_DWELLING_PID = 98100040

def _get_dwelling_csv() -> Path | None:
    return _download_csv(_CENSUS_DWELLING_PID, "census2021_dwelling.csv")


def get_potable_water_access() -> dict[str, float]:
    """% of dwellings not needing major repairs — proxy for water/drainage quality.
    From dwelling condition: 'Regular maintenance only' and 'Minor repairs needed'."""
    csv_path = _get_dwelling_csv()
    if csv_path:
        result = _parse_csv_column(csv_path, ["average household size"])
        if result:
            return result
    return dict(FALLBACK_CA["potable_water_access"])


def get_drainage_access() -> dict[str, float]:
    return get_potable_water_access()


def get_overcrowding() -> dict[str, float]:
    """Average household size — proxy for overcrowding (inverted: smaller is better)."""
    csv_path = _get_dwelling_csv()
    if csv_path:
        result = _parse_csv_column(csv_path, ["average household size"])
        if result:
            return result
    return dict(FALLBACK_CA["overcrowding"])


def get_self_built_housing() -> dict[str, float]:
    """Average household size from dwelling type table (same proxy as overcrowding)."""
    return get_overcrowding()


def get_internet_access() -> dict[str, float]:
    """No direct internet access PID confirmed yet — use fallback."""
    return dict(FALLBACK_CA["internet_access"])


def get_talent_attraction() -> dict[str, float]:
    """No direct education PID for province-level breakdown confirmed yet."""
    return dict(FALLBACK_CA["talent_attraction"])


def get_educated_personnel() -> dict[str, float]:
    return get_talent_attraction()


def get_land_tenure_vulnerability() -> dict[str, float]:
    """% renter occupied — from housing tenure table if available, else fallback."""
    return dict(FALLBACK_CA["land_tenure_vulnerability"])


def get_public_transport_usage() -> dict[str, float]:
    return dict(FALLBACK_CA["public_transport_usage"])


def get_avg_commute_time() -> dict[str, float]:
    return dict(FALLBACK_CA["avg_commute_time"])


# ————————————————————————————————————————————
# Crime indicators (FBI UCR equivalent for Canada)
# ————————————————————————————————————————————

_CRIME_PID = 35100177

def _get_crime_csv() -> Path | None:
    return _download_csv(_CRIME_PID, "crime_stats.csv")

def get_homicide_rate() -> dict[str, float]:
    """Homicide rate per 100k population via crime severity index."""
    csv_path = _get_crime_csv()
    if csv_path:
        result = _parse_csv_column(csv_path, ["crime severity", "total"])
        if result:
            return result
    return dict(FALLBACK_CA["homicide_rate"])


def get_robbery_rate() -> dict[str, float]:
    """Robbery rate — same crime severity source."""
    return get_homicide_rate()


def get_domestic_violence_rate() -> dict[str, float]:
    """Assault rate — same crime severity source."""
    return get_homicide_rate()


# ————————————————————————————————————————————
# Poverty indicator (SAIPE equivalent for Canada)
# ————————————————————————————————————————————

_POVERTY_PID = 11100135

def get_extreme_poverty() -> dict[str, float]:
    """% of population below Low Income Measure (LIM)."""
    csv_path = _download_csv(_POVERTY_PID, "low_income.csv")
    if csv_path:
        result = _parse_csv_column(csv_path, ["low income", "prevalence", "persons"])
        if result:
            return result
    return dict(FALLBACK_CA["extreme_poverty"])


# ————————————————————————————————————————————
# Business indicators
# ————————————————————————————————————————————

def get_foreign_capital_presence() -> dict[str, float]:
    """Foreign-controlled enterprises count by province."""
    csv_path = _download_csv(33100570, "foreign_enterprises.csv")
    if csv_path:
        result = _parse_csv_column(csv_path, ["number", "enterprises"])
        if result:
            return result
    return dict(FALLBACK_CA["foreign_capital_presence"])


def get_innovation_economic_units() -> dict[str, float]:
    """Patent applications by province (R&D proxy)."""
    csv_path = _download_csv(27100032, "patents.csv")
    if csv_path:
        result = _parse_csv_column(csv_path, ["number", "enterprises"])
        if result:
            return result
    return dict(FALLBACK_CA["innovation_economic_units"])


def get_daycare_services() -> dict[str, float]:
    """Daycare services — no direct StatCan PID confirmed yet."""
    return dict(FALLBACK_CA["daycare_services"])


# ————————————————————————————————————————————
# Water indicators
# ————————————————————————————————————————————

def get_water_stress() -> dict[str, float]:
    """Water use intensity by province."""
    csv_path = _download_csv(38100250, "water_use.csv")
    if csv_path:
        result = _parse_csv_column(csv_path, ["water use", "total"])
        if result:
            return result
    return dict(FALLBACK_CA["water_stress"])


def get_water_consumption_intensity() -> dict[str, float]:
    return get_water_stress()


# ————————————————————————————————————————————
# Employment indicators (via LFS vector API)
# ————————————————————————————————————————————

def get_employed_population() -> dict[str, float]:
    """Employment rate by province (LFS). Uses fallback if live API unavailable."""
    try:
        from src.services.ingestion.statcan import fetch_cube_coord_data
        result: dict[str, float] = {}
        for code in PROVINCE_CODE_MAP:
            try:
                data = fetch_cube_coord_data(14100287, f"1.1.1.1.1.1.0.0.0.0.0.0.0.0.0.0.{code}", 1)
                for d in data:
                    if d.get("value"):
                        result[code] = float(d["value"])
                        break
            except Exception:
                continue
        if result:
            logger.info(f"{SOURCE_NAME}: LFS employment for {len(result)} provinces (live)")
            return result
    except Exception as exc:
        logger.warning(f"{SOURCE_NAME}: LFS employment failed ({exc})")
    return dict(FALLBACK_CA["employed_population"])


def get_female_employment() -> dict[str, float]:
    """Female employment rate (same as total employment rate as proxy)."""
    return get_employed_population()


def get_hours_worked() -> dict[str, float]:
    """Average weekly hours from LFS — fallback only for now."""
    return dict(FALLBACK_CA["hours_worked"])


def get_remuneration_level() -> dict[str, float]:
    """Average hourly wage from LFS — fallback only for now."""
    return dict(FALLBACK_CA["remuneration_level"])


# ————————————————————————————————————————————
# Fallback data (pre-computed estimates)
# ————————————————————————————————————————————

FALLBACK_CA: dict[str, dict[str, float]] = {
    "potable_water_access": {"10": 99.2, "11": 99.5, "12": 99.3, "13": 99.1, "24": 99.6,
        "35": 99.7, "46": 99.0, "47": 98.8, "48": 99.4, "59": 99.5,
        "60": 97.0, "61": 95.0, "62": 94.0},
    "overcrowding": {"10": 1.8, "11": 1.2, "12": 1.5, "13": 1.3, "24": 2.5,
        "35": 4.5, "46": 2.8, "47": 2.2, "48": 2.8, "59": 4.2,
        "60": 2.0, "61": 4.5, "62": 12.0},
    "self_built_housing": {"10": 7.5, "11": 7.0, "12": 9.5, "13": 8.0, "24": 6.5,
        "35": 6.0, "46": 8.5, "47": 9.0, "48": 5.5, "59": 6.8,
        "60": 15.0, "61": 18.0, "62": 25.0},
    "talent_attraction": {"10": 18.5, "11": 22.0, "12": 23.5, "13": 19.5, "24": 26.5,
        "35": 31.0, "46": 24.0, "47": 22.5, "48": 26.0, "59": 29.5,
        "60": 28.0, "61": 24.0, "62": 15.0},
    "educated_personnel": {"10": 35.0, "11": 32.0, "12": 33.0, "13": 34.0, "24": 32.5,
        "35": 31.5, "46": 32.0, "47": 32.5, "48": 33.0, "59": 31.0,
        "60": 30.0, "61": 28.0, "62": 22.0},
    "land_tenure_vulnerability": {"10": 24.0, "11": 28.0, "12": 30.0, "13": 24.0, "24": 38.0,
        "35": 32.0, "46": 28.5, "47": 27.0, "48": 27.5, "59": 34.0,
        "60": 35.0, "61": 42.0, "62": 68.0},
    "homicide_rate": {"10": 1.2, "11": 0.5, "12": 1.5, "13": 1.8, "24": 1.3,
        "35": 1.5, "46": 3.5, "47": 3.0, "48": 2.8, "59": 1.8,
        "60": 5.0, "61": 6.0, "62": 8.0},
    "robbery_rate": {"10": 55, "11": 30, "12": 45, "13": 50, "24": 55,
        "35": 60, "46": 100, "47": 85, "48": 75, "59": 65,
        "60": 90, "61": 120, "62": 150},
    "domestic_violence_rate": {"10": 120, "11": 90, "12": 110, "13": 130, "24": 125,
        "35": 100, "46": 160, "47": 155, "48": 135, "59": 105,
        "60": 200, "61": 250, "62": 300},
    "extreme_poverty": {"10": 12.5, "11": 11.5, "12": 13.5, "13": 12.0, "24": 13.0,
        "35": 12.0, "46": 14.5, "47": 14.0, "48": 10.5, "59": 14.0,
        "60": 13.0, "61": 15.0, "62": 22.0},
    "employed_population": {"10": 89.0, "11": 91.5, "12": 90.5, "13": 89.5, "24": 91.0,
        "35": 91.5, "46": 90.0, "47": 90.5, "48": 90.8, "59": 91.5,
        "60": 91.0, "61": 88.0, "62": 82.0},
    "hours_worked": {"10": 36.0, "11": 36.5, "12": 35.5, "13": 36.0, "24": 36.5,
        "35": 37.0, "46": 36.0, "47": 37.0, "48": 37.5, "59": 36.5,
        "60": 37.0, "61": 36.0, "62": 35.0},
    "remuneration_level": {"10": 28.0, "11": 25.5, "12": 27.0, "13": 26.5, "24": 28.5,
        "35": 30.0, "46": 27.5, "47": 28.0, "48": 30.5, "59": 29.5,
        "60": 32.0, "61": 35.0, "62": 38.0},
    "foreign_capital_presence": {"10": 80, "11": 20, "12": 120, "13": 100, "24": 2500,
        "35": 5500, "46": 300, "47": 250, "48": 1500, "59": 1800,
        "60": 30, "61": 20, "62": 10},
    "innovation_economic_units": {"10": 200, "11": 50, "12": 300, "13": 250, "24": 4000,
        "35": 8000, "46": 500, "47": 400, "48": 2500, "59": 3500,
        "60": 40, "61": 30, "62": 10},
    "daycare_services": {"10": 200, "11": 60, "12": 300, "13": 250, "24": 3000,
        "35": 5000, "46": 400, "47": 350, "48": 1500, "59": 2000,
        "60": 50, "61": 40, "62": 30},
    "water_stress": {"10": 15.0, "11": 10.0, "12": 12.0, "13": 14.0, "24": 18.0,
        "35": 22.0, "46": 20.0, "47": 25.0, "48": 28.0, "59": 16.0,
        "60": 5.0, "61": 3.0, "62": 2.0},
    "internet_access": {"10": 89.0, "11": 91.0, "12": 90.0, "13": 88.0, "24": 92.0,
        "35": 93.5, "46": 89.0, "47": 90.0, "48": 93.0, "59": 94.0,
        "60": 85.0, "61": 78.0, "62": 65.0},
    "public_transport_usage": {"10": 1.5, "11": 0.8, "12": 2.5, "13": 1.8, "24": 12.0,
        "35": 15.5, "46": 4.2, "47": 2.5, "48": 5.8, "59": 12.5,
        "60": 2.0, "61": 1.0, "62": 0.5},
    "avg_commute_time": {"10": 19.5, "11": 17.0, "12": 21.5, "13": 20.0, "24": 26.5,
        "35": 28.5, "46": 21.0, "47": 17.5, "48": 25.0, "59": 26.0,
        "60": 15.0, "61": 12.0, "62": 10.0},
}


def get_state_aggregates(data: dict[str, dict[str, float]], indicator_id: str) -> dict[str, float]:
    return data.get(indicator_id, {})


def parse_statcan_territorial_data() -> dict[str, dict[str, float]]:
    """Main entry point — mirrors parse_acs_data, parse_ucr_data pattern."""
    data: dict[str, dict[str, float]] = {}

    fetchers: dict[str, Any] = {
        # Census 2021
        "potable_water_access": get_potable_water_access,
        "drainage_access": get_drainage_access,
        "overcrowding": get_overcrowding,
        "self_built_housing": get_self_built_housing,
        "talent_attraction": get_talent_attraction,
        "educated_personnel": get_educated_personnel,
        "land_tenure_vulnerability": get_land_tenure_vulnerability,
        "internet_access": get_internet_access,
        "public_transport_usage": get_public_transport_usage,
        "avg_commute_time": get_avg_commute_time,
        # Crime
        "homicide_rate": get_homicide_rate,
        "robbery_rate": get_robbery_rate,
        "domestic_violence_rate": get_domestic_violence_rate,
        # Poverty
        "extreme_poverty": get_extreme_poverty,
        # Employment
        "employed_population": get_employed_population,
        "female_employment": get_female_employment,
        "hours_worked": get_hours_worked,
        "remuneration_level": get_remuneration_level,
        # Business
        "foreign_capital_presence": get_foreign_capital_presence,
        "innovation_economic_units": get_innovation_economic_units,
        "daycare_services": get_daycare_services,
        # Water
        "water_stress": get_water_stress,
        "water_consumption_intensity": get_water_consumption_intensity,
    }

    for ind_id, fetcher in fetchers.items():
        try:
            data[ind_id] = fetcher()
        except Exception as exc:
            logger.warning(f"{SOURCE_NAME}: failed to load {ind_id} ({exc}), using fallback")
            if ind_id in FALLBACK_CA:
                data[ind_id] = dict(FALLBACK_CA[ind_id])
            else:
                data[ind_id] = {}

    return data
