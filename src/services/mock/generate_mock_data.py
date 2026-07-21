"""Generador de datos mock end-to-end para la Fase 0/1 del pipeline Atlas
México-EEUU.

Genera, para cada sector de `pipeline/reference/sectors.yaml` (nivel
nacional, México vs EEUU) y para el par estatal aeroespacial (Chihuahua vs
Texas), series de tiempo sintéticas pero estadísticamente realistas: cada
par comparte una tendencia estocástica común (cointegración genuina) y tiene
una relación de causalidad de Granger unidireccional conocida por
construcción (ver `_common_trend_pair`). Las series pasan por los mismos
módulos `processing.normalize` / `processing.align` /
`econometrics.pipeline_runner` / `export.to_json` que usaría el pipeline con
datos reales — este script es, además de un generador de fixtures, una
prueba de integración end-to-end del pipeline completo.

Ejecutar con:
    pipeline/.venv/bin/python -m pipeline.mock.generate_mock_data

Reproducible: semilla fija `MOCK_RANDOM_SEED` (ver `pipeline/config.py`), con
un `numpy.random.SeedSequence` hijo distinto (pero determinístico) por serie
generada, de forma que agregar sectores no cambia los números ya generados
para los sectores existentes.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.config import MOCK_END_PERIOD, MOCK_RANDOM_SEED, MOCK_START_PERIOD, SECTORS_YAML
from src.services.econometrics.pipeline_runner import run_all
from src.services.export.to_json import export_all
from src.services.processing.normalize import SeriesMeta, normalize_series

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Parámetros del proceso generador de datos (DGP), nivel nacional -----
DGP_DRIFT = 0.35
DGP_SIGMA_RW = 0.9
DGP_PHI = 0.55  # persistencia AR(1) del componente estacionario
DGP_GAMMA = 0.5  # fuerza del canal de Granger MX -> US (rezago 1)
DGP_SIGMA_EPS_A = 1.1
DGP_SIGMA_EPS_B = 1.0
DGP_RHO = 0.8  # carga de la serie B sobre la tendencia común (cointegración)
DGP_SEASONAL_AMPLITUDE = 1.5

# --- Parámetros del DGP a nivel estatal (aeroespacial: Chihuahua vs Texas) --
STATE_DGP_DRIFT = 0.3
STATE_DGP_SIGMA_RW = 0.7
STATE_DGP_PHI = 0.5
STATE_DGP_GAMMA = 0.45
STATE_DGP_SIGMA_EPS_A = 0.9
STATE_DGP_SIGMA_EPS_B = 0.8
STATE_DGP_RHO = 0.7
STATE_MONTHLY_NOISE_SIGMA = 0.6

# --- Metadatos de fuente (ilustrativos: "(mock)" dice explícitamente que no ---
# --- son datos reales, para que nunca se confundan con una consulta real) ---
MX_NATIONAL_SOURCE = "INEGI - EMIM (mock)"
US_NATIONAL_SOURCE = "FRED - Industrial Production (mock)"
CA_NATIONAL_SOURCE = "Statistics Canada — Monthly GDP (mock)"
MX_STATE_SOURCE = "INEGI - ITAEE (mock)"
US_STATE_SOURCE = "BLS - State and Area Employment (mock)"
CA_STATE_SOURCE = "Statistics Canada — Manufacturing sales (mock)"

MX_NATIONAL_UNITS = "Índice base 2018=100 (sintético)"
US_NATIONAL_UNITS = "Índice base 2017=100 (sintético)"
CA_NATIONAL_UNITS = "Chained (2017) dollars (synthetic)"
MX_STATE_UNITS = "Índice base 2018=100 (sintético)"
US_STATE_UNITS = "Miles de empleos (sintético)"
CA_STATE_UNITS = "Thousands of dollars (synthetic)"

# Rezagos de publicación aproximados (días) de cada fuente real, usados aquí
# solo para que el mock declare vintages realistas.
MX_NATIONAL_LAG_DAYS = 45
US_NATIONAL_LAG_DAYS = 15
CA_NATIONAL_LAG_DAYS = 60
MX_STATE_LAG_DAYS = 95
US_STATE_LAG_DAYS = 21
CA_STATE_LAG_DAYS = 60

CHIHUAHUA_REGION_CODE = "08"
TEXAS_REGION_CODE = "48"

# --- Pares estatales adicionales: frontera + corredores no fronterizos -----
# Extiende el patrón de `_state_pair_frames` (antes hardcodeado a
# Chihuahua-Texas/aeroespacial) a los estados fronterizos de
# `region_registry.yaml` (border: true) y a 3 pares no fronterizos tomados de
# los `corridors` del mismo registro. Cada entrada fija un `rng_index` único
# y PERMANENTE (bloque 100+, separado del rango 0..len(sectors)-1 que usan
# los pares nacionales y del índice fijo del par estatal original) — nunca
# reordenar ni reutilizar un índice ya asignado aquí, o cambian los números
# ya publicados de ese par (ver `_child_rng`).
#
# Correspondencia MX<->US elegida por proximidad geográfica/económica real:
#   Baja California <-> California (frontera Tijuana-San Diego)
#   Sonora          <-> Arizona   (frontera Nogales-Nogales)
#   Chihuahua       <-> Texas     (frontera Cd. Juárez-El Paso; ya existente
#                                   para aeroespacial, ver `_state_pair_frames`
#                                   más abajo)
#   Coahuila        <-> Texas     (frontera Piedras Negras/Acuña-Texas)
#   Nuevo León      <-> Texas     (corredor industrial Monterrey-Texas)
#   Tamaulipas      <-> Texas     (frontera Reynosa/Nuevo Laredo-Texas)
# No fronterizos (corredores de `sectors.yaml`/`region_registry.yaml`):
#   farmaceutico-laguna-culiacan: Jalisco/Sinaloa <-> polos farmacéuticos
#     reales de EEUU (New Jersey, North Carolina)
#   agroindustrial-sureste: Veracruz <-> Florida (agroindustria/logística)
ADDITIONAL_STATE_PAIRS: list[dict[str, Any]] = [
    # --- Frontera: aeroespacial (corredor aeroespacial del noreste) ---
    {
        "rng_index": 100,
        "sector_id": "aeroespacial",
        "mx": {"code": "02", "abbr": "BC", "label": "Baja California"},
        "us": {"code": "06", "abbr": "CA", "label": "California"},
    },
    {
        "rng_index": 101,
        "sector_id": "aeroespacial",
        "mx": {"code": "26", "abbr": "SON", "label": "Sonora"},
        "us": {"code": "04", "abbr": "AZ", "label": "Arizona"},
    },
    {
        "rng_index": 102,
        "sector_id": "aeroespacial",
        "mx": {"code": "05", "abbr": "COA", "label": "Coahuila"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 103,
        "sector_id": "aeroespacial",
        "mx": {"code": "19", "abbr": "NL", "label": "Nuevo León"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 104,
        "sector_id": "aeroespacial",
        "mx": {"code": "28", "abbr": "TAM", "label": "Tamaulipas"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    # --- Frontera: manufactura_total (corredor siderúrgico-metal-mecánico) ---
    {
        "rng_index": 110,
        "sector_id": "manufactura_total",
        "mx": {"code": "02", "abbr": "BC", "label": "Baja California"},
        "us": {"code": "06", "abbr": "CA", "label": "California"},
    },
    {
        "rng_index": 111,
        "sector_id": "manufactura_total",
        "mx": {"code": "26", "abbr": "SON", "label": "Sonora"},
        "us": {"code": "04", "abbr": "AZ", "label": "Arizona"},
    },
    {
        "rng_index": 112,
        "sector_id": "manufactura_total",
        "mx": {"code": "08", "abbr": "CHH", "label": "Chihuahua"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 113,
        "sector_id": "manufactura_total",
        "mx": {"code": "05", "abbr": "COA", "label": "Coahuila"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 114,
        "sector_id": "manufactura_total",
        "mx": {"code": "19", "abbr": "NL", "label": "Nuevo León"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 115,
        "sector_id": "manufactura_total",
        "mx": {"code": "28", "abbr": "TAM", "label": "Tamaulipas"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    # --- No fronterizos: corredores farmacéutico y agroindustrial ---
    {
        "rng_index": 120,
        "sector_id": "farmaceutica",
        "mx": {"code": "14", "abbr": "JAL", "label": "Jalisco"},
        "us": {"code": "34", "abbr": "NJ", "label": "New Jersey"},
    },
    {
        "rng_index": 121,
        "sector_id": "farmaceutica",
        "mx": {"code": "25", "abbr": "SIN", "label": "Sinaloa"},
        "us": {"code": "37", "abbr": "NC", "label": "North Carolina"},
    },
    {
        "rng_index": 122,
        "sector_id": "agroindustrial",
        "mx": {"code": "30", "abbr": "VER", "label": "Veracruz"},
        "us": {"code": "12", "abbr": "FL", "label": "Florida"},
    },
    # --- Frontera: petroquimica (polo petroquímico de Tamaulipas) ---
    {
        "rng_index": 130,
        "sector_id": "petroquimica",
        "mx": {"code": "28", "abbr": "TAM", "label": "Tamaulipas"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 131,
        "sector_id": "petroquimica",
        "mx": {"code": "05", "abbr": "COA", "label": "Coahuila"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    # --- Frontera: farmaceutica ---
    {
        "rng_index": 140,
        "sector_id": "farmaceutica",
        "mx": {"code": "02", "abbr": "BC", "label": "Baja California"},
        "us": {"code": "06", "abbr": "CA", "label": "California"},
    },
    {
        "rng_index": 141,
        "sector_id": "farmaceutica",
        "mx": {"code": "26", "abbr": "SON", "label": "Sonora"},
        "us": {"code": "04", "abbr": "AZ", "label": "Arizona"},
    },
    # --- Frontera: eolica ---
    {
        "rng_index": 150,
        "sector_id": "eolica",
        "mx": {"code": "05", "abbr": "COA", "label": "Coahuila"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 151,
        "sector_id": "eolica",
        "mx": {"code": "26", "abbr": "SON", "label": "Sonora"},
        "us": {"code": "04", "abbr": "AZ", "label": "Arizona"},
    },
    {
        "rng_index": 152,
        "sector_id": "eolica",
        "mx": {"code": "28", "abbr": "TAM", "label": "Tamaulipas"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    # --- Frontera: agroindustrial ---
    {
        "rng_index": 160,
        "sector_id": "agroindustrial",
        "mx": {"code": "05", "abbr": "COA", "label": "Coahuila"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    {
        "rng_index": 161,
        "sector_id": "agroindustrial",
        "mx": {"code": "26", "abbr": "SON", "label": "Sonora"},
        "us": {"code": "04", "abbr": "AZ", "label": "Arizona"},
    },
    {
        "rng_index": 162,
        "sector_id": "agroindustrial",
        "mx": {"code": "19", "abbr": "NL", "label": "Nuevo León"},
        "us": {"code": "48", "abbr": "TX", "label": "Texas"},
    },
    # --- Manufactura: corredores no fronterizos adicionales ---
    {
        "rng_index": 170,
        "sector_id": "manufactura_total",
        "mx": {"code": "08", "abbr": "CHH", "label": "Chihuahua"},
        "us": {"code": "35", "abbr": "NM", "label": "New Mexico"},
    },
    {
        "rng_index": 171,
        "sector_id": "manufactura_total",
        "mx": {"code": "19", "abbr": "NL", "label": "Nuevo León"},
        "us": {"code": "26", "abbr": "MI", "label": "Michigan"},
    },
    {
        "rng_index": 172,
        "sector_id": "manufactura_total",
        "mx": {"code": "11", "abbr": "GUA", "label": "Guanajuato"},
        "us": {"code": "17", "abbr": "IL", "label": "Illinois"},
    },
    {
        "rng_index": 173,
        "sector_id": "manufactura_total",
        "mx": {"code": "14", "abbr": "JAL", "label": "Jalisco"},
        "us": {"code": "06", "abbr": "CA", "label": "California"},
    },
    # --- Agroindustrial: corredores adicionales ---
    {
        "rng_index": 180,
        "sector_id": "agroindustrial",
        "mx": {"code": "08", "abbr": "CHH", "label": "Chihuahua"},
        "us": {"code": "35", "abbr": "NM", "label": "New Mexico"},
    },
    {
        "rng_index": 181,
        "sector_id": "agroindustrial",
        "mx": {"code": "14", "abbr": "JAL", "label": "Jalisco"},
        "us": {"code": "06", "abbr": "CA", "label": "California"},
    },
]

# --- Pares MX ↔ Canadá ---
# Provincias canadienses con mayor integración industrial México-Canadá
# (automotriz, aeroespacial, agroindustrial, energía):
#   Quebec (QC)       — aeroespacial (Bombardier, CAE, corredor con Chihuahua)
#   Ontario (ON)      — automotriz (corredor con Nuevo León)
#   British Columbia (BC) — comercio Pacífico (Baja California)
#   Alberta (AB)      — energía/petroquímica (Tamaulipas)

MX_CA_NATIONAL_PAIRS: list[dict[str, Any]] = [
    {"rng_index": 200, "sector_id": "eolica"},
    {"rng_index": 201, "sector_id": "farmaceutica"},
    {"rng_index": 202, "sector_id": "aeroespacial"},
    {"rng_index": 203, "sector_id": "agroindustrial"},
    {"rng_index": 204, "sector_id": "petroquimica"},
    {"rng_index": 205, "sector_id": "manufactura_total"},
]

MX_CA_STATE_PAIRS: list[dict[str, Any]] = [
    {
        "rng_index": 210,
        "sector_id": "aeroespacial",
        "mx": {"code": "08", "abbr": "CHH", "label": "Chihuahua"},
        "ca": {"code": "24", "abbr": "QC", "label": "Quebec"},
    },
    {
        "rng_index": 211,
        "sector_id": "manufactura_total",
        "mx": {"code": "19", "abbr": "NL", "label": "Nuevo León"},
        "ca": {"code": "35", "abbr": "ON", "label": "Ontario"},
    },
    {
        "rng_index": 212,
        "sector_id": "manufactura_total",
        "mx": {"code": "02", "abbr": "BC", "label": "Baja California"},
        "ca": {"code": "59", "abbr": "BC", "label": "British Columbia"},
    },
    {
        "rng_index": 213,
        "sector_id": "petroquimica",
        "mx": {"code": "28", "abbr": "TAM", "label": "Tamaulipas"},
        "ca": {"code": "48", "abbr": "AB", "label": "Alberta"},
    },
]


def _load_sectors() -> list[dict[str, Any]]:
    with open(SECTORS_YAML, encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    return payload["sectors"]


def _child_rng(index: int) -> np.random.Generator:
    """RNG hijo determinístico derivado de `MOCK_RANDOM_SEED` + `index`, vía
    `SeedSequence.spawn`. Cada serie generada usa un índice distinto, así que
    la corrida completa es 100% reproducible a partir de una sola semilla
    documentada y agregar series nuevas no cambia las ya existentes."""
    child = np.random.SeedSequence(MOCK_RANDOM_SEED).spawn(index + 1)[index]
    return np.random.default_rng(child)


def _common_trend_pair(
    rng: np.random.Generator,
    n: int,
    *,
    drift: float,
    sigma_rw: float,
    phi: float,
    gamma: float,
    sigma_eps_a: float,
    sigma_eps_b: float,
    rho: float,
    seasonal_amplitude: float,
    base_level: float = 100.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Genera un par (a, b) con causalidad de Granger A -> B conocida por
    construcción Y cointegración genuina (tendencia estocástica compartida).

        rw[t]  = rw[t-1] + drift + xi[t]                       random walk con deriva (I(1) compartido)
        s_a[t] = phi * s_a[t-1] + eps_a[t]                     AR(1) estacionario
        s_b[t] = phi * s_b[t-1] + gamma * s_a[t-1] + eps_b[t]  A Granger-causa a B con rezago 1
        a[t]   = base_level + rw[t] + s_a[t] + estacional_a[t]
        b[t]   = base_level + rho*rw[t] + s_b[t] + estacional_b[t]

    Cointegración: la combinación lineal `b - rho*a` cancela `rw[t]` (la
    tendencia estocástica compartida) y queda
    `base_level*(1-rho) + s_b[t] - rho*s_a[t]`, que es estacionaria porque
    `s_a`/`s_b` lo son por construcción — (a, b) son I(1) individualmente
    pero cointegran con vector aproximado (1, -rho).

    B NO Granger-causa a A (`s_a` no depende de `s_b` en ningún rezago), así
    que la causalidad es unidireccional por diseño: se espera que el motor
    detecte "a causa b" como significativo y "b causa a" como no significativo.
    """
    xi = rng.normal(0.0, sigma_rw, size=n)
    rw = np.cumsum(drift + xi)

    eps_a = rng.normal(0.0, sigma_eps_a, size=n)
    eps_b = rng.normal(0.0, sigma_eps_b, size=n)

    s_a = np.zeros(n)
    s_b = np.zeros(n)
    for t in range(1, n):
        s_a[t] = phi * s_a[t - 1] + eps_a[t]
        s_b[t] = phi * s_b[t - 1] + gamma * s_a[t - 1] + eps_b[t]

    months = np.arange(n) % 12
    seasonal_a = seasonal_amplitude * np.sin(2 * np.pi * months / 12)
    seasonal_b = seasonal_amplitude * 0.7 * np.sin(2 * np.pi * months / 12 + 0.4)

    a = base_level + rw + s_a + seasonal_a
    b = base_level + rho * rw + s_b + seasonal_b
    return a, b


