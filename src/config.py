"""
Application settings loaded from environment variables.

Dev mode: reads from local .env
Prod mode: reads from ~/.secrets/scientika.env
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _resolve_vault_path() -> Path | None:
    vault = Path.home() / ".secrets" / "scientika.env"
    return vault if vault.exists() else None


def _load_env() -> None:
    env = os.getenv("ENGINE_ENV", "development").lower()
    if env == "production":
        vault = _resolve_vault_path()
        if vault:
            load_dotenv(vault, override=True)
            return
        print(
            "[engine] WARNING: ENGINE_ENV=production pero "
            "~/.secrets/scientika.env no existe. "
            "Usando .env local como fallback.",
            file=sys.stderr,
        )
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


_load_env()


@dataclass(frozen=True)
class Settings:
    engine_env: str = field(
        default_factory=lambda: os.getenv("ENGINE_ENV", "development").lower()
    )
    use_mocks: bool = field(
        default_factory=lambda: os.getenv("ENGINE_USE_MOCKS", "true").lower() == "true"
    )
    db_path: str = field(
        default_factory=lambda: os.getenv(
            "ENGINE_DB_PATH",
            str(Path(__file__).resolve().parents[2] / "data" / "engine.db"),
        )
    )
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv(
                "ENGINE_CORS_ORIGINS", "http://localhost:3000"
            ).split(",")
            if o.strip()
        ]
    )

    search_api_key: str = field(
        default_factory=lambda: os.getenv("SEARCH_API_KEY", "")
    )
    deepseek_api_key: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "")
    )
    comtrade_api_key: str = field(
        default_factory=lambda: os.getenv("COMTRADE_API_KEY", "")
    )
    wipo_api_key: str = field(
        default_factory=lambda: os.getenv("WIPO_API_KEY", "")
    )
    inegi_token: str = field(
        default_factory=lambda: os.getenv("INEGI_TOKEN", "")
    )
    banxico_token: str = field(
        default_factory=lambda: os.getenv("BANXICO_TOKEN", "")
    )
    fred_api_key: str = field(
        default_factory=lambda: os.getenv("FRED_API_KEY", "")
    )
    bea_api_key: str = field(
        default_factory=lambda: os.getenv("BEA_API_KEY", "")
    )
    bls_api_key: str = field(
        default_factory=lambda: os.getenv("BLS_API_KEY", "")
    )

    @property
    def is_development(self) -> bool:
        return self.engine_env == "development"

    @property
    def is_production(self) -> bool:
        return self.engine_env == "production"

    def require(self, key_name: str, value: str | None = None) -> str:
        val = value if value is not None else getattr(self, key_name, "")
        if not val:
            raise RuntimeError(
                f"Missing required credential: {key_name}. "
                f"Set it in {'~/.secrets/scientika.env' if self.is_production else '.env'}."
            )
        return val


settings = Settings()

# ============================================================
# Pipeline constants — paths, thresholds, mock config
# (mirrored from Dashboard pipeline/config.py)
# ============================================================

ENGINE_ROOT = Path(__file__).resolve().parents[1]

REFERENCE_DIR = ENGINE_ROOT / "src" / "reference"
SECTORS_YAML = REFERENCE_DIR / "sectors.yaml"
REGION_REGISTRY_YAML = REFERENCE_DIR / "region_registry.yaml"
CROSSWALK_CSV = REFERENCE_DIR / "crosswalks" / "scian_naics_crosswalk.csv"

DATA_DIR = Path(os.getenv("ENGINE_DATA_DIR", str(ENGINE_ROOT / "data")))
SERIES_DIR = DATA_DIR / "series"
RESULTS_DIR = DATA_DIR / "results"
MANIFEST_PATH = DATA_DIR / "manifest.json"

MIN_OBS_QUARTERLY = 30
MIN_OBS_MONTHLY = 40
MIN_OBS_ANNUAL = 8
MIN_OBS_DAILY = 250

ALPHA = 0.05
FDR_ALPHA = 0.05
FDR_METHOD = "fdr_bh"

MAX_DIFF_ORDER = 2

MOCK_RANDOM_SEED = 42
MOCK_START_PERIOD = "2010-01"
MOCK_END_PERIOD = "2026-06"
