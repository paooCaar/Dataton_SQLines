# UX: forecast corto y escenarios largos

Esta mejora solo cambia presentación y cálculos descriptivos en memoria.
No se regeneran CSV ni metadata, ni se cambian modelos, se recalibran intervalos
ni se modifica Opportunity Score. Los tests existentes se conservan.

## Dos productos visibles

1/3/6/12 meses se identifican como **CORTO PLAZO · FORECAST VALIDADO**
retrospectivamente. Persistencia conserva el nivel reciente por su desempeño
histórico; no promete que la actividad no cambie. Las diferencias de calidad
de validación por horizonte y las coberturas históricas siguen disponibles.

36/60 meses se identifican como **LARGO PLAZO · ESCENARIOS · SCENARIO_ONLY**,
con `is_validated_forecast = False`. La app explica el ancla de 12 meses,
crecimiento histórico, escenarios bajo/base/alto y ajuste TomTom. Las tarjetas
largas usan texto, no `st.metric`, incluso fuera de cobertura.

## Mapa corto y compatibilidad

El selector principal contiene Actividad prevista, Incertidumbre y Tendencia
reciente. El selectbox heredado **Mostrar en mapa**, con todas sus opciones,
vive en **Detalles técnicos y complementarios**. Ambos controles se sincronizan;
al elegir una opción técnica se limpia la selección principal y se señala el
mapa activo. Cada opción muestra su propia explicación. Se mantienen literalmente
los avisos de emisión actual ausente y de validación histórica.

Incertidumbre conserva el mapa de ancho relativo del intervalo ya existente.
Su explicación no afirma que una colonia haya sido individualmente más difícil:
los radios conformales se calibraron globalmente por horizonte. Una banda
relativamente mayor puede deberse a menor actividad, sin mayor error local.

## Tendencia reciente: historia observada

Se lee `panel_demanda_v2.csv` sin modificarlo. Para cada zona y origen mostrado
(también para los distintos orígenes del backtest), se compara `t` con `t-12`
meses calendario exactos. Ambos deben ser OBSERVED o ZERO_DEMAND, no negativos,
finitos y con fecha mínima de disponibilidad anterior o igual a inicio de `t+1`.
No se recurre a la fila anterior si falta el mes requerido ni se usa el target
futuro del forecast. Fórmula: `100 * (y_t - y_t-12) / y_t-12`.

Un denominador cero, missing, estado desconocido o publicación posterior al
corte da **Sin dato**. Cero observado en el numerador sí puede producir −100%.
No se estiman ni imputan valores. La tasa se clasifica con una regla de producto:
mayor que +5% Subiendo, menor que −5% Bajando, ambos límites incluidos en Estable.
±5% sirve para lectura consistente; no es un umbral de significancia ni fue
optimizado contra resultados. Sin dato permanece fuera de esas categorías.

El hover incluye colonia, alcaldía, porcentaje, categoría y los dos meses.
Las zonas sin historia aparecen grises cuando tienen geometría; sin geometría
siguen disponibles en búsqueda y detalle. Las alcaldías fuera de cobertura
conservan el aviso correspondiente.

## Mapas largos

`scenario_change_pct = 100 * (scenario_value / anchor_12m_value - 1)` se calcula
en una copia de las filas; se conserva aparte de `forecast_change_pct`. Con
ancla cero/missing o valor inválido se muestra Sin dato. Dirección: >+5% AUMENTO,
<−5% DISMINUCIÓN, entre ambos ESTABLE; también es regla de producto.

El selector largo ofrece actividad del escenario, cambio frente al ancla,
dirección y aporte TomTom. Bajo/Base/Alto cambian su explicación y sus valores.
El mapa TomTom usa el ajuste porcentual existente sin inventar variación local:
un mismo horizonte/escenario tiene un solo porcentaje citywide. No entra en
los controles ni tarjetas cortas. El score sigue siendo independiente.

## Límites

La tasa interanual usa dos observaciones y puede ser sensible a expansión de
red, estacionalidad cambiante y revisiones. Las fechas de disponibilidad son
cotas mínimas; no acreditan vintages históricos. No es tendencia estadística
estimada ni predicción. Los escenarios mantienen sus hipótesis de crecimiento
y tráfico sin causalidad demostrada ni probabilidades. El mapa de ancho del
intervalo no aporta nueva evidencia de cobertura por colonia.

## Verificación

Suite completa: **145 tests OK**, sin fallos ni omitidos (133 anteriores y
12 nuevos). AppTest recorre 1/3/6/12, 36/60, las tres vistas principales,
opciones técnicas, Bajo/Base/Alto, cuatro mapas largos, zonas sin geometría y
alcaldías fuera de cobertura. Los hashes de datos, modelos, Opportunity Score,
app legacy y tests previos coinciden con `9899c41`. No se realizó commit ni push.
