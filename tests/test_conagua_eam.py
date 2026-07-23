"""Tests for CONAGUA EAM/SINA ingestion and its fallback wiring in territorial.py.

Regression coverage for the same class of bug fixed in statcan_territorial.py:
conagua.py's hardcoded 2023 snapshot must never be tagged data_quality="real"
just because a value is present — only actual conagua_eam.py bulk-file data
may be tagged "real".
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_check_available_false_when_no_files(tmp_path, monkeypatch):
    from src.services.ingestion import conagua_eam

    monkeypatch.setattr(conagua_eam, "CACHE_DIR", tmp_path)
    assert conagua_eam.check_available() is False


def test_parse_returns_empty_when_no_files(tmp_path, monkeypatch):
    from src.services.ingestion import conagua_eam

    monkeypatch.setattr(conagua_eam, "CACHE_DIR", tmp_path)
    result = conagua_eam.parse_conagua_eam_data()
    assert result == {"water_stress": {}, "water_consumption_intensity": {}}


def test_parse_csv_extracts_water_stress(tmp_path):
    from src.services.ingestion import conagua_eam

    csv_path = tmp_path / "eam_2026.csv"
    csv_path.write_text(
        "Entidad federativa,Grado de presion (%),Consumo\n"
        "Aguascalientes,29.4,412.5\n"
        "Nuevo Leon,40.2,298.7\n"
        "Estado de Mexico,15.0,893.4\n",
        encoding="utf-8",
    )

    result = conagua_eam.parse_conagua_eam_data(data_path=csv_path)
    assert result["water_stress"]["01"] == 29.4
    assert result["water_stress"]["19"] == 40.2
    assert result["water_stress"]["15"] == 15.0


def test_parse_csv_no_matching_column_returns_empty_for_that_indicator(tmp_path):
    from src.services.ingestion import conagua_eam

    csv_path = tmp_path / "eam_2026.csv"
    csv_path.write_text(
        "Entidad federativa,Grado de presion (%)\nAguascalientes,29.4\n",
        encoding="utf-8",
    )

    result = conagua_eam.parse_conagua_eam_data(data_path=csv_path)
    assert result["water_stress"]["01"] == 29.4
    assert result["water_consumption_intensity"] == {}


def test_normalize_state_handles_prefixes_and_accents():
    from src.services.ingestion.conagua_eam import _normalize_state

    assert _normalize_state("Nuevo Leon") == "19"
    assert _normalize_state("Estado de Mexico") == "15"
    assert _normalize_state("Ciudad de Mexico") == "09"
    assert _normalize_state("Not A Real State") is None
    assert _normalize_state(None) is None


def test_conagua_fallback_never_tagged_real_when_no_eam_file(monkeypatch):
    """Regression: with no conagua_eam file present, territorial.py must tag
    the hardcoded conagua.py values as data_quality="synthetic", never "real"
    — the same bug class fixed for Canada in statcan_territorial.py."""
    from src.services.ingestion import conagua_eam
    from src.services import territorial as terr

    monkeypatch.setattr(conagua_eam, "parse_conagua_eam_data", lambda **kw: {
        "water_stress": {}, "water_consumption_intensity": {},
    })
    # _load_conagua_if_needed caches globally after its first call ever —
    # reset so this test doesn't read a stale result from another test.
    monkeypatch.setattr(terr, "_CONAGUA_LOADED", False)
    monkeypatch.setattr(terr, "_CONAGUA_CACHE", None)

    catalog = [{"id": "water_stress"}, {"id": "water_consumption_intensity"}]
    loaded = terr._load_conagua_if_needed(catalog, "MX")
    assert loaded is not None
    data, is_live = loaded

    assert all(v is False for v in is_live.values())
    for ind_id, region_values in data.items():
        for region_code in region_values:
            value, dq, note = terr._conagua_indicator_value(ind_id, region_code, data, is_live)
            assert dq == "synthetic", f"{ind_id}/{region_code} wrongly tagged {dq!r}"


def test_conagua_real_eam_data_tagged_real(monkeypatch):
    """When a real conagua_eam file is present, its values must be tagged
    "real" — the fix must not make everything synthetic either."""
    from src.services.ingestion import conagua_eam
    from src.services import territorial as terr

    monkeypatch.setattr(conagua_eam, "parse_conagua_eam_data", lambda **kw: {
        "water_stress": {"01": 12.3},
        "water_consumption_intensity": {},
    })
    monkeypatch.setattr(terr, "_CONAGUA_LOADED", False)
    monkeypatch.setattr(terr, "_CONAGUA_CACHE", None)

    catalog = [{"id": "water_stress"}, {"id": "water_consumption_intensity"}]
    loaded = terr._load_conagua_if_needed(catalog, "MX")
    assert loaded is not None
    data, is_live = loaded

    assert is_live["water_stress"] is True
    assert is_live["water_consumption_intensity"] is False

    value, dq, note = terr._conagua_indicator_value("water_stress", "01", data, is_live)
    assert dq == "real"
    assert value == 12.3
