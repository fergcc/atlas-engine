"""
Statistical Office Adapter — abstract base class.

Each country must subclass this to provide subnational time series data
for the Atlas methodology. Adapters are auto-discovered from the adapters/
directory by the adapter registry.

Lifecycle:
  1. Adapter is instantiated (reads credentials from config).
  2. `health_check()` verifies connectivity.
  3. `fetch_series(sector_id, region_code)` returns normalized tidy DataFrames.
  4. `list_regions()` / `list_indicators()` supply metadata for the API/frontend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class IndicatorInfo:
    id: str
    name: str
    name_en: str
    theme: str
    frequency: str
    unit: str
    proxy_type: str
    geographic_granularity: str
    available: bool = True


@dataclass
class RegionInfo:
    code: str
    name: str
    name_en: str | None = None
    level: str = "state"


@dataclass
class SeriesBundle:
    series_id: str
    tidy: pd.DataFrame
    label: str


class StatisticalOfficeAdapter(ABC):

    country: str
    country_name: str
    country_name_en: str

    @abstractmethod
    def health_check(self) -> bool:
        """Verifica que el adapter tenga conectividad con su fuente de datos."""
        ...

    @abstractmethod
    def fetch_series(
        self,
        sector_id: str,
        region_code: str = "NAC",
        *,
        scian_code: str | None = None,
        naics_code: str | None = None,
        frequency: str | None = None,
    ) -> SeriesBundle:
        """Obtiene y normaliza una serie de tiempo para un sector y región dados.

        Devuelve un `SeriesBundle` con la serie ya normalizada al esquema tidy
        (lista para entrar a `processing.align` y `econometrics.pipeline_runner`).
        """
        ...

    @abstractmethod
    def list_indicators(self) -> list[IndicatorInfo]:
        """Lista los indicadores disponibles vía este adapter."""
        ...

    @abstractmethod
    def list_regions(self, level: str = "state") -> list[RegionInfo]:
        """Lista las regiones subnacionales disponibles."""
        ...

    @abstractmethod
    def get_default_proxy_type(self) -> str:
        """Tipo de proxy por defecto para este adapter ('output_index', 'labor_input', etc.)."""
        ...

    def get_series_id(
        self, sector_id: str, region_code: str, source_suffix: str = ""
    ) -> str:
        country_lower = self.country.lower()
        region_lower = region_code.lower()
        suffix = f"_{source_suffix}" if source_suffix else ""
        return f"{country_lower}-{region_lower}_{sector_id}{suffix}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(country={self.country})"
