"""Cointegración: Engle-Granger (screening rápido) + Johansen (autoritativo)
+ VECM (vector de cointegración y velocidad de ajuste) cuando hay evidencia
de cointegración.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import VECM, coint_johansen

# Columnas de statsmodels `coint_johansen(...).cvt`: valores críticos al
# 90%, 95% y 99%, en ese orden.
_CRIT_95_COLUMN = 1


@dataclass
class EngleGrangerResult:
    stat: float
    p_value: float
    cointegrated: bool


@dataclass
class JohansenResult:
    trace_stat: list[float]
    trace_crit_95: list[float]
    critical_values: list[list[float]]
    rank: int


@dataclass
class VECMResult:
    cointegrating_vector: list[float]
    adjustment_speed: list[float]


def test_engle_granger(series_a: pd.Series, series_b: pd.Series, *, alpha: float = 0.05) -> EngleGrangerResult:
    """Prueba de Engle-Granger (`statsmodels.tsa.stattools.coint`) como
    screening rápido de cointegración entre dos series I(1). Se usa como
    primera señal; el resultado autoritativo es Johansen (`test_johansen`).
    """
    stat, p_value, _crit = coint(series_a, series_b)
    return EngleGrangerResult(stat=float(stat), p_value=float(p_value), cointegrated=bool(p_value < alpha))


def test_johansen(levels_df: pd.DataFrame, *, k_ar_diff: int = 1, det_order: int = 0) -> JohansenResult:
    """Prueba de traza de Johansen (`coint_johansen`), resultado autoritativo
    de cointegración para sistemas de 2+ variables.

    El rango de cointegración se determina con el procedimiento secuencial
    estándar: se recorren las hipótesis r<=0, r<=1, ... en orden y se cuenta
    cuántas se rechazan (traza > valor crítico al 95%) ANTES de la primera
    que no se rechaza; no se cuentan rechazos aislados más allá de ese punto,
    para evitar inflar el rango por ruido de muestra finita.
    """
    with warnings.catch_warnings():
        # statsmodels castea a real un resultado complejo de vez en cuando en
        # sistemas cercanos a rango completo; es un artefacto numérico interno
        # de la librería, no un problema con nuestros datos de entrada.
        warnings.simplefilter("ignore")
        result = coint_johansen(levels_df.to_numpy(), det_order, k_ar_diff)

    trace_stat = [float(x) for x in result.lr1]
    critical_values = [[float(x) for x in row] for row in result.cvt]
    trace_crit_95 = [row[_CRIT_95_COLUMN] for row in critical_values]

    rank = 0
    for stat_value, crit_value in zip(trace_stat, trace_crit_95):
        if stat_value > crit_value:
            rank += 1
        else:
            break

    return JohansenResult(
        trace_stat=trace_stat,
        trace_crit_95=trace_crit_95,
        critical_values=critical_values,
        rank=rank,
    )


def fit_vecm(levels_df: pd.DataFrame, *, coint_rank: int, k_ar_diff: int = 1) -> VECMResult:
    """Ajusta un VECM con `coint_rank` vectores de cointegración (mínimo 1 —
    esta función solo debe llamarse cuando Johansen ya reportó rank > 0) y
    devuelve el vector de cointegración normalizado (`beta`, primera columna)
    y la velocidad de ajuste de cada variable (`alpha`, primera columna).
    """
    rank = max(coint_rank, 1)
    model = VECM(levels_df, k_ar_diff=k_ar_diff, coint_rank=rank, deterministic="ci")
    fitted = model.fit()
    cointegrating_vector = [float(x) for x in np.asarray(fitted.beta)[:, 0]]
    adjustment_speed = [float(x) for x in np.asarray(fitted.alpha)[:, 0]]
    return VECMResult(cointegrating_vector=cointegrating_vector, adjustment_speed=adjustment_speed)
