"""SESNSP crime data ingestion.
 
Downloads and parses municipal-level crime statistics from the Secretariado
Ejecutivo del Sistema Nacional de Seguridad Pública (SESNSP).

Data sources:
  - Metodología 2015-2025: municipal CSV via gob.mx open data
  - Metodología 2026+: updated format, same portal
  - Manual download: place CSV in data/sesnsp/ directory
    → Download from https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva
    → Look for "Incidencia delictiva municipal" CSV under the desired methodology

The module auto-discovers CSV files in the cache directory. If multiple
files exist, it prefers the newest one. Falls back gracefully if no data
is available.

Population data for per-capita rates can be provided as a separate CSV
(columns: Cve_Ent, Cve_Mun, Poblacion) in the same directory.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

SOURCE_NAME = "SESNSP"
SESNSP_CACHE_DIR = DATA_DIR / "sesnsp"
SESNSP_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Crime type mappings to indicator IDs
CRIME_MAP = {
    "homicide_rate": {
        "keywords": ["HOMICIDIO"],
        "subtypes": ["DOLOSO", "CULPOSO"],
    },
    "robbery_rate": {
        "keywords": ["ROBO"],
        "subtypes": None,  # all robbery subtypes
    },
    "domestic_violence_rate": {
        "keywords": ["VIOLENCIA FAMILIAR"],
        "subtypes": None,
    },
}


def _find_csv_files(directory: Path) -> list[Path]:
    """Find all CSV files in the directory, sorted by mtime (newest first)."""
    if not directory.exists():
        return []
    files = sorted(
        [f for f in directory.iterdir() if f.suffix.lower() == ".csv"],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return files


def _load_csv(path: Path) -> list[dict[str, str]]:
    """Load and parse the SESNSP CSV into a list of row dicts.
    
    Tries multiple encodings (SESNSP publishes in Latin-1 or UTF-8
    depending on methodology year).
    """
    for encoding in ["utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            with open(path, encoding=encoding) as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
                if rows:
                    logger.info(f"{SOURCE_NAME}: loaded {len(rows)} rows using {encoding}")
                    return rows
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Cannot decode {path.name} with any known encoding")


def _find_column(rows: list[dict[str, str]], candidates: list[str]) -> str:
    """Find the first matching column name from the CSV header."""
    if not rows:
        return candidates[0]
    headers = list(rows[0].keys())
    for candidate in candidates:
        for header in headers:
            if candidate.lower().replace(" ", "") == header.lower().replace(" ", ""):
                return header
        for header in headers:
            if candidate.lower() in header.lower():
                return header
    return candidates[0]


def _extract_crime_totals(
    rows: list[dict[str, str]],
    *,
    keywords: list[str],
    subtypes: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Extract total crime counts per municipality per year.

    Returns: {key: {"total": int, "municipio": str, "year": str, "entidad": str}}
    where key is "{muni_code}_{year}".
    """
    result: dict[str, dict[str, Any]] = {}

    tipo_col = _find_column(rows, ["Tipo de delito", "TipoDelito", "tipo_delito"])
    subtipo_col = _find_column(rows, ["Subtipo de delito", "SubtipoDelito", "subtipo_delito"])
    ent_col = _find_column(rows, ["Clave_Ent", "Cve. Entidad", "cve_entidad", "Entidad"])
    mun_col = _find_column(rows, ["Clave_Mun", "Cve. Municipio", "cve_municipio", "Municipio"])
    year_col = _find_column(rows, ["Año", "Anio", "ano", "year", "AÑO"])

    month_names = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]

    for row in rows:
        tipo = (row.get(tipo_col, "") or "").upper().strip()
        subtipo = (row.get(subtipo_col, "") or "").upper().strip()

        matched = any(kw.upper() in tipo for kw in keywords)
        if not matched:
            continue

        if subtypes is not None:
            if not any(st.upper() in subtipo for st in subtypes):
                continue

        ent = (row.get(ent_col, "") or "").strip()
        mun = (row.get(mun_col, "") or "").strip()

        # Entity code can be numeric (01-32) or text name ("Aguascalientes")
        ent_code = _resolve_entity_code(ent)
        if not ent_code:
            ent_text = ent
        else:
            ent_text = ent_code

        # Municipality code may be numeric or text name
        mun_code = _resolve_muni_code(mun, ent_text)
        if mun_code is None:
            mun_code = mun[-3:].zfill(3) if len(mun) >= 3 else mun.zfill(3)
        full_code = f"{ent_text}{mun_code}" if ent_code else f"{ent[:2].zfill(2)}{mun_code}"

        year = (row.get(year_col, "") or "").strip()
        if not year:
            continue

        total = 0
        for month_col in month_names:
            val = row.get(month_col, "0")
            try:
                total += int(float(val or "0"))
            except (ValueError, TypeError):
                pass

        total_col = _find_column(rows, ["Total"])
        if total_col and total == 0:
            try:
                total = int(float(row.get(total_col, "0") or "0"))
            except (ValueError, TypeError):
                pass

        key = f"{full_code}_{year}"
        if key not in result:
            result[key] = {
                "total": 0, "municipio": full_code,
                "year": year, "entidad": ent_text,
            }
        result[key]["total"] += total

    return result


