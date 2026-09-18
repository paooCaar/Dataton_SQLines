# CONTEXT.md — Documento maestro del proyecto

> **Propósito de este documento**: es la fuente única de verdad para que cualquier
> integrante del equipo, o cualquier agente de IA que se sume a trabajar en este
> repositorio, entienda el reto, las decisiones ya tomadas, la metodología acordada
> y el estado actual, sin depender de contexto de conversación previo.
>
> **Jerarquía de documentos**:
> - `CONTEXT.md` (este archivo) → qué estamos construyendo y por qué, decisiones y metodología.
> - `PLAN.md` → cronograma día a día, roles y checkpoints.
> - `docs/fuentes_datos.md` → bitácora viva de fuentes de datos (URLs, cobertura, fecha de descarga).
>
> **Regla de mantenimiento**: cualquier persona o agente que tome una decisión que
> cambie algo descrito aquí (unidad de zona, variable objetivo, arquitectura del
> modelo, stack) debe actualizar este archivo en el mismo commit. Si estás retomando
> el proyecto, empieza por leer la sección 12 (Estado actual y próximos pasos).

---

## 1. El reto (resumen)

**Competencia**: Datatón 2026 (ITAM).
**Tema general**: Predicción de demanda urbana en la Ciudad de México.
**Pregunta central**: ¿En qué zonas de la CDMX cambiará la demanda de un servicio en
los próximos años, y qué señales lo anticipan?

Se pide construir una **aplicación / dashboard funcional** que:
- Use datos históricos (≥3 momentos comparables) para detectar tendencias por zona.
- Proyecte un horizonte de **1, 3 o 5 años**, estimando **aumento / estabilidad /
  disminución** de la demanda.
- Incluya una **medida explícita de tendencia**, una **medida de incertidumbre o
  confianza**, y una **validación retrospectiva** (backtesting).
- Explique los factores detrás de cada predicción (no solo un número).
- Reciba como entradas del usuario: horizonte de proyección, población objetivo,
  tipo de zona buscada y nivel de riesgo aceptable.
- Entregue como salida un **ranking de oportunidades de expansión** por zona.
- Integre **al menos 3 fuentes de datos**, con **INEGI obligatorio**, documentando
  sus diferencias temporales y geográficas.
- Incluya **visualización geoespacial** e **interacción en tiempo real**.
- Reconozca sesgos y limitaciones (correlación ≠ causalidad; ausencia de datos ≠
  ausencia de demanda; evitar recomendaciones que refuercen exclusión).

**Público objetivo de la demo** (dato clave de la rúbrica, no del documento del
reto): *"un extranjero que no conoce las características, ventajas o desventajas
de las distintas zonas de la Ciudad de México"*. Esto tiene consecuencias de
diseño concretas — ver sección 8.4.

**Formato de la sesión de evaluación**: 15 minutos por equipo → 10 min presentación
sin interrupciones, 5 min interacción (los jueces hacen al menos una búsqueda en
vivo en la app), calificación individual con rúbrica inmediatamente después.

**Ejes de evaluación** (documento del reto): calidad técnica y de la validación
retrospectiva; calidad/integración/armonización de datos; utilidad e interpretación
de la predicción; experiencia de usuario y visualizaciones; claridad de la
presentación; verificación en vivo a discreción de los jueces.

**Ejes de la rúbrica de la sesión**: (1) calidad técnica y metodológica, (2)
claridad y comunicación, (3) uso y manejo de datos, (4) experiencia de usuario e
interfaz, (5) ejercicio en tiempo real. Además, 4 requisitos técnicos duros:
mapa geoespacial, interfaz amigable, ≥3 fuentes de datos, y **un algoritmo que
calcule una puntuación y categorice las zonas según los datos y la información
del usuario** (esto es un componente aparte del modelo de forecasting — ver
sección 9).

---

## 2. Categoría elegida y justificación

**Categoría**: *Movilidad, transporte e infraestructura ciclista.*

**Por qué**: los datos públicos de INEGI y de Datos Abiertos CDMX sobre movilidad
y ciclismo están relativamente limpios y bien documentados (DENUE con giros de
comercio/reparación de bicicletas, Ecobici con series mensuales largas, ciclovías
con capas geoespaciales oficiales), lo cual reduce el riesgo de limpieza de datos
—el cuello de botella típico de un datatón— y deja más tiempo para el modelo y la
presentación.

**Enfoque de producto (borrador de título)**: *"¿Dónde pedalear el futuro?"* — un
dashboard que identifica colonias de la CDMX donde crecerá la demanda de
infraestructura y servicios de movilidad ciclista (ciclovías, estacionamientos
seguros, talleres/comercios de bicicletas, uso de bici pública) en los próximos
1, 3 o 5 años, explicando por qué y con qué confianza.

> Este es el encuadre recomendado, no una decisión irreversible. Si el Día 1
> (auditoría de datos, ver `PLAN.md`) revela que alguna fuente clave no está
> disponible o es insuficiente, el equipo debe decidir explícitamente el ajuste
> y documentarlo aquí.

---

## 3. Unidad de zona

**Unidad de análisis y visualización recomendada: colonia** (usando el shapefile
oficial de colonias de la CDMX — SEDUVI / IDECDMX / Marco Geoestadístico INEGI).

**Por qué colonia y no AGEB**: una persona que no conoce la CDMX (nuestro público
objetivo en la demo) no puede interpretar una clave de AGEB, pero sí puede ubicar
"Condesa", "Iztapalapa centro" o "Santa Fe" en un mapa con nombres. Los datos
censales a nivel AGEB se agregan hacia colonia (unión espacial por centroide o
por área de traslape) para no perder precisión demográfica.

**Fallback**: si el nivel colonia resulta demasiado ruidoso (series muy cortas o
con demasiados ceros/faltantes por zona), agregar a **alcaldía** como respaldo
robusto. Esta decisión debe tomarse explícitamente el Día 3 y documentarse aquí.

**Alcance geográfico**: se recomienda **acotar el análisis a un subconjunto de
alcaldías** con buena cobertura de Ecobici y actividad ciclista relevante (p. ej.
Cuauhtémoc, Benito Juárez, Miguel Hidalgo, Coyoacán, Álvaro Obregón, Iztapalapa)
en lugar de intentar las 16 alcaldías completas. Menos zonas pero con datos
sólidos > cobertura total con huecos. Confirmar el subconjunto final en el Día 1.

---

## 4. Fuentes de datos

Ver la bitácora viva en [`docs/fuentes_datos.md`](docs/fuentes_datos.md) — ahí se
registran URLs exactas, ediciones descargadas, cobertura temporal/geográfica y
fecha de descarga (obligatorio documentarlo, lo pide el reto explícitamente).

Fuentes candidatas (mínimo 3, INEGI obligatorio):

| # | Fuente | Qué aporta | Rol en el proyecto |
|---|--------|-----------|---------------------|
| 1 | **INEGI — DENUE** (varias ediciones) | Conteo de establecimientos por giro SCIAN (comercio/reparación de bicicletas, mensajería, transporte de pasajeros) por dirección geolocalizada | Señal de demanda económica revelada (aperturas/cierres netos por zona y periodo) |
| 2 | **INEGI — Censos de Población y Vivienda (2010, 2020) + Intercensal 2015** | Población, densidad, estructura de edad, vivienda por AGEB | Covariables demográficas estáticas/lentas; también permite estimar "población objetivo" |
| 3 | **INEGI — Marco Geoestadístico** | Polígonos de AGEB, colonia, alcaldía | Unidad espacial y uniones geográficas |
| 4 | **Datos Abiertos CDMX — Ecobici** (viajes y estaciones) | Serie mensual/diaria de viajes por estación desde ~2010 | Backbone temporal denso para el modelo (compensa la escasez de puntos censales) |
| 5 | **Datos Abiertos CDMX — Ciclovías / infraestructura ciclista** | Km de ciclovía por año y zona | Señal de oferta existente → permite calcular "brecha" oferta-demanda |
| 6 | **Datos Abiertos CDMX / INEGI ATUS — Siniestros viales** | Accidentes con ciclistas por zona/año | Señal de necesidad de infraestructura no atendida (seguridad) |
| 7 (opcional) | **OpenStreetMap** | Red vial, POIs, ciclovías no oficiales | Complemento/validación cruzada de infraestructura |

