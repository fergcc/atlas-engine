"""
Test fixtures for the Atlas Engine.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from collections.abc import AsyncIterator

import pytest


@pytest.fixture
def temp_db() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def temp_data_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def use_temp_paths(temp_db: Path, temp_data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENGINE_ENV", "development")
    monkeypatch.setenv("ENGINE_USE_MOCKS", "true")
    monkeypatch.setenv("ENGINE_DB_PATH", str(temp_db))
    monkeypatch.setenv("ENGINE_DATA_DIR", str(temp_data_dir))

    (temp_data_dir / "series").mkdir(parents=True, exist_ok=True)
    (temp_data_dir / "results").mkdir(parents=True, exist_ok=True)

    _path_map = {
        "DATA_DIR": temp_data_dir,
        "SERIES_DIR": temp_data_dir / "series",
        "RESULTS_DIR": temp_data_dir / "results",
        "MANIFEST_PATH": temp_data_dir / "manifest.json",
    }
    for mod_path in [
        "src.config",
        "src.services.pipeline",
        "src.services.export.to_json",
        "src.services.live.run_live",
        "src.api.routes.data",
    ]:
        for attr, target in _path_map.items():
            try:
                monkeypatch.setattr(f"{mod_path}.{attr}", target)
            except AttributeError:
                pass


@pytest.fixture
async def client(use_temp_paths) -> AsyncIterator:
    from httpx import ASGITransport, AsyncClient
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
