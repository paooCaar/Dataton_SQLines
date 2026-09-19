# Fase 6 — incertidumbre y explicabilidad V2

## Decisión de diseño

El modelo operativo sigue siendo `PERSISTENCE`, elegido en Fase 5 por su
estabilidad retrospectiva. Por eso la explicación primaria describe el
mecanismo de persistencia: el forecast mantiene como referencia el nivel más
reciente de actividad. No se presentan importancias de variables ni SHAP para
esta predicción.

La incertidumbre usa `CONFORMAL_SYMMETRIC_ABS_RESIDUAL`: residuos absolutos de
persistencia fuera de muestra, agrupados por horizonte, con el cuantil
con corrección finita: el elemento ordenado `ceil((n+1)*0.80)` de los n
errores absolutos. La banda es
simétrica alrededor del forecast y se trunca a cero cuando el límite inferior
sería negativo. No se supone normalidad.

## Regla temporal de calibración

Para una predicción con origen `o`, solo se usan residuos cuyo
`origin_period < o` y cuyo `target_period < o`. Esta segunda condición es
necesaria para horizontes largos: el error de un corte anterior puede seguir
siendo desconocido si su mes objetivo aún no llegó. Además, la fecha
`max(inicio del mes posterior al target, target_available_no_earlier_than)`
debe ser estrictamente anterior al primer día del mes origen. Es una regla
conservadora respecto de la emisión en el inicio de origen+1. Los datos
reportados tarde o sin fecha quedan fuera del conjunto de calibración.
El mínimo es 30 residuos previos: un piso práctico que deja unos seis puntos
en la cola de 20%, no treinta cortes independientes ni garantía estadística.
Con menos historia se exporta
`INSUFFICIENT_CALIBRATION_HISTORY` y no se inventa ningún intervalo.

La cobertura objetivo es 80%. La cobertura reportada es retrospectiva y se
calcula sobre predicciones históricas de persistencia con la misma regla
rolling; no es una garantía futura por zona.

| Horizonte | Cobertura objetivo | Cobertura observada | Error de cobertura | Ancho medio | Predicciones evaluadas | Fallos de calibración |
|---:|---:|---:|---:|---:|---:|---:|
| 1 mes | 0.800 | 0.758 | -0.042 | 1,878.77 | 931 | 162 |
| 3 meses | 0.800 | 0.771 | -0.029 | 2,545.95 | 808 | 291 |
| 6 meses | 0.800 | 0.843 | +0.043 | 2,728.72 | 645 | 446 |
| 12 meses | 0.800 | 0.830 | +0.030 | 4,116.83 | 200 | 819 |

Los fallos son filas sin 30 residuos conocidos; el CSV también cuenta
orígenes fallidos: 3/5/7/13. Quedan 15/13/10/3 orígenes evaluables. Las
medianas de ancho son 1,974 / 2,408 / 2,692 / 4,562 endpoints.
La cobertura por corte varía entre 40.3–95.2%, 47.9–98.4%, 72.2–89.5% y
76.2–92.3%, respectivamente. La agregación no implica estabilidad por zona.
En el forecast operativo hay 403 filas: 97, 96, 105 y 105 para 1, 3, 6 y 12
meses; 27 filas quedan sin banda (8 a seis meses y 19 a doce). Seis límites
inferiores se truncan a cero y llevan `lower_clipped=true`.

Se eligió el método simétrico antes de esta evaluación por simplicidad, por
contener el forecast y por estimar una sola cola absoluta con poca historia.
Los residuos firmados permitirían asimetría, pero requerirían estimar dos
colas y podrían desplazar ambos límites a un mismo lado del forecast. No se
hizo búsqueda de métodos ni se afirma superioridad empírica sobre esa
alternativa. Los límites se llaman `interval_lower_80`/`interval_upper_80`,
nunca P10/P90.

