"""Clasificacion de tipo de zona por colonia (CONTEXT.md 7: input de usuario
"tipo de zona buscada" - residencial / mixta / comercial), necesaria para el
termino `afinidad_zona` del algoritmo de puntuacion (src/app/algoritmo_puntuacion.py).

No existe un catalogo oficial de "tipo de zona" por colonia, asi que se
deriva de DENUE (todas las actividades economicas, no solo bici/mensajeria
como en indicadores_denue.py) relativizado a poblacion:

  densidad_comercial_por_mil_hab = establecimientos_totales_denue / poblacion_colonia_2020 * 1000

Terciles de esa densidad (sobre las colonias con ambos datos disponibles)
definen `tipo_zona`: tercio superior -> "Comercial", tercio inferior ->
"Residencial", tercio medio -> "Mixta". Es un proxy razonado (densidad
comercial per capita), no una clasificacion catastral/de uso de suelo real -
se documenta como limitacion (CONTEXT.md 9).

Colonias sin match DENUE o sin poblacion quedan con tipo_zona = "Sin
clasificar" (nunca se fuerza una clasificacion sin datos - mismo principio
que "Datos insuficientes" en el resto del proyecto).

Entradas:
  - data/raw/denue/conjunto_de_datos/denue_inegi_09_.csv (todas las actividades)
  - data/processed/crosswalk_colonias.csv
  - data/processed/poblacion_colonia.csv

Salida: data/processed/tipo_zona_colonia.csv
  columnas: colonia, establecimientos_totales_denue, poblacion_colonia_2020,
            densidad_comercial_por_mil_hab, tipo_zona
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from armonizar_colonias import normalizar  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DENUE_CSV = ROOT / "data" / "raw" / "denue" / "conjunto_de_datos" / "denue_inegi_09_.csv"
CROSSWALK = ROOT / "data" / "processed" / "crosswalk_colonias.csv"
POBLACION_COLONIA = ROOT / "data" / "processed" / "poblacion_colonia.csv"

SALIDA = ROOT / "data" / "processed" / "tipo_zona_colonia.csv"


def main() -> None:
    denue = pd.read_csv(DENUE_CSV, encoding="latin-1", usecols=["nomb_asent"]).dropna()

    crosswalk = pd.read_csv(CROSSWALK)[["colonia_ecobici", "denue_nomb_asent"]].dropna().drop_duplicates()
    # Misma normalizacion en ambos lados del merge: `denue_nomb_asent` es la
    # clave normalizada del crosswalk, no el `nomb_asent` crudo de DENUE (ver
    # el comentario equivalente en indicadores_denue.py).
    denue["clave_asent"] = denue["nomb_asent"].map(normalizar)
    denue = denue.merge(crosswalk, left_on="clave_asent", right_on="denue_nomb_asent", how="inner")

    establecimientos = (
        denue.groupby("colonia_ecobici")
        .size()
        .reset_index(name="establecimientos_totales_denue")
        .rename(columns={"colonia_ecobici": "colonia"})
    )

    poblacion = pd.read_csv(POBLACION_COLONIA)
    tabla = poblacion.merge(establecimientos, on="colonia", how="outer")

    # Denominador: poblacion > 0 obligatoria. Con poblacion 0 (o NaN) la
    # division daba +inf, y +inf cae siempre en el tercil superior -> la colonia
    # se clasificaba "Comercial" por un artefacto aritmetico, no por su densidad
    # comercial (llegaron a ser 11 de 26 "Comercial", incluida "Residencial
    # Emperadores"). Ademas esos +inf envenenaban aguas abajo el z-score de
    # densidad comercial en algoritmo_puntuacion.py. Poblacion ausente o cero no
    # permite calcular una densidad per capita: el resultado es NaN ->
    # "Sin clasificar", que es justo la categoria prevista para "sin datos".
    poblacion_valida = tabla["poblacion_colonia_2020"].where(tabla["poblacion_colonia_2020"] > 0)
    tabla["densidad_comercial_por_mil_hab"] = (
        tabla["establecimientos_totales_denue"] / poblacion_valida * 1000
    )
    tabla["densidad_comercial_por_mil_hab"] = tabla["densidad_comercial_por_mil_hab"].replace(
        [np.inf, -np.inf], np.nan
    )

    con_datos = tabla["densidad_comercial_por_mil_hab"].notna()
    terciles = tabla.loc[con_datos, "densidad_comercial_por_mil_hab"].quantile([1 / 3, 2 / 3])

    def clasificar(densidad: float) -> str:
        if pd.isna(densidad):
            return "Sin clasificar"
        if densidad <= terciles.iloc[0]:
            return "Residencial"
        if densidad <= terciles.iloc[1]:
            return "Mixta"
        return "Comercial"

    tabla["tipo_zona"] = tabla["densidad_comercial_por_mil_hab"].map(clasificar)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(SALIDA, index=False)
    print(f"Guardado: {SALIDA} ({len(tabla)} colonias)")
    print(tabla["tipo_zona"].value_counts())
    print(
        f"\nCortes de tercil (establecimientos por mil hab.): "
        f"<= {terciles.iloc[0]:.2f} Residencial, <= {terciles.iloc[1]:.2f} Mixta, resto Comercial"
    )


if __name__ == "__main__":
    main()
