"""Indicador demografico (CONTEXT.md 5, componente 3 "crecimiento
demografico"): poblacion total 2020 por alcaldia, asignada como covariable
estatica a cada colonia de esa alcaldia.

Limitacion explicita (mismo patron que CONTEXT.md aplica a ATUS en 6.1.1):
no se hizo union espacial AGEB->colonia (necesitaria los poligonos de AGEB
del Marco Geoestadistico, no descargados todavia - ver docs/fuentes_datos.md),
asi que la poblacion queda a resolucion de alcaldia, no de colonia, y es un
solo corte (2020), no una serie para medir crecimiento. El archivo AGEB/manzana
ya descargado (data/raw/censo_ageb_manzana2020/) queda listo para cuando se
agregue esa union espacial.

Entrada: data/raw/censo_iter2020/iter_09_cpv2020/conjunto_de_datos/conjunto_de_datos_iter_09CSV20.csv
Salida: data/processed/poblacion_alcaldia.csv
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ITER_CSV = (
    ROOT / "data" / "raw" / "censo_iter2020" / "iter_09_cpv2020"
    / "conjunto_de_datos" / "conjunto_de_datos_iter_09CSV20.csv"
)
SALIDA = ROOT / "data" / "processed" / "poblacion_alcaldia.csv"

# CONTEXT.md usa los nombres de alcaldia tal como los trae Caracteristicas_estaciones.csv
# (sin acentos, "Alvaro Obregon" en vez de "Álvaro Obregón" de INEGI).
MAPA_NOMBRES = {
    "Cuauhtémoc": "Cuauhtemoc",
    "Benito Juárez": "Benito Juarez",
    "Miguel Hidalgo": "Miguel Hidalgo",
    "Coyoacán": "Coyoacan",
    "Azcapotzalco": "Azcapotzalco",
    "Álvaro Obregón": "Alvaro Obregon",
}


def main() -> None:
    iter_df = pd.read_csv(ITER_CSV, encoding="utf-8")
    totales = iter_df[iter_df["NOM_LOC"] == "Total del Municipio"][["NOM_MUN", "POBTOT"]]
    totales["alcaldia"] = totales["NOM_MUN"].map(MAPA_NOMBRES)
    totales = totales.dropna(subset=["alcaldia"])[["alcaldia", "POBTOT"]].rename(
        columns={"POBTOT": "poblacion_2020"}
    )

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    totales.to_csv(SALIDA, index=False)
    print(f"Guardado: {SALIDA}")
    print(totales.to_string(index=False))


if __name__ == "__main__":
    main()
