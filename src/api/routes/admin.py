"""
Admin endpoints — trigger pipeline runs and check status.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.api.schemas import PipelineRunRequest
from src.services.pipeline import run_pipeline

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_last_run: dict | None = None


@router.post("/run-pipeline")
async def run_pipeline_endpoint(request: PipelineRunRequest):
    global _last_run
    result = run_pipeline(mode=request.mode.value)
    _last_run = {
        "mode": result.mode,
        "pairs_total": result.pairs_total,
        "pairs_real": result.pairs_real,
        "pairs_mock": result.pairs_mock,
        "error": result.error,
        "status": "completed" if not result.error else "failed",
    }
    return _last_run


@router.get("/status")
async def pipeline_status():
    if _last_run is None:
        return {"status": "never_run", "last_run": None}
    return {"status": "ok", "last_run": _last_run}
