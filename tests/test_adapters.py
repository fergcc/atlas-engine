"""
Tests for the adapter system — registry, discovery, and per-country adapters.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_adapters(client: AsyncClient):
    response = await client.get("/api/v1/adapters/")
    assert response.status_code == 200
    data = response.json()
    assert "countries" in data
    assert "MX" in data["countries"]
    assert "US" in data["countries"]
    assert len(data["adapters"]) >= 2


@pytest.mark.asyncio
async def test_mexico_indicators(client: AsyncClient):
    response = await client.get("/api/v1/adapters/MX/indicators")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "MX"
    assert len(data["indicators"]) >= 1
    proxy_types = {i["proxy_type"] for i in data["indicators"]}
    assert "output_index" in proxy_types


@pytest.mark.asyncio
async def test_usa_indicators(client: AsyncClient):
    response = await client.get("/api/v1/adapters/US/indicators")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "US"
    assert len(data["indicators"]) >= 2


@pytest.mark.asyncio
async def test_mexico_regions(client: AsyncClient):
    response = await client.get("/api/v1/adapters/MX/regions")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "MX"
    assert data["level"] == "state"
    assert data["count"] == 32


@pytest.mark.asyncio
async def test_usa_regions(client: AsyncClient):
    response = await client.get("/api/v1/adapters/US/regions")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "US"
    assert data["count"] >= 50


@pytest.mark.asyncio
async def test_unknown_country_404(client: AsyncClient):
    response = await client.get("/api/v1/adapters/XX/indicators")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_includes_countries(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "MX" in data["countries_available"]
    assert "US" in data["countries_available"]


@pytest.mark.asyncio
async def test_mexico_health_check(client: AsyncClient):
    response = await client.get("/api/v1/adapters/MX/health")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "MX"
    assert "healthy" in data


@pytest.mark.asyncio
async def test_usa_health_check(client: AsyncClient):
    response = await client.get("/api/v1/adapters/US/health")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "US"
    assert "healthy" in data


@pytest.mark.asyncio
async def test_adapter_registry_direct():
    from src.adapters.registry import get_adapter, list_countries
    countries = list_countries()
    assert "MX" in countries
    assert "US" in countries

    mx = get_adapter("MX")
    assert mx is not None
    assert mx.country == "MX"
    assert mx.country_name == "México"
    assert mx.get_default_proxy_type() == "output_index"

    us = get_adapter("US")
    assert us is not None
    assert us.country == "US"

    assert mx.health_check() or True  # may fail without token, but shouldn't crash

    mx_regions = mx.list_regions()
    assert len(mx_regions) == 32
    assert any(r.code == "08" for r in mx_regions)

    us_regions = us.list_regions()
    assert len(us_regions) >= 50
    assert any(r.code == "48" for r in us_regions)  # Texas
