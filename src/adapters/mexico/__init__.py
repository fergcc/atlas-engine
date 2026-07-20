"""
Mexico INEGI Adapter — wraps INEGI BIE API + Banxico.

Provides subnational industrial production data for Mexican states
using IMAI (national) and ITAEE (state-level quarterly).
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
from src.config import settings

logger = logging.getLogger(__name__)

INEGI_NATIONAL_IMAI_MAP = {
    "eolica": "736491",
    "farmaceutica": "736462",
    "aeroespacial": "736515",
    "agroindustrial": "736427",
    "petroquimica": "736459",
    "manufactura_total": "736407",
}

INEGI_STATE_ITAEE_MANUFACTURING = "741651"
INEGI_STATE_ITAEE_TOTAL = "741177"

KNOWN_MISSING_ITAEE_STATES = {"04", "05", "07", "19", "28", "30"}


class MexicoINEGIAdapter(StatisticalOfficeAdapter):

    country = "MX"
    country_name = "México"
    country_name_en = "Mexico"

    def health_check(self) -> bool:
        try:
            from src.services.ingestion.inegi import _get_token
            _get_token()
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
    ) -> SeriesBundle:
        from src.services.ingestion.inegi import (
            SOURCE_NAME,
            COYUNTURA_SOURCE_DB,
            NATIONAL_AREA_CODE,
            fetch_indicator,
        )
        from src.services.processing.normalize import SeriesMeta, normalize_series

        is_national = region_code == "NAC"
        indicator_id = INEGI_NATIONAL_IMAI_MAP.get(sector_id)

        if is_national:
            if indicator_id is None:
                indicator_id = INEGI_STATE_ITAEE_TOTAL
                use_itaee_fallback = True
            else:
                use_itaee_fallback = False

            raw = fetch_indicator(
                indicator_id,
                area_code=NATIONAL_AREA_CODE,
                source_db=COYUNTURA_SOURCE_DB,
            )
            freq = "monthly"
            units = "Índice base 2018=100" if not use_itaee_fallback else "Índice de volumen físico base 2018"
            proxy = "output_index"
            series_id = self.get_series_id(sector_id, region_code, "emim" if not use_itaee_fallback else "itaee")
            source_label = f"INEGI - {'IMAI' if not use_itaee_fallback else 'ITAEE'}"
        else:
            if sector_id == "manufactura_total":
                state_indicator = INEGI_STATE_ITAEE_TOTAL
            else:
                state_indicator = INEGI_STATE_ITAEE_MANUFACTURING

            if region_code in KNOWN_MISSING_ITAEE_STATES and state_indicator == INEGI_STATE_ITAEE_MANUFACTURING:
                state_indicator = INEGI_STATE_ITAEE_TOTAL

            raw = fetch_indicator(
                state_indicator,
                area_code=region_code,
                source_db=COYUNTURA_SOURCE_DB,
            )
            freq = "quarterly"
            units = "Índice de volumen físico base 2018"
            proxy = "output_index"
            suffix = "itaee"
            series_id = self.get_series_id(sector_id, region_code, suffix)
            source_label = "INEGI - ITAEE estatal"

        observations = []
        for obs in raw:
            period_str = obs.get("TIME_PERIOD", "")
            value_str = obs.get("OBS_VALUE", "")
            if not period_str or not value_str:
                continue
            observations.append((period_str, value_str))

        if not observations:
            raise ValueError(
                f"INEGI: sin observaciones para sector={sector_id} region={region_code}"
            )

        last_date = pd.Timestamp(max(o[0] for o in observations))
        vintage = (last_date + timedelta(days=45)).date().isoformat()

        meta = SeriesMeta(
            series_id=series_id,
            source=source_label,
            country="MX",
            region_code=region_code,
            sector_id=sector_id,
            frequency=freq,
            seasonal_adjustment="nsa",
            units=units,
            proxy_type=proxy,
            publication_lag_days=45,
            vintage_date=vintage,
            scian_code=scian_code,
            naics_code=naics_code,
        )

        tidy = normalize_series(observations, meta)
        label = f"{source_label} ({sector_id}, {region_code})"

        return SeriesBundle(series_id=series_id, tidy=tidy, label=label)

    def list_indicators(self) -> list[IndicatorInfo]:
        return [
            IndicatorInfo(
                id="imai_national",
                name="IMAI — Indicador Mensual de la Actividad Industrial (nacional)",
                name_en="IMAI — Monthly Industrial Activity Index (national)",
                theme="industrial_concentration",
                frequency="monthly",
                unit="Índice base 2018=100",
                proxy_type="output_index",
                geographic_granularity="national",
            ),
            IndicatorInfo(
                id="itaee_state",
                name="ITAEE — Indicador Trimestral de la Actividad Económica Estatal",
                name_en="ITAEE — Quarterly State Economic Activity Index",
                theme="industrial_concentration",
                frequency="quarterly",
                unit="Índice de volumen físico base 2018",
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
                RegionInfo(code=s["code"], name=s["name"])
                for s in registry.get("mx_states", [])
            ]
        return []

    def get_default_proxy_type(self) -> str:
        return "output_index"
