"""
Tests for Canada adapter.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_canada_adapter_registry():
    from src.adapters.registry import get_adapter, list_countries

    assert "CA" in list_countries()

    ca = get_adapter("CA")
    assert ca is not None
    assert ca.country == "CA"
    assert ca.country_name == "Canadá"
    assert ca.get_default_proxy_type() == "output_index"


@pytest.mark.asyncio
async def test_canada_regions():
    from src.adapters.registry import get_adapter

    ca = get_adapter("CA")
    regions = ca.list_regions()
    assert len(regions) == 13
    codes = {r.code for r in regions}
    assert "59" in codes  # British Columbia
    assert "35" in codes  # Ontario
    assert "24" in codes  # Quebec


@pytest.mark.asyncio
async def test_canada_indicators():
    from src.adapters.registry import get_adapter

    ca = get_adapter("CA")
    indicators = ca.list_indicators()
    assert len(indicators) >= 3
    proxy_types = {i.proxy_type for i in indicators}
    assert "output_index" in proxy_types


@pytest.mark.asyncio
async def test_canada_adapter_api(client):
    response = await client.get("/api/v1/adapters/CA/indicators")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "CA"
    assert len(data["indicators"]) >= 3


@pytest.mark.asyncio
async def test_canada_regions_api(client):
    response = await client.get("/api/v1/adapters/CA/regions")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "CA"
    assert data["count"] == 13
