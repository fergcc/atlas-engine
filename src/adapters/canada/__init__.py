"""
Statistics Canada Adapter for Canada.

Provides national and provincial industrial production data using:
  - Statistics Canada WDS (monthly national GDP by NAICS)
  - Manufacturing sales by province (monthly)
  - Labour Force Survey employment by province (monthly)

Covers 10 provinces + 3 territories.
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

CA_PROVINCES = [
    ("10", "Newfoundland and Labrador", "NL"),
    ("11", "Prince Edward Island", "PE"),
    ("12", "Nova Scotia", "NS"),
    ("13", "New Brunswick", "NB"),
    ("24", "Quebec", "QC"),
    ("35", "Ontario", "ON"),
    ("46", "Manitoba", "MB"),
    ("47", "Saskatchewan", "SK"),
    ("48", "Alberta", "AB"),
    ("59", "British Columbia", "BC"),
    ("60", "Yukon", "YT"),
    ("61", "Northwest Territories", "NT"),
    ("62", "Nunavut", "NU"),
]

CA_NATIONAL = "01"

CANADA_PIDS = {
    "national_monthly_gdp": 36100434,
    "manufacturing_sales": 16100048,
    "labour_force": 14100287,
}


class CanadaAdapter(StatisticalOfficeAdapter):

    country = "CA"
    country_name = "Canadá"
    country_name_en = "Canada"

    def health_check(self) -> bool:
        try:
            import requests
            resp = requests.get(
                "https://www150.statcan.gc.ca/t1/wds/rest/getAllCubesListLite",
                timeout=10,
            )
            return resp.status_code == 200
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
    ) -> SeriesBundle:
        is_national = region_code in ("NAC", CA_NATIONAL)

        if is_national:
            return self._fetch_national_manufacturing(
                sector_id, scian_code=scian_code, naics_code=naics_code
            )
        else:
            return self._fetch_provincial_manufacturing(
                sector_id, region_code, scian_code=scian_code, naics_code=naics_code
            )

    def _fetch_national_manufacturing(
        self,
        sector_id: str,
        scian_code: str | None = None,
        naics_code: str | None = None,
    ) -> SeriesBundle:
        from src.services.ingestion.statcan import fetch_cube_coord_data
        from src.services.processing.normalize import SeriesMeta, normalize_series

        pid = CANADA_PIDS["national_monthly_gdp"]
        coordinate = "1.1.1.1.0.0.0.0.0.0"

        raw = fetch_cube_coord_data(pid, coordinate, latest_n=60)
        observations = [
            (o["refPer"], o["value"]) for o in raw if o.get("value") is not None
        ]

        if not observations:
            return self._empty_bundle(sector_id, "nac", "statcan")

        engine_series_id = self.get_series_id(sector_id, "nac", "sc")
        last_date = pd.Timestamp(max(o[0] for o in observations))
        vintage = (last_date + timedelta(days=60)).date().isoformat()

        meta = SeriesMeta(
            series_id=engine_series_id,
            source=f"Statistics Canada — Monthly GDP (PID {pid})",
            country="CA",
            region_code="NAC",
            sector_id=sector_id,
            frequency="monthly",
            seasonal_adjustment="nsa",
            units="Chained (2017) dollars",
            proxy_type="output_index",
            publication_lag_days=60,
            vintage_date=vintage,
            scian_code=scian_code,
            naics_code=naics_code,
        )

        tidy = normalize_series(observations, meta)
        label = f"GDP by industry — {sector_id} (Canada, national)"

        return SeriesBundle(series_id=engine_series_id, tidy=tidy, label=label)

    def _fetch_provincial_manufacturing(
        self,
        sector_id: str,
        region_code: str,
        scian_code: str | None = None,
        naics_code: str | None = None,
    ) -> SeriesBundle:
        from src.services.ingestion.statcan import fetch_cube_coord_data
        from src.services.processing.normalize import SeriesMeta, normalize_series

        pid = CANADA_PIDS["manufacturing_sales"]
        geo_idx = self._province_index(region_code)
        coordinate = f"1.{geo_idx}.1.1.0.0.0.0.0.0"

        raw = fetch_cube_coord_data(pid, coordinate, latest_n=60)
        observations = [
            (o["refPer"], o["value"]) for o in raw if o.get("value") is not None
        ]

        if not observations:
            return self._empty_bundle(sector_id, region_code.lower(), "statcan")

        engine_series_id = self.get_series_id(sector_id, region_code.lower(), "sc")
        last_date = pd.Timestamp(max(o[0] for o in observations))
        vintage = (last_date + timedelta(days=60)).date().isoformat()

        region_name = next(
            (p[1] for p in CA_PROVINCES if p[0] == region_code), region_code
        )

        meta = SeriesMeta(
            series_id=engine_series_id,
            source=f"Statistics Canada — Manufacturing sales ({region_name})",
            country="CA",
            region_code=region_code,
            sector_id=sector_id,
            frequency="monthly",
            seasonal_adjustment="nsa",
            units="Thousands of dollars",
            proxy_type="output_index",
            publication_lag_days=60,
            vintage_date=vintage,
            scian_code=scian_code,
            naics_code=naics_code,
        )

        tidy = normalize_series(observations, meta)
        label = f"Manufacturing sales — {sector_id} ({region_name})"

        return SeriesBundle(series_id=engine_series_id, tidy=tidy, label=label)

    def _empty_bundle(
        self, sector_id: str, region_code: str, suffix: str
    ) -> SeriesBundle:
        series_id = self.get_series_id(sector_id, region_code, suffix)
        from src.services.processing.normalize import SeriesMeta, normalize_series
        meta = SeriesMeta(
            series_id=series_id,
            source=f"Statistics Canada (no data)",
            country="CA",
            region_code=region_code,
            sector_id=sector_id,
            frequency="monthly",
            seasonal_adjustment="nsa",
            units="N/A",
            proxy_type="output_index",
            publication_lag_days=60,
            vintage_date=date.today().isoformat(),
        )
        tidy = normalize_series(
            [(date.today().isoformat(), 0)], meta
        )
        return SeriesBundle(series_id=series_id, tidy=tidy, label=f"No data — {sector_id}")

    def _province_index(self, code: str) -> int:
        for i, (c, _, _) in enumerate(CA_PROVINCES, start=1):
            if c == code:
                return i
        return 1

    def list_indicators(self) -> list[IndicatorInfo]:
        return [
            IndicatorInfo(
                id="statcan_monthly_gdp",
                name="GDP mensual por industria (nacional)",
                name_en="Monthly GDP by industry (national)",
                theme="industrial_concentration",
                frequency="monthly",
                unit="Chained (2017) dollars",
                proxy_type="output_index",
                geographic_granularity="national",
            ),
            IndicatorInfo(
                id="statcan_manufacturing_sales",
                name="Ventas manufactureras por provincia",
                name_en="Manufacturing sales by province",
                theme="industrial_concentration",
                frequency="monthly",
                unit="Thousands of dollars",
                proxy_type="output_index",
                geographic_granularity="provincial",
            ),
            IndicatorInfo(
                id="statcan_labour_force",
                name="Encuesta de fuerza laboral por provincia",
                name_en="Labour Force Survey by province",
                theme="employment",
                frequency="monthly",
                unit="Thousands of persons",
                proxy_type="labor_input",
                geographic_granularity="provincial",
            ),
        ]

    def list_regions(self, level: str = "state") -> list[RegionInfo]:
        if level in ("state", "province"):
            return [
                RegionInfo(code=c, name=n, name_en=n)
                for c, n, a in CA_PROVINCES
            ]
        return []

    def get_default_proxy_type(self) -> str:
        return "output_index"
