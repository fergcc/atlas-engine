"""
Data endpoints — serve manifest, series, and results JSON files.
Backward compatible with Dashboard frontend contracts.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from src.config import MANIFEST_PATH, RESULTS_DIR, SERIES_DIR

router = APIRouter(prefix="/data", tags=["data"])
logger = logging.getLogger(__name__)


def _load_json(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path.name}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in {path.name}: {exc}")


@router.get("/manifest")
async def get_manifest():
    if not MANIFEST_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="No manifest found. Run POST /api/v1/admin/run-pipeline first.",
        )
    return _load_json(MANIFEST_PATH)


@router.get("/series/{series_id}.json")
async def get_series(series_id: str):
    path = SERIES_DIR / f"{series_id}.json"
    return _load_json(path)


@router.get("/results/{pair_id}.json")
async def get_result(pair_id: str):
    path = RESULTS_DIR / f"{pair_id}.json"
    return _load_json(path)
