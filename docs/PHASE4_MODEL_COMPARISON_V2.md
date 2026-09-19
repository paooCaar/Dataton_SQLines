# Fase 4 — comparación temporal frente a temporal + espacial

## Pregunta y decisión

¿Añadir demanda histórica de vecinos Queen mejora el pronóstico puntual frente
al mismo LightGBM con features temporales, bajo las mismas observaciones y cortes?
En la evaluación espacial comparable de esta corrida, **no hay mejora estable**:
MAE empeora en los cuatro horizontes. A un mes el cambio es pequeño y RMSE
mejora marginalmente; a 3, 6 y 12 meses ambos errores empeoran.

Recomendación del feature set: **KEEP_TEMPORAL_ONLY** para esta configuración.
Recomendación general de LightGBM: **DO_NOT_USE_YET** como sustituto de
persistencia. Como diagnóstico secundario acotado, el temporal a un mes en el
subconjunto comparable puede conservarse como **KEEP_AS_SECONDARY_MODEL**:
mejora MAE agregado 4.16%, pero gana solo 8 de 17 cortes y no supera persistencia
en EVALUATION_ALL. No es una recomendación de desplegarlo ni de elegir colonias
post hoc. Las etiquetas metodológicas no se trasladan a Streamlit.

## Disponibilidad y feature sets

Todas las reglas se exportan en `feature_availability_v2.csv`. Solo columnas
permitidas por una allowlist explícita y clasificadas TEMPORAL_SAFE o
SPATIAL_SAFE entran a `select_X`. La matriz conserva identificadores y labels,
pero `zone_id`, colonia, alcaldía, horizonte, target futuro y timestamps no son
predictores. Grado Queen y descriptores estáticos se excluyen para aislar demanda
histórica vecina. La geometría es un grafo fijo, no una covariable nueva.

Se probaron las fórmulas de las 21 features de Fase 2. Antes del primer destino
evaluado, se fijó una regla de cobertura >=60% en pares históricos a un paso con
lag1 y label disponibles hasta el primer origen USED: abril de 2024. Sobre 694
filas iniciales, la regla retuvo 11 features. La cobertura no usa errores de
validación ni datos posteriores para seleccionar columnas. Se usa exactamente
el mismo conjunto temporal en todos los horizontes y ambos modelos:

- lag_1, lag_3;
- rolling_mean_3, rolling_std_3;
- growth_1, growth_3;
- month, year, sin_month, cos_month;
- trend_3.

Los lags/ventanas/growth de 6 y 12 meses quedan fuera por cobertura inicial
insuficiente (aproximadamente 8%–48%). `feature_coverage_v2.csv` conserva cobertura
para todos los candidatos, tanto de calibración como por horizonte de test.
La evaluación no concluye sobre cualquier configuración temporal posible.

El segundo modelo agrega exactamente cinco features:
neighbor_trips_lag1, neighbor_growth_lag1, neighbor_trips_mean_lag3,
neighbor_active_zones y neighbor_observation_coverage. Las variables de
estaciones, densidades actuales, población, DENUE, ciclovías y demás snapshots
permanecen DESCRIPTIVE_ONLY o BLOCKED_HISTORICAL, sin uso predictivo.

### Congelar en el origen, no en el destino

Para origen o y horizonte h, el target es viajes_total(o+h). La emisión se
modela al inicio de o+1, al cerrar o. Las features de demanda usan las fórmulas
de Fase 2 evaluadas en t=o+1: lag1=y(o), lag3=y(o-2), medias/desviaciones/tendencias
terminan en o, y growth_k=(y(o)-y(o-k))/abs(y(o-k)). Los denominadores cero o
faltantes producen NaN. Las features de calendario usan el mes destino o+h,
conocido de antemano. Esto evita usar la actividad de vecinos de o+h-1 para un
pronóstico emitido en o cuando h>1.

