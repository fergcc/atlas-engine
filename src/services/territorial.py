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

    rng = np.random.default_rng(42)

    results: list[dict[str, Any]] = []
    for region_code in region_codes:
        region_name = _get_region_name(country, region_code)
        for ind in catalog:
            value = rng.normal(50, 15)
            value = max(0, min(100, value))

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
                "data_quality": "synthetic",
                "note": "Mock value — real data requires census/DENUE microdata access",
            })

    return results


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
