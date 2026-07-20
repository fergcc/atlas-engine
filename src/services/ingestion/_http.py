"""Utilidades HTTP compartidas por los módulos de ingestión.

Centraliza la política de reintentos (tenacity, backoff exponencial) para
errores transitorios de red/rate-limit. Los errores de credenciales faltantes
NUNCA pasan por aquí — se levantan antes, en cada módulo de fuente, para no
gastar reintentos en algo que no es transitorio.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.services.ingestion.exceptions import SourceUnavailableError

logger = logging.getLogger(__name__)

# Códigos HTTP que consideramos transitorios y por tanto reintentables.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class _RetryableHTTPError(requests.RequestException):
    """Error interno usado solo para señalarle a tenacity que reintente."""


def _do_request(method: str, url: str, timeout: float, **kwargs: Any) -> requests.Response:
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise _RetryableHTTPError(str(exc)) from exc
    if response.status_code in _RETRYABLE_STATUS:
        raise _RetryableHTTPError(f"HTTP {response.status_code} de {url}")
    return response


_retrying_request = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(_RetryableHTTPError),
    before_sleep=lambda retry_state: logger.warning(
        "Reintentando petición HTTP (intento %s) tras: %s",
        retry_state.attempt_number,
        retry_state.outcome.exception() if retry_state.outcome else None,
    ),
)(_do_request)


def request_json(
    method: str,
    url: str,
    *,
    source: str,
    timeout: float = 20.0,
    **kwargs: Any,
) -> dict:
    """Hace una petición HTTP con reintentos de backoff exponencial en errores
    de red/rate-limit (hasta 4 intentos), y devuelve el cuerpo parseado como
    JSON. Levanta `SourceUnavailableError` (no reintentable en este punto) si:
    - se agotaron los reintentos sin éxito,
    - la respuesta final no es 2xx,
    - el cuerpo no es JSON válido.
    """
    try:
        response = _retrying_request(method, url, timeout, **kwargs)
    except _RetryableHTTPError as exc:
        raise SourceUnavailableError(
            f"{source}: sin respuesta utilizable tras reintentos ({url}): {exc}"
        ) from exc

    if not response.ok:
        raise SourceUnavailableError(
            f"{source}: HTTP {response.status_code} inesperado de {url}: {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise SourceUnavailableError(f"{source}: respuesta no es JSON válido ({url})") from exc
