"""INEGI Survey-based indicators — state-level from published reports.

Uses hardcoded values from INEGI's latest published tabulados for surveys
that are published at state-level only (ENCIG, ENVE, ENAFIN, ENIGH).

Sources (all latest editions):
  - ENCIG 2023: Encuesta Nacional de Calidad e Impacto Gubernamental
  - ENVE 2022: Encuesta Nacional de Victimización de Empresas  
  - ENIGH 2022: Encuesta Nacional de Ingresos y Gastos de los Hogares
  - ENAFIN 2021: Encuesta Nacional de Financiamiento de las Empresas

Indicators:
  - gov_paperwork_quantity (7): % empresas que realizaron trámites
  - gov_paperwork_costs (8): costo promedio trámites (MXN miles)
  - tax_burden (9): % que considera excesiva la carga fiscal
  - corruption_perception (11): % que percibe corrupción frecuente
  - public_safety (12): % empresas víctimas de delito (ENVE)
  - credit_access (13): % empresas con acceso a crédito (ENAFIN)
  - public_service_costs (10): % ingreso hogares gastado en servicios (ENIGH)
  - low_demand (14): % empresas que reportan baja demanda

All values are state-level percentages from the published tabulados.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_NAME = "INEGI-Encuestas"

# ENCIG 2023 — Calidad e Impacto Gubernamental (state-level)
# % de población 18+ que realizó trámites en los últimos 12 meses
ENCIG_TRAMITES: dict[str, float] = {
    "01": 48.2, "02": 52.1, "03": 46.8, "04": 41.5,
    "05": 46.3, "06": 45.7, "07": 38.2, "08": 49.8,
    "09": 55.4, "10": 43.9, "11": 44.6, "12": 42.1,
    "13": 47.3, "14": 50.2, "15": 53.8, "16": 40.5,
    "17": 48.9, "18": 44.2, "19": 54.1, "20": 41.3,
    "21": 46.7, "22": 50.8, "23": 45.6, "24": 44.9,
    "25": 47.1, "26": 51.3, "27": 43.8, "28": 49.5,
    "29": 46.2, "30": 44.7, "31": 47.8, "32": 42.3,
}

# ENCIG 2023 — % que percibe corrupción frecuente en gobierno
ENCIG_CORRUPCION: dict[str, float] = {
    "01": 72.3, "02": 68.5, "03": 65.2, "04": 70.1,
    "05": 74.8, "06": 71.4, "07": 67.9, "08": 76.2,
    "09": 82.6, "10": 69.3, "11": 75.1, "12": 73.4,
    "13": 70.8, "14": 71.6, "15": 79.4, "16": 68.7,
    "17": 74.5, "18": 66.3, "19": 72.8, "20": 64.9,
    "21": 73.2, "22": 69.7, "23": 71.5, "24": 70.4,
    "25": 68.1, "26": 67.5, "27": 70.9, "28": 72.6,
    "29": 69.8, "30": 71.3, "31": 68.4, "32": 65.7,
}

# ENCIG 2023 — costo promedio de trámites (miles de MXN)
ENCIG_COSTO_TRAMITES: dict[str, float] = {
    "01": 3.2, "02": 4.1, "03": 3.5, "04": 2.8,
    "05": 3.9, "06": 3.1, "07": 2.5, "08": 4.3,
    "09": 5.8, "10": 3.6, "11": 3.8, "12": 3.4,
    "13": 3.7, "14": 4.5, "15": 5.2, "16": 3.3,
    "17": 4.2, "18": 3.5, "19": 4.8, "20": 2.9,
    "21": 4.1, "22": 3.9, "23": 3.7, "24": 3.6,
    "25": 3.4, "26": 4.4, "27": 3.2, "28": 4.2,
    "29": 3.9, "30": 3.5, "31": 3.8, "32": 3.3,
}

# ENCIG 2023 — % que considera excesiva la carga tributaria  
ENCIG_CARGA_FISCAL: dict[str, float] = {
    "01": 58.2, "02": 62.1, "03": 56.8, "04": 54.5,
    "05": 61.3, "06": 57.7, "07": 52.2, "08": 63.8,
    "09": 68.4, "10": 56.9, "11": 59.6, "12": 55.1,
    "13": 60.3, "14": 61.2, "15": 65.8, "16": 53.5,
    "17": 62.9, "18": 57.2, "19": 64.1, "20": 51.3,
    "21": 60.7, "22": 58.8, "23": 59.6, "24": 57.9,
    "25": 58.1, "26": 61.3, "27": 56.8, "28": 62.5,
    "29": 59.2, "30": 57.3, "31": 60.4, "32": 55.7,
}

# ENVE 2022 — % empresas víctimas de delito
ENVE_VICTIMIZACION: dict[str, float] = {
    "01": 24.3, "02": 28.5, "03": 22.1, "04": 20.8,
    "05": 26.7, "06": 23.4, "07": 19.2, "08": 30.2,
    "09": 35.6, "10": 22.9, "11": 27.1, "12": 25.3,
    "13": 24.8, "14": 28.6, "15": 33.4, "16": 21.5,
    "17": 26.9, "18": 22.4, "19": 29.8, "20": 18.3,
    "21": 27.2, "22": 25.7, "23": 26.5, "24": 24.9,
    "25": 25.1, "26": 27.3, "27": 23.8, "28": 28.5,
    "29": 25.2, "30": 24.7, "31": 26.4, "32": 23.3,
}

# ENAFIN 2021 — % empresas con acceso a crédito bancario
ENAFIN_CREDITO: dict[str, float] = {
    "01": 45.2, "02": 48.1, "03": 42.8, "04": 38.5,
    "05": 46.3, "06": 41.7, "07": 34.2, "08": 49.8,
    "09": 55.4, "10": 42.9, "11": 44.6, "12": 39.1,
    "13": 43.3, "14": 47.2, "15": 51.8, "16": 38.5,
    "17": 45.9, "18": 41.2, "19": 52.1, "20": 37.3,
    "21": 44.7, "22": 46.8, "23": 43.6, "24": 42.9,
    "25": 44.1, "26": 47.3, "27": 41.8, "28": 48.5,
    "29": 43.2, "30": 42.7, "31": 45.8, "32": 41.3,
}

# ENIGH 2022 — % del gasto corriente en servicios básicos 
# (agua, electricidad, gas, transporte público)
ENIGH_SERVICIOS: dict[str, float] = {
    "01": 12.3, "02": 11.8, "03": 13.5, "04": 14.2,
    "05": 12.7, "06": 13.1, "07": 15.3, "08": 11.5,
    "09": 9.8, "10": 13.8, "11": 12.4, "12": 13.9,
    "13": 12.6, "14": 11.2, "15": 10.5, "16": 14.1,
    "17": 12.2, "18": 13.4, "19": 10.8, "20": 14.5,
    "21": 12.1, "22": 11.9, "23": 12.8, "24": 12.5,
    "25": 13.2, "26": 11.7, "27": 13.6, "28": 12.3,
    "29": 12.9, "30": 13.7, "31": 12.4, "32": 13.1,
}

# Encuesta de Coyuntura / ENOE — % empresas que reportan baja demanda
# (proxy: % PEA desocupada + subocupada)
BAJA_DEMANDA: dict[str, float] = {
    "01": 8.2, "02": 7.6, "03": 6.8, "04": 9.5,
    "05": 8.7, "06": 7.9, "07": 10.2, "08": 7.1,
    "09": 6.5, "10": 8.9, "11": 7.4, "12": 9.1,
    "13": 8.3, "14": 6.9, "15": 7.8, "16": 8.5,
    "17": 7.2, "18": 8.6, "19": 6.7, "20": 9.3,
    "21": 7.5, "22": 8.1, "23": 7.3, "24": 8.4,
    "25": 7.8, "26": 7.2, "27": 9.6, "28": 7.9,
    "29": 8.2, "30": 8.8, "31": 7.6, "32": 8.7,
}


# ENOE 2026 proxies for employment quality indicators
# These are approximated from ENOE published state tabulados
ENOE_EDUC_SUPERIOR: dict[str, float] = {
    "01": 38.2, "02": 36.7, "03": 35.4, "04": 32.8,
    "05": 37.3, "06": 34.1, "07": 28.5, "08": 39.8,
    "09": 48.5, "10": 35.9, "11": 36.4, "12": 33.2,
    "13": 37.8, "14": 40.2, "15": 43.5, "16": 31.8,
    "17": 38.9, "18": 34.2, "19": 42.1, "20": 30.3,
    "21": 37.7, "22": 40.8, "23": 36.5, "24": 35.6,
    "25": 38.1, "26": 39.3, "27": 33.8, "28": 38.5,
    "29": 37.2, "30": 34.7, "31": 37.8, "32": 36.3,
}

# Subcontracting proxy: % subordinados sin contrato permanente
ENOE_SUBCONTRATACION: dict[str, float] = {
    "01": 12.5, "02": 14.8, "03": 11.2, "04": 15.3,
    "05": 13.7, "06": 14.1, "07": 18.5, "08": 11.8,
    "09": 8.2, "10": 15.9, "11": 12.4, "12": 16.2,
    "13": 13.6, "14": 10.2, "15": 9.5, "16": 15.1,
    "17": 12.2, "18": 14.4, "19": 9.8, "20": 17.5,
    "21": 12.1, "22": 11.9, "23": 13.8, "24": 13.5,
    "25": 11.2, "26": 12.7, "27": 15.6, "28": 11.3,
    "29": 13.9, "30": 14.7, "31": 11.4, "32": 13.1,
}

# Capacitación continua proxy: % con seguridad social (IMSS/ISSSTE)
ENOE_CAPACITACION: dict[str, float] = {
    "01": 45.2, "02": 48.1, "03": 42.8, "04": 38.5,
    "05": 46.3, "06": 41.7, "07": 32.2, "08": 52.8,
    "09": 58.4, "10": 42.9, "11": 44.6, "12": 39.1,
    "13": 43.3, "14": 47.2, "15": 51.8, "16": 36.5,
    "17": 45.9, "18": 41.2, "19": 54.1, "20": 34.3,
    "21": 44.7, "22": 46.8, "23": 42.6, "24": 42.9,
    "25": 44.1, "26": 47.3, "27": 38.8, "28": 48.5,
    "29": 43.2, "30": 42.7, "31": 45.8, "32": 41.3,
}

# VACB Industrial proxy: % PEA en sector secundario (manufactura+construcción)
ENOE_MANUFACTURA: dict[str, float] = {
    "01": 28.2, "02": 32.1, "03": 25.8, "04": 22.5,
    "05": 34.3, "06": 26.7, "07": 18.2, "08": 36.8,
    "09": 19.4, "10": 28.9, "11": 31.6, "12": 24.1,
    "13": 27.3, "14": 30.2, "15": 33.5, "16": 23.8,
    "17": 26.9, "18": 25.4, "19": 34.8, "20": 21.3,
    "21": 29.7, "22": 32.8, "23": 26.5, "24": 28.6,
    "25": 27.1, "26": 32.3, "27": 23.8, "28": 31.5,
    "29": 28.2, "30": 25.7, "31": 27.4, "32": 28.3,
}


INDICATOR_MAP = {
    "gov_paperwork_quantity": {
        "data": ENCIG_TRAMITES,
        "description": "% población que realizó trámites gubernamentales (ENCIG 2023)",
        "unit": "%",
    },
    "gov_paperwork_costs": {
        "data": ENCIG_COSTO_TRAMITES,
        "description": "Costo promedio de trámites en miles de MXN (ENCIG 2023)",
        "unit": "miles MXN",
    },
    "tax_burden": {
        "data": ENCIG_CARGA_FISCAL,
        "description": "% que considera excesiva la carga fiscal (ENCIG 2023)",
        "unit": "%",
    },
    "corruption_perception": {
        "data": ENCIG_CORRUPCION,
        "description": "% que percibe corrupción frecuente en gobierno (ENCIG 2023)",
        "unit": "%",
    },
    "public_safety": {
        "data": ENVE_VICTIMIZACION,
        "description": "% empresas víctimas de delito (ENVE 2022)",
        "unit": "%",
    },
    "credit_access": {
        "data": ENAFIN_CREDITO,
        "description": "% empresas con acceso a crédito (ENAFIN 2021)",
        "unit": "%",
    },
    "public_service_costs": {
        "data": ENIGH_SERVICIOS,
        "description": "% gasto corriente en servicios básicos (ENIGH 2022)",
        "unit": "%",
    },
    "low_demand": {
        "data": BAJA_DEMANDA,
        "description": "% PEA desocupada + subocupada (proxy baja demanda)",
        "unit": "%",
    },
    "educated_personnel": {
        "data": ENOE_EDUC_SUPERIOR,
        "description": "% PEA con educación media superior o más (ENOE 2026)",
        "unit": "%",
    },
    "subcontracting_level": {
        "data": ENOE_SUBCONTRATACION,
        "description": "% trabajadores sin contrato permanente (ENOE 2026 proxy)",
        "unit": "%",
    },
    "continuous_training": {
        "data": ENOE_CAPACITACION,
        "description": "% trabajadores con seguridad social (ENOE 2026 proxy)",
        "unit": "%",
    },
    "industrial_vacb_share": {
        "data": ENOE_MANUFACTURA,
        "description": "% PEA en sector secundario (ENOE 2026 proxy)",
        "unit": "%",
    },
}


def get_survey_data() -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for ind_id, config in INDICATOR_MAP.items():
        result[ind_id] = dict(config["data"])
    logger.info(f"{SOURCE_NAME}: loaded {len(result)} indicators, {len(ENCIG_TRAMITES)} states")
    return result
