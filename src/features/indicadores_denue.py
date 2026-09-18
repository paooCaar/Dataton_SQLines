"""Indicador DENUE por colonia (CONTEXT.md 5, componente 1): establecimientos
relacionados con bicis y mensajeria/transporte ligero.

DENUE es un solo snapshot (mayo 2026), no hay ediciones anteriores
descargadas para comparar aperturas/cierres netos (ver docs/fuentes_datos.md).
Como sustituto se usa `fecha_alta` (fecha de registro de cada establecimiento
que SIGUE ACTIVO hoy) para reconstruir aperturas brutas por mes y colonia -
esto subestima el total historico real porque no ve establecimientos que ya
cerraron, pero sigue siendo util para comparar zonas entre si.

Entradas:
  - data/raw/denue/conjunto_de_datos/denue_inegi_09_.csv
  - data/processed/crosswalk_colonias.csv (colonia_ecobici <-> nomb_asent)
  - data/processed/panel_demanda_colonia.csv (para saber que periodos existen)

Salidas:
  - data/processed/denue_nivel_colonia.csv (snapshot: conteo total por colonia)
  - data/processed/denue_aperturas_colonia_mes.csv (aperturas por colonia x periodo)
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from armonizar_colonias import normalizar  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DENUE_CSV = ROOT / "data" / "raw" / "denue" / "conjunto_de_datos" / "denue_inegi_09_.csv"
CROSSWALK = ROOT / "data" / "processed" / "crosswalk_colonias.csv"
PANEL = ROOT / "data" / "processed" / "panel_demanda_colonia.csv"

SALIDA_NIVEL = ROOT / "data" / "processed" / "denue_nivel_colonia.csv"
SALIDA_APERTURAS = ROOT / "data" / "processed" / "denue_aperturas_colonia_mes.csv"

ACTIVIDADES_BICI = [
    "Reparación y mantenimiento de bicicletas",
    "Comercio al por menor de bicicletas",
    "Comercio al por mayor de juguetes y bicicletas",
    "Fabricación de bicicletas y triciclos",
]
ACTIVIDADES_MENSAJERIA = [
    "Servicios de mensajería y paquetería local",
    "Servicios de mensajería y paquetería foránea",
]
ACTIVIDADES_RELEVANTES = ACTIVIDADES_BICI + ACTIVIDADES_MENSAJERIA


def main() -> None:
    denue = pd.read_csv(
        DENUE_CSV,
        encoding="latin-1",
        usecols=["nombre_act", "nomb_asent", "fecha_alta"],
    )
    denue = denue[denue["nombre_act"].isin(ACTIVIDADES_RELEVANTES)].dropna(subset=["nomb_asent"])
    denue["categoria"] = denue["nombre_act"].isin(ACTIVIDADES_BICI).map(
        {True: "bici", False: "mensajeria"}
    )

    crosswalk = pd.read_csv(CROSSWALK)[["colonia_ecobici", "denue_nomb_asent"]].dropna().drop_duplicates()

    # `denue_nomb_asent` del crosswalk es la clave NORMALIZADA (mayusculas, sin
    # acentos, sin parentesis - ver armonizar_colonias.normalizar), no el valor
    # crudo de DENUE. Cruzar contra `nomb_asent` sin normalizar solo casaba las
    # colonias cuyo nombre ya venia sin acentos ni variantes en DENUE y perdia
    # silenciosamente el resto (~22% de los establecimientos: "VERONICA
    # ANZURES" contra "VERÓNICA ANZURES", etc.). Hay que aplicar la MISMA
    # normalizacion a ambos lados del merge.
    denue["clave_asent"] = denue["nomb_asent"].map(normalizar)
    denue = denue.merge(
        crosswalk, left_on="clave_asent", right_on="denue_nomb_asent", how="inner"
    )

    print(f"Establecimientos relevantes con colonia Ecobici asignada: {len(denue)}")
    print(denue["categoria"].value_counts())

    nivel = (
        denue.groupby(["colonia_ecobici", "categoria"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
        .rename(columns={"bici": "establecimientos_bici", "mensajeria": "establecimientos_mensajeria"})
    )
    for col in ["establecimientos_bici", "establecimientos_mensajeria"]:
        if col not in nivel.columns:
            nivel[col] = 0
    nivel["establecimientos_relacionados_total"] = (
        nivel["establecimientos_bici"] + nivel["establecimientos_mensajeria"]
    )
    SALIDA_NIVEL.parent.mkdir(parents=True, exist_ok=True)
    nivel.to_csv(SALIDA_NIVEL, index=False)
    print(f"Guardado: {SALIDA_NIVEL} ({len(nivel)} colonias)")

    panel = pd.read_csv(PANEL, dtype={"periodo": str})
    periodos_validos = sorted(panel["periodo"].unique())

    denue["periodo"] = denue["fecha_alta"].str.slice(0, 7)
    aperturas = (
        denue[denue["periodo"].isin(periodos_validos)]
        .groupby(["colonia_ecobici", "periodo"])
        .size()
        .reset_index(name="aperturas_denue")
    )
    aperturas.to_csv(SALIDA_APERTURAS, index=False)
    print(f"Guardado: {SALIDA_APERTURAS} ({len(aperturas)} filas colonia x periodo con aperturas > 0)")
    print(f"(de {len(periodos_validos)} periodos en el panel: {periodos_validos[0]} a {periodos_validos[-1]})")


if __name__ == "__main__":
    main()
