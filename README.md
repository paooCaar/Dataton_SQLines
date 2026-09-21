# Dataton_SQLines

Proyecto del equipo para el **Datatón 2026 (ITAM)** — reto de predicción de
demanda urbana en la Ciudad de México, categoría **Movilidad, transporte e
infraestructura ciclista**.

## Empieza aquí

- [`CONTEXT.md`](CONTEXT.md) — documento maestro: el reto, las decisiones de
  alcance, la metodología (modelo baseline + Temporal Fusion Transformer), el
  algoritmo de puntuación y el estado actual del proyecto. Léelo primero,
  seas humano o agente de IA retomando este repo.
- [`PLAN.md`](PLAN.md) — cronograma día a día, roles del equipo y checklist
  final pre-demo.
- [`docs/fuentes_datos.md`](docs/fuentes_datos.md) — bitácora de fuentes de
  datos usadas (INEGI + Datos Abiertos CDMX + complementarias).

## Estructura del repo

Ver sección 10 de [`CONTEXT.md`](CONTEXT.md).

## Abrir la aplicación V2

Desde la raíz del repositorio, con Python 3.12 y los artefactos ya existentes en
`data/processed/`:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-app-v2.txt
.venv/bin/streamlit run src/app/app_v2.py
```

La aplicación es de solo lectura y no entrena modelos al abrirse. Tiene dos
páginas: **Panorama actual** colorea las colonias según la actividad observada
del último mes y puede mostrar las cicloestaciones instaladas del catálogo local.
Al pasar sobre un punto aparece su actividad del último mes por estación que
puede reconstruirse con los archivos locales (2026-01); no es la disponibilidad
de bicicletas en tiempo real ni corresponde al mes del mapa por colonia (2026-08).
El archivo `data/processed/station_activity_latest_v2.csv` se regenera con
`.venv/bin/python -m src.data.station_activity_snapshot` al añadir viajes mensuales.
**A futuro** muestra el
cambio frente al mes actual con una misma escala de colores para 1, 3 y 5 años.
El horizonte de 1 año usa el pronóstico publicado; 3 y 5 años usan escenarios
bajo, base y alto.

La columna «Nuevas estimadas» del ranking usa una regla de tres por colonia:
`ceil(estaciones_hoy × demanda_futura / demanda_hoy) − estaciones_hoy`, con
mínimo de cero. Si la demanda actual es cero o falta, no se calcula. Es una
estimación de capacidad proporcional, no una predicción de aperturas oficiales.
