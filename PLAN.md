# PLAN.md — Cronograma y roles del equipo

> Lee primero [`CONTEXT.md`](CONTEXT.md) si no conoces el reto, las decisiones de
> alcance o la metodología — este archivo asume ese contexto y solo organiza el
> *cómo y cuándo*.

Duración total: **9 días de trabajo** (equipo de 4 personas, dedicación parcial).
Sustituye "Día N" por la fecha real de tu calendario; el último día (Día 9) debe
caer el día anterior a la presentación como mínimo, idealmente con un día de
colchón adicional si el cronograma real lo permite.

---

## Roles

No son compartimentos estancos — en un equipo de 4 habrá superposición — pero
cada eje de la rúbrica necesita un dueño claro para que nada se caiga por
difusión de responsabilidad.

| Rol | Persona | Responsabilidad principal |
|---|---|---|
| **A. Datos & GIS** | _(asignar)_ | Sourcing, descarga, limpieza y armonización geográfica de todas las fuentes; construir el panel histórico por zona; documentar `docs/fuentes_datos.md` |
| **B. Modelado (transformer)** | _(asignar)_ | Índice de demanda, baseline (tendencia/LightGBM), Temporal Fusion Transformer, validación retrospectiva, interpretabilidad |
| **C. Backend / Integración** | _(asignar)_ | Algoritmo de puntuación y categorización (requisito duro de rúbrica), contrato de datos modelo↔app, robustez del "ejercicio en tiempo real" |
| **D. Frontend / UX / Narrativa** | _(asignar)_ | Mapa e interfaz, textos para público no experto en CDMX, guion de presentación, ensayo de demo |

### Mapeo explícito a los ejes de evaluación

| Eje de evaluación | Dueño principal | Dónde se resuelve |
|---|---|---|
| Calidad técnica y metodológica | B (+ A) | Sección 6-7 de `CONTEXT.md`, tabla de backtesting |
| Claridad y comunicación de la solución | D | Guion de presentación, textos de la app |
| Uso y manejo de datos | A | `docs/fuentes_datos.md`, armonización geográfica |
| Experiencia de usuario e interfaz | D (+ C) | App, requisito duro "interfaz amigable" |
| Ejercicio en tiempo real | C (+ D) | App respondiendo a consultas en vivo de los jueces |
| Requisito duro: mapa geoespacial | D | Sección 8 de `CONTEXT.md` |
| Requisito duro: ≥3 fuentes con INEGI | A | Sección 4 de `CONTEXT.md` |
| Requisito duro: algoritmo de puntuación/categorización | C (con output de B) | Sección 7 de `CONTEXT.md` |

---

## Cronograma

### Día 1 — Kickoff y auditoría de datos
- Repartir roles (tabla arriba) y confirmar disponibilidad de cada persona en
  los próximos 9 días.
- Leer y discutir `CONTEXT.md` como equipo completo; ajustar cualquier
  decisión (unidad de zona, alcaldías en alcance, stack) y **dejarlo escrito**
  en ese archivo, no solo hablado.
- **A**: auditar disponibilidad real de cada fuente candidata (sección 4 de
  `CONTEXT.md`) contra los portales oficiales (INEGI DENUE, Datos Abiertos
  CDMX/Ecobici, ciclovías, ATUS). Confirmar ediciones/años exactos disponibles
  y llenar `docs/fuentes_datos.md`.
- **B**: investigar en paralelo si `pytorch-forecasting` instala sin fricción
  en el entorno del equipo (riesgo técnico temprano, mejor descubrirlo el
  Día 1 que el Día 6).
- **Entregable del día**: `docs/fuentes_datos.md` con fuentes confirmadas +
  decisiones de alcance congeladas en `CONTEXT.md`.

### Día 2 — Ingesta y esquema de datos
- **A**: descargar datos crudos (scripts reproducibles en `src/data/`, no
  descargas manuales sin registrar); cargar y validar shapefile de
  colonias/alcaldías.
- **A + B**: definir el esquema exacto del panel histórico (`zona_id`,
  `periodo`, columnas) y escribirlo en `CONTEXT.md` sección 5.1.
- **D**: empezar el mockup de la app con datos sintéticos (no bloquear en
  espera de datos reales) — layout del mapa, panel de ranking, inputs.
- **C**: definir el contrato de datos exacto (`data/processed/*.parquet`,
  columnas) en código/README de `src/app/`.

### Día 3 — Limpieza, armonización y primer índice
- **A**: unión espacial AGEB→colonia, geocodificación de DENUE→colonia,
  limpieza de series de Ecobici/ciclovías/siniestros.
- **A + B**: construir el panel histórico real (≥3 momentos) y calcular la
  primera versión del índice de demanda (sección 5 de `CONTEXT.md`); congelar
  la fórmula final (pesos) en sección 5.1.
- **Decisión de checkpoint**: ¿colonia es viable o hay que caer a alcaldía?
  Documentar en `CONTEXT.md` sección 3.
- **D**: EDA visual — primeros mapas exploratorios con datos reales.

### Día 4 — Baseline end-to-end (hito crítico)
- **B**: entrenar el modelo baseline (tendencia robusta o LightGBM cuantílico)
  y correr la primera validación retrospectiva.
- **C**: implementar el algoritmo de puntuación/categorización (sección 7)
  usando la salida del baseline.
- **D**: conectar la app real (no mockup) al pipeline: datos → baseline →
  scoring → mapa. **Esto debe funcionar de punta a punta hoy**, aunque el
  modelo sea simple — es la red de seguridad del proyecto.
