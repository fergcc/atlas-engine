"""Serializa el resultado del pipeline a `data/manifest.json`,
`data/series/{id}.json` y `data/results/{pair_id}.json` (raíz del monorepo,
fuera de `pipeline/` — es lo único que el frontend Next.js consume, vía
`app/src/lib/data-loader.ts` / `client-data.ts`, y lo único que
`scripts/sync-data.mjs` copia a `app/public/data`).

Mantener el esquema de `manifest.json`/`series/*.json` en sync con
`app/src/lib/types.ts` (`Manifest`, `SeriesCatalogEntry`, `SeriesFile`).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.config import MANIFEST_PATH, RESULTS_DIR, SERIES_DIR

FREQ_LABEL_ES = {
    "monthly": "mensual",
    "quarterly": "trimestral",
    "annual": "anual",
    "daily": "diaria",
}

# Paso aproximado en días usado solo para estimar la próxima actualización
# esperada en el catálogo de series (informativo, no normativo).
FREQ_STEP_DAYS = {"monthly": 30, "quarterly": 92, "annual": 365, "daily": 1}


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (pd.Timestamp, date, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"No se sabe serializar el tipo {type(obj)!r}")


def _write_json(path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def build_series_catalog_entry(series_id: str, tidy: pd.DataFrame, *, label: str) -> dict[str, Any]:
    """Construye la entrada de `manifest.series_catalog` para una serie tidy
    (ver `app/src/lib/types.ts::SeriesCatalogEntry`)."""
    row0 = tidy.iloc[0]
    last_date = pd.Timestamp(tidy["period_end_date"].max())
    freq = row0["frequency"]
    step_days = FREQ_STEP_DAYS.get(freq, 30)
    next_estimated = last_date + pd.Timedelta(days=step_days)
    return {
        "id": series_id,
        "nombre": label,
        "pais": row0["country"],
        "region_code": row0["region_code"],
        "sector_id": row0["sector_id"],
        "fuente": row0["source"],
        "periodicidad": FREQ_LABEL_ES.get(freq, freq),
        "unidad": row0["units"],
        "proxy_type": row0["proxy_type"],
        "ultima_actualizacion": str(last_date.date()),
        "proxima_actualizacion_estimada": str(next_estimated.date()),
    }


def _period_label(period_end_date: pd.Timestamp, frequency: str) -> str:
    if frequency == "monthly":
        return period_end_date.strftime("%Y-%m")
    if frequency == "quarterly":
        return f"{period_end_date.year}-Q{period_end_date.quarter}"
    if frequency == "annual":
        return str(period_end_date.year)
    return str(period_end_date.date())


def build_series_file(series_id: str, tidy: pd.DataFrame, catalog_entry: dict[str, Any]) -> dict[str, Any]:
    """Construye el contenido de `data/series/{series_id}.json` (ver
    `app/src/lib/types.ts::SeriesFile`)."""
    ordered = tidy.sort_values("period_end_date")
    frequency = ordered["frequency"].iloc[0]
    observations = [
        {
            "period": _period_label(pd.Timestamp(row["period_end_date"]), frequency),
            "value": None if pd.isna(row["value"]) else float(row["value"]),
        }
        for _, row in ordered.iterrows()
    ]
    return {"id": series_id, "meta": catalog_entry, "observations": observations}


def export_all(
    *,
    sectors: list[dict[str, Any]],
    series_lookup: dict[str, pd.DataFrame],
    series_labels: dict[str, str],
    pair_defs: list[dict[str, Any]],
    results: list[dict[str, Any]],
    mode: str = "mock",
    refresh_cadence: str = "trimestral",
) -> dict[str, Any]:
    """Escribe `data/manifest.json`, `data/series/*.json` y
    `data/results/*.json`. Devuelve el manifest ensamblado (útil para tests).
    """
    series_catalog: list[dict[str, Any]] = []
    for series_id, tidy in series_lookup.items():
        label = series_labels.get(series_id, series_id)
        entry = build_series_catalog_entry(series_id, tidy, label=label)
        series_catalog.append(entry)
        series_file = build_series_file(series_id, tidy, entry)
        _write_json(SERIES_DIR / f"{series_id}.json", series_file)

    for result in results:
        _write_json(RESULTS_DIR / f"{result['pair_id']}.json", result)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "refresh_cadence": refresh_cadence,
        "sectors": [
            {"id": s["id"], "label": s["label"], "icon": s["icon"], "priority": s["priority"]}
            for s in sectors
        ],
        "series_catalog": series_catalog,
        "pairs": pair_defs,
    }
    _write_json(MANIFEST_PATH, manifest)
    return manifest
