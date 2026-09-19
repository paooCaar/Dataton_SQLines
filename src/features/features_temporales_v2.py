"""Build causal temporal features from the versioned ECOBICI panel.

Every feature on row ``t`` uses target observations strictly before ``t``.
The calendar variables are known at ``t`` and do not inspect the target. Missing
and unknown activity statuses remain missing; they are never converted to zero.
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
VERSION = "2.0-phase2-temporal"
AVAILABLE_STATUSES = frozenset({"OBSERVED", "ZERO_DEMAND"})
LAGS = (1, 3, 6, 12)
WINDOWS = (3, 6, 12)
FEATURE_COLUMNS = (
    "lag_1", "lag_3", "lag_6", "lag_12",
    "rolling_mean_3", "rolling_mean_6", "rolling_mean_12",
    "rolling_std_3", "rolling_std_6", "rolling_std_12",
    "growth_1", "growth_3", "growth_6", "growth_12",
    "month", "year", "sin_month", "cos_month",
    "trend_3", "trend_6", "trend_12",
)


def _validate_panel(panel: pd.DataFrame) -> None:
    required = {"zone_id", "periodo", "fecha", "data_status", "viajes_total"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"Panel missing required columns: {sorted(missing)}")
    if panel.duplicated(["zone_id", "periodo"]).any():
        raise ValueError("Temporal features require a unique zone/month key")
    ordered = panel.sort_values(["zone_id", "fecha"]).reset_index(drop=True)
    if not ordered[["zone_id", "periodo"]].equals(panel[["zone_id", "periodo"]].reset_index(drop=True)):
        raise ValueError("Panel must be sorted by zone_id and calendar month")
    for _, group in panel.groupby("zone_id", sort=False):
        periods = pd.PeriodIndex(group["periodo"], freq="M")
        expected = pd.period_range(periods.min(), periods.max(), freq="M")
        if not periods.equals(expected):
            raise ValueError("Temporal features require a continuous calendar per zone")


def _slope(values: np.ndarray) -> float:
    if len(values) == 0 or np.isnan(values).any():
        return np.nan
    x = np.arange(len(values), dtype=float)
    x_centered = x - x.mean()
    y_centered = values - values.mean()
    denominator = float(np.dot(x_centered, x_centered))
    return float(np.dot(x_centered, y_centered) / denominator) if denominator else np.nan


def build_temporal_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Return a causal feature table with one row per zone and calendar month."""
    panel = panel.copy()
    panel["fecha"] = pd.to_datetime(panel["fecha"])
    panel = panel.sort_values(["zone_id", "fecha"]).reset_index(drop=True)
    _validate_panel(panel)

    keep = [
        column for column in [
            "zone_id", "colonia", "alcaldia", "periodo", "fecha", "data_status",
            "datos_disponibles", "archivo_disponible", "source_status", "viajes_total",
            "target_demanda", "run_id",
        ] if column in panel.columns
    ]
    out = panel[keep].copy()
    target = panel["viajes_total"].where(panel["data_status"].isin(AVAILABLE_STATUSES))
    grouped = target.groupby(panel["zone_id"], sort=False)

    for lag in LAGS:
        out[f"lag_{lag}"] = grouped.shift(lag)

    past = grouped.shift(1)
    for window in WINDOWS:
        out[f"rolling_mean_{window}"] = past.groupby(panel["zone_id"], sort=False).transform(
            lambda values: values.rolling(window, min_periods=window).mean())
        out[f"rolling_std_{window}"] = past.groupby(panel["zone_id"], sort=False).transform(
            lambda values: values.rolling(window, min_periods=window).std())
        out[f"trend_{window}"] = past.groupby(panel["zone_id"], sort=False).transform(
            lambda values: values.rolling(window, min_periods=window).apply(_slope, raw=True))

    for lag in LAGS:
        prior = grouped.shift(lag + 1)
        denominator_valid = prior.notna() & prior.ne(0)
        out[f"growth_{lag}"] = ((past - prior) / prior.abs()).where(
            denominator_valid & past.notna())

    out["month"] = out["fecha"].dt.month.astype("int64")
    out["year"] = out["fecha"].dt.year.astype("int64")
    angle = 2 * np.pi * (out["month"] - 1) / 12
    out["sin_month"] = np.sin(angle)
    out["cos_month"] = np.cos(angle)
    out["feature_version"] = VERSION
    out["feature_target"] = "viajes_total"
    out["feature_causality"] = "target_through_t_minus_1"

    expected = set(FEATURE_COLUMNS)
    if expected.difference(out.columns):
        raise AssertionError(f"Feature construction incomplete: {expected.difference(out.columns)}")
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_metadata(features: pd.DataFrame, source_path: Path, source_metadata: dict | None) -> dict:
    source_metadata = source_metadata or {}
    return {
        "pipeline_version": VERSION,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source_path.relative_to(ROOT)),
        "source_sha256": _sha256(source_path),
        "source_panel_run_id": source_metadata.get("run_id"),
        "target": "viajes_total",
        "rows": int(len(features)),
        "zones": int(features.zone_id.nunique()),
        "period_min": features.periodo.min(),
        "period_max": features.periodo.max(),
        "features": list(FEATURE_COLUMNS),
        "available_statuses": sorted(AVAILABLE_STATUSES),
        "missing_policy": "MISSING_DATA and UNKNOWN_ACTIVITY_STATUS remain NaN; no zero imputation",
        "causality_policy": "lags and derived windows use target through t-1; calendar variables are known at t",
        "growth_policy": "(y[t-1] - y[t-1-k]) / abs(y[t-1-k]); zero or missing denominator yields NaN",
        "rolling_policy": "full windows only; any missing member yields NaN",
        "trend_policy": "ordinary least-squares slope over the previous full calendar window",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/processed/panel_demanda_v2.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/features_temporales_v2.csv")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data/processed/features_temporales_v2.metadata.json")
    args = parser.parse_args()
    panel = pd.read_csv(args.input)
    features = build_temporal_features(panel)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(args.output, index=False)
    source_meta_path = args.input.with_name("panel_demanda_v2.metadata.json")
    source_meta = json.loads(source_meta_path.read_text()) if source_meta_path.exists() else {}
    args.metadata.write_text(json.dumps(build_metadata(features, args.input, source_meta), indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "rows": len(features), "features": list(FEATURE_COLUMNS)}, indent=2))


if __name__ == "__main__":
    main()
