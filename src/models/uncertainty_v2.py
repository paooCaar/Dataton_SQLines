"""Rolling-calibrated uncertainty and persistence-compatible explanations.

The operational model is persistence. This module uses only out-of-sample
persistence residuals whose earliest target availability precedes the forecast
origin. It does not fit a model, compute SHAP, or modify Streamlit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HORIZONS = (1, 3, 6, 12)
TARGET_COVERAGE = 0.80
MIN_CALIBRATION_POINTS = 30
METHOD = "CONFORMAL_SYMMETRIC_ABS_RESIDUAL"
KEY = ["zone_id", "horizon_months"]
UNIT = "station_endpoints_per_calendar_month"
EXPLANATION_VERSION = "2.0-phase6-persistence-context"
SAFE_CONTEXT = (
    "growth_1", "growth_3", "rolling_mean_3", "trend_3",
    "neighbor_trips_lag1", "neighbor_growth_lag1", "neighbor_observation_coverage",
)

INPUTS = {
    "predictions": ROOT / "data/processed/lightgbm_compare_predictions_v2.csv",
    "operational": ROOT / "data/processed/forecast_operational_v2.csv",
    "policy": ROOT / "data/processed/model_policy_v2.csv",
    "policy_metadata": ROOT / "data/processed/model_policy_v2.metadata.json",
    "temporal_features": ROOT / "data/processed/features_temporales_v2.csv",
    "spatial_features": ROOT / "data/processed/features_espaciales_v2.csv",
    "panel": ROOT / "data/processed/panel_demanda_v2.csv",
    "splits": ROOT / "data/processed/rolling_splits_v2.csv",
    "matrix": ROOT / "data/processed/model_matrix_temporal_spatial_v2.csv",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def prepare_predictions(predictions, panel, splits):
    """Validate OOS keys and attach the target's earliest known availability."""
    frame = predictions[(predictions.evaluation_scope == "EVALUATION_ALL") &
                        (predictions.model == "PERSISTENCE")].copy()
    keys = ["zone_id", "horizon", "origin_period", "target_period"]
    if frame[keys].isna().any().any() or frame.duplicated(keys).any():
        raise ValueError("Duplicate/null OOS prediction key")
    used = splits[splits.status.eq("USED")][["split_id", "horizon", "origin_period", "target_period"]]
    frame = frame.merge(used, how="left", on=list(used.columns), validate="many_to_one", indicator=True)
    if frame.pop("_merge").ne("both").any():
        raise ValueError("Prediction does not match an existing USED rolling cut")
    labels = panel[["zone_id", "periodo", "viajes_total", "target_available_no_earlier_than", "data_status"]].rename(columns={"periodo": "target_period"})
    frame = frame.merge(labels, how="left", on=["zone_id", "target_period"], validate="many_to_one")
    if not np.isfinite(frame[["actual", "predicted", "origin_value"]]).all().all():
        raise ValueError("Nonfinite OOS values")
    if (frame[["actual", "predicted"]] < 0).any().any():
        raise ValueError("Negative activity")
    if not np.allclose(frame.actual, frame.viajes_total) or not np.allclose(frame.predicted, frame.origin_value):
        raise ValueError("OOS target/persistence mismatch")
    if not frame.data_status.isin(["OBSERVED", "ZERO_DEMAND"]).all():
        raise ValueError("Missing/unknown target cannot calibrate")
    target = pd.PeriodIndex(frame.target_period, freq="M")
    origin = pd.PeriodIndex(frame.origin_period, freq="M")
    if not np.array_equal(target.asi8 - origin.asi8, frame.horizon.to_numpy()):
        raise ValueError("Invalid calendar horizon")
    available = pd.to_datetime(frame.target_available_no_earlier_than, format="ISO8601")
    month_finished = pd.Series((target + 1).to_timestamp(), index=frame.index)
    frame["residual_available_at"] = available.where(available >= month_finished, month_finished).where(available.notna())
    return frame.sort_values(keys).reset_index(drop=True)


def calibration_history(predictions, horizon, origin_period):
    if "residual_available_at" not in predictions:
        raise ValueError("Residual availability is required; prepare predictions first")
    origin = pd.Period(origin_period, freq="M")
    dates = pd.to_datetime(predictions.residual_available_at)
    return predictions[(predictions.horizon == horizon) &
                       predictions.model.eq("PERSISTENCE") &
                       predictions.evaluation_scope.eq("EVALUATION_ALL") &
                       (pd.PeriodIndex(predictions.origin_period, freq="M") < origin) &
                       (pd.PeriodIndex(predictions.target_period, freq="M") < origin) &
                       dates.notna() & (dates < origin.to_timestamp()) &
                       np.isfinite(predictions.actual) & np.isfinite(predictions.predicted)]


