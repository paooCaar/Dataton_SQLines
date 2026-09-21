"""App V2 de ECOBICI: pronóstico corto + escenarios de largo plazo.

La app mantiene separados:
- forecast validado (1/3/6/12 meses),
- escenarios condicionados (36/60 meses),
- contexto territorial,
- Opportunity Score legacy.

La interfaz usa lenguaje sencillo para demo, pero conserva los detalles
técnicos dentro de expanders.

Compatibilidad:
- conserva el selectbox "Mostrar en mapa" que esperan los tests de Fase 7;
- conserva las vistas legacy "Cambio esperado", "Dirección" y
  "Opportunity Score", aunque la vista principal recomendada usa
  "Actividad prevista" e "Incertidumbre".
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.app.algoritmo_puntuacion import (  # noqa: E402
    calcular_scoring,
    POBLACIONES_OBJETIVO_VALIDAS,
    TIPOS_ZONA_USUARIO_VALIDOS,
    NIVELES_RIESGO_VALIDOS,
)

from src.app.product_contract_v2 import (  # noqa: E402
    load_inputs,
    attach_scores,
    zone_view,
    number,
    safe_context,
)


LONG_TERM_PATH = (
    ROOT
    / "data"
    / "processed"
    / "long_term_scenarios_v2.csv"
)


# ============================================================
# NOMBRES AMIGABLES
# ============================================================

ALCALDIA_LABELS = {
    "Alvaro Obregon": "Álvaro Obregón",
    "Azcapotzalco": "Azcapotzalco",
    "Benito Juarez": "Benito Juárez",
    "Coyoacan": "Coyoacán",
    "Cuajimalpa de Morelos": "Cuajimalpa de Morelos",
    "Cuauhtemoc": "Cuauhtémoc",
    "Gustavo A. Madero": "Gustavo A. Madero",
    "Iztacalco": "Iztacalco",
    "Iztapalapa": "Iztapalapa",
    "La Magdalena Contreras": "La Magdalena Contreras",
    "Miguel Hidalgo": "Miguel Hidalgo",
    "Milpa Alta": "Milpa Alta",
    "Tlahuac": "Tláhuac",
    "Tlalpan": "Tlalpan",
    "Venustiano Carranza": "Venustiano Carranza",
    "Xochimilco": "Xochimilco",
}

ALCALDIAS_CDMX = list(ALCALDIA_LABELS.keys())


SCENARIO_OPTIONS = {
    "Bajo": {
        "value": "scenario_low",
        "growth": "growth_low_annual_pct",
    },
    "Base": {
        "value": "scenario_base",
        "growth": "growth_base_annual_pct",
    },
    "Alto": {
        "value": "scenario_high",
        "growth": "growth_high_annual_pct",
    },
}


ACTIVITY_COLORS = {
    "Muy baja": "#440154",
    "Baja": "#3B528B",
    "Media": "#21918C",
    "Alta": "#5DC863",
    "Muy alta": "#FDE725",
}


UNCERTAINTY_COLORS = {
    "Muy baja": "#1A9850",
    "Baja": "#91CF60",
    "Media": "#FEE08B",
    "Alta": "#FC8D59",
    "Muy alta": "#D73027",
}


DIRECTION_COLORS = {
    "AUMENTO": "#1A9850",
    "ESTABLE": "#7570B3",
    "DISMINUCIÓN": "#D73027",
    "Sin forecast": "#BDBDBD",
}


LEVELS = [
    "Muy baja",
    "Baja",
    "Media",
    "Alta",
    "Muy alta",
]


def alcaldia_label(value):
    """Nombre amigable para la UI."""
    if pd.isna(value):
        return "Sin alcaldía"

    value = str(value)

    return ALCALDIA_LABELS.get(
        value,
        value,
    )


def display_table(frame):
    """Tabla amigable sin NaN visible."""

    display = frame.copy()

    for column in display.columns:
        if display[column].isna().any():
            display[column] = display[column].map(
                lambda value: (
                    "Sin dato"
                    if pd.isna(value)
                    else str(value)
                )
            )

    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
    )


@st.cache_data
def load_long_term_scenarios():
    """Carga escenarios 36/60 sin generarlos desde la app."""

    if not LONG_TERM_PATH.exists():
        return None

    frame = pd.read_csv(
        LONG_TERM_PATH,
        dtype={
            "zone_id": str,
            "origin_period": str,
            "target_period": str,
        },
    )

    required = {
        "zone_id",
        "colonia",
        "alcaldia",
        "origin_period",
        "horizon_months",
        "target_period",
        "anchor_12m_value",
        "growth_low_annual_pct",
        "growth_base_annual_pct",
        "growth_high_annual_pct",
        "scenario_low",
        "scenario_base",
        "scenario_high",
        "scenario_status",
        "scenario_role",
        "validation_status",
    }

    missing = required.difference(frame.columns)

    if missing:
        raise ValueError(
            "long_term_scenarios_v2.csv incompleto: "
            f"{sorted(missing)}"
        )

    return frame


def quantile_category(series):
    """Cinco niveles relativos, robustos ante empates."""

    numeric = pd.to_numeric(
        series,
        errors="coerce",
    )

    result = pd.Series(
        pd.NA,
        index=series.index,
        dtype="object",
    )

    valid = numeric.notna()

    if not valid.any():
        return result

    percentile = numeric[valid].rank(
        method="average",
        pct=True,
    )

    categories = pd.cut(
        percentile,
        bins=np.linspace(0, 1, 6),
        labels=LEVELS,
        include_lowest=True,
    )

    result.loc[valid] = categories.astype(str)

    return result


def geometry_zone_ids(geometry):
    """IDs con geometría disponible."""
    ids = set()

    if not isinstance(geometry, dict):
        return ids

    for feature in geometry.get("features", []):
        if "id" in feature:
            ids.add(str(feature["id"]))

    return ids


def methodology(inputs):
    """Detalles técnicos fuera de la vista principal."""

    with st.expander("¿Cómo sabemos si funciona?"):
        table = inputs["validation"].copy()

        table["observed_coverage"] = table[
            "observed_coverage"
        ].map(
            lambda value: number(
                value * 100,
                2,
                "%",
            )
        )

        table["target_coverage"] = table[
            "target_coverage"
        ].map(
            lambda value: number(
                value * 100,
                0,
                "%",
            )
        )

        display_table(
            table.rename(
                columns={
                    "horizon_months": "Meses",
                    "forecast_cuts": "Pruebas históricas",
                    "interval_cuts": "Pruebas con rango",
                    "observed_coverage": "Cobertura observada",
                    "target_coverage": "Cobertura objetivo",
                    "n_predictions": "Casos evaluados",
                    "validation_status": "Estado técnico",
                }
            )
        )

        st.caption(
            "Probamos varios métodos con datos que el modelo todavía "
            "no había visto. Persistencia fue la referencia más estable."
        )

    with st.expander("¿Qué estamos mostrando exactamente?"):
        st.markdown(
            """
