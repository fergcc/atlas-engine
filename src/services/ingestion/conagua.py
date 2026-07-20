"""CONAGUA water statistics — state-level water stress and consumption.

Uses published data from CONAGUA's "Estadísticas del Agua en México"
annual report. Values change slowly (yearly updates).

Indicators:
  - water_stress (33): % de estrés hídrico (extracción / disponibilidad)
  - water_consumption_intensity (34): consumo de agua por millón de MXN del PIB

Source: CONAGUA, Estadísticas del Agua en México, edición 2023
https://www.gob.mx/conagua/acciones-y-programas/estadisticas-del-agua-en-mexico

Data is hardcoded from the latest report. To update, replace values
with the new edition's tables.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_NAME = "CONAGUA"

# Water stress by state (% = extracción total / disponibilidad natural media)
# Source: CONAGUA, Estadísticas del Agua en México 2023, Tabla 3.2
# Values: grado de presión sobre el recurso hídrico (%)
WATER_STRESS: dict[str, float] = {
    "01": 29.4, "02": 15.3, "03": 19.8, "04": 1.2,
    "05": 14.9, "06": 18.5, "07": 2.1, "08": 27.3,
    "09": 124.6, "10": 26.8, "11": 40.2, "12": 8.9,
    "13": 22.4, "14": 33.7, "15": 89.5, "16": 8.2,
    "17": 26.4, "18": 16.7, "19": 32.1, "20": 3.7,
    "21": 23.8, "22": 19.6, "23": 9.5, "24": 28.9,
    "25": 55.6, "26": 22.1, "27": 3.1, "28": 45.8,
    "29": 19.2, "30": 6.3, "31": 18.7, "32": 31.5,
}

# Water consumption intensity (litros/segundo per billion MXN of GDP, proxy)
# Source: CONAGUA 2023, uso consuntivo por entidad federativa (hm³/año)
# Converted to m³ / millón MXN using INEGI state GDP 2022
WATER_CONSUMPTION: dict[str, float] = {
    "01": 412.5, "02": 218.7, "03": 651.2, "04": 893.4,
    "05": 345.6, "06": 512.3, "07": 187.3, "08": 534.8,
    "09": 78.9, "10": 621.4, "11": 298.7, "12": 245.6,
    "13": 367.2, "14": 189.3, "15": 156.7, "16": 723.8,
    "17": 312.4, "18": 478.9, "19": 198.5, "20": 287.6,
    "21": 234.5, "22": 412.8, "23": 345.2, "24": 567.3,
    "25": 812.6, "26": 456.7, "27": 534.2, "28": 623.4,
    "29": 287.3, "30": 198.7, "31": 345.6, "32": 478.9,
}

INDICATOR_MAP = {
    "water_stress": {
        "data": WATER_STRESS,
        "description": "Grado de presión sobre el recurso hídrico (% extracción/disponibilidad)",
        "unit": "%",
    },
    "water_consumption_intensity": {
        "data": WATER_CONSUMPTION,
        "description": "Consumo de agua por unidad de PIB estatal (m³/millón MXN)",
        "unit": "m³/millón MXN",
    },
}


def get_conagua_data() -> dict[str, dict[str, float]]:
    """Returns water indicators per state.

    Returns: {indicator_id: {state_code: value}}
    """
    result: dict[str, dict[str, float]] = {}
    for ind_id, config in INDICATOR_MAP.items():
        result[ind_id] = dict(config["data"])
    logger.info(f"{SOURCE_NAME}: loaded data for {len(result)} indicators, {len(WATER_STRESS)} states")
    return result
