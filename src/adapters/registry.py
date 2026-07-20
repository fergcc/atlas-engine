"""
Adapter auto-discovery and registry.

Adapters in adapters/ that subclass StatisticalOfficeAdapter are
automatically registered. Access via `get_adapter(country_code)`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Type

from src.adapters.base import StatisticalOfficeAdapter

logger = logging.getLogger(__name__)

_registry: dict[str, Type[StatisticalOfficeAdapter]] = {}


def _discover() -> None:
    if _registry:
        return

    adapters_root = Path(__file__).resolve().parent
    for item in adapters_root.iterdir():
        if not item.is_dir() or item.name.startswith("_"):
            continue

        init_file = item / "__init__.py"
        if not init_file.exists():
            continue

        for attr_name in dir(__import_module(item.name)):
            attr = getattr(__import_module(item.name), attr_name, None)
            if (
                isinstance(attr, type)
                and issubclass(attr, StatisticalOfficeAdapter)
                and attr is not StatisticalOfficeAdapter
                and not attr.__name__.startswith("_")
            ):
                _registry[attr.country] = attr
                logger.info(f"Registered adapter: {attr.__name__} → {attr.country}")


def __import_module(name: str):
    import importlib
    return importlib.import_module(f"src.adapters.{name}")


def get_adapter(country: str) -> StatisticalOfficeAdapter | None:
    _discover()
    cls = _registry.get(country.upper())
    if cls is None:
        return None
    return cls()


def list_countries() -> list[str]:
    _discover()
    return sorted(_registry.keys())


def get_adapter_info() -> list[dict]:
    _discover()
    result = []
    for country, cls in _registry.items():
        instance = cls()
        result.append({
            "country": country,
            "country_name": instance.country_name,
            "country_name_en": instance.country_name_en,
            "indicators": [
                {"id": i.id, "name": i.name, "proxy_type": i.proxy_type}
                for i in instance.list_indicators()
            ],
            "region_count": len(instance.list_regions()),
        })
    return result
