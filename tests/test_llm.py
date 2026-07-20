"""
Tests for LLM endpoints and DeepSeek services.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_classify_sector_stub(client: AsyncClient):
    response = await client.post(
        "/api/v1/llm/classify-sector",
        json={
            "sector_name": "Aeroespacial",
            "description": "Aerospace manufacturing and parts",
            "context": "Mexico has a growing aerospace cluster in Queretaro and Chihuahua.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sector"] == "Aeroespacial"


@pytest.mark.asyncio
async def test_extract_indicators_stub(client: AsyncClient):
    response = await client.post(
        "/api/v1/llm/extract-indicators",
        json={
            "text": "Mexico's manufacturing GDP was 217 billion USD in 2023, with exports reaching 593 billion.",
            "indicator_ids": ["manufacturing_value_added", "exports_usd"],
            "country": "MX",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "MX"


@pytest.mark.asyncio
async def test_generate_narrative_stub(client: AsyncClient):
    response = await client.post(
        "/api/v1/llm/generate-narrative",
        json={
            "sector_id": "aeroespacial",
            "country_codes": ["MX"],
            "language": "es",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sector_id"] == "aeroespacial"


@pytest.mark.asyncio
async def test_search_research_stub(client: AsyncClient):
    response = await client.post(
        "/api/v1/search/research",
        json={
            "query": "Mexico aerospace manufacturing FDI 2024",
            "source": "web",
            "max_results": 5,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "Mexico aerospace manufacturing FDI 2024"


@pytest.mark.asyncio
async def test_search_scholar_stub(client: AsyncClient):
    response = await client.post(
        "/api/v1/search/research",
        json={
            "query": "global value chains pharmaceutical industry",
            "source": "scholar",
            "max_results": 3,
        },
    )
    assert response.status_code == 200
