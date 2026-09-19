"""Emit persistence from a common observed origin; reuse frozen Phase 6 radii."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.model_matrices_v2 import origin_features, validate_panel
from src.models.uncertainty_v2 import (
    ROOT, HORIZONS, UNIT, build_explanations, _sha256, _git_commit,
)

DATA = ROOT / "data/processed"
INPUT_NAMES = (
    "panel_demanda_v2.csv", "catalogo_zonas_v2.csv", "zone_neighbors_v2.csv",
    "model_policy_v2.csv", "model_policy_v2.metadata.json",
    "uncertainty_backtest_v2.csv", "forecast_uncertainty_v2.metadata.json",
)


def common_origin(panel, catalog, issued_at):
    """Do not shrink the catalog or replace missing/unknown activity with zero."""
    validate_panel(panel)
    if catalog.zone_id.duplicated().any():
        raise ValueError("Duplicate catalog zone")
    universe = set(catalog.zone_id)
    for period in sorted(panel.periodo.unique(), reverse=True):
        rows = panel[panel.periodo.eq(period) & panel.zone_id.isin(universe)]
        issue_boundary = (pd.Period(period, freq="M") + 1).to_timestamp()
        available = pd.to_datetime(rows.target_available_no_earlier_than, format="ISO8601")
        if (issue_boundary <= pd.Timestamp(issued_at).tz_localize(None)
                and set(rows.zone_id) == universe
                and rows.data_status.isin(["OBSERVED", "ZERO_DEMAND"]).all()
                and np.isfinite(rows.viajes_total).all() and rows.viajes_total.ge(0).all()
                and available.notna().all() and available.le(issue_boundary).all()):
            return period
    raise ValueError("No common observed origin with sufficient available information")


def frozen_radius(backtest, horizon, origin):
    """Recover a saved global radius, never estimate a new residual quantile."""
    rows = backtest[backtest.horizon_months.eq(horizon)
                    & backtest.origin_period.le(origin)
                    & backtest.uncertainty_status.eq("CALIBRATED")].copy()
    if rows.empty:
        return np.nan, None, 0
    rows = rows[rows.origin_period.eq(rows.origin_period.max())]
    radii = rows.interval_upper_80 - rows.forecast_value
    if not np.isfinite(radii).all() or (radii < 0).any() or not np.allclose(radii, radii.iloc[0]):
        raise ValueError("Saved calibration radius is not finite/global by horizon")
    if rows.n_calibration_points.nunique() != 1:
        raise ValueError("Inconsistent saved calibration count")
    return float(radii.iloc[0]), rows.origin_period.iloc[0], int(rows.n_calibration_points.iloc[0])


def build_current(panel, catalog, neighbors, policy, backtest, issued_at):
    if (set(policy.horizon_months) != set(HORIZONS)
            or policy.horizon_months.duplicated().any()
            or not policy.primary_model.eq("PERSISTENCE").all()):
        raise ValueError("Unsupported or changed model policy")
    origin = common_origin(panel, catalog, issued_at)
    # Exactly the existing formulas; context is computed offline, not by the app.
    features = origin_features(panel, neighbors, origin)
    observed = panel[panel.periodo.eq(origin)][["zone_id", "viajes_total"]]
    base = catalog[["zone_id", "colonia", "alcaldia"]].merge(observed, on="zone_id", validate="one_to_one")
    rows, matrices = [], []
    for h in HORIZONS:
        selected = policy[policy.horizon_months.eq(h)].iloc[0]
        frame = base.rename(columns={"viajes_total": "reference_value"}).copy()
        frame["origin_period"] = origin
        frame["horizon_months"] = h
        frame["target_period"] = str(pd.Period(origin, freq="M") + h)
        frame["forecast_value"] = frame.reference_value
        frame["forecast_change_abs"] = 0.0
        frame["forecast_change_pct"] = np.where(frame.reference_value.ne(0), 0.0, np.nan)
        frame["direction"] = "NEUTRAL"  # existing zero-endpoint threshold
        frame["model_used"] = selected.primary_model
        frame["validation_status"] = selected.validation_status
        frame["forecast_role"] = selected.forecast_role
        frame["artifact_role"] = "CURRENT_FORECAST"
        frame["target_unit"] = UNIT
        frame["issued_at"] = issued_at
        radius, calibration_origin, n = frozen_radius(backtest, h, origin)
        frame["interval_lower_80"] = np.maximum(0, frame.forecast_value - radius)
        frame["interval_upper_80"] = frame.forecast_value + radius
        frame["interval_width"] = frame.interval_upper_80 - frame.interval_lower_80
        frame["lower_clipped"] = frame.forecast_value.lt(radius)
        frame["frozen_radius"] = radius
        frame["calibration_origin_period"] = calibration_origin
        frame["n_calibration_points"] = n
        frame["uncertainty_status"] = "FROZEN_PHASE6_CALIBRATION" if np.isfinite(radius) else "INSUFFICIENT_CALIBRATION_HISTORY"
        rows.append(frame)
        context = features.copy()
        context["horizon"] = h
        context["target_period"] = frame.target_period.iloc[0]
        matrices.append(context)
    result = pd.concat(rows, ignore_index=True)
    explanations = build_explanations(result, matrix=pd.concat(matrices, ignore_index=True))
    # Phase 6 supplies the exact safe context formatter. Its replay-only wording
    # is not applicable to this separately issued artifact.
    explanations = explanations.drop(columns=["limitations"])
    result = result.merge(explanations, on=["zone_id", "colonia", "horizon_months", "origin_period", "target_period"], validate="one_to_one")
    result["limitations"] = (
        "Disponibilidad histórica y finalización del target no verificadas. "
        "Radio de Fase 6 congelado; cobertura de la emisión actual no evaluada. "
        "Contexto descriptivo no causal; catálogo de estaciones sin vigencia histórica verificada."
    )
    return result.sort_values(["zone_id", "horizon_months"]).reset_index(drop=True)


def run(data=DATA, issued_at=None):
    issued_at = issued_at or datetime.now(timezone.utc).isoformat()
    read = lambda name: pd.read_csv(data / name)
    product = build_current(read(INPUT_NAMES[0]), read(INPUT_NAMES[1]), read(INPUT_NAMES[2]),
                            read("model_policy_v2.csv"), read("uncertainty_backtest_v2.csv"), issued_at)
    metadata = {
        "pipeline_version": "2.0-phase7", "artifact_role": "CURRENT_FORECAST",
        "issued_at": issued_at, "git_commit": _git_commit(),
        "common_origin_period": product.origin_period.iloc[0],
        "n_zones": product.zone_id.nunique(), "n_rows": len(product),
        "horizons_months": list(HORIZONS), "target": "viajes_total", "target_unit": UNIT,
        "universe": "Entire V2 catalog; no missing/unknown values imputed",
        "historical_availability_verified": False, "target_finalized": False,
        "interval_policy": "Reuse last saved Phase 6 global radius per horizon, no recalibration; lower clipped to zero",
        "calibration_by_horizon": product[["horizon_months", "calibration_origin_period", "frozen_radius", "n_calibration_points"]].drop_duplicates().to_dict("records"),
        "current_coverage_validated": False,
        "source_sha256": {str((data / name).relative_to(ROOT)): _sha256(data / name) for name in INPUT_NAMES},
        "implementation_sha256": {name: _sha256(ROOT / name) for name in (
            "src/models/current_forecast_v2.py", "src/models/uncertainty_v2.py", "src/features/model_matrices_v2.py")},
    }
    return product, metadata


def main():
    product, metadata = run()
    path = DATA / "current_forecast_product_v2.csv"
    product.to_csv(path, index=False)
    metadata["output_sha256"] = {str(path.relative_to(ROOT)): _sha256(path)}
    (DATA / "current_forecast_product_v2.metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Common origin {metadata['common_origin_period']}: {len(product)} rows, {metadata['n_zones']} zones")


if __name__ == "__main__":
    main()
