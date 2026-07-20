"""Causalidad de Granger vía VAR, con selección de orden por AIC/BIC y prueba
`test_causality` en ambas direcciones.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from statsmodels.tsa.api import VAR

MAX_LAGS_DEFAULT = 8


@dataclass
class DirectionalCausality:
    f_stat: float
    p_value: float


@dataclass
class GrangerResult:
    optimal_lag: int
    selection_criterion: str
    a_causes_b: DirectionalCausality
    b_causes_a: DirectionalCausality
    warnings: list[str] = field(default_factory=list)


def _difference_n_times(series: pd.Series, order: int) -> pd.Series:
    out = series.copy()
    for _ in range(order):
        out = out.diff()
    return out


def test_granger_causality(
    series_a: pd.Series,
    series_b: pd.Series,
    order_a: int,
    order_b: int,
    *,
    criterion: str = "bic",
    max_lags: int | None = None,
) -> GrangerResult:
    """Ajusta un VAR(p) sobre `series_a`/`series_b` diferenciadas al mismo
    orden (`max(order_a, order_b)`, para que ambas entren estacionarias al
    sistema) y corre `test_causality` en ambas direcciones.

    El orden `p` óptimo se elige con `VAR.select_order` según `criterion`
    ("aic" o "bic", bic por defecto — penaliza más los rezagos extra, mejor
    para no sobreajustar con series económicas relativamente cortas).
    """
    warns: list[str] = []
    diff_order = max(order_a, order_b)
    a = _difference_n_times(series_a, diff_order).rename("a")
    b = _difference_n_times(series_b, diff_order).rename("b")
    df = pd.concat([a, b], axis=1).dropna()
    df = df.reset_index(drop=True)

    n = len(df)
    if n < 12:
        raise ValueError(f"test_granger_causality requiere más observaciones útiles (n={n} tras diferenciar)")

    if max_lags is None:
        # Regla práctica: no probar más rezagos de los que la muestra puede
        # soportar sin perder casi todos los grados de libertad.
        max_lags = max(1, min(MAX_LAGS_DEFAULT, n // 5 - 1))
    max_lags = max(1, max_lags)

    model = VAR(df)
    try:
        selection = model.select_order(max_lags)
        optimal_lag = int(getattr(selection, criterion))
    except Exception as exc:  # selección puede fallar con series muy cortas/colineales
        warns.append(f"VAR.select_order falló ({exc}); se usa lag=1 por defecto.")
        optimal_lag = 1

    optimal_lag = max(optimal_lag, 1)
    result = model.fit(maxlags=optimal_lag, ic=None)

    def _direction(caused: str, causing: str) -> DirectionalCausality:
        test = result.test_causality(caused, [causing], kind="f")
        return DirectionalCausality(f_stat=float(test.test_statistic), p_value=float(test.pvalue))

    a_causes_b = _direction(caused="b", causing="a")
    b_causes_a = _direction(caused="a", causing="b")

    return GrangerResult(
        optimal_lag=optimal_lag,
        selection_criterion=criterion,
        a_causes_b=a_causes_b,
        b_causes_a=b_causes_a,
        warnings=warns,
    )
