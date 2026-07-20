"""
Territorial indicator computation service.

Computes the 34 territorial indicators from the Atlas methodology
at the subnational level. Uses adapter data where available;
falls back to synthetic/mock values for indicators without real data.

The indicator catalog is defined in reference/indicators.yaml.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import yaml

from src.config import REFERENCE_DIR
from src.adapters.registry import get_adapter

logger = logging.getLogger(__name__)

_indicators_catalog: list[dict[str, Any]] | None = None


def load_indicators() -> list[dict[str, Any]]:
    global _indicators_catalog
    if _indicators_catalog is not None:
        return _indicators_catalog

    path = REFERENCE_DIR / "indicators.yaml"
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    _indicators_catalog = data.get("indicators", [])
    logger.info(f"Loaded {len(_indicators_catalog)} indicators from catalog")
    return _indicators_catalog


def get_indicators_by_theme() -> dict[str, list[dict[str, Any]]]:
    catalog = load_indicators()
    by_theme: dict[str, list[dict[str, Any]]] = {}
    for ind in catalog:
        theme = ind.get("subtheme", ind.get("theme", "other"))
        by_theme.setdefault(theme, []).append(ind)
    return by_theme


def get_indicators_by_phase() -> dict[str, list[dict[str, Any]]]:
    catalog = load_indicators()
    by_phase: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
    for ind in catalog:
        by_phase[ind.get("phase", "B")].append(ind)
    return by_phase


def compute_indicator_values(
    country: str,
    region_codes: list[str] | None = None,
    indicator_ids: list[str] | None = None,
    sector_id: str | None = None,
) -> list[dict[str, Any]]:
    catalog = load_indicators()
    if indicator_ids:
        catalog = [ind for ind in catalog if ind["id"] in indicator_ids]

    adapter = get_adapter(country)
    if region_codes is None and adapter is not None:
        regions = adapter.list_regions()
        region_codes = [r.code for r in regions]
    elif region_codes is None:
        region_codes = ["NAC"]

    crime_data = _load_sesnsp_if_needed(catalog, country)

    rng = np.random.default_rng(42)

    results: list[dict[str, Any]] = []
    for region_code in region_codes:
        region_name = _get_region_name(country, region_code)
        for ind in catalog:
            value, data_quality, note = _compute_value(
                ind, country, region_code, rng, crime_data
            )

            results.append({
                "indicator_id": ind["id"],
                "indicator_name": ind["name"],
                "indicator_name_en": ind.get("name_en", ""),
                "theme": ind.get("theme", ""),
                "subtheme": ind.get("subtheme", ""),
                "phase": ind.get("phase", "B"),
                "country": country,
                "region_code": region_code,
                "region_name": region_name,
                "sector_id": sector_id,
                "value": round(value, 2),
                "unit": ind.get("unit", ""),
                "standardization": ind.get("standardization", "z_score"),
                "polarity": ind.get("polarity", "neutral"),
                "source": ind.get("source", ""),
                "data_quality": data_quality,
                "note": note,
            })

    return results


def _compute_value(
    ind: dict[str, Any],
    country: str,
    region_code: str,
    rng: np.random.Generator,
    crime_data: dict[str, Any] | None,
) -> tuple[float, str, str]:
    indicator_id = ind["id"]

    if country == "MX" and indicator_id in ("homicide_rate", "robbery_rate", "domestic_violence_rate"):
        if crime_data:
            value, dq, note = _crime_indicator_value(indicator_id, region_code, crime_data)
            if dq == "real":
                return value, dq, note

    value = rng.normal(50, 15)
    value = max(0, min(100, value))
    return value, "synthetic", "Mock value — real data requires census/DENUE microdata access"


_SESNSP_CACHE: dict[str, Any] | None = None
_SESNSP_CACHE_LOADED = False


def _load_sesnsp_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, Any] | None:
    global _SESNSP_CACHE, _SESNSP_CACHE_LOADED
    if _SESNSP_CACHE_LOADED:
        return _SESNSP_CACHE

    _SESNSP_CACHE_LOADED = True
    if country != "MX":
        return None

    crime_ids = {"homicide_rate", "robbery_rate", "domestic_violence_rate"}
    if not any(ind["id"] in crime_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.sesnsp import compute_crime_rate, get_crime_data, get_latest_year_totals

        data = get_crime_data()
        if not data:
            logger.info("SESNSP: no data available, crime indicators will use mock values")
            return None

        latest = {}
        for ind_id in crime_ids:
            totals = get_latest_year_totals(data, ind_id)
            latest[ind_id] = totals

        _SESNSP_CACHE = {"data": latest, "compute_rate": compute_crime_rate}
        logger.info(f"SESNSP: loaded crime data for {len(latest)} indicators")
        return _SESNSP_CACHE
    except Exception as exc:
        logger.warning(f"SESNSP: failed to load crime data ({exc}), using mock values")
        return None


def _crime_indicator_value(
    indicator_id: str,
    region_code: str,
    crime_data: dict[str, Any],
) -> tuple[float, str, str]:
    totals = crime_data["data"].get(indicator_id, {})
    compute_rate = crime_data["compute_rate"]

    total_crimes = 0
    total_pop = 0

    for muni_code, count in totals.items():
        muni_state = muni_code[:2] if len(muni_code) >= 2 else muni_code
        if muni_state == region_code:
            total_crimes += count

    # Try municipal-level population first, then state-level
    pop_lookup = _get_population_lookup()
    for muni_code in totals:
        muni_state = muni_code[:2] if len(muni_code) >= 2 else muni_code
        if muni_state == region_code:
            mun_pop = pop_lookup.get(muni_code, 0)
            if mun_pop > 0:
                total_pop += mun_pop

    # Fallback: use state population if no municipal data
    if total_pop == 0:
        total_pop = _STATE_POPULATION_2020.get(region_code, 0)

    if total_pop > 0:
        rate = compute_rate(indicator_id, total_crimes, total_pop)
        indicator_names = {
            "homicide_rate": "Homicidios",
            "robbery_rate": "Robos",
            "domestic_violence_rate": "Violencia doméstica",
        }
        name = indicator_names.get(indicator_id, indicator_id)
        return (
            round(rate, 2),
            "real",
            f"{name} — SESNSP municipal agregado estatal (2026), tasa por 100k hab",
        )

    return (0.0, "synthetic", "Mock — SESNSP sin datos para este estado")


_POP_CACHE: dict[str, int] | None = None

# INEGI Censo de Población 2020 — state-level totals
_STATE_POPULATION_2020: dict[str, int] = {
    "01": 1425607, "02": 3769020, "03": 798447, "04": 928363,
    "05": 3146771, "06": 731391, "07": 5543828, "08": 3741869,
    "09": 9209944, "10": 1832650, "11": 6166934, "12": 3540685,
    "13": 3082841, "14": 8348151, "15": 16992418, "16": 4748846,
    "17": 1971520, "18": 1235456, "19": 5784442, "20": 4132148,
    "21": 6583278, "22": 2368467, "23": 1857985, "24": 2822255,
    "25": 3026943, "26": 2944840, "27": 2402598, "28": 3527735,
    "29": 1342977, "30": 8062579, "31": 2320898, "32": 1622138,
}


def _get_population_lookup() -> dict[str, int]:
    global _POP_CACHE
    if _POP_CACHE is not None:
        return _POP_CACHE

    _POP_CACHE = {}
    try:
        # Try to load from cached CSV first
        from src.config import DATA_DIR
        pop_file = DATA_DIR / "sesnsp" / "poblacion_municipal.csv"
        if pop_file.exists():
            import csv
            for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
                try:
                    with open(pop_file, encoding=encoding) as fh:
                        reader = csv.DictReader(fh)
                        for row in reader:
                            ent = (row.get("Cve_Ent", row.get("cve_ent", row.get("Clave_Ent", ""))) or "").strip().zfill(2)
                            mun = (row.get("Cve_Mun", row.get("cve_mun", row.get("Cve. Municipio", ""))) or "").strip().zfill(3)
                            pop_str = row.get("Poblacion", row.get("POBLACION", row.get("Población", "0")))
                            try:
                                _POP_CACHE[ent + mun] = int(float(pop_str))
                            except (ValueError, TypeError):
                                pass
                    if _POP_CACHE:
                        logger.info(f"Loaded population data for {len(_POP_CACHE)} municipalities from CSV")
                        return _POP_CACHE
                except (UnicodeDecodeError, UnicodeError):
                    continue
    except Exception as exc:
        logger.info(f"No municipal population CSV ({exc}); using state-level population")

    # Fallback: use state-level population as default for all municipalities
    for state_code, pop in _STATE_POPULATION_2020.items():
        _POP_CACHE[state_code] = pop
    logger.info(f"Using state-level population (32 states, INEGI 2020)")

    return _POP_CACHE


def _get_region_name(country: str, region_code: str) -> str:
    adapter = get_adapter(country)
    if adapter:
        for r in adapter.list_regions():
            if r.code == region_code:
                return r.name
    return region_code


def build_indicator_matrix(
    country: str,
    region_codes: list[str] | None = None,
    sector_id: str | None = None,
) -> dict[str, Any]:
    values = compute_indicator_values(
        country=country,
        region_codes=region_codes,
        sector_id=sector_id,
    )

    by_region: dict[str, dict[str, float]] = {}
    for v in values:
        rc = v["region_code"]
        if rc not in by_region:
            by_region[rc] = {"region_code": rc, "region_name": v["region_name"]}
        by_region[rc][v["indicator_id"]] = v["value"]

    return {
        "country": country,
        "sector_id": sector_id,
        "total_indicators": len(set(v["indicator_id"] for v in values)),
        "total_regions": len(by_region),
        "data_quality": "synthetic",
        "by_region": list(by_region.values()),
        "raw_values": values,
    }