def _calibration_residuals(predictions: pd.DataFrame, horizon: int, origin_period: str) -> np.ndarray:
    """Return residuals known strictly before ``origin_period``.

    Both the forecast origin and the residual's target month must precede the
    current origin. The second guard prevents a long-horizon forecast error
    from being used before its target month has arrived.
    """
    known = calibration_history(predictions, horizon, origin_period)
    return (known.actual.to_numpy(dtype=float) - known.predicted.to_numpy(dtype=float))


def _interval(forecast_value: float, residuals: np.ndarray) -> tuple[float, float, int, bool, str]:
    if not np.isfinite(forecast_value) or forecast_value < 0:
        raise ValueError("Forecast must be finite nonnegative activity")
    if not np.isfinite(residuals).all():
        raise ValueError("Nonfinite calibration residual")
    n = int(len(residuals))
    if n < MIN_CALIBRATION_POINTS:
        return np.nan, np.nan, n, False, "INSUFFICIENT_CALIBRATION_HISTORY"
    # Finite-sample conformal order statistic, k=ceil((n+1)*coverage).
    # Exchangeability is NOT assumed valid for these dependent rolling rows;
    # coverage must therefore be assessed empirically, not guaranteed.
    rank = int(np.ceil((n + 1) * TARGET_COVERAGE))
    radius = float(np.sort(np.abs(residuals))[rank - 1])
    lower_raw = float(forecast_value - radius)
    upper_raw = float(forecast_value + radius)
    lower = max(0.0, lower_raw)
    upper = max(0.0, upper_raw)
    return lower, upper, n, bool(lower_raw < 0), "CALIBRATED"


def rolling_intervals(predictions):
    """Retain every OOS row, including cold starts, for coverage auditing."""
    rows = []
    for (horizon, origin), group in predictions.groupby(["horizon", "origin_period"], sort=True):
        history = calibration_history(predictions, horizon, origin)
        residuals = (history.actual - history.predicted).to_numpy()
        for r in group.itertuples():
            lower, upper, n, clipped, status = _interval(r.predicted, residuals)
            rows.append({"zone_id": r.zone_id, "horizon_months": horizon,
                "origin_period": origin, "target_period": r.target_period,
                "actual": r.actual, "forecast_value": r.predicted,
                "residual_available_at": r.residual_available_at,
                "interval_lower_80": lower, "interval_upper_80": upper,
                "interval_width": upper - lower, "lower_clipped": clipped,
                "covered": float(lower <= r.actual <= upper) if status == "CALIBRATED" else np.nan,
                "n_calibration_points": n, "n_calibration_cuts": history.origin_period.nunique(),
                "max_calibration_available_at": history.residual_available_at.max(),
                "uncertainty_status": status})
    return pd.DataFrame(rows, columns=["zone_id", "horizon_months", "origin_period", "target_period",
        "actual", "forecast_value", "residual_available_at", "interval_lower_80", "interval_upper_80",
        "interval_width", "lower_clipped", "covered", "n_calibration_points", "n_calibration_cuts",
        "max_calibration_available_at", "uncertainty_status"])


def summarize_coverage(backtest):
    metrics = []
    for horizon in HORIZONS:
        all_rows = backtest[backtest.horizon_months.eq(horizon)]
        source = all_rows[all_rows.uncertainty_status.eq("CALIBRATED")]
        per_cut = source.groupby("origin_period").covered.mean()
        metrics.append({"horizon_months": horizon, "calibration_method": METHOD,
            "target_coverage": TARGET_COVERAGE, "observed_coverage": source.covered.mean(),
            "coverage_error": source.covered.mean() - TARGET_COVERAGE,
            "mean_interval_width": source.interval_width.mean(),
            "median_interval_width": source.interval_width.median(), "n_predictions": len(source),
            "n_calibration_failures": len(all_rows) - len(source),
            "n_failed_origins": all_rows.origin_period.nunique() - source.origin_period.nunique(),
            "n_evaluable_origins": source.origin_period.nunique(),
            "n_origins_total": all_rows.origin_period.nunique(),
            "cut_coverage_min": per_cut.min(), "cut_coverage_max": per_cut.max(),
            "cut_coverage_std": per_cut.std(ddof=0)})
    return pd.DataFrame(metrics)


def _historical_calibration_metrics(predictions):
    return summarize_coverage(rolling_intervals(predictions))