**Nota importante**: no se pudo verificar en esta sesión la disponibilidad exacta
(años/ediciones vigentes) de cada fuente en este momento — eso es tarea del Día 1
del plan. Cada fuente debe confirmarse contra el portal correspondiente y
registrarse en `docs/fuentes_datos.md` con fecha de verificación.

---

## 5. Definición de "demanda" (variable objetivo)

El reto pide "estimar la evolución de la demanda por zona combinando variables
pertinentes". Se propone un **índice compuesto de demanda de movilidad ciclista**
por zona y periodo, construido como combinación ponderada (z-scores normalizados
por zona y periodo) de:

- **Crecimiento de establecimientos relacionados** (DENUE): aperturas netas de
  comercio/reparación de bicicletas y servicios de mensajería/transporte ligero.
- **Uso de Ecobici**: viajes por habitante (origen+destino) en la zona, y su
  tasa de crecimiento.
- **Crecimiento demográfico**: población y densidad (interpolado entre censos).
- **Brecha de infraestructura**: inverso de km de ciclovía por habitante o por
  área — una zona con alta actividad pero poca infraestructura tiene "demanda
  insatisfecha" alta.
- **Señal de seguridad**: tasa de siniestros con ciclistas (más siniestros con
  uso creciente = necesidad urgente de infraestructura, no solo demanda pasiva).

La fórmula exacta de ponderación (pesos w_i) se define en el Día 3 con base en
la disponibilidad real de datos, y debe documentarse en este archivo (sección a
añadir: "5.1 Fórmula final del índice") en cuanto se congele.

**Medida de tendencia explícita**: pendiente (regresión robusta tipo Theil-Sen o
CAGR) del índice compuesto a través de los ≥3 momentos históricos disponibles,
por zona.

### 5.1 Fórmula implementada (primera versión, 2026-09-15)

**Estado real de las fuentes**: de los 5 componentes listados arriba, hasta
ahora solo está cargado y confirmado el componente **"Uso de Ecobici"**
(`datos_bici/*.csv`, viajes individuales, y `Caracteristicas_estaciones.csv`
para la colonia/alcaldía de cada estación). DENUE, Censo, infraestructura
ciclista y ATUS **no están descargados todavía** en este repo (ver
`docs/fuentes_datos.md`) — los CSV de INEGI presentes en `data/csvs inegi/`
son indicadores económicos nacionales/estatales no relacionados con este
reto. Por eso el índice de esta primera versión es, honestamente, un
**índice de uso de Ecobici por zona**, no el índice compuesto completo. Los
demás componentes se suman como términos adicionales cuando se descarguen
(no cambia la mecánica de zona x periodo, solo agrega columnas al panel).

**Unidad de zona**: colonia (asignada a partir de la colonia de cada
cicloestación en `Caracteristicas_estaciones.csv`; 107 colonias con
actividad, dentro de 6 alcaldías: Cuauhtémoc, Benito Juárez, Miguel
Hidalgo, Coyoacán, Azcapotzalco, Álvaro Obregón — el subconjunto real que
cubre la red de Ecobici, no las 16 alcaldías de la CDMX).

**Panel**: `data/processed/panel_demanda_colonia.csv`, llave (`colonia`,
`periodo` mensual `YYYY-MM`), 107 colonias × 25 periodos (2023-01 a
2026-06, con huecos donde no hubo archivo mensual disponible — la rejilla
se completa con 0 viajes, no se interpola). Columnas: `viajes_origen`
(retiros en la colonia), `viajes_destino` (arribos), `viajes_total` (suma).

**Índice por periodo** (`indice_uso_ecobici`, en `panel_demanda_colonia.csv`):

```
indice_uso_ecobici[zona, periodo] = ( viajes_total[zona, periodo] − media_periodo ) / sigma_periodo
```

z-score calculado **entre zonas dentro del mismo periodo** (no entre
periodos) — mide qué tan por encima/debajo de la colonia promedio está una
zona en un mes dado, evitando que el crecimiento general del sistema (más
usuarios/estaciones con el tiempo) se confunda con demanda relativa.

**Tendencia por zona** (`data/processed/indice_demanda_colonia.csv`):
pendiente de Theil-Sen (`scipy.stats.theilslopes`) de `indice_uso_ecobici`
sobre `time_idx` (mes calendario, respetando huecos), ajustada **solo con
los periodos donde la colonia tuvo viajes** (`viajes_total > 0`) y
calculada solo para colonias con ≥3 de esos periodos. Categorías:
`Creciente` (pendiente > 0.02/mes), `Decreciente` (< −0.02/mes), `Estable`
(en medio), `Datos insuficientes` (< 3 periodos con viajes) — ver sección 9
sobre por qué esta última categoría existe explícitamente.

**Nota metodológica importante**: la rejilla colonia × periodo se completa
con 0 viajes en los meses anteriores a que una colonia tuviera
cicloestaciones activas (la red de Ecobici se fue expandiendo — p. ej.
Narvarte y Portales no tienen estaciones registradas antes de 2023-09).
Ajustar Theil-Sen sobre *todos* los periodos (incluyendo esos ceros
"pre-apertura") sesga la pendiente hacia arriba de forma artificial — se
lee como "demanda creciente" cuando en realidad es "la red llegó a esta
colonia después". Por eso el filtro a periodos activos es obligatorio antes
de ajustar la tendencia (aplica igual al baseline de la sección 6.1).

**Resultado (2026-09-15, corregido)**: 2 colonias `Creciente` (Santa María
la Ribera y Doctores, ambas con estaciones activas desde 2023-01, así que
su tendencia positiva es real y no un artefacto de expansión de red), 105
`Estable`, 0 `Decreciente`. Nivel más alto de uso: Roma Norte, Juárez,
Polanco, Centro, Cuauhtémoc (todas en la alcaldía Cuauhtémoc salvo
Polanco). La mayoría de zonas son "Estable" porque el índice mide
*participación relativa* — el sistema completo crece o decrece junto, pero
pocas zonas cambian su posición relativa mes a mes.

### 5.2 Índice compuesto (actualización, 2026-09-15)

Se descargaron DENUE, Censo 2020 (AGEB/manzana) y la capa de infraestructura
vial ciclista (ver `docs/fuentes_datos.md`), y se integraron al índice.
Implementado en [`src/features/indice_compuesto.py`](src/features/indice_compuesto.py),
que corre **después** de `panel_demanda_ecobici.py`, `armonizar_colonias.py`,
`indicadores_denue.py`, `indicadores_infraestructura.py` e
`indicadores_poblacion.py` (ese es el orden del pipeline).

**Cruce de nombres de colonia** (`armonizar_colonias.py` →
`data/processed/crosswalk_colonias.csv`): ninguna de las tres fuentes nuevas
comparte un identificador con los nombres de colonia de Ecobici, así que el
cruce es por nombre normalizado (sin acentos, mayúsculas). Cobertura sobre
las 107 colonias Ecobici: **93% con DENUE** (99/107 — DENUE ya trae
`nomb_asent`/`ageb` por establecimiento, no hizo falta unión espacial
punto-en-polígono como preveía la sección 6.1.1), **79% con polígono de
colonia** (84/107 — se usó la capa `colonias_iecm` de Datos Abiertos CDMX,
no el Marco Geoestadístico de INEGI, que da AGEB/municipio pero no colonia;
esta capa además subdivide algunas colonias en sub-polígonos con esquemas
de numeración distintos a los de Ecobici — p. ej. "Del Valle Centro/Norte/Sur"
vs. "DEL VALLE I-VII" del catálogo IECM — que no se pudieron cruzar
automáticamente). Las colonias sin match quedan con ese componente en NaN,
imputado a 0 (ni penaliza ni favorece) en vez de forzar una coincidencia
dudosa.

**Componentes y pesos** (primera asignación razonada, no calibrada — no
existe una "demanda real" medible contra la cual ajustar `w_i`, tal como ya
anticipaba la sección 5):

