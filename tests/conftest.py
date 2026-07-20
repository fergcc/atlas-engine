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


@pytest.fixture
async def client(use_temp_paths) -> AsyncIterator:
    from httpx import ASGITransport, AsyncClient
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
