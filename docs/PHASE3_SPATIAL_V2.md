# Fase 3 — contexto espacial V2 por colonia

El pipeline mantiene la colonia como unidad y `zone_id` como llave. Conserva las
106 zonas y las 4,664 observaciones de enero de 2023 a agosto de 2026. No cambia
baselines, métricas, Streamlit, los archivos de Fase 1/2 ni outputs legacy.
La utilidad predictiva de las variables espaciales todavía no se ha evaluado.

## Inventario y correspondencias

La auditoría usa exclusivamente las fuentes locales existentes: catálogo V2,
GeoJSON legacy, crosswalk, aliases revisados y catálogo de estaciones. La
correspondencia inicial usa alcaldía y nombre exacto o alias explícito del
catálogo, detecta ambigüedades y pasa inmediatamente a `zone_id`. Nombres
similares no son llaves ni autorizan fusiones.

- 106 identificadores únicos: 84 con geometría y 22 sin ella.
- 84 polígonos simples, 0 multipart, 0 nulos y 0 inválidos según `is_valid`.
- 0 geometrías del GeoJSON ajenas al universo del catálogo/panel.
- 677 estaciones con coordenadas; 312 filas vacías excluidas por el lector de Fase 1.
- 38 estaciones fuera de su polígono de catálogo; otras 108 sin polígono de
  catálogo disponible. Las restantes 531 están dentro. No hay puntos cubiertos
  por múltiples polígonos en esta corrida.

`geospatial_audit_v2.csv` conserva una fila por zona con validez, tipo, CRS,
área, centroides, vecinos, errores, reparación propuesta y notas. Una geometría
inválida se reporta y se excluye de las medidas y el grafo, sin repararla. Si se
necesitara reparar, requiere revisión y un artefacto distinto del GeoJSON
legacy. Esta corrida no necesitó ni generó `zonas_geometria_v2.geojson`.

`zonas_sin_geometria_v2.csv` enumera las 22 zonas con estaciones, actividad
acumulada disponible y candidatos de revisión. Primero recupera los labels
existentes del crosswalk; después puede sugerir hasta tres nombres de la misma
alcaldía con similitud >=0.6. Son candidatos sin verificar, no asignaciones.
Incluye el alias aprobado de Del Valle Centro sin inventar un polígono.
La actividad acumulada excluye meses faltantes y no es una estimación de estos.

`stations_geometry_audit_v2.csv` reporta zona de catálogo, zona cubierta si es
única, distancia al polígono asignado y candidatos. `covers` incluye el borde.
Si no hay polígono que cubra un punto, se lista el polígono disponible más
cercano como candidato de inspección, nunca como reasignación ni como vecino.
La ausencia de polígono asignado no se cuenta como conflicto comprobado.

## CRS, áreas y topología

`source_crs`: OGC:CRS84 explícito en el archivo, WGS84 longitud/latitud.
`analysis_crs`: EPSG:32614, WGS84 / UTM zona 14 norte, metros, como el pipeline
legacy. CDMX se encuentra en esa zona UTM. `export_crs`: EPSG:4326.
No se generan distancias ni áreas en grados. Los centroides x/y, áreas m² y km²,
distancias entre centroides y distancias estación–polígono se calculan en UTM.
Los centroides lon/lat se obtienen reproyectando el centroide UTM para referencia.
No se necesitan buffers ni nuevas fuentes. Cualquier GeoJSON futuro se exportará
en EPSG:4326; el archivo legacy permanece intacto.

La contigüidad exacta se decide sobre la topología de origen con `touches`:
compartir borde o vértice sin solapamiento interior. Esta operación topológica
no mide distancias. No se hace snapping, buffering ni unión por proximidad.
Proyectar primero altera algunos contactos por precisión numérica: la
inspección encontró 131 pares en la representación proyectada frente a 128 en
la fuente. Se eligió conservar reproduciblemente los 128 pares de la fuente.

Hay 47 pares con intersección de área positiva, medida proyectando la
intersección fuente a UTM. Nueve superan 1 m²; el mayor mide 124.6413 m².
Se listan todos en `geospatial_overlaps_v2.csv`; el umbral de 1 m² es solo una
marca de auditoría, no una reparación ni tolerancia para crear vecinos.
Los solapamientos no se convierten automáticamente en relaciones Queen.

