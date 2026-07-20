"""
Tests for on-demand econometrics endpoint.
"""

from __future__ import annotations

import numpy as np
import pytest
from httpx import AsyncClient


def _random_walk_pair(n: int = 100, seed: int = 42) -> tuple[list[dict], list[dict]]:
    rng = np.random.default_rng(seed)
    shared = np.cumsum(rng.normal(0, 1, n))
    a = 100 + shared + rng.normal(0, 0.5, n)
    b = 100 + shared + rng.normal(0, 0.5, n)

    from datetime import date, timedelta
    start = date(2015, 1, 1)
    periods = [
        (start + timedelta(days=90 * i)).isoformat()
        for i in range(n)
    ]

    series_a = [{"period": p, "value": float(v)} for p, v in zip(periods, a)]
    series_b = [{"period": p, "value": float(v)} for p, v in zip(periods, b)]
    return series_a, series_b


@pytest.mark.asyncio
async def test_econometrics_insufficient_data(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/econometrics",
        json={
            "series_a": [{"period": f"2020-Q{i}", "value": float(100 + i)} for i in range(1, 5)],
            "series_b": [{"period": f"2020-Q{i}", "value": float(50 + i)} for i in range(1, 5)],
            "meta_a": {"series_id": "a", "frequency": "quarterly", "country": "XX"},
            "meta_b": {"series_id": "b", "frequency": "quarterly", "country": "XX"},
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_econometrics_with_mock_pair(client: AsyncClient):
    series_a, series_b = _random_walk_pair(n=60)

    response = await client.post(
        "/api/v1/analysis/econometrics",
        json={
            "series_a": series_a,
            "series_b": series_b,
            "meta_a": {
                "series_id": "series_a",
                "source": "mock",
                "country": "XX",
                "region_code": "NAC",
                "sector_id": "test",
                "frequency": "quarterly",
                "proxy_type": "output_index",
                "sector_label": "Test Sector",
            },
            "meta_b": {
                "series_id": "series_b",
                "source": "mock",
                "country": "XX",
                "region_code": "NAC",
                "sector_id": "test",
                "frequency": "quarterly",
                "proxy_type": "output_index",
                "sector_label": "Test Sector",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pair_id"] == "series_a__series_b"
    assert "sample" in data
    assert data["sample"]["n_obs"] > 0
    assert "stationarity" in data
    assert "granger" in data
    assert "cointegration_engle_granger" in data
    assert "cointegration_johansen" in data

    if data.get("insufficient_data"):
        assert data["stationarity"] is None
        assert data["granger"] is None
    else:
        assert data["stationarity"] is not None
        assert data["stationarity"]["a"] is not None
        assert "is_stationary" in data["stationarity"]["a"]


@pytest.mark.asyncio
async def test_econometrics_invalid_series(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/econometrics",
        json={
            "series_a": [{"period": "2020-01", "value": "not_a_number"} for _ in range(20)],
            "series_b": [{"period": "2020-01", "value": 100} for _ in range(20)],
            "meta_a": {"series_id": "a", "frequency": "monthly", "country": "XX"},
            "meta_b": {"series_id": "b", "frequency": "monthly", "country": "XX"},
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_econometrics_missing_metadata(client: AsyncClient):
    series_a, series_b = _random_walk_pair(n=60)
    response = await client.post(
        "/api/v1/analysis/econometrics",
        json={
            "series_a": series_a,
            "series_b": series_b,
            "meta_a": {},
            "meta_b": {},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pair_id"].startswith("series_")
