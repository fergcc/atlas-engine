"""Ingestión de Banxico SIE (Sistema de Información Económica).

Endpoint real:
    https://www.banxico.org.mx/SieAPIRest/service/v1/series/{idSerie}/datos

Documentación: https://www.banxico.org.mx/SieAPIRest/service/v1/doc/index.html

Serie de ejemplo usada como referencia de integración: `SF43718` (tipo de
cambio FIX, pesos por dólar, diario) — la única serie con granularidad diaria
real entre las fuentes del Atlas (ver plan de proyecto).

El token se lee de la variable de entorno `BANXICO_TOKEN` (vía python-dotenv)
y se envía en el header `Bmx-Token`, como recomienda la documentación oficial.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from src.services.ingestion._http import request_json
from src.services.ingestion.exceptions import MissingCredentialError, SourceUnavailableError

load_dotenv()

SOURCE_NAME = "Banxico SIE"
BASE_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"

DEFAULT_SERIES_ID = "SF43718"  # Tipo de cambio FIX


def _get_token() -> str:
    token = os.getenv("BANXICO_TOKEN")
    if not token:
        raise MissingCredentialError(
            "BANXICO_TOKEN no está definido. Registra un token gratuito e inmediato en "
            "https://www.banxico.org.mx/SieAPIRest/service/v1/doc/index.html y agrégalo "
            "a tu archivo .env (ver .env.example)."
        )
    return token


def fetch_series(
    series_id: str = DEFAULT_SERIES_ID,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Consulta una serie del SIE de Banxico y devuelve las observaciones
    crudas (`datos`). Si `start_date`/`end_date` se omiten, la API devuelve el
    histórico completo disponible. Formato de fecha esperado por la API:
    `YYYY-MM-DD`.
    """
    token = _get_token()
    if start_date and end_date:
        url = f"{BASE_URL}/{series_id}/datos/{start_date}/{end_date}"
    else:
        url = f"{BASE_URL}/{series_id}/datos"

    # No se envían query params adicionales: el parámetro "decimales" (con
    # cualquier valor) hace que el SIE de Banxico devuelva un HTTP 400 genérico
    # ("Ha tecleado un carácter no válido..."), confirmado probando la misma
    # URL con y sin ese parámetro contra el token real.
    payload = request_json("GET", url, source=SOURCE_NAME, headers={"Bmx-Token": token})
    try:
        series = payload["bmx"]["series"][0]["datos"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceUnavailableError(
            f"{SOURCE_NAME}: payload inesperado para la serie {series_id}: {payload!r}"
        ) from exc
    if not series:
        raise SourceUnavailableError(f"{SOURCE_NAME}: la serie {series_id} no trajo observaciones")
    return series