## Vecindad, pesos y aislamiento

El grafo contiene 128 pares no dirigidos, exportados como 256 filas dirigidas
simétricas en `zone_neighbors_v2.csv`. No hay duplicados ni self-neighbors.
Queen usa `weight_raw=1` y `weight_normalized=1/n_neighbors_queen` por fila.
Las distancias entre centroides quedan explícitas, pero no afectan los pesos.

Cinco zonas con geometría no tienen vecinos Queen: Centro, Centro Urbano
Presidente Aleman, Irrigacion, Nextitla y Parque San Andres. Mantienen
`n_neighbors_queen=0`. El fallback por distancia se consideró y quedó
**desactivado**: cero zonas con fallback, todas las relaciones son `queen`.
Las 22 zonas sin geometría no se confunden con estas cinco aisladas; su número
de vecinos es desconocido (`NaN`). No se pueden inferir polígonos vecinos
faltantes a partir de la proximidad de sus estaciones.

## Features dinámicas y disponibilidad

Para una fila de tiempo objetivo `t`:

- `neighbor_trips_lag1`: media ponderada de `viajes_total(j,t-1)`.
- `neighbor_growth_lag1`: media ponderada de
  `(y[j,t-1]-y[j,t-2])/abs(y[j,t-2])`, la definición causal `growth_1` de Fase 2.
  Denominador cero o faltante produce `NaN`.
- `neighbor_trips_mean_lag3`: media ponderada de la media de los tres meses
  calendario `t-3`, `t-2`, `t-1` de cada vecino. Exige los tres valores válidos.
- `neighbor_active_zones`: número de vecinos con observación válida en `t-1`,
  incluyendo ceros observados; no es prueba de vigencia oficial de operación.
- `neighbor_observation_coverage`: suma de pesos normalizados de los vecinos
  utilizables para lag1, equivalente a la proporción de vecinos observados.
- `neighbor_growth_coverage` y `neighbor_mean3_coverage`: cobertura específica
  para growth y ventana completa, que puede ser menor que la de lag1.

Se consulta cada mes por `(zone_id, periodo-k)`; una discontinuidad no cambia
`k` ni se interpreta como la fila anterior. Los valores con `MISSING_DATA`,
`UNKNOWN_ACTIVITY_STATUS` o `NOT_YET_ACTIVE` se enmascaran aunque contengan un
número. Solo `OBSERVED` y `ZERO_DEMAND` aportan observaciones.

Además se excluyen valores con `target_available_no_earlier_than` posterior al
inicio de `t`. El guard se aplica a cada valor de cada ventana. Se excluyen así
los endpoints fechados en un mes pero conocidos, como mínimo, después del
corte. La fecha guardada es solo un límite inferior: no certifica el momento de
publicación. Si no existe esa fecha, se conserva la interpretación retrospectiva
por mes de evento; no se afirma reconstrucción histórica de publicaciones.
Este guard es adicional al rezago de Fase 2; no modifica sus archivos.

Se renormaliza por los vecinos con datos válidos para cada feature:
`sum(w*y válidos) / sum(w válidos)`. Si hay grafo pero ningún dato, lag=`NaN`,
coverage=0 y active_zones=0. Sin geometría o sin vecinos no hay denominador:
lag, coverage y active_zones quedan `NaN`. Un cero realmente observado sí cuenta.
Octubre de 2024 continúa faltante y los spatial lags de noviembre son nulos.

La cobertura media de lag1 es **46.9175%**, sobre 3,476 filas
(79 zonas con al menos un vecino × 44 meses), incluyendo meses con cobertura
cero y excluyendo zonas sin denominador. Hay 2,463 filas con algún lag1 válido.
`spatial_features_available` es verdadero solamente para estas filas;
`spatial_geometry_usable` identifica por separado la disponibilidad estructural.
No hay cobertura artificial de 0% para las zonas sin geometría.

## Descriptores de estaciones y conjunto causal

Se preparan cuatro columnas `STATIC_CURRENT_SNAPSHOT`, `historical_safe=false`:

- `n_estaciones_colonia_catalogo`: estaciones asignadas según el catálogo actual.
- `estaciones_por_km2_catalogo`: ese conteo dividido por el área km² de la colonia.
- `neighbor_station_count_catalogo`: suma de estaciones de los vecinos Queen.
- `neighbor_station_density_catalogo`: media Queen de densidades de los vecinos,
  cada una calculada como estaciones / área km². No es suma de densidades ni
  densidad del área unida de los vecinos.