def build_uncertainty(operational: pd.DataFrame, predictions: pd.DataFrame, backtest=None) -> pd.DataFrame:
    if operational[KEY].isna().any().any() or operational.duplicated(KEY).any():
        raise ValueError("Operational key must be unique")
    if not operational.model_used.eq("PERSISTENCE").all() or not operational.target_unit.eq(UNIT).all():
        raise ValueError("Only persistence in activity endpoints is supported")
    if not operational.horizon_months.isin(HORIZONS).all():
        raise ValueError("Unsupported horizon")
    if backtest is None:
        backtest = rolling_intervals(predictions)
    rows = operational.copy()
    intervals = []
    for row in rows.itertuples(index=False):
        matches = predictions[predictions.zone_id.eq(row.zone_id) & predictions.horizon.eq(row.horizon_months) &
            predictions.origin_period.eq(row.origin_period) & predictions.target_period.eq(row.target_period)]
        if len(matches) != 1 or not np.isclose(matches.predicted.iloc[0], row.forecast_value):
            raise ValueError("Operational row must match a persisted OOS prediction")
        residuals = _calibration_residuals(predictions, int(row.horizon_months), row.origin_period)
        history = calibration_history(predictions, row.horizon_months, row.origin_period)
        previous = backtest[backtest.horizon_months.eq(row.horizon_months) &
            (pd.to_datetime(backtest.residual_available_at) < pd.Period(row.origin_period, freq="M").to_timestamp()) &
            (backtest.origin_period < row.origin_period)]
        lower, upper, n_points, clipped, status = _interval(float(row.forecast_value), residuals)
        intervals.append({
            "interval_lower_80": lower,
            "interval_upper_80": upper,
            "interval_width": upper - lower if np.isfinite(lower) and np.isfinite(upper) else np.nan,
            "calibration_method": METHOD,
            "target_coverage": TARGET_COVERAGE,
            "validation_coverage": previous.covered.mean(),
            "n_validation_predictions": int(previous.covered.notna().sum()),
            "n_calibration_points": n_points,
            "n_calibration_cuts": history.origin_period.nunique(),
            "max_calibration_available_at": history.residual_available_at.max(),
            "calibration_cutoff": pd.Period(row.origin_period, freq="M").to_timestamp().isoformat(),
            "artifact_role": "RETROSPECTIVE_REPLAY",
            "lower_clipped": clipped,
            "uncertainty_status": status,
        })
    return pd.concat([rows.reset_index(drop=True), pd.DataFrame(intervals)], axis=1)


def _context_direction(value: float, feature: str = "growth_1") -> str:
    if not np.isfinite(value):
        return "UNAVAILABLE"
    if feature in {"neighbor_trips_lag1", "rolling_mean_3", "neighbor_observation_coverage"}:
        return "LEVEL"
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    return "NEUTRAL"


def _context_label(feature: str) -> str:
    return {
        "growth_1": "crecimiento reciente",
        "growth_3": "crecimiento trimestral",
        "rolling_mean_3": "media móvil trimestral",
        "trend_3": "tendencia trimestral",
        "neighbor_trips_lag1": "actividad vecinal reciente",
        "neighbor_growth_lag1": "crecimiento vecinal reciente",
        "neighbor_observation_coverage": "cobertura vecinal",
    }[feature]


