# Bitácora de fuentes de datos

> El reto exige documentar explícitamente las diferencias temporales y
> geográficas entre fuentes. Esta tabla es esa documentación — mantenla
> actualizada conforme cada fuente se confirma y se descarga. No dejar filas
> "por confirmar" después del Día 1 del `PLAN.md`.

## Cómo llenar cada fila
- **Cobertura temporal**: años/periodos exactos cubiertos por lo que se
  descargó (no lo que el portal ofrece en general).
- **Cobertura geográfica**: nivel de agregación real del archivo (dirección
  puntual, AGEB, colonia, alcaldía) y si cubre toda la CDMX o un subconjunto.
- **Fecha de descarga**: fecha en que el equipo bajó el archivo (los portales
  cambian de versión con el tiempo).
- **Ruta local**: dónde vive en `data/raw/` o `data/external/`.

| Fuente | URL / portal | Cobertura temporal | Cobertura geográfica | Formato | Fecha de descarga | Ruta local | Notas |
|---|---|---|---|---|---|---|---|
| INEGI — DENUE | [`denue_09_csv.zip`](https://www.inegi.org.mx/contenidos/masiva/denue/denue_09_csv.zip) | Snapshot a mayo 2026 (campo `fecha_alta` por establecimiento permite ver antigüedad de registro, pero **no hay fecha de baja** — un cierre solo se detecta comparando contra otra edición descargada después) | Punto (lat/lon) + `ageb`, `manzana` y `nomb_asent` (nombre de colonia/asentamiento) **ya vienen en el archivo**, no hace falta unión espacial punto-en-polígono para asignar colonia | CSV (zip, 43.3 MB) | 2026-09-15 | `data/raw/denue/` | 462,732 establecimientos en CDMX. Giros de bici confirmados: reparación/mantenimiento (719), comercio al por menor (269), por mayor de juguetes y bicicletas (159), fabricación (15). 6 filas sin `nomb_asent` (despreciable) |
| INEGI — Censo Población y Vivienda 2020, AGEB/manzana urbana | [`ageb_mza_urbana_09_cpv2020_csv.zip`](https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/ageb_manzana/ageb_mza_urbana_09_cpv2020_csv.zip) | Corte único 2020 (no es serie temporal en sí — el "≥3 momentos" se resuelve con otras ediciones censales si se necesitan, ver nota) | AGEB urbana (2,433 AGEB con `POBTOT`) y manzana, toda la CDMX | CSV (zip, 13.0 MB) | 2026-09-15 | `data/raw/censo_ageb_manzana2020/` | **Ojo**: el producto "ITER" (ver fila siguiente) NO llega a AGEB en CDMX — solo a alcaldía. Este es el producto correcto para población por zona pequeña, hay que usar `ageb_manzana`, no `iter` |
| INEGI — Censo Población y Vivienda 2020 (ITER) | [`iter_09_cpv2020_csv.zip`](https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/iter/iter_09_cpv2020_csv.zip) | Corte único 2020 | **Solo alcaldía/localidad** (16 alcaldías; en CDMX cada alcaldía es ~1 sola localidad urbana) — mucho más agregado de lo que dice la fila original de esta tabla | CSV (zip, 171 KB) | 2026-09-15 | `data/raw/censo_iter2020/` | Se descargó primero por error de expectativa (el nombre "ITER" sugiere AGEB, pero no en zonas urbanas). Se queda como referencia de alcaldía; usar `ageb_manzana` (fila de arriba) para el panel real |
| INEGI — Marco Geoestadístico (AGEB urbana, edición 2020, vía Datos Abiertos CDMX) | [`ageb_urbana_cdmx.zip`](https://datos.cdmx.gob.mx/dataset/d2ccf6ae-fdf4-407c-a15f-e7dfac2d509d/resource/b2e17ed0-f2d9-4540-94a1-e57e988b6668/download/b2e17ed0-f2d9-4540-94a1-e57e988b6668.zip) — el propio dataset de CDMX declara que reproduce "el Marco Geoestadístico 2020 generado por INEGI"; no se usó la descarga masiva directa de inegi.org.mx/app/descarga porque el portal de CDMX ya lo distribuye recortado a CDMX y en el mismo formato SHP que `colonias_iecm` | Corte 2020, sin histórico | 2,431 polígonos de AGEB urbana, toda la CDMX, EPSG:4326, con `CVEGEO` (mismo esquema de clave que el censo AGEB/manzana: `ENTIDAD+MUN+LOC+AGEB`, 13 caracteres) | SHP (zip, 1.6 MB) | 2026-09-15 | `data/raw/marco_geoestadistico/` | Cierra el bloqueo de `indicadores_poblacion.py` (CONTEXT.md 5.2): permite unión espacial AGEB→colonia (centroide del AGEB dentro del polígono de `colonias_iecm`) para population por colonia, no solo por alcaldía — ver `indicadores_poblacion_colonia.py`. 2,431 de 2,433 AGEB del censo tienen polígono (2 AGEB del censo no aparecen en esta capa) |
| Colonias CDMX (límites) | [`colonias_cdmx.zip`](https://datos.cdmx.gob.mx/dataset/04a1900a-0c2f-41ed-94dc-3d2d5bad4065/resource/f1408eeb-4e97-4548-bc69-61ff83838b1d/download/f1408eeb-4e97-4548-bc69-61ff83838b1d.zip) (catálogo de colonias, Datos Abiertos CDMX — capa `colonias_iecm`, IECM = Instituto Electoral CDMX) | Estado actual, sin histórico | 1,814 polígonos de colonia, toda la CDMX, EPSG:32614 | SHP (zip, 1.4 MB) | 2026-09-15 | `data/raw/colonias_cdmx/` | **No es el Marco Geoestadístico de INEGI** (ese da AGEB/municipio, no colonia) — se usó esta capa electoral porque sí trae polígono de colonia. Nombres en MAYÚSCULAS y algunas colonias partidas en sub-polígonos (p. ej. "ROMA NORTE I/II/III") — no calzan 1:1 con los nombres de `Caracteristicas_estaciones.csv` de Ecobici, hace falta normalizar/mapear antes de usar para unión espacial |
| Datos Abiertos CDMX — Ecobici (viajes) | archivos mensuales `YYYY-MM.csv` provistos directamente por el equipo en `datos_bici/` (no descargados por el agente en esta sesión) | 25 meses con huecos, 2023-01 a 2026-06 | Viaje individual con cicloestación origen/destino (`Ciclo_Estacion_Retiro`/`Ciclo_EstacionArribo`) + `Caracteristicas_estaciones.csv` con colonia/alcaldía/lat-lon por estación (688 estaciones, 107 colonias, 6 alcaldías: Cuauhtémoc, Benito Juárez, Miguel Hidalgo, Coyoacán, Azcapotzalco, Álvaro Obregón) | CSV | ya en repo al 2026-09-15 | `datos_bici/` | **Confirmado**: sí trae detalle por estación (no solo agregado ciudad). 33,894,635 viajes procesados — ver `data/processed/panel_demanda_colonia.csv`. Es la única fuente con densidad mensual real |
| Datos Abiertos CDMX / GBFS Ecobici (tiempo real) | `https://gbfs.mex.lyftbikes.com/gbfs/gbfs.json` | Solo estado actual (no histórico) | Por cicloestación (punto) | JSON | | | Útil solo para catálogo de estaciones activas hoy (lado de "oferta"), no para serie histórica — no descargado todavía |
| Datos Abiertos CDMX — Infraestructura vial ciclista (SEMOVI/ADIP) | [`infraestructura_vial_ciclista.zip`](https://datos.cdmx.gob.mx/dataset/7a017dd2-0dec-44f2-b550-10af1a6ee120/resource/6e541083-1399-4c14-a210-0493167c7b16/download/6e541083-1399-4c14-a210-0493167c7b16.zip) (SHP) + [diccionario de datos](https://datos.cdmx.gob.mx/dataset/7a017dd2-0dec-44f2-b550-10af1a6ee120/resource/d70d3ddd-25c8-42ba-8bf9-fe2a855ded25/download/d70d3ddd-25c8-42ba-8bf9-fe2a855ded25.xlsx) | 11ª versión, 651 tramos a marzo 2025 (confirmado: 651 filas exactas en `Infraestructura ciclista total.shp`) — cada tramo trae año de entrada en operación → permite reconstruir km acumulados por año | Tramo de vialidad (línea), con alcaldía, EPSG:32614 | SHP (zip, 296 KB) + XLSX (9 KB) | 2026-09-15 | `data/raw/infraestructura_ciclista/` | Capa dividida por tipo (Ciclovía, Ciclovía bidireccional, Carril Bus-Bici, Ciclocarril, Carril de prioridad ciclista, Sendero compartido) + una capa `Infraestructura ciclista total` que las une. La propia fuente advierte que "la información histórica puede cambiar en actualizaciones posteriores" — documentar como limitación |
| INEGI — ATUS (accidentes de tránsito) | [Catálogo RNM](https://www.inegi.org.mx/rnm/index.php/catalog/684/data-dictionary/F1?file_name=ATUS) — edición real usada: `atus_anual_2023/2024/2025.csv`, ya presente (México completo, todos los años 1997-2025) en el commit inicial del repo (`c9bc25b`, "csvs inegi upload") y **restaurada del historial de git** con `src/data/preparar_atus.py` (no se volvió a descargar de INEGI) | 2023-01 a 2025-12 (cifras definitivas; ATUS 2026 aún no publicado — el panel Ecobici llega a 2026-06, así que esos 6 meses quedan sin dato ATUS, ver `indicadores_atus.py`) | **Municipio/alcaldía** (campo `CVE_MUN`, mapeado a nombre con `tc_municipio.csv`); calle exacta solo como texto libre en `URBANA` (no geocodificada) | CSV (filtrado a CDMX: 3 archivos de ~19,200 accidentes en total, de ~1.1M nacionales) | ya en el repo desde 2026-09-09 (subida inicial); filtrado/restaurado a CDMX el 2026-09-15 | `data/raw/atus/` | Se usó `TIPACCID == "Colisión con ciclista"` OR `CICLMUERTO+CICLHERIDO > 0` para capturar también atropellamientos a ciclistas clasificados bajo otro tipo de accidente (6 casos en 2023-2025). 348 accidentes con ciclista en CDMX 2023-2025, concentrados en Cuauhtémoc (85) y Benito Juárez (44) de las 6 alcaldías en alcance. Se agrega a nivel alcaldía-mes → `data/processed/atus_accidentes_alcaldia_mes.csv`, ver `indicadores_atus.py` y CONTEXT.md 5.2 |
| OpenStreetMap (opcional) | Overpass API | Estado actual, sin histórico nativo | Lo que se consulte (vías, POIs) | JSON/GeoJSON | | | Solo como complemento/validación cruzada, no fuente primaria de tendencia — no descargado todavía |

## Apéndice — estructura real confirmada de las fuentes (2026-09-10)

### DENUE (registro = 1 establecimiento, snapshot a fecha de corte)
`CLEE`, `Id_establecimiento`, `Nombre_establecimiento`, `Razon_social`,
`Clase_actividad` (texto) + `Clase_Actividad_Id`/`Sector_Actividad_Id`/... (con
método `BuscarAreaAct` de la API), `Estrato` (personal ocupado, en rangos),
`Tipo_vialidad`, `Calle`, `Num_exterior`, `Num_interior`, `Colonia`,
`Codigo_postal`, `Localidad`/`Municipio`/`Entidad`, `Telefono`, `Correo`,
`Sitio_internet`, `Tipo_establecimiento`, `Longitud`, `Latitud`,
`Centro_comercial`, `Fecha_Alta`, y con `BuscarAreaAct` también `AGEB` y
`Manzana`. **Importante**: no hay campo de "fecha de baja" — un cierre se
infiere por la desaparición del `Id_establecimiento` entre dos snapshots
descargados en fechas distintas. Fuente: [Diccionario de datos DENUE (PDF)](https://www.inegi.org.mx/contenidos/masiva/denue/denue_diccionario_de_datos.pdf),
[API DENUE](https://www.inegi.org.mx/servicios/api_denue.html).

### ATUS — accidentes de tránsito (registro = 1 accidente/víctima)
46 variables en total; las relevantes para este proyecto: `EDO`, `MPIO`,
`LOCALIDAD`, `URBANA` (texto libre con nombre de calle), `ANIO`, `MES`, `DIA`,
`DIASEMANA`, `HORA`, `MINUTOS`, `TIPACCID` (incluye "colisión con ciclista"),
`CAUSAACCI`, `CAPAROD`, y conteos de víctimas por categoría (conductores,
pasajeros, peatones, **ciclistas**). Fuente: [Diccionario ATUS 2020](https://www.inegi.org.mx/rnm/index.php/catalog/684/data-dictionary/F1?file_name=ATUS).

### Infraestructura vial ciclista CDMX (registro = 1 tramo de vialidad)
Geometría de línea + atributos: tipo de infraestructura (ciclovía, carril
bus-bici, ciclocarril, etc.), año de entrada en operación, dependencia
responsable, tipo de vialidad, alcaldía, coordenadas. Diccionario de datos
completo viene en un Excel aparte del shapefile — descargarlo junto con los
datos. Fuente: [Dataset infraestructura vial ciclista](https://datos.cdmx.gob.mx/dataset/infraestructura-vial-ciclista).

### Ecobici (estructura por confirmar exactamente — pendiente Día 1)
El portal de Datos Abiertos CDMX ofrece "viajes diarios" (agregado diario por
género) y "viajes mensuales desglosados" (agregado mensual por género, rango
de edad, hora de arribo); el sitio propio de Ecobici históricamente ha
publicado además archivos mensuales `YYYY-MM.csv` con el detalle de columnas
típico de sistemas de bici pública (`Genero_Usuario`, `Edad_Usuario`, `Bici`,
`Ciclo_Estacion_Retiro`, `Fecha_Retiro`, `Hora_Retiro`,
`Ciclo_Estacion_Arribo`, `Fecha_Arribo`, `Hora_Arribo`) — **esto último no se
pudo confirmar leyendo un CSV real en esta sesión, verificarlo descargando un
archivo de muestra antes de construir el pipeline.** Si solo hay agregados a
nivel ciudad (sin estación), Ecobici deja de servir como variable *por zona*
y su rol se reduce a covariable de contexto general.

## Decisiones de armonización

- **Desajuste geográfico — nombres de colonia sin identificador común**:
  Ecobici, DENUE y la capa `colonias_iecm` (Datos Abiertos CDMX) escriben
  las colonias de tres formas distintas y sin una clave compartida. Se
  resolvió con un cruce por nombre normalizado (sin acentos, mayúsculas,
  quitando sufijos de sección romana como fallback) en
  [`src/features/armonizar_colonias.py`](../src/features/armonizar_colonias.py)
  → `data/processed/crosswalk_colonias.csv`. Cobertura: 93% (99/107) contra
  DENUE, 79% (84/107) contra el polígono de colonia. Las colonias sin match
  quedan explícitamente sin ese dato (no se fuerza una coincidencia
  dudosa) — ver detalle en `CONTEXT.md` 5.2.

- **Desajuste geográfico — DENUE ya viene con colonia/AGEB**: a diferencia de
  lo que anticipaba `CONTEXT.md` 6.1.1 (unión espacial punto-en-polígono),
  la edición de DENUE descargada trae `ageb`, `manzana` y `nomb_asent`
  (colonia) directamente por establecimiento — no hizo falta `geopandas.sjoin`.

- **Desajuste geográfico — Marco Geoestadístico vs. colonia**: el Marco
  Geoestadístico de INEGI da polígonos de AGEB/manzana/municipio, pero NO
  de colonia. Para el polígono de colonia se usó en su lugar la capa
  `colonias_iecm` del Instituto Electoral de la CDMX (Datos Abiertos CDMX),
  que sí tiene geometría de colonia pero con límites/nomenclatura propios
  (subdivide algunas colonias en sub-polígonos con esquemas de numeración
  distintos a los de Ecobici, p. ej. "DEL VALLE I-VII" vs. "Del Valle
  Centro/Norte/Sur") — de ahí la cobertura de match incompleta (79%).

- **Desajuste temporal — DENUE es snapshot único**: la edición descargada
  (mayo 2026) no tiene fecha de baja, así que no se pueden calcular
  aperturas/cierres netos comparando contra una edición anterior (no
  descargada). Se usó `fecha_alta` (fecha de registro de cada
  establecimiento que sigue activo) como proxy de aperturas brutas por
  mes — subestima el total histórico real (no ve cierres) pero es
  comparable entre zonas. Ver `CONTEXT.md` 5.2.

- **Desajuste geográfico/temporal — población, resuelto a nivel colonia
  (2026-09-15)**: con el Marco Geoestadístico ya descargado (fila de arriba),
  `indicadores_poblacion_colonia.py` hace la unión AGEB→colonia (centroide de
  cada uno de los 2,431 AGEB dentro del polígono de `colonias_iecm` que lo
  contiene) y agrega población real por colonia (`poblacion_colonia_2020`),
  que ya sí entra al índice compuesto ponderado (`indice_compuesto.py`) — a
  diferencia de la versión anterior (`poblacion_alcaldia.csv`, ITER 2020, que
  se queda solo como columna informativa porque no discrimina entre colonias
  de una misma alcaldía). Sigue siendo un solo corte (2020): aporta nivel, no
  tendencia. Cobertura: 84/107 colonias (mismas que tienen polígono en
  `colonias_iecm`, ver crosswalk arriba); las 23 sin polígono quedan
  imputadas a 0 en el z-score (ni penaliza ni favorece).

- **Desajuste geográfico — infraestructura ciclista prorrateada**: los 651
  tramos de la capa de infraestructura vial ciclista se intersectaron
  (`geopandas.overlay`) contra los polígonos de `colonias_iecm` para
  prorratear el km de cada tramo entre las colonias que cruza, en vez de
  asignar el tramo completo a una sola colonia — ver
  [`src/features/indicadores_infraestructura.py`](../src/features/indicadores_infraestructura.py).
