"""
UN Comtrade API — International trade statistics.

Free tier: https://comtradeplus.un.org/
Requires API key (free registration).

Key calls:
  - Trade balance between two countries for a commodity group
  - Revealed Comparative Advantage (RCA)
  - Global market share
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import settings
from src.services.trade._base import TradeAPIError, fetch_json

logger = logging.getLogger(__name__)

SOURCE_NAME = "UN Comtrade"
BASE_URL = "https://comtradeapi.un.org/public/v1"


async def get_trade_balance(
    client: httpx.AsyncClient,
    reporter_code: str,
    partner_code: str,
    commodity_code: str = "TOTAL",
    year: str | None = None,
) -> dict[str, Any]:
    key = settings.comtrade_api_key
    if not key:
        raise TradeAPIError(f"{SOURCE_NAME}: COMTRADE_API_KEY not configured")

    headers = {"Ocp-Apim-Subscription-Key": key}
    params: dict[str, str] = {
        "reporterCode": reporter_code,
        "partnerCode": partner_code,
        "cmdCode": commodity_code,
    }
    if year:
        params["period"] = year

    url = f"{BASE_URL}/preview/data/trade"
    try:
        data = await fetch_json(client, "GET", url, source=SOURCE_NAME, headers=headers, params=params)
        results = data.get("data", []) if isinstance(data, dict) else []
        exports = sum(r.get("primaryValue", 0) or 0 for r in results if r.get("flowCode") == "X")
        imports = sum(r.get("primaryValue", 0) or 0 for r in results if r.get("flowCode") == "M")
        return {
            "reporter": reporter_code,
            "partner": partner_code,
            "commodity": commodity_code,
            "year": year or "latest",
            "exports_usd": exports,
            "imports_usd": imports,
            "trade_balance_usd": exports - imports,
            "source": SOURCE_NAME,
        }
    except TradeAPIError:
        raise
    except Exception as exc:
        raise TradeAPIError(f"{SOURCE_NAME}: error fetching trade balance: {exc}") from exc


async def get_top_trading_partners(
    client: httpx.AsyncClient,
    reporter_code: str,
    commodity_code: str = "TOTAL",
    year: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    key = settings.comtrade_api_key
    if not key:
        raise TradeAPIError(f"{SOURCE_NAME}: COMTRADE_API_KEY not configured")

    headers = {"Ocp-Apim-Subscription-Key": key}
    params: dict[str, str] = {
        "reporterCode": reporter_code,
        "cmdCode": commodity_code,
        "topPartnerLimit": str(limit),
    }
    if year:
        params["period"] = year

    url = f"{BASE_URL}/preview/data/trade"
    data = await fetch_json(client, "GET", url, source=SOURCE_NAME, headers=headers, params=params)
    results = data.get("data", []) if isinstance(data, dict) else []
    return results
