"""Indicador de infraestructura ciclista por colonia (CONTEXT.md 5,
componente 4 "brecha de infraestructura"): km de ciclovia por colonia,
mediante interseccion espacial de los tramos de vialidad contra los
poligonos de colonia (prorrateando un tramo si cruza mas de una colonia,
como indica CONTEXT.md 6.1.1).

Entradas:
  - data/raw/infraestructura_ciclista/shp/.../Infraestructura ciclista total.shp
  - data/raw/colonias_cdmx/shp/colonias_iecm.shp
  - data/processed/crosswalk_colonias.csv (colonia_ecobici <-> NOMUT)

Salida: data/processed/infraestructura_km_colonia.csv
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CICLOVIAS_SHP = (
    ROOT / "data" / "raw" / "infraestructura_ciclista" / "shp"
    / "infraestructura_vial_ciclista" / "Infraestructura ciclista total.shp"
)
COLONIAS_SHP = ROOT / "data" / "raw" / "colonias_cdmx" / "shp" / "colonias_iecm.shp"
CROSSWALK = ROOT / "data" / "processed" / "crosswalk_colonias.csv"

SALIDA = ROOT / "data" / "processed" / "infraestructura_km_colonia.csv"


def main() -> None:
    ciclovias = gpd.read_file(CICLOVIAS_SHP)[["ID_TRAMO", "TIPO_IC", "A_INICIO", "geometry"]]
    colonias = gpd.read_file(COLONIAS_SHP)[["NOMDT", "NOMUT", "geometry"]]
    colonias["clave_alcaldia"] = colonias["NOMDT"].str.upper().str.strip()

    if ciclovias.crs != colonias.crs:
        ciclovias = ciclovias.to_crs(colonias.crs)

    # Interseccion: parte cada tramo en los pedazos que caen dentro de cada
    # poligono de colonia, para no contar un tramo completo dos veces si
    # cruza el limite entre colonias.
    interseccion = gpd.overlay(ciclovias, colonias, how="intersection")
    interseccion["km"] = interseccion.geometry.length / 1000.0  # CRS en metros (EPSG:32614)

    # Agrupar y cruzar por (NOMUT, alcaldia), no solo por NOMUT: NOMUT se repite
    # entre alcaldias (62 casos en colonias_iecm.shp - "Buenavista" esta en
    # Cuauhtemoc y en Iztapalapa, "Centro" en Cuauhtemoc y en Venustiano
    # Carranza...). Sumando solo por NOMUT, la colonia Ecobici se llevaba
    # tambien los km de ciclovia de su homonima al otro extremo de la ciudad,
    # inflando saturacion_penal en el algoritmo de puntuacion. Es el mismo
    # cuidado que ya tienen armonizar_colonias.py y geometria_colonias.py.
    km_por_nomut = interseccion.groupby(["NOMUT", "clave_alcaldia"])["km"].sum().reset_index()

    crosswalk = pd.read_csv(CROSSWALK)[["colonia_ecobici", "alcaldia", "colonias_cdmx_nomut"]].dropna(
        subset=["colonias_cdmx_nomut"]
    )
    crosswalk["clave_alcaldia"] = crosswalk["alcaldia"].str.upper().str.strip()
    km_por_colonia = crosswalk.merge(
        km_por_nomut,
        left_on=["colonias_cdmx_nomut", "clave_alcaldia"],
        right_on=["NOMUT", "clave_alcaldia"],
        how="left",
    )
    # Aqui el 0.0 SI es correcto y no una imputacion: el poligono de la colonia
    # existe y se interseco contra la capa completa de ciclovias, asi que "sin
    # interseccion" significa literalmente "no pasa ninguna ciclovia por aqui".
    km_por_colonia["km"] = km_por_colonia["km"].fillna(0.0)

    resultado = km_por_colonia.groupby("colonia_ecobici")["km"].sum().reset_index()
    resultado = resultado.rename(columns={"km": "km_ciclovia"})

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(SALIDA, index=False)

    print(f"Guardado: {SALIDA} ({len(resultado)} colonias con poligono)")
    print(f"Total km de ciclovia asignados: {resultado['km_ciclovia'].sum():.1f}")
    print(f"Total km en el shapefile original: {(ciclovias.geometry.length.sum() / 1000):.1f}")
    print("\nTop 10 colonias por km de ciclovia:")
    print(resultado.sort_values("km_ciclovia", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
