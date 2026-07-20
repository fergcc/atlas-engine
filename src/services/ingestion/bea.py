"""Ingestión de BEA (Bureau of Economic Analysis) — API REST del dataset Regional.

Endpoint real:
    https://apps.bea.gov/api/data/

Documentación: https://apps.bea.gov/api/signup/ (registro) y
    https://apps.bea.gov/api/bea_web_service_api_user_guide.htm

Consulta de ejemplo usada como referencia de integración: tabla `SQGDP1`
(GDP por estado, trimestral) del dataset `Regional`, línea 1 ("All industry
total"), `GeoFips=STATE` (todos los estados). Para GDP por industria/NAICS
se usa `SQGDP2` con el `IndustryId` correspondiente.

La API key se lee de la variable de entorno `BEA_API_KEY` (vía python-dotenv).
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from src.services.ingestion._http import request_json
from src.services.ingestion.exceptions import MissingCredentialError, SourceUnavailableError

load_dotenv()

SOURCE_NAME = "BEA"
BASE_URL = "https://apps.bea.gov/api/data/"

DEFAULT_TABLE_NAME = "SQGDP1"  # GDP estatal trimestral, todas las industrias
DEFAULT_LINE_CODE = "1"  # "All industry total"


def _get_api_key() -> str:
    api_key = os.getenv("BEA_API_KEY")
    if not api_key:
        raise MissingCredentialError(
            "BEA_API_KEY no está definido. Regístrate con tu email en "
            "https://apps.bea.gov/api/signup/ (la key llega por correo) y agrégala a "
            "tu archivo .env (ver .env.example)."
        )
    return api_key


def fetch_regional_gdp(
    *,
    table_name: str = DEFAULT_TABLE_NAME,
    line_code: str = DEFAULT_LINE_CODE,
    geo_fips: str = "STATE",
    year: str = "ALL",
) -> list[dict[str, Any]]:
    """Consulta el dataset `Regional` de la API de BEA (GDP por estado/industria)
    y devuelve la lista cruda de observaciones (`Data`).

    `geo_fips="STATE"` trae todos los estados en una sola llamada; para un
    estado específico se pasa su código FIPS de 2 dígitos (ver
    `region_registry.yaml`).
    """
    api_key = _get_api_key()
    params = {
        "UserID": api_key,
        "method": "GetData",
        "datasetname": "Regional",
        "TableName": table_name,
        "LineCode": line_code,
        "GeoFips": geo_fips,
        "Year": year,
        "ResultFormat": "JSON",
    }
    payload = request_json("GET", BASE_URL, source=SOURCE_NAME, params=params)
    try:
        results = payload["BEAAPI"]["Results"]
    except (KeyError, TypeError) as exc:
        raise SourceUnavailableError(f"{SOURCE_NAME}: payload inesperado: {payload!r}") from exc

    if isinstance(results, dict) and "Error" in results:
        raise SourceUnavailableError(f"{SOURCE_NAME}: error de la API: {results['Error']!r}")

    try:
        data = results["Data"]
    except (KeyError, TypeError) as exc:
        raise SourceUnavailableError(f"{SOURCE_NAME}: respuesta sin campo 'Data': {results!r}") from exc
    if not data:
        raise SourceUnavailableError(
            f"{SOURCE_NAME}: la tabla {table_name} (línea {line_code}) no trajo observaciones"
        )
    return data
