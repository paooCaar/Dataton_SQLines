# Fase 7 — integración de producto

## Auditoría previa de la app legacy

`src/app/app.py` consume geometrías (`colonia`, `alcaldia`, geometría),
panel legacy (`colonia`, `time_idx`, `viajes_total`, `indice_demanda_compuesto`),
índice por colonia y validaciones baseline/LGBM (valores reales, predicciones y
errores). Su gráfico proyecta un índice compuesto a 1/3/5 **años**, no endpoints.
El mapa une por nombre de colonia y colorea categorías/score.

`algoritmo_puntuacion.py` consume además proyecciones baseline/LGBM
(`colonia`, `horizonte_anios`, `prediccion_p10/p50/p90`), índice (`alcaldia`,
`km_ciclovia`), población y tipo de zona (densidad comercial y clasificación).
Combina crecimiento, saturación, riesgo y afinidades con los pesos existentes.
Sus nombres, categorías, columnas y horizontes anuales son contratos legacy;
los filtros modifican el score, nunca el forecast V2.

Plan decidido antes de editar Streamlit:

- **KEEP:** app.py, algoritmo_puntuacion.py y todos sus CSV/GeoJSON intactos;
  cálculo original del score con sus filtros de población, zona y riesgo.
- **ADAPT:** patrón de controles, mapa, ranking y detalle a `zone_id`, meses,
  endpoints y joins de alias dentro de la misma alcaldía. No reutilizar el
  gráfico de proyecciones del índice como forecast de actividad.
- **ADD:** app_v2.py independiente, contrato verificable, emisión común,
  vista histórica separada, intervalos, contexto descriptivo y métricas rolling.
- **DEPRECATE_LATER:** unión por nombre solo, mensajes que presentan LightGBM
  como principal y proyecciones anuales de la app legacy. Se mantienen para
  compatibilidad; no se trasladan al forecast V2.

## Política de emisión

El universo operativo es el catálogo V2 completo. Se busca el último mes con
target OBSERVED/ZERO_DEMAND finito para todas sus zonas y disponibilidad mínima
anterior o igual al inicio del mes siguiente. La emisión se registra con su
fecha real de generación: no afirma haber sido publicada históricamente.
La disponibilidad histórica y la finalización de targets siguen sin verificar.

No se recalibran intervalos: para cada horizonte se recupera el radio global
del último corte calibrado de Fase 6 (`upper - forecast`, que no pierde el radio
por clipping inferior). Se aplica ese radio congelado a la nueva persistencia,
recortando el límite inferior a cero. Se registra el origen de calibración;
su cobertura actual no está validada. La cobertura mostrada es la retrospectiva
del procedimiento de Fase 6, no una garantía de esta emisión congelada.
