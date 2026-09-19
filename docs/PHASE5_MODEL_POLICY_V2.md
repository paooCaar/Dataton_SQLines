# Fase 5 — selección de modelo y política de forecast V2

## Decisión

La política operativa usa `PERSISTENCE` como modelo `PRIMARY` en 1, 3, 6 y
12 meses. Es la opción con menor MAE y RMSE en `EVALUATION_ALL` de Fase 4,
aplicando parsimonia y conservando el universo completo disponible. Para
un mes, `LGBM_TEMPORAL` queda como `SECONDARY` experimental: en el universo
espacial comparable alcanza MAE 730.05 frente a 761.73 de persistencia
(+4.16%), pero gana solo 8 de 17 cortes. En 3, 6 y 12 meses no se registra
secundario operativo porque el LightGBM temporal pierde frente a persistencia
en el comparable y es inestable en el universo completo.

`LGBM_TEMPORAL_SPATIAL` queda documentado como `EXPLORATORY_ONLY`. No se
promueve a modelo operativo porque el valor marginal espacial no es estable:
en el comparable su mejora de MAE frente al temporal es -0.58%, -13.94%,
-9.02% y -9.64% para 1, 3, 6 y 12 meses, respectivamente.

## Evidencia usada

La selección lee únicamente los artefactos existentes de Fases 2 y 4:
`baseline_metrics_v2.csv`, `lightgbm_compare_metrics_v2.csv`,
`lightgbm_compare_cut_metrics_v2.csv`, `lightgbm_compare_spatial_value_v2.csv`,
`lightgbm_compare_zone_metrics_v2.csv`, `lightgbm_compare_overfitting_v2.csv`,
`rolling_splits_v2.csv` y las predicciones auditadas de Fase 4. No se entrenan
modelos, no se ajustan hiperparámetros y no se agregan features.

Las reglas se fijaron antes de la selección: priorizar MAE, después RMSE,
estabilidad entre cortes y cobertura; usar `directional_accuracy` solo como
métrica secundaria; exigir cortes y observaciones suficientes; y preferir el
modelo simple si el complejo no mejora de forma clara y consistente. El
universo operativo principal es `EVALUATION_ALL`, que no confunde una mejora
obtenida en el subconjunto espacial con una mejora global. El universo
`EVALUATION_SPATIAL_COMPARABLE` se conserva para medir el valor marginal de lo
espacial con exactamente las mismas filas.

## Decisión por horizonte

| Horizonte | Primary | Secondary | MAE primary | RMSE primary | Persistencia | Cortes | Observaciones | Estado |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 mes | PERSISTENCE | LGBM_TEMPORAL (experimental) | 749.55 | 1,332.21 | 749.55 | 18 | 1,093 | VALIDATED_SHORT_TERM |
| 3 meses | PERSISTENCE | ninguno | 1,005.69 | 1,988.63 | 1,005.69 | 18 | 1,099 | VALIDATED_WITH_CAUTION |
| 6 meses | PERSISTENCE | ninguno | 951.64 | 1,938.90 | 951.64 | 17 | 1,091 | VALIDATED_WITH_CAUTION |
| 12 meses | PERSISTENCE | ninguno | 1,674.95 | 4,146.16 | 1,674.95 | 16 | 1,019 | VALIDATED_WITH_CAUTION |

Las cifras de persistencia de esta tabla provienen de `EVALUATION_ALL` de Fase
4, por lo que comparten exactamente el universo disponible de LightGBM. El
CSV de Fase 2 se conserva como referencia independiente; sus cifras abarcan
un universo completo distinto. Para contexto, en el comparable
`LGBM_TEMPORAL` obtiene MAE 976.88,
2,231.92 y 5,942.72 para 3, 6 y 12 meses, frente a 888.36, 866.41 y
1,381.83 de persistencia. Sus mejoras contra persistencia son -9.97%,
-157.61% y -330.06%, con 6/15, 1/14 y 1/13 cortes ganados.

Los otros baselines de Fase 2 tampoco desplazan a persistencia. Sus MAE
(`PERSISTENCE`, `SEASONAL_NAIVE`, `THEIL_SEN`) son, respectivamente, 1,789.74,
4,177.47 y 7,050.12 a 1 mes; 2,567.72, 4,177.47 y 9,465.72 a 3 meses;
2,515.46, 4,133.49 y 13,426.53 a 6 meses; y 4,372.82, 4,372.82 y 24,706.36
a 12 meses. `directional_accuracy` se conserva como métrica secundaria y no
altera esta selección.

El CSV operativo contiene solo `VALIDATED_FORECAST` de 1/3/6/12 meses. El
estado `VALIDATED_WITH_CAUTION` describe respaldo retrospectivo real pero
limitado, no una promesa de precisión futura.

## Política de largo plazo

El histórico mensual no permite validar 36 ni 60 meses. Un año (12 meses) se
mantiene como forecast con cautela porque existen 16 cortes retrospectivos; 36
meses y 60 meses son `SCENARIO_ONLY`, quedan fuera de
`forecast_operational_v2.csv` y no se extrapolan silenciosamente con
LightGBM. Una futura fase deberá definir supuestos explícitos antes de
materializarlos.

## Contrato operativo

`model_policy_v2.csv` tiene una fila única por horizonte y registra el primary,
secondary, estado de validación, rol del forecast, rol espacial, métricas y
razón de selección. `forecast_operational_v2.csv` toma, para cada zona y
horizonte, el último origen disponible en las predicciones ya auditadas de
persistencia. Sus valores son `viajes_total` en unidades
`station_endpoints_per_calendar_month`; no se mezclan con índices legacy ni
con `target_demanda`. Cada fila conserva `origin_period`, `target_period`,
`reference_value`, cambio absoluto y porcentual, modelo usado y
`direction_threshold_version=v2_zero_endpoint_threshold`.

La dirección mantiene la definición V2: comparar el signo del cambio previsto
y observado respecto al valor del origen, con umbral cero. Los ceros son
neutrales y no se convierten en missing; octubre de 2024 conserva su estado
missing en los artefactos fuente.

## Rol de LightGBM y de lo espacial

LightGBM temporal no reemplaza a persistencia. Se conserva como diagnóstico y
como secundario experimental de un mes sobre el subconjunto comparable, donde
la ventaja no gana mayoría de cortes. El modelo temporal más espacial no entra
al forecast principal: sus features espaciales son útiles para visualización,
contexto territorial y diagnóstico, pero no tienen evidencia marginal estable.
No se usan SHAP, cuantiles, intervalos ni incertidumbre.

## Limitaciones y riesgos

- La disponibilidad de algunas zonas y features reduce el universo evaluable;
  las cifras ALL y comparable no deben mezclarse.
- Los cortes son dependientes en el tiempo y no equivalen a muestras
  independientes.
- Las observaciones faltantes y la disponibilidad tardía condicionan qué zonas
  llegan al forecast; no se imputan a cero.
- El horizonte de 12 meses tiene más variabilidad y pocos cortes que 1 mes.
- La selección no demuestra validez para 36/60 meses ni causalidad espacial.
- La salida es un contrato de forecast, no una integración a Streamlit.

## Próximo paso

La Fase 6 puede definir, con aprobación separada, el diseño de escenarios de
largo plazo o la integración de visualización. Antes de ello deben mantenerse
la política, sus hashes y la separación entre forecast validado y escenario.
Esta Fase 5 se detiene aquí.
