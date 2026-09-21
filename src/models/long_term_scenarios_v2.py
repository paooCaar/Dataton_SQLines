"""Escenarios de largo plazo (36 y 60 meses) para ECOBICI V2.

IMPORTANTE
----------
Esto NO es un forecast validado como los horizontes 1/3/6/12 meses.

Los escenarios parten del forecast operativo a 12 meses y extienden la
actividad con tasas de crecimiento anual históricas robustas por colonia.

Método:
1. calcular crecimientos exactos a 12 meses sobre viajes_total;
2. trabajar en escala log para evitar tasas menores a -100%;
3. usar q25 / mediana / q75 por colonia como escenarios bajo/base/alto;
4. limitar las tasas con caps derivados de la distribución histórica global
   de medianas por colonia (p10/p90), no con números arbitrarios;
5. componer 2 años adicionales para 36 meses y 4 años adicionales para
   60 meses a partir del ancla de 12 meses.

No se presentan como intervalos de confianza ni como P10/P50/P90.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

PANEL_PATH = ROOT / "data" / "processed" / "panel_demanda_v2.csv"
CURRENT_PATH = ROOT / "data" / "processed" / "current_forecast_product_v2.csv"

OUTPUT_PATH = ROOT / "data" / "processed" / "long_term_scenarios_v2.csv"
METADATA_PATH = ROOT / "data" / "processed" / "long_term_scenarios_v2.metadata.json"

VERSION = "2.0-phase8-long-term-scenarios"

HORIZONS = (36, 60)
MIN_GROWTH_POINTS = 8
GLOBAL_CAP_LOW_Q = 0.10
GLOBAL_CAP_HIGH_Q = 0.90


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except Exception:
        return None


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{name} no contiene columnas requeridas: {sorted(missing)}")


def compute_yoy_log_growth(panel: pd.DataFrame) -> pd.DataFrame:
    """Calcula crecimiento exacto a 12 meses por zone_id.

    Un mes faltante NO se sustituye por el registro anterior disponible.
    Si no existe el mismo mes del año previo, esa observación simplemente
    no participa.
    """

    _require_columns(
        panel,
        {"zone_id", "periodo", "viajes_total"},
        "panel_demanda_v2",
    )

    base = panel[["zone_id", "periodo", "viajes_total"]].copy()
    base["zone_id"] = base["zone_id"].astype(str)
    base["periodo"] = pd.PeriodIndex(base["periodo"].astype(str), freq="M")
    base["viajes_total"] = pd.to_numeric(base["viajes_total"], errors="coerce")

    if base.duplicated(["zone_id", "periodo"]).any():
        raise ValueError("panel_demanda_v2 tiene llaves zone_id/periodo duplicadas")

    previous = base.rename(
        columns={"viajes_total": "viajes_total_prev_12m"}
    ).copy()
    previous["periodo"] = previous["periodo"] + 12

    merged = base.merge(
        previous,
        on=["zone_id", "periodo"],
        how="left",
        validate="one_to_one",
    )

    valid = (
        merged["viajes_total"].notna()
        & merged["viajes_total_prev_12m"].notna()
        & merged["viajes_total"].gt(0)
        & merged["viajes_total_prev_12m"].gt(0)
    )

    growth = merged.loc[
        valid,
        [
            "zone_id",
            "periodo",
            "viajes_total",
            "viajes_total_prev_12m",
        ],
    ].copy()

    growth["log_growth_12m"] = np.log(
        growth["viajes_total"] / growth["viajes_total_prev_12m"]
    )

    growth["annual_growth_pct"] = (
        np.exp(growth["log_growth_12m"]) - 1
    ) * 100

    growth = growth[
        np.isfinite(growth["log_growth_12m"])
    ].copy()

    return growth


def summarize_growth(
    growth: pd.DataFrame,
    min_points: int = MIN_GROWTH_POINTS,
) -> tuple[pd.DataFrame, dict]:
    """Resume crecimiento por zona y obtiene caps globales robustos."""

    if growth.empty:
        raise ValueError("No hay observaciones válidas de crecimiento interanual")

    grouped = growth.groupby("zone_id")["log_growth_12m"]

    summary = grouped.agg(
        n_growth_points="count",
        growth_log_q25=lambda s: s.quantile(0.25),
        growth_log_base="median",
        growth_log_q75=lambda s: s.quantile(0.75),
    ).reset_index()

    eligible = summary[
        summary["n_growth_points"].ge(min_points)
    ].copy()

    if eligible.empty:
        raise ValueError(
            f"Ninguna zona alcanza min_growth_points={min_points}"
        )

    medians = eligible["growth_log_base"].dropna()

    cap_low = float(
        medians.quantile(GLOBAL_CAP_LOW_Q)
    )
    cap_high = float(
        medians.quantile(GLOBAL_CAP_HIGH_Q)
    )

    if not np.isfinite([cap_low, cap_high]).all() or cap_low > cap_high:
        raise ValueError("Caps globales inválidos")

    for col in [
        "growth_log_q25",
        "growth_log_base",
        "growth_log_q75",
    ]:
        summary[col] = summary[col].clip(
            lower=cap_low,
            upper=cap_high,
        )

    # Garantía defensiva de orden tras clipping.
    ordered = np.sort(
        summary[
            [
                "growth_log_q25",
                "growth_log_base",
                "growth_log_q75",
            ]
        ].to_numpy(dtype=float),
        axis=1,
    )

    summary[
        [
            "growth_log_low",
            "growth_log_base_clipped",
            "growth_log_high",
        ]
    ] = ordered

    summary["growth_low_annual_pct"] = (
        np.exp(summary["growth_log_low"]) - 1
    ) * 100

    summary["growth_base_annual_pct"] = (
        np.exp(summary["growth_log_base_clipped"]) - 1
    ) * 100

    summary["growth_high_annual_pct"] = (
        np.exp(summary["growth_log_high"]) - 1
    ) * 100

    summary["history_status"] = np.where(
        summary["n_growth_points"].ge(min_points),
        "SUFFICIENT_HISTORY",
        "INSUFFICIENT_HISTORY",
    )

    caps = {
        "global_cap_low_log": cap_low,
        "global_cap_high_log": cap_high,
        "global_cap_low_annual_pct": (math.exp(cap_low) - 1) * 100,
        "global_cap_high_annual_pct": (math.exp(cap_high) - 1) * 100,
        "cap_source": (
            "p10/p90 de las medianas de crecimiento log interanual "
            "de zonas con historia suficiente"
        ),
    }

    return summary, caps


def build_long_term_scenarios(
    panel: pd.DataFrame,
    current: pd.DataFrame,
    min_points: int = MIN_GROWTH_POINTS,
) -> tuple[pd.DataFrame, dict]:
    """Construye escenarios 36/60 meses a partir del ancla de 12 meses."""

    _require_columns(
        current,
        {
            "zone_id",
            "colonia",
            "alcaldia",
            "origin_period",
            "horizon_months",
            "target_period",
            "forecast_value",
        },
        "current_forecast_product_v2",
    )

    origins = sorted(
        current["origin_period"].dropna().astype(str).unique().tolist()
    )

    if len(origins) != 1:
        raise ValueError(
            f"Se esperaba un solo origin_period común; se encontraron {origins}"
        )

    origin_period = origins[0]

    anchor = current[
        current["horizon_months"].eq(12)
    ][
        [
            "zone_id",
            "colonia",
            "alcaldia",
            "origin_period",
            "target_period",
            "forecast_value",
        ]
    ].copy()

    anchor["zone_id"] = anchor["zone_id"].astype(str)
    anchor["forecast_value"] = pd.to_numeric(
        anchor["forecast_value"],
        errors="coerce",
    )

    if anchor["zone_id"].duplicated().any():
        raise ValueError("El ancla de 12 meses tiene zone_id duplicado")

    growth = compute_yoy_log_growth(panel)
    summary, caps = summarize_growth(
        growth,
        min_points=min_points,
    )

    base = anchor.merge(
        summary,
        on="zone_id",
        how="left",
        validate="one_to_one",
    )

    rows = []

    origin = pd.Period(origin_period, freq="M")

    for horizon in HORIZONS:
        extra_years = horizon / 12 - 1

        frame = base.copy()

        frame["horizon_months"] = horizon
        frame["target_period"] = str(origin + horizon)
        frame["anchor_12m_value"] = frame["forecast_value"]
        # El target del ancla de 12 meses se conserva por separado.
        frame["anchor_12m_target_period"] = anchor["target_period"].to_numpy()

        valid = (
            frame["forecast_value"].notna()
            & frame["forecast_value"].ge(0)
            & frame["history_status"].eq("SUFFICIENT_HISTORY")
            & frame[
                [
                    "growth_log_low",
                    "growth_log_base_clipped",
                    "growth_log_high",
                ]
            ].notna().all(axis=1)
        )

        frame["scenario_low"] = np.nan
        frame["scenario_base"] = np.nan
        frame["scenario_high"] = np.nan

        frame.loc[valid, "scenario_low"] = (
            frame.loc[valid, "forecast_value"]
            * np.exp(
                frame.loc[valid, "growth_log_low"]
                * extra_years
            )
        )

        frame.loc[valid, "scenario_base"] = (
            frame.loc[valid, "forecast_value"]
            * np.exp(
                frame.loc[valid, "growth_log_base_clipped"]
                * extra_years
            )
        )

        frame.loc[valid, "scenario_high"] = (
            frame.loc[valid, "forecast_value"]
            * np.exp(
                frame.loc[valid, "growth_log_high"]
                * extra_years
            )
        )

        for col in [
            "scenario_low",
            "scenario_base",
            "scenario_high",
        ]:
            frame[col] = frame[col].clip(lower=0)

        frame["scenario_status"] = np.where(
            valid,
            "READY",
            "INSUFFICIENT_HISTORY",
        )

        frame["scenario_role"] = "SCENARIO_ONLY"
        frame["validation_status"] = "SCENARIO_ONLY"
        frame["is_validated_forecast"] = False

        frame["scenario_method"] = (
            "12m_anchor_plus_compounded_robust_yoy_log_growth"
        )

        frame["extra_years_after_12m_anchor"] = extra_years

        frame["notes"] = np.where(
            valid,
            (
                "Escenario condicional basado en crecimiento interanual "
                "histórico robusto; no es un forecast validado."
            ),
            (
                "No se genera escenario numérico porque la colonia no "
                "tiene suficiente historia interanual válida."
            ),
        )

        rows.append(
            frame[
                [
                    "zone_id",
                    "colonia",
                    "alcaldia",
                    "origin_period",
                    "horizon_months",
                    "target_period",
                    "anchor_12m_value",
                    "anchor_12m_target_period",
                    "n_growth_points",
                    "growth_low_annual_pct",
                    "growth_base_annual_pct",
                    "growth_high_annual_pct",
                    "scenario_low",
                    "scenario_base",
                    "scenario_high",
                    "scenario_status",
                    "scenario_role",
                    "validation_status",
                    "is_validated_forecast",
                    "scenario_method",
                    "extra_years_after_12m_anchor",
                    "notes",
                ]
            ]
        )

    output = pd.concat(
        rows,
        ignore_index=True,
    )

    output = output.sort_values(
        [
            "horizon_months",
            "alcaldia",
            "colonia",
            "zone_id",
        ]
    ).reset_index(drop=True)

    # Contratos defensivos.
    if output.duplicated(["zone_id", "horizon_months"]).any():
        raise AssertionError("Escenarios duplicados por zone_id/horizon")

    ready = output["scenario_status"].eq("READY")

    if ready.any():
        ordered = (
            output.loc[ready, "scenario_low"].le(
                output.loc[ready, "scenario_base"]
            )
            & output.loc[ready, "scenario_base"].le(
                output.loc[ready, "scenario_high"]
            )
        )

        if not ordered.all():
            raise AssertionError("scenario_low <= base <= high no se cumple")

        if (
            output.loc[
                ready,
                [
                    "scenario_low",
                    "scenario_base",
                    "scenario_high",
                ],
            ]
            .lt(0)
            .any()
            .any()
        ):
            raise AssertionError("Hay escenarios negativos")

    meta = {
        "pipeline_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "origin_period": origin_period,
        "horizons_months": list(HORIZONS),
        "method": (
            "Ancla del forecast operativo a 12 meses + crecimiento log "
            "interanual robusto por colonia. q25/mediana/q75 definen "
            "escenario bajo/base/alto; caps globales p10/p90 de medianas "
            "por colonia evitan extrapolaciones extremas."
        ),
        "not_a_forecast_interval": True,
        "not_p10_p50_p90": True,
        "min_growth_points": min_points,
        "growth_caps": caps,
        "n_rows": int(len(output)),
        "n_zones": int(output["zone_id"].nunique()),
        "ready_by_horizon": {
            str(int(h)): int(
                output[
                    output["horizon_months"].eq(h)
                ]["scenario_status"].eq("READY").sum()
            )
            for h in HORIZONS
        },
        "limitations": [
            "36/60 meses no cuentan con validación retrospectiva equivalente a 1/3/6/12 meses.",
            "Los escenarios mantienen la tasa histórica condicionada y no modelan cambios de política, infraestructura o cobertura futuros.",
            "El crecimiento histórico de ECOBICI puede reflejar expansión de red además de cambios de uso.",
            "Bajo/base/alto son escenarios condicionados, no cuantiles predictivos ni intervalos de confianza.",
        ],
        "input_sha256": {
            str(PANEL_PATH.relative_to(ROOT)): sha256_file(PANEL_PATH),
            str(CURRENT_PATH.relative_to(ROOT)): sha256_file(CURRENT_PATH),
        },
    }

    return output, meta


def main() -> None:
    panel = pd.read_csv(
        PANEL_PATH,
        dtype={"periodo": str, "zone_id": str},
    )

    current = pd.read_csv(
        CURRENT_PATH,
        dtype={
            "origin_period": str,
            "target_period": str,
            "zone_id": str,
        },
    )

    output, metadata = build_long_term_scenarios(
        panel,
        current,
    )

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    metadata["output_sha256"] = sha256_file(
        OUTPUT_PATH
    )

    METADATA_PATH.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Generado: {OUTPUT_PATH.relative_to(ROOT)}"
    )

    print(
        output.groupby(
            ["horizon_months", "scenario_status"]
        ).size()
    )


if __name__ == "__main__":
    main()
