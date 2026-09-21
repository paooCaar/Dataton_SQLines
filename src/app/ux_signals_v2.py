"""Read-only presentation signals; never model inputs or persisted forecasts."""
import numpy as np
import pandas as pd

PRODUCT_THRESHOLD_PCT = 5.0
MAP_EXPLANATIONS = {
    "Actividad prevista": "Cuánta actividad ECOBICI esperamos en esta colonia para el horizonte elegido. El punto central usa persistencia porque fue el método más estable en validación retrospectiva.",
    "Incertidumbre": "Qué amplitud tiene el rango construido con errores históricos del forecast. El mapa compara su ancho relativo a la actividad prevista; no mide una probabilidad ni dificultad histórica individual por colonia.",
    "Tendencia reciente": "Esta vista muestra cómo venía cambiando la actividad observada de ECOBICI. Es historia observada, no una predicción.",
    "Cambio esperado": "Con el modelo de persistencia, el cambio puntual suele ser cercano a 0%. Por eso esta vista es principalmente técnica.",
    "Dirección": "La dirección resume el cambio puntual del forecast. Con persistencia muchas zonas aparecen como ESTABLE.",
    "Opportunity Score": "Este indicador es complementario y no forma parte del forecast V2.",
}
SCENARIO_EXPLANATIONS = {
    "Bajo": "Trayectoria conservadora. Combina el crecimiento histórico bajo de ECOBICI con un escenario donde la presión vial disminuye.",
    "Base": "Trayectoria central. Parte del forecast de 12 meses, usa la tendencia histórica mediana de ECOBICI y mantiene neutral el efecto TomTom.",
    "Alto": "Trayectoria de mayor crecimiento. Combina la tendencia histórica alta de ECOBICI con un escenario de mayor presión vial. No significa que este resultado sea el más probable.",
}
LONG_MAP_EXPLANATIONS = {
    "Actividad del escenario": "Actividad mensual que resultaría bajo la hipótesis seleccionada; no es un forecast validado.",
    "Cambio vs. ancla": "Cambio porcentual del escenario frente al forecast de 12 meses. Es un cambio condicionado acumulado desde el ancla, no el cambio puntual del forecast corto.",
    "Dirección del escenario": "AUMENTO por encima de +5%, DISMINUCIÓN por debajo de −5% y ESTABLE entre ambos. Es una regla de producto, no significancia estadística.",
    "Aporte TomTom": "Ajuste porcentual aplicado al escenario ECOBICI. Es igual para todas las colonias dentro de cada escenario y horizonte; no describe diferencias locales de tráfico.",
}


def classify_change(values, labels=("Subiendo", "Estable", "Bajando")):
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series("Sin dato", index=numeric.index)
    valid = np.isfinite(numeric)
    result.loc[valid] = labels[1]
    result.loc[valid & numeric.gt(PRODUCT_THRESHOLD_PCT)] = labels[0]
    result.loc[valid & numeric.lt(-PRODUCT_THRESHOLD_PCT)] = labels[2]
    return result


def observed_trend(panel, origins):
    """Exact same-month YoY at each product origin; never skip calendar gaps.

    Both months must be observed/known-zero, finite and available by the first
    day after the origin. Zero previous activity gives an undefined rate.
    Availability dates remain lower bounds, not verified historical vintages.
    """
    keys = origins[["zone_id", "origin_period"]].drop_duplicates().reset_index(drop=True)
    if panel.duplicated(["zone_id", "periodo"]).any():
        raise ValueError("Historia duplicada por zona/mes")
    history = panel.set_index(["zone_id", "periodo"])
    result = keys.copy()
    result["trend_pct"] = np.nan
    result["trend_comparison_period"] = None
    for index, row in keys.iterrows():
        if pd.isna(row.origin_period):
            continue
        origin = pd.Period(row.origin_period, freq="M")
        previous = origin - 12
        result.at[index, "trend_comparison_period"] = str(previous)
        cutoff = (origin + 1).to_timestamp()
        values = []
        for period in (str(origin), str(previous)):
            if (row.zone_id, period) not in history.index:
                break
            observed = history.loc[(row.zone_id, period)]
            available = pd.to_datetime(observed.target_available_no_earlier_than, errors="coerce")
            value = observed.viajes_total
            if (observed.data_status not in ("OBSERVED", "ZERO_DEMAND")
                    or pd.isna(available) or available > cutoff or pd.isna(value)
                    or not np.isfinite(value) or value < 0):
                break
            values.append(float(value))
        if len(values) == 2 and values[1] > 0:
            result.at[index, "trend_pct"] = (values[0] - values[1]) / values[1] * 100
    result["trend_category"] = classify_change(result.trend_pct)
    return result


def scenario_display(frame, scenario_name):
    """Derived display columns on a copy; no writes to the scenario artifact."""
    name = {"Bajo": "low", "Base": "base", "Alto": "high"}[scenario_name]
    result = frame.copy()
    anchor = pd.to_numeric(result.anchor_12m_value, errors="coerce")
    value = pd.to_numeric(result[f"scenario_{name}"], errors="coerce")
    valid = np.isfinite(anchor) & anchor.gt(0) & np.isfinite(value) & value.ge(0)
    result["scenario_change_pct"] = ((value - anchor) / anchor.where(valid)) * 100
    result.loc[~valid, "scenario_change_pct"] = np.nan
    result["scenario_direction"] = classify_change(result.scenario_change_pct, ("AUMENTO", "ESTABLE", "DISMINUCIÓN"))
    result["selected_traffic_adjustment_pct"] = result[f"traffic_{name}_adjustment_pct"]
    return result