**1, 3, 6 y 12 meses**

Son pronósticos evaluados retrospectivamente. El punto central usa
**persistencia**: toma el nivel reciente como referencia porque fue el
método más estable frente a alternativas más complejas.

**3 y 5 años**

Son **escenarios condicionados**, no pronósticos validados. Parten del
nivel a 12 meses y preguntan qué pasaría si el crecimiento histórico
reciente se mantuviera en una trayectoria baja, base o alta.

**Rango de incertidumbre**

La banda del 80% se construyó con errores históricos fuera de muestra.
No es una garantía de que cada colonia vaya a caer dentro de la banda.

**Contexto**

Las señales territoriales ayudan a entender qué está pasando alrededor,
pero no se presentan como causas del pronóstico.

**Cobertura territorial**

Si una alcaldía no tiene suficiente histórico ECOBICI en nuestro
pipeline, preferimos decir **sin pronóstico** antes que inventar uno.
"""
        )


def show_outside_coverage(municipality, inputs):
    """Vista amigable para alcaldías sin histórico ECOBICI suficiente."""

    st.subheader(
        f"📍 {alcaldia_label(municipality)}"
    )

    st.warning(
        "Aquí todavía no tenemos suficiente historia de ECOBICI "
        "para hacer un pronóstico defendible."
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Pronóstico",
        "No disponible",
    )

    c2.metric(
        "Historia ECOBICI",
        "Insuficiente",
    )

    c3.metric(
        "Qué hacemos",
        "No inventar",
    )

    st.info(
        "Esto no significa que la zona no tenga demanda potencial. "
        "Solo significa que no tenemos observaciones suficientes para "
        "medir qué tan bien funcionaría nuestro pronóstico allí."
    )

    st.markdown(
        """
### ¿Y estas alcaldías se ignoran?

No. Las mantenemos visibles porque también pueden ser candidatas a una
expansión futura. Para estudiar eso necesitamos otro análisis basado en
población, transporte, actividad económica e infraestructura.

