"""Build a dated, station-level ECOBICI activity snapshot from local trips.

Each trip contributes one endpoint at its departure station and one at its
arrival station, counted in the calendar month of the respective event.
The current station catalog has no historical opening dates: zero endpoints
means no record in this month, not proof that a station was operating.
"""

from __future__ import annotations

from pathlib import Path
import argparse

import pandas as pd

from src.data.ecobici_v2 import discover_months, event_dates, load_stations


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data/raw/ecobici"
OUTPUT = ROOT / "data/processed/station_activity_latest_v2.csv"


def build_station_activity(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    files = discover_months(raw_dir)
    period, source = next(reversed(files.items()))
    stations, _ = load_stations(raw_dir / "Caracteristicas_estaciones.csv")
    station_ids = set(stations.num_cicloe)
    departure_counts = pd.Series(dtype="int64")
    arrival_counts = pd.Series(dtype="int64")
    headers = pd.read_csv(source, nrows=0).columns
    arrival_columns = [column for column in ("Fecha Arribo", "Fecha_Arribo") if column in headers]
    if len(arrival_columns) != 1:
        raise ValueError(f"Expected one arrival date column in {source.name}")
    for chunk in pd.read_csv(
        source,
        usecols=["Ciclo_Estacion_Retiro", "Ciclo_EstacionArribo", "Fecha_Retiro", arrival_columns[0]],
        dtype=str,
        chunksize=200_000,
    ):
        departure, arrival = event_dates(chunk)
        valid = departure.notna() & arrival.notna() & departure.le(arrival)
        for station_column, dates, counts in (
            ("Ciclo_Estacion_Retiro", departure, departure_counts),
            ("Ciclo_EstacionArribo", arrival, arrival_counts),
        ):
            in_month = dates.dt.to_period("M").astype(str).eq(period)
            ids = chunk.loc[valid & in_month, station_column].str.strip()
            ids = ids[ids.isin(station_ids)]
            updated = ids.value_counts()
            if station_column == "Ciclo_Estacion_Retiro":
                departure_counts = counts.add(updated, fill_value=0).astype("int64")
            else:
                arrival_counts = counts.add(updated, fill_value=0).astype("int64")

    result = stations[["num_cicloe"]].copy()
    result["periodo"] = period
    result["viajes_origen"] = result.num_cicloe.map(departure_counts).fillna(0).astype("int64")
    result["viajes_destino"] = result.num_cicloe.map(arrival_counts).fillna(0).astype("int64")
    result["viajes_total"] = result.viajes_origen + result.viajes_destino
    result["activity_status"] = result.viajes_total.gt(0).map({True: "OBSERVED", False: "NO_RECORD"})
    return result.sort_values("num_cicloe").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_station_activity(args.raw_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"{args.output}: {len(result)} estaciones, mes {result.periodo.iloc[0]}")


if __name__ == "__main__":
    main()