Cada valor propio y vecino debe tener mes de evento <=o y
`target_available_no_earlier_than <= inicio(o+1)`. Fechas mínimas nulas se
excluyen en esta fase. Las fórmulas se reconstruyen del panel maestro; no se
consumen directamente las filas espaciales del destino. El mismo guard rige
las features temporales y espaciales. Los vecinos faltantes se excluyen del
numerador y denominador efectivo, conforme a Fase 3.

Las fechas de disponibilidad son límites inferiores, no timestamps verificados
de publicación ni vintages históricos completos. Por ello historical_safe es
condicional a esa información y al grafo fijo, no una certificación point-in-time.
Los tests alteran datos futuros y comprueban que las features del origen no
cambian; también verifican equivalencia con las fórmulas de Fase 2 cuando no
hay datos tardíos.

## Overlaps

Se revisaron 47 pares con las áreas UTM de Fase 3. Las proporciones son
100 × área_solapada / área_de_cada_zona. Regla fijada antes del entrenamiento:

- LIKELY_BOUNDARY_ARTIFACT: área <=1 m² y máximo porcentaje <=0.001%.
- SMALL_OVERLAP: si no entra arriba, área <=1,000 m² y máximo porcentaje <1%.
- MATERIAL_OVERLAP: supera alguno de los límites de pequeño.
- REVIEW_REQUIRED: área/proporciones no finitas, negativas o inconsistentes.

Resultado: 38 posibles artefactos de borde y 9 pequeños; cero materiales y cero
pendientes por medición inválida. El máximo solapamiento es 124.6413 m² y el
mayor porcentaje 0.06232%. Estos umbrales son una clasificación de inspección,
no estándares catastrales ni prueba de equivalencia geométrica. No se modificó
Queen, no se excluyó ninguna geometría ni se repararon polígonos. Persisten los
contactos omitidos por overlaps y los límites numéricos documentados en Fase 3.

## Diseño experimental y universos

Se usan únicamente los 69 cortes USED de `rolling_splits_v2.csv`: 18/18/17/16
para 1/3/6/12 meses. No se inventan cortes ni se reactivan los excluidos. Las
matrices contienen 16,324 pares zona–origen–horizonte con destinos dentro del
calendario. Conservan 106 zonas y labels/features faltantes. Los pares
históricos de entrenamiento no son cortes de evaluación adicionales.

Cada corte entrena dos regresores globales directos al horizonte, sobre las
mismas filas históricas. Un label de entrenamiento debe pertenecer a un mes
<=origen y tener disponibilidad mínima <=emisión. Las features de cada fila
histórica se congelan a su propio origen. Los modelos usan los mismos targets,
orden de filas, hiperparámetros y semillas. Los hashes de llaves de train/test
quedan en `lightgbm_compare_run_audit_v2.csv`.

EVALUATION_ALL incluye las filas con target futuro observado y lag1 disponible
para poder comparar con persistencia=y(origen). LightGBM admite NaN en las
otras features seleccionadas; no se usan ceros de reemplazo ni se retiran filas
al modelo espacial por carecer de geometría. EVALUATION_SPATIAL_COMPARABLE es
un subconjunto estricto donde todas las 11 temporales y 5 espaciales están
presentes. Los tres estimadores se puntúan sobre exactamente esas mismas
filas. Se filtran las mismas predicciones ya generadas, sin reentrenar por scope.

El universo completo evaluable suma 4,302 eventos de pronóstico en 105 zonas;
el comparable suma 2,326 eventos en 73 zonas. Son eventos por horizonte y corte,
no viajes ni observaciones independientes. La zona restante sigue en matrices,
pero no aporta una fila evaluable con persistencia disponible en estos cortes.
Los ceros, octubre de 2024 y estados desconocidos conservan su semántica.

Las filas con missing espacial se cuentan antes del filtro de cada scope.
Tabla por modelo (los conteos son idénticos para los tres):