def _monthly_periods() -> pd.DatetimeIndex:
    periods = pd.period_range(start=MOCK_START_PERIOD, end=MOCK_END_PERIOD, freq="M")
    return pd.DatetimeIndex(periods.to_timestamp(how="end").normalize())


def _quarterly_periods() -> pd.DatetimeIndex:
    start_q = pd.Period(MOCK_START_PERIOD, freq="Q")
    end_q = pd.Period(MOCK_END_PERIOD, freq="Q")
    periods = pd.period_range(start=start_q, end=end_q, freq="Q")
    return pd.DatetimeIndex(periods.to_timestamp(how="end").normalize())


def _national_pair_frames(
    rng_index: int,
    sector: dict[str, Any],
    monthly_dates: pd.DatetimeIndex,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, Any]]:
    """Serie MX (EMIM mock) vs serie US (Industrial Production mock) a nivel
    nacional para un sector, ya normalizadas al esquema tidy."""
    rng = _child_rng(rng_index)
    n = len(monthly_dates)
    mx_values, us_values = _common_trend_pair(
        rng,
        n,
        drift=DGP_DRIFT,
        sigma_rw=DGP_SIGMA_RW,
        phi=DGP_PHI,
        gamma=DGP_GAMMA,
        sigma_eps_a=DGP_SIGMA_EPS_A,
        sigma_eps_b=DGP_SIGMA_EPS_B,
        rho=DGP_RHO,
        seasonal_amplitude=DGP_SEASONAL_AMPLITUDE,
    )

    sector_id = sector["id"]
    scian_code = sector["scian_codes"][0] if sector.get("scian_codes") else None
    naics_code = sector["naics_codes"][0] if sector.get("naics_codes") else None

    mx_series_id = f"mx-nac_{sector_id}_emim"
    us_series_id = f"us-nac_{sector_id}_ip"

    last_date = monthly_dates[-1]
    mx_vintage = (last_date + pd.Timedelta(days=MX_NATIONAL_LAG_DAYS)).date().isoformat()
    us_vintage = (last_date + pd.Timedelta(days=US_NATIONAL_LAG_DAYS)).date().isoformat()

    mx_meta = SeriesMeta(
        series_id=mx_series_id,
        source=MX_NATIONAL_SOURCE,
        country="MX",
        region_code="NAC",
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units=MX_NATIONAL_UNITS,
        proxy_type="output_index",
        publication_lag_days=MX_NATIONAL_LAG_DAYS,
        vintage_date=mx_vintage,
        scian_code=scian_code,
        naics_code=naics_code,
    )
    us_meta = SeriesMeta(
        series_id=us_series_id,
        source=US_NATIONAL_SOURCE,
        country="US",
        region_code="NAC",
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units=US_NATIONAL_UNITS,
        proxy_type="output_index",
        publication_lag_days=US_NATIONAL_LAG_DAYS,
        vintage_date=us_vintage,
        scian_code=scian_code,
        naics_code=naics_code,
    )

    mx_tidy = normalize_series(list(zip(monthly_dates, mx_values)), mx_meta)
    us_tidy = normalize_series(list(zip(monthly_dates, us_values)), us_meta)

    label_en = sector.get("label_en", sector["label"])
    labels = {
        mx_series_id: f"Producción manufacturera - {sector['label']} (México, nacional)",
        us_series_id: f"Industrial Production Index - {label_en} (US, national)",
    }
    pair_def = {
        "pair_id": f"mx-nac_{sector_id}__us-nac_{sector_id}",
        "level": "nacional",
        "sector_id": sector_id,
        "series_a": mx_series_id,
        "series_b": us_series_id,
    }
    return {mx_series_id: mx_tidy, us_series_id: us_tidy}, labels, pair_def


