"""
Search endpoint — SearchAPI-powered web and academic research.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.api.schemas import SearchResearchRequest
from src.services.search import client

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)


@router.post("/research")
async def research(request: SearchResearchRequest):
    try:
        engine = "google_scholar" if request.source == "scholar" else "google"
        result = client.search(
            query=request.query,
            engine=engine,
            num=request.max_results,
        )
        return {"status": "ok", "query": request.query, "results": result}
    except Exception as exc:
        logger.error(f"search failed: {exc}")
        return {
            "status": "error",
            "query": request.query,
            "error": str(exc),
            "note": "SEARCH_API_KEY may not be configured or service unavailable",
        }
