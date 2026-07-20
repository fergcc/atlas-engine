"""
Analysis endpoints — Global Value Chain, territorial indicators, custom econometrics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    SectorAnalysisRequest,
    TerritorialAnalysisRequest,
    EconometricsRequest,
)
from src.services.trade.comtrade import get_trade_balance
from src.services.trade.worldbank import get_latest_value, KEY_INDICATORS
from src.services.trade.harvard_atlas import get_country_pci
from src.services.trade.wipo import get_patent_count
from src.services.territorial import (
    load_indicators,
    get_indicators_by_theme,
    get_indicators_by_phase,
    build_indicator_matrix,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])
logger = logging.getLogger(__name__)


@router.post("/sector")
async def analyze_sector(request: SectorAnalysisRequest):
    results: dict[str, Any] = {
        "sector": request.sector_name,
        "countries": request.country_codes,
    }

    if not request.include_cgv:
        return results

    async with httpx.AsyncClient() as client:
        analysis: dict[str, Any] = {}

        try:
            t1 = await get_trade_balance(client, request.country_codes[0], "000")
            t2 = await get_trade_balance(client, "000", request.country_codes[0])
            analysis["trade"] = {"exports": t1, "imports": t2}
        except Exception as exc:
            analysis["trade"] = {"error": str(exc)}

        try:
            wb_data = {}
            for name, code in [
                ("manufacturing_gdp_pct", KEY_INDICATORS["manufacturing_value_added_pct_gdp"]),
                ("gdp_current_usd", KEY_INDICATORS["gdp_current_usd"]),
                ("gdp_growth", KEY_INDICATORS["gdp_growth_pct"]),
                ("fdi_pct", KEY_INDICATORS["fdi_pct_gdp"]),
                ("research_pct_gdp", KEY_INDICATORS["research_expenditure_pct_gdp"]),
            ]:
                wb_data[name] = await get_latest_value(client, code, request.country_codes[0])
            analysis["world_bank"] = wb_data
        except Exception as exc:
            analysis["world_bank"] = {"error": str(exc)}

        try:
            pci = await get_country_pci(client, request.country_codes[0])
            analysis["economic_complexity"] = pci
        except Exception as exc:
            analysis["economic_complexity"] = {"error": str(exc)}

        try:
            patents = await get_patent_count(client, request.country_codes[0])
            analysis["innovation"] = patents
        except Exception as exc:
            analysis["innovation"] = {"error": str(exc)}

        results["analysis"] = analysis

    return results


@router.get("/indicators/catalog")
async def indicators_catalog():
    catalog = load_indicators()
    return {
        "total_indicators": len(catalog),
        "by_phase": {
            "A": len(get_indicators_by_phase()["A"]),
            "B": len(get_indicators_by_phase()["B"]),
        },
        "themes": [
            {"id": theme, "count": len(items)}
            for theme, items in get_indicators_by_theme().items()
        ],
        "indicators": catalog,
    }


@router.post("/territorial")
async def analyze_territorial(request: TerritorialAnalysisRequest):
    matrix = build_indicator_matrix(
        country=request.country,
        region_codes=request.region_codes,
        sector_id=request.sector_id,
    )
    return matrix


@router.post("/econometrics")
async def analyze_econometrics(request: EconometricsRequest):
    from src.services.processing.normalize import SeriesMeta, normalize_series
    from src.services.econometrics.pipeline_runner import run_pair

    if len(request.series_a) < 8 or len(request.series_b) < 8:
        raise HTTPException(
            status_code=400,
            detail="Each series must have at least 8 observations to run econometric tests.",
        )

    try:
        meta_a = SeriesMeta(
            series_id=request.meta_a.get("series_id", "series_a"),
            source=request.meta_a.get("source", "custom"),
            country=request.meta_a.get("country", "XX"),
            region_code=request.meta_a.get("region_code", "NAC"),
            sector_id=request.meta_a.get("sector_id"),
            frequency=request.meta_a.get("frequency", "quarterly"),
            seasonal_adjustment=request.meta_a.get("seasonal_adjustment", "nsa"),
            units=request.meta_a.get("units", ""),
            proxy_type=request.meta_a.get("proxy_type", "output_index"),
            publication_lag_days=request.meta_a.get("publication_lag_days", 30),
            vintage_date=request.meta_a.get("vintage_date", datetime.now(timezone.utc).date().isoformat()),
            scian_code=request.meta_a.get("scian_code"),
            naics_code=request.meta_a.get("naics_code"),
        )
        meta_b = SeriesMeta(
            series_id=request.meta_b.get("series_id", "series_b"),
            source=request.meta_b.get("source", "custom"),
            country=request.meta_b.get("country", "XX"),
            region_code=request.meta_b.get("region_code", "NAC"),
            sector_id=request.meta_b.get("sector_id"),
            frequency=request.meta_b.get("frequency", "quarterly"),
            seasonal_adjustment=request.meta_b.get("seasonal_adjustment", "nsa"),
            units=request.meta_b.get("units", ""),
            proxy_type=request.meta_b.get("proxy_type", "output_index"),
            publication_lag_days=request.meta_b.get("publication_lag_days", 30),
            vintage_date=request.meta_b.get("vintage_date", datetime.now(timezone.utc).date().isoformat()),
            scian_code=request.meta_b.get("scian_code"),
            naics_code=request.meta_b.get("naics_code"),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid series metadata: {exc}")

    obs_a = [(o.get("period", o.get("date", "")), o.get("value")) for o in request.series_a]
    obs_b = [(o.get("period", o.get("date", "")), o.get("value")) for o in request.series_b]

    try:
        tidy_a = normalize_series(obs_a, meta_a)
        tidy_b = normalize_series(obs_b, meta_b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot normalize series: {exc}")

    pair_id = f"{meta_a.series_id}__{meta_b.series_id}"
    sector_meta = {
        "id": request.meta_a.get("sector_id", "custom"),
        "label": request.meta_a.get("sector_label", ""),
        "scian": meta_a.scian_code,
        "naics": meta_a.naics_code,
    }

    try:
        result = run_pair(pair_id, sector_meta, tidy_a, tidy_b)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Econometric analysis failed: {exc}")
    except Exception as exc:
        logger.error(f"Econometric analysis error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")
