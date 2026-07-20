"""
SearchAPI.io wrapper.

Company convention: SEARCH_API_KEY from env var.
Caches results in SQLite (search_cache table) by query hash.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import settings
from src.database import cache_search_response, get_search_cache, init_db

logger = logging.getLogger(__name__)

SOURCE_NAME = "SearchAPI"
BASE_URL = "https://www.searchapi.io/api/v1"


def _get_client() -> httpx.Client:
    key = settings.search_api_key
    if not key:
        raise RuntimeError(f"{SOURCE_NAME}: SEARCH_API_KEY not configured")
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {key}"},
        timeout=30.0,
    )


def search(
    query: str,
    *,
    engine: str = "google",
    num: int = 10,
    use_cache: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    if use_cache:
        conn = init_db(settings.db_path)
        cached = get_search_cache(conn, query, engine)
        if cached:
            logger.info(f"{SOURCE_NAME}: cache hit for '{query[:60]}...'")
            return cached

    logger.info(f"{SOURCE_NAME}: searching '{query[:60]}...' (engine={engine})")
    client = _get_client()
    try:
        response = client.get(
            "/search",
            params={
                "q": query,
                "engine": engine,
                "num": str(num),
                **kwargs,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"{SOURCE_NAME}: HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
    finally:
        client.close()

    organic = data.get("organic_results", [])
    results_list = [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
            "position": r.get("position"),
        }
        for r in organic[:num]
    ]

    result = {
        "query": query,
        "engine": engine,
        "total_results": data.get("search_information", {}).get("total_results"),
        "results": results_list,
        "source": SOURCE_NAME,
    }

    if use_cache:
        conn = init_db(settings.db_path)
        cache_search_response(conn, query, result, engine)

    return result


def search_scholar(
    query: str,
    *,
    num: int = 10,
    use_cache: bool = True,
) -> dict[str, Any]:
    return search(query, engine="google_scholar", num=num, use_cache=use_cache)