def _state_pair_frames(
    rng_index: int,
    sector: dict[str, Any],
    quarterly_dates: pd.DatetimeIndex,
    monthly_dates: pd.DatetimeIndex,
    *,
    mx_region_code: str = CHIHUAHUA_REGION_CODE,
    mx_abbr: str = "CHH",
    mx_state_label: str = "Chihuahua",
    us_region_code: str = TEXAS_REGION_CODE,
    us_abbr: str = "TX",
    us_state_label: str = "Texas",
    us_series_disambiguator: str | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, Any]]:
    """Serie MX ITAEE (nivel estatal, trimestral, `output_index`) vs serie US
    BLS (nivel estatal, mensual, `labor_input`) para un sector y un par de
    estados MX/US dados. El BLS mensual se construye a partir del mismo valor
    trimestral latente que el ITAEE + ruido idiosincrático mensual, para que
    `processing.align` tenga que remuestrear mensual->trimestral por promedio
    antes de correr el motor, igual que pasaría con datos reales.

    Por defecto reproduce exactamente el par original Chihuahua/aeroespacial
    vs Texas (mismos `region_code`/abrreviaturas), para no alterar los
    identificadores ya publicados de ese par al generalizar la función.

    `us_series_disambiguator` evita colisiones de `series_id` cuando el mismo
    estado de EEUU (p. ej. Texas) se compara contra VARIOS estados mexicanos
    distintos para el mismo sector (Coahuila, Nuevo León, Tamaulipas y
    Chihuahua todos contra Texas): sin esto, `us-tx_{sector}_bls` se
    generaría idéntico para los 4 pares y `series_lookup` (un dict keyed por
    series_id) se sobreescribiría en silencio, dejando 3 de los 4 pares
    corriendo el motor econométrico contra los valores sintéticos de OTRO
    par (el DGP común-tendencia/Granger de cada par dejaría de corresponder
    a esa serie). Ver `ADDITIONAL_STATE_PAIRS` más abajo, donde siempre se
    pasa el abbr del estado mexicano como disambiguador."""
    rng = _child_rng(rng_index)
    n_q = len(quarterly_dates)
    if len(monthly_dates) != n_q * 3:
        raise ValueError("El rango mensual y trimestral del mock deben cubrir exactamente los mismos meses")

    mx_q_values, us_latent_q = _common_trend_pair(
        rng,
        n_q,
        drift=STATE_DGP_DRIFT,
        sigma_rw=STATE_DGP_SIGMA_RW,
        phi=STATE_DGP_PHI,
        gamma=STATE_DGP_GAMMA,
        sigma_eps_a=STATE_DGP_SIGMA_EPS_A,
        sigma_eps_b=STATE_DGP_SIGMA_EPS_B,
        rho=STATE_DGP_RHO,
        # El ITAEE agregado trimestral ya no exhibe el patrón estacional
        # mensual crudo; se deja en 0 a este nivel de agregación.
        seasonal_amplitude=0.0,
    )
    us_monthly_values = np.repeat(us_latent_q, 3) + rng.normal(0.0, STATE_MONTHLY_NOISE_SIGMA, size=n_q * 3)

    sector_id = sector["id"]
    scian_code = sector["scian_codes"][0]
    naics_code = sector["naics_codes"][0]
    label_en = sector.get("label_en", sector["label"])

    mx_abbr_lower = mx_abbr.lower()
    us_abbr_lower = us_abbr.lower()
    mx_series_id = f"mx-{mx_abbr_lower}_{sector_id}_itaee"
    if us_series_disambiguator:
        us_series_id = f"us-{us_abbr_lower}_{sector_id}_{us_series_disambiguator.lower()}_bls"
    else:
        us_series_id = f"us-{us_abbr_lower}_{sector_id}_bls"

    mx_vintage = (quarterly_dates[-1] + pd.Timedelta(days=MX_STATE_LAG_DAYS)).date().isoformat()
    us_vintage = (monthly_dates[-1] + pd.Timedelta(days=US_STATE_LAG_DAYS)).date().isoformat()

    mx_meta = SeriesMeta(
        series_id=mx_series_id,
        source=MX_STATE_SOURCE,
        country="MX",
        region_code=mx_region_code,
        sector_id=sector_id,
        frequency="quarterly",
        seasonal_adjustment="nsa",
        units=MX_STATE_UNITS,
        proxy_type="output_index",
        publication_lag_days=MX_STATE_LAG_DAYS,
        vintage_date=mx_vintage,
        scian_code=scian_code,
        naics_code=naics_code,
    )
    us_meta = SeriesMeta(
        series_id=us_series_id,
        source=US_STATE_SOURCE,
        country="US",
        region_code=us_region_code,
        sector_id=sector_id,
        frequency="monthly",
        seasonal_adjustment="nsa",
        units=US_STATE_UNITS,
        proxy_type="labor_input",
        publication_lag_days=US_STATE_LAG_DAYS,
        vintage_date=us_vintage,
        scian_code=scian_code,
        naics_code=naics_code,
    )

    mx_tidy = normalize_series(list(zip(quarterly_dates, mx_q_values)), mx_meta)
    us_tidy = normalize_series(list(zip(monthly_dates, us_monthly_values)), us_meta)

    labels = {
        mx_series_id: f"ITAEE - Actividad industrial ({mx_state_label})",
        us_series_id: f"Empleo manufacturero - {label_en} ({us_state_label})",
    }
    pair_def = {
        "pair_id": f"mx-{mx_abbr_lower}_{sector_id}__us-{us_abbr_lower}_{sector_id}",
        "level": "estatal",
        "sector_id": sector_id,
        "series_a": mx_series_id,
        "series_b": us_series_id,
    }
    return {mx_series_id: mx_tidy, us_series_id: us_tidy}, labels, pair_def


