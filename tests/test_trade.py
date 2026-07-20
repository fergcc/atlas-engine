"""
Tests for trade/global APIs and sector analysis endpoint.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_analysis_sector_stub_returns_ok(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/sector",
        json={"sector_name": "Aeroespacial", "country_codes": ["MX"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sector"] == "Aeroespacial"


@pytest.mark.asyncio
async def test_analysis_sector_no_cgv(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/sector",
        json={"sector_name": "Farmacéutica", "country_codes": ["US"], "include_cgv": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert "analysis" not in data


@pytest.mark.asyncio
async def test_analysis_sector_with_cgv(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/sector",
        json={"sector_name": "Petroquímica", "country_codes": ["MX"], "include_cgv": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert "analysis" in data
