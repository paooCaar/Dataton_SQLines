"""Poblacion 2020 por COLONIA (CONTEXT.md 5, componente 3 "crecimiento
demografico" - version a resolucion de colonia, no de alcaldia).

Hasta ahora (indicadores_poblacion.py) la poblacion solo se tenia por
alcaldia porque faltaban los poligonos de AGEB del Marco Geoestadistico para
hacer la union espacial AGEB->colonia (ver CONTEXT.md 5.2 y
docs/fuentes_datos.md). Con el Marco Geoestadistico ya descargado
(data/raw/marco_geoestadistico/, poligonos de AGEB urbana segun el Marco
Geoestadistico 2020 de INEGI, redistribuidos por Datos Abiertos CDMX), este
script hace esa union: la poblacion de cada AGEB se REPARTE entre las colonias que
lo intersectan, en proporcion al area de interseccion (colonias_iecm, la
misma capa que usa armonizar_colonias.py e indicadores_infraestructura.py).
El cruce final es por (NOMUT, alcaldia) porque NOMUT se repite entre
alcaldias. Las colonias sin interseccion quedan con NaN, nunca con 0.

Sigue siendo un solo corte (2020) - no aporta TENDENCIA de poblacion, solo
NIVEL. A diferencia de la version por alcaldia, este si discrimina entre
colonias de una misma alcaldia, asi que aqui si tiene sentido que entre al
indice compuesto como termino de nivel (ver indice_compuesto.py) en vez de
quedar solo informativo.

Entradas:
  - data/raw/censo_ageb_manzana2020/.../conjunto_de_datos_ageb_urbana_09_cpv2020.csv
  - data/raw/marco_geoestadistico/shp/poligono_ageb_urbanas_cdmx.shp
  - data/raw/colonias_cdmx/shp/colonias_iecm.shp
  - data/processed/crosswalk_colonias.csv

Salida: data/processed/poblacion_colonia.csv (colonia_ecobici, poblacion_2020)
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CENSO_CSV = (
    ROOT / "data" / "raw" / "censo_ageb_manzana2020" / "ageb_mza_urbana_09_cpv2020"
    / "conjunto_de_datos" / "conjunto_de_datos_ageb_urbana_09_cpv2020.csv"
)
AGEB_SHP = ROOT / "data" / "raw" / "marco_geoestadistico" / "shp" / "poligono_ageb_urbanas_cdmx.shp"
COLONIAS_SHP = ROOT / "data" / "raw" / "colonias_cdmx" / "shp" / "colonias_iecm.shp"
CROSSWALK = ROOT / "data" / "processed" / "crosswalk_colonias.csv"

SALIDA = ROOT / "data" / "processed" / "poblacion_colonia.csv"


def main() -> None:
    censo = pd.read_csv(CENSO_CSV, dtype=str)
    # Filas a nivel AGEB (no manzana, no total de entidad/municipio/localidad):
    # MZA == "000" y AGEB != "0000".
    censo_ageb = censo[(censo["MZA"] == "000") & (censo["AGEB"] != "0000")].copy()
    censo_ageb["CVEGEO"] = censo_ageb["ENTIDAD"] + censo_ageb["MUN"] + censo_ageb["LOC"] + censo_ageb["AGEB"]
    censo_ageb["POBTOT"] = pd.to_numeric(censo_ageb["POBTOT"], errors="coerce")

    ageb_poligonos = gpd.read_file(AGEB_SHP)[["CVEGEO", "geometry"]]
    ageb = ageb_poligonos.merge(censo_ageb[["CVEGEO", "POBTOT"]], on="CVEGEO", how="left")
    sin_poblacion = ageb["POBTOT"].isna().sum()
    print(f"AGEB con poligono: {len(ageb)}; sin match de poblacion en el censo: {sin_poblacion}")
    ageb["POBTOT"] = ageb["POBTOT"].fillna(0)

    colonias = gpd.read_file(COLONIAS_SHP)[["NOMDT", "NOMUT", "geometry"]]
    colonias["clave_alcaldia"] = colonias["NOMDT"].str.upper().str.strip()

    if ageb.crs != colonias.crs:
        ageb = ageb.to_crs(colonias.crs)

    # Reparto AREAL, no por centroide. Asignar la poblacion COMPLETA de un AGEB
    # a la colonia que contiene su centroide es todo-o-nada: los AGEB del Marco
    # Geoestadistico son mas grandes que muchas colonias, asi que una colonia
    # chica que cae DENTRO de un AGEB no recibe ningun centroide y terminaba con
    # poblacion 0 (San Rafael, Credito Constructor, Nextitla... 13 de 84
    # colonias quedaban en 0), mientras la colonia vecina que si se quedo el
    # centroide recibia el AGEB entero. Se reparte la poblacion de cada AGEB
    # entre las colonias que lo intersectan, en proporcion al area de
    # interseccion. Supone densidad uniforme dentro del AGEB - una aproximacion,
    # pero mucho mejor que el todo-o-nada anterior, y sobre todo no fabrica
    # ceros donde solo hay una geometria que no coincide.
    ageb["area_ageb_m2"] = ageb.geometry.area
    piezas = gpd.overlay(ageb, colonias, how="intersection", keep_geom_type=True)
    piezas["poblacion_2020"] = piezas["POBTOT"] * (piezas.geometry.area / piezas["area_ageb_m2"])

    poblacion_asignada = piezas["poblacion_2020"].sum()
    print(
        f"Poblacion AGEB repartida por area a alguna colonia: {poblacion_asignada:,.0f} "
        f"de {ageb['POBTOT'].sum():,.0f} ({poblacion_asignada / ageb['POBTOT'].sum():.1%})"
    )

    # NOMUT NO es unico en el shapefile: "Buenavista" existe en Cuauhtemoc y en
    # Iztapalapa, "Santo Tomas" en Azcapotzalco y Miguel Hidalgo, etc. (62 NOMUT
    # repetidos entre alcaldias). Agrupar solo por NOMUT sumaba la poblacion de
    # la colonia homonima del otro extremo de la ciudad - Buenavista pasaba de
    # 10,827 a 37,058 habitantes y Santo Tomas de 89 a 2,441. Hay que agrupar y
    # cruzar por (NOMUT, alcaldia), igual que ya hace geometria_colonias.py.
    poblacion_por_nomut = (
        piezas.groupby(["NOMUT", "clave_alcaldia"])["poblacion_2020"].sum().reset_index()
    )

    crosswalk = pd.read_csv(CROSSWALK)[["colonia_ecobici", "alcaldia", "colonias_cdmx_nomut"]].dropna(
        subset=["colonias_cdmx_nomut"]
    )
    crosswalk["clave_alcaldia"] = crosswalk["alcaldia"].str.upper().str.strip()
    resultado = crosswalk.merge(
        poblacion_por_nomut,
        left_on=["colonias_cdmx_nomut", "clave_alcaldia"],
        right_on=["NOMUT", "clave_alcaldia"],
        how="left",
    )
    # NADA de fillna(0.0): un sub-poligono sin interseccion es AUSENCIA de dato,
    # no "cero habitantes" (principio del proyecto, CONTEXT.md 9). min_count=1
    # hace que una colonia cuyos sub-poligonos TODOS quedaron sin dato conserve
    # NaN en vez de colapsar a 0.0 por el sum() de pandas; aguas abajo,
    # indicadores_tipo_zona.py la deja "Sin clasificar" y el z-score la trata
    # como neutral, que es lo correcto.
    resultado = resultado.groupby("colonia_ecobici")["poblacion_2020"].sum(min_count=1).reset_index()
    # Nombre distinto de "poblacion_2020" (poblacion_alcaldia.csv, resolucion
    # de alcaldia) para no confundir las dos versiones al fusionarlas en el
    # panel - ver indice_compuesto.py.
    resultado = resultado.rename(columns={"colonia_ecobici": "colonia", "poblacion_2020": "poblacion_colonia_2020"})

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(SALIDA, index=False)

    print(f"\nGuardado: {SALIDA} ({len(resultado)} colonias)")
    sin_dato = int(resultado["poblacion_colonia_2020"].isna().sum())
    en_cero = int((resultado["poblacion_colonia_2020"] == 0).sum())
    print(f"Colonias sin dato de poblacion (NaN, NO 0): {sin_dato}; con poblacion exactamente 0: {en_cero}")
    print(f"Poblacion total sumada (colonias con poligono): {resultado['poblacion_colonia_2020'].sum():,.0f}")
    print(f"Poblacion total del censo AGEB (CDMX completa): {censo_ageb['POBTOT'].sum():,.0f}")
    print("\nTop 10 colonias por poblacion 2020:")
    print(resultado.sort_values("poblacion_colonia_2020", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
