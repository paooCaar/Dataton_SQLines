# Fase 2: features temporales y validación rolling

Fecha de corrida: 2026-09-18. Rama: `feature/forecast-geoespacial-v2`.

Esta fase usa `data/processed/panel_demanda_v2.csv` y el target
`viajes_total`. No modifica outputs legacy ni Streamlit. Tampoco incluye
features espaciales, LightGBM, SHAP, incertidumbre ni cambios de aplicación.

## Features causales

`src/features/features_temporales_v2.py` genera una fila por `zone_id` y mes
calendario. Incluye lags 1/3/6/12, medias y desviaciones estándar móviles 3/6/12,
growth 1/3/6/12, calendario cíclico, y tendencias lineales 3/6/12.

Las features de target usan exclusivamente observaciones hasta `t-1`; esto es
más estricto que permitir terminar en `t` y evita contaminar el target del mes
que se quiere pronosticar. Las ventanas exigen todos sus meses calendario. Un
mes `MISSING_DATA` o `UNKNOWN_ACTIVITY_STATUS` queda como `NaN` y no se
convierte en cero. Growth se define como
`(y[t-1] - y[t-1-k]) / abs(y[t-1-k])`; denominadores cero o faltantes producen
`NaN`.

Output: `data/processed/features_temporales_v2.csv` y su metadata.

## Cortes expanding-window

La validación pronostica exactamente el mes `origen + horizonte`. Cada corte
usa las mismas 106 zonas para los tres baselines y requiere target completo en
el origen, destino y referencia estacional `destino - 12`. Octubre de 2024 se
excluye porque es `MISSING_DATA`.

- Horizonte 1: 18 cortes, origen enero de 2025–julio de 2026; destino febrero de 2025–agosto de 2026.
- Horizonte 3: 18 cortes, origen noviembre de 2024–mayo de 2026; destino febrero de 2025–agosto de 2026.
- Horizonte 6: 17 cortes, origen agosto de 2024–febrero de 2026; destino febrero de 2025–agosto de 2026.
- Horizonte 12: 16 cortes, origen abril de 2024–agosto de 2025; destino abril de 2025–agosto de 2026.

Los cortes excluidos quedan registrados con la razón en
`data/processed/rolling_splits_v2.csv`. No se imputan meses ausentes.

## Baselines y métricas

`src/validation/rolling_validation_v2.py` compara persistencia, naive
estacional `t-12` y Theil–Sen por zona usando el mismo target, zonas y cortes.
Theil–Sen usa toda la historia válida disponible hasta el origen, con mínimo
de tres observaciones.

Las métricas son MAE, RMSE, sMAPE en porcentaje, R2 y
`directional_accuracy`. Esta última compara el signo del cambio entre el
origen y el destino real contra el cambio predicho; el threshold es exactamente
`0` endpoints, y un cambio neutral solo coincide con otra predicción neutral.

Resultados agregados en `data/processed/baseline_metrics_v2.csv`:

- Horizonte 1: persistencia MAE 1,789.74, naive estacional 4,177.47, Theil–Sen 7,050.12.
- Horizonte 3: persistencia 2,567.72, naive estacional 4,177.47, Theil–Sen 9,465.72.
- Horizonte 6: persistencia 2,515.46, naive estacional 4,133.49, Theil–Sen 13,426.53.
- Horizonte 12: persistencia y naive estacional 4,372.82, Theil–Sen 24,706.36.

En esta muestra, persistencia tiene la menor MAE y RMSE en los cuatro
horizontes. La evidencia es razonable para horizontes 1–6 por contar con 17–18
cortes completos; horizonte 12 tiene solo 16 cortes y debe interpretarse con
mayor cautela. Estas métricas describen actividad observada por endpoints de
estación, no viajes únicos ni demanda latente.

## Limitaciones y cierre

La validación común empieza tarde para que naive estacional tenga referencia
completa. Theil–Sen es un baseline de tendencia por zona, no un modelo de
producción. No hay covariables, validación espacial ni evaluación de publicación
histórica de features. La fase se detiene aquí antes de LightGBM y Fase 3.
