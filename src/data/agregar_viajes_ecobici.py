"""Agrega los CSV mensuales de viajes Ecobici (datos_bici/) por estación de
retiro y de arribo, y cruza el resultado con las coordenadas de las
estaciones (datos_bici/Caracteristicas_estaciones.csv).

Salida: data/processed/ecobici_viajes_por_estacion.csv
"""
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATOS_BICI = ROOT / "datos_bici"
SALIDA = ROOT / "data" / "processed" / "ecobici_viajes_por_estacion.csv"

ARCHIVOS_ESTACIONES = DATOS_BICI / "Caracteristicas_estaciones.csv"


def cargar_estaciones() -> pd.DataFrame:
    st = pd.read_csv(ARCHIVOS_ESTACIONES, encoding="latin-1")
    st["num_cicloe"] = st["num_cicloe"].astype(str).str.strip()
    st = st.drop_duplicates(subset="num_cicloe", keep="first")
    return st


def agregar_conteos() -> pd.DataFrame:
    archivos = sorted(
        f for f in DATOS_BICI.glob("*.csv") if f.name != "Caracteristicas_estaciones.csv"
    )
    print(f"Procesando {len(archivos)} archivos mensuales...")

    retiros = Counter()
    arribos = Counter()
    total_filas = 0

    for f in archivos:
        for chunk in pd.read_csv(
            f,
            usecols=["Ciclo_Estacion_Retiro", "Ciclo_EstacionArribo"],
            dtype=str,
            chunksize=500_000,
        ):
            retiros.update(chunk["Ciclo_Estacion_Retiro"].str.strip().dropna())
            arribos.update(chunk["Ciclo_EstacionArribo"].str.strip().dropna())
            total_filas += len(chunk)
        print(f"  {f.name}: acumulado {total_filas:,} viajes")

    estaciones = sorted(set(retiros) | set(arribos))
    df = pd.DataFrame(
        {
            "num_cicloe": estaciones,
            "viajes_retiro": [retiros.get(e, 0) for e in estaciones],
            "viajes_arribo": [arribos.get(e, 0) for e in estaciones],
        }
    )
    df["viajes_total"] = df["viajes_retiro"] + df["viajes_arribo"]
    print(f"Total de viajes procesados: {total_filas:,}")
    return df


def main() -> None:
    conteos = agregar_conteos()
    st = cargar_estaciones()

    merged = conteos.merge(st, on="num_cicloe", how="left")
    sin_match = merged["latitud"].isna().sum()
    if sin_match:
        print(f"Aviso: {sin_match} estaciones en los viajes sin coordenadas (revisar codigos).")

    merged = merged.sort_values("viajes_total", ascending=False)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(SALIDA, index=False)
    print(f"Guardado: {SALIDA} ({len(merged)} estaciones)")


if __name__ == "__main__":
    main()