def _national_pair_frames_ca(
    rng_index: int,
    sector: dict[str, Any],
    monthly_dates: pd.DatetimeIndex,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, Any]]:
    """Serie MX (EMIM mock) vs serie CA (Statistics Canada mock) nacional."""
    rng = _child_rng(rng_index)
    n = len(monthly_dates)
    mx_values, ca_values = _common_trend_pair(
        rng, n, drift=DGP_DRIFT, sigma_rw=DGP_SIGMA_RW, phi=DGP_PHI,
        gamma=DGP_GAMMA, sigma_eps_a=DGP_SIGMA_EPS_A, sigma_eps_b=DGP_SIGMA_EPS_B,
        rho=DGP_RHO, seasonal_amplitude=DGP_SEASONAL_AMPLITUDE,
    )
    sector_id = sector["id"]
    scian_code = sector["scian_codes"][0] if sector.get("scian_codes") else None
    naics_code = sector["naics_codes"][0] if sector.get("naics_codes") else None

    mx_series_id = f"mx-nac_{sector_id}_emim"
    ca_series_id = f"ca-nac_{sector_id}_sc"

    last_date = monthly_dates[-1]
    mx_vintage = (last_date + pd.Timedelta(days=MX_NATIONAL_LAG_DAYS)).date().isoformat()
    ca_vintage = (last_date + pd.Timedelta(days=CA_NATIONAL_LAG_DAYS)).date().isoformat()

    mx_meta = SeriesMeta(
        series_id=mx_series_id, source=MX_NATIONAL_SOURCE, country="MX",
        region_code="NAC", sector_id=sector_id, frequency="monthly",
        seasonal_adjustment="nsa", units=MX_NATIONAL_UNITS, proxy_type="output_index",
        publication_lag_days=MX_NATIONAL_LAG_DAYS, vintage_date=mx_vintage,
        scian_code=scian_code, naics_code=naics_code,
    )
    ca_meta = SeriesMeta(
        series_id=ca_series_id, source=CA_NATIONAL_SOURCE, country="CA",
        region_code="NAC", sector_id=sector_id, frequency="monthly",
        seasonal_adjustment="nsa", units=CA_NATIONAL_UNITS, proxy_type="output_index",
        publication_lag_days=CA_NATIONAL_LAG_DAYS, vintage_date=ca_vintage,
        scian_code=scian_code, naics_code=naics_code,
    )

    mx_tidy = normalize_series(list(zip(monthly_dates, mx_values)), mx_meta)
    ca_tidy = normalize_series(list(zip(monthly_dates, ca_values)), ca_meta)

    label_en = sector.get("label_en", sector["label"])
    labels = {
        mx_series_id: f"Producción manufacturera - {sector['label']} (México, nacional)",
        ca_series_id: f"GDP by industry - {label_en} (Canada, national)",
    }
    pair_def = {
        "pair_id": f"mx-nac_{sector_id}__ca-nac_{sector_id}",
        "level": "nacional",
        "sector_id": sector_id,
        "series_a": mx_series_id,
        "series_b": ca_series_id,
    }
    return {mx_series_id: mx_tidy, ca_series_id: ca_tidy}, labels, pair_def


