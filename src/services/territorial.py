"""
Territorial indicator computation service.

Computes the 34 territorial indicators from the Atlas methodology
at the subnational level. Uses adapter data where available;
falls back to synthetic/mock values for indicators without real data.

The indicator catalog is defined in reference/indicators.yaml.

Results are cached in-memory with a 1-hour TTL since data sources
are static (census, CONEVAL) or slow-changing (crime, employment).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import yaml

from src.config import REFERENCE_DIR
from src.adapters.registry import get_adapter

logger = logging.getLogger(__name__)

_indicators_catalog: list[dict[str, Any]] | None = None

# Simple TTL cache for computed indicator values
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_TTL = 3600  # 1 hour


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
    cache_key = f"{country}_{sector_id or 'all'}_{','.join(sorted(indicator_ids or []))}_{','.join(sorted(region_codes or []))}"
    now = time.time()
    if cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            logger.info(f"Territorial cache hit ({now - cached_time:.0f}s old)")
            return cached_data
        else:
            del _cache[cache_key]

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
    censo_data = _load_censo_if_needed(catalog, country)
    coneval_data = _load_coneval_if_needed(catalog, country)
    enoe_data = _load_enoe_if_needed(catalog, country)
    denue_data = _load_denue_if_needed(catalog, country)
    conagua_loaded = _load_conagua_if_needed(catalog, country)
    conagua_data, conagua_is_live = conagua_loaded if conagua_loaded is not None else (None, {})

    acs_data = _load_acs_if_needed(catalog, country)
    ucr_data = _load_ucr_if_needed(catalog, country)
    bls_state_data = _load_bls_state_if_needed(catalog, country)
    cbp_data = _load_cbp_if_needed(catalog, country)
    saipe_data = _load_saipe_if_needed(catalog, country)
    statcan_loaded = _load_statcan_if_needed(catalog, country)
    statcan_data, statcan_is_live = statcan_loaded if statcan_loaded is not None else (None, {})

    rng = np.random.default_rng(42)

    results: list[dict[str, Any]] = []
    for region_code in region_codes:
        region_name = _get_region_name(country, region_code)
        for ind in catalog:
            value, data_quality, note = _compute_value(
                ind, country, region_code, rng, crime_data, censo_data, coneval_data, enoe_data, denue_data, conagua_data, acs_data, ucr_data, bls_state_data, cbp_data, saipe_data, statcan_data, statcan_is_live, conagua_is_live
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

    _cache[cache_key] = (now, results)
    return results


def _compute_value(
    ind: dict[str, Any],
    country: str,
    region_code: str,
    rng: np.random.Generator,
    crime_data: dict[str, Any] | None,
    censo_data: dict[str, dict[str, float]] | None,
    coneval_data: dict[str, dict[str, float]] | None,
    enoe_data: dict[str, dict[str, float]] | None,
    denue_data: dict[str, dict[str, int]] | None,
    conagua_data: dict[str, dict[str, float]] | None,
    acs_data: dict[str, dict[str, float]] | None = None,
    ucr_data: dict[str, Any] | None = None,
    bls_state_data: dict[str, dict[str, float]] | None = None,
    cbp_data: dict[str, dict[str, int]] | None = None,
    saipe_data: dict[str, dict[str, float]] | None = None,
    statcan_data: dict[str, dict[str, float]] | None = None,
    statcan_is_live: dict[str, bool] | None = None,
    conagua_is_live: dict[str, bool] | None = None,
) -> tuple[float, str, str]:
    indicator_id = ind["id"]

    def _mock() -> tuple[float, str, str]:
        value = rng.normal(50, 15)
        value = max(0, min(100, value))
        return value, "synthetic", "Mock — no data source wired for this country/indicator"

    # ——— United States data sources ———
    if country == "US":
        # ACS census indicators
        _acs_ids = {
            "potable_water_access", "drainage_access", "internet_access",
            "overcrowding", "self_built_housing", "talent_attraction",
            "educated_personnel", "public_transport_usage", "avg_commute_time",
            "land_tenure_vulnerability",
        }
        if indicator_id in _acs_ids and acs_data:
            value, dq, note = _acs_indicator_value(indicator_id, region_code, acs_data)
            if dq == "real":
                return value, dq, note

        # FBI UCR crime indicators
        if indicator_id in ("homicide_rate", "robbery_rate", "domestic_violence_rate"):
            if ucr_data:
                value, dq, note = _ucr_indicator_value(indicator_id, region_code, ucr_data)
                if dq == "real":
                    return value, dq, note

        # BLS state employment indicators
        _bls_ids = {"employed_population", "female_employment", "hours_worked", "remuneration_level"}
        if indicator_id in _bls_ids and bls_state_data:
            value, dq, note = _bls_state_indicator_value(indicator_id, region_code, bls_state_data)
            if dq == "real":
                return value, dq, note

        # Census CBP establishment indicators
        _cbp_ids = {"foreign_capital_presence", "daycare_services", "innovation_economic_units"}
        if indicator_id in _cbp_ids and cbp_data:
            value, dq, note = _cbp_indicator_value(indicator_id, region_code, cbp_data)
            if dq == "real":
                return value, dq, note

        # SAIPE poverty indicator
        if indicator_id == "extreme_poverty" and saipe_data:
            value, dq, note = _saipe_indicator_value(indicator_id, region_code, saipe_data)
            if dq == "real":
                return value, dq, note

        # Water: no US equivalent of CONAGUA wired yet — stays mock
        # Surveys: no US equivalent wired yet — stays mock
        # Poverty: no US equivalent wired yet — stays mock

        # Report mock for US indicators without real data
        return _mock()

    # ——— Mexico data sources ———
    if country == "MX":
        # SESNSP crime indicators
        if indicator_id in ("homicide_rate", "robbery_rate", "domestic_violence_rate"):
            if crime_data:
                value, dq, note = _crime_indicator_value(indicator_id, region_code, crime_data)
                if dq == "real":
                    return value, dq, note

        # Censo 2020 indicators
        _censo_ids = {
            "potable_water_access", "drainage_access", "internet_access",
            "overcrowding", "self_built_housing", "talent_attraction",
            "public_transport_usage", "avg_commute_time",
        }
        if indicator_id in _censo_ids and censo_data:
            value, dq, note = _censo_indicator_value(indicator_id, region_code, censo_data)
            if dq == "real":
                return value, dq, note

        # CONEVAL indicators
        if indicator_id in ("extreme_poverty", "land_tenure_vulnerability") and coneval_data:
            value, dq, note = _coneval_indicator_value(indicator_id, region_code, coneval_data)
            if dq == "real":
                return value, dq, note

        # ENOE employment indicators
        _enoe_ids = {"employed_population", "female_employment", "hours_worked", "remuneration_level", "educated_personnel"}
        if indicator_id in _enoe_ids and enoe_data:
            value, dq, note = _enoe_indicator_value(indicator_id, region_code, enoe_data)
            if dq == "real":
                return value, dq, note

        # DENUE establishment indicators
        _denue_ids = {"foreign_capital_presence", "daycare_services", "innovation_economic_units"}
        if indicator_id in _denue_ids and denue_data:
            value, dq, note = _denue_indicator_value(indicator_id, region_code, denue_data)
            if dq == "real":
                return value, dq, note

        # CONAGUA water indicators
        _conagua_ids = {"water_stress", "water_consumption_intensity"}
        if indicator_id in _conagua_ids and conagua_data:
            value, dq, note = _conagua_indicator_value(
                indicator_id, region_code, conagua_data, conagua_is_live or {}
            )
            if dq == "real":
                return value, dq, note

        return _mock()

    # ——— Canada data sources ———
    if country == "CA":
        _ca_ids = {
            "potable_water_access", "drainage_access", "overcrowding",
            "self_built_housing", "talent_attraction", "educated_personnel",
            "land_tenure_vulnerability", "homicide_rate", "robbery_rate",
            "domestic_violence_rate", "extreme_poverty", "employed_population",
            "female_employment", "hours_worked", "remuneration_level",
            "foreign_capital_presence", "innovation_economic_units",
            "daycare_services", "water_stress", "water_consumption_intensity",
            "internet_access", "public_transport_usage", "avg_commute_time",
        }
        if indicator_id in _ca_ids and statcan_data:
            value, dq, note = _statcan_indicator_value(
                indicator_id, region_code, statcan_data, statcan_is_live or {}
            )
            if dq == "real":
                return value, dq, note

        return _mock()

    # Other countries: all mock
    return _mock()


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
        "data_quality": _data_quality_override(values) if values else "synthetic",
        "by_region": list(by_region.values()),
        "raw_values": values,
    }


def _data_quality_override(values: list[dict[str, Any]]) -> str:
    qualities = {v.get("data_quality") for v in values}
    if "real" in qualities:
        return "mixed"
    return "synthetic"


def export_territorial_json(country: str = "MX") -> dict[str, Any]:
    """Compute all territorial data for all states and return as JSON dict.
    
    Used at build time to generate static data for the Dashboard.
    Caches result to avoid recomputation on subsequent calls.
    """
    adapter = get_adapter(country)
    region_codes = [r.code for r in adapter.list_regions()] if adapter else [f"{i:02d}" for i in range(1, 33)]
    
    result = build_indicator_matrix(country=country, region_codes=region_codes)
    result["generated_at"] = __import__("datetime").datetime.now().isoformat()
    return result


# ————————————————————————————————————————————
# Censo 2020 data loading and indicator computation
# ————————————————————————————————————————————

_CENSO_CACHE: dict[str, dict[str, float]] | None = None
_CENSO_LOADED = False


def _load_censo_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, float]] | None:
    global _CENSO_CACHE, _CENSO_LOADED
    if _CENSO_LOADED:
        return _CENSO_CACHE
    _CENSO_LOADED = True

    if country != "MX":
        return None

    censo_ids = {"potable_water_access", "drainage_access", "internet_access",
                 "overcrowding", "self_built_housing", "talent_attraction"}
    if not any(ind["id"] in censo_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.censo2020 import get_state_aggregates, parse_iter_data
        data = parse_iter_data()
        if not data or not data.get("potable_water_access"):
            logger.info("Censo2020: no data available")
            return None
        _CENSO_CACHE = data
        logger.info(f"Censo2020: loaded data for {len(data)} indicators")
        return _CENSO_CACHE
    except Exception as exc:
        logger.warning(f"Censo2020: failed to load ({exc}), using mock values")
        return None


def _censo_indicator_value(
    indicator_id: str,
    region_code: str,
    censo_data: dict[str, dict[str, float]],
) -> tuple[float, str, str]:
    from src.services.ingestion.censo2020 import get_state_aggregates

    indicator_names = {
        "potable_water_access": "Agua potable",
        "drainage_access": "Drenaje",
        "internet_access": "Internet",
        "overcrowding": "Hacinamiento",
        "land_tenure_vulnerability": "Tenencia vulnerable",
        "self_built_housing": "Autoconstrucción (piso tierra)",
        "talent_attraction": "Atracción de talento",
        "public_transport_usage": "Transporte público",
        "avg_commute_time": "Tiempo traslado",
    }
    units = {
        "overcrowding": "%",
        "potable_water_access": "%",
        "drainage_access": "%",
        "internet_access": "%",
        "land_tenure_vulnerability": "%",
        "self_built_housing": "%",
        "talent_attraction": "%",
        "public_transport_usage": "%",
        "avg_commute_time": "min",
    }

    state_vals = get_state_aggregates(censo_data, indicator_id)
    value = state_vals.get(region_code)
    if value is not None:
        name = indicator_names.get(indicator_id, indicator_id)
        unit = units.get(indicator_id, "%")
        return (
            round(value, 2),
            "real",
            f"{name} — Censo 2020 (ITER), promedio estatal, {unit}",
        )

    return (0.0, "synthetic", f"Mock — Censo 2020 sin datos para estado {region_code}")


# ————————————————————————————————————————————
# CONEVAL data loading and indicator computation
# ————————————————————————————————————————————

_CONEVAL_CACHE: dict[str, dict[str, float]] | None = None
_CONEVAL_LOADED = False


def _load_coneval_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, float]] | None:
    global _CONEVAL_CACHE, _CONEVAL_LOADED
    if _CONEVAL_LOADED:
        return _CONEVAL_CACHE
    _CONEVAL_LOADED = True

    if country != "MX":
        return None

    if not any(ind["id"] == "extreme_poverty" for ind in catalog):
        return None

    try:
        from src.services.ingestion.coneval import get_state_aggregates, parse_coneval_data
        data = parse_coneval_data()
        if not data or not data.get("extreme_poverty"):
            logger.info("CONEVAL: no data available")
            return None
        _CONEVAL_CACHE = data
        logger.info(f"CONEVAL: loaded poverty data for {len(data.get('extreme_poverty', {}))} municipalities")
        return _CONEVAL_CACHE
    except Exception as exc:
        logger.warning(f"CONEVAL: failed to load ({exc}), using mock values")
        return None


def _coneval_indicator_value(
    indicator_id: str,
    region_code: str,
    coneval_data: dict[str, dict[str, float]],
) -> tuple[float, str, str]:
    from src.services.ingestion.coneval import get_state_aggregates

    indicator_names = {
        "extreme_poverty": "Pobreza extrema",
        "land_tenure_vulnerability": "Tenencia vulnerable",
    }

    state_vals = get_state_aggregates(coneval_data, indicator_id)
    value = state_vals.get(region_code)
    if value is not None:
        name = indicator_names.get(indicator_id, indicator_id)
        return (
            round(float(value), 2),
            "real",
            f"{name} — CONEVAL 2020, promedio municipal estatal, %",
        )
    return (0.0, "synthetic", f"Mock — CONEVAL sin datos para estado {region_code}")


# ————————————————————————————————————————————
# ENOE data loading and indicator computation
# ————————————————————————————————————————————

_ENOE_CACHE: dict[str, dict[str, float]] | None = None
_ENOE_LOADED = False


def _load_enoe_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, float]] | None:
    global _ENOE_CACHE, _ENOE_LOADED
    if _ENOE_LOADED:
        return _ENOE_CACHE
    _ENOE_LOADED = True

    if country != "MX":
        return None

    enoe_ids = {"employed_population", "female_employment", "hours_worked", "remuneration_level"}
    if not any(ind["id"] in enoe_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.enoe import parse_enoe_data
        data = parse_enoe_data()
        if not data or not data.get("employed_population"):
            logger.info("ENOE: no data available")
            return None
        _ENOE_CACHE = data
        logger.info(f"ENOE: loaded employment data for {len(data.get('employed_population', {}))} states")
        return _ENOE_CACHE
    except Exception as exc:
        logger.warning(f"ENOE: failed to load ({exc}), using mock values")
        return None


def _enoe_indicator_value(
    indicator_id: str,
    region_code: str,
    enoe_data: dict[str, dict[str, float]],
) -> tuple[float, str, str]:
    from src.services.ingestion.enoe import get_state_aggregates

    indicator_names = {
        "employed_population": "Población ocupada",
        "female_employment": "Empleo femenino",
        "hours_worked": "Horas trabajadas",
        "remuneration_level": "Remuneración promedio",
        "educated_personnel": "Personal educado",
    }
    units = {
        "employed_population": "%",
        "female_employment": "%",
        "hours_worked": "horas/semana",
        "remuneration_level": "MXN/mes",
        "educated_personnel": "%",
    }

    state_vals = get_state_aggregates(enoe_data, indicator_id)
    value = state_vals.get(region_code)
    if value is not None:
        name = indicator_names.get(indicator_id, indicator_id)
        unit = units.get(indicator_id, "")
        return (
            round(value, 2),
            "real",
            f"{name} — ENOE INEGI, estatal, {unit}",
        )

    return (0.0, "synthetic", f"Mock — ENOE sin datos para estado {region_code}")


# ————————————————————————————————————————————
# DENUE data loading and indicator computation
# ————————————————————————————————————————————

_DENUE_CACHE: dict[str, dict[str, int]] | None = None
_DENUE_LOADED = False


def _load_denue_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, int]] | None:
    global _DENUE_CACHE, _DENUE_LOADED
    if _DENUE_LOADED:
        return _DENUE_CACHE
    _DENUE_LOADED = True

    if country != "MX":
        return None

    denue_ids = {"foreign_capital_presence", "daycare_services", "innovation_economic_units"}
    if not any(ind["id"] in denue_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.denue import get_denue_counts
        data = get_denue_counts()
        if not data:
            logger.info("DENUE: no data available")
            return None
        _DENUE_CACHE = data
        states = len(data.get("foreign_capital_presence", {}))
        logger.info(f"DENUE: loaded establishment counts for {states} states")
        return _DENUE_CACHE
    except Exception as exc:
        logger.warning(f"DENUE: failed to load ({exc}), using mock values")
        return None


def _denue_indicator_value(
    indicator_id: str,
    region_code: str,
    denue_data: dict[str, dict[str, int]],
) -> tuple[float, str, str]:
    from src.services.ingestion.denue import get_state_counts

    counts = get_state_counts(denue_data, indicator_id)
    value = counts.get(region_code)

    if value is None:
        return (0.0, "synthetic", f"Mock — DENUE sin datos para estado {region_code}")

    indicator_meta = {
        "foreign_capital_presence": ("Manufactura", "establecimientos (proxy)"),
        "daycare_services": ("Guarderías", "establecimientos"),
        "innovation_economic_units": ("Innovación", "establecimientos R&D+tech"),
    }
    name, unit = indicator_meta.get(indicator_id, (indicator_id, "establecimientos"))

    return (
        float(value),
        "real",
        f"{name} — DENUE INEGI, {unit}, total estatal",
    )


# ————————————————————————————————————————————
# CONAGUA data loading and indicator computation
# ————————————————————————————————————————————

_CONAGUA_CACHE: tuple[dict[str, dict[str, float]], dict[str, bool]] | None = None
_CONAGUA_LOADED = False


def _load_conagua_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> tuple[dict[str, dict[str, float]], dict[str, bool]] | None:
    """Loads CONAGUA water indicators: real bulk-file data (conagua_eam) first
    per indicator, falling back to the hardcoded 2023-snapshot dict
    (conagua.py) only for indicators the bulk file didn't cover.

    Returns (data, is_live) — is_live[indicator_id] is True only when that
    indicator's values came from a real conagua_eam file this run, never from
    the hardcoded fallback (see conagua_eam.py's docstring for the bug this
    distinction fixes).
    """
    global _CONAGUA_CACHE, _CONAGUA_LOADED
    if _CONAGUA_LOADED:
        return _CONAGUA_CACHE
    _CONAGUA_LOADED = True

    if country != "MX":
        return None

    conagua_ids = {"water_stress", "water_consumption_intensity"}
    if not any(ind["id"] in conagua_ids for ind in catalog):
        return None

    data: dict[str, dict[str, float]] = {}
    is_live: dict[str, bool] = {}

    try:
        from src.services.ingestion.conagua_eam import parse_conagua_eam_data
        eam_data = parse_conagua_eam_data()
    except Exception as exc:
        logger.warning(f"CONAGUA EAM: failed to load ({exc}), using fallback only")
        eam_data = {}

    try:
        from src.services.ingestion.conagua import get_conagua_data
        fallback_data = get_conagua_data()
    except Exception as exc:
        logger.warning(f"CONAGUA fallback: failed to load ({exc})")
        fallback_data = {}

    for ind_id in conagua_ids:
        live_values = eam_data.get(ind_id) or {}
        if live_values:
            data[ind_id] = live_values
            is_live[ind_id] = True
        else:
            data[ind_id] = dict(fallback_data.get(ind_id, {}))
            is_live[ind_id] = False

    n_live = sum(1 for v in is_live.values() if v)
    logger.info(
        f"CONAGUA: loaded {len(data)} indicators ({n_live} from real EAM file, {len(data) - n_live} fallback)"
    )
    _CONAGUA_CACHE = (data, is_live)
    return _CONAGUA_CACHE


def _conagua_indicator_value(
    indicator_id: str,
    region_code: str,
    conagua_data: dict[str, dict[str, float]],
    conagua_is_live: dict[str, bool],
) -> tuple[float, str, str]:
    values = conagua_data.get(indicator_id, {})
    value = values.get(region_code)
    indicator_names = {
        "water_stress": "Estrés hídrico",
        "water_consumption_intensity": "Intensidad de consumo de agua",
    }
    units = {
        "water_stress": "%",
        "water_consumption_intensity": "m³/millón MXN",
    }
    name = indicator_names.get(indicator_id, indicator_id)
    unit = units.get(indicator_id, "")
    if value is not None and conagua_is_live.get(indicator_id):
        return (
            round(value, 2),
            "real",
            f"{name} — CONAGUA EAM/SINA, {unit}, estatal",
        )
    return (0.0, "synthetic", f"Mock — CONAGUA sin datos en vivo para estado {region_code}")



# ————————————————————————————————————————————
# US Census ACS data loading and indicator computation
# ————————————————————————————————————————————

_ACS_CACHE: dict[str, dict[str, float]] | None = None
_ACS_LOADED = False


def _load_acs_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, float]] | None:
    global _ACS_CACHE, _ACS_LOADED
    if _ACS_LOADED:
        return _ACS_CACHE
    _ACS_LOADED = True

    if country != "US":
        return None

    acs_ids = {"potable_water_access", "drainage_access", "internet_access",
               "overcrowding", "self_built_housing", "talent_attraction"}
    if not any(ind["id"] in acs_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.census_acs import parse_acs_data
        data = parse_acs_data()
        if not data:
            logger.info("CensusACS: no data available")
            return None
        _ACS_CACHE = data
        logger.info(f"CensusACS: loaded data for {len(data)} indicators")
        return _ACS_CACHE
    except Exception as exc:
        logger.warning(f"CensusACS: failed to load ({exc}), using mock values")
        return None


def _acs_indicator_value(
    indicator_id: str,
    region_code: str,
    acs_data: dict[str, dict[str, float]],
) -> tuple[float, str, str]:
    indicator_names = {
        "potable_water_access": "Complete plumbing",
        "drainage_access": "Sewer access",
        "internet_access": "Broadband internet",
        "overcrowding": "Overcrowding (>1.0/room)",
        "self_built_housing": "Pre-1950 housing stock",
        "talent_attraction": "Bachelor's degree+",
    }

    value = acs_data.get(indicator_id, {}).get(region_code)
    if value is not None:
        name = indicator_names.get(indicator_id, indicator_id)
        return (
            round(value, 2),
            "real",
            f"{name} — Census ACS 2022 5-year, state-level, %",
        )
    return (0.0, "synthetic", f"Mock — ACS no data for state {region_code}")


# ————————————————————————————————————————————
# FBI UCR data loading and indicator computation
# ————————————————————————————————————————————

_UCR_CACHE: dict[str, Any] | None = None
_UCR_LOADED = False


def _load_ucr_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, Any] | None:
    global _UCR_CACHE, _UCR_LOADED
    if _UCR_LOADED:
        return _UCR_CACHE
    _UCR_LOADED = True

    if country != "US":
        return None

    crime_ids = {"homicide_rate", "robbery_rate", "domestic_violence_rate"}
    if not any(ind["id"] in crime_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.fbi_ucr import parse_ucr_data
        data = parse_ucr_data()
        if not data:
            logger.info("FBI UCR: no data available, crime indicators will use mock values")
            return None
        _UCR_CACHE = {"data": data}
        logger.info(f"FBI UCR: loaded crime data for {len(data)} indicators, "
                    f"{len(data.get('homicide_rate', {}))} states")
        return _UCR_CACHE
    except Exception as exc:
        logger.warning(f"FBI UCR: failed to load ({exc}), using mock values")
        return None


def _ucr_indicator_value(
    indicator_id: str,
    region_code: str,
    ucr_data: dict[str, Any],
) -> tuple[float, str, str]:
    data = ucr_data.get("data", {})
    indicator_data = data.get(indicator_id, {})
    value = indicator_data.get(region_code)
    if value is not None:
        indicator_names = {
            "homicide_rate": "Homicides",
            "robbery_rate": "Robberies",
            "domestic_violence_rate": "Aggravated assault",
        }
        name = indicator_names.get(indicator_id, indicator_id)
        return (
            round(float(value), 2),
            "real",
            f"{name} — FBI UCR, rate per 100k, state-level",
        )
    return (0.0, "synthetic", f"Mock — FBI UCR no data for state {region_code}")


# ————————————————————————————————————————————
# BLS state employment data loading and indicator computation
# ————————————————————————————————————————————

_BLS_STATE_CACHE: dict[str, dict[str, float]] | None = None
_BLS_STATE_LOADED = False


def _load_bls_state_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, float]] | None:
    global _BLS_STATE_CACHE, _BLS_STATE_LOADED
    if _BLS_STATE_LOADED:
        return _BLS_STATE_CACHE
    _BLS_STATE_LOADED = True

    if country != "US":
        return None

    bls_ids = {"employed_population", "female_employment", "hours_worked", "remuneration_level"}
    if not any(ind["id"] in bls_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.bls_state import parse_bls_state_data
        data = parse_bls_state_data()
        if not data:
            logger.info("BLS State: no data available")
            return None
        _BLS_STATE_CACHE = data
        logger.info(f"BLS State: loaded employment data for {len(data.get('employed_population', {}))} states")
        return _BLS_STATE_CACHE
    except Exception as exc:
        logger.warning(f"BLS State: failed to load ({exc}), using mock values")
        return None


def _bls_state_indicator_value(
    indicator_id: str,
    region_code: str,
    bls_state_data: dict[str, dict[str, float]],
) -> tuple[float, str, str]:
    indicator_names = {
        "employed_population": "Employment rate",
        "female_employment": "Labor force participation",
        "hours_worked": "Avg weekly hours (mfg)",
        "remuneration_level": "Avg hourly earnings (mfg)",
    }
    units = {
        "employed_population": "%",
        "female_employment": "%",
        "hours_worked": "hours/week",
        "remuneration_level": "USD/hr",
    }

    value = bls_state_data.get(indicator_id, {}).get(region_code)
    if value is not None:
        name = indicator_names.get(indicator_id, indicator_id)
        unit = units.get(indicator_id, "")
        return (
            round(value, 2),
            "real",
            f"{name} — BLS LAUS/CES, state-level, {unit}",
        )
    return (0.0, "synthetic", f"Mock — BLS no data for state {region_code}")


# ————————————————————————————————————————————
# Census CBP data loading and indicator computation
# ————————————————————————————————————————————

_CBP_CACHE: dict[str, dict[str, int]] | None = None
_CBP_LOADED = False


def _load_cbp_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, int]] | None:
    global _CBP_CACHE, _CBP_LOADED
    if _CBP_LOADED:
        return _CBP_CACHE
    _CBP_LOADED = True

    if country != "US":
        return None

    cbp_ids = {"foreign_capital_presence", "daycare_services", "innovation_economic_units"}
    if not any(ind["id"] in cbp_ids for ind in catalog):
        return None

    try:
        from src.services.ingestion.census_cbp import get_cbp_counts
        data = get_cbp_counts()
        if not data:
            logger.info("CensusCBP: no data available")
            return None
        _CBP_CACHE = data
        states = len(data.get("foreign_capital_presence", {}))
        logger.info(f"CensusCBP: loaded establishment counts for {states} states")
        return _CBP_CACHE
    except Exception as exc:
        logger.warning(f"CensusCBP: failed to load ({exc}), using mock values")
        return None


def _cbp_indicator_value(
    indicator_id: str,
    region_code: str,
    cbp_data: dict[str, dict[str, int]],
) -> tuple[float, str, str]:
    counts = cbp_data.get(indicator_id, {})
    value = counts.get(region_code)

    if value is None:
        return (0.0, "synthetic", f"Mock — CBP no data for state {region_code}")

    indicator_meta = {
        "foreign_capital_presence": ("Manufacturing", "establishments (NAICS 31-33)"),
        "daycare_services": ("Child day care", "establishments (NAICS 624410)"),
        "innovation_economic_units": ("R&D + CSD", "establishments (NAICS 5417+5415)"),
    }
    name, unit = indicator_meta.get(indicator_id, (indicator_id, "establishments"))

    return (
        float(value),
        "real",
        f"{name} — Census CBP 2022, {unit}, total state",
    )


# ————————————————————————————————————————————
# Census SAIPE data loading and indicator computation
# ————————————————————————————————————————————

_SAIPE_CACHE: dict[str, dict[str, float]] | None = None
_SAIPE_LOADED = False


def _load_saipe_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> dict[str, dict[str, float]] | None:
    global _SAIPE_CACHE, _SAIPE_LOADED
    if _SAIPE_LOADED:
        return _SAIPE_CACHE
    _SAIPE_LOADED = True

    if country != "US":
        return None

    if not any(ind["id"] == "extreme_poverty" for ind in catalog):
        return None

    try:
        from src.services.ingestion.census_saipe import parse_saipe_data
        data = parse_saipe_data()
        if not data:
            logger.info("CensusSAIPE: no data available")
            return None
        _SAIPE_CACHE = data
        logger.info(f"CensusSAIPE: loaded poverty data for {len(data.get('extreme_poverty', {}))} states")
        return _SAIPE_CACHE
    except Exception as exc:
        logger.warning(f"CensusSAIPE: failed to load ({exc}), using mock values")
        return None


def _saipe_indicator_value(
    indicator_id: str,
    region_code: str,
    saipe_data: dict[str, dict[str, float]],
) -> tuple[float, str, str]:
    value = saipe_data.get(indicator_id, {}).get(region_code)
    if value is not None:
        return (
            round(value, 2),
            "real",
            f"Poverty rate — Census SAIPE 2022, state-level, %",
        )
    return (0.0, "synthetic", f"Mock — SAIPE no data for state {region_code}")


# ————————————————————————————————————————————
# Statistics Canada data loading and indicator computation
# ————————————————————————————————————————————

_STATCAN_CACHE: tuple[dict[str, dict[str, float]], dict[str, bool]] | None = None
_STATCAN_LOADED = False


def _load_statcan_if_needed(
    catalog: list[dict[str, Any]], country: str
) -> tuple[dict[str, dict[str, float]], dict[str, bool]] | None:
    global _STATCAN_CACHE, _STATCAN_LOADED
    if _STATCAN_LOADED:
        return _STATCAN_CACHE
    _STATCAN_LOADED = True

    if country != "CA":
        return None

    try:
        from src.services.ingestion.statcan_territorial import parse_statcan_territorial_data
        data, is_live = parse_statcan_territorial_data()
        if not data:
            logger.info("StatCan Territorial: no data available")
            return None
        _STATCAN_CACHE = (data, is_live)
        n_live = sum(1 for v in is_live.values() if v)
        logger.info(
            f"StatCan Territorial: loaded data for {len(data)} indicators ({n_live} live, {len(data) - n_live} fallback)"
        )
        return _STATCAN_CACHE
    except Exception as exc:
        logger.warning(f"StatCan Territorial: failed to load ({exc}), using mock values")
        return None


def _statcan_indicator_value(
    indicator_id: str,
    region_code: str,
    statcan_data: dict[str, dict[str, float]],
    statcan_is_live: dict[str, bool],
) -> tuple[float, str, str]:
    indicator_names = {
        "potable_water_access": "Acceptable housing",
        "drainage_access": "Acceptable housing",
        "overcrowding": "Suitable housing",
        "self_built_housing": "Major repairs needed",
        "talent_attraction": "Bachelor's degree+",
        "educated_personnel": "Postsecondary cert/diploma",
        "land_tenure_vulnerability": "Renter occupied",
        "homicide_rate": "Crime severity",
        "robbery_rate": "Crime severity",
        "domestic_violence_rate": "Crime severity",
        "extreme_poverty": "Low income (LIM)",
        "employed_population": "Employment rate",
        "female_employment": "Employment rate",
        "hours_worked": "Avg weekly hours",
        "remuneration_level": "Avg hourly wage",
        "foreign_capital_presence": "Foreign enterprises",
        "innovation_economic_units": "Patent applications",
        "daycare_services": "Daycare centres",
        "water_stress": "Water use",
        "water_consumption_intensity": "Water use",
        "internet_access": "Internet access",
        "public_transport_usage": "Public transit",
        "avg_commute_time": "Avg commute time",
    }
    units = {
        "hours_worked": "hours/week",
        "remuneration_level": "CAD/hr",
    }

    value = statcan_data.get(indicator_id, {}).get(region_code)
    if value is not None and value > 0 and statcan_is_live.get(indicator_id):
        name = indicator_names.get(indicator_id, indicator_id)
        unit = units.get(indicator_id, "%")
        return (
            round(float(value), 2),
            "real",
            f"{name} — Statistics Canada, province-level, {unit}",
        )
    return (0.0, "synthetic", f"Mock — StatCan no live data for province {region_code}")
