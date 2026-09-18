"""Build the parallel monthly ECOBICI activity panel; no models or features.

Usage: python -m src.features.panel_demanda_v2
Legacy outputs and the Streamlit contract are read-only. Output snapshots are
immutable; the V2 convenience files point to the most recently completed run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.ecobici_v2 import (build_catalog, count_chunk, discover_months,
                               load_stations, sha256_file)

ROOT = Path(__file__).resolve().parents[2]
VERSION = "2.0-phase1"
START = "2023-01"
# Conservative retrieval date documented by the legacy project, not a claim
# that these data were available at their census/reference date.
SNAPSHOT_AVAILABLE_FROM = "2026-09-15"
LEGACY_INPUTS = ["panel_demanda_colonia.csv", "crosswalk_colonias.csv",
                 "zonas_geometria.geojson", "poblacion_colonia.csv",
                 "infraestructura_km_colonia.csv", "tipo_zona_colonia.csv",
                 "atus_accidentes_alcaldia_mes.csv",
                 "proyeccion_demanda_colonia.csv", "proyeccion_demanda_colonia_lgbm.csv"]


def monthly_calendar(files: dict[str, Path], start: str = START) -> pd.DataFrame:
    calendar = pd.DataFrame({"periodo": pd.period_range(start, max(files), freq="M").astype(str)})
    calendar["fecha"] = pd.to_datetime(calendar.periodo + "-01")
    calendar["archivo_disponible"] = calendar.periodo.isin(files)
    calendar["archivo"] = calendar.periodo.map({k: v.name for k, v in files.items()})
    calendar["source_status"] = np.where(calendar.archivo_disponible, "AVAILABLE", "MISSING_DATA")
    return calendar


def assemble_panel(catalog: pd.DataFrame, calendar: pd.DataFrame, counts: pd.DataFrame,
                   confirmed_activation: dict[str, str] | None = None) -> pd.DataFrame:
    panel = catalog.merge(calendar, how="cross")
    for label in ["origen", "destino"]:
        subset = counts[counts.event == label]
        agg = subset.groupby(["zone_id", "periodo"]).agg(
            count=("count", "sum"), last_source=("source_period", "max")).reset_index()
        panel = panel.merge(agg.rename(columns={"count": f"observed_viajes_{label}",
                                                "last_source": f"last_source_{label}"}),
                            on=["zone_id", "periodo"], how="left", validate="one_to_one")
        panel[f"observed_viajes_{label}"] = panel[f"observed_viajes_{label}"].fillna(0).astype("int64")
    observed = panel.observed_viajes_origen + panel.observed_viajes_destino
    first_observed = panel.loc[observed > 0].groupby("zone_id").periodo.min()
    panel["first_observed_activity_month"] = panel.zone_id.map(first_observed)
    panel["activation_date_verified"] = panel.zone_id.map(confirmed_activation or {})
    unknown_pre_activity = (panel.first_observed_activity_month.isna() |
                            (panel.periodo < panel.first_observed_activity_month))
    # No opening date is inferred from first observed trips. NOT_YET_ACTIVE
    # can only be asserted when an authoritative activation date is supplied.
    not_active = panel.activation_date_verified.notna() & (
        panel.fecha + pd.offsets.MonthEnd(0) < pd.to_datetime(panel.activation_date_verified))
    if (not_active & observed.gt(0)).any():
        raise ValueError("Observed events conflict with confirmed activation date")
    panel["data_status"] = "OBSERVED"
    panel.loc[observed.eq(0), "data_status"] = "ZERO_DEMAND"
    panel.loc[unknown_pre_activity & observed.eq(0), "data_status"] = "UNKNOWN_ACTIVITY_STATUS"
    panel.loc[not_active, "data_status"] = "NOT_YET_ACTIVE"
    panel.loc[~panel.archivo_disponible, "data_status"] = "MISSING_DATA"
    panel["datos_disponibles"] = panel.data_status.isin(["OBSERVED", "ZERO_DEMAND"])
    for label in ["origen", "destino"]:
        panel[f"viajes_{label}"] = panel[f"observed_viajes_{label}"].where(panel.datos_disponibles)
    panel["viajes_total"] = panel.viajes_origen + panel.viajes_destino
    panel["target_demanda"] = panel.viajes_total
    panel["year"] = panel.fecha.dt.year
    panel["month"] = panel.fecha.dt.month
    panel["time_idx"] = (panel.year - int(START[:4])) * 12 + panel.month - 1
    # Empty event groups still require at least the corresponding source file.
    latest_source = panel[["last_source_origen", "last_source_destino", "periodo"]].fillna("").max(axis=1)
    panel["target_available_no_earlier_than"] = (
        pd.PeriodIndex(latest_source, freq="M") + 1).to_timestamp()
    panel["historical_availability_verified"] = False
    panel["target_finalized"] = False
    panel["target"] = "viajes_total"
    panel["target_unit"] = "station_endpoints_per_calendar_month"
    panel["station_assignment_method"] = "current_catalog_no_historical_validity"
    panel["pipeline_version"] = VERSION
    return panel.sort_values(["zone_id", "fecha"]).reset_index(drop=True)


def attach_context(panel: pd.DataFrame, catalog: pd.DataFrame, processed: Path) -> pd.DataFrame:
    """Keep snapshots for inspection; they are NOT eligible historical features.

    Do not deduce an opening date, a 2023 business stock, or a zero accident
    count from a missing source. DENUE's geographical join is unverified.
    """
    mappings = [
        ("poblacion_colonia.csv", "colonia", "poblacion_colonia_2020", "poblacion_colonia_2020", "2020"),
        ("infraestructura_km_colonia.csv", "colonia_ecobici", "km_ciclovia", "km_ciclovia", "2025-03"),
        ("tipo_zona_colonia.csv", "colonia", "establecimientos_totales_denue", "negocios_denue", "2026-05"),
    ]
    panel = panel.copy()
    for filename, key, source_column, target, reference in mappings:
        source = pd.read_csv(processed / filename)
        if source[key].duplicated().any():
            raise ValueError(f"Non-unique context key in {filename}")
        # Exact canonical label only. Stocks of two legacy aliases are never
        # summed; this prevents duplicating the same DENUE stock.
        join = catalog[["zone_id", "colonia"]].merge(
            source[[key, source_column]].rename(columns={key: "colonia", source_column: target + "_snapshot_legacy"}),
            on="colonia", how="left", validate="one_to_one").drop(columns="colonia")
        panel = panel.merge(join, on="zone_id", how="left", validate="many_to_one")
        panel[target + "_reference_date"] = reference
        panel[target + "_available_from"] = SNAPSHOT_AVAILABLE_FROM
        panel[target + "_source_version"] = filename + ":sha256:" + sha256_file(processed / filename)
        eligible = (panel.fecha + pd.offsets.MonthEnd(0) >= pd.Timestamp(SNAPSHOT_AVAILABLE_FROM))
        if target == "negocios_denue":
            eligible = pd.Series(False, index=panel.index)  # Requires corrected geographic join.
        panel[target] = panel[target + "_snapshot_legacy"].where(eligible)
        panel[target + "_forecast_eligible"] = eligible & panel[target].notna()
    accidents = pd.read_csv(processed / "atus_accidentes_alcaldia_mes.csv")
    panel = panel.merge(accidents[["alcaldia", "periodo", "accidentes_ciclistas"]].rename(
        columns={"accidentes_ciclistas": "accidentes_reportados_legacy"}),
        on=["alcaldia", "periodo"], how="left", validate="many_to_one")
    panel["accidentes_reference_date"] = panel.periodo.where(panel.periodo <= "2025-12")
    panel["accidentes_available_from"] = SNAPSHOT_AVAILABLE_FROM
    panel["accidentes_source_version"] = "atus_2023_2025:sha256:" + sha256_file(processed / "atus_accidentes_alcaldia_mes.csv")
    panel["accidentes"] = panel.accidentes_reportados_legacy.where(
        panel.fecha + pd.offsets.MonthEnd(0) >= pd.Timestamp(SNAPSHOT_AVAILABLE_FROM))
    panel["accidentes_forecast_eligible"] = panel.accidentes.notna()
    return panel


def validate_panel(panel: pd.DataFrame) -> None:
    if panel.duplicated(["zone_id", "fecha"]).any():
        raise ValueError("Duplicate panel key")
    if not panel.sort_values(["zone_id", "fecha"]).index.equals(panel.index):
        raise ValueError("Panel is not sorted")
    for _, group in panel.groupby("zone_id"):
        if len(pd.period_range(group.periodo.min(), group.periodo.max(), freq="M")) != len(group):
            raise ValueError("Irregular monthly grid")
    if panel.loc[~panel.datos_disponibles, "target_demanda"].notna().any():
        raise ValueError("Unavailable observations must not become demand zero")
    if (panel.loc[panel.datos_disponibles, "target_demanda"] < 0).any():
        raise ValueError("Negative demand")
    if np.isinf(panel.select_dtypes(include="number").to_numpy()).any():
        raise ValueError("Infinite values")
    available = panel.datos_disponibles
    if not (panel.loc[available, "target_demanda"] ==
            panel.loc[available, "viajes_origen"] + panel.loc[available, "viajes_destino"]).all():
        raise ValueError("Target does not reconcile")


def geometry_audit(geojson: dict) -> dict:
    try:
        from shapely.geometry import shape
        from shapely.validation import explain_validity
    except ImportError:
        return {"topology_verified": False, "reason": "Shapely unavailable; presence is not validity"}
    invalid = [{"colonia": f["properties"]["colonia"], "reason": explain_validity(shape(f["geometry"]))}
               for f in geojson["features"] if not shape(f["geometry"]).is_valid]
    if invalid:
        raise ValueError(f"Invalid legacy geometries (not repaired): {invalid}")
    return {"topology_verified": True, "valid_geometries": len(geojson["features"]), "invalid": invalid}


def before_after(legacy: pd.DataFrame, panel: pd.DataFrame, files: dict, stations: pd.DataFrame) -> dict:
    def describe(df, field):
        return {"n_meses": int(df.periodo.nunique()), "n_colonias": int(df.colonia.nunique()),
                "n_filas": len(df), "fecha_min": df.periodo.min(), "fecha_max": df.periodo.max(),
                "n_missing": int(df[field].isna().sum()), "n_zero": int(df[field].eq(0).sum())}
    before = describe(legacy, "viajes_total")
    before.update(n_archivos_ecobici_detectados=int(legacy.periodo.nunique()),
                  discovery_from_configured_legacy_path=len(list((ROOT / "datos_bici").glob("20??-??.csv"))),
                  n_estaciones=int(pd.read_csv(ROOT / "data/processed/ecobici_viajes_por_estacion.csv").num_cicloe.nunique()),
                  n_zone_ids=0)
    after = describe(panel, "target_demanda")
    after.update(n_archivos_ecobici_detectados=len(files), n_estaciones=len(stations),
                 n_zone_ids=int(panel.zone_id.nunique()), data_status=panel.data_status.value_counts().to_dict())
    return {"before": before, "after": after,
            "note": "Before: 25 source months represented by saved panel, but configured input folder currently finds 0. 688 legacy observed IDs vs 677 mapped catalog stations are different universes."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/ecobici")
    parser.add_argument("--chunksize", type=int, default=250_000)
    args = parser.parse_args()
    processed = ROOT / "data/processed"
    files = discover_months(args.raw_dir)
    catalog_path = args.raw_dir / "Caracteristicas_estaciones.csv"
    aliases_path = ROOT / "config/aliases_colonias_v2.json"
    source_paths = list(files.values()) + [catalog_path, aliases_path] + [processed / f for f in LEGACY_INPUTS]
    fingerprints = {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): sha256_file(p) for p in source_paths}
    # Include implementation bytes, so a code fix never silently reuses a run ID.
    for p in [Path(__file__), ROOT / "src/data/ecobici_v2.py"]:
        fingerprints[str(p.relative_to(ROOT))] = sha256_file(p)
    legacy_hashes = {str(p): sha256_file(p) for p in processed.iterdir()
                     if p.is_file() and "v2" not in p.name}
    run_id = hashlib.sha256(json.dumps(fingerprints, sort_keys=True).encode()).hexdigest()[:16]
    snapshot = processed / "v2_runs" / run_id
    if snapshot.exists():
        raise FileExistsError(f"Run {run_id} already exists; snapshots are never overwritten")
    stations, blank_rows = load_stations(catalog_path)
    geojson = json.loads((processed / "zonas_geometria.geojson").read_text())
    geometry = geometry_audit(geojson)
    catalog, stations = build_catalog(stations, pd.read_csv(processed / "crosswalk_colonias.csv"),
                                      geojson, json.loads(aliases_path.read_text())["approved_aliases"])
    station_zones = stations.set_index("num_cicloe").zone_id
    calendar = monthly_calendar(files)
    counts, reports, manifests = [], [], []
    for period, path in files.items():
        report = {"periodo": period, "archivo": path.name}
        for chunk in pd.read_csv(path, dtype=str, chunksize=args.chunksize):
            frame, quality = count_chunk(chunk, station_zones, period, START, max(files))
            counts.append(frame)
            for key, value in quality.items():
                report[key] = report.get(key, 0) + value
        reports.append(report)
        manifests.append({"periodo": period, "archivo": path.name, "rows": report["rows"],
                          "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        print(f"{period}: {report['rows']:,} records; cross-month={report['cross_month_trips']}", flush=True)
    panel = assemble_panel(catalog, calendar, pd.concat(counts, ignore_index=True))
    panel = attach_context(panel, catalog, processed).sort_values(["zone_id", "fecha"]).reset_index(drop=True)
    panel["data_cutoff_date"] = str(pd.Period(max(files), freq="M").end_time.date())
    panel["run_id"] = run_id
    panel["run_date"] = datetime.now(timezone.utc).isoformat()
    validate_panel(panel)
    legacy = pd.read_csv(processed / "panel_demanda_colonia.csv")
    comparison = before_after(legacy, panel, files, stations)
    legacy_quantiles = pd.read_csv(processed / "proyeccion_demanda_colonia_lgbm.csv")
    crossings = (legacy_quantiles.prediccion_p50 < legacy_quantiles.prediccion_p10) | (
        legacy_quantiles.prediccion_p50 > legacy_quantiles.prediccion_p90)
    metadata = {"pipeline_version": VERSION, "run_id": run_id,
                "run_date": panel.run_date.iloc[0], "data_cutoff_date": panel.data_cutoff_date.iloc[0],
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "implementation_and_input_sha256": fingerprints,
                "target": "viajes_total", "target_unit": "station_endpoints_per_calendar_month",
                "training_cutoff": None, "model_name": None, "model_version": None,
                "forecast_horizon": None, "feature_set": "none_phase1",
                "runtime": {"pandas": pd.__version__, "numpy": np.__version__},
                "blank_station_rows_removed": blank_rows, "geometry": geometry,
                "comparison": comparison, "legacy_quantile_crossings_not_modified": int(crossings.sum()),
                "quality_totals": pd.DataFrame(reports).select_dtypes(include="number").sum().to_dict(),
                "limitations": ["Actual dates are used per endpoint; file months are arrival partitions.",
                    "Activity is two station endpoints per trip, not unique trips or latent demand.",
                    "Retirements are lower bounds: later arrival files may reveal earlier departures.",
                    "No historical station validity or authoritative activation dates are available.",
                    "Unknown pre-activity months are null, not claimed NOT_YET_ACTIVE or zero demand.",
                    "Snapshot covariates are masked before conservative retrieval dates; DENUE remains unverified.",
                    "Target availability is a lower bound; historical publication timestamps are unknown."]}
    if any(sha256_file(Path(path)) != digest for path, digest in legacy_hashes.items()):
        raise AssertionError("A legacy output changed")
    # Snapshot first. Convenience names never overwrite a legacy artifact.
    snapshot.mkdir(parents=True)
    outputs = {"panel_demanda_v2.csv": panel, "catalogo_zonas_v2.csv": catalog,
               "calendario_ecobici_v2.csv": calendar, "ecobici_archivos_v2.csv": pd.DataFrame(manifests),
               "ecobici_calidad_v2.csv": pd.DataFrame(reports)}
    for filename, frame in outputs.items():
        frame.to_csv(snapshot / filename, index=False)
    metadata["output_sha256"] = {filename: sha256_file(snapshot / filename) for filename in outputs}
    metadata["legacy_sha256_unchanged"] = legacy_hashes
    (snapshot / "panel_demanda_v2.metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    for path in snapshot.iterdir():
        shutil.copyfile(path, processed / path.name)
    print(json.dumps(comparison, indent=2, ensure_ascii=False))
    print(f"Completed immutable run: {snapshot}")


if __name__ == "__main__":
    main()
