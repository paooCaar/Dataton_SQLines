"""Read-only contracts and presentation helpers for the independent V2 app."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/processed"
HORIZONS = (1, 3, 6, 12)
UNIT = "station_endpoints_per_calendar_month"
DIRECTIONS = {"POSITIVE": "AUMENTO", "NEUTRAL": "ESTABLE", "NEGATIVE": "DISMINUCIÓN"}
CONTEXT_LABELS = {
    "growth_1": "Crecimiento reciente", "growth_3": "Crecimiento trimestral",
    "trend_3": "Tendencia reciente", "rolling_mean_3": "Media trimestral",
    "neighbor_growth_lag1": "Crecimiento vecinal", "neighbor_trips_lag1": "Actividad vecinal",
}
REQUIRED = {"zone_id", "colonia", "origin_period", "horizon_months", "target_period",
    "reference_value", "forecast_value", "forecast_change_abs", "forecast_change_pct", "direction",
    "interval_lower_80", "interval_upper_80", "model_used", "validation_status", "forecast_role",
    "forecast_explanation", "context_signal_1", "context_signal_2", "context_signal_3",
    "context_coverage", "uncertainty_status", "target_unit", "artifact_role"}


def validate_product(frame, policy, current=False):
    if not REQUIRED.issubset(frame.columns) or frame.empty:
        raise ValueError("Contrato incompleto o producto vacío")
    if frame[["zone_id", "horizon_months", "origin_period", "target_period"]].isna().any().any() or frame.duplicated(["zone_id", "horizon_months"]).any():
        raise ValueError("Claves duplicadas o ausentes")
    role = "CURRENT_FORECAST" if current else "RETROSPECTIVE_REPLAY"
    if not frame.artifact_role.eq(role).all():
        raise ValueError("No mezclar emisión actual y retrospectiva")
    if current and frame.origin_period.nunique() != 1:
        raise ValueError("La emisión actual requiere un origen común")
    if not frame.horizon_months.isin(HORIZONS).all():
        raise ValueError("Horizonte no validado; 36/60 meses son SCENARIO_ONLY")
    expected = frame.merge(policy[["horizon_months", "primary_model", "validation_status", "forecast_role"]],
                           on="horizon_months", suffixes=("", "_policy"), how="left", validate="many_to_one")
    if (expected.model_used.ne(expected.primary_model).any()
            or expected.validation_status.ne(expected.validation_status_policy).any()
            or expected.forecast_role.ne(expected.forecast_role_policy).any()):
        raise ValueError("El producto contradice la política")
    if not frame.target_unit.eq(UNIT).all():
        raise ValueError("La actividad debe expresarse en endpoints mensuales")
    if not np.isfinite(frame[["forecast_value", "reference_value"]]).all().all() or (frame[["forecast_value", "reference_value"]] < 0).any().any():
        raise ValueError("Actividad inválida")
    if (not frame.model_used.eq("PERSISTENCE").all()
            or not np.allclose(frame.forecast_value, frame.reference_value)
            or not np.allclose(frame.forecast_change_abs, 0)
            or not frame.direction.eq("NEUTRAL").all()):
        raise ValueError("El forecast no corresponde a persistencia")
    nonzero = frame.reference_value.ne(0)
    if not np.allclose(frame.loc[nonzero, "forecast_change_pct"], 0) or frame.loc[~nonzero, "forecast_change_pct"].notna().any():
        raise ValueError("Cambio porcentual incoherente")
    origin = pd.PeriodIndex(frame.origin_period, freq="M")
    target = pd.PeriodIndex(frame.target_period, freq="M")
    if not np.array_equal(target.asi8 - origin.asi8, frame.horizon_months):
        raise ValueError("Horizonte calendario incoherente")
    lower, upper = frame.interval_lower_80, frame.interval_upper_80
    present = lower.notna() | upper.notna()
    if (not np.isfinite(frame.loc[present, ["interval_lower_80", "interval_upper_80"]]).all().all()
            or (lower[present] < 0).any() or (lower[present] > frame.loc[present, "forecast_value"]).any()
            or (upper[present] < frame.loc[present, "forecast_value"]).any()):
        raise ValueError("Intervalo inválido")
    return frame


def number(value, decimals=0, suffix=""):
    if pd.isna(value) or not np.isfinite(float(value)):
        return "Sin dato"
    return f"{value:,.{decimals}f}{suffix}"


def safe_context(row):
    """Render typed, whitelisted signals only; never trust free-form explanations."""
    signals = []
    for i in (1, 2, 3):
        feature = row.get(f"context_signal_{i}_feature")
        value = row.get(f"context_signal_{i}_value", np.nan)
        if feature not in CONTEXT_LABELS or pd.isna(value) or not np.isfinite(value):
            signals.append("Señal no disponible")
            continue
        label = CONTEXT_LABELS[feature]
        amount = number(value * 100, 2, "%") if "growth" in feature else number(value, 2, " endpoints/mes" if feature == "trend_3" else " endpoints")
        signals.append(f"{label}: {amount}")
    return signals


def alias_lookup(catalog):
    lookup = {}
    for row in catalog.itertuples():
        for name in set([row.colonia] + json.loads(row.aliases)):
            key = (row.alcaldia, name)
            if key in lookup and lookup[key] != row.zone_id:
                raise ValueError("Alias ambiguo dentro de la alcaldía")
            lookup[key] = row.zone_id
    return lookup


def geometry_for_catalog(geojson, catalog):
    result = copy.deepcopy(geojson)
    lookup = alias_lookup(catalog)
    features, seen = [], set()
    for feature in result["features"]:
        prop = feature["properties"]
        zone = lookup.get((prop.get("alcaldia"), prop.get("colonia")))
        if zone is None or not feature.get("geometry"):
            continue
        if zone in seen:
            raise ValueError("Más de una geometría por zona")
        feature["id"] = zone
        seen.add(zone)
        features.append(feature)
    result["features"] = features
    return result


def attach_scores(catalog, scores):
    """Canonical name first, then unique alias in SAME municipality; no blending."""
    records = []
    for row in catalog.itertuples():
        candidates = scores[scores.alcaldia.eq(row.alcaldia) & scores.colonia.isin(json.loads(row.aliases))]
        canonical = candidates[candidates.colonia.eq(row.colonia)]
        choice = canonical if len(canonical) == 1 else candidates
        record = {"zone_id": row.zone_id, "opportunity_score": np.nan, "opportunity_category": "Sin dato", "score_source_colonia": None}
        if len(choice) == 1:
            item = choice.iloc[0]
            record.update(opportunity_score=item.score, opportunity_category=item.categoria, score_source_colonia=item.colonia)
        records.append(record)
    return pd.DataFrame(records)


def zone_view(product, catalog, geometry, scores, horizon):
    if horizon not in HORIZONS:
        return pd.DataFrame()  # no numeric scenarios
    # LEFT join from the catalog retains zones without forecast or geometry.
    frame = catalog[["zone_id", "colonia", "alcaldia"]].merge(
        product[product.horizon_months.eq(horizon)].drop(columns=["colonia", "alcaldia"], errors="ignore"),
        on="zone_id", how="left", validate="one_to_one").merge(scores, on="zone_id", how="left", validate="one_to_one")
    mapped = {f["id"] for f in geometry["features"]}
    frame["map_status"] = frame.zone_id.map(lambda z: "Disponible" if z in mapped else "Sin geometría disponible para mapa")
    frame["direction_label"] = frame.direction.map(DIRECTIONS).fillna("Sin forecast")
    frame["relative_interval_width"] = (frame.interval_upper_80 - frame.interval_lower_80).div(frame.forecast_value.where(frame.forecast_value.gt(0)))
    return frame


def validation_table(policy, coverage):
    frame = policy[["horizon_months", "MAE_primary", "RMSE_primary", "n_cuts", "validation_status"]].merge(
        coverage[["horizon_months", "observed_coverage", "target_coverage", "n_evaluable_origins", "n_predictions"]],
        on="horizon_months", validate="one_to_one")
    return frame.rename(columns={"MAE_primary": "MAE", "RMSE_primary": "RMSE", "n_cuts": "forecast_cuts", "n_evaluable_origins": "interval_cuts"})


def load_inputs(data=DATA):
    read = lambda name: pd.read_csv(data / name)
    policy = read("model_policy_v2.csv")
    historic = validate_product(read("forecast_product_v2.csv"), policy)
    catalog = read("catalogo_zonas_v2.csv")
    geo_path = data / "zonas_geometria_v2.geojson"
    if not geo_path.exists():
        geo_path = data / "zonas_geometria.geojson"
    geometry = geometry_for_catalog(json.loads(geo_path.read_text()), catalog)
    current_path = data / "current_forecast_product_v2.csv"
    current, metadata = None, None
    if current_path.exists():
        metadata = json.loads(current_path.with_suffix(".metadata.json").read_text())
        digest = hashlib.sha256(current_path.read_bytes()).hexdigest()
        if digest != metadata["output_sha256"]["data/processed/current_forecast_product_v2.csv"]:
            raise ValueError("La emisión actual no coincide con su metadata")
        current = validate_product(pd.read_csv(current_path), policy, current=True)
        if metadata["common_origin_period"] != current.origin_period.iloc[0]:
            raise ValueError("Origen de metadata incoherente")
        for h in HORIZONS:
            if set(current[current.horizon_months.eq(h)].zone_id) != set(catalog.zone_id):
                raise ValueError("La emisión actual no cubre el catálogo completo")
    coverage = read("uncertainty_metrics_v2.csv")
    return {"policy": policy, "historical": historic, "current": current, "metadata": metadata,
            "catalog": catalog, "geometry": geometry, "coverage": coverage,
            "validation": validation_table(policy, coverage), "backtest": read("uncertainty_backtest_v2.csv")}
