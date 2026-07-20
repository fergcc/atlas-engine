"""
Pydantic schemas for the Engine API.

Shapes are compatible with the existing Dashboard frontend data contracts
(app/src/lib/types.ts) to ensure smooth migration.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---- Enums ----

class ProxyType(str, Enum):
    output_index = "output_index"
    labor_input = "labor_input"
    exchange_rate = "exchange_rate"
    trade_value = "trade_value"
    employment_index = "employment_index"


class Frequency(str, Enum):
    daily = "daily"
    monthly = "monthly"
    quarterly = "quarterly"
    annual = "annual"


class PairLevel(str, Enum):
    nacional = "nacional"
    estatal = "estatal"
    regional = "regional"


class SectorPriority(str, Enum):
    strategic = "strategic"
    reference = "reference"


class PipelineMode(str, Enum):
    mock = "mock"
    live = "live"
    mixed = "mixed"


class PipelineStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class CountryCode(str, Enum):
    MX = "MX"
    US = "US"


# ---- Sector ----

class SectorMeta(BaseModel):
    id: str
    label: str
    label_en: str | None = None
    icon: str
    scian_codes: list[str] = Field(default_factory=list)
    naics_codes: list[str] = Field(default_factory=list)
    isic_codes: list[str] = Field(default_factory=list)
    priority: SectorPriority = SectorPriority.strategic
    source_atlas: bool = False


# ---- Series ----

class SeriesCatalogEntry(BaseModel):
    id: str
    nombre: str
    pais: CountryCode | str
    region_code: str
    sector_id: str
    fuente: str
    periodicidad: str
    unidad: str
    proxy_type: ProxyType | str
    ultima_actualizacion: str
    proxima_actualizacion_estimada: str


class SeriesObservation(BaseModel):
    period: str
    value: float | None


class SeriesFile(BaseModel):
    id: str
    meta: dict[str, Any]
    observations: list[SeriesObservation]


# ---- Pairs ----

class PairMeta(BaseModel):
    pair_id: str
    level: PairLevel | str
    sector_id: str
    series_a: str
    series_b: str


# ---- Econometric Results ----

class StationarityResult(BaseModel):
    adf_statistic: float | None = None
    adf_p_value: float | None = None
    kpss_statistic: float | None = None
    kpss_p_value: float | None = None
    is_stationary: bool | None = None
    order_of_integration: int | None = None
    log_transformed: bool = False


class GrangerDirectionResult(BaseModel):
    f_stat: float
    p_value: float
    p_value_fdr_adj: float
    significant: bool


class GrangerResult(BaseModel):
    optimal_lag: int | None = None
    selection_criterion: str = "bic"
    a_causes_b: GrangerDirectionResult | None = None
    b_causes_a: GrangerDirectionResult | None = None


class CointegrationEngleGranger(BaseModel):
    statistic: float | None = None
    p_value: float | None = None
    cointegrated: bool | None = None


class CointegrationJohansen(BaseModel):
    trace_statistic: list[float] | None = None
    critical_values: list[list[float]] | None = None
    cointegration_rank: int | None = None


class VecmResult(BaseModel):
    cointegration_vector: list[float] | None = None
    adjustment_speed: list[float] | None = None


class SampleMeta(BaseModel):
    frequency_used: str | None = None
    start: str | None = None
    end: str | None = None
    n_obs: int = 0


class ResultFile(BaseModel):
    pair_id: str | None = None
    sector: dict[str, Any] = Field(default_factory=dict)
    series_a: dict[str, Any] = Field(default_factory=dict)
    series_b: dict[str, Any] = Field(default_factory=dict)
    sample: SampleMeta = Field(default_factory=SampleMeta)
    stationarity: dict[str, Any] | None = None
    granger: dict[str, Any] | None = None
    cointegration_engle_granger: dict[str, Any] | None = None
    cointegration_johansen: dict[str, Any] | None = None
    vecm: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    generated_at: str = ""
    data_vintage: str = ""
    insufficient_data: bool = False


# ---- Manifest ----

class Manifest(BaseModel):
    generated_at: str
    mode: PipelineMode | str
    refresh_cadence: str
    sectors: list[SectorMeta]
    series_catalog: list[SeriesCatalogEntry]
    pairs: list[PairMeta]


# ---- Analysis Requests ----

class SectorAnalysisRequest(BaseModel):
    sector_name: str
    country_codes: list[str] = Field(default_factory=lambda: ["MX"])
    include_cgv: bool = True
    include_territorial: bool = False


class TerritorialAnalysisRequest(BaseModel):
    country: str
    sector_id: str | None = None
    indicators: list[str] | None = None
    region_codes: list[str] | None = None


class EconometricsRequest(BaseModel):
    series_a: list[dict[str, Any]]
    series_b: list[dict[str, Any]]
    meta_a: dict[str, Any] = Field(default_factory=dict)
    meta_b: dict[str, Any] = Field(default_factory=dict)


class LLMClassifySectorRequest(BaseModel):
    sector_name: str
    description: str = ""
    context: str = ""


class LLMExtractIndicatorsRequest(BaseModel):
    text: str
    indicator_ids: list[str] | None = None
    country: str = "MX"


class LLMGenerateNarrativeRequest(BaseModel):
    sector_id: str
    country_codes: list[str] = Field(default_factory=lambda: ["MX"])
    language: str = "es"


class SearchResearchRequest(BaseModel):
    query: str
    source: str = "web"
    max_results: int = 10


# ---- Admin ----

class PipelineRunRequest(BaseModel):
    mode: PipelineMode = PipelineMode.live
    sectors: list[str] | None = None


class PipelineRunStatus(BaseModel):
    id: int
    started_at: str
    finished_at: str | None = None
    mode: str
    status: str
    pairs_total: int
    pairs_real: int
    pairs_mock: int
    error_message: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    engine_env: str
    use_mocks: bool
    db_connected: bool
    version: str = "0.1.0"
