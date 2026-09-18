"""Prueba de LightGBM cuantilico como alternativa al baseline de tendencia
lineal (CONTEXT.md 6.1: "alternativamente LightGBM/XGBoost con objetivo
cuantilico (P10/P50/P90) entrenado en formato panel (todas las zonas
juntas), usando el horizonte como feature - direct multi-horizon
forecasting").

Formato de entrenamiento: en vez de una fila por (colonia, periodo), se
construyen PARES (periodo_origen, periodo_destino) dentro de la misma
colonia, con `horizonte_meses = periodo_destino - periodo_origen` como
feature explicito. Esto permite entrenar un solo modelo global (con
`colonia`/`alcaldia` como categoricas) sobre todos los horizontes
observados en el panel a la vez, en vez de un modelo separado por colonia
como hace el baseline Theil-Sen.

Limitacion honesta (ver CONTEXT.md 6.3): el panel solo cubre ~25-42 meses
(2023-01 a 2026-06 con huecos), asi que el modelo nunca ve durante
entrenamiento un horizonte de 36 o 60 meses (3-5 anios, los horizontes que
pide el reto) - esos se extrapolan fuera del rango de horizontes
observados. Se documenta en vez de ocultarlo.

Entrada: data/processed/panel_demanda_colonia.csv (mismo panel que el
         baseline, ver baseline_tendencia.py)

Salidas:
  - data/processed/proyeccion_demanda_colonia_lgbm.csv
  - data/processed/validacion_retrospectiva_lgbm.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "data" / "processed" / "panel_demanda_colonia.csv"
SALIDA_PROYECCION = ROOT / "data" / "processed" / "proyeccion_demanda_colonia_lgbm.csv"
SALIDA_VALIDACION = ROOT / "data" / "processed" / "validacion_retrospectiva_lgbm.csv"

COLUMNA_OBJETIVO = "indice_demanda_compuesto"
COLUMNAS_ESTATICAS = ["alcaldia", "km_ciclovia", "poblacion_2020"]
CATEGORICAS = ["colonia", "alcaldia"]
FEATURES = ["colonia", "alcaldia", "km_ciclovia", "poblacion_2020", "time_idx_origen", "horizonte_meses", "valor_origen"]

HORIZONTES_ANIOS = [1, 3, 5]
MIN_PERIODOS_PARA_PAR = 2
MIN_PERIODOS_PARA_HOLDOUT = 4  # igual que baseline_tendencia.MIN_PERIODOS_PARA_TENDENCIA + 1
UMBRAL_CATEGORIA_MENSUAL = 0.02  # mismo criterio que baseline_tendencia.py

CUANTILES = {"prediccion_p10": 0.1, "prediccion_p50": 0.5, "prediccion_p90": 0.9}

PARAMS_LGBM = dict(
    n_estimators=200,
    num_leaves=15,
    min_child_samples=10,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=0,
    verbose=-1,
)


def categoria_por_delta(delta: float, pasos: float = 1) -> str:
    if np.isnan(delta):
        return "Datos insuficientes"
    umbral = UMBRAL_CATEGORIA_MENSUAL * pasos
    if delta > umbral:
        return "Creciente"
    if delta < -umbral:
        return "Decreciente"
    return "Estable"


def construir_pares(panel: pd.DataFrame, excluir_ultimo_periodo: bool) -> pd.DataFrame:
    """Construye todos los pares (periodo_origen, periodo_destino) dentro de
    cada colonia, sobre los periodos con viajes_total > 0. Si
    excluir_ultimo_periodo=True, el ultimo periodo activo de cada colonia se
    descarta antes de formar pares (usado para el conjunto de entrenamiento
    de la validacion retrospectiva, igual que baseline_tendencia.py)."""
    filas = []
    for colonia, grupo in panel.groupby("colonia"):
        activos = grupo[grupo["viajes_total"] > 0].sort_values("time_idx")
        if excluir_ultimo_periodo:
            activos = activos.iloc[:-1]
        if len(activos) < MIN_PERIODOS_PARA_PAR:
            continue

        estaticas = activos.iloc[0]
        x_time = activos["time_idx"].to_numpy(dtype=float)
        x_val = activos[COLUMNA_OBJETIVO].to_numpy(dtype=float)

        for i in range(len(activos)):
            for j in range(i + 1, len(activos)):
                filas.append(
                    {
                        "colonia": colonia,
                        "alcaldia": estaticas["alcaldia"],
                        "km_ciclovia": estaticas["km_ciclovia"],
                        "poblacion_2020": estaticas["poblacion_2020"],
                        "time_idx_origen": x_time[i],
                        "horizonte_meses": x_time[j] - x_time[i],
                        "valor_origen": x_val[i],
                        "valor_destino": x_val[j],
                    }
                )
    pares = pd.DataFrame(filas)
    for col in CATEGORICAS:
        pares[col] = pares[col].astype("category")
    return pares


def entrenar_modelos(pares: pd.DataFrame) -> dict:
    """Entrena un LGBMRegressor con objective='quantile' por cada cuantil en
    CUANTILES, sobre el mismo conjunto de pares (formato panel: todas las
    colonias juntas, horizonte como feature)."""
    X = pares[FEATURES]
    y = pares["valor_destino"]
    modelos = {}
    for nombre, alpha in CUANTILES.items():
        modelo = LGBMRegressor(objective="quantile", alpha=alpha, **PARAMS_LGBM)
        modelo.fit(X, y, categorical_feature=CATEGORICAS)
        modelos[nombre] = modelo
    return modelos


def predecir(modelos: dict, X: pd.DataFrame) -> pd.DataFrame:
    pred = pd.DataFrame(index=X.index)
    for nombre, modelo in modelos.items():
        pred[nombre] = modelo.predict(X)
    # Los cuantiles se entrenan por separado y pueden cruzarse (p10 > p90)
    # con pocos datos - se ordenan explicitamente para que el intervalo
    # reportado tenga sentido, igual que hace baseline_tendencia.py con
    # pendiente_lo/pendiente_hi.
    lo = pred[["prediccion_p10", "prediccion_p90"]].min(axis=1)
    hi = pred[["prediccion_p10", "prediccion_p90"]].max(axis=1)
    pred["prediccion_p10"], pred["prediccion_p90"] = lo, hi
    return pred


def proyectar(panel: pd.DataFrame) -> pd.DataFrame:
    pares = construir_pares(panel, excluir_ultimo_periodo=False)
    modelos = entrenar_modelos(pares)

    filas_base = []
    for colonia, grupo in panel.groupby("colonia"):
        alcaldia = grupo["alcaldia"].iloc[0]
        activos = grupo[grupo["viajes_total"] > 0].sort_values("time_idx")
        if len(activos) < MIN_PERIODOS_PARA_PAR:
            for h in HORIZONTES_ANIOS:
                filas_base.append(
                    {
                        "colonia": colonia,
                        "alcaldia": alcaldia,
                        "horizonte_anios": h,
                        "colonia_cat": colonia,
                        "alcaldia_cat": alcaldia,
                        "km_ciclovia": np.nan,
                        "poblacion_2020": np.nan,
                        "time_idx_origen": np.nan,
                        "horizonte_meses": h * 12,
                        "valor_origen": np.nan,
                    }
                )
            continue

        ultimo = activos.iloc[-1]
        for h in HORIZONTES_ANIOS:
            filas_base.append(
                {
                    "colonia": colonia,
                    "alcaldia": alcaldia,
                    "horizonte_anios": h,
                    "colonia_cat": colonia,
                    "alcaldia_cat": alcaldia,
                    "km_ciclovia": ultimo["km_ciclovia"],
                    "poblacion_2020": ultimo["poblacion_2020"],
                    "time_idx_origen": ultimo["time_idx"],
                    "horizonte_meses": h * 12,
                    "valor_origen": ultimo[COLUMNA_OBJETIVO],
                }
            )

    base = pd.DataFrame(filas_base)
    validos = base["time_idx_origen"].notna()

    X = base.loc[validos, ["colonia_cat", "alcaldia_cat", "km_ciclovia", "poblacion_2020", "time_idx_origen", "horizonte_meses", "valor_origen"]]
    X = X.rename(columns={"colonia_cat": "colonia", "alcaldia_cat": "alcaldia"})
    for col in CATEGORICAS:
        X[col] = X[col].astype(pares[col].dtype)

    pred = predecir(modelos, X)
    resultado = base[["colonia", "alcaldia", "horizonte_anios"]].copy()
    for col in ["prediccion_p50", "prediccion_p10", "prediccion_p90"]:
        resultado[col] = np.nan
    resultado.loc[validos, pred.columns] = pred.to_numpy()

    resultado["categoria_proyectada"] = [
        categoria_por_delta(p50 - v0, pasos=h * 12) if not np.isnan(p50) else "Datos insuficientes"
        for p50, v0, h in zip(resultado["prediccion_p50"], base["valor_origen"], base["horizonte_anios"])
    ]
    return resultado


def validar_retrospectivo(panel: pd.DataFrame) -> pd.DataFrame:
    """Mismo esquema de hold-out que baseline_tendencia.validar_retrospectivo:
    ultimo periodo activo por colonia como prueba, resto como entrenamiento -
    pero aqui un unico modelo global se entrena una vez con los pares de
    TODAS las colonias (excluyendo el periodo de prueba de cada una)."""
    pares_entrenamiento = construir_pares(panel, excluir_ultimo_periodo=True)
    modelos = entrenar_modelos(pares_entrenamiento)

    filas_prueba = []
    for colonia, grupo in panel.groupby("colonia"):
        activos = grupo[grupo["viajes_total"] > 0].sort_values("time_idx")
        if len(activos) < MIN_PERIODOS_PARA_HOLDOUT:
            continue

        entrenamiento = activos.iloc[:-1]
        prueba = activos.iloc[-1]
        origen = entrenamiento.iloc[-1]

        filas_prueba.append(
            {
                "colonia": colonia,
                "alcaldia": grupo["alcaldia"].iloc[0],
                "periodo_prueba": prueba["periodo"],
                "km_ciclovia": origen["km_ciclovia"],
                "poblacion_2020": origen["poblacion_2020"],
                "time_idx_origen": origen["time_idx"],
                "horizonte_meses": float(prueba["time_idx"] - origen["time_idx"]),
                "valor_origen": origen[COLUMNA_OBJETIVO],
                "valor_real": prueba[COLUMNA_OBJETIVO],
                "prediccion_naive": origen[COLUMNA_OBJETIVO],
            }
        )

    prueba_df = pd.DataFrame(filas_prueba)
    for col in CATEGORICAS:
        prueba_df[col] = prueba_df[col].astype(pares_entrenamiento[col].dtype)

    pred = predecir(modelos, prueba_df[FEATURES])
    prueba_df = pd.concat([prueba_df.reset_index(drop=True), pred.reset_index(drop=True)], axis=1)

    prueba_df["error_abs"] = (prueba_df["valor_real"] - prueba_df["prediccion_p50"]).abs()
    prueba_df["error"] = prueba_df["valor_real"] - prueba_df["prediccion_p50"]
    prueba_df["dentro_p10_p90"] = (prueba_df["prediccion_p10"] <= prueba_df["valor_real"]) & (
        prueba_df["valor_real"] <= prueba_df["prediccion_p90"]
    )
    # `pasos` = horizonte_meses real del par de hold-out, no 1 fijo: los meses
    # sin actividad se filtran, asi que origen y prueba pueden estar a mas de un
    # mes de distancia y el umbral de categoria es MENSUAL (mismo arreglo que en
    # baseline_tendencia.validar_retrospectivo).
    prueba_df["categoria_predicha"] = [
        categoria_por_delta(p50 - v0, pasos=h)
        for p50, v0, h in zip(prueba_df["prediccion_p50"], prueba_df["valor_origen"], prueba_df["horizonte_meses"])
    ]
    prueba_df["categoria_real"] = [
        categoria_por_delta(real - v0, pasos=h)
        for real, v0, h in zip(prueba_df["valor_real"], prueba_df["valor_origen"], prueba_df["horizonte_meses"])
    ]
    prueba_df["categoria_acierto"] = prueba_df["categoria_predicha"] == prueba_df["categoria_real"]
    prueba_df["error_abs_naive"] = (prueba_df["valor_real"] - prueba_df["prediccion_naive"]).abs()
    prueba_df["error_naive"] = prueba_df["valor_real"] - prueba_df["prediccion_naive"]

    columnas_salida = [
        "colonia", "alcaldia", "periodo_prueba", "valor_real",
        "prediccion_p50", "prediccion_p10", "prediccion_p90",
        "error_abs", "error", "dentro_p10_p90",
        "categoria_predicha", "categoria_real", "categoria_acierto",
        "prediccion_naive", "error_abs_naive", "error_naive",
    ]
    return prueba_df[columnas_salida]


def reportar_metricas(validacion: pd.DataFrame) -> None:
    mae = validacion["error_abs"].mean()
    rmse = np.sqrt((validacion["error"] ** 2).mean())
    cobertura = validacion["dentro_p10_p90"].mean()
    acierto_direccional = validacion["categoria_acierto"].mean()

    mae_naive = validacion["error_abs_naive"].mean()
    rmse_naive = np.sqrt((validacion["error_naive"] ** 2).mean())

    print(f"\n--- Validacion retrospectiva LightGBM cuantilico (n={len(validacion)} colonias, holdout 1 mes) ---")
    print(f"{'Modelo':<28}{'MAE':>10}{'RMSE':>10}")
    print(f"{'LightGBM cuantilico':<28}{mae:>10.4f}{rmse:>10.4f}")
    print(f"{'Naive (persistencia)':<28}{mae_naive:>10.4f}{rmse_naive:>10.4f}")
    print(f"\nCobertura empirica P10-P90 (esperado ~80%): {cobertura:.1%}")
    print(f"Precision direccional (categoria, umbral +/-{UMBRAL_CATEGORIA_MENSUAL}/mes): {acierto_direccional:.1%}")
    print("\nMatriz de confusion (predicha vs real):")
    print(pd.crosstab(validacion["categoria_predicha"], validacion["categoria_real"]))

    if mae_naive < mae:
        print(
            "\nAVISO: a 1 mes de horizonte, la persistencia naive tiene menor error que "
            "LightGBM cuantilico. Mismo fenomeno que con el baseline Theil-Sen (ver "
            "CONTEXT.md 6.3.1): el indice mensual es ruidoso y el hold-out de 1 mes no es "
            "representativo del horizonte real de la app (1-5 anios)."
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
