"""Excepciones específicas de la capa de ingestión.

Se usan en vez de devolver `None`/datos vacíos para que un fallo de
credenciales o de red nunca se confunda silenciosamente con "no hay dato para
este periodo".
"""
from __future__ import annotations


class IngestionError(RuntimeError):
    """Clase base de errores de ingestión."""


class MissingCredentialError(IngestionError):
    """La variable de entorno con la credencial requerida no está definida.

    No es reintentable: no tiene sentido reintentar una llamada que nunca va a
    tener token. El llamador debe conseguir la credencial (ver docs/README)
    antes de volver a intentar.
    """


class SourceUnavailableError(IngestionError):
    """La fuente respondió con error, timeout o payload inválido tras agotar
    los reintentos con backoff exponencial (`tenacity`), o devolvió un cuerpo
    que no tiene la forma esperada para la serie solicitada.
    """
