"""
WIPO PATENTSCOPE API — Patent data for innovation indicators.

Free, requires registration at https://www.wipo.int/
Uses WIPO IP Statistics Data Center API.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import settings
from src.services.trade._base import TradeAPIError, fetch_json

logger = logging.getLogger(__name__)

SOURCE_NAME = "WIPO"
BASE_URL = "https://www3.wipo.int/ipstats/datacenter"


async def get_patent_count(
    client: httpx.AsyncClient,
    country_code: str,
    technology_field: str | None = None,
    year: str | None = None,
) -> dict[str, Any]:
    key = settings.wipo_api_key
    url = f"{BASE_URL}/patent-family"
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    params: dict[str, str] = {"country": country_code}
    if technology_field:
        params["technology"] = technology_field
    if year:
        params["year"] = year

    try:
        data = await fetch_json(client, "GET", url, source=SOURCE_NAME, headers=headers, params=params)
        return {
            "country": country_code,
            "technology": technology_field or "all",
            "year": year or "latest",
            "patent_count": data.get("total", 0),
            "source": SOURCE_NAME,
        }
    except TradeAPIError:
        return {
            "country": country_code,
            "technology": technology_field or "all",
            "year": year or "latest",
            "patent_count": None,
            "source": SOURCE_NAME,
            "note": "WIPO API not available or key not configured",
        }
