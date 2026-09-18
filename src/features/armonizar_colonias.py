"""Cruza los nombres de colonia de tres fuentes que las escriben distinto:

  - Ecobici (107 colonias, Title Case, ver data/processed/indice_demanda_colonia.csv)
  - DENUE (`nomb_asent`, MAYUSCULAS con acentos)
  - Colonias CDMX / IECM (`NOMUT`, MAYUSCULAS, algunas colonias partidas en
    sub-poligonos "NOMBRE I", "NOMBRE II", etc.)

No hay un identificador comun entre las tres, asi que el cruce es por nombre
normalizado (sin acentos, mayusculas, espacios colapsados). Se documenta
explicitamente que colonias no encontraron match en vez de forzar una
coincidencia dudosa (ver CONTEXT.md 5.1 y 9 sobre honestidad metodologica).

Salida: data/processed/crosswalk_colonias.csv
  columnas: colonia_ecobici, alcaldia, denue_nomb_asent, colonias_cdmx_nomut
  (nomut puede tener varias filas por colonia_ecobici si la colonia esta
  partida en sub-poligonos - una fila por sub-poligono que hizo match)
"""
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INDICE_ECOBICI = ROOT / "data" / "processed" / "indice_demanda_colonia.csv"
DENUE_CSV = ROOT / "data" / "raw" / "denue" / "conjunto_de_datos" / "denue_inegi_09_.csv"
COLONIAS_SHP = ROOT / "data" / "raw" / "colonias_cdmx" / "shp" / "colonias_iecm.shp"

SALIDA = ROOT / "data" / "processed" / "crosswalk_colonias.csv"

SUFIJOS_SECCION = re.compile(r"\s+(I{1,3}|IV|V)$")


def normalizar(nombre: str) -> str:
    if pd.isna(nombre):
        return ""
    s = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode("ascii")
    s = s.upper().strip()
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)  # quita "(AMPL)", "(RANCHO)", etc.
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalizar_sin_seccion(nombre: str) -> str:
    """Ademas de normalizar, quita sufijos de seccion romana al final
    ("ROMA NORTE I" -> "ROMA NORTE") - solo para el pase de fallback."""
    s = normalizar(nombre)
    return SUFIJOS_SECCION.sub("", s).strip()


def main() -> None:
    ecobici = pd.read_csv(INDICE_ECOBICI)[["colonia", "alcaldia"]].drop_duplicates()
    ecobici["clave"] = ecobici["colonia"].map(normalizar)

    denue = pd.read_csv(DENUE_CSV, encoding="latin-1", usecols=["nomb_asent"]).dropna()
    denue_claves = set(denue["nomb_asent"].map(normalizar))

    colonias = gpd.read_file(COLONIAS_SHP)[["NOMDT", "NOMUT"]]
    colonias["clave"] = colonias["NOMUT"].map(normalizar)
    colonias["clave_sin_seccion"] = colonias["NOMUT"].map(normalizar_sin_seccion)
    colonias["clave_alcaldia"] = colonias["NOMDT"].map(normalizar)

    filas = []
    for _, row in ecobici.iterrows():
        clave = row["clave"]

        denue_match = clave if clave in denue_claves else None

        # Acotar candidatas a la MISMA alcaldia que la colonia Ecobici antes
        # de buscar por nombre: nombres de colonia como "Santa Catarina" se
        # repiten en varias alcaldias de la CDMX (p. ej. Azcapotzalco,
        # Coyoacan y Tlahuac tienen cada una una), y el "clave" normalizado
        # (sin el sufijo entre parentesis, que es justo lo que las distingue
        # - "(PBLO)"/"(BARR)"/"(AMPL)") no alcanza para diferenciarlas. Sin
        # este filtro, el match terminaba uniendo poligonos de colonias
        # homonimas en el otro extremo de la ciudad (ver geometria_colonias.py).
        candidatas = colonias[colonias["clave_alcaldia"] == normalizar(row["alcaldia"])]

        exactas = candidatas[candidatas["clave"] == clave]
        if len(exactas):
            nomut_matches = exactas["NOMUT"].tolist()
        else:
            aprox = candidatas[candidatas["clave_sin_seccion"] == clave]
            if len(aprox):
                nomut_matches = aprox["NOMUT"].tolist()
            else:
                # Fallback: el catalogo IECM a veces subdivide una colonia en
                # sub-barrios y marca cada uno con la colonia "madre" entre
                # parentesis, p. ej. "LOS MORALES (POLANCO)" para la colonia
                # Ecobici "Polanco". Busca ese patron como ultimo recurso.
                por_etiqueta = candidatas[
                    candidatas["NOMUT"].str.contains(f"({clave})", regex=False, case=False, na=False)
                ]
                nomut_matches = por_etiqueta["NOMUT"].tolist()

        if not nomut_matches:
            filas.append(
                {
                    "colonia_ecobici": row["colonia"],
                    "alcaldia": row["alcaldia"],
                    "denue_nomb_asent": denue_match,
                    "colonias_cdmx_nomut": None,
                }
            )
        else:
            for nomut in nomut_matches:
                filas.append(
                    {
                        "colonia_ecobici": row["colonia"],
                        "alcaldia": row["alcaldia"],
                        "denue_nomb_asent": denue_match,
                        "colonias_cdmx_nomut": nomut,
                    }
                )

    crosswalk = pd.DataFrame(filas)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(SALIDA, index=False)

    n_colonias = ecobici["colonia"].nunique()
    con_denue = crosswalk.dropna(subset=["denue_nomb_asent"])["colonia_ecobici"].nunique()
    con_poligono = crosswalk.dropna(subset=["colonias_cdmx_nomut"])["colonia_ecobici"].nunique()

    print(f"Guardado: {SALIDA} ({len(crosswalk)} filas)")
    print(f"Colonias Ecobici: {n_colonias}")
    print(f"  con match en DENUE (nomb_asent):        {con_denue} ({con_denue/n_colonias:.0%})")
    print(f"  con match en poligono (colonias_cdmx):   {con_poligono} ({con_poligono/n_colonias:.0%})")

    sin_denue = sorted(set(ecobici["colonia"]) - set(crosswalk.dropna(subset=["denue_nomb_asent"])["colonia_ecobici"]))
    sin_poligono = sorted(set(ecobici["colonia"]) - set(crosswalk.dropna(subset=["colonias_cdmx_nomut"])["colonia_ecobici"]))
    print(f"\nSin match en DENUE ({len(sin_denue)}): {sin_denue}")
    print(f"\nSin match en poligono ({len(sin_poligono)}): {sin_poligono}")


if __name__ == "__main__":
    main()
