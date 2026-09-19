"""Expanding-window validation for common V2 demand baselines.

The evaluator forecasts the exact month ``origin + horizon``. Splits require
the same complete set of zones for persistence, seasonal naive and Theil-Sen,
and exclude any origin whose target or seasonal reference is missing.
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
VERSION = "2.0-phase2-rolling"
HORIZONS = (1, 3, 6, 12)
AVAILABLE_STATUSES = frozenset({"OBSERVED", "ZERO_DEMAND"})
MODELS = ("persistence", "seasonal_naive", "theil_sen")
DIRECTIONAL_ACCURACY_THRESHOLD = 0.0
MIN_THEIL_SEN_HISTORY = 3


def _as_arrays(actual, predicted, origin):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    origin = np.asarray(origin, dtype=float)
    valid = np.isfinite(actual) & np.isfinite(predicted) & np.isfinite(origin)
    return actual[valid], predicted[valid], origin[valid]


def smape(actual, predicted) -> float:
    """Symmetric MAPE in percent; a pair of exact zeros contributes zero."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    denominator = np.abs(actual) + np.abs(predicted)
    values = np.divide(2 * np.abs(predicted - actual), denominator,
                       out=np.zeros_like(denominator, dtype=float), where=denominator != 0)
    return float(np.mean(values) * 100) if len(values) else np.nan


def directional_accuracy(actual, predicted, origin,
                         threshold: float = DIRECTIONAL_ACCURACY_THRESHOLD) -> float:
    """Share of matching directions versus origin; threshold is 0 endpoints.

    A change with absolute magnitude less than or equal to ``threshold`` is
    neutral. The default threshold is exactly zero station endpoints, so a
    neutral actual change is correct only for a neutral prediction.
    """
    actual, predicted, origin = _as_arrays(actual, predicted, origin)
    if len(actual) == 0:
        return np.nan
    actual_delta = actual - origin
    predicted_delta = predicted - origin
    actual_sign = np.where(actual_delta > threshold, 1, np.where(actual_delta < -threshold, -1, 0))
    predicted_sign = np.where(predicted_delta > threshold, 1, np.where(predicted_delta < -threshold, -1, 0))
    return float(np.mean(actual_sign == predicted_sign))


def calculate_metrics(actual, predicted, origin) -> dict[str, float | int]:
    actual, predicted, origin = _as_arrays(actual, predicted, origin)
    if len(actual) == 0:
        return {"n_predictions": 0, "MAE": np.nan, "RMSE": np.nan,
                "sMAPE": np.nan, "R2": np.nan, "directional_accuracy": np.nan}
    errors = predicted - actual
    denominator = float(np.sum((actual - actual.mean()) ** 2))
    r2 = np.nan if denominator == 0 else float(1 - np.sum(errors ** 2) / denominator)
    return {
        "n_predictions": int(len(actual)),
        "MAE": float(np.mean(np.abs(errors))),
        "RMSE": float(np.sqrt(np.mean(errors ** 2))),
        "sMAPE": smape(actual, predicted),
        "R2": r2,
        "directional_accuracy": directional_accuracy(actual, predicted, origin),
    }


def _theil_sen_predict(history_periods: pd.PeriodIndex, history_values: np.ndarray,
                       target_period: pd.Period, min_history: int = MIN_THEIL_SEN_HISTORY) -> float:
    """Robust linear forecast using the median pairwise slope and intercept."""
    valid = np.isfinite(history_values)
    x = np.asarray([period.ordinal for period in history_periods], dtype=float)[valid]
    y = np.asarray(history_values, dtype=float)[valid]
    if len(y) < min_history:
        return np.nan
    slopes = []
    for left in range(len(y) - 1):
        delta_x = x[left + 1:] - x[left]
        slopes.extend(((y[left + 1:] - y[left]) / delta_x).tolist())
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * x))
    return float(intercept + slope * target_period.ordinal)