def build_explanations(operational: pd.DataFrame, uncertainty=None, matrix=None) -> pd.DataFrame:
    columns = ["zone_id", "origin_period", "horizon", "target_period", "issue_time"] + list(SAFE_CONTEXT)
    if matrix is None:
        matrix = pd.read_csv(INPUTS["matrix"], usecols=columns)
    matrix = matrix[columns].rename(columns={"horizon": "horizon_months"})
    context = operational[["zone_id", "colonia", "horizon_months", "origin_period", "target_period"]].copy()
    context = context.merge(matrix, on=KEY + ["origin_period", "target_period"], how="left", validate="one_to_one", indicator=True)
    if context.pop("_merge").ne("both").any():
        raise ValueError("Missing origin-frozen context row")
    context["spatial_context_available"] = context.neighbor_trips_lag1.notna() & context.neighbor_observation_coverage.gt(0)
    context["context_coverage"] = context["neighbor_observation_coverage"]
    for i in range(1, 4):
        context[f"context_signal_{i}_feature"] = "NONE"
        context[f"context_signal_{i}"] = "SIN_DATO"
        context[f"context_signal_{i}_value"] = np.nan
        context[f"context_signal_{i}_direction"] = "UNAVAILABLE"
    for index, row in context.iterrows():
        # One recent growth, one temporal level/trend and one spatial signal.
        # No cross-zone quantile labels and no outcome-driven feature selection.
        slots = [("growth_1", "growth_3"), ("trend_3", "rolling_mean_3"),
                 ("neighbor_growth_lag1", "neighbor_trips_lag1")]
        for slot, candidates in enumerate(slots, start=1):
            for feature in candidates:
                value = row[feature]
                if pd.isna(value) or not np.isfinite(value):
                    continue
                formatted = f"{value * 100:.2f}%" if "growth" in feature else f"{value:.2f} endpoints"
                if feature == "trend_3":
                    formatted += "/mes"
                context.at[index, f"context_signal_{slot}"] = f"{_context_label(feature)}: {formatted} (contexto no causal)"
                context.at[index, f"context_signal_{slot}_feature"] = feature
                context.at[index, f"context_signal_{slot}_value"] = value
                context.at[index, f"context_signal_{slot}_direction"] = _context_direction(value, feature)
                break
    context["forecast_model"] = "PERSISTENCE"
    context["forecast_explanation"] = "El forecast mantiene el nivel de actividad registrado en su origen: persistencia fue seleccionada por su desempeño retrospectivo. Las señales contextuales no modifican esta predicción."
    context["limitations"] = np.where(
        context.spatial_context_available,
        "Las señales vecinales son contextuales y no implican causalidad; la geometría y disponibilidad espacial son parciales.",
        "Las señales espaciales no están disponibles para este origen; el contexto no implica causalidad.",
    )
    context["limitations"] += " Catálogo de estaciones sin vigencia histórica verificada. Pronóstico retrospectivo; no es una corrida futura común."
    if uncertainty is not None:
        statuses = uncertainty.set_index(KEY).uncertainty_status
        for index, row in context.iterrows():
            if statuses.loc[(row.zone_id, row.horizon_months)] != "CALIBRATED":
                context.at[index, "limitations"] += " Historia insuficiente para un intervalo."
    context["explanation_version"] = EXPLANATION_VERSION
    return context[["zone_id", "colonia", "horizon_months", "origin_period", "target_period", "issue_time", "forecast_model", "forecast_explanation",
                    "context_signal_1_feature", "context_signal_2_feature", "context_signal_3_feature",
                    "context_signal_1", "context_signal_1_value", "context_signal_1_direction",
                    "context_signal_2", "context_signal_2_value", "context_signal_2_direction",
                    "context_signal_3", "context_signal_3_value", "context_signal_3_direction",
                    "spatial_context_available", "context_coverage", "limitations", "explanation_version"]]


def build_product(uncertainty: pd.DataFrame, explanations: pd.DataFrame) -> pd.DataFrame:
    if explanations.duplicated(KEY).any() or uncertainty.duplicated(KEY).any():
        raise ValueError("Duplicate product key")
    joins = KEY + ["colonia", "origin_period", "target_period"]
    product = uncertainty.merge(explanations, on=joins, how="outer", validate="one_to_one", indicator=True)
    if product.pop("_merge").ne("both").any():
        raise ValueError("Mismatched explanation/forecast origins or key universe")
    return product


