"""
Adapter endpoints — list available countries, indicators, and regions.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.adapters.registry import get_adapter, get_adapter_info, list_countries

router = APIRouter(prefix="/adapters", tags=["adapters"])


@router.get("/")
async def list_adapters():
    return {"countries": list_countries(), "adapters": get_adapter_info()}


@router.get("/{country}/indicators")
async def country_indicators(country: str):
    adapter = get_adapter(country)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"No adapter for country: {country}")
    return {
        "country": adapter.country,
        "country_name": adapter.country_name,
        "indicators": [
            {
                "id": i.id,
                "name": i.name,
                "name_en": i.name_en,
                "theme": i.theme,
                "frequency": i.frequency,
                "unit": i.unit,
                "proxy_type": i.proxy_type,
                "geographic_granularity": i.geographic_granularity,
                "available": i.available,
            }
            for i in adapter.list_indicators()
        ],
    }


@router.get("/{country}/regions")
async def country_regions(country: str):
    adapter = get_adapter(country)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"No adapter for country: {country}")
    regions = adapter.list_regions()
    return {
        "country": adapter.country,
        "country_name": adapter.country_name,
        "level": "state",
        "count": len(regions),
        "regions": [
            {"code": r.code, "name": r.name, "name_en": r.name_en}
            for r in regions
        ],
    }


@router.get("/{country}/health")
async def country_health(country: str):
    adapter = get_adapter(country)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"No adapter for country: {country}")
    ok = adapter.health_check()
    return {
        "country": adapter.country,
        "healthy": ok,
        "status": "ok" if ok else "unavailable",
    }
