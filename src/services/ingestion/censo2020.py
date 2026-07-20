"""INEGI Censo de Población y Vivienda 2020 — ITER (Principales resultados por localidad).

Parses the ITER CSV (municipal-level summary) and extracts indicators for:
  - potable_water_access (26): % viviendas con agua entubada
  - drainage_access (27): % viviendas con drenaje
  - internet_access (28): % viviendas con internet
  - overcrowding (25): % viviendas con hacinamiento (proxy: promedio ocupantes/cuarto)
  - land_tenure_vulnerability (23): % viviendas en tenencia irregular
  - self_built_housing (24): % viviendas con piso de tierra (proxy de autoconstrucción)

Data source: INEGI ITER 2020 CSV
Download from: https://www.inegi.org.mx/programas/ccpv/2020/#microdatos
Place in: Engine/data/censo2020/

Auto-discovers CSV files in the cache directory.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

SOURCE_NAME = "Censo2020"
CACHE_DIR = DATA_DIR / "censo2020"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Stable INEGI URL for ITER 2020 national CSV (ZIP)
ITER_URL = (
    "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/"
    "datosabiertos/iter/iter_00_cpv2020_csv.zip"
)
ITER_CSV_NAME = "conjunto_de_datos_iter_00CSV20.csv"

# Column candidates (ITER 2020 uses uppercase names)
_COL_CANDIDATES = {
    "entidad": ["ENTIDAD", "NOM_ENT", "entidad", "CVE_ENT"],
    "mun": ["MUN", "NOM_MUN", "municipio", "CVE_MUN"],
    "loc": ["LOC", "NOM_LOC", "localidad"],
    "pobtot": ["POBTOT", "POB_TOTAL", "Poblacion_Total"],
    "vivtot": ["VIVTOT", "TVIVHAB", "VIV_TOTAL", "Total_Viviendas"],
    "vivhab": ["TVIVHAB", "VIVHAB", "TVIVPARHAB", "VIV_HAB"],
    # Water: dwellings with piped water inside
    "agua": ["VPH_AGUADV", "VPH_AGUA", "VIV_AGUA_ENTUBADA"],
    # Drainage: dwellings connected to public sewer or septic tank
    "drenaje": ["VPH_DRENAJ", "VPH_DREN", "VIV_DRENAJE"],
    # Internet
    "internet": ["VPH_INTER", "VPH_INT", "VIV_INTERNET", "VPH_TELEF", "VPH_INTERNET"],
    # Dirt floor (proxy for self-built/informal housing)
    "piso_tierra": ["VPH_PISOTI", "VPH_PISODT", "VPH_PISOT", "VIV_PISO_TIERRA"],
    # Dwellings with 1 room (overcrowding proxy)
    "cuartos_1": ["VPH_1CUART", "VIV_1CUART"],
    "cuartos_2ymas": ["VPH_2CUART", "VIV_2CUART"],
    "ocupantes": ["PROM_OCUP", "PROM_OCCUP", "OCUPANTES_PROM"],
    "vivpart": ["VIVPAR_HAB", "TVIVPARHAB"],
    # All basic services (water + drainage + electricity)
    "servicios": ["VPH_C_SERV", "VPH_SERV", "VIV_SERV_BAS"],
}

# Maps indicator IDs to ITER columns and calculation logic
INDICATOR_MAP = {
    "potable_water_access": {
        "numerator": "agua",
        "denominator": "vivhab",
        "description": "% viviendas con agua entubada dentro de la vivienda",
        "unit": "%",
    },
    "drainage_access": {
        "numerator": "drenaje",
        "denominator": "vivhab",
        "description": "% viviendas con drenaje conectado a red pública o fosa séptica",
        "unit": "%",
    },
    "internet_access": {
        "numerator": "internet",
        "denominator": "vivhab",
        "description": "% viviendas con acceso a internet",
        "unit": "%",
    },
    "overcrowding": {
        "numerator": "cuartos_1",
        "denominator": "vivhab",
        "description": "% viviendas con un solo cuarto (proxy de hacinamiento)",
        "unit": "%",
    },
    "self_built_housing": {
        "numerator": "piso_tierra",
        "denominator": "vivhab",
        "description": "% viviendas con piso de tierra (proxy de autoconstrucción)",
        "unit": "%",
    },
}


def _find_csv_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    files = sorted(
        [f for f in directory.iterdir() if f.suffix.lower() == ".csv"],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return files


def _download_iter(dest_dir: Path) -> Path | None:
    """Download and extract ITER 2020 ZIP from INEGI."""
    import tempfile
    import zipfile
    import urllib.request

    logger.info(f"{SOURCE_NAME}: downloading ITER from {ITER_URL} ...")
    try:
        with urllib.request.urlopen(ITER_URL, timeout=120) as resp:
            zip_data = resp.read()
    except Exception as exc:
        logger.warning(f"{SOURCE_NAME}: download failed: {exc}")
        return None

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_data)
        tmp_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(ITER_CSV_NAME):
                    csv_path = dest_dir / ITER_CSV_NAME
                    with zf.open(name) as src, open(csv_path, "wb") as dst:
                        dst.write(src.read())
                    logger.info(f"{SOURCE_NAME}: extracted {csv_path} ({csv_path.stat().st_size} bytes)")
                    return csv_path
        logger.warning(f"{SOURCE_NAME}: {ITER_CSV_NAME} not found in ZIP")
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


def _load_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            with open(path, encoding=encoding) as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
                if rows:
                    logger.info(f"{SOURCE_NAME}: loaded {len(rows)} rows ({encoding})")
                    return rows
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Cannot decode {path.name}")


def _find_columns(rows: list[dict[str, str]]) -> dict[str, str]:
    """Find the actual column names matching our candidates."""
    headers = list(rows[0].keys()) if rows else []
    result: dict[str, str] = {}
    for key, candidates in _COL_CANDIDATES.items():
        found = None
        for candidate in candidates:
            for header in headers:
                if candidate.upper() == header.upper().strip():
                    found = header
                    break
            if found:
                break
        if found:
            result[key] = found
    return result


def _get_number(row: dict[str, str], col: str | None) -> float:
    if col is None:
        return 0.0
    val = (row.get(col, "0") or "0").strip().replace(",", "")
    if val in ("*", "N/D", "NA", "N.A.", "-"):
        return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0


def parse_iter_data(
    *,
    data_path: Path | None = None,
) -> dict[str, dict[str, float]]:
    """Parse ITER 2020 CSV and return indicator values per municipality.

    Returns: {indicator_id: {municipio_code: value}}
    where values are percentages (0-100).
    """
    if data_path and data_path.exists():
        csv_path = data_path
    else:
        csv_files = _find_csv_files(CACHE_DIR)
        if not csv_files:
            logger.info(f"{SOURCE_NAME}: no local CSV, attempting download...")
            csv_path = _download_iter(CACHE_DIR)
            if csv_path is None:
                logger.info(f"{SOURCE_NAME}: download failed, no data available")
                return {}
        else:
            csv_path = csv_files[0]

    if not csv_path.exists():
        return {}

    rows = _load_csv(csv_path)
    cols = _find_columns(rows)

    logger.info(
        f"{SOURCE_NAME}: found columns — entidad={cols.get('entidad')}, "
        f"mun={cols.get('mun')}, pobtot={cols.get('pobtot')}"
    )

    # Build municipality lookup
    result: dict[str, dict[str, float]] = {
        ind_id: {} for ind_id in INDICATOR_MAP
    }

    for row in rows:
        loc_col = cols.get("loc")
        if loc_col:
            loc_val = (row.get(loc_col, "0001") or "0001").strip()
            if loc_val != "0000":
                continue

        ent = (row.get(cols.get("entidad", ""), "") or "").strip()
        mun = (row.get(cols.get("mun", ""), "") or "").strip()

        # Entity: try numeric first, then text name mapping
        if not ent.isdigit():
            ent = _resolve_entity_name(ent)
        if not ent:
            continue

        ent = ent.zfill(2)
        mun = mun.zfill(3)
        muni_code = ent + mun

        vivhab = _get_number(row, cols.get("vivhab"))
        if vivhab <= 0:
            vivhab = _get_number(row, cols.get("vivtot"))
        if vivhab <= 0:
            continue

        # Compute simple ratio indicators
        for ind_id, config in INDICATOR_MAP.items():
            num = _get_number(row, cols.get(config["numerator"]))
            denom = vivhab
            if denom > 0:
                result[ind_id][muni_code] = round((num / denom) * 100, 1)

    logger.info(
        f"{SOURCE_NAME}: parsed {len(result.get('potable_water_access', {}))} municipalities"
    )
    return result


def get_state_aggregates(
    iter_data: dict[str, dict[str, float]],
    indicator_id: str,
) -> dict[str, float]:
    """Aggregate municipal values to state-level averages.

    Returns: {state_code: average_value}
    """
    values = iter_data.get(indicator_id, {})
    state_sums: dict[str, float] = {}
    state_counts: dict[str, int] = {}

    for muni_code, val in values.items():
        state = muni_code[:2]
        state_sums[state] = state_sums.get(state, 0.0) + val
        state_counts[state] = state_counts.get(state, 0) + 1

    return {
        state: round(state_sums[state] / state_counts[state], 2)
        for state in state_sums
    }


_ENTITY_NAME_MAP = {
    "AGUASCALIENTES": "01", "BAJA CALIFORNIA": "02", "BAJA CALIFORNIA SUR": "03",
    "CAMPECHE": "04", "COAHUILA DE ZARAGOZA": "05", "COAHUILA": "05",
    "COLIMA": "06", "CHIAPAS": "07", "CHIHUAHUA": "08",
    "CIUDAD DE MÉXICO": "09", "CIUDAD DE MEXICO": "09", "DISTRITO FEDERAL": "09",
    "DURANGO": "10", "GUANAJUATO": "11", "GUERRERO": "12",
    "HIDALGO": "13", "JALISCO": "14", "MÉXICO": "15", "MEXICO": "15",
    "MICHOACÁN DE OCAMPO": "16", "MICHOACAN DE OCAMPO": "16", "MICHOACÁN": "16",
    "MORELOS": "17", "NAYARIT": "18", "NUEVO LEÓN": "19", "NUEVO LEON": "19",
    "OAXACA": "20", "PUEBLA": "21", "QUERÉTARO": "22",
    "QUINTANA ROO": "23", "SAN LUIS POTOSÍ": "24", "SAN LUIS POTOSI": "24",
    "SINALOA": "25", "SONORA": "26", "TABASCO": "27",
    "TAMAULIPAS": "28", "TLAXCALA": "29",
    "VERACRUZ DE IGNACIO DE LA LLAVE": "30", "VERACRUZ": "30",
    "YUCATÁN": "31", "YUCATAN": "31", "ZACATECAS": "32",
}


def _resolve_entity_name(name: str) -> str | None:
    name = name.strip().upper()
    if name.isdigit():
        return name.zfill(2)
    return _ENTITY_NAME_MAP.get(name)


def check_available() -> bool:
    csv_files = _find_csv_files(CACHE_DIR)
    return len(csv_files) > 0
