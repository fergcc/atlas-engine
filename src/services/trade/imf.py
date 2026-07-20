"""
IMF Data API — Supplementary trade and financial data.

Free, no auth required.
https://www.imf.org/en/Data

Key datasets:
  - DOT: Direction of Trade Statistics
  - IFS: International Financial Statistics
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.services.trade._base import TradeAPIError, fetch_json

logger = logging.getLogger(__name__)

SOURCE_NAME = "IMF"
BASE_URL = "http://dataservices.imf.org/REST/SDMX_JSON.svc"


async def get_trade_flows(
    client: httpx.AsyncClient,
    country_code: str = "MX",
    indicator: str = "TMG_CIF_USD",
) -> dict[str, Any]:
    dataset = "DOT"
    url = f"{BASE_URL}/CompactData/{dataset}/{country_code}.{indicator}"
    try:
        data = await fetch_json(client, "GET", url, source=SOURCE_NAME)
        series = data.get("CompactData", {}).get("DataSet", {}).get("Series", {})
        obs = series.get("Obs", []) if isinstance(series, dict) else []

        values = []
        for o in obs if isinstance(obs, list) else [obs]:
            values.append({
                "period": o.get("@TIME_PERIOD"),
                "value_millions_usd": float(o.get("@OBS_VALUE", 0)),
            })
        return {
            "country": country_code,
            "indicator": indicator,
            "source": SOURCE_NAME,
            "observations": values,
        }
    except TradeAPIError:
        return {
            "country": country_code,
            "indicator": indicator,
            "source": SOURCE_NAME,
            "observations": [],
            "note": "IMF DOT data unavailable",
        }