```
indice_demanda_compuesto[zona, periodo] =
    0.6 · z_periodo( viajes_total[zona, periodo] )                          # uso Ecobici
  + 0.2 · z_periodo( aperturas_denue[zona, periodo] )                       # crecimiento DENUE
  + 0.2 · z_estatico( −km_ciclovia[zona] )                                  # brecha de infraestructura
```

- **Uso Ecobici**: igual que 5.1 (z-score entre zonas, por periodo).
- **Aperturas DENUE** (`indicadores_denue.py`): DENUE es un solo snapshot
  (mayo 2026, sin fecha de baja — ver `docs/fuentes_datos.md`), así que no
  se pueden calcular aperturas/cierres netos comparando ediciones. Como
  sustituto se usa `fecha_alta` (fecha de registro de cada establecimiento
  que sigue activo hoy) para reconstruir aperturas brutas por colonia-mes,
  filtradas a giros de bici (reparación, comercio, fabricación — 246
  establecimientos con colonia asignada) y mensajería/paquetería (170).
  Señal **muy dispersa**: solo 17 combinaciones colonia-periodo de 2,675
  tienen aperturas > 0 — se documenta así, no se disimula.
- **Brecha de infraestructura** (`indicadores_infraestructura.py`): km de
  ciclovía por colonia vía intersección espacial real (`geopandas.overlay`,
  prorrateando tramos que cruzan el límite entre colonias) entre los 651
  tramos de la capa de infraestructura y los polígonos de colonia — 247.8
  de los 580.5 km totales del shapefile caen dentro de alguna de las 84
  colonias con polígono (el resto está fuera del subconjunto de 6 alcaldías
  con Ecobici). Es **estático** (un solo snapshot marzo 2025, sin serie
  temporal), así que no aporta tendencia, solo nivel. Se usa el signo
  invertido: menos ciclovía → mayor "brecha"/oportunidad.
- **Población** (`indicadores_poblacion.py`): **no entra al índice**.
  Solo está disponible a nivel alcaldía (ITER 2020, un solo corte) — no
  discrimina entre colonias de la misma alcaldía ni aporta crecimiento, así
  que sumarla solo diluiría la señal sin aportar nada real. Queda como
  columna informativa en el mapa/tabla (`poblacion_alcaldia_2020`). El
  archivo censal correcto a nivel AGEB (`data/raw/censo_ageb_manzana2020/`,
  2,433 AGEB con población) ya está descargado y listo para cuando se
  agregue la unión espacial AGEB→colonia (pendiente: requiere los polígonos
  de AGEB del Marco Geoestadístico, no descargados todavía).
- **ATUS** (siniestros): sigue sin descargarse — 5º componente pendiente.

**Resultado (2026-09-15)**: el ranking por nivel cambia de forma
interpretable respecto al índice solo-Ecobici de 5.1 — Polanco baja del
puesto 3 al 6 (tiene la mayor cantidad de ciclovía, 22.7 km, lo que reduce
su término de "brecha"), San Rafael sube varios puestos (casi no tiene
ciclovía, 0.06 km, así que puntúa alto en brecha pese a un uso Ecobici
solo mediano). Tendencia: 1 colonia `Creciente` (Santa María la Ribera;
Doctores deja de calificar como creciente al mezclar componentes menos
ruidosos con más peso en el nivel), 106 `Estable`, 0 `Decreciente`.

### 5.3 Cierre de los 5 componentes: ATUS + Marco Geoestadístico (2026-09-15)

Se cierran los dos componentes que quedaban pendientes de la sección 5:
**señal de seguridad** (ATUS) y **crecimiento demográfico real por colonia**
(requería el Marco Geoestadístico). Detalle completo de fuentes en
`docs/fuentes_datos.md`; resumen de lo nuevo:

- **ATUS ya estaba en el repo**: los CSV de accidentes de tránsito
  (`atus_anual_*.csv`, 1997-2025, México completo) se subieron completos en
  el commit inicial (`c9bc25b`), pero se interpretaron como "indicadores
  económicos no relacionados" (nota de la sección 5.1 original) y se
  borraron del working tree — un error, porque esta fuente sí es la que pide
  el reto (`TIPACCID`, `CICLMUERTO`, `CICLHERIDO`). `src/data/preparar_atus.py`
  la restaura del historial de git (no hizo falta re-descargarla de INEGI) y
  la filtra a CDMX 2023-2025 (el panel Ecobici llega a 2026-06; ATUS 2026 no
  está publicado todavía). `src/features/indicadores_atus.py` agrega
  accidentes con ciclista (`TIPACCID == "Colisión con ciclista"` o víctimas
  ciclistas > 0 bajo otro tipo) por **alcaldía-mes** (resolución más gruesa
  que colonia, ver 6.1.1) → `data/processed/atus_accidentes_alcaldia_mes.csv`.
  348 accidentes con ciclista en CDMX 2023-2025, concentrados en Cuauhtémoc
  (85) y Benito Juárez (44).
- **Marco Geoestadístico**: se descargó la capa de AGEB urbana edición 2020
  (vía Datos Abiertos CDMX, que redistribuye el Marco Geoestadístico oficial
  de INEGI ya recortado a CDMX) → `data/raw/marco_geoestadistico/`. Con esto,
  `src/features/indicadores_poblacion_colonia.py` hace la unión espacial que
  quedaba pendiente desde 5.2 (centroide de cada uno de los 2,431 AGEB dentro
  del polígono de `colonias_iecm` que lo contiene) y produce población real
  **por colonia** (`poblacion_colonia_2020`, 84/107 colonias con polígono),
  a diferencia de `poblacion_alcaldia.csv` (que se queda solo informativa,
  no discrimina dentro de una alcaldía).

**Pesos actualizados** (`src/features/indice_compuesto.py`, reemplaza la
fórmula de 5.2):

```
indice_demanda_compuesto[zona, periodo] =
    0.50 · z_periodo( viajes_total[zona, periodo] )                       # uso Ecobici
  + 0.15 · z_periodo( aperturas_denue[zona, periodo] )                    # crecimiento DENUE
  + 0.15 · z_estatico( −km_ciclovia[zona] )                               # brecha de infraestructura
  + 0.10 · z_periodo( accidentes_ciclistas[alcaldia(zona), periodo] )     # senal de seguridad (ATUS)
  + 0.10 · z_estatico( poblacion_colonia_2020[zona] )                     # crecimiento demografico (nivel)
```

Ecobici mantiene el mayor peso por ser el único componente con variación
mensual real a nivel colonia; los otros 4 son estáticos (infraestructura,
población) o de resolución más gruesa (alcaldía, ATUS). Pesos no calibrados
contra una "demanda real" (sigue sin existir esa referencia, ver sección 5).

**Resultado (2026-09-15)**: el top-10 por nivel se concentra aún más en
Cuauhtémoc (Roma Norte, Centro, Juárez, Cuauhtémoc, Hipódromo — 5 de las
top-6 — más Polanco en 6º), consistente con que esa alcaldía combina el
mayor uso de Ecobici con la mayor densidad poblacional por colonia y la
mayor siniestralidad ciclista absoluta (más exposición: más ciclistas ⇒ más
accidentes Y más uso). Tendencia: 1 colonia `Creciente` (Santa María la
Ribera), 106 `Estable`, 0 `Decreciente` — sin cambio en la categorización
respecto a 5.2, los dos componentes nuevos pesan sobre el *nivel*, no
cambian la *pendiente* mes a mes de forma apreciable.

**Limitaciones honestas que quedan (documentar en la presentación)**:
- ATUS y población-por-colonia son ambos de resolución/actualización más
  gruesa que Ecobici (alcaldía y corte único 2020 respectivamente) — el
  índice sigue dominado por la dinámica de Ecobici, como es esperable dado
  que es la única fuente con densidad temporal real.
- Los 6 meses de 2026 en el panel (2026-01 a 2026-06) no tienen dato ATUS
  (no publicado aún) — se imputan a 0 accidentes, indistinguible de "cero
  accidentes reales" ese mes (ver `docs/fuentes_datos.md`).
- Las 23 colonias sin polígono en `colonias_iecm` (ver crosswalk, 5.2) no
  reciben ni km de ciclovía ni población por colonia real — ambos términos
  quedan imputados a 0 (neutral) para ellas, así que su índice depende más
  de Ecobici/DENUE que el de las 84 colonias con polígono.

