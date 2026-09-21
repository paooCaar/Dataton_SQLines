# Fase 8 — Escenarios de largo plazo y lenguaje de producto

## Qué cambia

La app separa dos productos:

- **1, 3, 6 y 12 meses:** forecast V2 con validación retrospectiva e incertidumbre.
- **36 y 60 meses:** escenarios condicionados bajo/base/alto. No se presentan como forecast validado.

## Escenarios de 3 y 5 años

El escenario parte del forecast operativo de 12 meses y extiende la actividad con crecimiento interanual histórico por colonia.

Se calculan crecimientos exactos a 12 meses. No se salta un mes faltante para buscar el último registro disponible.

La distribución de crecimiento de cada colonia se resume con:

- q25 → escenario bajo
- mediana → escenario base
- q75 → escenario alto

Las tasas se limitan con p10/p90 de las medianas históricas de las colonias con historia suficiente. El objetivo es evitar que una tasa extrema se componga durante varios años.

Los escenarios se calculan en escala logarítmica y se componen:

- 36 meses: 2 años adicionales después del ancla a 12 meses
- 60 meses: 4 años adicionales después del ancla a 12 meses

Estos valores **no son P10/P50/P90**, no son intervalos de confianza y no tienen cobertura probabilística calibrada.

## Lenguaje de la app

La vista principal evita términos técnicos innecesarios.

En lugar de presentar `PERSISTENCE` como una etiqueta central, explica:

> Nuestro punto central mantiene el nivel reciente porque fue el método que se comportó de forma más estable cuando lo probamos con meses pasados.

Los detalles técnicos siguen disponibles en expanders.

## Cobertura territorial

Las 16 alcaldías permanecen visibles en el selector.

Las alcaldías sin histórico ECOBICI suficiente no reciben una predicción inventada. La app distingue explícitamente entre:

- falta de histórico para forecast;
- posible demanda u oportunidad de expansión.

## Mapa

Para horizontes cortos:

- Actividad prevista
- Incertidumbre

Para 3 y 5 años:

- escenario bajo
- escenario base
- escenario alto

Los colores son categorías relativas dentro de la selección visible y el valor numérico exacto aparece en hover.
