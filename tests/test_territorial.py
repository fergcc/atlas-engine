"""
Tests for territorial indicator computation and catalog.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_indicators_catalog_loaded(client: AsyncClient):
    """Catalog is 23 indicators (4 phase A, 19 phase B) as of the commit that
    removed 11 survey-only indicators with no real data source — these
    assertions previously said 34/14/20, stale since that removal."""
    response = await client.get("/api/v1/analysis/indicators/catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["total_indicators"] == 23
    assert data["by_phase"]["A"] == 4
    assert data["by_phase"]["B"] == 19
    assert len(data["themes"]) >= 6
    assert len(data["indicators"]) == 23


@pytest.mark.asyncio
async def test_indicators_have_required_fields(client: AsyncClient):
    response = await client.get("/api/v1/analysis/indicators/catalog")
    data = response.json()
    for ind in data["indicators"]:
        assert "id" in ind
        assert "name" in ind
        assert "theme" in ind
        assert "phase" in ind
        assert "unit" in ind
        assert "methodology" in ind
        assert "source" in ind
        assert "polarity" in ind
        assert "standardization" in ind


@pytest.mark.asyncio
async def test_territorial_analysis_mx(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/territorial",
        json={
            "country": "MX",
            "region_codes": ["08", "02"],
            "sector_id": "aeroespacial",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "MX"
    assert data["total_indicators"] == 23
    assert data["total_regions"] == 2
    assert len(data["by_region"]) == 2
    assert len(data["raw_values"]) == 23 * 2


@pytest.mark.asyncio
async def test_territorial_analysis_all_regions(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/territorial",
        json={"country": "MX", "sector_id": "manufactura_total"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_regions"] == 32


@pytest.mark.asyncio
async def test_territorial_analysis_no_adapter_fallback(client: AsyncClient):
    response = await client.post(
        "/api/v1/analysis/territorial",
        json={"country": "BR", "sector_id": "aeroespacial"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "BR"
    assert data["total_regions"] == 1
    assert data["by_region"][0]["region_code"] == "NAC"


def test_canada_fallback_never_tagged_real(monkeypatch):
    """Regression: statcan_territorial getters that have no live source wired
    (or whose live fetch fails) always return FALLBACK_CA — territorial.py
    must tag those as data_quality="synthetic", never "real". Previously any
    non-empty dict was tagged "real" regardless of provenance, so Canada's
    exported territorial data was 100% synthetic despite being labeled real.
    """
    from src.services.ingestion import statcan_territorial as sc
    from src.services import territorial as terr

    live_fetcher_names = [
        "_fetch_live_potable_water_access",
        "_fetch_live_overcrowding",
        "_fetch_live_homicide_rate",
        "_fetch_live_extreme_poverty",
        "_fetch_live_foreign_capital_presence",
        "_fetch_live_innovation_economic_units",
        "_fetch_live_water_stress",
        "_fetch_live_employed_population",
    ]
    # Simulate "no live source available" (e.g. network/API absent) for every
    # StatCan fetch that normally attempts one.
    for name in live_fetcher_names:
        monkeypatch.setattr(sc, name, lambda: {})

    data, is_live = sc.parse_statcan_territorial_data()

    # Every indicator resolves to the fallback dict and is marked non-live.
    for ind_id, values in data.items():
        assert values == dict(sc.FALLBACK_CA.get(ind_id, {}))
    assert all(v is False for v in is_live.values())

    # territorial.py must therefore tag every one of them "synthetic".
    for ind_id, region_values in data.items():
        for region_code in region_values:
            value, dq, note = terr._statcan_indicator_value(ind_id, region_code, data, is_live)
            assert dq == "synthetic", f"{ind_id}/{region_code} wrongly tagged {dq!r}"


def test_statcan_live_value_tagged_real():
    """When a StatCan fetch actually succeeds this run, the value must be
    tagged "real" — the fix must not make everything synthetic either."""
    from src.services import territorial as terr

    data = {"homicide_rate": {"35": 1.5}}
    is_live = {"homicide_rate": True}
    value, dq, note = terr._statcan_indicator_value("homicide_rate", "35", data, is_live)
    assert dq == "real"
    assert value == 1.5


@pytest.mark.asyncio
async def test_territorial_export_includes_all_countries(monkeypatch, tmp_path):
    """Regression: _export_territorial() must compute MX, US, and CA into the
    single territorial.json the Dashboard reads — previously it was hardcoded
    to MX only, so US/CA state pages silently rendered zero indicator rows.

    Stubs compute_indicator_values() itself so this only exercises the
    three-country loop/aggregation in _export_territorial(), not the full
    (network-touching) ingestion stack — that's covered by the other
    territorial/adapter tests.
    """
    from src.services import territorial as terr
    from src.services.live import run_live

    monkeypatch.setattr("src.config.DATA_DIR", tmp_path)

    def fake_compute_indicator_values(country, region_codes=None, indicator_ids=None, sector_id=None):
        return [{
            "indicator_id": "water_stress",
            "indicator_name": "Water stress",
            "indicator_name_en": "Water stress",
            "theme": "environment",
            "subtheme": "water",
            "phase": "B",
            "country": country,
            "region_code": f"{country}-01",
            "region_name": f"{country} region 1",
            "sector_id": sector_id,
            "value": 42.0,
            "unit": "%",
            "standardization": "z_score",
            "polarity": "neutral",
            "source": "test",
            "data_quality": "real",
            "note": "",
        }]

    monkeypatch.setattr(terr, "compute_indicator_values", fake_compute_indicator_values)
    monkeypatch.setattr(run_live, "_sync_to_dashboard", lambda: None)

    run_live._export_territorial()

    import json

    exported = json.loads((tmp_path / "territorial.json").read_text(encoding="utf-8"))
    countries_present = {v["country"] for v in exported["raw_values"]}
    assert countries_present == {"MX", "US", "CA"}
    assert exported["regions_by_country"] == {"MX": 1, "US": 1, "CA": 1}


@pytest.mark.asyncio
async def test_indicator_catalog_direct():
    from src.services.territorial import (
        load_indicators,
        get_indicators_by_theme,
        get_indicators_by_phase,
    )
    catalog = load_indicators()
    assert len(catalog) == 23  # 34 originally, 11 survey-only indicators removed since

    by_theme = get_indicators_by_theme()
    assert len(by_theme) >= 6

    by_phase = get_indicators_by_phase()
    assert len(by_phase["A"]) == 4
    assert len(by_phase["B"]) == 19

    indicator_ids = {ind["id"] for ind in catalog}
    assert "employed_population" in indicator_ids
    assert "homicide_rate" in indicator_ids
    assert "water_stress" in indicator_ids
    assert "talent_attraction" in indicator_ids
