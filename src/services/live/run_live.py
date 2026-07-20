"""Live pipeline orchestrator.

Generates mock data first for complete coverage (all 31 pairs), then overrides
specific pairs with real data from INEGI, FRED, BLS and Statistics Canada APIs.
On API failure, the mock data is kept — a single unavailable source degrades one
pair, not the entire pipeline run.

The override strategy is identical to the Dashboard's
`pipeline/live/run_live_pilot.py` (13 of 21 MX-US pairs verified real, plus
MX-CA pairs from Statistics Canada WDS).

Usage:
    from src.services.live.run_live import run_live_pipeline
    result = run_live_pipeline()
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from src.config import DATA_DIR, MANIFEST_PATH, RESULTS_DIR, SERIES_DIR

logger = logging.getLogger(__name__)

# ——————————————————————————————————————————————
# National pair override: MX INEGI IMAI vs US FRED IP
# ——————————————————————————————————————————————

_IMAI_MAP = {
    "eolica": "736491",
    "farmaceutica": "736462",
    "aeroespacial": "736515",
    "agroindustrial": "736427",
    "petroquimica": "736459",
    "manufactura_total": "736407",
}

_FRED_MAP = {
    "eolica": "IPG333N",
    "farmaceutica": "IPG3254N",
    "aeroespacial": "IPG3364N",
    "agroindustrial": "IPN3118N",
    "petroquimica": "IPG3251N",
    "manufactura_total": "INDPRO",
}

# Known approximations (documented in the Dashboard's live pilot):
_APPROXIMATIONS: dict[str, str] = {
    "eolica": (
        "SCIAN/NAICS 333611 (turbinas eólicas) no está desagregado en el "
        "catálogo IMAI ni en FRED; se usa el subsector 333 completo "
        "('Fabricación de maquinaria y equipo') en ambos lados."
    ),
    "agroindustrial": (
        "Proxy ya declarado en scian_naics_crosswalk.csv (cacao/vainilla vía "
        "panadería y tortillas); no existe indicador SCIAN 311800 exacto en IMAI."
    ),
    "petroquimica": (
        "sectors.yaml declara 2 códigos SCIAN para petroquímica (324110 "
        "refinación + 325100 química básica); se usa solo 325100/3251 para una "
        "correspondencia 1:1 clara con FRED (IPG3251N)."
    ),
}

_ITAEE_MANUFACTURING_ID = "741651"
_ITAEE_TOTAL_ID = "741177"

# ——————————————————————————————————————————————
# State pairs: INEGI ITAEE vs BLS CES
# ——————————————————————————————————————————————

_BLS_SECTOR_CODE: dict[str, str] = {
    "aeroespacial": "31336400",
    "farmaceutica": "32325400",
    "manufactura_total": "30000000",
}

# States where INEGI ITAEE 741651 returns ErrorCode:100 (no data for these):
_KNOWN_MISSING_ITAEE = {"04", "05", "07", "19", "28", "30"}

_ITAEE_FALLBACK_NOTE = (
    "ITAEE específico de este sector no existe en el catálogo estatal público de "
    "INEGI (la granularidad máxima es manufactura 31-33 total); se usa 741651 "
    "(ITAEE manufactura total) como mejor proxy disponible del lado MX."
)

BLS_START_YEAR = "2006"
BLS_END_YEAR = "2026"


def _fetch_national_pair(
    sector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Fetch a national MX-US pair from INEGI IMAI + FRED IP.

    Returns (frames_dict, labels_dict) on success, or None if any API fails.
    The frames dict keys match the mock series IDs exactly so they can
    replace the mock entries in series_lookup.
    """
    from src.services.ingestion import inegi, fred
    from src.services.processing.normalize import SeriesMeta, normalize_series

    sector_id = sector["id"]
    mx_indicator = _IMAI_MAP.get(sector_id)
    if mx_indicator is None and sector_id != "manufactura_total":
        return None

    # Always use manufactura_total as fallback for unknown sectors
    if mx_indicator is None:
        mx_indicator = _IMAI_MAP["manufactura_total"]

    us_series = _FRED_MAP.get(sector_id, _FRED_MAP["manufactura_total"])

    scian_code = sector["scian_codes"][0] if sector.get("scian_codes") else None
    naics_code = sector["naics_codes"][0] if sector.get("naics_codes") else None

    try:
        mx_raw = inegi.fetch_indicator(mx_indicator, area_code=inegi.NATIONAL_AREA_CODE)
    except Exception as exc:
        logger.info("INEGI IMAI %s: %s — skipping national pair %s", mx_indicator, exc, sector_id)
        return None

    mx_series_id = f"mx-nac_{sector_id}_emim"
    mx_pairs = [(o["TIME_PERIOD"].replace("/", "-") + "-01", o["OBS_VALUE"]) for o in mx_raw]

    approx = _APPROXIMATIONS.get(sector_id)
    mx_source = f"INEGI - IMAI (clave {mx_indicator})"
    if approx:
        mx_source += f" [APROXIMACIÓN: {approx}]"

    mx_meta = SeriesMeta(
        series_id=mx_series_id,
        source=mx_source,
        country="MX",
        region_code="NAC",
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units="Índice base 2018=100",
        proxy_type="output_index",
        publication_lag_days=45,
        vintage_date=max(o["TIME_PERIOD"] for o in mx_raw).replace("/", "-") + "-01",
        scian_code=scian_code,
        naics_code=naics_code,
    )
    mx_tidy = normalize_series(mx_pairs, mx_meta)

    try:
        us_raw = fred.fetch_series(series_id=us_series)
    except Exception as exc:
        logger.info("FRED %s: %s — skipping national pair %s", us_series, exc, sector_id)
        return None

    us_series_id = f"us-nac_{sector_id}_ip"
    us_pairs = [(o["date"], o["value"]) for o in us_raw if o.get("value") not in (".", "NaN", None)]

    us_meta = SeriesMeta(
        series_id=us_series_id,
        source=f"FRED - {us_series} (Industrial Production)",
        country="US",
        region_code="NAC",
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units="Index 2017=100",
        proxy_type="output_index",
        publication_lag_days=15,
        vintage_date=max(o["date"] for o in us_raw),
        scian_code=scian_code,
        naics_code=naics_code,
    )
    us_tidy = normalize_series(us_pairs, us_meta)

    label_en = sector.get("label_en", sector["label"])
    proxy_suffix = " [proxy]" if approx else ""
    labels = {
        mx_series_id: f"Producción manufacturera - {sector['label']} (México, nacional, INEGI real{proxy_suffix})",
        us_series_id: f"Industrial Production Index - {label_en} (US, national, FRED real)",
    }
    return {mx_series_id: mx_tidy, us_series_id: us_tidy}, labels


