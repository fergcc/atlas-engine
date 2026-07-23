"""Tests for the USA adapter's BEA GDP-by-state wiring.

Regression coverage for a real gap found while auditing connectors: BEA was
advertised as the "bea_gdp_state" indicator in list_indicators() (and
BEA_API_KEY / fetch_regional_gdp() already existed in bea.py/config.py), but
fetch_series() had no code path that ever called it — any state-level
request silently returned BLS employment data instead, regardless of which
indicator was asked for.
"""

from __future__ import annotations

import pytest


def test_bea_advertised_in_list_indicators():
    from src.adapters.registry import get_adapter

    us = get_adapter("US")
    indicator_ids = {i.id for i in us.list_indicators()}
    assert "bea_gdp_state" in indicator_ids


def test_fetch_series_defaults_to_bls_for_state_level(monkeypatch):
    """Backward compatibility: omitting indicator_id must keep returning BLS
    employment data, not silently switch to BEA."""
    from src.adapters.registry import get_adapter

    us = get_adapter("US")

    def fake_bls_fetch(series_ids):
        return [{"data": [{"year": "2024", "period": "M01", "value": "123.4"}]}]

    def fail_if_called(*args, **kwargs):
        raise AssertionError("BEA should not be called when indicator_id is not bea_gdp_state")

    monkeypatch.setattr("src.services.ingestion.bls.fetch_timeseries", fake_bls_fetch)
    monkeypatch.setattr("src.services.ingestion.bea.fetch_regional_gdp", fail_if_called)

    bundle = us.fetch_series("manufactura_total", "06")
    assert bundle.series_id.endswith("_bls")


def test_bea_gdp_state_series(monkeypatch):
    from src.adapters.registry import get_adapter

    us = get_adapter("US")

    fake_rows = [
        {"GeoFips": "06000", "TimePeriod": "2023Q1", "DataValue": "3,200,000"},
        {"GeoFips": "06000", "TimePeriod": "2023Q2", "DataValue": "3,250,500"},
        {"GeoFips": "06000", "TimePeriod": "2023Q3", "DataValue": "(NA)"},
    ]
    monkeypatch.setattr(
        "src.services.ingestion.bea.fetch_regional_gdp", lambda **kw: fake_rows
    )

    bundle = us.fetch_series("manufactura_total", "06", indicator_id="bea_gdp_state")

    assert bundle.series_id.endswith("_bea")
    assert len(bundle.tidy) == 2  # the "(NA)" row must be dropped
    assert bundle.tidy["value"].max() == pytest.approx(3250500.0)


def test_bea_period_to_month_handles_quarters_and_years():
    from src.adapters.usa import _bea_period_to_month

    assert _bea_period_to_month("2023Q1") == "2023-01"
    assert _bea_period_to_month("2023Q3") == "2023-07"
    assert _bea_period_to_month("2023") == "2023-01"
    assert _bea_period_to_month("garbage") is None


def test_bea_no_observations_raises(monkeypatch):
    from src.adapters.registry import get_adapter

    us = get_adapter("US")
    monkeypatch.setattr(
        "src.services.ingestion.bea.fetch_regional_gdp", lambda **kw: []
    )

    with pytest.raises(ValueError):
        us.fetch_series("manufactura_total", "06", indicator_id="bea_gdp_state")
