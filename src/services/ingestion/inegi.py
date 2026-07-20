"""Ingestión de INEGI — API de Indicadores (Banco de Información Económica, BIE).

Endpoint real:
    https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/
        INDICATOR/{indicador}/{idioma}/{area}/{recientes}/{fuente}/2.0/{token}?type=json

Documentación: https://www.inegi.org.mx/servicios/api_indicadores.html

IMPORTANTE sobre `{fuente}` y `{area}` (verificado en vivo contra el token real,
no asumido de la documentación): para el catálogo "Indicadores económicos de
coyuntura" (donde viven IMAI e ITAEE), el segmento de fuente de datos debe ser
literalmente `BIE-BISE` (con guión) — ni `BIE` ni `BISE` solos funcionan y
devuelven `ErrorCode:100` ("No se encontraron resultados") aunque el token sea
válido. Esto se confirmó inspeccionando el scope de AngularJS del "Constructor
de consultas" oficial (https://www.inegi.org.mx/app/querybuilder2/) mientras
generaba la URL para un indicador seleccionado ahí. El área nacional es `00`
(no `0700`, que también da `ErrorCode:100`).

Series verificadas en vivo (claves del BIE, catálogo "actualizado" — estas
claves NO se pueden derivar de la documentación pública ni buscar por texto
vía la API; solo se descubren con el "Constructor de consultas" del sitio,
navegando el árbol hasta el nodo hoja — ver `pipeline/live/run_live_pilot.py`
para el método programático de recorrido del árbol usado para las claves de
abajo):
    - 736407: "Total de la actividad industrial" (IMAI), Índice de volumen
      físico, Series Originales (NSA), nacional. Existe también una variante
      desestacionalizada bajo el mismo árbol ("Series desestacionalizadas y
      tendencia-ciclo", nodo 606616) que no se ha identificado a nivel de
      clave específica aún (TODO: ubicarla si se necesita SA en vez de NSA).
    - 741177: ITAEE total estatal, Índice de volumen físico, Series
      Originales — usar con `area_code` = código INEGI de 2 dígitos del
      estado (ver `region_registry.yaml`).
    - 741651: ITAEE del sector "31-33 Industrias manufactureras" por estado,
      mismo uso que 741177 pero acotado a manufactura. IMPORTANTE: devuelve
      `ErrorCode:100` (sin resultados) para `area_code` en {"04", "05", "07",
      "19", "28", "30"} (Campeche, Coahuila, Chiapas, Nuevo León, Tamaulipas,
      Veracruz) — verificado contra la API real, no es un bug de este
      pipeline; el catálogo estatal de INEGI simplemente no publica ese
      desglose para esos estados bajo esta clave.
    - IMAI por subsector SCIAN, nacional, mismo árbol que 736407 ("Actividad
      industrial, base 2018 > Series Originales > Índice de volumen físico >
      31-33 Industrias manufactureras > {subsector}"): 736515 (3364,
      aeroespacial), 736462 (3254, farmacéutica), 736491 (total subsector
      333, maquinaria y equipo — no existe desglose a 333611/turbinas
      eólicas en este catálogo), 736427 (3118, panadería y tortillas — proxy
      de agroindustrial ya declarado en `scian_naics_crosswalk.csv`), 736459
      (3251, químicos básicos — mitad de petroquímica) y 736457 (3241,
      derivados del petróleo y carbón — la otra mitad de petroquímica, sin
      usar actualmente). El catálogo IMAI SÍ desagrega hasta SCIAN de 4
      dígitos a nivel nacional (a diferencia del catálogo ITAEE estatal,
      que solo llega hasta manufactura 31-33 total o grupos gruesos
      "31"/"32"/"33" — no hay equivalente estatal de estas claves de 4
      dígitos). Ver `pipeline/live/run_live_pilot.py` para la tabla completa
      de cobertura y las aproximaciones documentadas en cada caso.

El token se lee de la variable de entorno `INEGI_TOKEN` (vía python-dotenv).
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from src.services.ingestion._http import request_json
from src.services.ingestion.exceptions import MissingCredentialError, SourceUnavailableError

load_dotenv()

SOURCE_NAME = "INEGI"
BASE_URL = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml"

# "Total de la actividad industrial" (IMAI), Índice, Series Originales, nacional.
DEFAULT_INDICATOR_ID = "736407"
# Código de área para "Estados Unidos Mexicanos" (nacional) en el BIE.
NATIONAL_AREA_CODE = "00"
# Fuente de datos requerida por el catálogo de indicadores de coyuntura
# (IMAI/ITAEE) — ver nota arriba, no es "BIE" ni "BISE" solos.
COYUNTURA_SOURCE_DB = "BIE-BISE"


def _get_token() -> str:
    token = os.getenv("INEGI_TOKEN")
    if not token:
        raise MissingCredentialError(
            "INEGI_TOKEN no está definido. Registra un token gratuito e inmediato en "
            "https://www.inegi.org.mx/servicios/api_indicadores.html y agrégalo a tu "
            "archivo .env (ver .env.example)."
        )
    return token


def fetch_indicator(
    indicator_id: str = DEFAULT_INDICATOR_ID,
    *,
    area_code: str = NATIONAL_AREA_CODE,
    language: str = "es",
    recent_only: bool = False,
    source_db: str = COYUNTURA_SOURCE_DB,
) -> list[dict[str, Any]]:
    """Consulta un indicador del BIE de INEGI (nacional o estatal) y devuelve la
    lista cruda de observaciones (`OBSERVATIONS`) tal cual la entrega la API.

    Para series estatales (ITAEE), pasar `area_code` con el código de entidad
    INEGI de 2 dígitos definido en `region_registry.yaml`.
    """
    token = _get_token()
    recent = "true" if recent_only else "false"
    url = (
        f"{BASE_URL}/INDICATOR/{indicator_id}/{language}/{area_code}/{recent}/"
        f"{source_db}/2.0/{token}?type=json"
    )
    payload = request_json("GET", url, source=SOURCE_NAME)
    try:
        series = payload["Series"][0]["OBSERVATIONS"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceUnavailableError(
            f"{SOURCE_NAME}: payload inesperado para indicador {indicator_id} "
            f"en área {area_code}: {payload!r}"
        ) from exc
    if not series:
        raise SourceUnavailableError(
            f"{SOURCE_NAME}: el indicador {indicator_id} (área {area_code}) no trajo observaciones"
        )
    return series


ITAEE_TOTAL_INDICATOR_ID = "741177"
ITAEE_MANUFACTURING_INDICATOR_ID = "741651"


def fetch_itaee(
    state_area_code: str, *, indicator_id: str = ITAEE_TOTAL_INDICATOR_ID
) -> list[dict[str, Any]]:
    """Atajo semántico para el ITAEE (Indicador Trimestral de la Actividad
    Económica Estatal), proxy estatal trimestral de producción en México.
    `indicator_id` por defecto corresponde al ITAEE total estatal (verificado
    en vivo); pasar `ITAEE_MANUFACTURING_INDICATOR_ID` para el subtotal de
    manufactura (31-33), o el id específico de otro SCIAN del catálogo BIE.
    """
    return fetch_indicator(indicator_id, area_code=state_area_code)
