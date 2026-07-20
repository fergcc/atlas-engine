"""Tests for the live pipeline module and live/mixed pipeline execution."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.fixture
def temp_live_dirs(monkeypatch: pytest.MonkeyPatch):
    """Create temporary dirs for live pipeline output, isolating from other tests."""
    tmp_data = tempfile.TemporaryDirectory()
    tmp_engine = Path(tmp_data.name)
    monkeypatch.setattr("src.config.DATA_DIR", tmp_engine)
    monkeypatch.setattr("src.config.SERIES_DIR", tmp_engine / "series")
    monkeypatch.setattr("src.config.RESULTS_DIR", tmp_engine / "results")
    monkeypatch.setattr("src.config.MANIFEST_PATH", tmp_engine / "manifest.json")
    (tmp_engine / "series").mkdir(parents=True, exist_ok=True)
    (tmp_engine / "results").mkdir(parents=True, exist_ok=True)
    yield
    tmp_data.cleanup()


@pytest.mark.asyncio
async def test_admin_run_pipeline_live_falls_back_to_mock(client: AsyncClient):
    """Without API keys, live mode should complete successfully by falling back to mock."""
    response = await client.post(
        "/api/v1/admin/run-pipeline",
        json={"mode": "live"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "error" not in data or data["error"] is None


@pytest.mark.asyncio
async def test_admin_run_pipeline_mixed_falls_back_to_mock(client: AsyncClient):
    """Without API keys, mixed mode should complete successfully."""
    response = await client.post(
        "/api/v1/admin/run-pipeline",
        json={"mode": "mixed"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_admin_run_pipeline_unknown_mode(client: AsyncClient):
    """Unknown pipeline mode should return an error."""
    response = await client.post(
        "/api/v1/admin/run-pipeline",
        json={"mode": "unknown"},
    )
    assert response.status_code == 422


def test_live_pipeline_module_imports():
    """The live pipeline module should be importable."""
    from src.services.live.run_live import run_live_pipeline

    assert callable(run_live_pipeline)


def test_live_pipeline_module_has_helpers():
    """Helper functions should be importable."""
    from src.services.live.run_live import (
        _fetch_national_pair,
        _fetch_state_pair,
        _fetch_canada_national_pair,
        _fetch_canada_state_pair,
    )
    assert callable(_fetch_national_pair)
    assert callable(_fetch_state_pair)
    assert callable(_fetch_canada_national_pair)
    assert callable(_fetch_canada_state_pair)


def test_live_pipeline_runs_without_api_keys(temp_live_dirs):
    """Running the live pipeline directly (without API keys) should produce
    a manifest with mock data as fallback for all pairs."""
    from src.services.live.run_live import run_live_pipeline

    manifest = run_live_pipeline()
    assert manifest is not None
    assert "mode" in manifest
    assert manifest["mode"] in ("mock", "mixed", "live")
    assert "sectors" in manifest
    assert len(manifest["sectors"]) == 6
    assert "series_catalog" in manifest
    assert "pairs" in manifest
    assert len(manifest["pairs"]) == 31


def test_live_pipeline_via_orchestrator(temp_live_dirs):
    """The pipeline orchestrator should accept live mode."""
    from src.services.pipeline import run_pipeline

    result = run_pipeline(mode="live")
    assert result.error is None
    assert result.pairs_total >= 0


def test_live_pipeline_via_orchestrator_mixed(temp_live_dirs):
    """The pipeline orchestrator should accept mixed mode."""
    from src.services.pipeline import run_pipeline

    result = run_pipeline(mode="mixed")
    assert result.error is None
    assert result.pairs_total >= 0
