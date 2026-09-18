"""Read-only ECOBICI ingestion helpers for the parallel V2 pipeline.

Preserves legacy chunked counting, but discovers both monthly naming styles,
uses actual event dates, and only consolidates explicitly reviewed aliases.
No writes, model fitting, or changes to legacy scripts occur here.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

import pandas as pd

MONTH_FILE = re.compile(r"^(\d{4})[-_](\d{2})\.csv$", re.IGNORECASE)
DATE_COLUMNS = {"Fecha_Retiro": "retiro", "Fecha Arribo": "arribo", "Fecha_Arribo": "arribo"}
NAMESPACE = uuid.UUID("71bf5a60-6250-4bfe-9b95-fef0fc664b97")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_months(folder: Path, start: str = "2023-01") -> dict[str, Path]:
    files = {}
    for path in sorted(folder.glob("*.csv")):
        match = MONTH_FILE.fullmatch(path.name)
        if not match:
            if re.match(r"^\d{4}", path.name):
                raise ValueError(f"Unrecognized monthly filename: {path.name}")
            continue
        period = str(pd.Period(f"{match[1]}-{match[2]}", freq="M"))
        if period < start:
            continue
        if period in files:
            raise ValueError(f"Duplicate source month {period}: {files[period]} and {path}")
        files[period] = path
    if not files:
        raise ValueError(f"No monthly files in {folder}")
    return dict(sorted(files.items()))


def load_stations(path: Path) -> tuple[pd.DataFrame, int]:
    raw = pd.read_csv(path, encoding="latin-1", dtype=str)
    blank_count = int(raw.isna().all(axis=1).sum())
    stations = raw.dropna(how="all").copy()
    required = ["num_cicloe", "colonia", "alcaldia", "latitud", "longitud"]
    if stations[required].isna().any().any():
        raise ValueError("Partially missing station identity/geography; inspect source")
    for column in ["num_cicloe", "colonia", "alcaldia"]:
        stations[column] = stations[column].str.strip()
    if stations.num_cicloe.duplicated().any():
        raise ValueError("Duplicate station IDs; do not silently choose the first")
    for column in ["latitud", "longitud"]:
        stations[column] = pd.to_numeric(stations[column], errors="raise")
    if not (stations.latitud.between(-90, 90) & stations.longitud.between(-180, 180)).all():
        raise ValueError("Station coordinate out of range")
    return stations, blank_count


def stable_zone_id(alcaldia: str, canonical: str) -> str:
    # Exact curated names, NOT fuzzy/automatic accent or case consolidation.
    return "col_" + uuid.uuid5(NAMESPACE, json.dumps([alcaldia, canonical], ensure_ascii=False)).hex


def build_catalog(stations: pd.DataFrame, crosswalk: pd.DataFrame, geojson: dict,
                  approved_aliases: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    stations = stations.copy()
    stations["colonia_original"] = stations.colonia
    for rule in approved_aliases:
        same_borough = stations.alcaldia == rule["alcaldia"]
        alias = same_borough & (stations.colonia_original == rule["alias"])
        canonical = same_borough & (stations.colonia_original == rule["canonical"])
        for mask, key in [(alias, "expected_alias_station_ids"), (canonical, "expected_canonical_station_ids")]:
            if set(stations.loc[mask, "num_cicloe"]) != set(rule[key]):
                raise ValueError("Alias evidence changed: station IDs require manual review")
        if rule["alias"].casefold() != rule["canonical"].casefold():
            raise ValueError("This reviewed alias mechanism only permits exact case variants")
        evidence = crosswalk[(crosswalk.alcaldia == rule["alcaldia"]) &
                             crosswalk.colonia_ecobici.isin([rule["alias"], rule["canonical"]])]
        if evidence.colonia_ecobici.nunique() != 2 or evidence.denue_nomb_asent.dropna().nunique() != 1:
            raise ValueError("Alias crosswalk evidence missing or conflicting")
        if evidence.colonias_cdmx_nomut.dropna().nunique() > 1:
            raise ValueError("Conflicting geometry mappings for alias")
        stations.loc[alias, "colonia"] = rule["canonical"]
    geometry_keys = [(f["properties"]["alcaldia"], f["properties"]["colonia"])
                     for f in geojson["features"]]
    if len(geometry_keys) != len(set(geometry_keys)):
        raise ValueError("Duplicate geometry keys")
    records = []
    for (borough, name), group in stations.groupby(["alcaldia", "colonia"], sort=True):
        aliases = sorted(group.colonia_original.unique())
        records.append({"zone_id": stable_zone_id(borough, name), "colonia": name,
                        "alcaldia": borough, "aliases": json.dumps(aliases, ensure_ascii=False),
                        "geometry_available": (borough, name) in geometry_keys,
                        "n_estaciones_catalogo_actual": len(group),
                        "station_history_available": False})
    catalog = pd.DataFrame(records)
    if catalog.zone_id.duplicated().any():
        raise ValueError("Duplicate zone IDs")
    stations = stations.merge(catalog[["colonia", "alcaldia", "zone_id"]],
                              on=["colonia", "alcaldia"], validate="many_to_one")
    return catalog, stations


def event_dates(chunk: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    arrival_columns = [c for c in ["Fecha Arribo", "Fecha_Arribo"] if c in chunk]
    if len(arrival_columns) != 1:
        raise ValueError("Expected exactly one arrival date column")
    departure = pd.to_datetime(chunk["Fecha_Retiro"], format="%d/%m/%Y", errors="coerce")
    arrival = pd.to_datetime(chunk[arrival_columns[0]], format="%d/%m/%Y", errors="coerce")
    return departure, arrival


def count_chunk(chunk: pd.DataFrame, station_zones: pd.Series, source_period: str,
                start: str, end: str) -> tuple[pd.DataFrame, dict]:
    """Count each endpoint in its own calendar month, retaining availability.

    Unknown station IDs, invalid/reversed dates and out-of-window events are
    accounted for separately, never silently added to a different month.
    Durations over one day are retained, flagged, and require later review.
    """
    departure, arrival = event_dates(chunk)
    invalid = departure.isna() | arrival.isna()
    reversed_dates = (departure > arrival).fillna(False)
    valid = ~invalid & ~reversed_dates
    arrival_period = arrival.dt.strftime("%Y-%m")
    departure_period = departure.dt.strftime("%Y-%m")
    report = {"rows": len(chunk), "invalid_dates": int(invalid.sum()),
              "reversed_dates": int(reversed_dates.sum()),
              "cross_month_trips": int((valid & (departure_period != arrival_period)).sum()),
              "arrival_outside_file_month": int((arrival.notna() & (arrival_period != source_period)).sum()),
              "duration_over_1_day": int(((arrival - departure).dt.days > 1).sum())}
    if report["arrival_outside_file_month"]:
        raise ValueError(f"Arrival partition assumption violated in {source_period}")
    counts = []
    for label, station_column, periods in [
        ("origen", "Ciclo_Estacion_Retiro", departure_period),
        ("destino", "Ciclo_EstacionArribo", arrival_period),
    ]:
        zones = chunk[station_column].str.strip().map(station_zones)
        in_window = periods.ge(start) & periods.le(end)
        report[f"unmapped_{label}"] = int((valid & zones.isna()).sum())
        report[f"outside_window_{label}"] = int((valid & ~in_window).sum())
        keep = valid & zones.notna() & in_window
        frame = pd.DataFrame({"zone_id": zones[keep], "periodo": periods[keep]})
        frame = frame.groupby(["zone_id", "periodo"]).size().rename("count").reset_index()
        frame["event"] = label
        frame["source_period"] = source_period
        counts.append(frame)
        report[f"counted_{label}"] = int(keep.sum())
        report[f"unmapped_in_window_{label}"] = int((valid & in_window & zones.isna()).sum())
        if report[f"counted_{label}"] + report[f"unmapped_in_window_{label}"] + report[f"outside_window_{label}"] + int((~valid).sum()) != len(chunk):
            raise AssertionError("Endpoint accounting does not reconcile")
    return pd.concat(counts, ignore_index=True), report
