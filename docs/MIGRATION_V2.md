# Migración V2: forecast de actividad ECOBICI y score de oportunidad

Fecha de la primera fase: 2026-09-18. Rama: `feature/forecast-geoespacial-v2`.

Esta migración evoluciona el trabajo existente de Santiago en paralelo. Los
outputs legacy siguen siendo la referencia de la aplicación actual y no fueron
sobrescritos. La Fase 1 solo estabiliza ingesta, calendario, identidad de zonas
y panel maestro; todavía no agrega lags, ventanas móviles, variables vecinas ni
modelos nuevos.

## Qué se conserva, corrige y extiende

| Componente | Estado actual | Acción V2 | Motivo |
|---|---|---|---|
| Lectura ECOBICI | Existente y por chunks | FIX | La ruta legacy estaba vacía y el patrón no reconocía `YYYY_MM.csv`; V2 lee ambas variantes. |
| Agregación de viajes | Correcta para los 25 meses legacy contrastados | KEEP / EXTEND | Mantiene conteos por estación y agrega por fecha real de cada endpoint. |
| Panel colonia × mes | Existente, 25 meses | EXTEND | V2 usa una rejilla continua de 44 meses y conserva estados de disponibilidad. |
| Unidad espacial | Colonia | KEEP | Sigue siendo legible y compatible con GeoJSON y Streamlit. |
| Identidad geográfica | Principalmente nombre de colonia | FIX | Se agrega catálogo `zone_id`; solo se aplica el alias de Del Valle respaldado por evidencia. |
| Crosswalk | Existente | KEEP / AUDIT | Se conserva como evidencia; no se rehace automáticamente ni se fuerzan matches. |
| Población e infraestructura | Intersecciones geoespaciales existentes | KEEP como snapshots | No se usan retrospectivamente como features hasta acreditar vigencia. |
| Índice compuesto | Target del forecast legacy | KEEP como opportunity score | Sigue disponible para priorización; no se interpreta como viajes futuros. |
| Target forecast | `indice_demanda_compuesto` | REPLACE en V2 por `viajes_total` | El forecast debe responder sobre actividad ECOBICI observable. |
| Persistencia | Baseline existente | KEEP | Se evaluará con el mismo target y cortes V2. |
| Theil–Sen | Baseline existente | KEEP | Se reutiliza como referencia de tendencia, pendiente de adaptar al target V2. |
| LightGBM | Candidato que predice el índice | EXTEND después de Fase 1 | No se reentrenó ni se modificó en esta fase. |
| GeoJSON | 84 polígonos | KEEP / FIX pendiente | Se conserva; V2 marca explícitamente las 22 zonas canónicas sin geometría. |
| Streamlit | Aplicación actual | KEEP | No se modificó. |

## Qué se pronostica y qué se prioriza

**Forecast de demanda/actividad.** En V2, `target_demanda` es `viajes_total`,
medido en extremos de viaje por colonia y mes calendario. El target se conserva
como nulo cuando el archivo del mes falta o la actividad previa no puede
distinguirse de una ausencia de observación.

**Opportunity score.** `indice_demanda_compuesto` y el scoring de la aplicación
siguen siendo un producto de priorización. Combina utilización, población,
negocios, infraestructura, accidentes y preferencias del usuario. No debe
presentarse como porcentaje de crecimiento de viajes ni mezclarse
silenciosamente con el forecast.

## Definición de actividad

Para una colonia `z` y mes calendario `t`:

```text
viajes_origen[z,t]  = retiros de estación asignados a z cuyo Fecha_Retiro cae en t
viajes_destino[z,t] = arribos de estación asignados a z cuyo Fecha Arribo cae en t
viajes_total[z,t]   = viajes_origen[z,t] + viajes_destino[z,t]
```

`viajes_total` representa **actividad ECOBICI en forma de endpoints de
estación**, no viajes únicos. Un viaje normal aporta dos unidades: un retiro y
un arribo. V2 conserva ambos lados porque permiten distinguir generación y
atracción de actividad.

El nombre del archivo se usa para particionar y auditar el origen, pero no se
usa para asignar el retiro. Los arribos de los archivos revisados pertenecen al
mes del archivo. Los retiros se asignan por `Fecha_Retiro`; 7,244 cruces de mes
se conservaron en su mes real. 1,500 registros tienen duración mayor a un día y
quedan reportados para revisión posterior, sin descartarse en esta fase.

## Política temporal y de faltantes

El calendario explícito cubre enero de 2023 a agosto de 2026: 44 meses, 43 con
archivo y uno sin archivo.

| Estado | Significado | `target_demanda` |
|---|---|---|
| `OBSERVED` | Archivo disponible y al menos un endpoint asignado | Valor observado |
| `ZERO_DEMAND` | Archivo disponible, zona previamente activa y cero endpoints | Cero real |
| `UNKNOWN_ACTIVITY_STATUS` | Archivo disponible, pero todavía no hay evidencia para saber si la zona estaba activa | Nulo |
| `NOT_YET_ACTIVE` | Solo se asigna con una fecha oficial de activación proporcionada explícitamente | Nulo |
| `MISSING_DATA` | No existe archivo fuente para el mes | Nulo |

