"""Ingestión de FRED (Federal Reserve Bank of St. Louis).

Endpoint real:
    https://api.stlouisfed.org/fred/series/observations

Documentación: https://fred.stlouisfed.org/docs/api/fred/series_observations.html

Serie de ejemplo usada como referencia de integración: `INDPRO` (Industrial
Production: Total Index, nacional, mensual). Para producción industrial por
NAICS a nivel nacional se sustituye el `series_id` por el código específico
(p. ej. `IPG3364S` para equipo aeroespacial); FRED no publica producción
industrial por estado — el mejor proxy estatal en EEUU es empleo/horas
manufactureras de BLS (ver `pipeline/ingestion/bls.py`).

La API key se lee de la variable de entorno `FRED_API_KEY` (vía python-dotenv).
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from src.services.ingestion._http import request_json
from src.services.ingestion.exceptions import MissingCredentialError, SourceUnavailableError

load_dotenv()

SOURCE_NAME = "FRED"
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

DEFAULT_SERIES_ID = "INDPRO"  # Industrial Production: Total Index


def _get_api_key() -> str:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise MissingCredentialError(
            "FRED_API_KEY no está definido. Crea una cuenta gratuita en "
            "https://fred.stlouisfed.org/docs/api/api_key.html para obtener una API key "
            "inmediata y agrégala a tu archivo .env (ver .env.example)."
        )
    return api_key


def fetch_series(
    series_id: str = DEFAULT_SERIES_ID,
    *,
    observation_start: str | None = None,
    observation_end: str | None = None,
    units: str = "lin",
) -> list[dict[str, Any]]:
    """Consulta una serie de observaciones de FRED y devuelve la lista cruda
    (`observations`). Formato de fecha esperado por la API: `YYYY-MM-DD`.
    `units="lin"` devuelve el nivel sin transformar (ver parámetro `units` de
    la API de FRED para variaciones porcentuales, log, etc.).
    """
    api_key = _get_api_key()
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "units": units,
    }
    if observation_start:
        params["observation_start"] = observation_start
    if observation_end:
        params["observation_end"] = observation_end

    payload = request_json("GET", BASE_URL, source=SOURCE_NAME, params=params)
    try:
        observations = payload["observations"]
    except (KeyError, TypeError) as exc:
        raise SourceUnavailableError(
            f"{SOURCE_NAME}: payload inesperado para la serie {series_id}: {payload!r}"
        ) from exc
    if not observations:
        raise SourceUnavailableError(f"{SOURCE_NAME}: la serie {series_id} no trajo observaciones")
    return observations
