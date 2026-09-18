"""Indice de demanda COMPUESTO (CONTEXT.md 5): combina las 5 fuentes de la
seccion 5 de CONTEXT.md. Componentes y pesos (actualizado 2026-09-15, al
cerrar los 5 componentes con ATUS + Marco Geoestadistico):

  - uso Ecobici (0.5): z-score de viajes_total entre zonas, por periodo.
    Unico componente con variacion mes a mes real y resolucion de colonia.
  - aperturas DENUE bici/mensajeria (0.15): z-score de aperturas por periodo
    (via fecha_alta, ver indicadores_denue.py - senal dispersa, la mayoria
    de colonia-periodo valen 0).
  - brecha de infraestructura (0.15): z-score de -km_ciclovia (estatico, un
    solo snapshot marzo 2025) - zonas con MENOS km de ciclovia puntuan mas
    alto aqui (interpretacion: demanda insatisfecha / oportunidad).
  - senal de seguridad / ATUS (0.1): z-score de accidentes_ciclistas por
    periodo (ver indicadores_atus.py). Resolucion de ALCALDIA, no colonia
    (ATUS viene a nivel municipio - CONTEXT.md 6.1.1), asi que todas las
    colonias de una alcaldia comparten el mismo valor en un periodo dado.
    Mas siniestros -> mayor puntaje (interpretacion: necesidad de
    infraestructura no atendida, no "mas demanda" en sentido positivo).
  - crecimiento demografico / poblacion por colonia (0.1): z-score de
    poblacion_colonia_2020 (ver indicadores_poblacion_colonia.py, requirio el
    Marco Geoestadistico para la union AGEB->colonia). Estatico (un solo
    corte 2020, no aporta tendencia) pero SI discrimina entre colonias de
    una misma alcaldia, a diferencia de poblacion_alcaldia.csv (que se deja
    solo informativa, ver mas abajo).

poblacion_alcaldia.csv (indicadores_poblacion.py) sigue sin entrar al
z-score: es estatica por ALCALDIA, no discrimina entre colonias de la misma
alcaldia. Se deja como columna informativa en el mapa/tabla.

Los pesos (0.5/0.15/0.15/0.1/0.1) son una asignacion razonada, no calibrada
contra ninguna verdad de terreno (no existe una "demanda real" medible para
ajustarlos) - CONTEXT.md 5 ya anticipaba esto ("la formula exacta... se
define con base en la disponibilidad real de datos"). Ecobici mantiene el
mayor peso porque es el unico componente con variacion mensual real a nivel
colonia; los otros 4 son estaticos o de resolucion mas gruesa (alcaldia).

Entradas:
  - data/processed/panel_demanda_colonia.csv
  - data/processed/denue_aperturas_colonia_mes.csv
  - data/processed/infraestructura_km_colonia.csv
  - data/processed/atus_accidentes_alcaldia_mes.csv
  - data/processed/poblacion_colonia.csv
  - data/processed/poblacion_alcaldia.csv (solo informativo)

Salida: data/processed/panel_demanda_colonia.csv (se sobreescribe, agregando
columnas) y data/processed/indice_demanda_colonia.csv (ranking + tendencia,
ahora sobre el indice compuesto).
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "data" / "processed" / "panel_demanda_colonia.csv"
APERTURAS = ROOT / "data" / "processed" / "denue_aperturas_colonia_mes.csv"
KM_CICLOVIA = ROOT / "data" / "processed" / "infraestructura_km_colonia.csv"
ATUS = ROOT / "data" / "processed" / "atus_accidentes_alcaldia_mes.csv"
POBLACION_COLONIA = ROOT / "data" / "processed" / "poblacion_colonia.csv"
POBLACION_ALCALDIA = ROOT / "data" / "processed" / "poblacion_alcaldia.csv"

DENUE_NIVEL = ROOT / "data" / "processed" / "denue_nivel_colonia.csv"
SALIDA_INDICE = ROOT / "data" / "processed" / "indice_demanda_colonia.csv"

PESOS = {
    "uso_ecobici": 0.5,
    "aperturas_denue": 0.15,
    "brecha_infraestructura": 0.15,
    "siniestralidad_ciclista": 0.1,
    "poblacion_colonia": 0.1,
}
UMBRAL_CATEGORIA_MENSUAL = 0.02


def zscore_por_periodo(df: pd.DataFrame, columna: str, periodo_col: str = "periodo") -> pd.Series:
    media = df.groupby(periodo_col)[columna].transform("mean")
    sigma = df.groupby(periodo_col)[columna].transform("std").replace(0, np.nan)
    return ((df[columna] - media) / sigma).fillna(0.0)


def zscore_estatico(serie: pd.Series) -> pd.Series:
    """Z-score de una serie estatica. Robusto ante no-finitos: un solo +/-inf
    hace que serie.std() sea NaN, y el guardarropa de abajo devolvia entonces
    0.0 para TODAS las zonas - es decir, la senal desaparecia entera sin avisar
    (fue exactamente lo que paso con densidad_comercial_por_mil_hab cuando
    tenia +inf por division entre poblacion 0). Los inf se tratan como dato
    ausente: no participan en media/sigma y salen como 0.0 (neutral)."""
    serie = serie.replace([np.inf, -np.inf], np.nan)
    finitos = serie.dropna()
    if len(finitos) < 2:
        return pd.Series(0.0, index=serie.index)
    media, sigma = finitos.mean(), finitos.std()
    if not sigma or pd.isna(sigma):
        return pd.Series(0.0, index=serie.index)
    return ((serie - media) / sigma).fillna(0.0)


def construir_panel_enriquecido() -> pd.DataFrame:
    panel = pd.read_csv(PANEL, dtype={"periodo": str})
    # Solo se conservan las columnas base (por si el script se corre mas de
    # una vez sobre un panel ya enriquecido en una corrida anterior).
    columnas_base = ["colonia", "periodo", "viajes_origen", "viajes_destino", "viajes_total", "alcaldia"]
    panel = panel[columnas_base].copy()

    aperturas = pd.read_csv(APERTURAS, dtype={"periodo": str}).rename(
        columns={"colonia_ecobici": "colonia"}
    )
    panel = panel.merge(aperturas, on=["colonia", "periodo"], how="left")
    panel["aperturas_denue"] = panel["aperturas_denue"].fillna(0)

    km = pd.read_csv(KM_CICLOVIA).rename(columns={"colonia_ecobici": "colonia"})
    panel = panel.merge(km, on="colonia", how="left")  # NaN si la colonia no tiene poligono

    atus = pd.read_csv(ATUS, dtype={"periodo": str})
    panel = panel.merge(atus, on=["alcaldia", "periodo"], how="left")
    # NaN = sin accidentes reportados ESE mes en ESA alcaldia, o periodo fuera
    # de la cobertura de ATUS (2023-2025; el panel llega a 2026-06, ver
    # indicadores_atus.py) - en ambos casos se trata como 0, no se distingue
    # (limitacion documentada, ver docs/fuentes_datos.md).
    panel["accidentes_ciclistas"] = panel["accidentes_ciclistas"].fillna(0)
    panel["victimas_ciclistas"] = panel["victimas_ciclistas"].fillna(0)

    poblacion_colonia = pd.read_csv(POBLACION_COLONIA)
    panel = panel.merge(poblacion_colonia, on="colonia", how="left")  # NaN si la colonia no tiene poligono

    poblacion_alcaldia = pd.read_csv(POBLACION_ALCALDIA)
    panel = panel.merge(poblacion_alcaldia, on="alcaldia", how="left")

    panel["indice_uso_ecobici"] = zscore_por_periodo(panel, "viajes_total")
    panel["indice_aperturas_denue"] = zscore_por_periodo(panel, "aperturas_denue")
    panel["indice_siniestralidad_ciclista"] = zscore_por_periodo(panel, "accidentes_ciclistas")

    # km_ciclovia y poblacion_colonia_2020 son estaticos (no cambian por
    # periodo) - se calculan UNA VEZ por colonia y se repiten en todos los
    # periodos; las colonias sin poligono (NaN) se excluyen del z-score y
    # luego se imputan a 0 (no se favorece ni penaliza por falta de dato).
    km_unico = panel.drop_duplicates("colonia")[["colonia", "km_ciclovia"]].set_index("colonia")["km_ciclovia"]
    z_gap_por_colonia = zscore_estatico(-km_unico)  # menos km -> mayor "brecha"
    panel["indice_brecha_infraestructura"] = panel["colonia"].map(z_gap_por_colonia).fillna(0.0)

    poblacion_unica = (
        panel.drop_duplicates("colonia")[["colonia", "poblacion_colonia_2020"]]
        .set_index("colonia")["poblacion_colonia_2020"]
    )
    z_poblacion_por_colonia = zscore_estatico(poblacion_unica)
    panel["indice_poblacion_colonia"] = panel["colonia"].map(z_poblacion_por_colonia).fillna(0.0)

    panel["indice_demanda_compuesto"] = (
        PESOS["uso_ecobici"] * panel["indice_uso_ecobici"]
        + PESOS["aperturas_denue"] * panel["indice_aperturas_denue"]
        + PESOS["brecha_infraestructura"] * panel["indice_brecha_infraestructura"]
        + PESOS["siniestralidad_ciclista"] * panel["indice_siniestralidad_ciclista"]
        + PESOS["poblacion_colonia"] * panel["indice_poblacion_colonia"]
    )

    panel["time_idx"] = (
        pd.to_datetime(panel["periodo"], format="%Y-%m").dt.year.sub(
            pd.to_datetime(panel["periodo"], format="%Y-%m").dt.year.min()
        )
        * 12
        + pd.to_datetime(panel["periodo"], format="%Y-%m").dt.month
    )

    return panel


def calcular_ranking(panel: pd.DataFrame) -> pd.DataFrame:
    denue_nivel = pd.read_csv(DENUE_NIVEL).rename(columns={"colonia_ecobici": "colonia"}).set_index("colonia")
    establecimientos_snapshot = denue_nivel["establecimientos_relacionados_total"]

    filas = []
    for colonia, grupo in panel.groupby("colonia"):
        grupo = grupo.sort_values("time_idx")
        activos = grupo[grupo["viajes_total"] > 0]
        n_activos = len(activos)

        pendiente = np.nan
        if n_activos >= 3:
            pendiente, _, _, _ = theilslopes(activos["indice_demanda_compuesto"], activos["time_idx"])

        if np.isnan(pendiente):
            categoria = "Datos insuficientes"
        elif pendiente > UMBRAL_CATEGORIA_MENSUAL:
            categoria = "Creciente"
        elif pendiente < -UMBRAL_CATEGORIA_MENSUAL:
            categoria = "Decreciente"
        else:
            categoria = "Estable"

        filas.append(
            {
                "colonia": colonia,
                "alcaldia": grupo["alcaldia"].iloc[0],
                "n_periodos_con_datos": n_activos,
                "viajes_total_acumulado": int(grupo["viajes_total"].sum()),
                "km_ciclovia": grupo["km_ciclovia"].iloc[0],
                "establecimientos_denue_relacionados": int(establecimientos_snapshot.get(colonia, 0)),
                "aperturas_denue_en_ventana_panel": int(grupo["aperturas_denue"].sum()),
                "accidentes_ciclistas_en_ventana_panel": int(grupo["accidentes_ciclistas"].sum()),
                "victimas_ciclistas_en_ventana_panel": int(grupo["victimas_ciclistas"].sum()),
                "poblacion_colonia_2020": grupo["poblacion_colonia_2020"].iloc[0],
                "poblacion_alcaldia_2020": grupo["poblacion_2020"].iloc[0],
                "indice_uso_ecobici_promedio": activos["indice_uso_ecobici"].mean() if n_activos else 0.0,
                "indice_demanda_compuesto_promedio": activos["indice_demanda_compuesto"].mean() if n_activos else 0.0,
                "tendencia_pendiente_theilsen": pendiente,
                "tendencia_categoria": categoria,
            }
        )

    return pd.DataFrame(filas).sort_values("indice_demanda_compuesto_promedio", ascending=False)


def main() -> None:
    panel = construir_panel_enriquecido()
    panel.to_csv(PANEL, index=False)
    print(f"Panel enriquecido guardado: {PANEL} ({len(panel)} filas, columnas: {panel.columns.tolist()})")

    ranking = calcular_ranking(panel)
    ranking.to_csv(SALIDA_INDICE, index=False)
    print(f"\nGuardado: {SALIDA_INDICE} ({len(ranking)} colonias)")
    print(ranking["tendencia_categoria"].value_counts())
    print("\nTop 10 por indice compuesto:")
    print(
        ranking.head(10)[
            ["colonia", "alcaldia", "indice_demanda_compuesto_promedio", "km_ciclovia", "tendencia_categoria"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
