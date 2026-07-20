"""
OECD Data API — Industrial value added, R&D expenditure.

Free, no auth required.
https://stats.oecd.org/

Key datasets:
  - STAN: Structural Analysis (value added by industry)
  - MSTI: Main Science and Technology Indicators (R&D)
  - TIVA: Trade in Value Added
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.services.trade._base import TradeAPIError, fetch_json

logger = logging.getLogger(__name__)

SOURCE_NAME = "OECD"
BASE_URL = "https://stats.oecd.org/sdmx-json/data"


async def get_value_added_by_industry(
    client: httpx.AsyncClient,
    country_code: str = "MEX",
    industry_code: str = "C",
) -> dict[str, Any]:
    dataset = "STAN_INDICATORS"
    params = {
        "format": "json",
        "dimensionAtObservation": "all",
    }
    url = f"{BASE_URL}/{dataset}/VALU.{industry_code}.TOTAL/{country_code}/all"
    try:
        data = await fetch_json(client, "GET", url, source=SOURCE_NAME, params=params)
        obs_list = data.get("dataSets", [{}])[0].get("observations", {})

        values = []
        for idx, val_list in obs_list.items():
            year_idx = int(idx.split(":")[-1]) if ":" in idx else 0
            if val_list and val_list[0] is not None:
                values.append({
                    "period": str(2000 + year_idx) if year_idx < 200 else str(year_idx),
                    "value_millions_usd": float(val_list[0]) / 1e6,
                })
        return {
            "country": country_code,
            "industry": industry_code,
            "source": SOURCE_NAME,
            "dataset": "STAN — Value Added",
            "observations": values,
        }
    except TradeAPIError:
        return {
            "country": country_code,
            "industry": industry_code,
            "source": SOURCE_NAME,
            "observations": [],
            "note": "OECD STAN data unavailable",
        }


async def get_rd_expenditure(
    client: httpx.AsyncClient,
    country_code: str = "MEX",
) -> dict[str, Any]:
    dataset = "MSTI_PUB"
    url = f"{BASE_URL}/{dataset}/GBARDGDP.TOTAL/{country_code}/all"
    params = {"format": "json"}
    try:
        data = await fetch_json(client, "GET", url, source=SOURCE_NAME, params=params)
        obs_list = data.get("dataSets", [{}])[0].get("observations", {})

        values = []
        for idx, val_list in obs_list.items():
            year_idx = int(idx.split(":")[-1]) if ":" in idx else 0
            if val_list and val_list[0] is not None:
                year = int(data.get("structure", {})
                    .get("dimensions", {})
                    .get("observation", [{}]*5)[4]
                    .get("values", [str(2000+year_idx)])[0])
                values.append({
                    "year": year,
                    "rd_pct_gdp": float(val_list[0]),
                })
        return {
            "country": country_code,
            "source": SOURCE_NAME,
            "dataset": "MSTI — GERD as % of GDP",
            "observations": values,
        }
    except TradeAPIError:
        return {
            "country": country_code,
            "source": SOURCE_NAME,
            "observations": [],
            "note": "OECD MSTI data unavailable",
        }
