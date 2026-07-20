"""Ingestión de BLS (Bureau of Labor Statistics) — Time Series API v2.

Endpoint real:
    https://api.bls.gov/publicAPI/v2/timeseries/data/  (POST, cuerpo JSON)

Documentación: https://www.bls.gov/developers/api_signature_v2.htm

Serie de ejemplo usada como referencia de integración: `SMU48000003133600001`
(CES estatal, Texas, manufactura de equipo de transporte). Este es el proxy
declarado `labor_input` (empleo), no `output_index` — nunca se debe presentar
como "producción" sin ese matiz (ver docs/metodologia.md).

Convención de construcción del `series_id` (documentada en
https://www.bls.gov/help/hlpforma.htm#SM, verificada con ejemplos reales de
la propia página): a diferencia de INEGI, BLS SÍ permite construir IDs
determinísticamente sin necesidad de un "buscador" — pero cada ID construido
debe VERIFICARSE contra la API real antes de usarse (una serie inexistente
no da error claro, ver más abajo). Formato de 20 caracteres:
    "SM" + "U" (no ajustado estacionalmente) + estado FIPS (2 dígitos) +
    código de área (5 dígitos, "00000" = todo el estado) +
    código de supersector+industria (8 dígitos, catálogo CES — NO es
    literalmente el código NAICS, aunque para las industrias manufactureras
    de 4-6 dígitos suele coincidir con el prefijo NAICS + ceros de relleno,
    ver `download.bls.gov/pub/time.series/sm/sm.industry` para el catálogo
    completo) + tipo de dato (2 dígitos, "01" = todos los empleados).
Ejemplos usados en `pipeline/live/run_live_pilot.py`: "30000000" (industria
manufacturera total), "31336400" (equipo aeroespacial, NAICS 3364),
"32325400" (farmacéutica, NAICS 3254).

La API key (v2, 500 consultas/día) se lee de la variable de entorno
`BLS_API_KEY` (vía python-dotenv). Sin key, BLS v1 permite 25 consultas/día,
pero este pipeline exige la key para no depender de un límite tan bajo.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from src.services.ingestion._http import request_json
from src.services.ingestion.exceptions import MissingCredentialError, SourceUnavailableError

load_dotenv()

SOURCE_NAME = "BLS"
BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

DEFAULT_SERIES_ID = "SMU48000003133600001"


def _get_api_key() -> str:
    api_key = os.getenv("BLS_API_KEY")
    if not api_key:
        raise MissingCredentialError(
            "BLS_API_KEY no está definido. Regístrate (gratis) en "
            "https://data.bls.gov/registrationEngine/ para subir el límite de 25 a 500 "
            "consultas/día y agrega la key a tu archivo .env (ver .env.example)."
        )
    return api_key


def fetch_timeseries(
    series_ids: list[str] | None = None,
    *,
    start_year: str | None = None,
    end_year: str | None = None,
) -> list[dict[str, Any]]:
    """Consulta una o más series del Time Series API v2 de BLS (hasta 50 series
    y 20 años por llamada) y devuelve la lista cruda `Results.series`.
    """
    api_key = _get_api_key()
    series_ids = series_ids or [DEFAULT_SERIES_ID]
    body: dict[str, Any] = {"seriesid": series_ids, "registrationkey": api_key}
    if start_year:
        body["startyear"] = start_year
    if end_year:
        body["endyear"] = end_year

    payload = request_json("POST", BASE_URL, source=SOURCE_NAME, json=body)

    status = payload.get("status")
    if status != "REQUEST_SUCCEEDED":
        raise SourceUnavailableError(
            f"{SOURCE_NAME}: status={status!r}, mensajes={payload.get('message')!r}"
        )
    try:
        series = payload["Results"]["series"]
    except (KeyError, TypeError) as exc:
        raise SourceUnavailableError(f"{SOURCE_NAME}: payload inesperado: {payload!r}") from exc
    if not series:
        raise SourceUnavailableError(f"{SOURCE_NAME}: no se recibieron series para {series_ids}")
    return series
