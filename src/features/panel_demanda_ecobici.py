"""Construye el panel colonia x mes de uso de Ecobici y un primer indice de
demanda por zona a partir de el (unica fuente confirmada y cargada hasta
ahora - ver CONTEXT.md seccion 5.1 para las limitaciones).

Entradas:
  - datos_bici/*.csv (viajes mensuales)
  - datos_bici/Caracteristicas_estaciones.csv (estacion -> colonia/alcaldia)

Salidas:
  - data/processed/panel_demanda_colonia.csv   (colonia x periodo, viajes)
  - data/processed/indice_demanda_colonia.csv  (ranking por zona: nivel + tendencia)
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

ROOT = Path(__file__).resolve().parents[2]
DATOS_BICI = ROOT / "datos_bici"
ESTACIONES = DATOS_BICI / "Caracteristicas_estaciones.csv"

SALIDA_PANEL = ROOT / "data" / "processed" / "panel_demanda_colonia.csv"
SALIDA_INDICE = ROOT / "data" / "processed" / "indice_demanda_colonia.csv"

PATRON_MES = re.compile(r"(\d{4})-(\d{2})\.csv$")


def cargar_mapa_estaciones() -> pd.DataFrame:
    st = pd.read_csv(ESTACIONES, encoding="latin-1")
    st["num_cicloe"] = st["num_cicloe"].astype(str).str.strip()
    st = st.drop_duplicates(subset="num_cicloe", keep="first")
    return st.dropna(subset=["colonia", "alcaldia"]).set_index("num_cicloe")[["colonia", "alcaldia"]]


def construir_panel(mapa: pd.DataFrame) -> pd.DataFrame:
    archivos = sorted(
        (f for f in DATOS_BICI.glob("*.csv") if PATRON_MES.search(f.name)),
        key=lambda f: PATRON_MES.search(f.name).group(0),
    )
    print(f"Procesando {len(archivos)} archivos mensuales para el panel colonia x mes...")

    filas = []
    for f in archivos:
        periodo = PATRON_MES.search(f.name).group(0).replace(".csv", "")
        origen_counts = pd.Series(dtype="int64")
        destino_counts = pd.Series(dtype="int64")

        for chunk in pd.read_csv(
            f,
            usecols=["Ciclo_Estacion_Retiro", "Ciclo_EstacionArribo"],
            dtype=str,
            chunksize=500_000,
        ):
            col_origen = chunk["Ciclo_Estacion_Retiro"].str.strip().map(mapa["colonia"])
            col_destino = chunk["Ciclo_EstacionArribo"].str.strip().map(mapa["colonia"])
            origen_counts = origen_counts.add(col_origen.value_counts(), fill_value=0)
            destino_counts = destino_counts.add(col_destino.value_counts(), fill_value=0)

        colonias = sorted(set(origen_counts.index) | set(destino_counts.index))
        for colonia in colonias:
            filas.append(
                {
                    "periodo": periodo,
                    "colonia": colonia,
                    "viajes_origen": int(origen_counts.get(colonia, 0)),
                    "viajes_destino": int(destino_counts.get(colonia, 0)),
                }
            )
        print(f"  {periodo}: {len(colonias)} colonias con actividad")

    panel = pd.DataFrame(filas)
    panel["viajes_total"] = panel["viajes_origen"] + panel["viajes_destino"]

    alcaldia_por_colonia = mapa.reset_index().drop_duplicates("colonia").set_index("colonia")["alcaldia"]
    panel["alcaldia"] = panel["colonia"].map(alcaldia_por_colonia)

    # Rejilla completa colonia x periodo (sin huecos), rellenando con 0 los
    # meses sin viajes registrados en una colonia que sí tuvo actividad en
    # otros periodos (requisito de pytorch-forecasting, CONTEXT.md 6.1.1).
    todas_colonias = panel["colonia"].unique()
    todos_periodos = panel["periodo"].unique()
    rejilla = pd.MultiIndex.from_product([todas_colonias, todos_periodos], names=["colonia", "periodo"])
    panel = (
        panel.set_index(["colonia", "periodo"])
        .reindex(rejilla, fill_value=0)
        .reset_index()
    )
    panel["alcaldia"] = panel["colonia"].map(alcaldia_por_colonia)

    return panel.sort_values(["colonia", "periodo"])


def periodo_a_time_idx(periodo: pd.Series) -> pd.Series:
    fecha = pd.to_datetime(periodo, format="%Y-%m")
    return (fecha.dt.year - fecha.dt.year.min()) * 12 + fecha.dt.month


def enriquecer_panel(panel: pd.DataFrame) -> pd.DataFrame:
    # Indice de uso Ecobici por zona: z-score de viajes_total normalizado
    # dentro de cada periodo (para comparar zonas entre si, no meses entre
    # si) - ver formula en CONTEXT.md 5.1.
    panel = panel.copy()
    media = panel.groupby("periodo")["viajes_total"].transform("mean")
    sigma = panel.groupby("periodo")["viajes_total"].transform("std").replace(0, np.nan)
    panel["indice_uso_ecobici"] = ((panel["viajes_total"] - media) / sigma).fillna(0.0)
    panel["time_idx"] = periodo_a_time_idx(panel["periodo"])
    return panel


def calcular_indice(panel: pd.DataFrame) -> pd.DataFrame:
    panel = enriquecer_panel(panel)

    filas = []
    for colonia, grupo in panel.groupby("colonia"):
        grupo = grupo.sort_values("time_idx")
        activos = grupo[grupo["viajes_total"] > 0]
        n_periodos_activos = len(activos)

        # Ajustar solo sobre periodos activos (viajes_total > 0): los
        # periodos anteriores a la apertura de estaciones en una colonia
        # quedan en 0 por la rejilla completa (ver construir_panel) y no son
        # "demanda cayendo a cero", son "todavia no habia estaciones ahi" -
        # incluirlos sesga la pendiente y el promedio hacia arriba de forma
        # artificial para colonias que se sumaron despues a la red.
        pendiente = np.nan
        if n_periodos_activos >= 3:
            pendiente, _, _, _ = theilslopes(activos["indice_uso_ecobici"], activos["time_idx"])

        if np.isnan(pendiente):
            categoria = "Datos insuficientes"
        elif pendiente > 0.02:
            categoria = "Creciente"
        elif pendiente < -0.02:
            categoria = "Decreciente"
        else:
            categoria = "Estable"

        filas.append(
            {
                "colonia": colonia,
                "alcaldia": grupo["alcaldia"].iloc[0],
                "n_periodos_con_datos": n_periodos_activos,
                "viajes_total_acumulado": int(grupo["viajes_total"].sum()),
                "viajes_total_promedio_mensual": activos["viajes_total"].mean() if n_periodos_activos else 0.0,
                "indice_uso_ecobici_promedio": activos["indice_uso_ecobici"].mean() if n_periodos_activos else 0.0,
                "indice_uso_ecobici_ultimo_periodo": grupo.iloc[-1]["indice_uso_ecobici"],
                "tendencia_pendiente_theilsen": pendiente,
                "tendencia_categoria": categoria,
            }
        )

    indice = pd.DataFrame(filas).sort_values("indice_uso_ecobici_promedio", ascending=False)
    return indice


def main() -> None:
    mapa = cargar_mapa_estaciones()
    panel = construir_panel(mapa)
    panel = enriquecer_panel(panel)

    SALIDA_PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(SALIDA_PANEL, index=False)
    print(f"Guardado panel: {SALIDA_PANEL} ({len(panel)} filas, "
          f"{panel['colonia'].nunique()} colonias x {panel['periodo'].nunique()} periodos)")

    indice = calcular_indice(panel)
    indice.to_csv(SALIDA_INDICE, index=False)
    print(f"Guardado indice: {SALIDA_INDICE} ({len(indice)} colonias)")
    print(indice["tendencia_categoria"].value_counts())


if __name__ == "__main__":
    main()
