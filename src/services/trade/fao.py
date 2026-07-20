"""
FAO Stat API — Agricultural production and land use.

Free, no auth required.
https://www.fao.org/faostat/en/#data/

Key datasets:
  - QA: Production quantities (crops and livestock)
  - QV: Production value
  - RL: Land use
  - TP: Trade (crops and livestock)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.services.trade._base import TradeAPIError, fetch_json

logger = logging.getLogger(__name__)

SOURCE_NAME = "FAO"
BASE_URL = "https://fenixservices.fao.org/faostat/api/v1/en"


FAO_DATASETS = {
    "production_tonnes": "QA",
    "production_value_usd": "QV",
    "land_use_ha": "RL",
    "trade_value_usd": "TP",
    "trade_quantity_tonnes": "TQ",
}


async def get_production_data(
    client: httpx.AsyncClient,
    country_code: str,
    item_code: str,
    element_code: str = "5510",
    year_range: str | None = None,
) -> dict[str, Any]:
    dataset = FAO_DATASETS["production_tonnes"]
    url = f"{BASE_URL}/{dataset}/{country_code}/{item_code}/{element_code}"
    params = {}
    if year_range:
        params["year"] = year_range

    try:
        data = await fetch_json(client, "GET", url, source=SOURCE_NAME, params=params)
        records = data.get("data", [])
        obs = []
        for r in records:
            obs.append({
                "year": r.get("Year"),
                "value": r.get("Value"),
                "unit": r.get("Unit"),
            })
        return {
            "country": country_code,
            "item_code": item_code,
            "element": "Production [t]",
            "source": SOURCE_NAME,
            "observations": obs,
        }
    except TradeAPIError:
        return {
            "country": country_code,
            "item_code": item_code,
            "source": SOURCE_NAME,
            "observations": [],
            "note": "FAO data unavailable",
        }