La fórmula sigue la corrección de rango de
[Conformal Prediction (Berkeley)](https://www.stat.berkeley.edu/~ryantibs/statlearn-s24/lectures/conformal.pdf).
Las zonas y cortes dependientes no satisfacen una intercambiabilidad
demostrada: por ello se informa cobertura observada y no una garantía conformal
del 80%. A un mes hay subcobertura; a doce meses tres cortes son evidencia
muy limitada. Ninguna de estas cifras justifica despliegue automático.

## Explicación frente a contexto

`forecast_explanation` explica el mecanismo: persistencia fue el método más
estable fuera de muestra para el horizonte. Las señales separadas en
`context_signal_1` a `context_signal_3` son descriptivas: crecimiento reciente,
crecimiento trimestral, media y tendencia trimestral, actividad vecinal y
cobertura vecinal cuando están disponibles. Se conservan sus valores y
dirección, pero no entran al forecast operativo.

El contexto se lee del mismo origen/horizonte en
`model_matrix_temporal_spatial_v2.csv` de Fase 4, con observaciones congeladas
según su disponibilidad al emitir. No se leen los labels futuros ni se
recalculan features. La selección fija da una señal de crecimiento, una de
tendencia/media y una vecinal; los missing siguen ausentes. Solo se usa signo
para crecimientos y tendencias. Un nivel positivo no se interpreta como
crecimiento; no se crean etiquetas LOW/MEDIUM/HIGH.

El contexto espacial se marca con `spatial_context_available` y
`context_coverage`. Una señal como “actividad vecinal reciente” significa que
la zona presenta ese patrón en el historial disponible; no significa que el
vecindario cause el forecast. Los snapshots actuales de estaciones, población,
negocios e infraestructura no se exportan como señales predictivas en esta
fase porque no tienen vigencia histórica demostrada. Hay contexto vecinal
disponible en 254 de 403 filas; la cobertura media donde el grafo define
cobertura es 62.0%, sin convertir a cero las zonas sin geometría.

Las limitaciones por fila indican si la geometría o la disponibilidad espacial
son parciales. Esto mantiene separados `FORECAST_MECHANISM` y `CONTEXT`.

Ejemplo: Obrero Popular, origen julio de 2026, destino agosto de 2026,
horizonte un mes. Persistencia conserva 1,657 endpoints; banda [612, 2,702]
con 911 residuos anteriores. El contexto indica crecimiento reciente -8.20%,
tendencia -180 endpoints/mes y crecimiento vecinal +2.91%; ninguna de estas
señales modifica ni causa la predicción de 1,657.

## SHAP

SHAP se difiere. El único candidato permitido habría sido `LGBM_TEMPORAL` de
1 mes como modelo secundario experimental, pero el modelo operativo es
persistencia y la evidencia de Fase 5 no justifica una explicación SHAP en el
producto principal. No se creó ningún output SHAP.

## Outputs

- `forecast_uncertainty_v2.csv`: forecast operativo con banda, método, puntos
  de calibración, clipping y estado.
- `uncertainty_metrics_v2.csv`: cobertura, ancho y fallos por horizonte.
- `uncertainty_backtest_v2.csv`: las 4,302 predicciones OOS con sus bandas,
  cobertura por fila, fechas y tamaños de calibración; permite recalcular las
  métricas y auditar el arranque insuficiente.
- `forecast_explanations_v2.csv`: mecanismo de persistencia y tres señales
  contextuales descriptivas.
- `forecast_product_v2.csv`: unión preparada para una futura app, sin cambiar
  Streamlit.
- Los dos archivos `*.metadata.json` registran política, regla temporal,
  hashes de fuentes, versión de explicación y `shap_enabled=false`.

Todos los valores siguen en `station_endpoints_per_calendar_month`, derivados
de `viajes_total`. No se generan escenarios de 36/60 meses, Monte Carlo,
cuantiles LightGBM, nuevas features ni nuevas fuentes.

El output de Fase 5 conservado es una selección de pronósticos históricos con
orígenes heterogéneos por zona. El producto lo marca como
`artifact_role=RETROSPECTIVE_REPLAY`, conserva origen, destino y unidades, y
no debe mostrarse como una emisión actual común. `forecast_role` y
`validation_status` se heredan sin promover ningún modelo. La futura app debe
mostrar el corte, distinguir banderas de historia insuficiente, presentar
señales junto a sus valores y mostrar las limitaciones. `validation_coverage`
por fila solo usa resultados evaluables conocidos antes de ese origen; puede
ser missing aun cuando existan 30 residuos para la banda. Las métricas
globales retrospectivas se consultan separadamente.

## Riesgos y siguiente fase

La suite `python3 -B -m unittest discover -s tests -v` pasa 99 tests:
99 aprobados, 0 fallos y 0 omitidos, usando Python y dependencias temporales
de las fases anteriores. Hay 22 pruebas específicas de esta fase: residuos
futuros/reportes tardíos, conteos exactos, estadístico de orden, clipping,
cobertura recalculada, contexto congelado, joins y preservación de hashes.
Se corrigió el setup del test de Fase 5 para calcular sus tablas en memoria:
antes ejecutaba el escritor y cambiaba `created_at` de metadata en cada suite.
La metadata versionada de Fase 5 conserva su contenido original.

Reproducción sin entrenar: `python3 -B -m src.models.uncertainty_v2`.
Los CSV son deterministas; solo el timestamp y commit del manifiesto cambian
entre ejecuciones. Se preservan todos los outputs previos y Streamlit.

La calibración es global por horizonte y no específica por zona; la cobertura
puede cambiar con régimen, disponibilidad y composición territorial. Las
bandas anchas a 6/12 meses reflejan esa incertidumbre y no deben interpretarse
como precisión causal. Los timestamps son límites inferiores de disponibilidad:
no hay vintages de publicación/revisión verificados. El filtro evita usar datos
antes de ese límite, pero no prueba reconstrucción histórica perfecta.

La siguiente fase recomendada es una revisión de
producto y supuestos de escenarios de largo plazo, manteniendo separadas la
incertidumbre calibrada, el mecanismo de forecast y el contexto descriptivo.
La integración a Streamlit requiere aprobación posterior.