En la corrida actual no apareció `ZERO_DEMAND`: las 106 zonas canónicas ya
tenían actividad en todos los archivos disponibles posteriores a su primera
observación. Hay 423 filas `UNKNOWN_ACTIVITY_STATUS` y 106 filas
`MISSING_DATA`. No se infiere `NOT_YET_ACTIVE` desde el primer viaje observado.

Octubre de 2024 está marcado como `MISSING_DATA` para las 106 zonas. No se
rellena con cero aunque puedan existir retiros fechados en octubre dentro de
otros archivos, porque eso no constituye un archivo mensual completo ni
permite reconciliar el universo de viajes.

Agosto de 2026 (`2026_08.csv`) se detecta y se incorpora como `2026-08`.

## Identidad espacial y alias

V2 genera `zone_id` determinísticamente a partir de `(alcaldia, colonia)` y
guarda el nombre legible y la lista de aliases en `catalogo_zonas_v2.csv`.

`Del Valle Centro` y `Del valle Centro` se consolidan en una sola zona porque:

- ambas pertenecen a Benito Juárez;
- las variantes difieren únicamente en mayúsculas/minúsculas;
- tienen conjuntos distintos de IDs de estación, 12 y 3 respectivamente;
- ambas usan la misma clave normalizada `DEL VALLE CENTRO` en el crosswalk DENUE;
- no hay evidencia de que deban fusionarse con Del Valle Norte o Del Valle Sur;
- no se afirmó equivalencia geométrica: ambas variantes carecen de polígono
  IECM en el crosswalk disponible.

La evidencia y los IDs esperados están en
`config/aliases_colonias_v2.json`. Si cambian los IDs, el pipeline falla y
exige revisión manual. No se aplican uniones fuzzy ni consolidaciones por
`lower()` a otras colonias.

El catálogo contiene 106 zonas canónicas, 677 estaciones completas y 84 zonas
con geometría disponible. La diferencia con los 107 nombres y 688 IDs
observados en outputs legacy se debe a la consolidación explícita y a IDs de
viajes sin registro completo en el catálogo.

## Outputs V2

Los archivos de conveniencia se encuentran en `data/processed/` y cada corrida
inmutable se conserva bajo `data/processed/v2_runs/<run_id>/`.

- `panel_demanda_v2.csv`: panel maestro, 4,664 filas, llave única
  `(zone_id, fecha)`, 106 zonas × 44 meses.
- `catalogo_zonas_v2.csv`: catálogo de IDs, aliases, cobertura geométrica y
  estaciones actuales.
- `calendario_ecobici_v2.csv`: 44 meses, archivo y estado de disponibilidad.
- `ecobici_archivos_v2.csv`: manifiesto de 43 archivos, filas, bytes y SHA-256.
- `ecobici_calidad_v2.csv`: conteos de fechas, cruces de mes, IDs sin match y
  endpoints contados.
- `panel_demanda_v2.metadata.json`: versión, commit, hashes, target, corte,
  limitaciones y hashes de los outputs legacy.

Las columnas de población, infraestructura, negocios y accidentes se incluyen
como snapshots de contexto cuando se pueden leer, pero se bloquean como
features históricas V2 en esta fase. Las fechas de referencia disponibles no
demuestran que esos valores estuvieran publicados para cada mes histórico.

## Antes y después

| Métrica | Legacy | V2 |
|---|---:|---:|
| Archivos mensuales representados/detectados | 25 en el panel; la ruta configurada detectaba 0 | 43 detectados y usados |
| Meses en la rejilla | 25 | 44 |
| Colonias/nombres | 107 | 106 zonas canónicas |
| Filas | 2,675 | 4,664 |
| Fecha mínima | 2023-01 | 2023-01 |
| Fecha máxima | 2026-06 | 2026-08 |
| Filas con target faltante | 0, pero los meses ausentes no estaban en la rejilla | 529 |
| Filas con target cero | 393 ceros legacy, sin estado separado | 0 en esta corrida |
| Estaciones | 688 IDs en el agregado legacy | 677 registros completos de catálogo |
| `zone_id` | 0 | 106 |

El aumento de filas proviene de integrar 19 meses adicionales en la rejilla de
44 meses y de representar octubre de 2024 como filas faltantes, no como ceros.

## Tests de Fase 1

`python3 -B -m unittest discover -s tests -v` ejecutó 16 tests: 16 pasaron,
0 fallaron y 0 quedaron omitidos después de instalar Shapely temporalmente para
validar la topología del GeoJSON. Las pruebas cubren descubrimiento de ambos
patrones de nombre, calendario continuo, missing versus zero, suma del target,
IDs, aliases, octubre de 2024, activación explícita, joins, geometrías y
hashes legacy.

