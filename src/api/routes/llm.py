"""
LLM endpoints — DeepSeek-powered sector classification, indicator extraction,
and narrative generation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.api.schemas import (
    LLMClassifySectorRequest,
    LLMExtractIndicatorsRequest,
    LLMGenerateNarrativeRequest,
)
from src.services.llm import tasks

router = APIRouter(prefix="/llm", tags=["llm"])
logger = logging.getLogger(__name__)


@router.post("/classify-sector")
async def classify_sector(request: LLMClassifySectorRequest):
    try:
        result = tasks.classify_sector(
            sector_name=request.sector_name,
            description=request.description,
            context=request.context,
        )
        return {"status": "ok", "sector": request.sector_name, "analysis": result}
    except Exception as exc:
        logger.error(f"classify-sector failed: {exc}")
        return {
            "status": "error",
            "sector": request.sector_name,
            "error": str(exc),
            "note": "DeepSeek API key may not be configured or service unavailable",
        }


@router.post("/extract-indicators")
async def extract_indicators(request: LLMExtractIndicatorsRequest):
    try:
        result = tasks.extract_indicators(
            text=request.text,
            indicator_ids=request.indicator_ids,
        )
        return {"status": "ok", "country": request.country, "indicators": result}
    except Exception as exc:
        logger.error(f"extract-indicators failed: {exc}")
        return {
            "status": "error",
            "country": request.country,
            "error": str(exc),
            "note": "DeepSeek API key may not be configured",
        }


@router.post("/generate-narrative")
async def generate_narrative(request: LLMGenerateNarrativeRequest):
    try:
        from src.adapters.registry import get_adapter

        country_names = ", ".join(
            get_adapter(c).country_name if get_adapter(c) else c
            for c in request.country_codes
        )

        result = tasks.generate_narrative(
            sector_name=request.sector_id,
            country_names=country_names,
            language=request.language,
        )
        return {"status": "ok", "sector_id": request.sector_id, "narrative": result}
    except Exception as exc:
        logger.error(f"generate-narrative failed: {exc}")
        return {
            "status": "error",
            "sector_id": request.sector_id,
            "error": str(exc),
            "note": "DeepSeek API key may not be configured",
        }