---

## 6. Metodología de modelado

Estrategia en dos capas, para gestionar el riesgo del datatón sin sacrificar la
ambición técnica:

### 6.1 Modelo base (red de seguridad — debe existir siempre, primero)

- **Qué**: regresión de tendencia robusta (Theil-Sen o mínimos cuadrados) del
  índice de demanda por zona sobre los puntos históricos, extrapolada al
  horizonte pedido; o alternativamente **LightGBM/XGBoost con objetivo
  cuantílico** (P10/P50/P90) entrenado en formato panel (todas las zonas
  juntas), usando el horizonte como feature ("direct multi-horizon
  forecasting").
- **Por qué primero**: es rápido de implementar, totalmente explicable
  ("ajustamos una tendencia"), y garantiza que la app tenga un producto
  funcional de principio a fin desde muy temprano en la semana (ver `PLAN.md`,
  Día 4).
- **Incertidumbre**: intervalo de confianza de la pendiente (baseline lineal) o
  cuantiles P10/P90 directos (LightGBM cuantílico).

### 6.1.1 De la estructura cruda a la estructura de panel (paso obligatorio antes de cualquier modelo)

Ninguna fuente candidata viene ya en formato panel (`zona_id` × `periodo`).
Cada una es una tabla con su propia granularidad y llave (ver estructura real
confirmada en `docs/fuentes_datos.md`, apéndice):

| Fuente | Grano actual | Llave actual |
|---|---|---|
| DENUE | 1 fila = 1 establecimiento, snapshot a una fecha de corte | punto (lat/lon) |
| Censo/ITER (2010/2015/2020) | 1 fila = 1 AGEB, por corte censal | AGEB + año censal |
| Marco Geoestadístico | 1 fila = 1 polígono, por edición | AGEB/colonia + edición |
| Infraestructura ciclista | 1 fila = 1 tramo de vialidad, con año de operación como atributo | tramo (línea) |
| Ecobici | 1 fila = 1 viaje (o 1 agregado diario/mensual, según recurso) | estación u origen-destino + timestamp |
| ATUS | 1 fila = 1 accidente | municipio/alcaldía + fecha |

Se requiere una transformación en tres pasos, antes de tocar cualquier modelo
(baseline o TFT):

**Paso 1 — Normalizar la unidad espacial a `zona_id` (colonia)**
- DENUE: unión espacial punto-en-polígono (`geopandas.sjoin`) del lat/lon del
  establecimiento contra el polígono de colonia.
- Censo/ITER: viene a nivel AGEB → unión AGEB→colonia por centroide, o por
  área de traslape ponderada si un AGEB cruza más de una colonia.
- Infraestructura ciclista: intersección de la geometría de línea contra los
  polígonos de colonia; si un tramo cruza varias colonias, prorratear los km
  por la longitud del tramo dentro de cada una.
- Ecobici: si el recurso trae cicloestación, unir la estación (punto) a su
  colonia; si solo viene agregado a nivel ciudad, **no sirve como variable por
  zona** (ver limitación en `docs/fuentes_datos.md`) y se usa solo como
  covariable de contexto general, no diferenciada por zona.
- ATUS: viene a nivel alcaldía → se asigna el mismo valor a todas las colonias
  de esa alcaldía (resolución más gruesa; documentarlo como limitación
  explícita en la presentación, no ocultarlo).

**Paso 2 — Normalizar el eje temporal a un `time_idx` entero consecutivo (mensual)**
- Ecobici define la malla temporal del panel (es la fuente con mayor
  densidad temporal); todas las demás se remuestrean/interpolan a esos meses.
- DENUE: cada edición es una foto → contar establecimientos activos por
  zona en cada snapshot; la diferencia entre snapshots consecutivos da
  aperturas/cierres netos, que se asignan al mes de la edición más reciente
  (o se prorratean en el intervalo si se quiere suavizar).
- Censo (solo 3 puntos: 2010/2015/2020): tratar como covariable que cambia en
  escalón (step function) entre cortes, o interpolar linealmente mes a mes —
  decidir y documentar la elección en la sección 5.1 (pendiente de escribir).
- Infraestructura ciclista: construir una columna acumulada "km de ciclovía
  activos a la fecha t" por zona, sumando por año de entrada en operación.
- ATUS: agregar conteo de accidentes con ciclistas por zona-mes.

**Paso 3 — Ensamblar la tabla panel final**, llave (`zona_id`, `time_idx`),
lista para `pytorch_forecasting.TimeSeriesDataSet` con roles de columna
explícitos: `target` = índice de demanda (sección 5); `static_categoricals` /
`static_reals` = alcaldía, superficie, uso de suelo; `time_varying_known_reals`
= mes/estacionalidad, tendencia demográfica interpolada; `time_varying_unknown_reals`
= índice de demanda histórico, viajes Ecobici del mes, aperturas netas DENUE,
accidentes del mes.

**Requisitos técnicos de `pytorch-forecasting` a tener en cuenta desde el
diseño del panel** (para no descubrirlo tarde):
- Cada `zona_id` necesita una serie **sin huecos** en `time_idx` (rejilla
  regular) — reindexar y rellenar (forward-fill para variables lentas, 0 o
  interpolación para variables de flujo) antes de construir el
  `TimeSeriesDataSet`.
- Se necesitan al menos `encoder_length + prediction_length` periodos por
  zona; si el histórico es corto, usar ventanas de encoder/decoder pequeñas o
  descartar zonas con muy pocos periodos (documentarlas como "datos
  insuficientes", no como "demanda baja" — ver sección 9).
- Normalizar por grupo (`GroupNormalizer` sobre `zona_id`), porque el nivel
  del índice de demanda puede variar en órdenes de magnitud distintos entre,
  por ejemplo, una colonia céntrica y una periférica.

### 6.2 Modelo diferenciador: Temporal Fusion Transformer (TFT)

Esta es la apuesta de arquitectura transformer que el equipo quiere destacar.
Se eligió TFT (y no un transformer genérico tipo GPT/BERT adaptado) porque está
diseñado exactamente para este tipo de problema: forecasting multi-horizonte
sobre muchas series (zonas) con variables estáticas, conocidas a futuro y
observadas, y con salida en cuantiles (incertidumbre nativa) e interpretabilidad
nativa (qué variables pesaron más en cada predicción) — esto último responde
directamente al requisito del reto de "explicar los factores que sustentan la
predicción".

- **Librería recomendada**: [`pytorch-forecasting`](https://pytorch-forecasting.readthedocs.io/)
  (incluye `TemporalFusionTransformer` y `TimeSeriesDataSet`, con utilidades de
  interpretabilidad ya construidas: `interpret_output`, importancia de
  variables estáticas/encoder/decoder). Alternativa más ligera si el setup de
  `pytorch-forecasting` consume demasiado tiempo: `darts.models.TFTModel`
  (API más simple, menos interpretabilidad out-of-the-box).
- **Formato de datos** (`TimeSeriesDataSet`):
  - `group_id`: `zona_id` (colonia).
  - `time_idx`: índice temporal entero (recomendado: mensual, usando Ecobici
    como backbone denso).
  - `target`: índice de demanda (sección 5).
  - Estáticas (por zona): alcaldía, superficie, densidad poblacional base, uso
    de suelo predominante, km de ciclovía en el periodo base.
  - Conocidas a futuro: mes/estacionalidad, tendencia demográfica proyectada
    (interpolación simple entre censos), proyectos de infraestructura
    anunciados (si se documentan).
  - Observadas (desconocidas a futuro): índice de demanda histórico, viajes
    Ecobici del periodo, aperturas netas DENUE del periodo, siniestros del
    periodo.
  - **Pérdida**: `QuantileLoss` → salida directa en P10/P50/P90.

- **Riesgo técnico principal y mitigación**: los datos "censales" (DENUE,
  censos) solo dan 3-5 puntos por zona, lo cual es insuficiente por sí solo
  para entrenar un transformer razonablemente. La mitigación es usar **Ecobici
  como serie temporal densa** (mensual, ~10+ años de historia) como la señal
  observada principal, con las variables censales como covariables más lentas
  (step-function entre ediciones). Esto le da a TFT suficiente longitud de
  secuencia por zona; la riqueza viene de tener cientos de zonas en paralelo
  (panel ancho), no de series individuales largas.
- **Horizontes largos (3-5 años = 36-60 pasos mensuales)**: es normal y
  esperado que la incertidumbre crezca mucho a esos horizontes — repórtalo así,
  es honesto y es justo lo que pide el reto ("comunicar su incertidumbre"). No
  forzar intervalos artificialmente angostos.

- **Checkpoint de decisión (Día 6-7 en `PLAN.md`)**: comparar TFT vs. baseline
  en la validación retrospectiva (sección 7). El modelo que se use **en vivo
  para la demo** es el que gane esa comparación — si TFT no converge a tiempo o
  no supera al baseline, el baseline queda como modelo de producción y TFT se
  presenta igualmente como análisis comparativo/exploratorio (sigue sumando en
  "calidad técnica", con honestidad metodológica). No forzar TFT al demo si no
  es robusto: mejor un baseline confiable en vivo que un transformer que falla
  frente a los jueces.

### 6.3 Validación retrospectiva (obligatoria por el reto)

- **Esquema**: hold-out temporal — entrenar con todos los momentos históricos
  excepto el más reciente, predecir ese último momento conocido, comparar
  contra el valor real observado.
- **Métricas a reportar** (para baseline y para TFT, en la misma tabla):
  - Error de magnitud: MAE / RMSE sobre el índice de demanda.
  - Precisión direccional: accuracy / matriz de confusión sobre la
    clasificación aumento / estable / disminución.
  - Calibración de incertidumbre: cobertura empírica del intervalo P10-P90
    (¿el valor real cae dentro ~80% de las veces?).
- Esta tabla comparativa es, en sí misma, una pieza fuerte de la presentación
  (responde directamente al eje de evaluación "calidad técnica y de la
  validación retrospectiva").

### 6.3.1 Resultado del baseline

Implementado en [`src/models/baseline_tendencia.py`](src/models/baseline_tendencia.py).
Hold-out: último mes con datos por colonia (t) vs. tendencia Theil-Sen
ajustada con todos los meses anteriores (mínimo 4 meses activos para poder
hacer hold-out). Salidas: `data/processed/proyeccion_demanda_colonia.csv`
(forecast P10/P50/P90 a 1/3/5 años desde el último periodo observado) y
`data/processed/validacion_retrospectiva_baseline.csv` (detalle por
colonia del hold-out a 1 mes). `COLUMNA_OBJETIVO` en ese script controla
sobre qué índice corre el baseline — hoy `indice_demanda_compuesto`
(sección 5.2).

**Primera versión (2026-09-15, sobre el índice parcial de 5.1 — solo uso
Ecobici)**:

| Modelo | MAE | RMSE |
|---|---|---|
| Tendencia Theil-Sen | 0.0589 | 0.1037 |
| Naive (persistencia: mes t = mes t-1) | **0.0324** | **0.0550** |

Cobertura P10-P90: 65.4%. Precisión direccional: 30.8% (predice "Estable"
en 85/107 colonias).

**Actualización (2026-09-15, sobre el índice compuesto de 5.2 — Ecobici +
DENUE + infraestructura)**:

| Modelo | MAE | RMSE |
|---|---|---|
| Tendencia Theil-Sen | 0.0366 | 0.0627 |
| Naive (persistencia: mes t = mes t-1) | **0.0194** | **0.0330** |

- Cobertura empírica del intervalo P10-P90: 66.4% (sigue por debajo del
  ~80% esperado).
- Precisión direccional: **49.5%** (mejoró vs. 30.8% del índice solo-Ecobici
  — mezclar un componente estático de baja varianza, como km de ciclovía,
  con peso 0.2 amortigua parte del ruido mes a mes del índice, aunque el
  modelo sigue prediciendo "Estable" en la mayoría de los casos: 53/107 en
  el hold-out).
- MAE y RMSE bajan en ambos modelos (naive y tendencia) respecto a la
  versión solo-Ecobici — mismo efecto de amortiguación por los componentes
  estáticos, no una mejora real de la capacidad predictiva.

**Hallazgo honesto, documentado tal como pide el reto ("comunicar
incertidumbre" y sección 9 de este documento)**: a horizonte de **1 mes**,
la persistencia naive (predecir "igual que el mes pasado") gana al modelo
de tendencia en error de magnitud. Esto es esperable y no invalida el
baseline: el índice mensual por colonia es ruidoso (un solo mes es una
muestra chica de viajes), y Theil-Sen está diseñado para capturar la
pendiente de **largo plazo** (1-5 años, el horizonte real que pide el
reto), no para predecir el mes inmediato siguiente. El hold-out a 1 mes es
la única validación posible con el histórico disponible (~25 meses con
huecos), pero **no es representativo del caso de uso real de la app**
(horizontes de años). Se documenta así en vez de ocultarlo o ajustar el
umbral para que "se vea mejor".

**Implicación para el diseño**: al incorporar LightGBM/TFT (sección 6.1-6.2)
conviene (a) evaluar también con hold-out más largos si el histórico lo
permite, y (b) considerar suavizar el índice mensual (p. ej. promedio móvil
de 3 meses) antes de ajustar la tendencia, para separar mejor señal de
ruido — pendiente de decidir, no implementado todavía.

### 6.3.2 Prueba: LightGBM cuantílico (alternativa al baseline lineal)

Implementado en [`src/models/lightgbm_cuantilico.py`](src/models/lightgbm_cuantilico.py),
siguiendo la opción alternativa de la sección 6.1 ("LightGBM/XGBoost con
objetivo cuantílico entrenado en formato panel, usando el horizonte como
feature"). En vez de una fila por (colonia, periodo), se construyen
**pares** (periodo_origen, periodo_destino) dentro de cada colonia, con
`horizonte_meses = periodo_destino − periodo_origen` como feature
explícito; un único modelo global (tres `LGBMRegressor` con
`objective="quantile"`, alpha 0.1/0.5/0.9) se entrena sobre los pares de
las 107 colonias juntas, usando `colonia` y `alcaldia` como categóricas
más `km_ciclovia`, `poblacion_2020`, `time_idx_origen` y `valor_origen`
como features adicionales.

**Validación retrospectiva** (mismo esquema hold-out de 1 mes que 6.3.1,
para comparación directa — modelo global entrenado excluyendo, por cada
colonia, los pares cuyo destino es su propio último periodo observado):

| Modelo | MAE | RMSE | Cobertura P10-P90 | Precisión direccional |
|---|---|---|---|---|
| LightGBM cuantílico | **0.0181** | **0.0314** | **81.3%** | **76.6%** |
| Tendencia Theil-Sen (6.3.1) | 0.0366 | 0.0627 | 66.4% | 49.5% |
| Naive (persistencia) | 0.0194 | 0.0330 | — | — |

A diferencia del baseline Theil-Sen, LightGBM **sí supera a la
persistencia naive** incluso en el hold-out de 1 mes (0.0181 vs. 0.0194
MAE), y su cobertura empírica del intervalo P10-P90 (81.3%) queda muy
cerca del ~80% teórico — evidencia de que el objetivo cuantílico está bien
calibrado en este panel, no solo de que el punto central mejora. La
precisión direccional también sube sustancialmente (76.6% vs. 49.5%),
aunque la matriz de confusión muestra que la mayoría de los aciertos son
en la clase "Estable" (75/107), que además es mayoritaria en los datos —
la ganancia real en las clases minoritarias ("Creciente"/"Decreciente") es
modesta (7/8 aciertos combinados) y debe leerse con cautela dado el tamaño
de muestra.

**Limitación honesta (extrapolación fuera de rango)**: el horizonte máximo
observado en los pares de entrenamiento es de 41 meses (~3.4 años, dado
que el panel cubre 2023-01 a 2026-06 con huecos). Un modelo basado en
árboles no puede extrapolar más allá del rango de la feature vista en
entrenamiento — la predicción para horizonte=60 meses (5 años) queda
prácticamente saturada al mismo valor que para horizonte=36 meses (3
años), como muestra `proyeccion_demanda_colonia_lgbm.csv` (p. ej. Acacias:
p50 a 3 años = −0.1647, a 5 años = −0.1666 — casi idéntico). Esto es
distinto del baseline Theil-Sen, que sí extrapola linealmente sin límite
(con el riesgo opuesto: una tendencia lineal indefinida tampoco es
realista a 5 años). Ninguna de las dos limitaciones se resuelve sin más
historia — se documenta para la presentación en vez de ocultarla.

**Estado**: resultado de una prueba puntual (no reemplaza aún al baseline
en producción — ver principio de la sección 6.1 de mantener el baseline
como red de seguridad). Dado que supera claramente al Theil-Sen en las
tres métricas del hold-out de 1 mes, es candidato fuerte a moverse a
`src/models/` como segundo modelo de la validación retrospectiva
comparativa (junto a TFT, sección 6.2) cuando el equipo decida el modelo
de producción — pendiente de discusión de equipo, no decidido aquí
unilateralmente.

### 6.3.3 Actualización tras cerrar los 5 componentes (ATUS + Marco Geoestadístico, 2026-09-15)

Ambos modelos (6.3.1, 6.3.2) se re-corrieron sobre el índice de 5 componentes
de la sección 5.3 (mismo hold-out de 1 mes, sin cambios de código en los
modelos — solo cambió el `indice_demanda_compuesto` de entrada):

| Modelo | MAE | RMSE | Cobertura P10-P90 | Precisión direccional |
|---|---|---|---|---|
| LightGBM cuantílico | **0.0175** | **0.0266** | 82.2% | **82.2%** |
| Tendencia Theil-Sen | 0.0545 | 0.0830 | 96.3% | 20.6% |
| Naive (persistencia) | 0.0162 | 0.0275 | — | — |

- **LightGBM mejora ligeramente** en las tres métricas frente a 6.3.2 (MAE
  0.0175 vs. 0.0181, cobertura 82.2% vs. 81.3%, dirección 82.2% vs. 76.6%) —
  consistente con que sus features estáticos (`km_ciclovia`, `poblacion_2020`)
  ya capturaban algo de la señal que ahora los 2 componentes nuevos hacen
  explícita en el índice objetivo mismo.
- **Theil-Sen empeora fuertemente en precisión direccional** (20.6% vs. 49.5%
  en 5.2) aunque su cobertura P10-P90 sube a 96.3% (antes 66.4%, ahora por
  ENCIMA del ~80% esperado — indica intervalos demasiado anchos, no una
  calibración mejor). Causa más probable: `accidentes_ciclistas` y
  `poblacion_colonia_2020` son señales de **alcaldía/nivel estático** que se
  mueven poco mes a mes salvo por el ruido de conteos pequeños (348
  accidentes repartidos en 6 alcaldías × ~25 meses), así que agregan
  varianza mes a mes sin aportar tendencia real — Theil-Sen, al ajustar
  sobre esa serie más ruidosa, produce pendientes menos informativas que
  con el índice de 3 componentes de 5.2. LightGBM, al tratar `alcaldia`
  como categórica separada en vez de mezclarla dentro de un único índice
  escalar por periodo, es más robusto a este tipo de ruido.
- **Implicación honesta para la presentación**: el baseline lineal (Theil-Sen)
  sigue siendo el modelo más simple/explicable, pero esta actualización es
  evidencia adicional (ver 6.3.2) de que LightGBM es el candidato más sólido
  para producción si el equipo decide no llegar a tiempo con TFT (sección
  6.2) — no se ocultó el resultado desfavorable a Theil-Sen porque
  contradice la narrativa de "más datos = mejor modelo lineal", que es
  justo el tipo de hallazgo que el reto pide comunicar con honestidad
  (sección 9).

---

## 7. Algoritmo de puntuación y categorización (requisito duro de la rúbrica)

Distinto del modelo de forecasting: es la capa que combina la predicción del
modelo con las **entradas del usuario** para producir el ranking final. Esto es
un requisito técnico explícito de la rúbrica de sesión (#4: "algoritmo que
calcule una puntuación y categorice las zonas según datos e información del
usuario").

Entradas del usuario (definidas por el reto):
- **Horizonte de proyección**: 1 / 3 / 5 años → selecciona qué predicción del
  modelo usar.
- **Población objetivo**: p. ej. general, jóvenes/estudiantes, adultos mayores,
  trabajadores → pondera qué variables demográficas de la zona importan más.
- **Tipo de zona buscada**: p. ej. residencial, mixta, comercial, o filtro por
  alcaldía/densidad.
- **Nivel de riesgo aceptable**: bajo / medio / alto → controla cuánto se
  penaliza la incertidumbre del pronóstico.

Score propuesto por zona `z` y horizonte `h` (pseudofórmula, pesos a calibrar):

```
crecimiento_norm   = normalizar( predicción_demanda[z, h] − nivel_actual[z] )
saturación_penal   = normalizar( oferta_actual[z] )                      # ya hay mucha oferta => penaliza
riesgo_penal       = f( ancho_intervalo_incertidumbre[z, h], riesgo_aceptable_usuario )
afinidad_poblacion = similitud( perfil_demográfico[z], población_objetivo_usuario )
afinidad_zona      = coincide( tipo_de_zona[z], tipo_zona_usuario )

score[z, h] = w1*crecimiento_norm − w2*saturación_penal − w3*riesgo_penal
            + w4*afinidad_poblacion + w5*afinidad_zona
```

**Categorías de salida** (por cortes de percentil o umbrales fijos, a definir
con datos reales): `Oportunidad alta`, `Oportunidad moderada`, `Vigilar`, `No
recomendada (saturada o alto riesgo)`, y una categoría separada obligatoria:
**`Datos insuficientes`** para zonas con demasiados faltantes — nunca mostrar
esas zonas como "baja demanda", porque el reto exige explícitamente no confundir
ausencia de datos con ausencia de demanda (sección 8 de consideraciones éticas).

### 7.1 Implementación (2026-09-16)

Implementado en [`src/app/algoritmo_puntuacion.py`](src/app/algoritmo_puntuacion.py)
vía `calcular_scoring(horizonte_anios, poblacion_objetivo, tipo_zona_usuario,
riesgo_aceptable)`. No corre inferencia de ningún modelo — solo lee las
proyecciones ya precalculadas (LightGBM como modelo primario por 6.3.3, con
fallback a Theil-Sen por colonia/horizonte) y hace aritmética ligera sobre
~107 filas, así que puede llamarse en vivo desde la app (cumple 8.1).

Decisiones tomadas al pasar de la pseudofórmula a código (documentadas con
más detalle en el docstring del módulo):

- `normalizar(...)` = min-max a [0, 1] entre las zonas válidas del horizonte
  pedido, para que los 5 términos sean comparables entre sí antes de aplicar
  los pesos.
- `oferta_actual[z]` (para `saturación_penal`) = km de ciclovía existente por
  colonia (proxy de infraestructura/madurez instalada — no existe todavía un
  conteo de estaciones Ecobici por colonia procesado, ver
  `datos_bici/Caracteristicas_estaciones.csv`, sin integrar).
- `tipo_de_zona[z]` (para `afinidad_zona`) es un dato nuevo: no existía
  ningún catálogo de tipo de zona por colonia, así que se derivó en
  [`src/features/indicadores_tipo_zona.py`](src/features/indicadores_tipo_zona.py)
  a partir de densidad de establecimientos DENUE (todas las actividades,
  no solo bici/mensajería) por cada mil habitantes, con terciles →
  `Residencial` / `Mixta` / `Comercial` (o `Sin clasificar` si falta DENUE o
  población). Guardado en `data/processed/tipo_zona_colonia.csv`.
- `afinidad_poblacion` es la limitación más honesta de esta sección: **no
  hay datos demográficos por edad a nivel colonia** (el Censo solo se
  integró como población total, sección 5.3). En vez de fingir una
  segmentación por edad que los datos no soportan, `poblacion_objetivo` se
  traduce en una heurística documentada sobre dos señales reales
  (densidad poblacional y densidad comercial DENUE): "trabajadores" favorece
  zonas de alta actividad comercial, "adultos_mayores" favorece zonas
  pobladas pero menos comerciales, "jóvenes/estudiantes" favorece ambas,
  "general" no pondera ninguna. Pendiente de mejorar si se consigue
  desagregación por edad del Censo.
- Categorización: guardarropa explícito primero (`saturación_penal` o
  `riesgo_penal` en el quintil superior → `No recomendada`, fiel al nombre
  de la categoría), después cortes por percentil (80/50/20) del score sobre
  las zonas restantes. `Datos insuficientes` se activa únicamente si ningún
  modelo tiene predicción para esa colonia/horizonte — nunca por falta de
  `km_ciclovia`/población/tipo de zona, que se imputan a un valor neutral
  (el promedio observado, no un punto arbitrario de una escala sesgada) y se
  marcan con la bandera `datos_zona_incompletos` para que la app pueda
  mostrar la advertencia correspondiente (sección 8.3).

Pendiente: pesos (`PESOS`, `RIESGO_MULTIPLICADOR`,
`PERFIL_POBLACION_OBJETIVO`) son razonados, no calibrados contra feedback de
negocio — mismo estado que los pesos del índice compuesto (sección 5.3).

---

## 8. Especificación de la aplicación

### 8.1 Principio de diseño no negociable
Las predicciones se **precalculan en batch** (todas las zonas × los 3 horizontes)
antes de la demo. La app en vivo **solo filtra, rankea y visualiza** sobre esa
tabla ya calculada — nunca corre inferencia pesada del modelo en tiempo real.
Esto es lo que permite cumplir "interacción en tiempo real" sin ningún riesgo de
que el modelo tarde o falle frente a los jueces.

### 8.2 Contrato de datos entre modelado y app
Archivo de interfaz único (para que el equipo de app pueda empezar con datos
dummy sin esperar al modelo real):

- `data/processed/zonas_predicciones.parquet` — una fila por
  `(zona_id, horizonte, cuantil)` con columnas: nivel actual, predicción,
  dirección, factores principales (top-3 variables), fuente del modelo usado
  (baseline/TFT).
- `data/processed/zonas_geometria.geojson` — polígonos de zonas con nombre
  legible (colonia, alcaldía).
- `data/processed/zonas_historico.parquet` — serie histórica del índice por
  zona, para graficar tendencias.

### 8.3 Inputs / outputs de la interfaz
- **Inputs**: horizonte (1/3/5 años), población objetivo, tipo de zona, nivel
  de riesgo — los mismos 4 que pide el reto.
- **Outputs**:
  - Mapa geoespacial (coroplético por categoría/score, con toggle a "cambio
    esperado" puro).
  - Panel de ranking: top-N zonas con score, categoría y mini-gráfica de
    tendencia histórica + banda de incertidumbre futura.
  - Al seleccionar una zona: panel "por qué" con los factores principales,
    fuentes usadas, nivel de confianza y advertencias de limitación si aplica.

### 8.4 Consecuencia de diseño del público objetivo ("un extranjero...")
Todo texto de la interfaz debe evitar claves y jerga local (AGEB, SCIAN,
siglas de alcaldías) y usar nombres reconocibles + una línea de contexto por
zona (p. ej. "Colonia Condesa, Alcaldía Cuauhtémoc — zona residencial-mixta
cerca del centro"). Evitar dar por sentado conocimiento de la geografía o
cultura de la CDMX en cualquier texto, tooltip o narrativa de la presentación.

### 8.5 Stack sugerido (decisión a confirmar Día 1 según habilidades del equipo)
- **Datos/modelado**: Python — `pandas`, `geopandas`, `scikit-learn`,
  `lightgbm`, `pytorch` + `pytorch-forecasting` (o `darts` como alternativa).
- **App — opción rápida (recomendada por defecto)**: `Streamlit` +
  `pydeck`/`folium` para el mapa. Menor riesgo de tiempo, todo en Python (el
  equipo de modelado puede ayudar directamente).
- **App — opción alterna (si hay fuerza en frontend)**: Next.js + `deck.gl` o
  Mapbox GL para una interfaz más pulida. Solo tomar esta ruta si alguien del
  equipo ya tiene experiencia previa — no es momento de aprender un framework
  nuevo bajo presión de tiempo.
- **Despliegue**: Streamlit Community Cloud (o equivalente) **más un respaldo
  local** corriendo en la laptop del equipo, por si falla el internet del
  recinto durante la demo.

### 8.6 Implementación (2026-09-17)

Implementado en [`src/app/app.py`](src/app/app.py) (`streamlit run
src/app/app.py`), sobre `calcular_scoring(...)` de `algoritmo_puntuacion.py`
(sección 7.1) — respeta el principio 8.1: la app no entrena ni corre
inferencia, solo lee CSV/GeoJSON precalculados.

- **Mapa** (`px.choropleth_map`, MapLibre vía `plotly`, sin necesitar token
  de Mapbox): coroplético por `categoria` o por `score` continuo (toggle),
  sobre los polígonos de `data/processed/zonas_geometria.geojson` (nuevo,
  ver `src/features/geometria_colonias.py` más abajo). Encuadrado por
  `fig.update_maps(bounds=...)` calculado desde el propio geojson, no un
  centro/zoom fijo — necesario porque las 6 alcaldías en alcance (sección 3)
  no están centradas en el "centro turístico" de la CDMX.
- **Ranking**: tabla ordenada por score con categoría, tipo de zona y modelo
  usado (LightGBM o Theil-Sen de respaldo, ver `_proyeccion_por_horizonte`
  en `algoritmo_puntuacion.py`).
- **Panel "por qué"**: al elegir una colonia — línea de contexto en lenguaje
  llano (sección 8.4), gráfica de histórico + proyección a 1/3/5 años con
  banda P10-P90 (la incertidumbre crece con el horizonte, visible en la
  misma gráfica), desglose de los 5 factores del score ya ponderados, y
  advertencias explícitas si la categoría es "Datos insuficientes" o si a la
  colonia le falta algún dato estático (nunca se confunden entre sí,
  sección 9).
- **Requisito de ≥3 fuentes**: expander con las 5 fuentes del índice
  compuesto (sección 5.3) y su cobertura temporal/geográfica.
- **Validación retrospectiva visible en la interfaz**: expander que
  recalcula en vivo (no hardcodeado) MAE/RMSE/cobertura P10-P90/precisión
  direccional de LightGBM vs. Theil-Sen vs. naive desde los CSV de hold-out
  (`data/processed/validacion_retrospectiva_*.csv`) — mismos números de la
  sección 6.3.3.
- **Ética/limitaciones**: expander con los puntos de la sección 9 más
  limitaciones específicas de la app (colonias sin polígono, resolución de
  ATUS/población).
- **Desviación del contrato 8.2**: no se crearon
  `zonas_predicciones.parquet` ni `zonas_historico.parquet` — la app importa
  `calcular_scoring` y lee `panel_demanda_colonia.csv`/
  `indice_demanda_colonia.csv` directamente, que ya cumplen el mismo rol sin
  una capa de archivo intermedia adicional que mantener sincronizada.
  `zonas_geometria.geojson` sí se materializó tal cual el contrato.
- **Geometría por colonia** (nuevo,
  [`src/features/geometria_colonias.py`](src/features/geometria_colonias.py)):
  disuelve los polígonos de `colonias_iecm.shp` por colonia Ecobici usando
  `crosswalk_colonias.csv`, reproyectados a EPSG:4326. Cobertura: 84/107
  colonias (las mismas 23 sin match de la sección 5.2) — las colonias sin
  polígono no aparecen en el mapa pero sí en el ranking (advertencia
  explícita en la app, no se ocultan). Al construirlo se encontró y corrigió
  un bug real en el cruce de nombres (ver sección 12): el cruce no acotaba
  por alcaldía, así que nombres de colonia duplicados en alcaldías distintas
  del shapefile (p. ej. "Buenavista" en Cuauhtémoc y en Iztapalapa) se
  fusionaban en un polígono que saltaba de un extremo de la ciudad al otro.

---

## 9. Consideraciones éticas (explícitas en el reto — deben aparecer en la presentación)

- Las proyecciones son estimaciones condicionadas a los datos y escenarios, no
  certezas — comunicar siempre con el intervalo de incertidumbre visible, nunca
  solo un número puntual.
- Correlación histórica no implica causalidad — al explicar "factores", usar
  lenguaje de asociación, no de causa ("la zona muestra crecimiento asociado
  a...", no "el crecimiento de X causa Y").
- Ausencia de datos ≠ ausencia de demanda — zonas con poca cobertura de datos
  deben marcarse como `Datos insuficientes`, nunca como demanda baja.
- Evitar que el ranking refuerce exclusión: revisar que zonas de menor ingreso
  no queden sistemáticamente en el fondo del ranking solo por tener menos datos
  o menor oferta comercial histórica — documentar explícitamente esta revisión
  como parte del análisis de sesgos en la presentación.

---

## 10. Estructura del repositorio

```
Dataton_SQLines/
├── README.md                 # punto de entrada, enlaza a este archivo
├── CONTEXT.md                # este documento (fuente de verdad)
├── PLAN.md                   # cronograma, roles, checkpoints
├── docs/
│   └── fuentes_datos.md      # bitácora viva de fuentes
├── data/
│   ├── raw/                  # datos descargados sin modificar (no versionar archivos pesados)
│   ├── external/             # shapefiles, catálogos externos
│   └── processed/            # panel limpio, tablas de predicción, contrato con la app
├── notebooks/                # exploración, prototipos de modelo
├── src/
│   ├── data/                 # scripts de descarga/limpieza/armonización geográfica
│   ├── features/             # construcción del índice de demanda y features del panel
│   ├── models/                # baseline + TFT, entrenamiento, validación retrospectiva
│   └── app/                  # dashboard (Streamlit u otro)
└── reports/figures/          # gráficas para la presentación
```

`.gitignore` debe excluir datos crudos pesados (`data/raw/`, `data/external/`)
si superan límites razonables de tamaño de repo — usar en su lugar un script de
descarga reproducible en `src/data/`.

---

## 11. Glosario rápido (para agentes/colaboradores no familiarizados con México)

- **AGEB**: Área Geoestadística Básica, la unidad censal más fina de INEGI.
- **DENUE**: Directorio Estadístico Nacional de Unidades Económicas (INEGI) —
  censo de establecimientos, con ediciones periódicas.
- **SCIAN**: Sistema de Clasificación Industrial de América del Norte — códigos
  de giro económico usados por DENUE.
- **Alcaldía**: división administrativa de la CDMX (equivalente a municipio),
  hay 16.
- **Colonia**: subdivisión vecinal dentro de una alcaldía, la unidad más
  reconocible para el público no experto.
- **Ecobici**: sistema de bicicletas públicas compartidas de la CDMX.
- **SEMOVI / SEDUVI**: secretarías de movilidad y de desarrollo urbano de la
  Ciudad de México, fuentes de datos abiertos oficiales.

---

## 12. Estado actual y próximos pasos

> **Mantener esta sección actualizada en cada sesión de trabajo.** Es lo primero
> que debe leer cualquier persona o agente que retome el proyecto.

**Última actualización**: 2026-09-17 (app interactiva de la sección 8
implementada y conectada al algoritmo de puntuación real).

**Estado**: los 4 requisitos técnicos duros de la rúbrica (sección 1) están
implementados: mapa geoespacial, interfaz amigable, ≥3 fuentes de datos y
algoritmo de puntuación/categorización. Falta el Temporal Fusion Transformer
(diferenciador, no requisito duro) y preparar la presentación/demo.

- ✅ 5/5 componentes del índice de demanda cargados e integrados
  (sección 5.3): uso Ecobici, aperturas DENUE, brecha de infraestructura,
  siniestralidad ciclista (ATUS), población por colonia (Marco Geoestadístico).
- ✅ Panel colonia × mes (107 colonias, 25 periodos) con el índice compuesto
  final, en `data/processed/panel_demanda_colonia.csv` /
  `indice_demanda_colonia.csv`.
- ✅ Modelo baseline (Theil-Sen) y prueba de LightGBM cuantílico corriendo
  end-to-end con validación retrospectiva (secciones 6.3.1-6.3.3) —
  LightGBM supera a Theil-Sen en las tres métricas tras cerrar los 5
  componentes, ver 6.3.3.
- ✅ Mapa exploratorio (`reports/figures/mapa_indice_demanda_colonia.html`)
  y mapa de calor de uso Ecobici.
- ✅ Algoritmo de puntuación/categorización con los 4 inputs del usuario
  (sección 7, requisito duro de la rúbrica) — implementado en
  `src/app/algoritmo_puntuacion.py` (ver detalle en sección 7.1), con su
  indicador nuevo de tipo de zona en `src/features/indicadores_tipo_zona.py`
  / `data/processed/tipo_zona_colonia.csv`. Falta calibrar pesos con
  feedback de negocio (ver 7.1) y conectarlo a una interfaz real.
- ✅ App/dashboard interactiva (sección 8) — `src/app/app.py` (Streamlit,
  decisión de sección 8.5 confirmada). Conecta en vivo con
  `calcular_scoring(...)` de `algoritmo_puntuacion.py` (principio 8.1: sin
  inferencia en vivo, solo lee proyecciones precalculadas). Cubre los 4
  inputs del usuario, mapa coropletico (con toggle categoría/score
  continuo), panel de ranking, panel "por qué" por colonia (factores,
  modelo usado, tendencia histórica + banda de incertidumbre P10-P90 a los
  3 horizontes), y expanders de fuentes/validación retrospectiva/ética
  (secciones 4, 6.3, 9). El contrato de sección 8.2 no se materializó tal
  cual (`zonas_predicciones.parquet`/`zonas_historico.parquet`) — la app lee
  directamente los CSV de `data/processed/` vía `algoritmo_puntuacion.py`,
  que cumple el mismo propósito sin una capa de archivo intermedia extra.
  Sí se agregó `data/processed/zonas_geometria.geojson` (nuevo:
  `src/features/geometria_colonias.py`, 84/107 colonias con polígono real,
  disuelto desde `colonias_iecm.shp` vía `crosswalk_colonias.csv`).
- 🐛 Bug corregido en `armonizar_colonias.py`/`geometria_colonias.py`
  (2026-09-17): el cruce de nombres de colonia no acotaba por alcaldía, así
  que nombres repetidos en alcaldías distintas del mismo shapefile (p. ej.
  "Buenavista" existe en Cuauhtémoc Y en Iztapalapa; "Cuauhtémoc" existe
  como colonia en Cuauhtémoc Y en La Magdalena Contreras) se fusionaban en
  un solo polígono gigante que saltaba de un extremo de la ciudad al otro.
  Ambos scripts ahora acotan las candidatas a la alcaldía de la colonia
  Ecobici antes de buscar por nombre. No cambia el % de cobertura reportado
  en 5.2 (93% DENUE, 79% polígono), solo corrige QUÉ polígono se asigna.
- ⬜ Temporal Fusion Transformer (sección 6.2) — no iniciado.
- ⬜ Roles del equipo (`PLAN.md`) sin asignar explícitamente en este
  documento.

**Próximos pasos inmediatos**:
1. Decidir el modelo de producción para la demo (Theil-Sen vs. LightGBM vs.
   TFT si da tiempo) — ver checkpoint de decisión en sección 6.2.
2. Probar la app (`streamlit run src/app/app.py`) con el equipo completo y
   recoger feedback de UX pensando en el público objetivo (sección 8.4) —
   pendiente la prueba de usuario externo del Día 8 de `PLAN.md`.
3. Validar con el equipo los pesos y heurísticas razonadas de la sección 7.1
   (afinidad_poblacion en particular, por la falta de datos demográficos por
   edad) y recalibrar si hay tiempo.
4. Considerar recalibrar/documentar mejor los pesos de la sección 5.3 dado
   el efecto negativo en la precisión direccional de Theil-Sen (ver 6.3.3).
5. Decidir si vale la pena resolver las 23 colonias sin polígono (crosswalk
   sin match, ver 5.2) para que aparezcan también en el mapa, no solo en el
   ranking de la app.

**Decisiones pendientes de confirmar**: si LightGBM reemplaza a Theil-Sen
como baseline "de seguridad" dado que ya lo supera en todas las métricas
(pendiente de discusión de equipo, no decidido unilateralmente aquí).
