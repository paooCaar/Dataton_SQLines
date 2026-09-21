# Fase 9 — TomTom en escenarios ECOBICI de 3 y 5 años

## Objetivo

Agregar presión vial externa a los escenarios de 36 y 60 meses sin alterar
el forecast validado de 1/3/6/12 meses.

## Fuente

Se usa TomTom Traffic Index para Ciudad de México.

El reporte 2025 publica:

- congestión media 2025: 75.9%;
- cambio frente a 2024: -3.6 puntos porcentuales.

Por consistencia, el archivo local reconstruye el valor comparable 2024 como
79.5%. No se mezclan cifras de ediciones anteriores con metodología distinta.

Fuente:
https://www.tomtom.com/traffic-index/city/mexico-city/

TomTom explica que su congestion level representa la diferencia entre el
tiempo real de viaje y las condiciones de flujo libre.

## Qué NO hacemos

No afirmamos que más tráfico cause más uso de ECOBICI.

Con solo una señal citywide comparable no es defendible estimar una
elasticidad causal por colonia.

## Cómo interviene TomTom

Los escenarios usan la magnitud absoluta del cambio reciente, 3.6 pp/año,
como stress:

- Bajo: -3.6 pp/año
- Base: 0 pp/año
- Alto: +3.6 pp/año

El nivel de congestión se convierte a factor de tiempo de viaje:

`1 + congestion / 100`

Luego usamos:

`traffic_multiplier = (future_factor / current_factor) ** 0.25`

El exponente 0.25 es una sensibilidad conservadora y explícita, no una
elasticidad estimada.

Finalmente:

`escenario_final = escenario_ecobici * traffic_multiplier`

## Interpretación

- Si el tráfico baja, el escenario bajo recibe un pequeño ajuste negativo.
- Si se mantiene, el escenario base queda neutral.
- Si aumenta, el escenario alto recibe un pequeño ajuste positivo.

El ajuste es moderado para que TomTom no domine la señal histórica de ECOBICI.

## Limitación espacial importante

La señal usada es para Ciudad de México en conjunto.

Por lo tanto, TomTom cambia los niveles de 3 y 5 años pero no cambia por sí
solo el ranking de colonias. Para hacer eso necesitamos Area Analytics o
Traffic Stats por polígonos/zonas.

## Contrato de producto

- 1/3/6/12 meses: forecast validado; TomTom NO interviene.
- 36/60 meses: SCENARIO_ONLY; TomTom sí interviene.
- TomTom se muestra en la app como señal de escenario y no como causa.

## Fórmula y calendario

Se conserva sin cambios el cálculo de Fase 8: crecimiento log interanual
exacto por colonia, q25/mediana/q75, al menos 8 comparaciones y caps globales
p10/p90 de las medianas. Primero se guardan `scenario_*_before_traffic`.
Para horizonte `h`, los años extra son `h / 12 - 1`: 2 para 36 y 4 para 60.
Se usa `C_futuro = max(0, 75.9 + cambio_anual_pp * años_extra)`.
No se limita a 100%, pues la congestión representa tiempo adicional.

El exponente 0.25 acerca el cociente positivo a 1 respecto al traslado completo
(exponente 1); esa es la razón de llamarlo conservador. No fue estimado ni
validado contra ECOBICI y no demuestra que exista respuesta al tráfico.
Base conserva exactamente su valor original porque su multiplicador es 1.
En bajo/alto, una actividad cero sigue en cero; una actividad missing sigue
missing. No se genera una señal de tráfico diferente por colonia.

El dato de 2025 se mantiene como referencia hipotética en el ancla de 12 meses
(2027-08 para origen 2026-08), y se aplica stress solo a los 2/4 años restantes.
No se pronostica ni se valida la trayectoria entre 2025 y esa ancla. Los targets
son 2029-08 y 2031-08. Las cantidades ECOBICI son endpoints del mes objetivo,
no viajes acumulados durante 3/5 años.

Por horizonte y escenario, todas las colonias se multiplican por el mismo
escalar positivo. Por ello se conserva el orden espacial, incluidos los
empates, al compararlo con el mismo escenario sin TomTom. No se afirma que los
rankings de bajo, base y alto sean iguales entre sí.

## Integración y reproducibilidad

Los dos ZIP entregados tienen SHA-256 idéntico
`396cf8761c6beb0dc8cb212799faecbe100f3a6406923e26ea619873ccf0371d`.
Se reutilizaron su CSV, presentación y pruebas de referencia; se integró el
ajuste en el generador existente sin reemplazar su lógica de crecimiento.
La carga valida valores finitos, años únicos, procedencia, indicadores de
derivación y reconciliación entre años comparables. Un delta reciente missing
produce error; no se infiere automáticamente desde otras ediciones.

`build_long_term_scenarios(..., tomtom=None)` conserva el comportamiento numérico
anterior, útil para comparar. El comando del generador exige el CSV TomTom y
no omite silenciosamente su ausencia. La metadata guarda observaciones,
supuestos, versión, hashes de código/fuentes y hash del CSV resultante.
Con los mismos inputs, el CSV se reproduce; `created_at` registra cada corrida.

Ejecutar desde la raíz del repo, en un entorno con las dependencias del proyecto:

```sh
python -B -m src.models.long_term_scenarios_v2
python -B -m unittest discover -s tests -v
streamlit run src/app/app_v2.py
```

La app presenta TomTom únicamente en 36/60 y conserva los contratos de Fase 7:
avisos de emisión actual ausente e histórica, selector de mapa y tarjetas
de escenario sin `st.metric`. El Opportunity Score conserva sus fuentes,
fórmula y filtros. No se entrena ni se recalibra el forecast corto.

## Riesgos pendientes

Una sola variación anual no identifica una tendencia duradera. El alto es un
stress simétrico, no una expectativa de empeoramiento. La cobertura citywide
no describe tráfico local, accesibilidad ciclista ni sustitución modal.
Los crecimientos ECOBICI pueden incluir expansión de la red y cambios de
cobertura. Los escenarios no tienen probabilidades ni intervalos conformales
propios, ni la validación retrospectiva de los horizontes cortos. La integridad
de estos últimos se verifica sin reinterpretar su evidencia previa.

## Resultado de esta integración

Fuente contrastada con la página oficial durante la integración: 75.9% en
2025 y 3.6 pp menos que 2024. Se generan 212 filas READY, 106 por horizonte,
con origen 2026-08. Ajustes bajo/base/alto: −1.039402% / 0% / +1.007966%
a 36 meses y −2.112627% / 0% / +1.986629% a 60 meses.

Validación ejecutada en orden: generador, suite completa (**133 tests OK**, sin
fallos ni skips) y arranque de Streamlit en localhost. AppTest también navega
36/60 y bajo/base/alto y verifica las tarjetas y el texto no causal. Se comprobó
la igualdad del crecimiento previo con Fase 8, invariancia del ranking y hashes
de artefactos cortos, legacy y tests anteriores respecto a `f7c98b7`.

Se usó Python 3.12 del runtime local con las dependencias temporales de las
fases previas (`ecobici-v7-app-deps`, `ecobici-v4-model-deps`,
`ecobici-v3-geo-deps`, `ecobici-v2-audit-deps` en `/private/tmp`). No se alteraron
las dependencias del proyecto. `.gitignore` permite únicamente el CSV TomTom
pequeño dentro de su carpeta para que pueda versionarse posteriormente.
No se realizó staging, commit, merge ni push.
