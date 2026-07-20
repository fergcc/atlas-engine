"""Alineación de pares de series tidy con distinta frecuencia.

Dado un par de series (posiblemente de distinta frecuencia, p. ej. ITAEE
trimestral vs BLS mensual), determina la frecuencia de trabajo, remuestrea
ambas por promedio del periodo (nunca por último valor — un promedio es una
mejor representación de "actividad del trimestre" que un corte puntual) y
recorta a la ventana muestral común (intersección de fechas).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.config import MIN_OBS_ANNUAL, MIN_OBS_DAILY, MIN_OBS_MONTHLY, MIN_OBS_QUARTERLY

# Frecuencias ordenadas de más baja a más alta granularidad. La "más baja" (el
# mínimo de las dos) es la que se usa como frecuencia de trabajo del par.
FREQ_RANK = {"annual": 0, "quarterly": 1, "monthly": 2, "daily": 3}

# Alias de pandas >=2.2 (evita los alias "M"/"Q"/"Y" deprecados en pandas 3).
FREQ_TO_PANDAS_OFFSET = {"annual": "YE", "quarterly": "QE", "monthly": "ME", "daily": "D"}

# Umbral mínimo de observaciones alineadas por frecuencia de trabajo. Ver
# pipeline/config.py — configurable en un solo lugar.
MIN_OBS_BY_FREQUENCY = {
    "quarterly": MIN_OBS_QUARTERLY,
    "monthly": MIN_OBS_MONTHLY,
    "annual": MIN_OBS_ANNUAL,
    "daily": MIN_OBS_DAILY,
}


@dataclass
class AlignedPair:
    frequency_used: str
    df: pd.DataFrame  # columnas: period_end_date, value_a, value_b
    n_obs: int
    start: str | None
    end: str | None
    insufficient_data: bool
    min_obs_required: int


def _lowest_frequency(freq_a: str, freq_b: str) -> str:
    return freq_a if FREQ_RANK[freq_a] <= FREQ_RANK[freq_b] else freq_b


def _resample_mean(tidy_df: pd.DataFrame, target_freq: str) -> pd.Series:
    """Remuestrea una serie tidy a `target_freq` promediando las observaciones
    de cada periodo (nunca tomando el último valor del periodo)."""
    series = tidy_df.set_index("period_end_date")["value"].sort_index()
    native_freq = tidy_df["frequency"].iloc[0]
    if native_freq == target_freq:
        # Ya está en la frecuencia objetivo: solo se normaliza el índice al
        # fin de periodo correspondiente para que el merge de abajo alinee bien.
        return series.resample(FREQ_TO_PANDAS_OFFSET[target_freq]).mean()
    return series.resample(FREQ_TO_PANDAS_OFFSET[target_freq]).mean()


def align_pair(series_a: pd.DataFrame, series_b: pd.DataFrame) -> AlignedPair:
    """Alinea dos series tidy (ver `processing.normalize.TIDY_COLUMNS`).

    1. Determina la frecuencia de trabajo: la más baja (menos granular) de las
       dos series de entrada.
    2. Remuestrea ambas series a esa frecuencia promediando por periodo.
    3. Calcula la ventana muestral común (intersección de fechas con datos en
       ambas series).
    4. Si `n_obs` cae debajo del mínimo configurado para esa frecuencia
       (`pipeline/config.py`), marca el par como `insufficient_data=True`.
    """
    freq_a = series_a["frequency"].iloc[0]
    freq_b = series_b["frequency"].iloc[0]
    target_freq = _lowest_frequency(freq_a, freq_b)

    resampled_a = _resample_mean(series_a, target_freq).rename("value_a")
    resampled_b = _resample_mean(series_b, target_freq).rename("value_b")

    merged = pd.concat([resampled_a, resampled_b], axis=1).dropna(how="any")
    merged.index.name = "period_end_date"
    merged = merged.reset_index()

    n_obs = len(merged)
    min_required = MIN_OBS_BY_FREQUENCY[target_freq]

    if n_obs == 0:
        return AlignedPair(
            frequency_used=target_freq,
            df=merged,
            n_obs=0,
            start=None,
            end=None,
            insufficient_data=True,
            min_obs_required=min_required,
        )

    return AlignedPair(
        frequency_used=target_freq,
        df=merged,
        n_obs=n_obs,
        start=str(pd.Timestamp(merged["period_end_date"].min()).date()),
        end=str(pd.Timestamp(merged["period_end_date"].max()).date()),
        insufficient_data=n_obs < min_required,
        min_obs_required=min_required,
    )
