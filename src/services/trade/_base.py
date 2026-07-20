"""
Base HTTP client for trade/global APIs.

Same retry pattern as ingestion._http but with async support
for use in FastAPI route handlers.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class TradeAPIError(Exception):
    pass


class _RetryableHTTPError(Exception):
    pass


async def _do_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    timeout: float,
    **kwargs: Any,
) -> httpx.Response:
    try:
        response = await client.request(method, url, timeout=timeout, **kwargs)
    except httpx.TimeoutException as exc:
        raise _RetryableHTTPError(str(exc)) from exc
    except httpx.ConnectError as exc:
        raise _RetryableHTTPError(str(exc)) from exc
    if response.status_code in _RETRYABLE_STATUS:
        raise _RetryableHTTPError(f"HTTP {response.status_code} from {url}")
    return response


_retrying_request = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(_RetryableHTTPError),
)(_do_request)


async def fetch_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    source: str,
    timeout: float = 20.0,
    **kwargs: Any,
) -> dict:
    try:
        response = await _retrying_request(client, method, url, timeout, **kwargs)
    except _RetryableHTTPError as exc:
        raise TradeAPIError(f"{source}: request failed: {exc}") from exc
    if response.status_code >= 400:
        raise TradeAPIError(
            f"{source}: HTTP {response.status_code} from {url}: {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError:
        raise TradeAPIError(f"{source}: invalid JSON from {url}")
