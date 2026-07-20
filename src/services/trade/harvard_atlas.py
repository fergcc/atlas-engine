"""
Harvard Atlas of Economic Complexity — Product Complexity Index.

Free, no auth required.
https://atlas.cid.harvard.edu/

Key metrics:
  - PCI (Product Complexity Index)
  - ECI (Economic Complexity Index) by country
  - Export baskets by country/product
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.services.trade._base import TradeAPIError, fetch_json

logger = logging.getLogger(__name__)

SOURCE_NAME = "Harvard Atlas EC"
BASE_URL = "https://atlas.cid.harvard.edu/api"


async def get_country_pci(
    client: httpx.AsyncClient,
    country_code: str = "MEX",
) -> dict[str, Any]:
    url = f"{BASE_URL}/country-data/{country_code}"
    data = await fetch_json(client, "GET", url, source=SOURCE_NAME)
    return {
        "country": country_code,
        "economic_complexity_index": data.get("eci"),
        "eci_rank": data.get("eci_rank"),
        "pci_data": data.get("products", []),
        "source": SOURCE_NAME,
    }


async def get_product_pci(
    client: httpx.AsyncClient,
    hs_code: str,
) -> dict[str, Any]:
    url = f"{BASE_URL}/product/{hs_code}"
    data = await fetch_json(client, "GET", url, source=SOURCE_NAME)
    return {
        "hs_code": hs_code,
        "product_name": data.get("name"),
        "pci": data.get("pci"),
        "pci_rank": data.get("pci_rank"),
        "source": SOURCE_NAME,
    }
