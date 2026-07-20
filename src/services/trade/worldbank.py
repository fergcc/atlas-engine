"""
World Bank API — Development indicators.

Free, no authentication required.
https://api.worldbank.org/v2/

Key indicators:
  - NV.IND.MANF.ZS: Manufacturing value added (% of GDP)
  - NV.IND.TOTL.ZS: Industry value added (% of GDP)
  - NY.GDP.MKTP.CD: GDP (current USD)
  - NY.GDP.MKTP.KD.ZG: GDP growth (%)
  - BX.KLT.DINV.WD.GD.ZS: Foreign direct investment (% of GDP)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.services.trade._base import TradeAPIError, fetch_json

logger = logging.getLogger(__name__)

SOURCE_NAME = "World Bank"
BASE_URL = "https://api.worldbank.org/v2"


KEY_INDICATORS = {
    "manufacturing_value_added_pct_gdp": "NV.IND.MANF.ZS",
    "industry_value_added_pct_gdp": "NV.IND.TOTL.ZS",
    "gdp_current_usd": "NY.GDP.MKTP.CD",
    "gdp_growth_pct": "NY.GDP.MKTP.KD.ZG",
    "fdi_pct_gdp": "BX.KLT.DINV.WD.GD.ZS",
    "exports_pct_gdp": "NE.EXP.GNFS.ZS",
    "high_tech_exports_pct": "TX.VAL.TECH.MF.ZS",
    "research_expenditure_pct_gdp": "GB.XPD.RSDV.GD.ZS",
    "patent_applications": "IP.PAT.RESD",
}


async def get_indicator(
    client: httpx.AsyncClient,
    indicator_code: str,
    country_code: str = "MX",
    per_page: int = 50,
) -> dict[str, Any]:
    url = f"{BASE_URL}/country/{country_code}/indicator/{indicator_code}"
    params = {"format": "json", "per_page": str(per_page)}
    data = await fetch_json(client, "GET", url, source=SOURCE_NAME, params=params)

    if not isinstance(data, list) or len(data) < 2:
        raise TradeAPIError(f"{SOURCE_NAME}: unexpected response format")

    metadata = data[0]
    observations = data[1] or []

    values = []
    for obs in observations:
        val = obs.get("value")
        if val is not None:
            values.append({
                "year": obs.get("date"),
                "value": float(val),
            })

    return {
        "indicator": indicator_code,
        "indicator_name": metadata.get("indicator", {}).get("value", indicator_code),
        "country": country_code,
        "country_name": metadata.get("country", {}).get("value", country_code),
        "source": SOURCE_NAME,
        "observations": values,
    }


async def get_multiple_indicators(
    client: httpx.AsyncClient,
    indicator_codes: list[str],
    country_code: str = "MX",
) -> dict[str, Any]:
    results: dict[str, Any] = {"country": country_code, "source": SOURCE_NAME, "indicators": {}}
    for code in indicator_codes:
        try:
            result = await get_indicator(client, code, country_code)
            results["indicators"][code] = result
        except TradeAPIError:
            results["indicators"][code] = None
    return results


async def get_latest_value(
    client: httpx.AsyncClient,
    indicator_code: str,
    country_code: str = "MX",
) -> dict[str, Any]:
    result = await get_indicator(client, indicator_code, country_code)
    observations = result.get("observations", [])
    if not observations:
        return {"indicator": indicator_code, "country": country_code, "value": None, "year": None}
    latest = observations[-1]
    return {
        "indicator": indicator_code,
        "indicator_name": result.get("indicator_name"),
        "country": country_code,
        "value": latest["value"],
        "year": latest["year"],
        "source": SOURCE_NAME,
    }
