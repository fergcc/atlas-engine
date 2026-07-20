"""Orquestador del motor econométrico.

Itera sobre los pares definidos (sector × región × fuente, ver
`sectors.yaml` y el manifest de pares), corre el motor completo
(estacionariedad -> Granger -> cointegración Engle-Granger -> Johansen ->
VECM) sobre cada uno, y aplica la corrección FDR Benjamini-Hochberg sobre el
conjunto COMPLETO de p-values de Granger de la corrida (no por par aislado —
ver `apply_fdr_correction`).

El esquema de cada resultado sigue `app/src/lib/types.ts` (`ResultFile`),
que es el contrato ya consumido por el frontend Next.js, con algunos campos
adicionales (p. ej. `sector`, `series_a`/`series_b`, `optimal_lag`) que no
rompen ese contrato porque son aditivos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from statsmodels.stats.multitest import multipletests

from src.config import FDR_ALPHA, FDR_METHOD
from src.services.econometrics.cointegration import fit_vecm, test_engle_granger, test_johansen
from src.services.econometrics.granger import test_granger_causality
from src.services.econometrics.stationarity import test_stationarity
from src.services.processing.align import AlignedPair, align_pair


def _series_meta_block(tidy: pd.DataFrame) -> dict[str, Any]:
    row0 = tidy.iloc[0]
    return {
        "id": row0["series_id"],
        "source": row0["source"],
        "region": row0["region_code"],
        "proxy_type": row0["proxy_type"],
        "seasonal_adjustment": row0["seasonal_adjustment"],
    }


def _vintage_of(tidy: pd.DataFrame) -> str:
    return str(tidy["vintage_date"].iloc[-1])


def run_pair(
    pair_id: str,
    sector_meta: dict[str, Any],
    series_a_tidy: pd.DataFrame,
    series_b_tidy: pd.DataFrame,
) -> dict[str, Any]:
    """Corre el motor completo sobre un par de series tidy ya normalizadas
    (pero todavía sin alinear — `align_pair` se llama aquí adentro, como
    parte del motor, para que cada resultado documente su propia ventana
    muestral efectiva)."""
    aligned = align_pair(series_a_tidy, series_b_tidy)

    series_a_meta = _series_meta_block(series_a_tidy)
    series_b_meta = _series_meta_block(series_b_tidy)
    vintage_a = _vintage_of(series_a_tidy)
    vintage_b = _vintage_of(series_b_tidy)
    data_vintage = max(vintage_a, vintage_b)

    base: dict[str, Any] = {
        "pair_id": pair_id,
        "sector": sector_meta,
        "series_a": series_a_meta,
        "series_b": series_b_meta,
        "sample": {
            "frequency_used": aligned.frequency_used,
            "start": aligned.start,
            "end": aligned.end,
            "n_obs": aligned.n_obs,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Campo del contrato del frontend (string, ver ResultFile.data_vintage
        # en app/src/lib/types.ts): vintage más reciente entre ambas series.
        "data_vintage": data_vintage,
        # Detalle adicional (no rompe el contrato: es un campo extra).
        "data_vintage_detail": {"a": vintage_a, "b": vintage_b},
        "insufficient_data": aligned.insufficient_data,
    }

    if aligned.insufficient_data:
        base["warnings"] = [
            f"n_obs={aligned.n_obs} < mínimo requerido={aligned.min_obs_required} para "
            f"frecuencia '{aligned.frequency_used}'; no se corrió el motor econométrico "
            "sobre este par (resultado se omite para evitar un estadístico espurio)."
        ]
        base["stationarity"] = None
        base["granger"] = None
        base["cointegration_engle_granger"] = None
        base["cointegration_johansen"] = None
        base["vecm"] = None
        return base

    a = aligned.df.set_index("period_end_date")["value_a"]
    b = aligned.df.set_index("period_end_date")["value_b"]

    warns: list[str] = []

    stat_a = test_stationarity(a)
    stat_b = test_stationarity(b)
    warns.extend(stat_a.warnings)
    warns.extend(stat_b.warnings)

    granger = test_granger_causality(a, b, stat_a.order_integrated, stat_b.order_integrated)
    warns.extend(granger.warnings)

    eg = test_engle_granger(a, b)

    levels_df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    johansen = test_johansen(levels_df)

    vecm_out = None
    if johansen.rank > 0:
        try:
            vecm_out = fit_vecm(levels_df, coint_rank=johansen.rank)
        except Exception as exc:  # el VECM puede fallar a converger en casos límite
            warns.append(f"VECM no pudo ajustarse ({exc}); se omite este bloque.")

    base.update(
        {
            "stationarity": {
                "a": {
                    "adf_statistic": stat_a.adf_stat,
                    "adf_p_value": stat_a.adf_pvalue,
                    "kpss_statistic": stat_a.kpss_stat,
                    "kpss_p_value": stat_a.kpss_pvalue,
                    "is_stationary": stat_a.is_stationary,
                    "order_of_integration": stat_a.order_integrated,
                    "log_transformed": stat_a.log_transformed,
                },
                "b": {
                    "adf_statistic": stat_b.adf_stat,
                    "adf_p_value": stat_b.adf_pvalue,
                    "kpss_statistic": stat_b.kpss_stat,
                    "kpss_p_value": stat_b.kpss_pvalue,
                    "is_stationary": stat_b.is_stationary,
                    "order_of_integration": stat_b.order_integrated,
                    "log_transformed": stat_b.log_transformed,
                },
            },
            "granger": {
                "optimal_lag": granger.optimal_lag,
                "selection_criterion": granger.selection_criterion,
                "a_causes_b": {
                    "f_stat": granger.a_causes_b.f_stat,
                    "p_value": granger.a_causes_b.p_value,
                    "p_value_fdr_adj": None,  # se rellena en apply_fdr_correction
                    "significant": None,
                },
                "b_causes_a": {
                    "f_stat": granger.b_causes_a.f_stat,
                    "p_value": granger.b_causes_a.p_value,
                    "p_value_fdr_adj": None,
                    "significant": None,
                },
            },
            "cointegration_engle_granger": {
                "statistic": eg.stat,
                "p_value": eg.p_value,
                "cointegrated": eg.cointegrated,
            },
            "cointegration_johansen": {
                "trace_statistic": johansen.trace_stat,
                "critical_values": johansen.critical_values,
                "cointegration_rank": johansen.rank,
            },
            "vecm": (
                {
                    "cointegration_vector": vecm_out.cointegrating_vector,
                    "adjustment_speed": vecm_out.adjustment_speed,
                }
                if vecm_out is not None
                else None
            ),
        }
    )
    base["warnings"] = warns
    return base


def apply_fdr_correction(results: list[dict[str, Any]], *, alpha: float = FDR_ALPHA) -> list[dict[str, Any]]:
    """Aplica FDR Benjamini-Hochberg sobre TODOS los p-values de Granger
    (ambas direcciones, todos los pares) de la corrida completa y rellena
    `p_value_fdr_adj`/`significant` en cada resultado in-place.

    Los pares `insufficient_data` (granger=None) se excluyen del conjunto de
    p-values corregidos porque no tienen un resultado de Granger que corregir.
    """
    entries: list[tuple[dict[str, Any], str]] = []
    for res in results:
        if res.get("insufficient_data") or res.get("granger") is None:
            continue
        entries.append((res, "a_causes_b"))
        entries.append((res, "b_causes_a"))

    if not entries:
        return results

    raw_pvalues = [res["granger"][direction]["p_value"] for res, direction in entries]
    reject, adj_pvalues, _, _ = multipletests(raw_pvalues, alpha=alpha, method=FDR_METHOD)

    for (res, direction), adj_p, sig in zip(entries, adj_pvalues, reject):
        res["granger"][direction]["p_value_fdr_adj"] = float(adj_p)
        res["granger"][direction]["significant"] = bool(sig)

    return results


def run_all(
    pair_defs: list[dict[str, Any]],
    series_lookup: dict[str, pd.DataFrame],
    sectors_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Itera `pair_defs` (mismo formato que `manifest.pairs`: `pair_id`,
    `sector_id`, `series_a`, `series_b`, `level`), corre `run_pair` sobre cada
    uno usando las series tidy de `series_lookup`, y aplica FDR sobre el
    conjunto completo antes de devolver la lista de resultados.
    """
    results: list[dict[str, Any]] = []
    for pair in pair_defs:
        sector = sectors_by_id[pair["sector_id"]]
        sector_meta = {
            "id": sector["id"],
            "scian": sector["scian_codes"][0] if sector.get("scian_codes") else None,
            "naics": sector["naics_codes"][0] if sector.get("naics_codes") else None,
            "label": sector["label"],
        }
        series_a_tidy = series_lookup[pair["series_a"]]
        series_b_tidy = series_lookup[pair["series_b"]]
        results.append(run_pair(pair["pair_id"], sector_meta, series_a_tidy, series_b_tidy))

    return apply_fdr_correction(results)
