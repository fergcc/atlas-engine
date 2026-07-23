"""
Pipeline orchestrator — wraps mock generation and live data ingestion.

Called by the API (POST /api/v1/admin/run-pipeline) or directly from CLI.
Produces manifest.json, series/*.json, results/*.json in Engine's data/ dir.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.config import DATA_DIR, MANIFEST_PATH, RESULTS_DIR, SERIES_DIR

logger = logging.getLogger(__name__)


@dataclass
class PipelineRunResult:
    manifest: dict[str, Any] | None = None
    mode: str = "mixed"
    pairs_total: int = 0
    pairs_real: int = 0
    pairs_mock: int = 0
    error: str | None = None


def run_mock_pipeline() -> PipelineRunResult:
    from src.services.mock.generate_mock_data import (
        _load_sectors,
        _monthly_periods,
        _quarterly_periods,
        _national_pair_frames,
        _state_pair_frames,
        _national_pair_frames_ca,
        _state_pair_frames_ca,
        _us_ca_national_pair_def,
        ADDITIONAL_STATE_PAIRS,
        MX_CA_NATIONAL_PAIRS,
        MX_CA_STATE_PAIRS,
        US_CA_NATIONAL_PAIRS,
    )
    from src.services.econometrics.pipeline_runner import run_all
    from src.services.export.to_json import export_all

    logger.info("Starting mock pipeline run...")
    sectors = _load_sectors()
    sectors_by_id = {s["id"]: s for s in sectors}

    monthly_dates = _monthly_periods()
    quarterly_dates = _quarterly_periods()

    series_lookup: dict[str, pd.DataFrame] = {}
    series_labels: dict[str, str] = {}
    pair_defs: list[dict[str, Any]] = []

    for idx, sector in enumerate(sectors):
        frames, labels, pair_def = _national_pair_frames(idx, sector, monthly_dates)
        series_lookup.update(frames)
        series_labels.update(labels)
        pair_defs.append(pair_def)

        if sector["id"] == "aeroespacial":
            state_frames, state_labels, state_pair_def = _state_pair_frames(
                idx + len(sectors),
                sector,
                quarterly_dates,
                monthly_dates,
            )
            series_lookup.update(state_frames)
            series_labels.update(state_labels)
            pair_defs.append(state_pair_def)

    for spec in ADDITIONAL_STATE_PAIRS:
        sector = sectors_by_id[spec["sector_id"]]
        mx = spec["mx"]
        us = spec["us"]
        state_frames, state_labels, state_pair_def = _state_pair_frames(
            spec["rng_index"],
            sector,
            quarterly_dates,
            monthly_dates,
            mx_region_code=mx["code"],
            mx_abbr=mx["abbr"],
            mx_state_label=mx["label"],
            us_region_code=us["code"],
            us_abbr=us["abbr"],
            us_state_label=us["label"],
            us_series_disambiguator=mx["abbr"],
        )
        series_lookup.update(state_frames)
        series_labels.update(state_labels)
        pair_defs.append(state_pair_def)

    for spec in MX_CA_NATIONAL_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        frames, labels, pair_def = _national_pair_frames_ca(spec["rng_index"], sector, monthly_dates)
        series_lookup.update(frames)
        series_labels.update(labels)
        pair_defs.append(pair_def)

    for spec in MX_CA_STATE_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        mx = spec["mx"]
        ca = spec["ca"]
        state_frames, state_labels, state_pair_def = _state_pair_frames_ca(
            spec["rng_index"], sector, quarterly_dates, monthly_dates,
            mx_region_code=mx["code"], mx_abbr=mx["abbr"], mx_state_label=mx["label"],
            ca_region_code=ca["code"], ca_abbr=ca["abbr"], ca_state_label=ca["label"],
        )
        series_lookup.update(state_frames)
        series_labels.update(state_labels)
        pair_defs.append(state_pair_def)

    for spec in US_CA_NATIONAL_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        pair_def = _us_ca_national_pair_def(sector, series_lookup)
        if pair_def is None:
            continue
        pair_defs.append(pair_def)

    results = run_all(pair_defs, series_lookup, sectors_by_id)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    manifest = export_all(
        sectors=sectors,
        series_lookup=series_lookup,
        series_labels=series_labels,
        pair_defs=pair_defs,
        results=results,
        mode="mock",
    )

    logger.info(f"Mock pipeline complete: {len(pair_defs)} pairs, manifest at {MANIFEST_PATH}")
    return PipelineRunResult(
        manifest=manifest,
        mode="mock",
        pairs_total=len(pair_defs),
        pairs_mock=len(pair_defs),
    )


def run_live_pipeline_wrapped() -> PipelineRunResult:
    from src.services.live.run_live import run_live_pipeline as _impl

    try:
        manifest = _impl()
        if manifest is None:
            return PipelineRunResult(error="Live pipeline produced no manifest", mode="live")
        mode = manifest.get("mode", "mixed")
        return PipelineRunResult(
            manifest=manifest,
            mode=mode,
            pairs_total=len(manifest.get("pairs", [])),
        )
    except Exception as exc:
        logger.error(f"Live pipeline failed: {exc}")
        traceback.print_exc()
        return PipelineRunResult(error=str(exc), mode="live")


def run_pipeline(mode: str = "mixed") -> PipelineRunResult:
    """Default is "mixed", not "mock": a caller that forgets to specify a
    mode should get real data where available (silently falling back to mock
    per-pair/per-indicator when a source or credential is missing) rather
    than a fully synthetic dataset by default. Explicit `mode="mock"` still
    works for local dev without API keys — see run_mock_pipeline()."""
    if mode == "mock":
        try:
            return run_mock_pipeline()
        except Exception as exc:
            logger.error(f"Mock pipeline failed: {exc}")
            traceback.print_exc()
            return PipelineRunResult(error=str(exc), mode="mock")

    if mode in ("live", "mixed"):
        try:
            return run_live_pipeline_wrapped()
        except Exception as exc:
            logger.error(f"Live pipeline failed: {exc}")
            traceback.print_exc()
            return PipelineRunResult(error=str(exc), mode=mode)

    return PipelineRunResult(error=f"Unknown pipeline mode: {mode}", mode=mode)
