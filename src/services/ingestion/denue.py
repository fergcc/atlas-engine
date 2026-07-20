"""INEGI DENUE — Directorio Estadístico Nacional de Unidades Económicas.

Queries the DENUE API to count establishments by activity and geographic area.

Methods used:
  - Cuantificar: count by SCIAN code + state (fast, single call)
  - BuscarEntidad: keyword search with pagination for non-SCIAN categories

Indicators:
  - foreign_capital_presence (2): manufacturing establishments (proxy)
  - daycare_services (18): "guardería" keyword search
  - innovation_economic_units (4): R&D + high-tech SCIAN codes

Token: INEGI_TOKEN works for both BIE and DENUE.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import DATA_DIR, settings

logger = logging.getLogger(__name__)

SOURCE_NAME = "DENUE"
BASE_URL = "https://www.inegi.org.mx/app/api/denue/v1/consulta"
CACHE_DIR = DATA_DIR / "denue"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "denue_counts.json"
CACHE_TTL = 86400  # 24 hours

PAGE_SIZE = 1000  # Max per request

# SCIAN codes for Cuantificar queries
SCIAN_QUERIES: dict[str, list[str]] = {
    "foreign_capital_presence": ["31", "32", "33"],  # All manufacturing
    "innovation_economic_units": [
        "5417", "5415",  # R&D, IT
        "334", "335", "3364",  # High-tech manufacturing
    ],
}

# Keyword queries for BuscarEntidad (paginated)
KEYWORD_QUERIES: dict[str, str] = {
    "daycare_services": "guardería",
}


def _get_token() -> str:
    token = settings.inegi_token
    if not token:
        raise RuntimeError(f"{SOURCE_NAME}: INEGI_TOKEN not configured")
    return token


def _load_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text())
        age = time.time() - data.get("_cached_at", 0)
        if age < CACHE_TTL:
            logger.info(f"{SOURCE_NAME}: cache hit ({age:.0f}s old)")
            return data
    except Exception:
        pass
    return None


def _save_cache(data: dict) -> None:
    data["_cached_at"] = time.time()
    CACHE_FILE.write_text(json.dumps(data, indent=2))


def _query_cuantificar(scían_code: str, state_code: str) -> int:
    token = _get_token()
    url = f"{BASE_URL}/Cuantificar/{scían_code}/{state_code}/0/{token}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    total = 0
    if isinstance(data, list):
        for item in data:
            total += int(item.get("Total", 0))
    return total


def _count_by_keyword(keyword: str, state_code: str) -> int:
    """Count establishments matching keyword in a state, with pagination."""
    token = _get_token()
    keyword_enc = urllib.parse.quote(keyword, safe="")

    # First call to check count
    url = f"{BASE_URL}/BuscarEntidad/{keyword_enc}/{state_code}/1/{PAGE_SIZE}/{token}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning(f"{SOURCE_NAME}: keyword search failed for '{keyword}' in {state_code}: {exc}")
        return 0

    if not isinstance(data, list):
        return 0

    total = len(data)
    if total < PAGE_SIZE:
        return total

    # Paginate
    page = 2
    while True:
        start = (page - 1) * PAGE_SIZE + 1
        url = f"{BASE_URL}/BuscarEntidad/{keyword_enc}/{state_code}/{start}/{page * PAGE_SIZE}/{token}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                page_data = json.loads(resp.read())
        except Exception:
            break
        if not isinstance(page_data, list) or len(page_data) == 0:
            break
        total += len(page_data)
        page += 1
        time.sleep(0.3)

    return total


def get_denue_counts(*, force_refresh: bool = False) -> dict[str, dict[str, int]]:
    """Returns establishment counts per indicator per state.

    Returns: {indicator_id: {state_code: total_establishments}}
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

    states = [f"{i:02d}" for i in range(1, 33)]

    # Count total queries
    n_cuant = sum(len(codes) for codes in SCIAN_QUERIES.values()) * len(states)
    n_kw = len(KEYWORD_QUERIES) * len(states)
    total_queries = n_cuant + n_kw

    result: dict[str, dict[str, int]] = {
        ind_id: {} for ind_id in list(SCIAN_QUERIES.keys()) + list(KEYWORD_QUERIES.keys())
    }

    done = 0
    logger.info(f"{SOURCE_NAME}: starting {total_queries} queries...")

    def log_progress():
        if done % 40 == 0 and done > 0:
            logger.info(f"{SOURCE_NAME}: {done}/{total_queries} queries...")

    for ind_id, scian_codes in SCIAN_QUERIES.items():
        state_totals: dict[str, int] = {}
        for state in states:
            total = 0
            for code in scian_codes:
                try:
                    total += _query_cuantificar(code, state)
                    done += 1
                    log_progress()
                except Exception as exc:
                    logger.debug(f"  {code}/{state}: {exc}")
                    done += 1
            state_totals[state] = total
            time.sleep(0.1)  # Rate limit safety
        result[ind_id] = state_totals

    for ind_id, keyword in KEYWORD_QUERIES.items():
        state_totals: dict[str, int] = {}
        for state in states:
            try:
                state_totals[state] = _count_by_keyword(keyword, state)
                done += 1
                log_progress()
            except Exception as exc:
                logger.debug(f"  keyword/{state}: {exc}")
                state_totals[state] = 0
                done += 1
            time.sleep(0.2)
        result[ind_id] = state_totals

    logger.info(f"{SOURCE_NAME}: done ({done}/{total_queries} queries)")

    if any(v for v in result.values()):
        _save_cache(result)

    return result


def get_state_counts(
    denue_data: dict[str, dict[str, int]],
    indicator_id: str,
) -> dict[str, int]:
    return denue_data.get(indicator_id, {})
