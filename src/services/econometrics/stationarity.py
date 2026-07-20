"""Pruebas de estacionariedad: ADF (H0 = raíz unitaria) confirmado por KPSS
(H0 = estacionaria), con transformación log previa y diferenciación acotada.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, kpss

from src.config import ALPHA, MAX_DIFF_ORDER


@dataclass
class StationarityResult:
    adf_stat: float
    adf_pvalue: float
    kpss_stat: float
    kpss_pvalue: float
    order_integrated: int
    log_transformed: bool
    is_stationary: bool
    warnings: list[str] = field(default_factory=list)


def _adf_kpss(series: pd.Series) -> tuple[bool, dict]:
    adf_stat, adf_pvalue, *_ = adfuller(series, autolag="AIC")
    with warnings.catch_warnings():
        # kpss emite InterpolationWarning cuando el estadístico cae fuera de
        # la tabla de referencia (p-value reportado como cota, no exacto).
        warnings.simplefilter("ignore")
        kpss_stat, kpss_pvalue, *_ = kpss(series, regression="c", nlags="auto")

    # ADF rechaza H0 (raíz unitaria) si p < alpha -> evidencia de estacionariedad.
    # KPSS rechaza H0 (estacionaria) si p < alpha -> evidencia de NO estacionariedad.
    # Se declara estacionaria solo si ambas pruebas coinciden en ese diagnóstico.
    adf_says_stationary = adf_pvalue < ALPHA
    kpss_says_stationary = kpss_pvalue > ALPHA
    stationary = bool(adf_says_stationary and kpss_says_stationary)

    return stationary, {
        "adf_stat": float(adf_stat),
        "adf_pvalue": float(adf_pvalue),
        "kpss_stat": float(kpss_stat),
        "kpss_pvalue": float(kpss_pvalue),
    }


def test_stationarity(raw_series: pd.Series) -> StationarityResult:
    """Determina el orden de integración de una serie.

    1. Aplica logaritmo si todos los valores son estrictamente positivos
       (estabiliza varianza; nunca se aplica a series con ceros/negativos).
    2. Corre ADF + KPSS sobre la serie (transformada o no).
    3. Si no hay evidencia conjunta de estacionariedad, diferencia una vez y
       repite, hasta un máximo de `MAX_DIFF_ORDER` diferencias. Si al llegar
       a ese límite sigue sin confirmarse estacionariedad, se devuelve ese
       orden como cota superior junto con un warning explícito (nunca se
       difiere indefinidamente en busca de un resultado "limpio").
    """
    warns: list[str] = []
    series = raw_series.dropna().astype(float)
    if len(series) < 8:
        raise ValueError("test_stationarity requiere al menos 8 observaciones no nulas")

    log_transformed = bool((series > 0).all())
    working = np.log(series) if log_transformed else series

    order = 0
    current = working
    stationary = False
    stats: dict = {}
    while True:
        stationary, stats = _adf_kpss(current)
        if stationary or order >= MAX_DIFF_ORDER:
            break
        current = current.diff().dropna()
        order += 1
        if len(current) < 8:
            warns.append(
                f"Quedaron muy pocas observaciones tras diferenciar {order} veces; "
                "se detiene la búsqueda de estacionariedad en este orden."
            )
            break

    if not stationary:
        warns.append(
            f"No se confirmó estacionariedad (ADF+KPSS) tras diferenciar {order} "
            f"vez/veces (límite MAX_DIFF_ORDER={MAX_DIFF_ORDER}); se usa este orden "
            "como mejor estimación disponible."
        )

    return StationarityResult(
        adf_stat=stats["adf_stat"],
        adf_pvalue=stats["adf_pvalue"],
        kpss_stat=stats["kpss_stat"],
        kpss_pvalue=stats["kpss_pvalue"],
        order_integrated=order,
        log_transformed=log_transformed,
        is_stationary=stationary,
        warnings=warns,
    )
