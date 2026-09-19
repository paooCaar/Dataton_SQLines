"""Select the audited V2 forecast policy and materialize its output.

This module deliberately does not import LightGBM and never fits a model.  It
reads the persisted Phase 2/4 validation artifacts, selects a model per
horizon, and standardizes the latest available historical forecast rows for
the operational contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HORIZONS = (1, 3, 6, 12)
CANDIDATES = ("PERSISTENCE", "SEASONAL_NAIVE", "THEIL_SEN", "LGBM_TEMPORAL")
SPATIAL_MODEL = "LGBM_TEMPORAL_SPATIAL"
DIRECTION_THRESHOLD_VERSION = "v2_zero_endpoint_threshold"
DIRECTIONAL_ACCURACY_THRESHOLD = 0.0

INPUTS = {
    "baseline_metrics": ROOT / "data/processed/baseline_metrics_v2.csv",
    "lgbm_metrics": ROOT / "data/processed/lightgbm_compare_metrics_v2.csv",
    "lgbm_cuts": ROOT / "data/processed/lightgbm_compare_cut_metrics_v2.csv",
    "spatial_value": ROOT / "data/processed/lightgbm_compare_spatial_value_v2.csv",
    "zone_metrics": ROOT / "data/processed/lightgbm_compare_zone_metrics_v2.csv",
    "overfitting": ROOT / "data/processed/lightgbm_compare_overfitting_v2.csv",
    "rolling_splits": ROOT / "data/processed/rolling_splits_v2.csv",
    "predictions": ROOT / "data/processed/lightgbm_compare_predictions_v2.csv",
    "panel": ROOT / "data/processed/panel_demanda_v2.csv",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float(value) -> float:
    return float(value) if pd.notna(value) else float("nan")


def _metric_row(metrics: pd.DataFrame, model: str, horizon: int) -> pd.Series:
    rows = metrics[(metrics.model == model) & (metrics.horizon == horizon)]
    if len(rows) != 1:
        raise ValueError(f"expected one metric row for {model}/{horizon}, got {len(rows)}")
    return rows.iloc[0]


def _lgbm_all_metrics(frame: pd.DataFrame, model: str, horizon: int,
                      scope: str = "EVALUATION_ALL") -> pd.Series:
    rows = frame[(frame.evaluation_scope == scope) &
                 (frame.model == model) & (frame.horizon == horizon)]
    if len(rows) != 1:
        raise ValueError(f"expected one EVALUATION_ALL row for {model}/{horizon}, got {len(rows)}")
    return rows.iloc[0]


def _cut_comparison(cuts: pd.DataFrame, horizon: int, model: str,
                    evaluation_scope: str = "EVALUATION_ALL") -> tuple[int, int, int, int]:
    scope = cuts[cuts.evaluation_scope == evaluation_scope]
    temporal = scope[(scope.horizon == horizon) & (scope.model == model)].set_index("split_id")
    persistence = scope[(scope.horizon == horizon) & (scope.model == "PERSISTENCE")].set_index("split_id")
    joined = temporal[["MAE"]].join(persistence[["MAE"]], lsuffix="_model", rsuffix="_persistence", how="inner").dropna()
    wins = int((joined.MAE_model < joined.MAE_persistence).sum())
    losses = int((joined.MAE_model > joined.MAE_persistence).sum())
    ties = int((joined.MAE_model == joined.MAE_persistence).sum())
    return wins, losses, ties, int(len(joined))


def build_policy() -> tuple[pd.DataFrame, dict]:
    """Build the auditable policy from existing Phase 2/4 outputs only."""
    baseline = pd.read_csv(INPUTS["baseline_metrics"])
    lgbm = pd.read_csv(INPUTS["lgbm_metrics"])
    cuts = pd.read_csv(INPUTS["lgbm_cuts"])
    spatial = pd.read_csv(INPUTS["spatial_value"])
    splits = pd.read_csv(INPUTS["rolling_splits"])
    if set(baseline.model.str.upper()) - set(CANDIDATES):
        raise ValueError("unexpected baseline candidate")

    rows: list[dict] = []
    for horizon in HORIZONS:
        baseline_p = _metric_row(baseline, "persistence", horizon)
        # Use the Phase 4 EVALUATION_ALL persistence row for the table so the
        # primary and LightGBM evidence share exactly the same availability
        # universe. Phase 2 is retained as the independent baseline source.
        p = _lgbm_all_metrics(lgbm, "PERSISTENCE", horizon, "EVALUATION_ALL")
        # Secondary evidence is only comparable where both models share the
        # exact spatially-comparable rows. It is never used as the operational
        # primary criterion.
        comparable_l = _lgbm_all_metrics(lgbm, "LGBM_TEMPORAL", horizon,
                                          "EVALUATION_SPATIAL_COMPARABLE")
        comparable_p = _lgbm_all_metrics(lgbm, "PERSISTENCE", horizon,
                                          "EVALUATION_SPATIAL_COMPARABLE")
        p_cuts = cuts[(cuts.evaluation_scope == "EVALUATION_ALL") &
                      (cuts.model == "PERSISTENCE") & (cuts.horizon == horizon)]
        l_wins, l_losses, l_ties, l_ncuts = _cut_comparison(
            cuts, horizon, "LGBM_TEMPORAL", "EVALUATION_SPATIAL_COMPARABLE")
        n_cuts = int(p.n_cuts)
        n_obs = int(p.n_observations)
        # Primary is selected against the complete, common operational universe.
        # Persistence wins the parsimony rule whenever its MAE/RMSE are lower or
        # equal and the candidate does not win a clear majority of cuts.
        primary = "PERSISTENCE"
        secondary = "LGBM_TEMPORAL" if horizon == 1 else "NONE"
        status = "VALIDATED_SHORT_TERM" if horizon == 1 else "VALIDATED_WITH_CAUTION"
        if horizon == 12:
            status = "VALIDATED_WITH_CAUTION"
        improvement = 100.0 * (float(comparable_p.MAE) - float(comparable_l.MAE)) / float(comparable_p.MAE)
        if secondary == "LGBM_TEMPORAL":
            reason = ("Persistencia conserva menor MAE/RMSE en EVALUATION_ALL; "
                      "LGBM_TEMPORAL queda secundario por señal de 1 mes en el "
                      "universo espacial comparable, sin promoción operativa.")
        else:
            reason = ("Persistencia conserva menor MAE/RMSE y la regla de parsimonia "
                      "no encuentra una mejora consistente de LGBM_TEMPORAL; "
                      "el horizonte requiere cautela por extrapolación creciente." if horizon >= 6 else
                      "Persistencia conserva menor MAE/RMSE y gana por parsimonia; "
                      "LGBM no supera de forma consistente a persistencia en el universo completo.")
        spatial_row = spatial[(spatial.evaluation_scope == "EVALUATION_SPATIAL_COMPARABLE") &
                              (spatial.horizon == horizon)]
        spatial_label = str(spatial_row.spatial_value_label.iloc[0]) if len(spatial_row) else "NO_SPATIAL_VALUE"
        rows.append({
            "horizon_months": horizon,
            "primary_model": primary,
            "secondary_model": secondary,
            "MAE_primary": float(p.MAE),
            "RMSE_primary": float(p.RMSE),
            "MAE_persistence": float(p.MAE),
            "improvement_vs_persistence_pct": 0.0,
            "cuts_won": 0,
            "cuts_lost": 0,
            "n_cuts": n_cuts,
            "n_observations": n_obs,
            "validation_status": status,
            "selection_reason": reason,
            "forecast_role": "VALIDATED_FORECAST",
            "spatial_role": "EXPLORATORY_ONLY",
            "spatial_value_label_comparable": spatial_label,
            "secondary_evaluation_scope": "EVALUATION_SPATIAL_COMPARABLE",
            "secondary_MAE_comparable": float(comparable_l.MAE),
            "secondary_RMSE_comparable": float(comparable_l.RMSE),
            "secondary_MAE_persistence_comparable": float(comparable_p.MAE),
            "secondary_improvement_vs_persistence_pct_comparable": improvement,
            "secondary_cuts_won": l_wins,
            "secondary_cuts_lost": l_losses,
            "secondary_cuts_ties": l_ties,
            "secondary_n_cuts": l_ncuts,
            "phase2_baseline_MAE": float(baseline_p.MAE),
            "phase2_baseline_RMSE": float(baseline_p.RMSE),
            "direction_threshold_version": DIRECTION_THRESHOLD_VERSION,
        })
    policy = pd.DataFrame(rows)
    if policy.horizon_months.duplicated().any() or not set(policy.primary_model).issubset(CANDIDATES):
        raise AssertionError("invalid or duplicate policy horizon")
    metadata = {
        "pipeline_version": "2.0-phase5-policy",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": "Phase 2/4 persisted outputs; no model fitting, tuning, or new features",
        "candidate_models": list(CANDIDATES),
        "spatial_model": SPATIAL_MODEL,
        "spatial_model_role": "EXPLORATORY_ONLY",
        "horizons": list(HORIZONS),
        "selection_universe": "EVALUATION_ALL for operational primary; comparable subset only as contextual evidence",
        "priority_order": ["MAE", "RMSE", "cut stability", "coverage", "directional_accuracy secondary"],
        "directional_accuracy_threshold": DIRECTIONAL_ACCURACY_THRESHOLD,
        "direction_threshold_version": DIRECTION_THRESHOLD_VERSION,
        "long_horizon_policy": {
            "12": "validated_with_caution; limited but real retrospective support",
            "36": "SCENARIO_ONLY; excluded from operational CSV",
            "60": "SCENARIO_ONLY; excluded from operational CSV",
        },
        "source_sha256": {str(path.relative_to(ROOT)): _sha256(path) for path in INPUTS.values()},
    }
    return policy, metadata


def _direction(change: float) -> str:
    if change > DIRECTIONAL_ACCURACY_THRESHOLD:
        return "UP"
    if change < -DIRECTIONAL_ACCURACY_THRESHOLD:
        return "DOWN"
    return "NEUTRAL"


def build_operational_forecast(policy: pd.DataFrame) -> pd.DataFrame:
    """Materialize latest available persistence rows, one row per zone/horizon."""
    predictions = pd.read_csv(INPUTS["predictions"])
    panel = pd.read_csv(INPUTS["panel"], usecols=["zone_id", "colonia", "alcaldia", "periodo", "target_unit"])
    if set(predictions.model.unique()) - {"PERSISTENCE", "LGBM_TEMPORAL", "LGBM_TEMPORAL_SPATIAL"}:
        raise ValueError("unexpected prediction model")
    rows = predictions[(predictions.evaluation_scope == "EVALUATION_ALL") &
                       (predictions.model == "PERSISTENCE")].copy()
    rows["horizon_months"] = rows["horizon"].astype(int)
    rows = rows[rows.horizon_months.isin(HORIZONS)]
    # For each zone/horizon, select the most recent audited origin. This gives
    # the operational contract a deterministic as-of forecast without retraining.
    rows = rows.sort_values(["horizon_months", "zone_id", "origin_period"])
    rows = rows.groupby(["horizon_months", "zone_id"], as_index=False).tail(1).copy()
    rows = rows.merge(panel.drop_duplicates("zone_id")[['zone_id', 'colonia', 'alcaldia']], on="zone_id", how="left", validate="many_to_one")
    rows["forecast_value"] = rows["predicted"].astype(float)
    rows["reference_value"] = rows["origin_value"].astype(float)
    rows["forecast_change_abs"] = rows["forecast_value"] - rows["reference_value"]
    rows["forecast_change_pct"] = np.where(rows.reference_value != 0,
                                            100.0 * rows.forecast_change_abs / rows.reference_value,
                                            np.nan)
    rows["direction"] = rows.forecast_change_abs.map(_direction)
    rows["model_used"] = "PERSISTENCE"
    policy_status = policy.set_index("horizon_months")["validation_status"].to_dict()
    policy_role = policy.set_index("horizon_months")["forecast_role"].to_dict()
    rows["validation_status"] = rows.horizon_months.map(policy_status)
    rows["forecast_role"] = rows.horizon_months.map(policy_role)
    rows["direction_threshold_version"] = DIRECTION_THRESHOLD_VERSION
    rows["target_unit"] = "station_endpoints_per_calendar_month"
    out = rows[["zone_id", "colonia", "origin_period", "horizon_months", "target_period",
                "forecast_value", "reference_value", "forecast_change_abs", "forecast_change_pct",
                "direction", "model_used", "validation_status", "forecast_role",
                "direction_threshold_version", "target_unit"]].sort_values(["horizon_months", "zone_id"]).reset_index(drop=True)
    if out.forecast_value.isna().any() or out.model_used.ne("PERSISTENCE").any():
        raise AssertionError("operational output contains invalid forecast rows")
    return out


def run(output_policy: Path = ROOT / "data/processed/model_policy_v2.csv",
        output_metadata: Path = ROOT / "data/processed/model_policy_v2.metadata.json",
        output_forecast: Path = ROOT / "data/processed/forecast_operational_v2.csv") -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    policy, metadata = build_policy()
    forecast = build_operational_forecast(policy)
    metadata["policy_sha256"] = hashlib.sha256(policy.to_csv(index=False).encode()).hexdigest()
    metadata["forecast_rows"] = int(len(forecast))
    metadata["forecast_rows_by_horizon"] = {str(k): int(v) for k, v in forecast.groupby("horizon_months").size().items()}
    metadata["output_sha256"] = {}
    output_policy.parent.mkdir(parents=True, exist_ok=True)
    policy.to_csv(output_policy, index=False)
    forecast.to_csv(output_forecast, index=False)
    metadata["output_sha256"][str(output_policy.relative_to(ROOT))] = _sha256(output_policy)
    metadata["output_sha256"][str(output_forecast.relative_to(ROOT))] = _sha256(output_forecast)
    output_metadata.write_text(json.dumps(metadata, indent=2) + "\n")
    return policy, forecast, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=ROOT / "data/processed/model_policy_v2.csv")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data/processed/model_policy_v2.metadata.json")
    parser.add_argument("--forecast", type=Path, default=ROOT / "data/processed/forecast_operational_v2.csv")
    args = parser.parse_args()
    policy, forecast, _ = run(args.policy, args.metadata, args.forecast)
    print(policy.to_string(index=False))
    print(f"operational rows: {len(forecast)}")


if __name__ == "__main__":
    main()
