"""INEGI ENOE — Encuesta Nacional de Ocupación y Empleo.

Downloads and processes ENOE microdata to compute state-level employment indicators:
  - employed_population (15): % población ocupada (clase1=1 sobre PEA total)
  - female_employment (16): % mujeres ocupadas en edad reproductiva (15-49)
  - hours_worked (20): horas promedio trabajadas por semana
  - remuneration_level (19): ingreso promedio mensual (pesos)

Data source: INEGI ENOE microdata ZIP (SDEMT — socio-demographic module)
URL pattern: .../enoe/15ymas/microdatos/enoe_{year}_{quarter}t_csv.zip
Auto-downloads and caches in data/enoe/
Uses survey expansion factors (fac_tri) for population-weighted estimates.
"""

from __future__ import annotations

import csv
import io
import logging
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

SOURCE_NAME = "ENOE"
CACHE_DIR = DATA_DIR / "enoe"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ENOE_URL = (
    "https://www.inegi.org.mx/contenidos/programas/enoe/15ymas/"
    "microdatos/enoe_2026_trim1_csv.zip"
)

INDICATOR_MAP = {
    "employed_population": {
        "description": "% población ocupada (PEA ocupada / PEA total, 15+ años)",
        "unit": "%",
    },
    "female_employment": {
        "description": "% mujeres ocupadas (15-49 años / total mujeres PEA 15-49)",
        "unit": "%",
    },
    "hours_worked": {
        "description": "Horas promedio trabajadas por semana (población ocupada)",
        "unit": "horas/semana",
    },
    "remuneration_level": {
        "description": "Ingreso promedio mensual (población ocupada, MXN)",
        "unit": "MXN/mes",
    },
}


def _find_csv_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    files = sorted(
        [f for f in directory.iterdir() if f.suffix.lower() == ".csv" and "SDEM" in f.name],
        key=lambda f: -f.stat().st_mtime,
    )
    return files


def _download_enoe(dest_dir: Path) -> Path | None:
    """Download ENOE microdata ZIP and extract the SDEMT CSV."""
    logger.info(f"{SOURCE_NAME}: downloading from {ENOE_URL} ...")
    try:
        req = urllib.request.Request(ENOE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            zip_data = resp.read()
    except Exception as exc:
        logger.warning(f"{SOURCE_NAME}: download failed: {exc}")
        return None

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_data)
        tmp_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(tmp_path) as zf:
            for name in zf.namelist():
                if "SDEMT" in name and name.endswith(".csv"):
                    csv_path = dest_dir / Path(name).name
                    with zf.open(name) as src:
                        csv_path.write_bytes(src.read())
                    logger.info(f"{SOURCE_NAME}: extracted {csv_path} ({csv_path.stat().st_size} bytes)")
                    return csv_path
        logger.warning(f"{SOURCE_NAME}: SDEMT CSV not found in ZIP")
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


