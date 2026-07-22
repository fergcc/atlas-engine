"""
Smoke tests for the Atlas Engine FastAPI application.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["engine_env"] == "development"
    assert data["use_mocks"] is True
    assert "version" in data


@pytest.mark.asyncio
async def test_root_redirects(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Atlas Engine"


@pytest.mark.asyncio
async def test_api_docs_available(client: AsyncClient):
    response = await client.get("/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_data_manifest_requires_pipeline(client: AsyncClient):
    response = await client.get("/api/v1/data/manifest")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_data_series_404(client: AsyncClient):
    response = await client.get("/api/v1/data/series/nonexistent.json")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_data_results_404(client: AsyncClient):
    response = await client.get("/api/v1/data/results/nonexistent.json")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analysis_sector_stub(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/sector",
        json={"sector_name": "Aeroespacial", "country_codes": ["MX", "US"]},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_status_stub(client: AsyncClient):
    response = await client.get("/api/v1/admin/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_run_pipeline_mock(client: AsyncClient):
    response = await client.post(
        "/api/v1/admin/run-pipeline",
        json={"mode": "mock"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["pairs_total"] == 101
    assert data["mode"] == "mock"

    response2 = await client.get("/api/v1/admin/status")
    assert response2.status_code == 200
    assert response2.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_data_manifest_after_pipeline(client: AsyncClient):
    await client.post("/api/v1/admin/run-pipeline", json={"mode": "mock"})
    response = await client.get("/api/v1/data/manifest")
    assert response.status_code == 200
    data = response.json()
    assert "sectors" in data
    assert "series_catalog" in data
    assert "pairs" in data
    assert len(data["sectors"]) == 6


@pytest.mark.asyncio
async def test_data_series_after_pipeline(client: AsyncClient):
    await client.post("/api/v1/admin/run-pipeline", json={"mode": "mock"})
    series_id = "mx-nac_eolica_emim.json"
    response = await client.get(f"/api/v1/data/series/{series_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "mx-nac_eolica_emim"
    assert len(data["observations"]) > 0


@pytest.mark.asyncio
async def test_data_results_after_pipeline(client: AsyncClient):
    await client.post("/api/v1/admin/run-pipeline", json={"mode": "mock"})
    pair_id = "mx-nac_eolica__us-nac_eolica.json"
    response = await client.get(f"/api/v1/data/results/{pair_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["pair_id"] == "mx-nac_eolica__us-nac_eolica"
    assert "granger" in data