- **Entregable del día**: demo interna funcional con datos y modelo reales
  (aunque sea el modelo simple).

### Día 5-6 — Temporal Fusion Transformer (diferenciador)
- **B**: preparar el panel en formato `TimeSeriesDataSet`, entrenar TFT con
  `QuantileLoss`, generar forecasts P10/P50/P90 a los 3 horizontes, extraer
  interpretabilidad (variable importance).
- **B + A**: correr la validación retrospectiva del TFT con el mismo esquema
  que el baseline (mismas métricas, misma tabla comparativa).
- **Checkpoint de decisión (fin de Día 6)**: comparar TFT vs. baseline. Si TFT
  gana → se convierte en modelo de producción para la demo. Si no converge o
  no supera al baseline → el baseline sigue siendo el modelo en vivo, y TFT se
  presenta como análisis comparativo honesto. **No forzar TFT en producción si
  no es confiable** — la decisión y su justificación se documentan en
  `CONTEXT.md` sección 6.2.
- **C + D**: mientras tanto, seguir puliendo la app sobre el baseline (no
  esperar a TFT para avanzar en UI).

### Día 7 — Integración completa
- **C**: conectar la salida del modelo ganador (TFT o baseline) al contrato de
  datos de la app; implementar los 4 inputs de usuario (horizonte, población
  objetivo, tipo de zona, riesgo) filtrando/rankeando sobre predicciones
  **precalculadas** (nunca inferencia en vivo — ver `CONTEXT.md` 8.1).
- **D**: pulir textos, tooltips y panel "por qué" pensado para el público no
  experto en CDMX (sección 8.4 de `CONTEXT.md`).
- **A**: redactar la sección de fuentes/armonización para la presentación
  (qué se integró, qué diferencias temporales/geográficas hubo).
- **Todo el equipo**: redactar juntos las consideraciones éticas/sesgos
  (sección 9 de `CONTEXT.md`) para incluir en la presentación.

### Día 8 — QA, validación final y narrativa
- Prueba de usuario con alguien externo al equipo (que no haya visto la app).
- Revisar y congelar la tabla final de métricas de validación retrospectiva.
- Armar el guion de los 10 minutos de presentación + preparar 2-3 consultas de
  ejemplo para los 5 minutos de interacción en vivo (incluir una variante del
  caso de ejemplo del reto adaptada a movilidad ciclista).
- Preparar respaldo de contingencia: capturas de pantalla / video corto de la
  app funcionando, por si falla el internet del recinto.

### Día 9 — Ensayo general y colchón
- Ensayo cronometrado completo (10 min presentación + 5 min interacción) con
  retroalimentación cruzada entre los 4.
- Checklist final (ver abajo) contra requisitos mínimos y rúbrica.
- Buffer para arreglar bugs de última hora — no programar trabajo nuevo aquí.

---

## Gestión de riesgos

| Riesgo | Mitigación |
|---|---|
| TFT no converge o no da tiempo | Baseline funcional desde Día 4, es lo que se demuestra si TFT falla (ver `CONTEXT.md` 6.2) |
| Fuente de datos clave no disponible como se esperaba | Auditoría de fuentes en Día 1, no en Día 4 |
| Internet falla durante la demo | App con respaldo local + video/capturas de respaldo (Día 8) |
| Modelo tarda en responder durante el "ejercicio en tiempo real" | Predicciones precalculadas en batch; la app solo filtra (`CONTEXT.md` 8.1) |
| Zonas con pocos datos aparecen como "baja demanda" (sesgo) | Categoría explícita `Datos insuficientes` (`CONTEXT.md` sección 7 y 9) |

---

## Checklist final pre-demo

- [x] Aplicación funcional (no solo notebooks) — `src/app/app.py`
      (Streamlit), ver `CONTEXT.md` 8.6.
- [x] ≥3 fuentes de datos integradas, con INEGI incluido y documentado —
      visible en la app (expander "Fuentes de datos").
- [x] Visualización geoespacial (mapa con zonas/marcadores) — 84/107
      colonias con polígono real, ver `CONTEXT.md` 8.6.
- [x] Interacción en tiempo real (inputs del usuario responden sin demoras)
      — verificado en navegador con los 4 inputs.
- [x] Método de proyección con horizonte 1/3/5 años.
- [x] Medida de tendencia explícita — pendiente Theil-Sen, visible por
      colonia en la app.
- [x] Medida de incertidumbre/confianza visible en la interfaz — banda
      P10-P90 en la gráfica de cada colonia.
- [ ] Validación retrospectiva con métricas reportadas (y comparación
      baseline vs. TFT) — LightGBM vs. Theil-Sen vs. naive ya se reportan
      (en vivo, en la app); falta TFT.
- [x] Algoritmo de puntuación que categoriza zonas según datos + inputs del
      usuario (`src/app/algoritmo_puntuacion.py`, ver `CONTEXT.md` 7.1).
- [x] Ranking de oportunidades de expansión.
- [x] Explicación de factores por zona (interpretabilidad).
- [ ] Consideraciones éticas/sesgos incluidas en la presentación.
- [ ] Textos de interfaz y guion pensados para alguien sin conocimiento previo
      de la CDMX.
- [ ] Guion de 10 min + plan de interacción de 5 min ensayado con tiempo real.
- [ ] Respaldo offline/video por si falla el internet en el recinto.