def run() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, dict]:
    predictions = prepare_predictions(pd.read_csv(INPUTS["predictions"]), pd.read_csv(INPUTS["panel"]), pd.read_csv(INPUTS["splits"]))
    operational = pd.read_csv(INPUTS["operational"])
    policy_meta = json.loads(INPUTS["policy_metadata"].read_text())
    policy = pd.read_csv(INPUTS["policy"])
    if policy.horizon_months.duplicated().any() or not policy.primary_model.eq("PERSISTENCE").all():
        raise ValueError("Policy changed; uncertainty requires a persistence policy")
    expected = operational[KEY + ["validation_status"]].merge(policy[["horizon_months", "validation_status"]], on="horizon_months", suffixes=("", "_policy"), validate="many_to_one")
    if len(expected) != len(operational) or expected.validation_status.ne(expected.validation_status_policy).any():
        raise ValueError("Operational validation status does not match policy")
    backtest = rolling_intervals(predictions)
    uncertainty = build_uncertainty(operational, predictions, backtest)
    metrics = summarize_coverage(backtest)
    metrics.attrs["backtest"] = backtest
    explanations = build_explanations(operational, uncertainty)
    product = build_product(uncertainty, explanations)
    common = {
        "pipeline_version": "2.0-phase6",
        "git_commit": _git_commit(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_policy_version": policy_meta.get("pipeline_version"),
        "model_used": "PERSISTENCE",
        "uncertainty_method": METHOD,
        "target_coverage": TARGET_COVERAGE,
        "calibration_window_rule": "Same-horizon EVALUATION_ALL OOS residuals: origin and target < current origin month; max(target month end, target earliest availability) strictly before start of current origin month",
        "quantile_rule": "k=ceil((n+1)*0.80); kth smallest absolute residual; no exchangeability guarantee for dependent rolling data",
        "validation_coverage_rule": "Per-row coverage uses only previously evaluable intervals with outcomes available before the same origin cutoff; aggregate metrics are retrospective diagnostics",
        "min_points_rationale": "30 is a pragmatic cold-start floor (about six observations in the 20% tail), not 30 independent cuts or a coverage guarantee",
        "method_choice": "Symmetric absolute residuals fixed before final evaluation for simplicity, containment of the point forecast and a single estimated tail; signed residual intervals deferred, no method tuning",
        "min_calibration_points": MIN_CALIBRATION_POINTS,
        "context_feature_rules": {"safe_features": list(SAFE_CONTEXT), "unsafe_snapshots_in_forecast": False,
            "source": "Phase 4 origin-frozen matrix; no future target columns loaded", "levels": "No LOW/MEDIUM/HIGH labels; sign only for growth and trend"},
        "shap_enabled": False,
        "limitations": [
            "Intervals are empirical residual bands, not normal-theory prediction intervals.",
            "Calibration is global by horizon, not zone-specific.",
            "Rows without 30 prior known residuals are explicitly insufficient.",
            "Context signals are descriptive and do not establish causality.",
            "No 36- or 60-month scenarios are generated.",
            "Historical target availability is only a lower bound; publication/revision vintages remain unverified.",
            "Operational CSV is a historical replay with heterogeneous origins, not live future forecasts.",
            "Dependent cuts/zones and varying activity scales invalidate an automatic conformal coverage guarantee; 12-month validation has very few post-cold-start cuts.",
        ],
        "implementation_sha256": {"src/models/uncertainty_v2.py": _sha256(Path(__file__))},
        "source_sha256": {str(path.relative_to(ROOT)): _sha256(path) for path in INPUTS.values()},
    }
    uncertainty_meta = {**common, "output": "forecast_uncertainty_v2.csv"}
    explanation_meta = {**common, "output": "forecast_explanations_v2.csv", "explanation_version": EXPLANATION_VERSION}
    return uncertainty, metrics, explanations, product, uncertainty_meta, explanation_meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uncertainty", type=Path, default=ROOT / "data/processed/forecast_uncertainty_v2.csv")
    parser.add_argument("--metrics", type=Path, default=ROOT / "data/processed/uncertainty_metrics_v2.csv")
    parser.add_argument("--explanations", type=Path, default=ROOT / "data/processed/forecast_explanations_v2.csv")
    parser.add_argument("--product", type=Path, default=ROOT / "data/processed/forecast_product_v2.csv")
    parser.add_argument("--backtest", type=Path, default=ROOT / "data/processed/uncertainty_backtest_v2.csv")
    parser.add_argument("--uncertainty-metadata", type=Path, default=ROOT / "data/processed/forecast_uncertainty_v2.metadata.json")
    parser.add_argument("--explanation-metadata", type=Path, default=ROOT / "data/processed/forecast_explanations_v2.metadata.json")
    args = parser.parse_args()
    uncertainty, metrics, explanations, product, uncertainty_meta, explanation_meta = run()
    backtest = metrics.attrs.pop("backtest")
    args.uncertainty.parent.mkdir(parents=True, exist_ok=True)
    uncertainty.to_csv(args.uncertainty, index=False)
    metrics.to_csv(args.metrics, index=False)
    explanations.to_csv(args.explanations, index=False)
    product.to_csv(args.product, index=False)
    backtest.to_csv(args.backtest, index=False)
    uncertainty_meta["output_sha256"] = {str(path): _sha256(path) for path in (args.uncertainty, args.metrics, args.backtest)}
    explanation_meta["output_sha256"] = {str(path): _sha256(path) for path in (args.explanations, args.product)}
    args.uncertainty_metadata.write_text(json.dumps(uncertainty_meta, indent=2) + "\n")
    args.explanation_metadata.write_text(json.dumps(explanation_meta, indent=2) + "\n")
    print(metrics.to_string(index=False))
    print(f"uncertainty rows: {len(uncertainty)}; explanations: {len(explanations)}; product: {len(product)}")


if __name__ == "__main__":
    main()
