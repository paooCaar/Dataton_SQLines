"""Citywide scenario sensitivity for 36/60 months, never a causal elasticity.

The CSV is a frozen comparable annual series. No network requests, historical
methodology mixing, local traffic inference, or short-term forecast changes.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOMTOM_PATH = ROOT / "data/external/tomtom/tomtom_traffic_index_cdmx_v2.csv"
TRAFFIC_PASS_THROUGH = 0.25
REQUIRED_COLUMNS = {"year", "congestion_level_pct", "yoy_change_pp", "observation_type",
                    "is_derived", "source_note", "source_url"}


@dataclass(frozen=True)
class TomTomSummary:
    latest_year: int
    latest_congestion_pct: float
    recent_change_pp: float
    stress_magnitude_pp_per_year: float
    pass_through: float = TRAFFIC_PASS_THROUGH


def validate_tomtom(frame):
    if not REQUIRED_COLUMNS.issubset(frame.columns) or frame.empty:
        raise ValueError("Fuente TomTom vacía o incompleta")
    clean = frame.copy()
    for column in ("year", "congestion_level_pct", "yoy_change_pp"):
        clean[column] = pd.to_numeric(clean[column], errors="raise")
    if (not np.isfinite(clean[["year", "congestion_level_pct"]]).all().all()
            or clean.year.mod(1).ne(0).any() or clean.year.le(0).any()
            or clean.year.duplicated().any() or clean.congestion_level_pct.lt(0).any()):
        raise ValueError("Años o niveles TomTom inválidos/duplicados")
    if not clean.observation_type.eq("annual_comparable").all():
        raise ValueError("Solo se admiten observaciones annual_comparable de la misma metodología")
    for column in ("source_note", "source_url"):
        if clean[column].isna().any() or clean[column].astype(str).str.strip().eq("").any():
            raise ValueError("Falta procedencia de la fuente TomTom")
    derived = clean.is_derived.astype(str).str.lower().map({"true": True, "false": False})
    if derived.isna().any():
        raise ValueError("is_derived debe ser booleano explícito")
    clean["is_derived"] = derived
    clean["year"] = clean.year.astype(int)
    clean = clean.sort_values("year").reset_index(drop=True)
    changes = clean.yoy_change_pp.dropna()
    if not np.isfinite(changes).all() or pd.isna(clean.iloc[-1].yoy_change_pp):
        raise ValueError("Se requiere cambio reciente finito y explícito; no se infiere de otra edición")
    if clean.iloc[-1].is_derived:
        raise ValueError("El dato más reciente debe ser observado")
    # Published deltas must reconcile with the comparable preceding year.
    for previous, latest in zip(clean.iloc[:-1].itertuples(), clean.iloc[1:].itertuples()):
        if latest.year == previous.year + 1 and pd.notna(latest.yoy_change_pp):
            if not np.isclose(latest.congestion_level_pct - previous.congestion_level_pct,
                              latest.yoy_change_pp, rtol=0, atol=1e-8):
                raise ValueError("Cambio TomTom inconsistente con el año previo comparable")
    return clean


def load_tomtom_traffic_index(path=DEFAULT_TOMTOM_PATH):
    return validate_tomtom(pd.read_csv(Path(path)))


def summarize_tomtom(frame, pass_through=TRAFFIC_PASS_THROUGH):
    if not np.isfinite(pass_through) or not 0 <= pass_through <= 1:
        raise ValueError("pass_through debe ser finito y estar entre 0 y 1")
    latest = validate_tomtom(frame).iloc[-1]
    return TomTomSummary(int(latest.year), float(latest.congestion_level_pct),
                         float(latest.yoy_change_pp), abs(float(latest.yoy_change_pp)), float(pass_through))


def traffic_scenario_parameters(summary):
    return {"low": -summary.stress_magnitude_pp_per_year, "base": 0.0,
            "high": summary.stress_magnitude_pp_per_year}


def projected_congestion(current_congestion_pct, annual_change_pp, years):
    if (not np.isfinite([current_congestion_pct, annual_change_pp, years]).all()
            or current_congestion_pct < 0 or years < 0):
        raise ValueError("Congestión/años deben ser finitos y no negativos")
    value = current_congestion_pct + annual_change_pp * years
    if not np.isfinite(value):
        raise ValueError("Proyección de congestión no finita")
    # Congestion is extra travel time; >100% is possible. Only floor at zero.
    return max(0.0, float(value))


def traffic_activity_multiplier(current_congestion_pct, future_congestion_pct,
                                pass_through=TRAFFIC_PASS_THROUGH):
    if (not np.isfinite([current_congestion_pct, future_congestion_pct, pass_through]).all()
            or min(current_congestion_pct, future_congestion_pct) < 0 or not 0 <= pass_through <= 1):
        raise ValueError("Congestión o sensibilidad inválida")
    return float(((1 + future_congestion_pct / 100) / (1 + current_congestion_pct / 100)) ** pass_through)


def build_traffic_scenario_bundle(tomtom, years_after_anchor, pass_through=TRAFFIC_PASS_THROUGH):
    summary = summarize_tomtom(tomtom, pass_through)
    result = {
        "tomtom_latest_year": summary.latest_year,
        "tomtom_congestion_pct": summary.latest_congestion_pct,
        "tomtom_recent_change_pp": summary.recent_change_pp,
        "traffic_pass_through": summary.pass_through,
        "traffic_stress_magnitude_pp_per_year": summary.stress_magnitude_pp_per_year,
    }
    for name, change in traffic_scenario_parameters(summary).items():
        target = projected_congestion(summary.latest_congestion_pct, change, years_after_anchor)
        multiplier = traffic_activity_multiplier(summary.latest_congestion_pct, target, summary.pass_through)
        result.update({f"traffic_{name}_change_pp_per_year": change,
                       f"traffic_{name}_target_congestion_pct": target,
                       f"traffic_{name}_multiplier": multiplier,
                       f"traffic_{name}_adjustment_pct": (multiplier - 1) * 100})
    return result