Las estaciones se cuentan según su asignación del catálogo, incluidas las
inconsistencias auditadas; no se presentan esos conteos como conteos punto en
polígono. Las densidades locales sin área fiable y los descriptores vecinos sin
grafo quedan nulos. No se incorporan población, DENUE ni ciclovías actuales;
no se confunde población absoluta con densidad. Cuando se evalúe densidad
poblacional deberá definirse como población / área km² con vigencia documentada.

`causal_spatial_features(frame)` devuelve solo llaves y la allowlist explícita
`CAUSAL`: grado Queen y las cinco features dinámicas mínimas. Excluye siempre
los cuatro snapshots y cualquier columna incidental, incluso si es numérica.
No debe pasarse el CSV combinado entero a un modelo. Los dos indicadores de
coverage adicionales son de diagnóstico y también quedan fuera por defecto.

En la metadata, `historical_safe=true` para las features rezagadas significa
causalidad de sus valores bajo un grafo fijo y el guard descrito. Es condicional:
la vigencia histórica de polígonos/asignaciones y las fechas reales de publicación
no están certificadas. Los snapshots de estaciones quedan inequívocamente en
false y no entran al selector causal.

## Reproducción y archivos

Instalar el entorno opcional con `python -m pip install -r requirements-spatial-v2.txt`.
El pipeline usa Shapely 2.1.2, PyProj 3.7.2, pandas 2.2.3 y numpy 2.3.5.
GeoPandas no es necesario para leer este GeoJSON. En esta sesión se reutilizó
Shapely temporal de Fase 1 y se instaló PyProj con certifi en otro directorio
temporal. No se descargaron fuentes geográficas nuevas.

```sh
python -B -m src.features.features_espaciales_v2
python -B -m unittest discover -s tests -v
```

Outputs bajo `data/processed/`:

- `geospatial_audit_v2.csv` y `geospatial_audit_v2.metadata.json`.
- `geospatial_overlaps_v2.csv`.
- `zone_neighbors_v2.csv`.
- `zonas_sin_geometria_v2.csv`.
- `stations_geometry_audit_v2.csv`.
- `features_espaciales_v2.csv` y `features_espaciales_v2.metadata.json`.
- `features_temporal_spatial_v2.csv`.

Las dos metadata comparten la procedencia de la corrida: hashes de entradas e
implementación, identificador determinista, commit, versiones, reglas y hashes
de salidas CSV. Los timestamps de ejecución pueden cambiar sin cambiar valores.
Antes y después se verifican todos los outputs previos protegidos; los 17 hashes
legacy guardados en Fase 1 también se prueban. El CSV combinado se une
`one_to_one` por `(zone_id, periodo)`, con exactamente las mismas llaves del panel
maestro, sin duplicaciones y sin modificar las features temporales existentes.

## Pruebas y siguiente checkpoint

La suite cuenta con 44 tests: 24 previos y 20 espaciales. Prueba identidades,
Queen borde/vértice, simetría, pesos, CRS, áreas métricas, polígonos nulos e
inválidos, overlaps, ceros/faltantes, ventanas calendario, disponibilidad tardía,
mutaciones de targets actuales y futuros, estaciones conflictivas, conservación
de zonas y rechazo de joins many-to-many. La selección por defecto excluye
snapshots y las salidas conservan hashes legacy.

Los riesgos abiertos son la cobertura geométrica parcial, topología sensible
al redondeo, solapamientos, estaciones fuera del polígono, asignaciones sin
vigencia y publicación histórica no certificada. Para horizonte `h>1`, no debe
usarse directamente la feature de la fila `origen+h`, porque podría contener
vecinos observados después del origen: el pipeline de evaluación deberá
congelar todas las entradas en cada origen común. No se afirma que los altos R2
o resultados de Fase 2 demuestren valor de estas features.

Recomendación para Fase 4: revisar estas discrepancias y acordar el contrato de
disponibilidad/cortes; después comparar temporal frente a temporal+espacial con
las mismas observaciones y baselines. Esa evaluación, la validación espacial y
LightGBM no se ejecutan en Fase 3. No se selecciona modelo final.
