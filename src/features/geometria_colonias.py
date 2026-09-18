"""Poligono por colonia Ecobici, para el mapa de la app (CONTEXT.md 8.2:
contrato `data/processed/zonas_geometria.geojson` — "poligonos de zonas con
nombre legible (colonia, alcaldia)").

Ninguna fuente trae ya un poligono por `colonia` Ecobici: `colonias_iecm.shp`
(data/raw/colonias_cdmx/) esta a nivel NOMUT, y algunas colonias Ecobici
corresponden a varios NOMUT (colonias partidas en sub-poligonos, ver
armonizar_colonias.py). Este script usa el cruce ya resuelto en
`crosswalk_colonias.csv` para disolver (union) los NOMUT de cada colonia
Ecobici en un solo poligono, y reproyecta a EPSG:4326 (el shapefile viene en
EPSG:32614) para poder graficarlo con Plotly/folium.

Cobertura: 84/107 colonias Ecobici tienen match de poligono (ver
armonizar_colonias.py) - las 23 sin match simplemente no aparecen en este
geojson; la app debe mostrar esa limitacion explicitamente en vez de
esconderla (CONTEXT.md 9), no inventar un poligono aproximado.

Entradas:
  - data/raw/colonias_cdmx/shp/colonias_iecm.shp
  - data/processed/crosswalk_colonias.csv

Salida: data/processed/zonas_geometria.geojson
  (una fila por colonia_ecobici con poligono disuelto; propiedades: colonia,
  alcaldia)
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
COLONIAS_SHP = ROOT / "data" / "raw" / "colonias_cdmx" / "shp" / "colonias_iecm.shp"
CROSSWALK = ROOT / "data" / "processed" / "crosswalk_colonias.csv"

SALIDA = ROOT / "data" / "processed" / "zonas_geometria.geojson"


def main() -> None:
    colonias = gpd.read_file(COLONIAS_SHP)[["NOMDT", "NOMUT", "geometry"]].to_crs(epsg=4326)
    # NOMUT no es unico en el shapefile: nombres de colonia como "Buenavista"
    # o "Santa Catarina" se repiten en alcaldias distintas (p. ej. Buenavista
    # existe en Cuauhtemoc Y en Iztapalapa). Unir solo por NOMUT trae de
    # vuelta AMBAS coincidencias y el dissolve las funde en un poligono
    # gigante que salta de un extremo de la ciudad al otro - hace falta
    # casar tambien por alcaldia (NOMDT), igual que ya hace
    # armonizar_colonias.py al construir el crosswalk.
    colonias["clave_alcaldia"] = colonias["NOMDT"].str.upper().str.strip()

    crosswalk = pd.read_csv(CROSSWALK).dropna(subset=["colonias_cdmx_nomut"])
    crosswalk = crosswalk.drop_duplicates(subset=["colonia_ecobici", "colonias_cdmx_nomut"])
    crosswalk["clave_alcaldia"] = crosswalk["alcaldia"].str.upper().str.strip()

    unido = crosswalk.merge(
        colonias, left_on=["colonias_cdmx_nomut", "clave_alcaldia"], right_on=["NOMUT", "clave_alcaldia"], how="inner"
    )
    unido = gpd.GeoDataFrame(unido, geometry="geometry", crs=colonias.crs)

    disuelto = unido.dissolve(by="colonia_ecobici", as_index=False).rename(
        columns={"colonia_ecobici": "colonia"}
    )
    # alcaldia es constante dentro de cada colonia_ecobici (viene del crosswalk,
    # que a su vez viene de indice_demanda_colonia.csv) - "first" tras el
    # dissolve alcanza, no hace falta agregacion especial.
    salida = disuelto[["colonia", "alcaldia", "geometry"]]

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    salida.to_file(SALIDA, driver="GeoJSON")

    n_total_ecobici = pd.read_csv(CROSSWALK)["colonia_ecobici"].nunique()
    print(f"Guardado: {SALIDA} ({len(salida)} colonias con poligono de {n_total_ecobici} totales)")
    sin_poligono = sorted(set(pd.read_csv(CROSSWALK)["colonia_ecobici"]) - set(salida["colonia"]))
    print(f"Sin poligono ({len(sin_poligono)}): {sin_poligono}")


if __name__ == "__main__":
    main()
