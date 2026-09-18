"""Modelo baseline (CONTEXT.md 6.1): tendencia robusta Theil-Sen del indice
de demanda por colonia, extrapolada a los horizontes 1/3/5 anios pedidos
por el reto, con banda de incertidumbre a partir del intervalo de confianza
de la pendiente.

Incluye tambien la validacion retrospectiva obligatoria (CONTEXT.md 6.3):
hold-out del ultimo periodo observado, comparando la extrapolacion del
modelo entrenado con el resto contra el valor real.

Entrada: data/processed/panel_demanda_colonia.csv (colonia, periodo,
         COLUMNA_OBJETIVO, time_idx - generado por panel_demanda_ecobici.py
         + indice_compuesto.py)

Salidas:
  - data/processed/proyeccion_demanda_colonia.csv
  - data/processed/validacion_retrospectiva_baseline.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "data" / "processed" / "panel_demanda_colonia.csv"
SALIDA_PROYECCION = ROOT / "data" / "processed" / "proyeccion_demanda_colonia.csv"
SALIDA_VALIDACION = ROOT / "data" / "processed" / "validacion_retrospectiva_baseline.csv"

# Objetivo del baseline: el indice de demanda COMPUESTO (CONTEXT.md 5 +
# indice_compuesto.py) si ya esta disponible en el panel; si no, cae de
# vuelta al indice de solo-uso-Ecobici (panel_demanda_ecobici.py).
COLUMNA_OBJETIVO = "indice_demanda_compuesto"

HORIZONTES_ANIOS = [1, 3, 5]
MIN_PERIODOS_PARA_TENDENCIA = 3
# Umbral de la PENDIENTE MENSUAL (mismo criterio que indice_demanda_colonia.csv,
# CONTEXT.md 5.1). Para categorizar un delta acumulado sobre "pasos" meses hay
# que escalarlo (umbral_acumulado = UMBRAL_CATEGORIA_MENSUAL * pasos) - un
# umbral fijo aplicado a un delta de 60 meses categorizaria como
# "Decreciente"/"Creciente" tendencias que en realidad son planas.
UMBRAL_CATEGORIA_MENSUAL = 0.02


def categoria_por_delta(delta: float, pasos: float = 1) -> str:
    if np.isnan(delta):
        return "Datos insuficientes"
    umbral = UMBRAL_CATEGORIA_MENSUAL * pasos
    if delta > umbral:
        return "Creciente"
    if delta < -umbral:
        return "Decreciente"
    return "Estable"


def ajustar_tendencia(grupo: pd.DataFrame):
    """Ajusta Theil-Sen sobre (time_idx, COLUMNA_OBJETIVO) de un grupo ya
    ordenado y filtrado a periodos con viajes_total > 0. Devuelve
    (pendiente, pendiente_lo, pendiente_hi, time_idx_ultimo, valor_ajustado_ultimo)
    o None si no hay suficientes puntos."""
    activos = grupo[grupo["viajes_total"] > 0].sort_values("time_idx")
    if len(activos) < MIN_PERIODOS_PARA_TENDENCIA:
        return None

    x = activos["time_idx"].to_numpy(dtype=float)
    y = activos[COLUMNA_OBJETIVO].to_numpy(dtype=float)
    pendiente, intercepto, pendiente_lo, pendiente_hi = theilslopes(y, x)

    x_ultimo = x[-1]
    valor_ajustado_ultimo = intercepto + pendiente * x_ultimo
    return pendiente, pendiente_lo, pendiente_hi, x_ultimo, valor_ajustado_ultimo


def proyectar(panel: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for colonia, grupo in panel.groupby("colonia"):
        alcaldia = grupo["alcaldia"].iloc[0]
        ajuste = ajustar_tendencia(grupo)

        if ajuste is None:
            for h in HORIZONTES_ANIOS:
                filas.append(
                    {
                        "colonia": colonia,
                        "alcaldia": alcaldia,
                        "horizonte_anios": h,
                        "prediccion_p50": np.nan,
                        "prediccion_p10": np.nan,
                        "prediccion_p90": np.nan,
                        "categoria_proyectada": "Datos insuficientes",
                    }
                )
            continue

        pendiente, pendiente_lo, pendiente_hi, x_ultimo, valor_ultimo = ajuste
        for h in HORIZONTES_ANIOS:
            pasos = h * 12
            p50 = valor_ultimo + pendiente * pasos
            p10 = valor_ultimo + pendiente_lo * pasos
            p90 = valor_ultimo + pendiente_hi * pasos
            filas.append(
                {
                    "colonia": colonia,
                    "alcaldia": alcaldia,
                    "horizonte_anios": h,
                    "prediccion_p50": p50,
                    "prediccion_p10": min(p10, p90),
                    "prediccion_p90": max(p10, p90),
                    "categoria_proyectada": categoria_por_delta(p50 - valor_ultimo, pasos=pasos),
                }
            )

    return pd.DataFrame(filas)


def validar_retrospectivo(panel: pd.DataFrame) -> pd.DataFrame:
    """Hold-out del ultimo periodo con datos de cada colonia: ajusta con el
    resto, predice ese periodo, compara con el valor real observado."""
    filas = []
    for colonia, grupo in panel.groupby("colonia"):
        activos = grupo[grupo["viajes_total"] > 0].sort_values("time_idx")
        if len(activos) < MIN_PERIODOS_PARA_TENDENCIA + 1:
            continue

        entrenamiento = activos.iloc[:-1]
        prueba = activos.iloc[-1]

        x = entrenamiento["time_idx"].to_numpy(dtype=float)
        y = entrenamiento[COLUMNA_OBJETIVO].to_numpy(dtype=float)
        pendiente, intercepto, pendiente_lo, pendiente_hi = theilslopes(y, x)

        x_prueba = float(prueba["time_idx"])
        x_ultimo_train = x[-1]
        y_ultimo_train = intercepto + pendiente * x_ultimo_train
        pasos = x_prueba - x_ultimo_train

        # El intervalo se ancla en el ULTIMO punto ajustado y se abre con
        # `pasos` meses de distancia, EXACTAMENTE como lo construye proyectar().
        # Antes se calculaba `intercepto + pendiente_lo * x_prueba`, que pivota
        # la banda en x=0 en vez de en el ultimo dato: el brazo de palanca pasa
        # a ser el time_idx absoluto (~42) en lugar de la distancia real de
        # pronostico (1 mes), y el intervalo sale ~42x mas ancho. La cobertura
        # reportada era 96.3% - pero del intervalo que el modelo produce de
        # verdad, no del que se estaba midiendo. Una validacion tiene que medir
        # el mismo objeto que se entrega en produccion.
        pred_p50 = y_ultimo_train + pendiente * pasos
        pred_p10 = y_ultimo_train + pendiente_lo * pasos
        pred_p90 = y_ultimo_train + pendiente_hi * pasos
        pred_p10, pred_p90 = min(pred_p10, pred_p90), max(pred_p10, pred_p90)

        real = float(prueba[COLUMNA_OBJETIVO])
        ultimo_valor_observado = float(entrenamiento.iloc[-1][COLUMNA_OBJETIVO])

        # `pasos` real, no 1 fijo: los periodos inactivos (viajes_total == 0) se
        # filtran, asi que el salto entre el ultimo mes de entrenamiento y el de
        # prueba puede ser de varios meses, y el umbral de categoria es MENSUAL.
        cat_predicha = categoria_por_delta(pred_p50 - y_ultimo_train, pasos=pasos)
        cat_real = categoria_por_delta(real - y_ultimo_train, pasos=pasos)

        filas.append(
            {
                "colonia": colonia,
                "alcaldia": grupo["alcaldia"].iloc[0],
                "periodo_prueba": prueba["periodo"],
                "valor_real": real,
                "prediccion_p50": pred_p50,
                "prediccion_p10": pred_p10,
                "prediccion_p90": pred_p90,
                "error_abs": abs(real - pred_p50),
                "error": real - pred_p50,
                "dentro_p10_p90": pred_p10 <= real <= pred_p90,
                "categoria_predicha": cat_predicha,
                "categoria_real": cat_real,
                "categoria_acierto": cat_predicha == cat_real,
                # Baseline de referencia (naive persistence): predice que el
                # proximo mes es igual al ultimo mes observado. Sirve para
                # saber si la tendencia Theil-Sen realmente aporta algo a 1
                # mes de horizonte - ver CONTEXT.md 6.3.
                "prediccion_naive": ultimo_valor_observado,
                "error_abs_naive": abs(real - ultimo_valor_observado),
                "error_naive": real - ultimo_valor_observado,
            }
        )

    return pd.DataFrame(filas)


def reportar_metricas(validacion: pd.DataFrame) -> None:
    mae = validacion["error_abs"].mean()
    rmse = np.sqrt((validacion["error"] ** 2).mean())
    cobertura = validacion["dentro_p10_p90"].mean()
    acierto_direccional = validacion["categoria_acierto"].mean()

    mae_naive = validacion["error_abs_naive"].mean()
    rmse_naive = np.sqrt((validacion["error_naive"] ** 2).mean())

    print(f"\n--- Validacion retrospectiva baseline (n={len(validacion)} colonias, holdout 1 mes) ---")
    print(f"{'Modelo':<28}{'MAE':>10}{'RMSE':>10}")
    print(f"{'Tendencia Theil-Sen':<28}{mae:>10.4f}{rmse:>10.4f}")
    print(f"{'Naive (persistencia)':<28}{mae_naive:>10.4f}{rmse_naive:>10.4f}")
    print(f"\nCobertura empirica P10-P90 (esperado ~80%): {cobertura:.1%}")
    print(f"Precision direccional (categoria, umbral +/-{UMBRAL_CATEGORIA_MENSUAL}/mes): {acierto_direccional:.1%}")
    print("\nMatriz de confusion (predicha vs real):")
    print(pd.crosstab(validacion["categoria_predicha"], validacion["categoria_real"]))

    if mae_naive < mae:
        print(
            "\nAVISO: a 1 mes de horizonte, la persistencia naive tiene menor error que la "
            "tendencia Theil-Sen. Esperado: el indice mensual es ruidoso y la tendencia esta "
            "disenada para extrapolar 1-5 anios, no para el mes siguiente. Ver CONTEXT.md 6.3."
        )


def main() -> None:
    panel = pd.read_csv(PANEL, dtype={"periodo": str})

    proyeccion = proyectar(panel)
    SALIDA_PROYECCION.parent.mkdir(parents=True, exist_ok=True)
    proyeccion.to_csv(SALIDA_PROYECCION, index=False)
    print(f"Guardado: {SALIDA_PROYECCION} ({proyeccion['colonia'].nunique()} colonias x {len(HORIZONTES_ANIOS)} horizontes)")

    validacion = validar_retrospectivo(panel)
    validacion.to_csv(SALIDA_VALIDACION, index=False)
    print(f"Guardado: {SALIDA_VALIDACION} ({len(validacion)} colonias evaluadas)")

    reportar_metricas(validacion)


if __name__ == "__main__":
    main()
