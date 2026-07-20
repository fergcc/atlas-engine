"""
Ingestion module for Statistics Canada Web Data Service (WDS).

Free, no auth required. Rate limit: 25 req/sec per IP.
Base URL: https://www150.statcan.gc.ca/t1/wds/rest

Key product IDs (PIDs):
  36100434 - Monthly GDP by NAICS (national)
  16100048 - Manufacturing sales by province (monthly)
  14100287 - Labour Force Survey (monthly, by province)
  36100711 - GDP by province and NAICS (annual)
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

SOURCE_NAME = "Statistics Canada"
BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest"

STATCAN_PRODUCTS = {
    "gdp_national_monthly": 36100434,
    "manufacturing_sales_provincial": 16100048,
    "labour_force_monthly": 14100287,
    "gdp_provincial_annual": 36100711,
}

FREQ_LABEL = {6: "monthly", 9: "quarterly", 12: "annual"}


class _RetryableHTTPError(requests.RequestException):
    pass


def _do_request(method: str, url: str, timeout: float = 30.0, **kwargs: Any) -> requests.Response:
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise _RetryableHTTPError(str(exc)) from exc
    if response.status_code in {429, 500, 502, 503, 504}:
        raise _RetryableHTTPError(f"HTTP {response.status_code} from {url}")
    return response


_retrying_request = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(_RetryableHTTPError),
)(_do_request)


def _request_json(method: str, url: str, **kwargs: Any) -> dict:
    response = _retrying_request(method, url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{SOURCE_NAME}: HTTP {response.status_code}: {response.text[:300]}")
    try:
        return response.json()
    except ValueError:
        raise RuntimeError(f"{SOURCE_NAME}: invalid JSON from {url}")


def fetch_vector_data(
    vector_ids: list[int], latest_n: int = 24
) -> list[dict[str, Any]]:
    payload = [{"vectorId": vid, "latestN": latest_n} for vid in vector_ids]
    url = f"{BASE_URL}/getDataFromVectorsAndLatestNPeriods"
    result = _request_json("POST", url, json=payload)

    observations: list[dict[str, Any]] = []
    for item in result if isinstance(result, list) else [result]:
        obj = item.get("object", {})
        if isinstance(obj, dict):
            for dp in obj.get("vectorDataPoint", []):
                observations.append({
                    "refPer": dp.get("refPer"),
                    "value": dp.get("value"),
                    "frequencyCode": dp.get("frequencyCode"),
                    "productId": obj.get("productId"),
                    "vectorId": obj.get("vectorId"),
                    "source": SOURCE_NAME,
                })
    return observations


def fetch_cube_metadata(product_id: int) -> dict[str, Any]:
    payload = [{"productId": product_id}]
    url = f"{BASE_URL}/getCubeMetadata"
    result = _request_json("POST", url, json=payload)
    return result[0] if isinstance(result, list) and result else result


def fetch_cube_coord_data(
    product_id: int,
    coordinate: str,
    latest_n: int = 24,
) -> list[dict[str, Any]]:
    payload = [{
        "productId": product_id,
        "coordinate": coordinate,
        "latestN": latest_n,
    }]
    url = f"{BASE_URL}/getDataFromCubePidCoordAndLatestNPeriods"
    result = _request_json("POST", url, json=payload)

    observations = []
    for item in result if isinstance(result, list) else [result]:
        obj = item.get("object", {})
        if isinstance(obj, dict):
            for dp in obj.get("vectorDataPoint", []):
                observations.append({
                    "refPer": dp.get("refPer"),
                    "value": dp.get("value"),
                    "frequencyCode": dp.get("frequencyCode"),
                    "productId": obj.get("productId"),
                    "vectorId": obj.get("vectorId"),
                    "source": SOURCE_NAME,
                })
    return observations


def fetch_full_table_csv(product_id: int) -> list[dict[str, Any]]:
    url = f"{BASE_URL}/getFullTableDownloadCSV/{product_id}/en"
    result = _request_json("GET", url)
    return [{"csv_url": result.get("object", ""), "source": SOURCE_NAME}]
