"""Tests for Settings — mainly regression coverage for credentials that must
be declared so they're discoverable/configurable, even when the ingestion
module that consumes them reads the environment variable directly.
"""

from __future__ import annotations


def test_settings_declares_census_api_key(monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", "test-key-123")

    from src.config import Settings

    settings = Settings()
    assert settings.census_api_key == "test-key-123"


def test_settings_census_api_key_defaults_empty(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)

    from src.config import Settings

    settings = Settings()
    assert settings.census_api_key == ""