def _state_pair_frames_ca(
    rng_index: int,
    sector: dict[str, Any],
    quarterly_dates: pd.DatetimeIndex,
    monthly_dates: pd.DatetimeIndex,
    *,
    mx_region_code: str,
    mx_abbr: str,
    mx_state_label: str,
    ca_region_code: str,
    ca_abbr: str,
    ca_state_label: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, Any]]:
    """Serie MX ITAEE (trimestral, output_index) vs serie CA (monthly, output_index)."""
    rng = _child_rng(rng_index)
    n_q = len(quarterly_dates)
    if len(monthly_dates) != n_q * 3:
        raise ValueError("El rango mensual y trimestral del mock deben cubrir exactamente los mismos meses")

    mx_q_values, ca_latent_q = _common_trend_pair(
        rng, n_q, drift=STATE_DGP_DRIFT, sigma_rw=STATE_DGP_SIGMA_RW,
        phi=STATE_DGP_PHI, gamma=STATE_DGP_GAMMA,
        sigma_eps_a=STATE_DGP_SIGMA_EPS_A, sigma_eps_b=STATE_DGP_SIGMA_EPS_B,
        rho=STATE_DGP_RHO, seasonal_amplitude=0.0,
    )
    ca_monthly_values = np.repeat(ca_latent_q, 3) + rng.normal(0.0, STATE_MONTHLY_NOISE_SIGMA, size=n_q * 3)

    sector_id = sector["id"]
    scian_code = sector["scian_codes"][0]
    naics_code = sector["naics_codes"][0]

    mx_abbr_lower = mx_abbr.lower()
    ca_abbr_lower = ca_abbr.lower()
    mx_series_id = f"mx-{mx_abbr_lower}_{sector_id}_itaee"
    ca_series_id = f"ca-{ca_abbr_lower}_{sector_id}_sc"

    mx_vintage = (quarterly_dates[-1] + pd.Timedelta(days=MX_STATE_LAG_DAYS)).date().isoformat()
    ca_vintage = (monthly_dates[-1] + pd.Timedelta(days=CA_STATE_LAG_DAYS)).date().isoformat()

    mx_meta = SeriesMeta(
        series_id=mx_series_id, source=MX_STATE_SOURCE, country="MX",
        region_code=mx_region_code, sector_id=sector_id, frequency="quarterly",
        seasonal_adjustment="nsa", units=MX_STATE_UNITS, proxy_type="output_index",
        publication_lag_days=MX_STATE_LAG_DAYS, vintage_date=mx_vintage,
        scian_code=scian_code, naics_code=naics_code,
    )
    ca_meta = SeriesMeta(
        series_id=ca_series_id, source=CA_STATE_SOURCE, country="CA",
        region_code=ca_region_code, sector_id=sector_id, frequency="monthly",
        seasonal_adjustment="nsa", units=CA_STATE_UNITS, proxy_type="output_index",
        publication_lag_days=CA_STATE_LAG_DAYS, vintage_date=ca_vintage,
        scian_code=scian_code, naics_code=naics_code,
    )

    mx_tidy = normalize_series(list(zip(quarterly_dates, mx_q_values)), mx_meta)
    ca_tidy = normalize_series(list(zip(monthly_dates, ca_monthly_values)), ca_meta)

    label_en = sector.get("label_en", sector["label"])
    labels = {
        mx_series_id: f"ITAEE - Actividad industrial ({mx_state_label})",
        ca_series_id: f"Manufacturing sales - {label_en} ({ca_state_label})",
    }
    pair_def = {
        "pair_id": f"mx-{mx_abbr_lower}_{sector_id}__ca-{ca_abbr_lower}_{sector_id}",
        "level": "estatal",
        "sector_id": sector_id,
        "series_a": mx_series_id,
        "series_b": ca_series_id,
    }
    return {mx_series_id: mx_tidy, ca_series_id: ca_tidy}, labels, pair_def