def parse_enoe_data(
    *,
    data_path: Path | None = None,
) -> dict[str, dict[str, float]]:
    """Parse ENOE SDEMT CSV and return state-level indicator values.

    Returns: {indicator_id: {state_code: value}}
    Uses survey expansion factors (fac_tri) for population-weighted estimates.
    """
    if data_path and data_path.exists():
        csv_path = data_path
    else:
        csv_files = _find_csv_files(CACHE_DIR)
        if not csv_files:
            logger.info(f"{SOURCE_NAME}: no local CSV, attempting download...")
            csv_path = _download_enoe(CACHE_DIR)
            if csv_path is None:
                logger.info(
                    f"{SOURCE_NAME}: download failed. "
                    f"Download ENOE microdata from "
                    f"https://www.inegi.org.mx/programas/enoe/15ymas/#microdatos "
                    f"and place the SDEMT CSV in {CACHE_DIR}/"
                )
                return {}
        else:
            csv_path = csv_files[0]

    logger.info(f"{SOURCE_NAME}: processing {csv_path.name} ({csv_path.stat().st_size:,} bytes)")

    # Accumulators per state
    accum: dict[str, dict[str, float]] = {}
    for state in [f"{i:02d}" for i in range(1, 33)]:
        accum[state] = {
            "total_weight": 0,       # sum of fac_tri for PEA
            "occupied_weight": 0,    # sum of fac_tri for occupied
            "female_pea_weight": 0,  # sum of fac_tri for women 15-49 PEA
            "female_occ_weight": 0,  # sum of fac_tri for women 15-49 occupied
            "hours_weighted": 0.0,   # sum of hrsocup * fac_tri for occupied
            "income_weighted": 0.0,  # sum of ingocup * fac_tri for occupied
            "hours_count": 0,        # count for avg hours
            "income_count": 0,       # count for avg income
        }

    line_count = 0
    file_encoding = "latin-1"  # ENOE CSVs use Latin-1/Windows-1252

    try:
        with open(csv_path, encoding=file_encoding) as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                line_count += 1
                if line_count % 500000 == 0:
                    logger.info(f"{SOURCE_NAME}: processed {line_count:,} rows...")

                state = row.get("cve_ent", "").strip().zfill(2)
                if state not in accum:
                    continue

                try:
                    fac = float(row.get("fac_tri", "0") or "0")
                except ValueError:
                    continue
                if fac <= 0:
                    continue

                clase1 = row.get("clase1", "").strip()
                sex = row.get("sex", "").strip()
                try:
                    edad = int(row.get("eda", "0") or "0")
                except ValueError:
                    edad = 0

                # PEA = occupied (1) + unemployed (2)
                is_pea = clase1 in ("1", "2")
                is_occupied = clase1 == "1"
                is_female = sex == "2"
                is_reproductive_age = 15 <= edad <= 49

                if is_pea:
                    a = accum[state]
                    a["total_weight"] += fac
                    if is_occupied:
                        a["occupied_weight"] += fac
                        # Hours worked
                        try:
                            hrs = float(row.get("hrsocup", "0") or "0")
                            if hrs > 0:
                                a["hours_weighted"] += hrs * fac
                                a["hours_count"] += fac
                        except ValueError:
                            pass
                        # Income
                        try:
                            ing = float(row.get("ingocup", "0") or "0")
                            if ing > 0:
                                a["income_weighted"] += ing * fac
                                a["income_count"] += fac
                        except ValueError:
                            pass

                    if is_female and is_reproductive_age:
                        a["female_pea_weight"] += fac
                        if is_occupied:
                            a["female_occ_weight"] += fac

    except Exception as exc:
        logger.error(f"{SOURCE_NAME}: error processing CSV: {exc}")
        return {}

    logger.info(f"{SOURCE_NAME}: processed {line_count:,} rows")

    # Compute indicators
    result: dict[str, dict[str, float]] = {ind_id: {} for ind_id in INDICATOR_MAP}

    for state, a in accum.items():
        tw = a["total_weight"]
        ow = a["occupied_weight"]
        fpw = a["female_pea_weight"]
        fow = a["female_occ_weight"]

        if tw > 0:
            result["employed_population"][state] = round((ow / tw) * 100, 1)
        if fpw > 0:
            result["female_employment"][state] = round((fow / fpw) * 100, 1)
        if a["hours_count"] > 0:
            result["hours_worked"][state] = round(a["hours_weighted"] / a["hours_count"], 1)
        if a["income_count"] > 0:
            result["remuneration_level"][state] = round(a["income_weighted"] / a["income_count"], 0)

    logger.info(
        f"{SOURCE_NAME}: computed {len(result['employed_population'])} states, "
        f"avg employment rate: {sum(result['employed_population'].values())/max(1,len(result['employed_population'])):.1f}%"
    )
    return result


def get_state_aggregates(
    enoe_data: dict[str, dict[str, float]],
    indicator_id: str,
) -> dict[str, float]:
    return enoe_data.get(indicator_id, {})


def check_available() -> bool:
    csv_files = _find_csv_files(CACHE_DIR)
    return len(csv_files) > 0