def _fetch_state_pair(
    sector: dict[str, Any],
    *,
    mx_area_code: str,
    mx_abbr: str,
    mx_state_label: str,
    us_region_code: str,
    us_abbr: str,
    us_state_label: str,
    us_disambiguator: str | None = None,
    itaee_fallback: bool = False,
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Fetch a state pair: INEGI ITAEE vs BLS CES.

    When itaee_fallback=True, uses ITAEE manufacturing total (741651) as
    proxy for sectors that don't have sector-specific ITAEE at state level.
    """
    from src.services.ingestion import bls, inegi
    from src.services.processing.normalize import SeriesMeta, normalize_series

    sector_id = sector["id"]

    # Determine INEGI indicator for state data
    if sector_id == "manufactura_total" or itaee_fallback:
        mx_indicator = _ITAEE_TOTAL_ID if sector_id == "manufactura_total" else _ITAEE_MANUFACTURING_ID
    else:
        mx_indicator = _ITAEE_MANUFACTURING_ID

    # Known missing states: fall back to total ITAEE
    if mx_area_code in _KNOWN_MISSING_ITAEE and mx_indicator == _ITAEE_MANUFACTURING_ID:
        mx_indicator = _ITAEE_TOTAL_ID

    # Build BLS series ID
    bls_industry = _BLS_SECTOR_CODE.get(sector_id, _BLS_SECTOR_CODE["manufactura_total"])
    bls_series_id = f"SMU{us_region_code}00000{bls_industry}01"

    scian_code = sector["scian_codes"][0] if sector.get("scian_codes") else None
    naics_code = sector["naics_codes"][0] if sector.get("naics_codes") else None

    try:
        mx_raw = inegi.fetch_itaee(mx_area_code, indicator_id=mx_indicator)
    except Exception as exc:
        logger.info("INEGI ITAEE %s (state %s): %s — skipping", mx_indicator, mx_area_code, exc)
        return None

    mx_abbr_lower = mx_abbr.lower()
    us_abbr_lower = us_abbr.lower()
    mx_series_id = f"mx-{mx_abbr_lower}_{sector_id}_itaee"
    if us_disambiguator:
        us_series_id = f"us-{us_abbr_lower}_{sector_id}_{us_disambiguator.lower()}_bls"
    else:
        us_series_id = f"us-{us_abbr_lower}_{sector_id}_bls"

    mx_pairs = []
    for o in mx_raw:
        year, q = o["TIME_PERIOD"].split("/")
        month = int(q) * 3
        mx_pairs.append((f"{year}-{month:02d}-01", o["OBS_VALUE"]))

    mx_source = f"INEGI - ITAEE (clave {mx_indicator})"
    if itaee_fallback and sector_id != "manufactura_total":
        mx_source += f" [APROXIMACIÓN: {_ITAEE_FALLBACK_NOTE}]"

    mx_meta = SeriesMeta(
        series_id=mx_series_id,
        source=mx_source,
        country="MX",
        region_code=mx_area_code,
        sector_id=sector_id,
        frequency="quarterly",
        seasonal_adjustment="nsa",
        units="Índice base 2018=100",
        proxy_type="output_index",
        publication_lag_days=95,
        vintage_date=max(p[0] for p in mx_pairs) if mx_pairs else "unknown",
        scian_code=scian_code,
        naics_code=naics_code,
    )
    mx_tidy = normalize_series(mx_pairs, mx_meta)

    try:
        us_raw = bls.fetch_timeseries([bls_series_id], start_year=BLS_START_YEAR, end_year=BLS_END_YEAR)
    except Exception as exc:
        logger.info("BLS %s: %s — skipping state pair", bls_series_id, exc)
        return None

    us_pairs = []
    for series_data in us_raw:
        for obs in series_data.get("data", []):
            if not obs.get("period") or obs["period"].startswith("M") is False or obs["period"] == "M13":
                continue
            month = int(obs["period"][1:])
            year = obs.get("year", "")
            value = obs.get("value", "")
            if year and month and value:
                us_pairs.append((f"{year}-{month:02d}-01", value))

    us_meta = SeriesMeta(
        series_id=us_series_id,
        source=f"BLS - CES {bls_series_id} ({us_state_label})",
        country="US",
        region_code=us_region_code,
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units="Miles de empleos",
        proxy_type="labor_input",
        publication_lag_days=21,
        vintage_date=max(p[0] for p in us_pairs) if us_pairs else "unknown",
        scian_code=scian_code,
        naics_code=naics_code,
    )
    us_tidy = normalize_series(us_pairs, us_meta)

    label_en = sector.get("label_en", sector["label"])
    proxy_suffix = " [proxy: ITAEE manufactura total]" if (itaee_fallback and sector_id != "manufactura_total") else ""
    labels = {
        mx_series_id: f"ITAEE - Actividad industrial ({mx_state_label}, INEGI real{proxy_suffix})",
        us_series_id: f"Empleo manufacturero - {label_en} ({us_state_label}, BLS real)",
    }
    return {mx_series_id: mx_tidy, us_series_id: us_tidy}, labels


def _fetch_canada_national_pair(
    sector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Fetch a national MX-CA pair: MX IMAI (mock baseline) + Statistics Canada GDP."""
    # Canada national data via StatCan; MX side keeps mock since it's already
    # covered by the Mexico national pairs above (series_lookup already has it).
    # We only need to add the Canada national series with real data.
    from src.services.ingestion.statcan import fetch_cube_coord_data
    from src.services.processing.normalize import SeriesMeta, normalize_series

    sector_id = sector["id"]
    scian_code = sector["scian_codes"][0] if sector.get("scian_codes") else None
    naics_code = sector["naics_codes"][0] if sector.get("naics_codes") else None

    ca_series_id = f"ca-nac_{sector_id}_sc"

    try:
        raw = fetch_cube_coord_data(36100434, "1.1.1.1.0.0.0.0.0.0", latest_n=60)
    except Exception as exc:
        logger.info("StatCan national GDP: %s — skipping CA national pair %s", exc, sector_id)
        return None

    ca_pairs = [(o["refPer"], o["value"]) for o in raw if o.get("value") is not None]
    if not ca_pairs:
        logger.info("StatCan national GDP: empty response — skipping CA national pair %s", sector_id)
        return None

    ca_meta = SeriesMeta(
        series_id=ca_series_id,
        source="Statistics Canada — Monthly GDP (real)",
        country="CA",
        region_code="NAC",
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units="Chained (2017) dollars",
        proxy_type="output_index",
        publication_lag_days=60,
        vintage_date=max(p[0] for p in ca_pairs),
        scian_code=scian_code,
        naics_code=naics_code,
    )
    ca_tidy = normalize_series(ca_pairs, ca_meta)

    label_en = sector.get("label_en", sector["label"])
    labels = {
        ca_series_id: f"GDP by industry — {label_en} (Canada, national, StatCan real)",
    }
    return {ca_series_id: ca_tidy}, labels


def _fetch_canada_state_pair(
    sector: dict[str, Any],
    *,
    mx_area_code: str,
    mx_abbr: str,
    mx_state_label: str,
    ca_region_code: str,
    ca_abbr: str,
    ca_state_label: str,
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Fetch a MX-CA state pair: MX ITAEE (mock or real) + StatCan manufacturing sales."""
    from src.services.ingestion.statcan import fetch_cube_coord_data
    from src.services.processing.normalize import SeriesMeta, normalize_series

    sector_id = sector["id"]
    scian_code = sector["scian_codes"][0] if sector.get("scian_codes") else None
    naics_code = sector["naics_codes"][0] if sector.get("naics_codes") else None

    mx_abbr_lower = mx_abbr.lower()
    ca_abbr_lower = ca_abbr.lower()
    ca_series_id = f"ca-{ca_abbr_lower}_{sector_id}_sc"

    # Determine province index for StatCan coordinate
    _ca_province_index = {
        "10": 1, "11": 2, "12": 3, "13": 4,
        "24": 5, "35": 6, "46": 7, "47": 8,
        "48": 9, "59": 10, "60": 11, "61": 12, "62": 13,
    }
    geo_idx = _ca_province_index.get(ca_region_code, 1)
    coordinate = f"1.{geo_idx}.1.1.0.0.0.0.0.0"

    try:
        raw = fetch_cube_coord_data(16100048, coordinate, latest_n=60)
    except Exception as exc:
        logger.info("StatCan manufacturing sales %s: %s — skipping", ca_state_label, exc)
        return None

    ca_pairs = [(o["refPer"], o["value"]) for o in raw if o.get("value") is not None]
    if not ca_pairs:
        logger.info("StatCan manufacturing sales %s: empty response — skipping", ca_state_label)
        return None

    ca_meta = SeriesMeta(
        series_id=ca_series_id,
        source=f"Statistics Canada — Manufacturing sales ({ca_state_label}, real)",
        country="CA",
        region_code=ca_region_code,
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units="Thousands of dollars",
        proxy_type="output_index",
        publication_lag_days=60,
        vintage_date=max(p[0] for p in ca_pairs),
        scian_code=scian_code,
        naics_code=naics_code,
    )
    ca_tidy = normalize_series(ca_pairs, ca_meta)

    label_en = sector.get("label_en", sector["label"])
    labels = {
        ca_series_id: f"Manufacturing sales — {label_en} ({ca_state_label}, StatCan real)",
    }
    return {ca_series_id: ca_tidy}, labels


# ——————————————————————————————————————————————
# Main orchestrator
# ——————————————————————————————————————————————


def run_live_pipeline() -> dict[str, Any]:
    """Run the live pipeline: mock baseline + real data overrides + econometrics + export.

    Returns the manifest dict (same shape as mock pipeline), with mode set to
    'live', 'mixed', or 'mock' depending on how many overrides succeeded.
    """
    from src.services.mock.generate_mock_data import (
        ADDITIONAL_STATE_PAIRS,
        MX_CA_NATIONAL_PAIRS,
        MX_CA_STATE_PAIRS,
        _load_sectors,
        _monthly_periods,
        _national_pair_frames,
        _national_pair_frames_ca,
        _quarterly_periods,
        _state_pair_frames,
        _state_pair_frames_ca,
    )
    from src.services.econometrics.pipeline_runner import run_all
    from src.services.export.to_json import export_all

    logger.info("=== Live pipeline: starting ===")

    sectors = _load_sectors()
    sectors_by_id = {s["id"]: s for s in sectors}
    monthly_dates = _monthly_periods()
    quarterly_dates = _quarterly_periods()

    series_lookup: dict[str, Any] = {}
    series_labels: dict[str, str] = {}
    pair_defs: list[dict[str, Any]] = []

    # ——— Step 1: Generate all mock data first (complete baseline) ———
    logger.info("Step 1/4: generating mock baseline (%d sectors)...", len(sectors))

    for idx, sector in enumerate(sectors):
        frames, labels, pair_def = _national_pair_frames(idx, sector, monthly_dates)
        series_lookup.update(frames)
        series_labels.update(labels)
        pair_defs.append(pair_def)

        if sector["id"] == "aeroespacial":
            state_frames, state_labels, state_pair_def = _state_pair_frames(
                idx + len(sectors), sector, quarterly_dates, monthly_dates
            )
            series_lookup.update(state_frames)
            series_labels.update(state_labels)
            pair_defs.append(state_pair_def)

    for spec in ADDITIONAL_STATE_PAIRS:
        sector = sectors_by_id[spec["sector_id"]]
        mx, us = spec["mx"], spec["us"]
        state_frames, state_labels, state_pair_def = _state_pair_frames(
            spec["rng_index"], sector, quarterly_dates, monthly_dates,
            mx_region_code=mx["code"], mx_abbr=mx["abbr"], mx_state_label=mx["label"],
            us_region_code=us["code"], us_abbr=us["abbr"], us_state_label=us["label"],
            us_series_disambiguator=mx["abbr"],
        )
        series_lookup.update(state_frames)
        series_labels.update(state_labels)
        pair_defs.append(state_pair_def)

    for spec in MX_CA_NATIONAL_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        frames, labels, pair_def = _national_pair_frames_ca(spec["rng_index"], sector, monthly_dates)
        series_lookup.update(frames)
        series_labels.update(labels)
        pair_defs.append(pair_def)

    for spec in MX_CA_STATE_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        mx, ca = spec["mx"], spec["ca"]
        state_frames, state_labels, state_pair_def = _state_pair_frames_ca(
            spec["rng_index"], sector, quarterly_dates, monthly_dates,
            mx_region_code=mx["code"], mx_abbr=mx["abbr"], mx_state_label=mx["label"],
            ca_region_code=ca["code"], ca_abbr=ca["abbr"], ca_state_label=ca["label"],
        )
        series_lookup.update(state_frames)
        series_labels.update(state_labels)
        pair_defs.append(state_pair_def)

    logger.info("Mock baseline: %d series, %d pairs", len(series_lookup), len(pair_defs))

    # ——— Step 2: Override MX-US national pairs with real data ———
    logger.info("Step 2/4: overriding national MX-US pairs with real data...")
    override_status: list[tuple[str, str, str]] = []

    for sector in sectors:
        sector_id = sector["id"]
        result = _fetch_national_pair(sector)
        if result is not None:
            frames, labels = result
            series_lookup.update(frames)
            series_labels.update(labels)
            override_status.append((f"mx-nac_{sector_id}__us-nac_{sector_id}", "real", ""))
            logger.info("  %s: real ✓", sector_id)
        else:
            override_status.append((f"mx-nac_{sector_id}__us-nac_{sector_id}", "mock", "API unavailable"))
            logger.info("  %s: mock (API unavailable)", sector_id)

    # ——— Step 3: Override MX-US state pairs with real data ———
    logger.info("Step 3/4: overriding state MX-US pairs with real data...")

    # All state pairs: aeroespacial (Chihuahua-Texas from step 1) + ADDITIONAL_STATE_PAIRS
    _override_state_pairs: list[dict[str, Any]] = [
        {
            "sector_id": "aeroespacial",
            "mx_code": "08", "mx_abbr": "CHH", "mx_label": "Chihuahua",
            "us_code": "48", "us_abbr": "TX", "us_label": "Texas",
            "us_disambiguator": None,
            "itaee_fallback": True,
        },
    ] + [
        {
            "sector_id": s["sector_id"],
            "mx_code": s["mx"]["code"], "mx_abbr": s["mx"]["abbr"], "mx_label": s["mx"]["label"],
            "us_code": s["us"]["code"], "us_abbr": s["us"]["abbr"], "us_label": s["us"]["label"],
            "us_disambiguator": s["mx"]["abbr"],
            "itaee_fallback": s["sector_id"] != "manufactura_total",
        }
        for s in ADDITIONAL_STATE_PAIRS
    ]

    for sp in _override_state_pairs:
        pair_label = f"mx-{sp['mx_abbr'].lower()}_{sp['sector_id']}__us-{sp['us_abbr'].lower()}_{sp['sector_id']}"
        sector = sectors_by_id[sp["sector_id"]]

        # Skip states known to fail with INEGI ITAEE
        if sp["itaee_fallback"] and sp["mx_code"] in _KNOWN_MISSING_ITAEE:
            override_status.append((pair_label, "mock", "INEGI no data for this state"))
            logger.info("  %s: mock (INEGI no data for state %s)", pair_label, sp["mx_code"])
            continue

        result = _fetch_state_pair(
            sector,
            mx_area_code=sp["mx_code"], mx_abbr=sp["mx_abbr"], mx_state_label=sp["mx_label"],
            us_region_code=sp["us_code"], us_abbr=sp["us_abbr"], us_state_label=sp["us_label"],
            us_disambiguator=sp.get("us_disambiguator"),
            itaee_fallback=sp.get("itaee_fallback", False),
        )
        if result is not None:
            frames, labels = result
            series_lookup.update(frames)
            series_labels.update(labels)
            override_status.append((pair_label, "real", ""))
            logger.info("  %s: real ✓", pair_label)
        else:
            override_status.append((pair_label, "mock", "API unavailable"))
            logger.info("  %s: mock (API unavailable)", pair_label)

    # ——— Step 4: Override Canada pairs with real data ———
    logger.info("Step 4/4: overriding Canada pairs with real data...")

    for spec in MX_CA_NATIONAL_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        pair_label = f"mx-nac_{spec['sector_id']}__ca-nac_{spec['sector_id']}"
        result = _fetch_canada_national_pair(sector)
        if result is not None:
            frames, labels = result
            series_lookup.update(frames)
            series_labels.update(labels)
            override_status.append((pair_label, "real", ""))
            logger.info("  %s: real ✓", pair_label)
        else:
            override_status.append((pair_label, "mock", "API unavailable"))
            logger.info("  %s: mock (StatCan unavailable)", pair_label)

    for spec in MX_CA_STATE_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        mx, ca = spec["mx"], spec["ca"]
        pair_label = f"mx-{mx['abbr'].lower()}_{spec['sector_id']}__ca-{ca['abbr'].lower()}_{spec['sector_id']}"
        result = _fetch_canada_state_pair(
            sector,
            mx_area_code=mx["code"], mx_abbr=mx["abbr"], mx_state_label=mx["label"],
            ca_region_code=ca["code"], ca_abbr=ca["abbr"], ca_state_label=ca["label"],
        )
        if result is not None:
            frames, labels = result
            series_lookup.update(frames)
            series_labels.update(labels)
            override_status.append((pair_label, "real", ""))
            logger.info("  %s: real ✓", pair_label)
        else:
            override_status.append((pair_label, "mock", "API unavailable"))
            logger.info("  %s: mock (StatCan unavailable)", pair_label)

    # ————————————————————————————————————————————
    # Determine run mode
    # ————————————————————————————————————————————
    n_real = sum(1 for _, status, _ in override_status if status == "real")
    n_total = len(override_status)
    if n_real == 0:
        mode = "mock"
    elif n_real == n_total:
        mode = "live"
    else:
        mode = "mixed"

    logger.info("Override summary: %d/%d pairs with real data → mode=%s", n_real, n_total, mode)
    for label, status, reason in override_status:
        if reason:
            logger.info("  %-70s %s (%s)", label, status, reason)
        else:
            logger.info("  %-70s %s", label, status)

    # ————————————————————————————————————————————
    # Run econometrics + export
    # ————————————————————————————————————————————
    logger.info("Running econometrics engine on %d pairs (mode=%s)...", len(pair_defs), mode)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = run_all(pair_defs, series_lookup, sectors_by_id)

def _export_territorial() -> None:
    """Export territorial indicators as static JSON for the Dashboard."""
    import json

    from src.config import DATA_DIR
    from src.services.territorial import compute_indicator_values, load_indicators

    logger.info("Exporting territorial indicators...")
    try:
        catalog = load_indicators()
        region_codes = [f"{i:02d}" for i in range(1, 33)]
        values = compute_indicator_values("MX", region_codes=region_codes)

        territorial = {
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "country": "MX",
            "total_indicators": len(catalog),
            "total_regions": len(region_codes),
            "data_quality": "mixed",
            "by_region": [],
            "raw_values": values,
        }

        # Build by_region matrix
        by_region_map: dict[str, dict[str, object]] = {}
        for v in values:
            rc = v["region_code"]
            if rc not in by_region_map:
                by_region_map[rc] = {
                    "region_code": rc,
                    "region_name": v["region_name"],
                }
            by_region_map[rc][v["indicator_id"]] = v["value"]
        territorial["by_region"] = list(by_region_map.values())

        path = DATA_DIR / "territorial.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(territorial, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Territorial indicators exported to {path}")
    except Exception as exc:
        logger.warning(f"Failed to export territorial indicators: {exc}")

    logger.info(
        "=== Live pipeline complete: %d sectors, %d series, %d pairs, mode=%s ===",
        len(sectors), len(series_lookup), len(pair_defs), mode,
    )
    return manifest
