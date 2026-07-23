"""
United States Adapter — wraps FRED (national), BLS (state employment), and BEA (state GDP).

Provides subnational industrial data for US states using:
  - FRED Industrial Production (national, monthly, output_index)
  - BLS CES employment (state-level, monthly, labor_input)
  - BEA GDP by state (state-level, quarterly, output_index)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from src.adapters.base import (
    IndicatorInfo,
    RegionInfo,
    SeriesBundle,
    StatisticalOfficeAdapter,
)

logger = logging.getLogger(__name__)

FRED_IP_MAP = {
    "eolica": "IPG333N",
    "farmaceutica": "IPG3254N",
    "aeroespacial": "IPG3364N",
    "agroindustrial": "IPN3118N",
    "petroquimica": "IPG3251N",
    "manufactura_total": "INDPRO",
}

BLS_MANUFACTURING_CODE = "30000000"
BLS_SECTOR_CODES = {
    "aeroespacial": "31336400",
    "farmaceutica": "32325400",
    "eolica": "31003300",
    "agroindustrial": "32311800",
    "petroquimica": "32325100",
    "manufactura_total": "30000000",
}

BLS_SECTOR_BASE = {
    "aeroespacial": "31336400",
    "farmaceutica": "32325400",
    "manufactura_total": "30000000",
}


class USAdapter(StatisticalOfficeAdapter):

    country = "US"
    country_name = "Estados Unidos"
    country_name_en = "United States"

    def health_check(self) -> bool:
        try:
            from src.services.ingestion.fred import _get_api_key
            _get_api_key()
            return True
        except Exception:
            return False

    def fetch_series(
        self,
        sector_id: str,
        region_code: str = "NAC",
        *,
        scian_code: str | None = None,
        naics_code: str | None = None,
        frequency: str | None = None,
        indicator_id: str | None = None,
    ) -> SeriesBundle:
        """`indicator_id` picks among this adapter's state-level indicators
        when there's more than one (see list_indicators()) — "bea_gdp_state"
        routes to BEA; anything else (including the default, None) keeps the
        original BLS employment series so existing behavior is unchanged."""
        is_national = region_code == "NAC"

        if is_national:
            return self._fetch_national(sector_id, scian_code=scian_code, naics_code=naics_code)
        if indicator_id == "bea_gdp_state":
            return self._fetch_bea_state(
                sector_id, region_code, scian_code=scian_code, naics_code=naics_code
            )
        return self._fetch_state(
            sector_id, region_code, scian_code=scian_code, naics_code=naics_code
        )

    def _fetch_national(
        self, sector_id: str, scian_code: str | None = None, naics_code: str | None = None
    ) -> SeriesBundle:
        from src.services.ingestion.fred import SOURCE_NAME, fetch_series
        from src.services.processing.normalize import SeriesMeta, normalize_series

        series_id = FRED_IP_MAP.get(sector_id, FRED_IP_MAP["manufactura_total"])
        raw = fetch_series(series_id)
        observations = [(o["date"], o["value"]) for o in raw if o.get("value") not in (".", "NaN", None)]

        if not observations:
            raise ValueError(f"FRED: sin observaciones para {series_id}")

        engine_series_id = self.get_series_id(sector_id, "nac", "ip")
        last_date = pd.Timestamp(max(o[0] for o in observations))
        vintage = (last_date + timedelta(days=30)).date().isoformat()

        meta = SeriesMeta(
            series_id=engine_series_id,
            source=f"FRED - Industrial Production ({series_id})",
            country="US",
            region_code="NAC",
            sector_id=sector_id,
            frequency="monthly",
            seasonal_adjustment="nsa",
            units="Index 2017=100",
            proxy_type="output_index",
            publication_lag_days=30,
            vintage_date=vintage,
            scian_code=scian_code,
            naics_code=naics_code,
        )

        tidy = normalize_series(observations, meta)
        label = f"Industrial Production Index ({sector_id}, US national)"

        return SeriesBundle(series_id=engine_series_id, tidy=tidy, label=label)

    def _fetch_state(
        self,
        sector_id: str,
        region_code: str,
        scian_code: str | None = None,
        naics_code: str | None = None,
    ) -> SeriesBundle:
        from src.services.ingestion.bls import fetch_timeseries
        from src.services.processing.normalize import SeriesMeta, normalize_series

        industry_code = BLS_SECTOR_BASE.get(
            sector_id, BLS_SECTOR_BASE.get("manufactura_total", "30000000")
        )

        bls_series = f"SMU{region_code}00000{industry_code}01"
        raw = fetch_timeseries([bls_series])

        observations = []
        for series_data in raw:
            for obs in series_data.get("data", []):
                year = obs.get("year", "")
                period = obs.get("period", "")
                value = obs.get("value", "")
                if year and period and value:
                    period_clean = period.replace("M", "")
                    date_str = f"{year}-{period_clean.zfill(2)}"
                    observations.append((date_str, value))

        if not observations:
            raise ValueError(
                f"BLS: sin observaciones para sector={sector_id} region={region_code}"
            )

        engine_series_id = self.get_series_id(sector_id, region_code, "bls")
        last_date = pd.Timestamp(max(o[0] for o in observations))
        vintage = (last_date + timedelta(days=60)).date().isoformat()

        meta = SeriesMeta(
            series_id=engine_series_id,
            source=f"BLS - State Employment ({bls_series})",
            country="US",
            region_code=region_code,
            sector_id=sector_id,
            frequency="monthly",
            seasonal_adjustment="nsa",
            units="Thousands of employees",
            proxy_type="labor_input",
            publication_lag_days=60,
            vintage_date=vintage,
            scian_code=scian_code,
            naics_code=naics_code,
        )

        tidy = normalize_series(observations, meta)
        label = f"Manufacturing employment ({sector_id}, {region_code})"

        return SeriesBundle(series_id=engine_series_id, tidy=tidy, label=label)

    def _fetch_bea_state(
        self,
        sector_id: str,
        region_code: str,
        scian_code: str | None = None,
        naics_code: str | None = None,
    ) -> SeriesBundle:
        """BEA Regional GDP by state (SQGDP1, all-industry total) — was
        advertised in list_indicators() as "bea_gdp_state" but had no fetch
        path until now; fetch_regional_gdp() and BEA_API_KEY already existed
        in bea.py/config.py, just never called from this adapter."""
        from src.services.ingestion.bea import fetch_regional_gdp
        from src.services.processing.normalize import SeriesMeta, normalize_series

        data = fetch_regional_gdp(geo_fips=region_code)

        observations = []
        for row in data:
            period = row.get("TimePeriod")
            value = row.get("DataValue")
            if not period or value in (None, "", "(NA)", "(D)"):
                continue
            try:
                value_f = float(str(value).replace(",", ""))
            except (ValueError, TypeError):
                continue
            date_str = _bea_period_to_month(period)
            if date_str:
                observations.append((date_str, value_f))

        if not observations:
            raise ValueError(f"BEA: sin observaciones para region={region_code}")

        engine_series_id = self.get_series_id(sector_id, region_code, "bea")
        last_date = pd.Timestamp(max(o[0] for o in observations))
        vintage = (last_date + timedelta(days=90)).date().isoformat()

        meta = SeriesMeta(
            series_id=engine_series_id,
            source="BEA - Regional GDP by State (SQGDP1)",
            country="US",
            region_code=region_code,
            sector_id=sector_id,
            frequency="quarterly",
            seasonal_adjustment="nsa",
            units="Millions of current dollars",
            proxy_type="output_index",
            publication_lag_days=90,
            vintage_date=vintage,
            scian_code=scian_code,
            naics_code=naics_code,
        )

        tidy = normalize_series(observations, meta)
        label = f"GDP by state ({sector_id}, {region_code}, BEA)"

        return SeriesBundle(series_id=engine_series_id, tidy=tidy, label=label)

    def list_indicators(self) -> list[IndicatorInfo]:
        return [
            IndicatorInfo(
                id="fred_ip_national",
                name="FRED Industrial Production Index (national)",
                name_en="FRED Industrial Production Index (national)",
                theme="industrial_concentration",
                frequency="monthly",
                unit="Index 2017=100",
                proxy_type="output_index",
                geographic_granularity="national",
            ),
            IndicatorInfo(
                id="bls_ces_state",
                name="BLS Current Employment Statistics (state)",
                name_en="BLS Current Employment Statistics (state)",
                theme="industrial_concentration",
                frequency="monthly",
                unit="Thousands of employees",
                proxy_type="labor_input",
                geographic_granularity="state",
            ),
            IndicatorInfo(
                id="bea_gdp_state",
                name="BEA GDP by State (quarterly)",
                name_en="BEA GDP by State (quarterly)",
                theme="industrial_concentration",
                frequency="quarterly",
                unit="Millions of current dollars",
                proxy_type="output_index",
                geographic_granularity="state",
            ),
        ]

    def list_regions(self, level: str = "state") -> list[RegionInfo]:
        if level == "state":
            import yaml
            from src.config import REGION_REGISTRY_YAML
            with open(REGION_REGISTRY_YAML, encoding="utf-8") as fh:
                registry = yaml.safe_load(fh)
            return [
                RegionInfo(code=s["fips"], name=s["name"])
                for s in registry.get("us_states", [])
            ]
        return []

    def get_default_proxy_type(self) -> str:
        return "output_index"


def _bea_period_to_month(period: str) -> str | None:
    """Convert a BEA `TimePeriod` value ("2021Q1" or "2021") to a "YYYY-MM"
    string usable by normalize_series. Returns None for unrecognized formats."""
    import re

    m = re.match(r"^(\d{4})Q([1-4])$", period)
    if m:
        year, quarter = m.groups()
        month = {"1": "01", "2": "04", "3": "07", "4": "10"}[quarter]
        return f"{year}-{month}"
    if re.match(r"^\d{4}$", period):
        return f"{period}-01"
    return None