_ENTITY_MAP: dict[str, str] = {
    "AGUASCALIENTES": "01", "BAJA CALIFORNIA": "02", "BAJA CALIFORNIA SUR": "03",
    "CAMPECHE": "04", "COAHUILA DE ZARAGOZA": "05", "COAHUILA": "05",
    "COLIMA": "06", "CHIAPAS": "07", "CHIHUAHUA": "08",
    "CIUDAD DE MEXICO": "09", "CIUDAD DE MÉXICO": "09", "DISTRITO FEDERAL": "09",
    "DURANGO": "10", "GUANAJUATO": "11", "GUERRERO": "12",
    "HIDALGO": "13", "JALISCO": "14", "MEXICO": "15", "MÉXICO": "15",
    "MICHOACAN DE OCAMPO": "16", "MICHOACÁN DE OCAMPO": "16", "MICHOACAN": "16", "MICHOACÁN": "16",
    "MORELOS": "17", "NAYARIT": "18", "NUEVO LEON": "19", "NUEVO LEÓN": "19",
    "OAXACA": "20", "PUEBLA": "21", "QUERETARO": "22", "QUERÉTARO": "22",
    "QUINTANA ROO": "23", "SAN LUIS POTOSI": "24", "SAN LUIS POTOSÍ": "24",
    "SINALOA": "25", "SONORA": "26", "TABASCO": "27",
    "TAMAULIPAS": "28", "TLAXCALA": "29", "VERACRUZ DE IGNACIO DE LA LLAVE": "30",
    "VERACRUZ": "30", "YUCATAN": "31", "YUCATÁN": "31",
    "ZACATECAS": "32",
}


def _resolve_entity_code(raw: str) -> str | None:
    """Resolve entity name or code to 2-digit INEGI code."""
    raw = raw.strip().upper()
    if raw.isdigit():
        return raw.zfill(2)
    return _ENTITY_MAP.get(raw)


def _resolve_muni_code(raw: str, entity_code: str) -> str | None:
    """Resolve municipality name or code to 3-digit code."""
    raw = raw.strip()
    if raw.isdigit():
        return raw.zfill(3)
    return None


def get_crime_data(
    *,
    data_path: Path | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Returns crime totals per municipality per year for all supported indicators.

    Searches for CSV files in SESNSP_CACHE_DIR by default. Falls back
    gracefully if no data is available.

    Returns:
        {indicator_id: {key: {"total": int, "municipio": str, "year": str, "entidad": str}}}
    """
    if data_path and data_path.exists():
        csv_path = data_path
    else:
        csv_files = _find_csv_files(SESNSP_CACHE_DIR)
        if not csv_files:
            logger.info(
                f"{SOURCE_NAME}: no CSV files found in {SESNSP_CACHE_DIR}. "
                f"Download the latest municipal crime CSV from "
                f"https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva "
                f"and place it in {SESNSP_CACHE_DIR}/"
            )
            return {}
        csv_path = csv_files[0]
        logger.info(f"{SOURCE_NAME}: using {csv_path.name}")

    if not csv_path.exists():
        return {}

    try:
        rows = _load_csv(csv_path)
    except Exception as exc:
        logger.warning(f"{SOURCE_NAME}: failed to parse {csv_path.name}: {exc}")
        return {}

    logger.info(f"{SOURCE_NAME}: loaded {len(rows)} rows from {csv_path.name}")

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for indicator_id, config in CRIME_MAP.items():
        result[indicator_id] = _extract_crime_totals(
            rows,
            keywords=config["keywords"],
            subtypes=config.get("subtypes"),
        )
        logger.info(
            f"{SOURCE_NAME}: {indicator_id} -> {len(result[indicator_id])} municipality-year entries"
        )

    return result


def get_latest_year_totals(
    crime_data: dict[str, dict[str, dict[str, Any]]],
    indicator_id: str,
    year: str | None = None,
) -> dict[str, int]:
    """Extract latest year totals per municipality for a given indicator.

    Returns: {municipio_code: total_crimes}
    """
    entries = crime_data.get(indicator_id, {})
    if not entries:
        return {}

    if year is None:
        years = sorted({e["year"] for e in entries.values()}, reverse=True)
        year = years[0] if years else None
    if year is None:
        return {}

    return {
        e["municipio"]: e["total"]
        for e in entries.values()
        if e["year"] == year
    }


def compute_crime_rate(
    indicator_id: str, total: int, population: int
) -> float:
    """Compute crime rate per 100k inhabitants."""
    if population <= 0:
        return 0.0
    return (total / population) * 100_000


def check_available() -> bool:
    """Check if SESNSP data is available locally."""
    csv_files = _find_csv_files(SESNSP_CACHE_DIR)
    return len(csv_files) > 0