def main() -> dict[str, Any]:
    logger.info(
        "Generando datos mock (semilla=%s, rango=%s..%s)", MOCK_RANDOM_SEED, MOCK_START_PERIOD, MOCK_END_PERIOD
    )

    sectors = _load_sectors()
    monthly_dates = _monthly_periods()
    quarterly_dates = _quarterly_periods()
    logger.info("n_obs mensual=%d, n_obs trimestral=%d", len(monthly_dates), len(quarterly_dates))

    series_lookup: dict[str, pd.DataFrame] = {}
    series_labels: dict[str, str] = {}
    pair_defs: list[dict[str, Any]] = []

    for idx, sector in enumerate(sectors):
        frames, labels, pair_def = _national_pair_frames(idx, sector, monthly_dates)
        series_lookup.update(frames)
        series_labels.update(labels)
        pair_defs.append(pair_def)

        if sector["id"] == "aeroespacial":
            state_frames, state_labels, state_pair_def = _state_pair_frames(
                idx + len(sectors), sector, quarterly_dates, monthly_dates
            )
            series_lookup.update(state_frames)
            series_labels.update(state_labels)
            pair_defs.append(state_pair_def)

    sectors_by_id = {s["id"]: s for s in sectors}

    logger.info("Generando %d pares estatales adicionales (frontera + corredores)...", len(ADDITIONAL_STATE_PAIRS))
    for spec in ADDITIONAL_STATE_PAIRS:
        sector = sectors_by_id[spec["sector_id"]]
        mx = spec["mx"]
        us = spec["us"]
        state_frames, state_labels, state_pair_def = _state_pair_frames(
            spec["rng_index"],
            sector,
            quarterly_dates,
            monthly_dates,
            mx_region_code=mx["code"],
            mx_abbr=mx["abbr"],
            mx_state_label=mx["label"],
            us_region_code=us["code"],
            us_abbr=us["abbr"],
            us_state_label=us["label"],
            # Siempre se disambigua con el abbr MX: varios pares nuevos
            # comparten el mismo estado de EEUU (Texas) para el mismo sector
            # (ver docstring de `_state_pair_frames`).
            us_series_disambiguator=mx["abbr"],
        )
        series_lookup.update(state_frames)
        series_labels.update(state_labels)
        pair_defs.append(state_pair_def)

    logger.info("Generando %d pares México-Canadá...", len(MX_CA_NATIONAL_PAIRS) + len(MX_CA_STATE_PAIRS))
    for spec in MX_CA_NATIONAL_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        frames, labels, pair_def = _national_pair_frames_ca(spec["rng_index"], sector, monthly_dates)
        series_lookup.update(frames)
        series_labels.update(labels)
        pair_defs.append(pair_def)

    for spec in MX_CA_STATE_PAIRS:
        sector = sectors_by_id.get(spec["sector_id"])
        if not sector:
            continue
        mx = spec["mx"]
        ca = spec["ca"]
        state_frames, state_labels, state_pair_def = _state_pair_frames_ca(
            spec["rng_index"], sector, quarterly_dates, monthly_dates,
            mx_region_code=mx["code"], mx_abbr=mx["abbr"], mx_state_label=mx["label"],
            ca_region_code=ca["code"], ca_abbr=ca["abbr"], ca_state_label=ca["label"],
        )
        series_lookup.update(state_frames)
        series_labels.update(state_labels)
        pair_defs.append(state_pair_def)

    logger.info("Corriendo motor econométrico sobre %d pares...", len(pair_defs))
    results = run_all(pair_defs, series_lookup, sectors_by_id)

    logger.info("Exportando manifest/series/results a data/ ...")
    manifest = export_all(
        sectors=sectors,
        series_lookup=series_lookup,
        series_labels=series_labels,
        pair_defs=pair_defs,
        results=results,
        mode="mock",
        refresh_cadence="trimestral",
    )
    logger.info(
        "Listo: %d sectores, %d series, %d pares.",
        len(sectors),
        len(series_lookup),
        len(pair_defs),
    )
    return manifest


if __name__ == "__main__":
    main()