## Compatibilidad y riesgos abiertos

No se modificaron `panel_demanda_colonia.csv`, las proyecciones legacy, el
GeoJSON, Streamlit ni los modelos. El pipeline V2 todavía no debe alimentar la
app ni reentrenar modelos.

Riesgos pendientes:

- el catálogo actual no tiene vigencias históricas de estaciones;
- un primer viaje observado no prueba la fecha de activación de una estación;
- los retiros pueden estar reportados en archivos de meses posteriores;
- las fuentes DENUE, población, infraestructura y ATUS no tienen aún una
  reconstrucción histórica compatible con cada fecha del panel;
- la actividad por endpoints tiene una relación dos-a-uno aproximada con los
  viajes, pero puede perder endpoints no asignados o incluir viajes anómalos;
- no hay todavía validación rolling ni validación espacial;
- la semántica del forecast no debe confundirse con el opportunity score.

## Siguiente fase recomendada después de la Fase 2 temporal

La fase posterior debe partir de las features temporales causales sobre
`panel_demanda_v2.csv`: una rejilla calendario explícita, lags y ventanas que
solo utilicen información disponible hasta el origen. Antes de entrenar un
modelo, debe definirse el corte de publicación de cada covariable y una
validación rolling común para persistencia, naive estacional, Theil–Sen y
LightGBM. La implementación temporal de esta fase está documentada en
[`docs/PHASE2_TEMPORAL_V2.md`](PHASE2_TEMPORAL_V2.md); LightGBM sigue fuera de
alcance.

## Fase 3 espacial V2

Se añadió el pipeline Queen y sus auditorías, descritos en
[`PHASE3_SPATIAL_V2.md`](PHASE3_SPATIAL_V2.md), con todas las zonas del panel.
El CSV combinado añade features de vecinos rezagadas sin reemplazar salidas
temporales. Los descriptores de estaciones quedan fuera del conjunto causal
por defecto. La auditoría y los límites de disponibilidad deben revisarse
antes de la evaluación predictiva de Fase 4; no se entrenó LightGBM ni se
modificó el contrato de la aplicación.

## Fase 4: comparación temporal y temporal + espacial

La evaluación puntual de LightGBM se realizó en dos universos idénticos entre
modelos, con features congeladas al origen y snapshots bloqueados. El
comparable estricto no muestra mejora espacial estable; se conserva el
feature set temporal y persistencia como referencia principal. Los resultados,
cobertura, riesgos y recomendaciones están en
[`PHASE4_MODEL_COMPARISON_V2.md`](PHASE4_MODEL_COMPARISON_V2.md). Los artefactos
de fases anteriores permanecen intactos y no se integró el modelo a la app.

## Fase 5: selección de modelo y política de forecast

`docs/PHASE5_MODEL_POLICY_V2.md` documenta la selección por horizonte y sus
reglas de parsimonia. La decisión usa el universo completo de evaluación para
el modelo primario y el universo espacial comparable solo como evidencia
contextual. Persistencia es primaria en 1, 3, 6 y 12 meses. El LightGBM
temporal queda secundario únicamente en 1 mes, mientras que el temporal más
espacial permanece exploratorio. `model_policy_v2.csv` y
`forecast_operational_v2.csv` son contratos reproducibles; no incluyen
escenarios de 36 ni 60 meses. No se entrenaron modelos nuevos, no se añadieron
features y no se modificó la app.

## Fase 6: incertidumbre y explicabilidad

La calibración conformal simétrica está documentada en
[`PHASE6_UNCERTAINTY_EXPLAINABILITY_V2.md`](PHASE6_UNCERTAINTY_EXPLAINABILITY_V2.md).
Usa residuos absolutos de persistencia fuera de muestra, solo cuando el origen
y el target del residuo ya son anteriores al nuevo origen. La banda objetivo es
80%, con mínimo de 30 puntos y estado explícito de historia insuficiente. La
explicación primaria corresponde al mecanismo de persistencia; las señales
temporales y espaciales quedan separadas como contexto descriptivo. SHAP se
difiere y no se modificó Streamlit.

## Fase 7: producto y Streamlit V2

La app nueva se ejecuta con `streamlit run src/app/app_v2.py` y consume el
contrato versionado de `forecast_product_v2.csv`, `current_forecast_product_v2.csv`,
`model_policy_v2.csv`, `uncertainty_metrics_v2.csv`, el catálogo y las
geometrías. La app legacy se mantiene con su ejecución existente. La emisión
actual tiene origen común `2026-08`, 106 zonas y 424 filas; sus bandas usan el
radio calibrado guardado en Fase 6 sin recalibración. El score legacy y el
forecast V2 tienen campos, unidades y controles separados. Las limitaciones
de cobertura, disponibilidad histórica, geometría y causalidad se muestran en
la interfaz y en la documentación de Fase 7.