def _complete_zones(frame: pd.DataFrame, period: str, zones: list[str]) -> bool:
    subset = frame[frame.periodo.eq(period) & frame.viajes_total.notna() &
                   frame.data_status.isin(AVAILABLE_STATUSES)]
    return subset.zone_id.nunique() == len(zones) and set(subset.zone_id) == set(zones)


def _history_complete(frame: pd.DataFrame, origin: pd.Period, zones: list[str], min_history: int) -> bool:
    history = frame[frame.periodo_period <= origin]
    counts = history.dropna(subset=["viajes_total"]).groupby("zone_id").size()
    return all(int(counts.get(zone, 0)) >= min_history for zone in zones)


def evaluate_rolling(features: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS,
                    min_history: int = MIN_THEIL_SEN_HISTORY) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Evaluate baselines on common expanding-window origin/target splits."""
    required = {"zone_id", "periodo", "viajes_total", "data_status"}
    missing = required.difference(features.columns)
    if missing:
        raise ValueError(f"Feature table missing required columns: {sorted(missing)}")
    frame = features.copy()
    frame["periodo"] = frame["periodo"].astype(str)
    frame["periodo_period"] = pd.PeriodIndex(frame["periodo"], freq="M")
    frame = frame.sort_values(["zone_id", "periodo_period"]).reset_index(drop=True)
    periods = pd.period_range(frame.periodo_period.min(), frame.periodo_period.max(), freq="M")
    zones = sorted(frame.zone_id.astype(str).unique())
    frame["zone_id"] = frame.zone_id.astype(str)
    min_history = int(min_history)

    split_rows = []
    prediction_rows = []
    for horizon in horizons:
        for origin in periods:
            target_period = origin + horizon
            split = {
                "split_id": f"h{horizon}_{origin}",
                "horizon": int(horizon),
                "origin_period": str(origin),
                "target_period": str(target_period),
                "seasonal_reference_period": str(target_period - 12),
                "status": "EXCLUDED",
                "reason": "",
                "n_zones": 0,
                "n_predictions": 0,
                "min_history_points": 0,
            }
            if target_period not in periods:
                split["reason"] = "target_outside_calendar"
                split_rows.append(split)
                continue
            checks = [
                ("origin_missing_or_incomplete", _complete_zones(frame, str(origin), zones)),
                ("target_missing_or_incomplete", _complete_zones(frame, str(target_period), zones)),
                ("seasonal_reference_missing_or_incomplete",
                 _complete_zones(frame, str(target_period - 12), zones)),
                ("insufficient_expanding_history", _history_complete(frame, origin, zones, min_history)),
            ]
            failed = [reason for reason, passed in checks if not passed]
            if failed:
                split["reason"] = ";".join(failed)
                split_rows.append(split)
                continue

            origin_values = frame[frame.periodo_period.eq(origin)].set_index("zone_id")["viajes_total"]
            target_values = frame[frame.periodo_period.eq(target_period)].set_index("zone_id")["viajes_total"]
            seasonal_values = frame[frame.periodo_period.eq(target_period - 12)].set_index("zone_id")["viajes_total"]
            for zone in zones:
                zone_history = frame[(frame.zone_id.eq(zone)) &
                                     (frame.periodo_period <= origin) &
                                     frame.viajes_total.notna()].sort_values("periodo_period")
                theil_sen = _theil_sen_predict(
                    pd.PeriodIndex(zone_history.periodo, freq="M"),
                    zone_history.viajes_total.to_numpy(dtype=float), target_period, min_history)
                prediction_rows.append({
                    "split_id": split["split_id"], "horizon": int(horizon),
                    "origin_period": str(origin), "target_period": str(target_period),
                    "zone_id": zone, "actual": float(target_values.loc[zone]),
                    "origin_value": float(origin_values.loc[zone]),
                    "persistence": float(origin_values.loc[zone]),
                    "seasonal_naive": float(seasonal_values.loc[zone]),
                    "theil_sen": theil_sen,
                })
            split.update({"status": "USED", "reason": "", "n_zones": len(zones),
                          "n_predictions": len(zones),
                          "min_history_points": int(min(
                              frame[(frame.zone_id.eq(zone)) &
                                    (frame.periodo_period <= origin) & frame.viajes_total.notna()].shape[0]
                              for zone in zones))})
            split_rows.append(split)

    splits = pd.DataFrame(split_rows)
    predictions = pd.DataFrame(prediction_rows)
    metric_rows = []
    for horizon in horizons:
        horizon_predictions = predictions[predictions.horizon.eq(horizon)]
        for model in MODELS:
            metrics = calculate_metrics(horizon_predictions.actual,
                                        horizon_predictions[model],
                                        horizon_predictions.origin_value)
            used = splits[(splits.horizon == horizon) & splits.status.eq("USED")]
            metric_rows.append({
                "horizon": int(horizon), "model": model,
                "n_splits": int(len(used)), "n_zones_per_split": int(used.n_zones.iloc[0]) if len(used) else 0,
                "origin_min": used.origin_period.min() if len(used) else None,
                "origin_max": used.origin_period.max() if len(used) else None,
                **metrics,
            })
    metrics = pd.DataFrame(metric_rows)
    metadata = {
        "pipeline_version": VERSION,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "target": "viajes_total",
        "horizons": [int(h) for h in horizons],
        "origin_policy": "expanding window; exact target at origin plus horizon",
        "common_zone_policy": "same complete zone set for all three baselines on each split",
        "available_statuses": sorted(AVAILABLE_STATUSES),
        "missing_policy": "MISSING_DATA and UNKNOWN_ACTIVITY_STATUS exclude a split; never imputed as zero",
        "minimum_theil_sen_history": int(min_history),
        "directional_accuracy_threshold": DIRECTIONAL_ACCURACY_THRESHOLD,
        "directional_accuracy_definition": "matching sign of prediction and actual change from origin; zero endpoint threshold",
        "metric_units": {"MAE": "station endpoints", "RMSE": "station endpoints", "sMAPE": "percent",
                         "R2": "unitless", "directional_accuracy": "fraction"},
        "split_counts": {str(h): int((splits.horizon == h).sum()) for h in horizons},
        "used_split_counts": {str(h): int(((splits.horizon == h) & splits.status.eq("USED")).sum()) for h in horizons},
        "limitations": [
            "The common comparison starts only when origin, target and target-minus-12 are complete for all zones.",
            "October 2024 is excluded as MISSING_DATA, never treated as zero.",
            "Theil-Sen is a per-zone expanding robust trend baseline; no covariates are used.",
            "No LightGBM, spatial features, SHAP or uncertainty estimation is included in this phase.",
        ],
    }
    return splits, metrics, {"predictions": predictions, "metadata": metadata}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/processed/features_temporales_v2.csv")
    parser.add_argument("--splits", type=Path, default=ROOT / "data/processed/rolling_splits_v2.csv")
    parser.add_argument("--metrics", type=Path, default=ROOT / "data/processed/baseline_metrics_v2.csv")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data/processed/rolling_validation_v2.metadata.json")
    args = parser.parse_args()
    features = pd.read_csv(args.input)
    splits, metrics, result = evaluate_rolling(features)
    args.splits.parent.mkdir(parents=True, exist_ok=True)
    splits.to_csv(args.splits, index=False)
    metrics.to_csv(args.metrics, index=False)
    metadata = result["metadata"]
    metadata["source_file"] = str(args.input.relative_to(ROOT))
    metadata["source_sha256"] = _sha256(args.input)
    metadata["metrics_file"] = str(args.metrics.relative_to(ROOT))
    metadata["splits_file"] = str(args.splits.relative_to(ROOT))
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n")
    print(metrics.to_string(index=False))
    print(json.dumps(metadata["used_split_counts"], indent=2))


if __name__ == "__main__":
    main()
