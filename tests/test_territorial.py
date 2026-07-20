"""
Tests for territorial indicator computation and catalog.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_indicators_catalog_loaded(client: AsyncClient):
    response = await client.get("/api/v1/analysis/indicators/catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["total_indicators"] == 34
    assert data["by_phase"]["A"] == 14
    assert data["by_phase"]["B"] == 20
    assert len(data["themes"]) >= 6
    assert len(data["indicators"]) == 34


@pytest.mark.asyncio
async def test_indicators_have_required_fields(client: AsyncClient):
    response = await client.get("/api/v1/analysis/indicators/catalog")
    data = response.json()
    for ind in data["indicators"]:
        assert "id" in ind
        assert "name" in ind
        assert "theme" in ind
        assert "phase" in ind
        assert "unit" in ind
        assert "methodology" in ind
        assert "source" in ind
        assert "polarity" in ind
        assert "standardization" in ind


@pytest.mark.asyncio
async def test_territorial_analysis_mx(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/territorial",
        json={
            "country": "MX",
            "region_codes": ["08", "02"],
            "sector_id": "aeroespacial",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "MX"
    assert data["total_indicators"] == 34
    assert data["total_regions"] == 2
    assert len(data["by_region"]) == 2
    assert len(data["raw_values"]) == 34 * 2


@pytest.mark.asyncio
async def test_territorial_analysis_all_regions(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/territorial",
        json={"country": "MX", "sector_id": "manufactura_total"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_regions"] == 32


@pytest.mark.asyncio
async def test_territorial_analysis_no_adapter_fallback(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/territorial",
        json={"country": "BR", "sector_id": "aeroespacial"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "BR"
    assert data["total_regions"] == 1
    assert data["by_region"][0]["region_code"] == "NAC"


@pytest.mark.asyncio
async def test_indicator_catalog_direct():
    from src.services.territorial import (
        load_indicators,
        get_indicators_by_theme,
        get_indicators_by_phase,
    )
    catalog = load_indicators()
    assert len(catalog) == 34

    by_theme = get_indicators_by_theme()
    assert len(by_theme) >= 9

    by_phase = get_indicators_by_phase()
    assert len(by_phase["A"]) == 14
    assert len(by_phase["B"]) == 20

    themes = {ind["id"] for ind in catalog}
    assert "industrial_vacb_share" in themes
    assert "homicide_rate" in themes
    assert "water_stress" in themes
    assert "talent_attraction" in themes