| evaluation_scope | horizon | n_rows_total | n_rows_usable | n_rows_with_spatial_missing | n_rows_excluded |
| --- | --- | --- | --- | --- | --- |
| EVALUATION_ALL | 1 | 1908 | 1093 | 805 | 815 |
| EVALUATION_ALL | 3 | 1908 | 1099 | 934 | 809 |
| EVALUATION_ALL | 6 | 1802 | 1091 | 873 | 711 |
| EVALUATION_ALL | 12 | 1696 | 1019 | 835 | 677 |
| EVALUATION_SPATIAL_COMPARABLE | 1 | 1908 | 657 | 805 | 1251 |
| EVALUATION_SPATIAL_COMPARABLE | 3 | 1908 | 566 | 934 | 1342 |
| EVALUATION_SPATIAL_COMPARABLE | 6 | 1802 | 571 | 873 | 1231 |
| EVALUATION_SPATIAL_COMPARABLE | 12 | 1696 | 532 | 835 | 1164 |

La cobertura vecinal media es 76.01% en el comparable. En ALL es 65.92% entre
filas cuyo grafo permite definir coverage; no imputa cobertura a las zonas sin
vecinos. El guard reduce especialmente observaciones de zonas de alta actividad.
Por ese cambio de universo no se comparan directamente estos MAE de persistencia
contra los de `baseline_metrics_v2.csv`: se recalcula persistencia sobre las
mismas filas sin cambiar su definición ni sobrescribir ese archivo.

## Configuración y métricas

Dos tipos de modelo, LGBM_TEMPORAL y LGBM_TEMPORAL_SPATIAL: 69 ajustes por tipo,
uno por corte/horizonte. Parámetros iguales: regression, 300 árboles,
learning_rate=0.03, num_leaves=15, min_child_samples=20, colsample_bytree=0.8,
random_state=42, n_jobs=1, deterministic=true, force_col_wise=true. No hay
subsampling de filas (subsample=1 y subsample_freq=0), tuning ni early stopping.
Los destinos no se pasan como eval_set durante entrenamiento. No se recortan
predicciones con una regla escogida después de ver resultados.