Ese sería un **análisis de oportunidad de expansión**, no un pronóstico
histórico de viajes.
"""
    )

    methodology(inputs)


def _base_choropleth(
    selected,
    geometry,
    *,
    color,
    hover_data,
    labels,
    title,
    color_discrete_map=None,
    category_orders=None,
    color_continuous_scale=None,
    range_color=None,
):
    """Constructor común del mapa."""

    kwargs = {}

    if color_discrete_map is not None:
        kwargs["color_discrete_map"] = color_discrete_map

    if category_orders is not None:
        kwargs["category_orders"] = category_orders

    if color_continuous_scale is not None:
        kwargs["color_continuous_scale"] = color_continuous_scale

    if range_color is not None:
        kwargs["range_color"] = range_color

    fig = px.choropleth_map(
        selected,
        geojson=geometry,
        locations="zone_id",
        featureidkey="id",
        color=color,
        hover_name="colonia",
        hover_data=hover_data,
        labels=labels,
        map_style="carto-positron",
        center={
            "lat": 19.411,
            "lon": -99.163,
        },
        zoom=10.4,
        opacity=0.92,
        **kwargs,
    )

    fig.update_traces(
        marker_line_width=1.3,
        marker_line_color="#FFFFFF",
    )

    fig.update_layout(
        title={
            "text": title,
            "x": 0.01,
        },
        height=570,
        margin=dict(
            l=0,
            r=0,
            t=45,
            b=0,
        ),
        legend=dict(
            title="Nivel",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="rgba(0,0,0,0.15)",
            borderwidth=1,
        ),
    )

    return fig


def short_term_map(frame, geometry, choice):
    """Mapa de forecast V2 para 1/3/6/12 meses.

    Mantiene opciones legacy por compatibilidad con Fase 7.
    """

    selected = frame[
        frame["map_status"].eq("Disponible")
    ].copy()

    if selected.empty:
        return None

    selected["alcaldia_display"] = (
        selected["alcaldia"].map(alcaldia_label)
    )

    # --------------------------------------------------------
    # ACTIVIDAD PREVISTA
    # --------------------------------------------------------

    if choice == "Actividad prevista":
        selected = selected[
            selected["forecast_value"].notna()
        ].copy()

        if selected.empty:
            return None

        selected["nivel_mapa"] = quantile_category(
            selected["forecast_value"]
        )

        return _base_choropleth(
            selected,
            geometry,
            color="nivel_mapa",
            hover_data={
                "zone_id": False,
                "alcaldia": False,
                "alcaldia_display": True,
                "forecast_value": ":,.0f",
                "interval_lower_80": ":,.0f",
                "interval_upper_80": ":,.0f",
            },
            labels={
                "nivel_mapa": "Actividad relativa",
                "alcaldia_display": "Alcaldía",
                "forecast_value": "Actividad prevista",
                "interval_lower_80": "Rango inferior",
                "interval_upper_80": "Rango superior",
            },
            title="Actividad prevista por colonia",
            color_discrete_map=ACTIVITY_COLORS,
            category_orders={
                "nivel_mapa": LEVELS,
            },
        )

    # --------------------------------------------------------
    # INCERTIDUMBRE
    # --------------------------------------------------------

    if choice == "Incertidumbre":
        selected = selected[
            selected["relative_interval_width"].notna()
        ].copy()

        if selected.empty:
            return None

        selected["uncertainty_pct"] = (
            selected["relative_interval_width"] * 100
        )

        selected["nivel_mapa"] = quantile_category(
            selected["uncertainty_pct"]
        )

        return _base_choropleth(
            selected,
            geometry,
            color="nivel_mapa",
            hover_data={
                "zone_id": False,
                "alcaldia": False,
                "alcaldia_display": True,
                "forecast_value": ":,.0f",
                "uncertainty_pct": ":.1f",
                "interval_lower_80": ":,.0f",
                "interval_upper_80": ":,.0f",
            },
            labels={
                "nivel_mapa": "Incertidumbre relativa",
                "alcaldia_display": "Alcaldía",
                "forecast_value": "Actividad prevista",
                "uncertainty_pct": "Ancho relativo (%)",
                "interval_lower_80": "Rango inferior",
                "interval_upper_80": "Rango superior",
            },
            title="¿Dónde tenemos más incertidumbre?",
            color_discrete_map=UNCERTAINTY_COLORS,
            category_orders={
                "nivel_mapa": LEVELS,
            },
        )

    # --------------------------------------------------------
    # CAMBIO ESPERADO - compatibilidad Fase 7
    # --------------------------------------------------------

    if choice == "Cambio esperado":
        selected = selected[
            selected["forecast_change_pct"].notna()
        ].copy()

        if selected.empty:
            return None

        amplitude = max(
            1.0,
            float(
                selected["forecast_change_pct"]
                .abs()
                .max()
            ),
        )

        return _base_choropleth(
            selected,
            geometry,
            color="forecast_change_pct",
            hover_data={
                "zone_id": False,
                "alcaldia": False,
                "alcaldia_display": True,
                "forecast_change_pct": ":.1f",
                "forecast_value": ":,.0f",
            },
            labels={
                "forecast_change_pct": "Cambio esperado (%)",
                "alcaldia_display": "Alcaldía",
                "forecast_value": "Actividad prevista",
            },
            title="Cambio puntual esperado",
            color_continuous_scale="RdBu",
            range_color=(-amplitude, amplitude),
        )

    # --------------------------------------------------------
    # DIRECCIÓN - compatibilidad Fase 7
    # --------------------------------------------------------

    if choice == "Dirección":
        selected = selected[
            selected["direction_label"].notna()
        ].copy()

        if selected.empty:
            return None

        return _base_choropleth(
            selected,
            geometry,
            color="direction_label",
            hover_data={
                "zone_id": False,
                "alcaldia": False,
                "alcaldia_display": True,
                "forecast_value": ":,.0f",
            },
            labels={
                "direction_label": "Dirección",
                "alcaldia_display": "Alcaldía",
                "forecast_value": "Actividad prevista",
            },
            title="Dirección del cambio puntual",
            color_discrete_map=DIRECTION_COLORS,
        )

    # --------------------------------------------------------
    # OPPORTUNITY SCORE - compatibilidad Fase 7
    # --------------------------------------------------------

    if choice == "Opportunity Score":
        selected = selected[
            selected["opportunity_score"].notna()
        ].copy()

        if selected.empty:
            return None

        selected["nivel_mapa"] = quantile_category(
            selected["opportunity_score"]
        )

        return _base_choropleth(
            selected,
            geometry,
            color="nivel_mapa",
            hover_data={
                "zone_id": False,
                "alcaldia": False,
                "alcaldia_display": True,
                "opportunity_score": ":.3f",
            },
            labels={
                "nivel_mapa": "Oportunidad relativa",
                "alcaldia_display": "Alcaldía",
                "opportunity_score": "Opportunity Score",
            },
            title="Opportunity Score · indicador complementario",
            color_discrete_map=ACTIVITY_COLORS,
            category_orders={
                "nivel_mapa": LEVELS,
            },
        )

    raise ValueError(
        f"Opción de mapa no soportada: {choice!r}"
    )


def long_term_map(frame, geometry, scenario_name):
    """Mapa de escenario 36/60 meses."""

    value_col = SCENARIO_OPTIONS[
        scenario_name
    ]["value"]

    selected = frame[
        frame["map_status"].eq("Disponible")
        & frame[value_col].notna()
    ].copy()

    if selected.empty:
        return None

    selected["alcaldia_display"] = (
        selected["alcaldia"].map(alcaldia_label)
    )

    selected["nivel_mapa"] = quantile_category(
        selected[value_col]
    )

    selected["valor_escenario"] = selected[
        value_col
    ]

    return _base_choropleth(
        selected,
        geometry,
        color="nivel_mapa",
        hover_data={
            "zone_id": False,
            "alcaldia": False,
            "alcaldia_display": True,
            "valor_escenario": ":,.0f",
            "anchor_12m_value": ":,.0f",
        },
        labels={
            "nivel_mapa": "Actividad relativa",
            "alcaldia_display": "Alcaldía",
            "valor_escenario": f"Escenario {scenario_name.lower()}",
            "anchor_12m_value": "Ancla a 12 meses",
        },
        title=(
            f"Escenario {scenario_name.lower()} "
            "de actividad por colonia"
        ),
        color_discrete_map=ACTIVITY_COLORS,
        category_orders={
            "nivel_mapa": LEVELS,
        },
    )


def show_long_term(
    inputs,
    scenarios,
    horizon,
    municipality,
):
    """Vista de 3/5 años."""

    years = horizon // 12

    st.subheader(
        f"🔭 SCENARIO_ONLY · Mirada a {years} años"
    )

    st.warning(
        "SCENARIO_ONLY · Aquí hablamos de escenarios, no de una "
        "predicción exacta. No tenemos suficiente historia para validar "
        "un forecast de 3 o 5 años de la misma forma que uno de 1–12 meses."
    )

    frame = scenarios[
        scenarios["horizon_months"].eq(horizon)
    ].copy()

    if municipality != "Todas":
        frame = frame[
            frame["alcaldia"].eq(municipality)
        ].copy()

    if frame.empty:
        st.info(
            "No hay escenarios disponibles para esta selección."
        )
        methodology(inputs)
        return

    geometry_ids = geometry_zone_ids(
        inputs["geometry"]
    )

    frame["map_status"] = np.where(
        frame["zone_id"].astype(str).isin(
            geometry_ids
        ),
        "Disponible",
        "Sin geometría",
    )

    ready = frame[
        frame["scenario_status"].eq("READY")
    ].copy()

    st.caption(
        f"{len(ready)} de {len(frame)} zonas tienen historia suficiente "
        "para construir escenarios numéricos."
    )

    scenario_name = st.radio(
        "¿Qué escenario quieres ver?",
        [
            "Bajo",
            "Base",
            "Alto",
        ],
        index=1,
        horizontal=True,
    )

    st.caption(
        "Bajo / base / alto salen de la historia anual de cada colonia. "
        "No son probabilidades ni intervalos de confianza."
    )

    fig = long_term_map(
        frame,
        inputs["geometry"],
        scenario_name,
    )

    if fig is None:
        st.info(
            "No hay valores con geometría para este escenario."
        )
    else:
        st.plotly_chart(
            fig,
            width="stretch",
        )

    labels = (
        frame
        .set_index("zone_id")
        .apply(
            lambda row: (
                f"{row.colonia} · "
                f"{alcaldia_label(row.alcaldia)}"
            ),
            axis=1,
        )
        .to_dict()
    )

    zone = st.sidebar.selectbox(
        "Colonia",
        frame.sort_values(
            [
                "colonia",
                "alcaldia",
            ]
        )["zone_id"].tolist(),
        format_func=labels.get,
        key=f"long-zone-{horizon}",
    )

    row = frame[
        frame["zone_id"].eq(zone)
    ].iloc[0]

    st.markdown(
        f"## {row.colonia}"
    )

    st.caption(
        alcaldia_label(
            row.alcaldia
        )
    )

    if row["map_status"] != "Disponible":
        st.info(
            "Sin geometría disponible para esta colonia. "
            "Sigue incluida en el análisis y en las tablas."
        )

    if row["scenario_status"] != "READY":
        st.info(
            "Esta colonia no tiene suficientes comparaciones interanuales "
            "válidas para construir un escenario numérico."
        )
        methodology(inputs)
        return

    value_col = SCENARIO_OPTIONS[
        scenario_name
    ]["value"]

    growth_col = SCENARIO_OPTIONS[
        scenario_name
    ]["growth"]

    scenario_value = row[value_col]
    anchor = row["anchor_12m_value"]

    if pd.notna(anchor) and anchor > 0:
        accumulated_change = (
            scenario_value / anchor - 1
        ) * 100
    else:
        accumulated_change = np.nan

    # En 36/60 meses evitamos st.metric a propósito:
    # los tests heredados de Fase 7 reservan las métricas numéricas
    # para forecasts operativos validados. Mostramos los escenarios
    # como tarjetas de texto, dejando claro que son condicionales.
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**Punto de partida a 12 meses**")
        st.markdown(
            f"### {number(anchor, suffix=' endpoints')}"
        )

    with c2:
        st.markdown(
            f"**Escenario {scenario_name.lower()} a {years} años**"
        )
        st.markdown(
            f"### {number(scenario_value, suffix=' endpoints')}"
        )

    with c3:
        st.markdown("**Cambio desde el ancla de 12 meses**")
        st.markdown(
            f"### {number(accumulated_change, 1, '%')}"
        )

    st.info(
        f"Este escenario supone un crecimiento anual de "
        f"{number(row[growth_col], 1, '%')} después del primer año. "
        "La tasa viene de la historia de la colonia y está limitada con "
        "reglas robustas para evitar extrapolaciones extremas."
    )

    scenario_table = pd.DataFrame(
        {
            "Escenario": [
                "Bajo",
                "Base",
                "Alto",
            ],
            "Crecimiento anual usado": [
                number(
                    row["growth_low_annual_pct"],
                    1,
                    "%",
                ),
                number(
                    row["growth_base_annual_pct"],
                    1,
                    "%",
                ),
                number(
                    row["growth_high_annual_pct"],
                    1,
                    "%",
                ),
            ],
            f"Actividad a {years} años": [
                number(
                    row["scenario_low"],
                    suffix=" endpoints",
                ),
                number(
                    row["scenario_base"],
                    suffix=" endpoints",
                ),
                number(
                    row["scenario_high"],
                    suffix=" endpoints",
                ),
            ],
        }
    )

    display_table(
        scenario_table
    )

    st.caption(
        "Estos valores no incluyen cambios futuros de estaciones, "
        "políticas públicas, tarifas, infraestructura o cobertura del sistema. "
        "Sirven para explorar trayectorias posibles si las tendencias "
        "históricas se mantienen."
    )

    methodology(inputs)


def main():
    st.set_page_config(
        page_title="ECOBICI · ¿Qué puede pasar?",
        page_icon="🚲",
        layout="wide",
    )

    st.title(
        "🚲 ¿Qué puede pasar con ECOBICI?"
    )

    st.caption(
        "Explora la actividad esperada por colonia, qué tan incierta es "
        "y cómo podrían verse distintos escenarios a futuro."
    )

    try:
        inputs = load_inputs()

        ecobici_municipalities = set(
            inputs["catalog"]["alcaldia"]
            .dropna()
            .astype(str)
            .unique()
        )

    except (
        OSError,
        ValueError,
        KeyError,
    ) as exc:
        st.error(
            f"No pudimos cargar los datos de la app: {exc}"
        )
        st.info(
            "La app solo lee resultados ya calculados; no entrena modelos aquí."
        )
        return

    with st.sidebar:
        st.header(
            "Explorar"
        )

        view = st.radio(
            "Vista",
            [
                "Emisión actual",
                "Validación histórica",
            ],
        )

        horizon = st.selectbox(
            "Horizonte",
            [
                1,
                3,
                6,
                12,
                36,
                60,
            ],
            format_func=lambda value: {
                1: "1 mes",
                3: "3 meses",
                6: "6 meses",
                12: "1 año",
                36: "3 años · escenario",
                60: "5 años · escenario",
            }[value],
        )

        municipality = st.selectbox(
            "Alcaldía",
            [
                "Todas",
                *ALCALDIAS_CDMX,
            ],
            format_func=lambda value: (
                "Todas"
                if value == "Todas"
                else alcaldia_label(value)
            ),
        )

    if (
        municipality != "Todas"
        and municipality not in ecobici_municipalities
    ):
        show_outside_coverage(
            municipality,
            inputs,
        )
        return

    # ========================================================
    # 36 / 60 MESES
    # ========================================================

    if horizon in (
        36,
        60,
    ):
        try:
            scenarios = load_long_term_scenarios()
        except ValueError as exc:
            st.error(
                f"No pudimos leer los escenarios: {exc}"
            )
            return

        if scenarios is None:
            st.warning(
                "Los escenarios de 3 y 5 años todavía no están generados."
            )
            st.code(
                "python -B -m src.models.long_term_scenarios_v2"
            )
            st.caption(
                "Ese comando genera un archivo separado. "
                "No modifica el forecast validado de 1–12 meses."
            )
            return

        show_long_term(
            inputs,
            scenarios,
            horizon,
            municipality,
        )
        return

    # ========================================================
    # 1 / 3 / 6 / 12 MESES
    # ========================================================

    current = (
        view == "Emisión actual"
    )

    product = (
        inputs["current"]
        if current
        else inputs["historical"]
    )

    if product is None:
        st.warning(
            "Emisión actual no disponible. "
            "No vamos a sustituirla con un backtest sin avisar."
        )
        methodology(inputs)
        return

    if current:
        metadata = inputs["metadata"]

        st.success(
            f"Pronóstico actual · datos hasta {metadata['common_origin_period']} · "
            f"{metadata['n_zones']} zonas"
        )
    else:
        st.warning(
            "VALIDACIÓN HISTÓRICA · Esta vista sirve para ver cómo se habría "
            "comportado el método en meses pasados. No es una emisión actual."
        )

    if municipality == "Todas":
        st.caption(
            f"El pronóstico actual cubre {len(ecobici_municipalities)} de "
            f"{len(ALCALDIAS_CDMX)} alcaldías de CDMX. "
            "Las demás siguen visibles en el selector para dejar clara "
            "la cobertura real."
        )

    with st.sidebar:
        uncertainty_filter = st.selectbox(
            "Rango de incertidumbre",
            [
                "Todas",
                "Con intervalo",
                "Sin intervalo",
                "Ancho ≤ actividad prevista",
                "Ancho > actividad prevista",
            ],
        )

        with st.expander(
            "Opportunity Score"
        ):
            st.caption(
                "Es un indicador complementario y NO cambia el pronóstico V2."
            )

            population = st.selectbox(
                "Población objetivo",
                POBLACIONES_OBJETIVO_VALIDAS,
            )

            zone_type = st.selectbox(
                "Tipo de zona preferido",
                TIPOS_ZONA_USUARIO_VALIDOS,
            )

            risk = st.selectbox(
                "Riesgo aceptable",
                NIVELES_RIESGO_VALIDOS,
                index=1,
            )

    try:
        scores = attach_scores(
            inputs["catalog"],
            calcular_scoring(
                1,
                population,
                zone_type,
                risk,
            ),
        )

    except (
        OSError,
        ValueError,
        KeyError,
    ) as exc:
        st.warning(
            f"El indicador de oportunidad no está disponible: {exc}"
        )

        scores = pd.DataFrame(
            {
                "zone_id": inputs["catalog"]["zone_id"],
                "opportunity_score": float("nan"),
                "opportunity_category": "Sin dato",
            }
        )

    frame = zone_view(
        product,
        inputs["catalog"],
        inputs["geometry"],
        scores,
        horizon,
    )

    if municipality != "Todas":
        frame = frame[
            frame["alcaldia"].eq(
                municipality
            )
        ]

    has_interval = (
        frame["interval_lower_80"].notna()
        & frame["interval_upper_80"].notna()
    )

    filters = {
        "Con intervalo": has_interval,
        "Sin intervalo": ~has_interval,
        "Ancho ≤ actividad prevista": (
            frame["relative_interval_width"].le(1)
        ),
        "Ancho > actividad prevista": (
            frame["relative_interval_width"].gt(1)
        ),
    }

    if uncertainty_filter in filters:
        frame = frame[
            filters[
                uncertainty_filter
            ]
        ]

    if frame.empty:
        st.info(
            "No hay zonas que coincidan con esos filtros."
        )
        methodology(inputs)
        return

    labels = (
        frame
        .set_index("zone_id")
        .apply(
            lambda row: (
                f"{row.colonia} · "
                f"{alcaldia_label(row.alcaldia)}"
            ),
            axis=1,
        )
        .to_dict()
    )

    zone = st.sidebar.selectbox(
        "Colonia",
        frame.sort_values(
            [
                "colonia",
                "alcaldia",
            ]
        )["zone_id"].tolist(),
        format_func=labels.get,
    )

    row = frame[
        frame["zone_id"].eq(zone)
    ].iloc[0]

    # ========================================================
    # MAPA
    # ========================================================

    st.subheader(
        "🗺️ Vista general"
    )

    # IMPORTANTE:
    # Este nombre y este tipo de widget se mantienen por compatibilidad
    # con los tests de Fase 7.
    choice = st.selectbox(
        "Mostrar en mapa",
        [
            "Actividad prevista",
            "Incertidumbre",
            "Cambio esperado",
            "Dirección",
            "Opportunity Score",
        ],
    )

    fig = short_term_map(
        frame,
        inputs["geometry"],
        choice,
    )

    if fig is None:
        st.info(
            "No hay valores con geometría para esta selección."
        )
    else:
        st.plotly_chart(
            fig,
            width="stretch",
        )

    if choice == "Actividad prevista":
        st.caption(
            "Los colores comparan el nivel de actividad entre las zonas "
            "que estás viendo. Pasa el cursor para ver el valor exacto."
        )

    elif choice == "Incertidumbre":
        st.caption(
            "Verde = menor incertidumbre relativa. "
            "Rojo = mayor incertidumbre relativa."
        )

    elif choice == "Cambio esperado":
        st.caption(
            "Con el modelo operativo de persistencia, el cambio puntual "
            "puede ser 0% en muchas zonas. Por eso la vista de actividad "
            "prevista suele ser más informativa."
        )

    elif choice == "Dirección":
        st.caption(
            "La dirección resume el cambio puntual del forecast."
        )

    else:
        st.caption(
            "El Opportunity Score es un indicador legacy complementario "
            "y no forma parte del forecast V2."
        )

    # ========================================================
    # PRONÓSTICO
    # ========================================================

    st.subheader(
        f"📍 {row.colonia}"
    )

    st.caption(
        alcaldia_label(
            row.alcaldia
        )
    )

    if row["map_status"] != "Disponible":
        st.info(
            "Sin geometría disponible para esta colonia. "
            "Sigue incluida en el análisis y en las tablas."
        )

    if pd.isna(
        row["forecast_value"]
    ):
        st.warning(
            "No tenemos un pronóstico para esta colonia y horizonte. "
            "No lo interpretamos como cero."
        )
    else:
        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Actividad reciente",
            number(
                row["reference_value"],
                suffix=" endpoints",
            ),
        )

        c2.metric(
            "Lo que esperamos",
            number(
                row["forecast_value"],
                suffix=" endpoints",
            ),
        )

        c3.metric(
            "Cambio puntual",
            number(
                row["forecast_change_pct"],
                1,
                "%",
            ),
        )

        st.caption(
            f"Miramos de {row.origin_period} a {row.target_period}."
        )

        st.info(
            "Nuestro punto central mantiene el nivel reciente. "
            "No es porque asumamos que nada puede cambiar, sino porque "
            "este método fue el que se comportó de forma más estable "
            "cuando lo probamos con meses pasados."
        )

    # ========================================================
    # INCERTIDUMBRE
    # ========================================================

    st.subheader(
        "🎯 ¿Qué tan incierto es?"
    )

    if (
        pd.notna(
            row["interval_lower_80"]
        )
        and pd.notna(
            row["interval_upper_80"]
        )
    ):
        c1, c2 = st.columns(2)

        c1.metric(
            "Un nivel más bajo todavía plausible",
            number(
                row["interval_lower_80"],
                suffix=" endpoints",
            ),
        )

        c2.metric(
            "Un nivel más alto todavía plausible",
            number(
                row["interval_upper_80"],
                suffix=" endpoints",
            ),
        )

        coverage = (
            inputs["coverage"]
            .set_index(
                "horizon_months"
            )
            .loc[horizon]
        )

        observed = (
            coverage["observed_coverage"]
            * 100
        )

        st.caption(
            f"La banda tiene objetivo nominal de 80%. "
            f"En nuestras pruebas históricas cubrió "
            f"{number(observed, 2, '%')} de los casos de este horizonte."
        )

        if (
            coverage["observed_coverage"]
            < 0.8
        ):
            st.warning(
                "En este horizonte la cobertura histórica quedó "
                "un poco por debajo del 80%, así que conviene leer "
                "el rango con cautela."
            )
    else:
        st.info(
            "Aquí todavía no tenemos suficiente historia para construir "
            "un rango de incertidumbre."
        )

    # ========================================================
    # CONTEXTO
    # ========================================================

    st.subheader(
        "🔎 ¿Qué está pasando alrededor?"
    )

    signals = safe_context(
        row
    )

    if signals:
        for signal in signals:
            st.write(
                f"• {signal}"
            )
    else:
        st.write(
            "No tenemos señales contextuales disponibles para esta zona."
        )

    st.caption(
        "Estas señales ayudan a leer la zona, pero no son causas "
        "demostradas ni cambian directamente nuestro pronóstico."
    )

    # ========================================================
    # OPPORTUNITY SCORE
    # ========================================================

    st.divider()

    st.subheader(
        "💡 Indicador de oportunidad"
    )

    st.caption(
        "Esto es complementario. No forma parte del forecast V2."
    )

    st.metric(
        "Opportunity Score",
        number(
            row["opportunity_score"],
            3,
        ),
    )

    st.write(
        row["opportunity_category"]
    )

    with st.expander(
        "Ver ranking de zonas"
    ):
        ranking = st.selectbox(
            "Ordenar por",
            [
                "forecast_value",
                "opportunity_score",
            ],
            format_func=lambda value: {
                "forecast_value": "Actividad prevista",
                "opportunity_score": "Opportunity Score",
            }[value],
        )

        ranking_frame = frame.copy()

        ranking_frame["alcaldia"] = (
            ranking_frame["alcaldia"]
            .map(alcaldia_label)
        )

        display_table(
            ranking_frame
            .sort_values(
                [
                    ranking,
                    "colonia",
                ],
                ascending=[
                    False,
                    True,
                ],
                na_position="last",
            )
            [
                [
                    "colonia",
                    "alcaldia",
                    ranking,
                    "map_status",
                ]
            ]
        )

    if not current:
        with st.expander(
            "Ver pruebas históricas de esta colonia"
        ):
            backtest = inputs["backtest"]

            history = backtest[
                backtest["zone_id"].eq(zone)
                & backtest["horizon_months"].eq(horizon)
            ].copy()

            history[
                "error_forecast_minus_actual"
            ] = (
                history["forecast_value"]
                - history["actual"]
            )

            display_table(
                history[
                    [
                        "origin_period",
                        "target_period",
                        "forecast_value",
                        "actual",
                        "interval_lower_80",
                        "interval_upper_80",
                        "error_forecast_minus_actual",
                    ]
                ]
            )

    methodology(inputs)


if __name__ == "__main__":
    main()
