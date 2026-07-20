"""Normalización de series crudas al esquema tidy común del pipeline.

Cualquier serie —venga de INEGI, Banxico, FRED, BEA, BLS o del generador
mock— pasa por `normalize_series` antes de tocar `processing.align` o
`econometrics.*`. Esto garantiza que el motor econométrico siempre opera sobre
la misma forma de datos sin importar la fuente.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

# Columnas del esquema tidy, en el orden en que deben aparecer siempre.
TIDY_COLUMNS: list[str] = [
    "series_id",
    "source",
    "country",
    "region_code",
    "scian_code",
    "naics_code",
    "sector_id",
    "frequency",
    "seasonal_adjustment",
    "period_end_date",
    "value",
    "units",
    "proxy_type",
    "publication_lag_days",
    "vintage_date",
]

VALID_FREQUENCIES = {"daily", "monthly", "quarterly", "annual"}
VALID_SEASONAL_ADJUSTMENT = {"sa", "nsa", "not_applicable"}
VALID_PROXY_TYPES = {"output_index", "labor_input", "exchange_rate", "trade_value", "employment_index"}
VALID_COUNTRIES = {"MX", "US", "CA", "BR", "CO", "AR", "XX"}


@dataclass(frozen=True)
class SeriesMeta:
    """Metadatos de una serie, constantes a lo largo de todas sus observaciones."""

    series_id: str
    source: str
    country: str
    region_code: str
    sector_id: str | None
    frequency: str
    seasonal_adjustment: str
    units: str
    proxy_type: str
    publication_lag_days: int
    vintage_date: str
    scian_code: str | None = None
    naics_code: str | None = None

    def __post_init__(self) -> None:
        if self.frequency not in VALID_FREQUENCIES:
            raise ValueError(f"{self.series_id}: frequency inválida: {self.frequency!r}")
        if self.seasonal_adjustment not in VALID_SEASONAL_ADJUSTMENT:
            raise ValueError(
                f"{self.series_id}: seasonal_adjustment inválido: {self.seasonal_adjustment!r}"
            )
        if self.proxy_type not in VALID_PROXY_TYPES:
            raise ValueError(f"{self.series_id}: proxy_type inválido: {self.proxy_type!r}")
        if self.country not in VALID_COUNTRIES:
            raise ValueError(f"{self.series_id}: country inválido: {self.country!r}")


def normalize_series(
    observations: Iterable[Sequence] | pd.Series,
    meta: SeriesMeta,
) -> pd.DataFrame:
    """Convierte observaciones crudas (periodo, valor) al esquema tidy común.

    `observations` acepta:
    - una `pandas.Series` indexada por fecha (o algo convertible a fecha), o
    - un iterable de tuplas/listas `(period_end_date, value)`.

    Filas con valor no numérico (NaN, cadenas vacías, "N/E", etc.) se
    descartan explícitamente en vez de propagarse como ceros o strings.
    Devuelve un DataFrame con exactamente las columnas de `TIDY_COLUMNS`,
    ordenado por `period_end_date` y sin duplicados (se conserva la última
    observación de cada fecha, asumiendo que es la revisión más reciente).
    """
    if isinstance(observations, pd.Series):
        pairs = list(zip(observations.index, observations.to_numpy()))
    else:
        pairs = list(observations)

    if not pairs:
        raise ValueError(f"{meta.series_id}: no hay observaciones para normalizar")

    df = pd.DataFrame(pairs, columns=["period_end_date", "value"])
    df["period_end_date"] = pd.to_datetime(df["period_end_date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df = df.dropna(subset=["value"])
    if df.empty:
        raise ValueError(f"{meta.series_id}: todas las observaciones eran no numéricas")

    df = df.sort_values("period_end_date").drop_duplicates(subset="period_end_date", keep="last")

    df["series_id"] = meta.series_id
    df["source"] = meta.source
    df["country"] = meta.country
    df["region_code"] = meta.region_code
    df["scian_code"] = meta.scian_code
    df["naics_code"] = meta.naics_code
    df["sector_id"] = meta.sector_id
    df["frequency"] = meta.frequency
    df["seasonal_adjustment"] = meta.seasonal_adjustment
    df["units"] = meta.units
    df["proxy_type"] = meta.proxy_type
    df["publication_lag_days"] = meta.publication_lag_days
    df["vintage_date"] = meta.vintage_date

    return df[TIDY_COLUMNS].reset_index(drop=True)