Se dejan NaN nativos con use_missing=true y zero_as_missing=false, conforme a
la [documentación de LightGBM 4.6.0](https://lightgbm.readthedocs.io/en/v4.6.0/Parameters.html#zero_as_missing).
Se reusan sin cambios MAE, RMSE, sMAPE, R2 y directional_accuracy de
`src/validation/rolling_validation_v2.py`. sMAPE está en porcentaje;
directional_accuracy es fracción con threshold de cero endpoints. Persistencia
predice cambio neutro; por ello su directional_accuracy es cero cuando ninguno
de los valores futuros coincide exactamente con el origen. Esto no invalida
su ventaja en error absoluto, ni se modifica la definición para favorecerla.

Las métricas agregadas se calculan sobre todas las predicciones del scope, no
promediando métricas de cortes. La media y mediana de mejora porcentual por
corte se reportan por separado. R2 agrupado está influido por diferencias de
escala entre colonias y no prueba precisión temporal dentro de cada zona.

## Métricas agregadas

### EVALUATION_SPATIAL_COMPARABLE — análisis principal

| horizon | model | n_observations | n_cuts | MAE | RMSE | sMAPE | R2 | directional_accuracy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | LGBM_TEMPORAL | 657 | 17 | 730.053 | 1174.476 | 8.075 | 0.985 | 0.664 |
| 3 | LGBM_TEMPORAL | 566 | 15 | 976.883 | 1770.617 | 11.427 | 0.961 | 0.678 |
| 6 | LGBM_TEMPORAL | 571 | 14 | 2231.925 | 5081.851 | 15.631 | 0.858 | 0.559 |
| 12 | LGBM_TEMPORAL | 532 | 13 | 5942.722 | 10268.560 | 38.670 | 0.325 | 0.440 |
| 1 | LGBM_TEMPORAL_SPATIAL | 657 | 17 | 734.284 | 1174.131 | 8.349 | 0.985 | 0.656 |
| 3 | LGBM_TEMPORAL_SPATIAL | 566 | 15 | 1113.078 | 1998.399 | 11.583 | 0.950 | 0.648 |
| 6 | LGBM_TEMPORAL_SPATIAL | 571 | 14 | 2433.286 | 5490.636 | 17.554 | 0.834 | 0.515 |
| 12 | LGBM_TEMPORAL_SPATIAL | 532 | 13 | 6515.618 | 11339.386 | 41.597 | 0.177 | 0.451 |
| 1 | PERSISTENCE | 657 | 17 | 761.729 | 1257.854 | 8.036 | 0.982 | 0.000 |
| 3 | PERSISTENCE | 566 | 15 | 888.357 | 1441.975 | 9.790 | 0.974 | 0.000 |
| 6 | PERSISTENCE | 571 | 14 | 866.410 | 1423.606 | 8.723 | 0.989 | 0.000 |
| 12 | PERSISTENCE | 532 | 13 | 1381.835 | 2688.931 | 11.215 | 0.954 | 0.000 |

### EVALUATION_ALL — contexto de cobertura

| horizon | model | n_observations | n_cuts | MAE | RMSE | sMAPE | R2 | directional_accuracy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | LGBM_TEMPORAL | 1093 | 18 | 843.807 | 1696.048 | 8.452 | 0.979 | 0.647 |
| 3 | LGBM_TEMPORAL | 1099 | 18 | 1842.331 | 3831.290 | 17.512 | 0.894 | 0.660 |
| 6 | LGBM_TEMPORAL | 1091 | 17 | 4261.719 | 13578.606 | 25.111 | 0.587 | 0.502 |
| 12 | LGBM_TEMPORAL | 1019 | 16 | 7156.791 | 14067.479 | 43.245 | 0.443 | 0.379 |
| 1 | LGBM_TEMPORAL_SPATIAL | 1093 | 18 | 834.473 | 1691.375 | 8.531 | 0.979 | 0.630 |
| 3 | LGBM_TEMPORAL_SPATIAL | 1099 | 18 | 1800.974 | 3525.123 | 16.531 | 0.911 | 0.633 |
| 6 | LGBM_TEMPORAL_SPATIAL | 1091 | 17 | 4146.196 | 13507.721 | 25.084 | 0.591 | 0.482 |
| 12 | LGBM_TEMPORAL_SPATIAL | 1019 | 16 | 7844.186 | 14946.696 | 47.252 | 0.371 | 0.380 |
| 1 | PERSISTENCE | 1093 | 18 | 749.551 | 1332.206 | 7.790 | 0.987 | 0.000 |
| 3 | PERSISTENCE | 1099 | 18 | 1005.694 | 1988.630 | 10.058 | 0.972 | 0.000 |
| 6 | PERSISTENCE | 1091 | 17 | 951.636 | 1938.905 | 8.895 | 0.992 | 0.000 |
| 12 | PERSISTENCE | 1019 | 16 | 1674.949 | 4146.165 | 11.779 | 0.952 | 0.000 |

## Valor marginal espacial

Mejora = 100 × (error_temporal − error_espacial) / error_temporal; positivo
significa mejora. Si el denominador es cero la mejora porcentual es NaN.
Ganas/empates/pérdidas usan MAE y tolerancia numérica 1e-8, no un umbral de
relevancia práctica. No se presentan como pruebas de significancia.

| horizon | n_cuts_total | n_cuts_spatial_wins | n_cuts_spatial_ties | n_cuts_spatial_losses | spatial_mae_improvement_pct | spatial_rmse_improvement_pct | mean_spatial_improvement_pct | median_spatial_improvement_pct | spatial_value_label |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 17 | 7 | 0 | 10 | -0.580 | 0.029 | -2.887 | -2.076 | SPATIAL_VALUE_MIXED |
| 3 | 15 | 5 | 0 | 10 | -13.942 | -12.865 | -14.117 | -14.526 | NO_SPATIAL_VALUE |
| 6 | 14 | 2 | 0 | 12 | -9.022 | -8.044 | -14.008 | -9.081 | NO_SPATIAL_VALUE |
| 12 | 13 | 6 | 0 | 7 | -9.640 | -10.428 | -9.800 | -9.104 | NO_SPATIAL_VALUE |

El scope ALL etiqueta internamente valor confirmado a 1 y 3 meses bajo la
regla mecánica de agregados y mayoría de cortes, pero la conclusión principal
no se transfiere desde ALL al comparable. En el comparable no hay ningún
horizonte confirmado: un mes es MIXED por RMSE marginalmente mejor y MAE peor;
los demás son NO_SPATIAL_VALUE para esta especificación.

Para CONFIRMED se exige mejora de MAE y RMSE, mayoría de cortes ganados, al menos
6 cortes y 100 observaciones, y ausencia de los indicadores de inestabilidad
predefinidos. MIXED indica mejoras parciales; NO_SPATIAL_VALUE ausencia de mejora
estable bajo esta configuración. Son etiquetas internas, no causalidad.

## Comparación contra persistencia

La mejora porcentual usa el MAE de persistencia del mismo scope/horizonte como
denominador. Una cifra negativa implica deterioro:

| horizon | model | persistence_improvement_pct | n_cuts_model_beats_persistence | n_cuts_model_loses_to_persistence |
| --- | --- | --- | --- | --- |
| 1 | LGBM_TEMPORAL | 4.158 | 8.000 | 9.000 |
| 3 | LGBM_TEMPORAL | -9.965 | 6.000 | 9.000 |
| 6 | LGBM_TEMPORAL | -157.606 | 1.000 | 13.000 |
| 12 | LGBM_TEMPORAL | -330.060 | 1.000 | 12.000 |
| 1 | LGBM_TEMPORAL_SPATIAL | 3.603 | 8.000 | 9.000 |
| 3 | LGBM_TEMPORAL_SPATIAL | -25.296 | 5.000 | 10.000 |
| 6 | LGBM_TEMPORAL_SPATIAL | -180.847 | 0.000 | 14.000 |
| 12 | LGBM_TEMPORAL_SPATIAL | -371.519 | 1.000 | 12.000 |

En ALL ambos LightGBM pierden frente a persistencia por MAE en todos los
horizontes. La ventaja temporal a un mes del comparable no justifica sustituir
el baseline: es pequeña, restringida a un subconjunto y no gana la mayoría de
cortes. Los horizontes largos empeoran claramente.

## Cobertura vecinal

Los terciles se calculan sin usar errores sobre eventos únicos del comparable:
q1=2/3 y q2=1. LOW <2/3; MEDIUM >=2/3 y <1; HIGH >=1. Los valores empatados se
mantienen juntos, por lo que los grupos no tienen igual tamaño: 731, 578 y
1,017 eventos respectivamente. Estos buckets son descriptivos posteriores;
no se usan para entrenar, seleccionar features ni cambiar hiperparámetros.

MAE por bucket y horizonte:

| horizon | coverage_bucket | model | n_observations | MAE | spatial_improvement_pct |
| --- | --- | --- | --- | --- | --- |
| 1 | HIGH_COVERAGE | LGBM_TEMPORAL | 266 | 543.718 | 0.785 |
| 1 | HIGH_COVERAGE | LGBM_TEMPORAL_SPATIAL | 266 | 539.451 | 0.785 |
| 1 | HIGH_COVERAGE | PERSISTENCE | 266 | 552.620 | 0.785 |
| 1 | LOW_COVERAGE | LGBM_TEMPORAL | 222 | 857.276 | -3.638 |
| 1 | LOW_COVERAGE | LGBM_TEMPORAL_SPATIAL | 222 | 888.466 | -3.638 |
| 1 | LOW_COVERAGE | PERSISTENCE | 222 | 920.667 | -3.638 |
| 1 | MEDIUM_COVERAGE | LGBM_TEMPORAL | 169 | 856.218 | 2.080 |
| 1 | MEDIUM_COVERAGE | LGBM_TEMPORAL_SPATIAL | 169 | 838.411 | 2.080 |
| 1 | MEDIUM_COVERAGE | PERSISTENCE | 169 | 882.077 | 2.080 |
| 3 | HIGH_COVERAGE | LGBM_TEMPORAL | 225 | 740.696 | -13.446 |
| 3 | HIGH_COVERAGE | LGBM_TEMPORAL_SPATIAL | 225 | 840.288 | -13.446 |
| 3 | HIGH_COVERAGE | PERSISTENCE | 225 | 775.662 | -13.446 |
| 3 | LOW_COVERAGE | LGBM_TEMPORAL | 188 | 1233.009 | -18.392 |
| 3 | LOW_COVERAGE | LGBM_TEMPORAL_SPATIAL | 188 | 1459.786 | -18.392 |
| 3 | LOW_COVERAGE | PERSISTENCE | 188 | 1006.596 | -18.392 |
| 3 | MEDIUM_COVERAGE | LGBM_TEMPORAL | 153 | 1009.501 | -7.798 |
| 3 | MEDIUM_COVERAGE | LGBM_TEMPORAL_SPATIAL | 153 | 1088.220 | -7.798 |
| 3 | MEDIUM_COVERAGE | PERSISTENCE | 153 | 908.797 | -7.798 |
| 6 | HIGH_COVERAGE | LGBM_TEMPORAL | 267 | 2477.036 | -5.780 |
| 6 | HIGH_COVERAGE | LGBM_TEMPORAL_SPATIAL | 267 | 2620.208 | -5.780 |
| 6 | HIGH_COVERAGE | PERSISTENCE | 267 | 716.509 | -5.780 |
| 6 | LOW_COVERAGE | LGBM_TEMPORAL | 172 | 2348.845 | -12.838 |
| 6 | LOW_COVERAGE | LGBM_TEMPORAL_SPATIAL | 172 | 2650.390 | -12.838 |
| 6 | LOW_COVERAGE | PERSISTENCE | 172 | 1108.552 | -12.838 |
| 6 | MEDIUM_COVERAGE | LGBM_TEMPORAL | 132 | 1583.781 | -11.903 |
| 6 | MEDIUM_COVERAGE | LGBM_TEMPORAL_SPATIAL | 132 | 1772.301 | -11.903 |
| 6 | MEDIUM_COVERAGE | PERSISTENCE | 132 | 854.098 | -11.903 |
| 12 | HIGH_COVERAGE | LGBM_TEMPORAL | 259 | 6134.642 | -4.222 |
| 12 | HIGH_COVERAGE | LGBM_TEMPORAL_SPATIAL | 259 | 6393.619 | -4.222 |
| 12 | HIGH_COVERAGE | PERSISTENCE | 259 | 1395.529 | -4.222 |
| 12 | LOW_COVERAGE | LGBM_TEMPORAL | 149 | 5532.829 | -30.395 |
| 12 | LOW_COVERAGE | LGBM_TEMPORAL_SPATIAL | 149 | 7214.532 | -30.395 |
| 12 | LOW_COVERAGE | PERSISTENCE | 149 | 1260.839 | -30.395 |
| 12 | MEDIUM_COVERAGE | LGBM_TEMPORAL | 124 | 6034.387 | 1.720 |
| 12 | MEDIUM_COVERAGE | LGBM_TEMPORAL_SPATIAL | 124 | 5930.612 | 1.720 |
| 12 | MEDIUM_COVERAGE | PERSISTENCE | 124 | 1498.621 | 1.720 |

No hay relación monótona estable entre coverage y mejora. A un mes, la mejora
es −3.64%/2.08%/0.78% en LOW/MEDIUM/HIGH; a 3 y 6 meses es negativa en los tres.
A 12 meses MEDIUM mejora 1.72%, pero LOW pierde 30.40% y HIGH pierde 4.22%.
La composición de zonas/cortes difiere entre buckets; no implica causalidad.

## Análisis por zona

`lightgbm_compare_zone_metrics_v2.csv` incluye ambos scopes. El resumen combina
horizontes y cortes con su número de eventos, sin tratarlos como réplicas
independientes. Para mostrar ejemplos se exigen al menos diez predicciones;
las demás zonas permanecen en el CSV. Los nombres son etiquetas de lectura,
no inputs del modelo.

Mayores mejoras frente al modelo temporal en el comparable:

| colonia | n_predictions | mae_persistence | mae_temporal | mae_temporal_spatial | spatial_improvement_pct | mean_neighbor_coverage |
| --- | --- | --- | --- | --- | --- | --- |
| Axotla | 41 | 398.220 | 1235.070 | 617.874 | 49.973 | 1.000 |
| San Angel | 35 | 277.229 | 968.883 | 731.312 | 24.520 | 1.000 |
| San Alvaro | 44 | 250.636 | 921.177 | 716.233 | 22.248 | 0.682 |
| San Mateo | 33 | 445.909 | 1556.779 | 1243.334 | 20.134 | 1.000 |
| Modelo Pensil | 51 | 279.686 | 1081.035 | 884.672 | 18.164 | 1.000 |

Mayores deterioros:

| colonia | n_predictions | mae_persistence | mae_temporal | mae_temporal_spatial | spatial_improvement_pct | mean_neighbor_coverage |
| --- | --- | --- | --- | --- | --- | --- |
| Credito Constructor | 49 | 228.837 | 565.165 | 1188.607 | -110.312 | 0.551 |
| Algarin | 20 | 838.450 | 1638.710 | 3092.416 | -88.710 | 0.700 |
| Nonoalco | 30 | 429.400 | 1083.576 | 1828.734 | -68.768 | 0.583 |
| Del Recreo | 52 | 132.750 | 285.496 | 456.787 | -59.998 | 0.724 |
| Villa Coyoacan | 39 | 648.615 | 1074.158 | 1576.123 | -46.731 | 0.731 |

Incluso donde lo espacial mejora frente al temporal, persistencia puede seguir
siendo mejor; Axotla es un ejemplo. No se hace selección de despliegue por zona
ni se modifica el ranking de la app.

## Overfitting e inestabilidad

Se registra MAE de entrenamiento y validación por scope/modelo/corte. La brecha
usa el train común completo; compararla con un subconjunto de test cambia la
composición y no identifica por sí sola overfitting. Señales predefinidas:
validation/train MAE >3; pérdidas espaciales >25% en >=25% de cortes; o coeficiente
de variación de MAE por corte >1. La fracción de brechas >3 en >=25% de cortes
también activa la marca grave. Son alarmas descriptivas, no tests estadísticos.

La historia entrenable varía de 1,112–2,216 filas a h1, 943–2,040 a h3,
633–1,658 a h6 y solo 117–947 a h12. El arranque de h12 es especialmente débil.
En el comparable, las pérdidas espaciales mayores a 25% aparecen en 5.9%,
33.3%, 35.7% y 30.8% de los cortes para h1/h3/h6/h12. En ALL, h6 tiene MAE muy
variable entre cortes y h12 muestra brechas >3 en 37.5% de los ajustes espaciales.
No se intentó corregir estas señales mediante tuning posterior.

La importancia de LightGBM se exporta como media de gain y número de splits
por feature/modelo/horizonte. En h1 dominan lag1, lag3 y rolling_mean_3.
Importancia por gain puede favorecer ciertas distribuciones y features
correlacionadas; no es explicación causal y no se calculó SHAP.

## Reproducción, tests y archivos

Entorno fijado en `requirements-model-compare-v2.txt`, que incluye el runtime de
Fase 3: LightGBM 4.6.0, scipy 1.16.2, scikit-learn 1.7.2 y dependencias fijadas.
En macOS se necesita libomp; se utilizó el instalado en el equipo. No se
crearon fuentes de datos externas. La metadata registra versiones, hashes de
entradas/implementación/salidas, parámetros y reglas de selección/estabilidad.

```sh
python -m pip install -r requirements-model-compare-v2.txt
python -B -m src.models.lightgbm_compare_v2
python -B -m unittest discover -s tests -v
```

La suite completa tiene 61 tests: los 44 anteriores y 17 de Fase 4. Cubre mismos
splits, targets, parámetros y universos, nesting de features, exclusión de
identificadores/snapshots, NaN preservados, corte de disponibilidad, no leakage
de destino, signo de mejoras, predicciones finitas y determinismo. Dos casos
sintéticos detectaron fechas ISO mezcladas con/sin hora; se corrigió el parser
sin cambiar fórmulas ni hiperparámetros. La repetición completa produjo hashes
idénticos para los 14 CSV. Los timestamps de metadata son propios de cada
corrida y no se espera que sean iguales.

Se protegen 45 archivos previos, incluidos Streamlit y los artefactos de las
fases cerradas. Los 17 hashes legacy de Fase 1 se vuelven a verificar. No se
reescriben baselines, directional_accuracy, Queen, geometrías ni snapshots.

Archivos de código: `src/features/model_matrices_v2.py`,
`src/models/lightgbm_compare_v2.py`, `tests/test_phase4_model_compare_v2.py` y
`requirements-model-compare-v2.txt`. Documentación: este archivo, más notas
aditivas en CONTEXT.md y MIGRATION_V2.md.

Outputs en `data/processed/`:

- model_matrix_temporal_v2.csv y model_matrix_temporal_spatial_v2.csv.
- lightgbm_compare_predictions_v2.csv.
- lightgbm_compare_cut_metrics_v2.csv y lightgbm_compare_metrics_v2.csv.
- lightgbm_compare_zone_metrics_v2.csv.
- lightgbm_compare_feature_importance_v2.csv.
- feature_availability_v2.csv y feature_coverage_v2.csv.
- geospatial_overlaps_review_v2.csv.
- lightgbm_compare_run_audit_v2.csv.
- lightgbm_compare_overfitting_v2.csv.
- lightgbm_compare_spatial_value_v2.csv.
- lightgbm_compare_coverage_metrics_v2.csv.
- lightgbm_compare_v2.metadata.json.

## Limitaciones y siguiente fase recomendada

La conclusión se limita a una configuración fija, un feature set reducido y
cortes dependientes con cobertura no aleatoria. La selección inicial protege
contra tuning sobre validación, pero excluye estacionalidad larga que podría
ser útil con mejor historia. Persisten la geometría parcial, 38 estaciones
conflictivas, catálogo sin vigencia y publicaciones/revisiones no certificadas.
El universo estricto no representa automáticamente las 106 zonas ni todas las
zonas de mayor volumen. Repetir la semilla demuestra reproducibilidad, no
robustez frente a otras semillas ni significancia estadística.

La fase siguiente debería revisar disponibilidades/vintages y representatividad,
y acordar un protocolo para estudiar los horizontes largos y el modelo temporal
secundario a un mes. Mantener persistencia como referencia principal; no avanzar
a explicabilidad o incertidumbre de un modelo aún no respaldado por evidencia
suficiente. Esta corrida no realiza SHAP, cuantiles, Monte Carlo, conformal,
validación espacial nueva ni cambios de aplicación. Se detiene al cerrar Fase 4.
