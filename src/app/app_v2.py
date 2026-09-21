"""App ECOBICI: actividad observada y mapas a 1, 3 y 5 años.

La interfaz pública tiene dos páginas y solo lee los artefactos procesados.
Las funciones analíticas heredadas permanecen aquí para compatibilidad, pero
no añaden controles ni explicaciones técnicas a las dos páginas visibles.
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
from src.app.ux_signals_v2 import (  # noqa: E402
    MAP_EXPLANATIONS, SCENARIO_EXPLANATIONS, LONG_MAP_EXPLANATIONS,
    observed_trend, scenario_display,
)
from src.app import ui_v2 as ui  # noqa: E402
from src.app.ui_v2 import (  # noqa: E402
    LEVELS,
    ACTIVITY_COLORS,
    UNCERTAINTY_COLORS,
    SCENARIO_COLORS,
    OPPORTUNITY_COLORS,
    TREND_COLORS,
    DIRECTION_COLORS,
    DIVERGING_SCALE,
)


# ============================================================
# CONSTANTES DE INTERFAZ
# ============================================================

SHORT_HORIZONS = (1, 3, 6, 12)
LONG_HORIZONS = (36, 60)

HORIZON_LABELS = {
    1: "1 mes",
    3: "3 meses",
    6: "6 meses",
    12: "12 meses",
    36: "3 años",
    60: "5 años",
}

VIEW_OPTIONS = ["Emisión actual", "Validación histórica"]

PRIMARY_MAPS = ("Actividad prevista", "Incertidumbre", "Tendencia reciente")
DEFAULT_MAP = "Actividad prevista"

UNCERTAINTY_FILTERS = [
    "Todas",
    "Con intervalo",
    "Sin intervalo",
    "Ancho ≤ actividad prevista",
    "Ancho > actividad prevista",
]

ZONE_KEY = "zone-id"          # colonia elegida (compartida entre secciones)
MAP_HEIGHT = 560              # alto útil del mapa en laptop (1440 × 900)
SCENARIO_TAG = "Escenario condicionado · no forecast validado"

TAGLINE = "Explora la actividad actual y cómo podría cambiar por colonia."
UNIT_HELP = (
    "**Endpoints mensuales** = inicios + finales de viajes de ECOBICI "
    "registrados dentro de una colonia durante un mes. Un viaje que "
    "empieza en una colonia y termina en otra cuenta una vez en cada una."
)

MAP_NOTES = {
    "Actividad prevista": (
        "Los colores comparan las colonias visibles en cinco niveles "
        "(quintiles): más oscuro = más actividad prevista."
    ),
    "Incertidumbre": (
        "Más oscuro = rango de incertidumbre relativamente más ancho. "
        "Compara colonias entre sí; no es una probabilidad."
    ),
    "Tendencia reciente": (
        "Historia observada, no predicción. Compara con el mismo mes del año "
        "previo: más de +5% sube, menos de −5% baja, entre ambos estable."
    ),
    "Cambio esperado": (
        "Con el modelo de persistencia el cambio puntual puede ser 0% en "
        "muchas zonas; la vista de actividad prevista suele ser más informativa."
    ),
    "Dirección": "La dirección resume el cambio puntual del forecast.",
    "Opportunity Score": (
        "Indicador complementario. No forma parte del forecast, no es una "
        "probabilidad ni una recomendación definitiva."
    ),
}


# ============================================================
# ESTADO DE LOS SELECTORES DE MAPA (compatibilidad Fase 7)
# ============================================================

def choose_primary_map():
    """Selector visible (segmented) → selector completo ('Mostrar en mapa')."""
    value = st.session_state.get("primary-map-choice")
    if value is None:
        # Se volvió a pulsar la opción activa: conservar la vista actual.
        current = st.session_state.get("short-map-choice", DEFAULT_MAP)
        st.session_state["primary-map-choice"] = (
            current if current in PRIMARY_MAPS else None
        )
        return
    st.session_state["short-map-choice"] = value


def choose_secondary_map():
    """Selector completo → selector visible (queda vacío en vistas técnicas)."""
    choice = st.session_state["short-map-choice"]
    st.session_state["primary-map-choice"] = (
        choice if choice in PRIMARY_MAPS else None
    )


def init_map_state():
    default = DEFAULT_MAP if DEFAULT_MAP in MAP_EXPLANATIONS else next(iter(MAP_EXPLANATIONS))
    if "short-map-choice" not in st.session_state:
        st.session_state["short-map-choice"] = default
    if "primary-map-choice" not in st.session_state:
        choice = st.session_state["short-map-choice"]
        st.session_state["primary-map-choice"] = choice if choice in PRIMARY_MAPS else None


def pick_zone_from_map(chart_key):
    """Callback de clic en el mapa → colonia seleccionada.

    Se ejecuta antes del script en la siguiente corrida, así puede
    escribir la selección sin chocar con los widgets ya creados.
    """
    def _callback():
        try:
            points = st.session_state[chart_key]["selection"]["points"]
            if not points:
                return
            zone = points[0].get("location")
            if zone is None:
                custom = points[0].get("customdata") or []
                zone = custom[0] if custom else None
            if zone is not None:
                st.session_state[ZONE_KEY] = str(zone)
        except (KeyError, TypeError, IndexError, AttributeError):
            return
    return _callback


def pick_zone_from_table(table_key):
    """Callback de clic en una fila del ranking → colonia seleccionada."""
    def _callback():
        try:
            rows = st.session_state[table_key]["selection"]["rows"]
            ids = st.session_state.get(f"{table_key}-ids", [])
            if rows and rows[0] < len(ids):
                st.session_state[ZONE_KEY] = str(ids[rows[0]])
        except (KeyError, TypeError, IndexError, AttributeError):
            return
    return _callback


@st.cache_data
def load_observed_history():
    return pd.read_csv(ROOT / "data/processed/panel_demanda_v2.csv", usecols=[
        "zone_id", "periodo", "viajes_total", "data_status", "target_available_no_earlier_than"])


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
        "traffic_target": "traffic_low_target_congestion_pct",
        "traffic_adjustment": "traffic_low_adjustment_pct",
        "traffic_change": "traffic_low_change_pp_per_year",
    },
    "Base": {
        "value": "scenario_base",
        "growth": "growth_base_annual_pct",
        "traffic_target": "traffic_base_target_congestion_pct",
        "traffic_adjustment": "traffic_base_adjustment_pct",
        "traffic_change": "traffic_base_change_pp_per_year",
    },
    "Alto": {
        "value": "scenario_high",
        "growth": "growth_high_annual_pct",
        "traffic_target": "traffic_high_target_congestion_pct",
        "traffic_adjustment": "traffic_high_adjustment_pct",
        "traffic_change": "traffic_high_change_pp_per_year",
    },
}


def alcaldia_label(value):
    """Nombre amigable para la UI."""
    if pd.isna(value):
        return "Sin alcaldía"

    value = str(value)

    return ALCALDIA_LABELS.get(
        value,
        value,
    )


def signed_pct(value, digits=1):
    """Porcentaje con signo explícito (+8.3%, −3.2%)."""
    if value is None or pd.isna(value):
        return "Sin dato"
    return f"{float(value):+.{digits}f}%"


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
        "tomtom_enabled",
        "tomtom_latest_year",
        "tomtom_congestion_pct",
        "tomtom_recent_change_pp",
        "traffic_low_target_congestion_pct",
        "traffic_base_target_congestion_pct",
        "traffic_high_target_congestion_pct",
        "traffic_low_adjustment_pct",
        "traffic_base_adjustment_pct",
        "traffic_high_adjustment_pct",
        "traffic_low_change_pp_per_year",
        "traffic_base_change_pp_per_year",
        "traffic_high_change_pp_per_year",
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


# ============================================================
# VALIDACIÓN Y METODOLOGÍA
# ============================================================

def validation_metrics(inputs):
    """MAE y RMSE por horizonte, sin inventar nada.

    1) Si el artefacto de validación ya trae columnas mae/rmse, las usa.
    2) Si no, las calcula a partir de las pruebas retrospectivas
       (pronóstico − real) que la app ya carga en inputs["backtest"].

    Devuelve (DataFrame indexado por horizon_months | None, origen).
    """
    try:
        validation = inputs["validation"]
        lowered = {str(c).lower(): c for c in validation.columns}
        mae_col = next((lowered[c] for c in ("mae", "mean_absolute_error") if c in lowered), None)
        rmse_col = next((lowered[c] for c in ("rmse", "root_mean_squared_error") if c in lowered), None)
        if mae_col and rmse_col:
            out = validation[["horizon_months", mae_col, rmse_col]].rename(
                columns={mae_col: "mae", rmse_col: "rmse"}
            )
            return out.set_index("horizon_months"), "artefacto de validación"

        backtest = inputs["backtest"][["horizon_months", "forecast_value", "actual"]].dropna()
        backtest = backtest.assign(error=backtest["forecast_value"] - backtest["actual"])
        grouped = backtest.groupby("horizon_months")["error"]
        out = pd.DataFrame({
            "mae": grouped.apply(lambda s: s.abs().mean()),
            "rmse": grouped.apply(lambda s: float(np.sqrt((s ** 2).mean()))),
        })
        return out, "pruebas retrospectivas (pronóstico − real)"
    except (KeyError, ValueError, TypeError):
        return None, None


def methodology(inputs):
    """Detalles técnicos fuera de la vista principal."""

    with st.expander("¿Cómo sabemos si funciona?", icon=":material/fact_check:"):
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

    with st.expander("¿Qué estamos mostrando exactamente?", icon=":material/help:"):
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

Además incorporamos **TomTom Traffic Index** como stress factor de tráfico.
No suponemos que más tráfico cause automáticamente más viajes en ECOBICI:
el ajuste es una sensibilidad explícita del escenario. La señal actual es
citywide, así que cambia niveles pero no crea diferencias entre colonias.

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


def show_outside_coverage(municipality, inputs, horizon=1):
    """Vista amigable para alcaldías sin histórico ECOBICI suficiente."""

    st.subheader(alcaldia_label(municipality), anchor=False)

    ui.notice(
        "warning",
        "Cobertura insuficiente",
        "Aquí todavía no tenemos suficiente historia de ECOBICI "
        "para hacer un pronóstico defendible.",
    )

    with st.container(border=True):
        for column, label in zip(st.columns(3), ("Actividad", "Historia ECOBICI", "Tendencia reciente")):
            column.markdown(f"**{label}**\n\nSin dato")

    st.info(
        "Esto no significa que la zona no tenga demanda potencial. "
        "Solo significa que no tenemos observaciones suficientes para "
        "medir qué tan bien funcionaría nuestro pronóstico allí.",
        icon=":material/info:",
    )

    st.markdown(
        """
##### ¿Y estas alcaldías se ignoran?

No. Las mantenemos visibles porque también pueden ser candidatas a una
expansión futura. Para estudiar eso necesitamos otro análisis basado en
población, transporte, actividad económica e infraestructura.

Ese sería un **análisis de oportunidad de expansión**, no un pronóstico
histórico de viajes.
"""
    )


# ============================================================
# MAPAS
# ============================================================

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
    highlight_zone=None,
    height=MAP_HEIGHT,
    tag=None,
    zoom=10.4,
):
    """Constructor común del mapa (estilo en ui.style_map)."""

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
        zoom=zoom,
        opacity=0.92,
        **kwargs,
    )

    ui.style_map(
        fig,
        title=title,
        height=height,
        tag=tag,
        continuous=color_continuous_scale is not None,
    )
    ui.add_zone_highlight(fig, geometry, highlight_zone)

    return fig


def short_term_map(frame, geometry, choice, *, highlight_zone=None, height=MAP_HEIGHT):
    """Mapa de forecast V2 para 1/3/6/12 meses.

    Mantiene opciones legacy por compatibilidad con Fase 7.
    """

    common = dict(highlight_zone=highlight_zone, height=height)

    selected = frame[
        frame["map_status"].eq("Disponible")
    ].copy()

    if selected.empty:
        return None

    selected["alcaldia_display"] = (
        selected["alcaldia"].map(alcaldia_label)
    )

    if choice == "Tendencia reciente":
        selected["trend_display"] = selected.trend_pct.map(lambda v: number(v, 1, "%"))
        return _base_choropleth(
            selected, geometry, color="trend_category",
            hover_data={"zone_id": False, "alcaldia_display": True, "trend_display": True,
                        "origin_period": True, "trend_comparison_period": True},
            labels={"trend_category": "Tendencia observada", "trend_display": "Cambio interanual",
                    "alcaldia_display": "Alcaldía", "origin_period": "Mes observado",
                    "trend_comparison_period": "Mismo mes del año anterior"},
            title="Tendencia reciente · historia observada",
            color_discrete_map=TREND_COLORS,
            category_orders={"trend_category": ["Subiendo", "Estable", "Bajando", "Sin dato"]},
            **common)

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
            **common,
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
            **common,
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
            color_continuous_scale=DIVERGING_SCALE,
            range_color=(-amplitude, amplitude),
            **common,
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
            **common,
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
            color_discrete_map=OPPORTUNITY_COLORS,
            category_orders={
                "nivel_mapa": LEVELS,
            },
            **common,
        )

    raise ValueError(
        f"Opción de mapa no soportada: {choice!r}"
    )


def long_term_map(frame, geometry, scenario_name, choice="Actividad del escenario",
                  *, highlight_zone=None, height=MAP_HEIGHT):
    """Mapa de escenario 36/60 meses (siempre etiquetado como escenario)."""

    common = dict(highlight_zone=highlight_zone, height=height, tag=SCENARIO_TAG)

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

    selected = scenario_display(selected, scenario_name)
    if choice == "Dirección del escenario":
        selected["change_display"] = selected.scenario_change_pct.map(lambda v: number(v, 1, "%"))
        return _base_choropleth(
            selected, geometry, color="scenario_direction",
            hover_data={"zone_id": False, "alcaldia_display": True, "change_display": True},
            labels={"scenario_direction": "Dirección del escenario", "alcaldia_display": "Alcaldía",
                    "change_display": "Cambio vs. ancla"}, title="Dirección del escenario · regla ±5%",
            color_discrete_map=DIRECTION_COLORS, **common)
    if choice in ("Cambio vs. ancla", "Aporte TomTom"):
        column = "scenario_change_pct" if choice == "Cambio vs. ancla" else "selected_traffic_adjustment_pct"
        selected = selected[np.isfinite(selected[column])].copy()
        if selected.empty:
            return None
        limit = max(1.0, selected[column].abs().max())
        return _base_choropleth(
            selected, geometry, color=column,
            hover_data={"zone_id": False, "alcaldia_display": True, column: ":.2f"},
            labels={column: f"{choice} (%)", "alcaldia_display": "Alcaldía"},
            title=f"{choice} · escenario {scenario_name.lower()}",
            color_continuous_scale=DIVERGING_SCALE, range_color=(-limit, limit), **common)

    selected["nivel_mapa"] = quantile_category(
        selected[value_col]
    )

    selected["valor_escenario"] = selected[
        value_col
    ]

    traffic_adjustment_col = SCENARIO_OPTIONS[
        scenario_name
    ]["traffic_adjustment"]

    selected["ajuste_trafico_pct"] = selected[
        traffic_adjustment_col
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
            "ajuste_trafico_pct": ":.2f",
        },
        labels={
            "nivel_mapa": "Actividad relativa",
            "alcaldia_display": "Alcaldía",
            "valor_escenario": f"Escenario {scenario_name.lower()}",
            "anchor_12m_value": "Ancla a 12 meses",
            "ajuste_trafico_pct": "Ajuste TomTom (%)",
        },
        title=(
            f"Escenario {scenario_name.lower()} "
            "de actividad por colonia"
        ),
        color_discrete_map=SCENARIO_COLORS,
        category_orders={
            "nivel_mapa": LEVELS,
        },
        **common,
    )


def render_map(fig, key):
    """Dibuja el mapa; un clic en una colonia la selecciona."""
    st.plotly_chart(
        fig,
        key=key,
        width="stretch",
        on_select=pick_zone_from_map(key),
        selection_mode="points",
        config={"displaylogo": False, "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
    )


# ============================================================
# COMPONENTES DE PÁGINA
# ============================================================

def render_header(inputs, ecobici_municipalities):
    """Encabezado compacto: nombre, propósito, periodo y cobertura."""
    metadata = inputs.get("metadata") or {}
    origin = metadata.get("common_origin_period", "sin dato")
    n_zones = len(geometry_zone_ids(inputs["geometry"]))

    left, right = st.columns([3, 2], vertical_alignment="center", gap="small")
    with left:
        st.title("¿Qué puede pasar con ECOBICI?", anchor=False)
        st.caption(TAGLINE)
    with right:
        with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
            st.badge(f"Datos hasta {origin}", icon=":material/event:", color="gray",
                     help="Último mes observado que alimenta el pronóstico actual.")
            coverage = f"{n_zones} colonias en mapa · {len(ecobici_municipalities)} alcaldías"
            st.badge(coverage, icon=":material/map:", color="gray",
                     help="Solo se colorean las colonias con contorno disponible.")


def default_zone(frame):
    """Colonia inicial: la de mayor actividad prevista con geometría.

    Solo cambia qué colonia se muestra al abrir; no toca ningún cálculo.
    """
    ordered = frame.sort_values(["colonia", "alcaldia"])
    value_column = "map_value" if "map_value" in ordered else "forecast_value"
    if value_column in ordered and ordered[value_column].notna().any():
        drawable = ordered[ordered["map_status"].eq("Disponible")] if "map_status" in ordered else ordered
        pool = drawable if drawable[value_column].notna().any() else ordered
        return pool.loc[pool[value_column].idxmax(), "zone_id"]
    return ordered["zone_id"].iloc[0]


def zone_selector(container, frame, *, widget_key):
    """Selector de colonia con selección compartida entre secciones."""
    ordered = frame.sort_values(["colonia", "alcaldia"])
    options = ordered["zone_id"].tolist()
    labels = {
        row.zone_id: f"{row.colonia} · {alcaldia_label(row.alcaldia)}"
        for row in ordered.itertuples()
    }

    current = st.session_state.get(ZONE_KEY)
    if current not in options:
        current = default_zone(frame)
    st.session_state[widget_key] = current

    def _sync():
        st.session_state[ZONE_KEY] = st.session_state[widget_key]

    with container:
        zone = st.selectbox(
            "Colonia",
            options,
            format_func=labels.get,
            key=widget_key,
            on_change=_sync,
            help="También puedes elegirla con un clic en el mapa.",
        )
    st.session_state[ZONE_KEY] = zone
    return zone


def disabled_zone_selector(container, placeholder):
    with container:
        st.selectbox("Colonia", [], disabled=True, placeholder=placeholder,
                     key="zone-disabled")


def uncertainty_note(inputs, horizon):
    """Cobertura histórica observada del intervalo (lógica original)."""
    try:
        coverage = inputs["coverage"].set_index("horizon_months").loc[horizon]
        return float(coverage["observed_coverage"])
    except (KeyError, ValueError, TypeError):
        return None


def colony_narrative(row):
    """Explicación en lenguaje natural, solo con campos existentes."""
    if pd.isna(row["forecast_value"]):
        return (
            "No tenemos un pronóstico para esta colonia y horizonte. "
            "No lo interpretamos como cero."
        )
    text = (
        f"Para **{row['target_period']}** esperamos alrededor de "
        f"**{number(row['forecast_value'])} endpoints** en {row['colonia']}"
    )
    if pd.notna(row["interval_lower_80"]) and pd.notna(row["interval_upper_80"]):
        text += (
            f", con un rango del 80% entre {number(row['interval_lower_80'])} "
            f"y {number(row['interval_upper_80'])}"
        )
    text += "."
    trend = row.get("trend_category")
    verbs = {"Subiendo": "subiendo", "Estable": "estable", "Bajando": "bajando"}
    if trend in verbs:
        text += (
            f" La actividad observada venía **{verbs[trend]}** "
            f"({signed_pct(row['trend_pct'])} frente al mismo mes del año anterior)."
        )
    level = row.get("uncertainty_level")
    if isinstance(level, str) and level in LEVELS:
        text += (
            f" Su incertidumbre relativa es **{level.lower()}** "
            "frente a las demás colonias visibles."
        )
    return text


def uncertainty_card(row, inputs, horizon):
    """¿Qué tan incierto es? Rango visual + cómo leerlo + advertencias."""
    st.markdown("**¿Qué tan incierto es?**")

    has_interval = pd.notna(row["interval_lower_80"]) and pd.notna(row["interval_upper_80"])
    if not has_interval or pd.isna(row["forecast_value"]):
        ui.notice(
            "info",
            "Sin rango de incertidumbre",
            "Aquí todavía no tenemos suficiente historia para construir "
            "un rango de incertidumbre.",
        )
        return

    ui.range_bar(
        row["interval_lower_80"], row["forecast_value"], row["interval_upper_80"],
        fmt=number,
    )

    rel = row.get("relative_interval_width")
    level = row.get("uncertainty_level")
    parts = []
    if pd.notna(rel):
        parts.append(f"Ancho relativo: **{number(rel * 100, 0, '%')}** de la actividad prevista")
    if isinstance(level, str) and level in LEVELS:
        parts.append(f"incertidumbre relativa **{level.lower()}** entre las colonias visibles")
    if parts:
        st.markdown(" · ".join(parts))

    observed = uncertainty_note(inputs, horizon)
    if observed is not None:
        st.caption(
            "Cómo leerlo: la franja es un rango con objetivo de 80%. "
            f"En nuestras pruebas históricas a {HORIZON_LABELS.get(horizon, horizon)} "
            f"cubrió {number(observed * 100, 1, '%')} de los casos."
        )
        if observed < 0.8:
            ui.notice(
                "warning",
                "Lee este rango con cautela",
                "En este horizonte la cobertura histórica quedó un poco por "
                "debajo del 80%.",
            )


def colony_summary_card(row, inputs, horizon):
    """Resumen de colonia en pocos segundos (panel lateral del Panorama)."""
    with st.container(border=True):
        st.subheader(row["colonia"], anchor=False)
        st.caption(
            f"{alcaldia_label(row['alcaldia'])} · "
            f"{row['origin_period'] if pd.notna(row['origin_period']) else 'sin dato'} → "
            f"{row['target_period'] if pd.notna(row['target_period']) else 'sin dato'}"
        )

        if row["map_status"] != "Disponible":
            st.caption("Sin geometría disponible: sigue incluida en el análisis y en las tablas.")

        if pd.isna(row["forecast_value"]):
            ui.notice(
                "warning",
                "Sin pronóstico para esta colonia",
                "No tenemos un pronóstico para esta colonia y horizonte. "
                "No lo interpretamos como cero.",
            )
            return

        m1, m2 = st.columns(2)
        m1.metric(
            "Actividad prevista",
            number(row["forecast_value"]),
            help="Punto central del pronóstico, en endpoints mensuales.",
        )
        m2.metric(
            "Actividad reciente",
            number(row["reference_value"]),
            help="Endpoints del mes observado más reciente.",
        )

        ui.range_bar(
            row["interval_lower_80"], row["forecast_value"], row["interval_upper_80"], fmt=number,
        ) or ui.notice("info", "Sin rango de incertidumbre",
                       "Aquí todavía no tenemos suficiente historia para construir un rango.")

        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            ui.trend_badge(
                row["trend_category"] if pd.notna(row["trend_category"]) else "Sin dato",
                label=f"Tendencia: {row['trend_category'] if pd.notna(row['trend_category']) else 'Sin dato'}",
            )
            st.caption(f"{signed_pct(row['trend_pct'])} interanual · historia observada")

        st.markdown(colony_narrative(row))


def ranking_table(frame, *, by, limit, key, show_map_status=False):
    """Ranking seleccionable: un clic en una fila elige la colonia."""
    work = frame[frame[by].notna()].copy()
    work = work.sort_values([by, "colonia"], ascending=[False, True], na_position="last")
    if limit:
        work = work.head(limit)

    if work.empty:
        ui.notice("info", "Sin datos para ordenar", "Ninguna colonia visible tiene este indicador.")
        return

    st.session_state[f"{key}-ids"] = work["zone_id"].tolist()

    table = pd.DataFrame({
        "Colonia": work["colonia"].values,
        "Alcaldía": work["alcaldia"].map(alcaldia_label).values,
    })
    if by == "forecast_value":
        table["Actividad prevista"] = work["forecast_value"].values
        table["Rango 80%"] = [
            f"{number(lo)} – {number(hi)}" if pd.notna(lo) and pd.notna(hi) else "Sin rango"
            for lo, hi in zip(work["interval_lower_80"], work["interval_upper_80"])
        ]
        table["Tendencia"] = [
            f"{ui.TREND_GLYPH.get(t, '·')} {t}" if isinstance(t, str) else "· Sin dato"
            for t in work["trend_category"]
        ]
        top = float(work["forecast_value"].max()) or 1.0
        config = {"Actividad prevista": st.column_config.ProgressColumn(
            "Actividad prevista", format="localized", min_value=0, max_value=top)}
    else:
        table["Opportunity Score"] = work["opportunity_score"].values
        table["Categoría"] = work["opportunity_category"].fillna("Sin dato").values
        config = {"Opportunity Score": st.column_config.NumberColumn("Opportunity Score", format="%.3f")}
    if show_map_status:
        table["Mapa"] = work["map_status"].values

    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=min(420, 36 * (len(table) + 1) + 4),
        column_config=config,
        key=key,
        on_select=pick_zone_from_table(key),
        selection_mode="single-row",
    )


def ranking_panel(frame, *, limit, key, title="Colonias con mayor actividad prevista"):
    """Ranking con selector de criterio (mismas opciones que la versión original)."""
    st.markdown(f"**{title}**")
    by = st.segmented_control(
        "Ordenar por",
        ["forecast_value", "opportunity_score"],
        format_func={"forecast_value": "Actividad prevista",
                     "opportunity_score": "Opportunity Score"}.get,
        default="forecast_value",
        required=True,
        key=f"{key}-by",
        persist_state="session",
    )
    if by == "opportunity_score":
        st.caption("Indicador complementario: no forma parte del forecast ni es una recomendación definitiva.")
    ranking_table(frame, by=by, limit=limit, key=key, show_map_status=limit is None)
    st.caption("Haz clic en una fila para ver esa colonia.")


# ============================================================
# FILTROS + CONTEXTO POR SECCIÓN
# ============================================================

def prepare_short_context(ctx):
    """Barra de filtros + datos de las secciones de corto plazo.

    Devuelve True si hay datos suficientes para dibujar la página.
    Conserva el pipeline original: scores → zone_view → tendencia →
    filtro de alcaldía → filtro de incertidumbre.
    """
    inputs = ctx["inputs"]
    ecobici = ctx["ecobici"]

    c_view, c_horizon, c_alc, c_zone = st.columns([1.5, 1.35, 1.05, 1.5], vertical_alignment="bottom", gap="small")

    with c_view:
        view = st.segmented_control(
            "Vista", VIEW_OPTIONS, default=VIEW_OPTIONS[0], required=True,
            key="f-view", persist_state="session", width="stretch",
            help="Emisión actual: pronóstico vigente. Validación histórica: cómo se habría comportado el método en meses pasados.",
        )
    with c_horizon:
        horizon = st.segmented_control(
            "Horizonte", list(SHORT_HORIZONS), format_func=HORIZON_LABELS.get,
            default=SHORT_HORIZONS[0], required=True, key="f-horizon",
            persist_state="session", width="stretch",
            help="Forecast validado retrospectivamente a 1, 3, 6 y 12 meses.",
        )
    with c_alc:
        municipality = st.selectbox(
            "Alcaldía", ["Todas", *ALCALDIAS_CDMX],
            format_func=lambda v: "Todas" if v == "Todas" else alcaldia_label(v),
            key="f-alcaldia", persist_state="session",
        )

    with st.expander("Filtros avanzados", icon=":material/tune:"):
        a1, a2, a3, a4 = st.columns(4)
        uncertainty_filter = a1.selectbox(
            "Rango de incertidumbre", UNCERTAINTY_FILTERS,
            key="f-uncertainty", persist_state="session",
        )
        population = a2.selectbox(
            "Población objetivo", POBLACIONES_OBJETIVO_VALIDAS,
            key="f-population", persist_state="session",
        )
        zone_type = a3.selectbox(
            "Tipo de zona preferido", TIPOS_ZONA_USUARIO_VALIDOS,
            key="f-zone-type", persist_state="session",
        )
        risk = a4.selectbox(
            "Riesgo aceptable", NIVELES_RIESGO_VALIDOS, index=1,
            key="f-risk", persist_state="session",
        )
        st.caption(
            "Los tres últimos parámetros solo afectan al Opportunity Score, "
            "un indicador complementario que NO cambia el pronóstico V2."
        )

    current = view == VIEW_OPTIONS[0]
    ctx.update(view=view, current=current, horizon=horizon, municipality=municipality)

    if municipality != "Todas" and municipality not in ecobici:
        disabled_zone_selector(c_zone, "Sin cobertura ECOBICI")
        show_outside_coverage(municipality, inputs, horizon)
        return False

    product = inputs["current"] if current else inputs["historical"]

    if product is None:
        disabled_zone_selector(c_zone, "Sin emisión actual")
        ui.notice(
            "warning",
            "Emisión actual no disponible",
            "No vamos a sustituirla con un backtest sin avisar. "
            "Puedes cambiar a “Validación histórica” en la barra de filtros.",
        )
        st.page_link(ctx["pages"]["validacion"], label="Ver validación y metodología",
                     icon=":material/verified:")
        return False

    with st.spinner("Preparando el mapa…"):
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
        except (OSError, ValueError, KeyError) as exc:
            st.warning(
                f"El indicador de oportunidad no está disponible: {exc}",
                icon=":material/warning:",
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
        try:
            trends = observed_trend(load_observed_history(), frame[["zone_id", "origin_period"]])
            frame = frame.merge(trends, on=["zone_id", "origin_period"], how="left", validate="one_to_one")
        except (OSError, ValueError, KeyError) as exc:
            st.warning(f"Tendencia reciente no disponible: {exc}", icon=":material/warning:")
            frame["trend_pct"] = np.nan
            frame["trend_category"] = "Sin dato"
            frame["trend_comparison_period"] = None

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
        disabled_zone_selector(c_zone, "Sin colonias para estos filtros")
        ui.notice(
            "info",
            "No hay zonas que coincidan con esos filtros",
            "Prueba con otra alcaldía o restablece “Rango de incertidumbre” a “Todas” "
            "en Filtros avanzados.",
        )
        return False

    frame = frame.copy()
    # Mismo agrupamiento por quintiles que usa el mapa de incertidumbre.
    frame["uncertainty_level"] = quantile_category(frame["relative_interval_width"])

    zone = zone_selector(c_zone, frame, widget_key="zone-pick-short")
    row = frame[frame["zone_id"].eq(zone)].iloc[0]

    if current:
        detail = (
            f"Datos hasta {(inputs.get('metadata') or {}).get('common_origin_period', 'sin dato')} · "
            f"{HORIZON_LABELS[horizon]} adelante · punto central por persistencia"
        )
        kind = "validated"
    else:
        detail = (
            "Muestra cómo se habría comportado el método en meses pasados. "
            "No es una emisión actual."
        )
        kind = "historical"
    ui.mode_banner(kind, detail, trailing=lambda: st.popover(
        "¿Qué es un endpoint?", icon=":material/help:", type="tertiary").markdown(UNIT_HELP))

    ctx.update(frame=frame, zone=zone, row=row)
    return True


def prepare_scenario_context(ctx):
    """Barra de filtros + datos de la sección de escenarios (36/60 meses)."""
    inputs = ctx["inputs"]
    ecobici = ctx["ecobici"]

    c_horizon, c_scenario, c_alc, c_zone = st.columns([1.1, 1.4, 1.1, 1.5], vertical_alignment="bottom", gap="small")

    with c_horizon:
        horizon = st.segmented_control(
            "Horizonte", list(LONG_HORIZONS), format_func=HORIZON_LABELS.get,
            default=LONG_HORIZONS[0], required=True, key="f-horizon-long",
            persist_state="session", width="stretch",
            help="Escenarios condicionados a 3 y 5 años. No son forecast validado.",
        )
    with c_scenario:
        scenario_name = st.segmented_control(
            "¿Qué escenario quieres ver?", list(SCENARIO_OPTIONS), default="Base", required=True,
            key="f-scenario", persist_state="session", width="stretch",
            help="Bajo, base y alto salen de la historia anual de cada colonia. No son probabilidades ni intervalos de confianza.",
        )
    with c_alc:
        municipality = st.selectbox(
            "Alcaldía", ["Todas", *ALCALDIAS_CDMX],
            format_func=lambda v: "Todas" if v == "Todas" else alcaldia_label(v),
            key="f-alcaldia", persist_state="session",
        )

    ctx.update(horizon=horizon, scenario_name=scenario_name, municipality=municipality)

    if municipality != "Todas" and municipality not in ecobici:
        disabled_zone_selector(c_zone, "Sin cobertura ECOBICI")
        show_outside_coverage(municipality, inputs, horizon)
        return False

    try:
        scenarios = load_long_term_scenarios()
    except ValueError as exc:
        disabled_zone_selector(c_zone, "Escenarios no disponibles")
        ui.notice("error", "No pudimos leer los escenarios", str(exc))
        return False

    if scenarios is None:
        disabled_zone_selector(c_zone, "Escenarios no generados")
        ui.notice(
            "warning",
            "Los escenarios de 3 y 5 años todavía no están generados",
            "Ese comando genera un archivo separado. No modifica el forecast "
            "validado de 1–12 meses.",
        )
        st.code("python -B -m src.models.long_term_scenarios_v2")
        return False

    frame = scenarios[scenarios["horizon_months"].eq(horizon)].copy()
    if municipality != "Todas":
        frame = frame[frame["alcaldia"].eq(municipality)].copy()

    if frame.empty:
        disabled_zone_selector(c_zone, "Sin escenarios")
        ui.notice("info", "No hay escenarios disponibles para esta selección",
                  "Prueba con otra alcaldía.")
        return False

    geometry_ids = geometry_zone_ids(inputs["geometry"])
    frame["map_status"] = np.where(
        frame["zone_id"].astype(str).isin(geometry_ids), "Disponible", "Sin geometría",
    )
    frame = scenario_display(frame, scenario_name)

    zone = zone_selector(c_zone, frame, widget_key="zone-pick-long")
    row = frame[frame["zone_id"].eq(zone)].iloc[0]

    ui.mode_banner(
        "scenario",
        "No son predicciones ni probabilidades: muestran qué pasaría si el "
        "crecimiento histórico y una hipótesis de tráfico se mantuvieran.",
    )
    ctx.update(scenarios=scenarios, frame=frame, zone=zone, row=row)
    return True


# ============================================================
# PÁGINA 1 · PANORAMA
# ============================================================

def page_panorama(ctx):
    inputs, frame, horizon, row = ctx["inputs"], ctx["frame"], ctx["horizon"], ctx["row"]

    init_map_state()
    map_col, side_col = st.columns([2.05, 1], gap="medium")

    with map_col:
        c_var, c_more = st.columns([3.3, 1], vertical_alignment="bottom", gap="small")
        with c_var:
            st.segmented_control(
                "Variable del mapa", list(PRIMARY_MAPS), key="primary-map-choice",
                on_change=choose_primary_map, persist_state="session", width="stretch",
                help="Elige qué quieres ver en el mapa.",
            )
        with c_more:
            with st.popover("Más vistas", icon=":material/layers:", width="stretch"):
                st.caption(
                    "Vistas técnicas y complementarias. Cambio esperado y Dirección "
                    "describen el punto central de persistencia; Opportunity Score "
                    "es independiente del forecast."
                )
                # Mismo selectbox y etiqueta que esperan los tests de Fase 7.
                st.selectbox(
                    "Mostrar en mapa", list(MAP_EXPLANATIONS), key="short-map-choice",
                    on_change=choose_secondary_map, persist_state="session",
                )
        choice = st.session_state["short-map-choice"]
        st.caption(f"{MAP_EXPLANATIONS[choice]} {MAP_NOTES.get(choice, '')} Haz clic en una colonia para ver su resumen.")

        fig = short_term_map(frame, inputs["geometry"], choice, highlight_zone=ctx["zone"])
        if fig is None:
            ui.notice("info", "No hay valores con geometría para esta selección",
                      "Prueba con otra variable del mapa o con otros filtros.")
        else:
            render_map(fig, "map-panorama")

    with side_col:
        n_zones = len(frame)
        with_forecast = int(frame["forecast_value"].notna().sum())
        with_interval = int((frame["interval_lower_80"].notna() & frame["interval_upper_80"].notna()).sum())
        total = frame["forecast_value"].sum(min_count=1)
        with st.container(border=True):
            k1, k2 = st.columns(2)
            k1.metric(
                "Actividad prevista total", number(total),
                help="Suma de endpoints mensuales previstos en las colonias visibles.",
            )
            k2.metric(
                "Colonias con pronóstico", f"{with_forecast:,} de {n_zones:,}",
                help=f"{with_interval:,} de ellas tienen rango de incertidumbre al 80%.",
            )
            st.caption("Tendencia reciente de las colonias (historia observada)")
            counts = frame["trend_category"].fillna("Sin dato").value_counts()
            ui.share_bar([(name, int(counts.get(name, 0))) for name in ("Subiendo", "Estable", "Bajando", "Sin dato")])
        colony_summary_card(row, inputs, horizon)

    rank_col, next_col = st.columns([2.05, 1], gap="medium")
    with rank_col:
        ranking_panel(frame, limit=8, key="rank-panorama")
    with next_col:
        with st.container(border=True):
            st.badge("Otra pregunta", icon=":material/timeline:", color="violet")
            st.markdown("**¿Y a 3 o 5 años?**")
            st.caption(
                "Explora escenarios condicionados. Son un ejercicio distinto del "
                "forecast validado: no son predicciones ni probabilidades."
            )
            st.page_link(ctx["pages"]["escenarios"], label="Ver escenarios",
                         icon=":material/arrow_forward:")
        st.page_link(ctx["pages"]["validacion"], label="¿Qué tan confiable es el pronóstico?",
                     icon=":material/verified:")


# ============================================================
# PÁGINA 2 · EXPLORAR COLONIAS
# ============================================================

def page_explorar(ctx):
    inputs, frame, horizon, row = ctx["inputs"], ctx["frame"], ctx["horizon"], ctx["row"]

    st.header(row["colonia"], anchor=False)
    period = (
        f"{row['origin_period']} → {row['target_period']}"
        if pd.notna(row["origin_period"]) and pd.notna(row["target_period"]) else "sin periodo"
    )
    st.caption(f"{alcaldia_label(row['alcaldia'])} · Miramos de {period} · {HORIZON_LABELS[horizon]}")

    if row["map_status"] != "Disponible":
        st.info("Sin geometría disponible para esta colonia. Sigue incluida en el análisis y en las tablas.",
                icon=":material/info:")

    left, right = st.columns([1.2, 1], gap="large")

    with left:
        st.markdown(colony_narrative(row))

        if pd.isna(row["forecast_value"]):
            ui.notice(
                "warning",
                "Sin pronóstico para esta colonia",
                "No tenemos un pronóstico para esta colonia y horizonte. No lo interpretamos como cero.",
            )
            st.markdown("**Actividad reciente / prevista / incertidumbre: Sin dato**")
        else:
            with st.container(border=True):
                m1, m2, m3 = st.columns(3)
                m1.metric("Actividad reciente", number(row["reference_value"], suffix=" endpoints"),
                          help="Endpoints del mes observado más reciente.")
                m2.metric("Actividad prevista", number(row["forecast_value"], suffix=" endpoints"),
                          help="Punto central del pronóstico (persistencia).")
                trend = row["trend_category"] if pd.notna(row["trend_category"]) else "Sin dato"
                m3.metric("Tendencia reciente · historia observada", trend,
                          icon=ui.TREND_META.get(trend, ui.TREND_META["Sin dato"])[0],
                          help="Historia observada frente al mismo mes del año anterior. No es una predicción.")
                st.caption(
                    f"Cambio interanual: {number(row['trend_pct'], 1, '%')} · mes observado "
                    f"{row['origin_period'] if pd.notna(row['origin_period']) else 'Sin dato'} · referencia "
                    f"{row['trend_comparison_period'] if pd.notna(row['trend_comparison_period']) else 'Sin dato'}. "
                    "Endpoints = inicios + finales registrados en la colonia durante el mes."
                )
            with st.expander("¿Por qué el punto central mantiene el nivel reciente?", icon=":material/help:"):
                st.write(
                    "Nuestro punto central mantiene el nivel reciente. No es porque asumamos que "
                    "nada puede cambiar, sino porque este método fue el que se comportó de forma "
                    "más estable cuando lo probamos con meses pasados."
                )

        with st.container(border=True):
            uncertainty_card(row, inputs, horizon)

    with right:
        fig = short_term_map(
            frame, inputs["geometry"], st.session_state.get("short-map-choice", DEFAULT_MAP),
            highlight_zone=ctx["zone"], height=380,
        )
        if fig is not None:
            render_map(fig, "map-explorar")

        st.markdown("**¿Qué está pasando alrededor?**")
        signals = safe_context(row)
        if signals:
            for signal in signals:
                st.markdown(f"- {signal}")
        else:
            st.write("No tenemos señales contextuales disponibles para esta zona.")
        st.caption(
            "Estas señales ayudan a leer la zona, pero no son causas "
            "demostradas ni cambian directamente nuestro pronóstico."
        )

    with st.container(border=True):
        h1, h2 = st.columns([1, 3], vertical_alignment="center")
        with h1:
            st.badge("Indicador complementario", icon=":material/lightbulb:", color="gray")
        with h2:
            st.caption("Opportunity Score: no forma parte del forecast V2, no es una probabilidad "
                       "ni una recomendación definitiva.")
        o1, o2 = st.columns(2)
        o1.metric("Opportunity Score", number(row["opportunity_score"], 3))
        o2.metric("Categoría", str(row["opportunity_category"]) if pd.notna(row["opportunity_category"]) else "Sin dato")

    if not ctx["current"]:
        with st.expander("Ver pruebas históricas de esta colonia", icon=":material/history:"):
            backtest = inputs["backtest"]

            history = backtest[
                backtest["zone_id"].eq(ctx["zone"])
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

    with st.expander("Ver todas las colonias", icon=":material/table_rows:"):
        ranking_panel(frame, limit=None, key="rank-explorar", title="Ranking de colonias")

    st.page_link(ctx["pages"]["validacion"], label="Metodología y validación del pronóstico",
                 icon=":material/verified:")


# ============================================================
# PÁGINA 3 · ESCENARIOS 3 Y 5 AÑOS
# ============================================================

def scenario_chain():
    """Cómo se construye un escenario, en cuatro pasos visibles."""
    steps = [
        ("Punto de partida", "Forecast validado a 12 meses"),
        ("+ Historia ECOBICI", "Crecimiento anual bajo, base o alto"),
        ("+ Hipótesis de tráfico", "Ajuste TomTom: sensibilidad, no causa"),
        ("= Escenario", "A 3 o 5 años, condicionado"),
    ]
    with st.container(border=True):
        for column, (title, body) in zip(st.columns(4), steps):
            column.markdown(f"**{title}**")
            column.caption(body)


def page_scenarios(ctx):
    inputs, frame, row = ctx["inputs"], ctx["frame"], ctx["row"]
    horizon, scenario_name, scenarios = ctx["horizon"], ctx["scenario_name"], ctx["scenarios"]
    years = horizon // 12

    st.subheader(f"Mirada a {years} años · escenario {scenario_name.lower()}", anchor=False)
    st.caption(SCENARIO_EXPLANATIONS[scenario_name])
    scenario_chain()
    st.caption(
        "is_validated_forecast = False · No son probabilidades ni intervalos conformales. "
        "El forecast de 12 meses no desaparece: es el punto de partida."
    )

    ready = frame[frame["scenario_status"].eq("READY")]
    st.caption(
        f"{len(ready)} de {len(frame)} zonas tienen historia suficiente "
        "para construir escenarios numéricos."
    )

    map_col, side_col = st.columns([2.05, 1], gap="medium")

    with map_col:
        long_choice = st.selectbox(
            "Mostrar en mapa de escenarios", list(LONG_MAP_EXPLANATIONS),
            key="long-map-choice", persist_state="session",
        )
        st.caption(f"{LONG_MAP_EXPLANATIONS[long_choice]} Haz clic en una colonia para ver su escenario.")
        fig = long_term_map(frame, inputs["geometry"], scenario_name, long_choice, highlight_zone=ctx["zone"])
        if fig is None:
            ui.notice("info", "No hay valores con geometría para este escenario",
                      "Prueba con otro escenario o con otra alcaldía.")
        else:
            render_map(fig, "map-escenarios")

    with side_col:
        with st.container(border=True):
            st.subheader(row["colonia"], anchor=False)
            st.caption(alcaldia_label(row["alcaldia"]))

            if row["map_status"] != "Disponible":
                st.caption("Sin geometría disponible: sigue incluida en el análisis y en las tablas.")

            if row["scenario_status"] != "READY":
                ui.notice(
                    "info",
                    "Escenario numérico no disponible",
                    "Esta colonia no tiene suficientes comparaciones interanuales "
                    "válidas para construir un escenario numérico.",
                )
            else:
                cfg = SCENARIO_OPTIONS[scenario_name]
                # En 36/60 meses evitamos st.metric a propósito (ver docstring).
                ui.stat("Punto de partida · forecast a 12 meses",
                        number(row["anchor_12m_value"], suffix=" endpoints"))
                ui.stat(f"Escenario {scenario_name.lower()} a {years} años",
                        number(row[cfg["value"]], suffix=" endpoints"),
                        note="Condicionado a supuestos; no es una predicción.")
                ui.stat("Cambio desde el punto de partida",
                        signed_pct(row["scenario_change_pct"]))
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    ui.direction_badge(row["scenario_direction"])
                    st.caption("Regla de producto: ±5% desde el ancla, no una verdad estadística.")

    if row["scenario_status"] != "READY":
        st.page_link(ctx["pages"]["validacion"], label="Metodología y validación", icon=":material/verified:")
        return

    cfg = SCENARIO_OPTIONS[scenario_name]

    # ---- Comparación 3 vs 5 años (misma colonia, tres escenarios) ----
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        st.markdown("**Comparación entre 3 y 5 años**")
        rows = []
        for h in LONG_HORIZONS:
            other = scenarios[scenarios["horizon_months"].eq(h) & scenarios["zone_id"].eq(ctx["zone"])]
            if not other.empty and other.iloc[0]["scenario_status"] == "READY":
                r = other.iloc[0]
                rows.append((HORIZON_LABELS[h], {"Bajo": r["scenario_low"], "Base": r["scenario_base"], "Alto": r["scenario_high"]}))
        if rows:
            st.plotly_chart(
                ui.scenario_range_chart(rows, row["anchor_12m_value"], fmt=number),
                key="scenario-compare", width="stretch", config={"displayModeBar": False},
            )
            st.caption("Es el rango entre escenarios bajo y alto, no un intervalo de confianza.")
        else:
            st.caption("Sin escenarios numéricos comparables para esta colonia.")

    with right:
        st.markdown("**Supuestos de este escenario**")
        assumptions = pd.DataFrame({
            "Escenario": ["Bajo", "Base", "Alto"],
            "Crecimiento anual ECOBICI": [number(row[SCENARIO_OPTIONS[s]["growth"]], 1, "%") for s in ("Bajo", "Base", "Alto")],
            "Ajuste TomTom": [number(row[SCENARIO_OPTIONS[s]["traffic_adjustment"]], 2, "%") for s in ("Bajo", "Base", "Alto")],
            f"Actividad a {years} años": [number(row[SCENARIO_OPTIONS[s]["value"]], suffix=" endpoints") for s in ("Bajo", "Base", "Alto")],
        })
        display_table(assumptions)
        st.caption(
            f"El componente ECOBICI usa un crecimiento anual de {number(row[cfg['growth']], 1, '%')} "
            "después del primer año, limitado con reglas robustas para evitar extrapolaciones extremas."
        )

    with st.expander("Hipótesis de tráfico (TomTom)", icon=":material/traffic:"):
        if bool(row.get("tomtom_enabled", False)):
            t1, t2, t3 = st.columns(3)
            with t1:
                ui.stat("TomTom más reciente", number(row["tomtom_congestion_pct"], 1, "%"),
                        note=f"Año {int(row['tomtom_latest_year'])}")
            with t2:
                ui.stat(f"Tráfico en escenario {scenario_name.lower()}",
                        number(row[cfg["traffic_target"]], 1, "%"),
                        note=f"{number(row[cfg['traffic_change']], 1, ' pp/año')} · hipótesis, no dato observado")
            with t3:
                adjustment = row[cfg["traffic_adjustment"]]
                sign = "+" if adjustment > 0 else ""
                ui.stat("Ajuste sobre ECOBICI", f"{sign}{number(adjustment, 2, '%')}",
                        note="Sensibilidad del escenario")
            if row["tomtom_recent_change_pp"] < 0:
                st.caption(
                    "Dato importante: el TomTom Traffic Index más reciente bajó frente al año anterior. "
                    "Por eso no asumimos que el tráfico necesariamente crecerá: el escenario alto es un "
                    "stress case y el base mantiene la congestión."
                )
            st.info(
                "TomTom modifica el valor de 3 y 5 años como hipótesis de escenario, no como una causa "
                "demostrada. Como la señal usada aquí es citywide, cambia el nivel de los escenarios "
                "pero no el ranking espacial entre colonias por sí sola.",
                icon=":material/info:",
            )
        else:
            st.caption("Este artefacto fue generado sin ajuste TomTom.")

    st.caption(
        "Estos valores no incluyen cambios futuros de estaciones, políticas públicas, tarifas, "
        "infraestructura o cobertura del sistema. Sirven para explorar trayectorias posibles si "
        "las tendencias históricas se mantienen."
    )
    st.page_link(ctx["pages"]["validacion"], label="Metodología y validación", icon=":material/verified:")


# ============================================================
# PÁGINA 4 · VALIDACIÓN Y METODOLOGÍA
# ============================================================

def page_validation(ctx):
    inputs = ctx["inputs"]
    validation = inputs["validation"]

    st.subheader("¿Qué tan confiable es el pronóstico?", anchor=False)
    st.markdown(
        "Probamos el método con datos que todavía no había visto. El modelo operativo usa "
        "**persistencia** porque fue el más estable frente a alternativas más complejas."
    )
    ui.mode_banner("validated", "Aplica a 1, 3, 6 y 12 meses. Los escenarios de 3 y 5 años no se validan así.")

    horizons = [int(h) for h in validation["horizon_months"].tolist() if int(h) in SHORT_HORIZONS] or list(SHORT_HORIZONS)
    horizon = st.segmented_control(
        "Horizonte", horizons, format_func=HORIZON_LABELS.get, default=horizons[0], required=True,
        key="v-horizon", persist_state="session",
    )
    vrow = validation[validation["horizon_months"].eq(horizon)]
    metrics, source = validation_metrics(inputs)

    def metric_value(column):
        if metrics is None or horizon not in metrics.index:
            return "Sin dato"
        return number(metrics.loc[horizon, column], 1, " endpoints")

    with st.container(border=True):
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("MAE", metric_value("mae"),
                  help="Error absoluto medio: en promedio, cuántos endpoints se equivocó el pronóstico por colonia y mes.")
        k2.metric("RMSE", metric_value("rmse"),
                  help="Raíz del error cuadrático medio: como el MAE, pero penaliza más los errores grandes.")
        if not vrow.empty:
            k3.metric("Cobertura del intervalo", number(vrow.iloc[0]["observed_coverage"] * 100, 1, "%"),
                      help=f"Objetivo nominal: {number(vrow.iloc[0]['target_coverage'] * 100, 0, '%')}. "
                           "Porcentaje de casos reales que cayeron dentro del rango del 80%.")
            k4.metric("Cortes retrospectivos", number(vrow.iloc[0]["forecast_cuts"]),
                      help=f"{number(vrow.iloc[0]['interval_cuts'])} con rango de incertidumbre · "
                           f"{number(vrow.iloc[0]['n_predictions'])} casos evaluados.")
        else:
            k3.metric("Cobertura del intervalo", "Sin dato")
            k4.metric("Cortes retrospectivos", "Sin dato")
    if source:
        st.caption(f"MAE y RMSE calculados desde: {source}.")
    else:
        st.caption("MAE y RMSE no están disponibles en los artefactos cargados.")

    chart_col, read_col = st.columns([1.3, 1], gap="large")
    with chart_col:
        st.markdown("**¿El rango del 80% cumple lo que promete?**")
        st.plotly_chart(
            ui.coverage_chart(validation["horizon_months"], validation["observed_coverage"],
                              float(validation["target_coverage"].iloc[0])),
            key="coverage-chart", width="stretch", config={"displayModeBar": False},
        )
    with read_col:
        st.markdown("**Cómo leerlo**")
        st.markdown(
            "- **MAE y RMSE** se miden en endpoints mensuales por colonia: cuanto más bajos, mejor.\n"
            "- **Cobertura** cercana al 80% indica que el rango es honesto; por debajo, hay que leerlo con cautela.\n"
            "- **Cortes retrospectivos** son las veces que repetimos la prueba en el pasado."
        )

    methodology(inputs)

    with st.expander("Limitaciones y fuentes", icon=":material/menu_book:"):
        st.markdown(
            """
**Limitaciones**

- Los escenarios de 3 y 5 años no son pronósticos validados ni probabilidades.
- Las señales territoriales contextualizan la colonia; no demuestran causalidad.
- El Opportunity Score es un indicador complementario: no forma parte del forecast
  ni es una recomendación definitiva.
- No incluimos cambios futuros de estaciones, políticas públicas, tarifas ni infraestructura.

**Fuentes**

- Viajes de ECOBICI procesados en el pipeline del proyecto (`panel_demanda_v2`).
- TomTom Traffic Index (señal de toda la ciudad) para la sensibilidad de los escenarios.
- Señales territoriales incluidas en el catálogo de zonas.
"""
        )
        # TODO(equipo): completar con las referencias oficiales de cada fuente.


# ============================================================
# DOS VISTAS PÚBLICAS
# ============================================================

SIMPLE_HORIZONS = {12: "1 año", 36: "3 años", 60: "5 años"}
# Viridis para la demanda observada por colonia.
ACTIVITY_GRADIENT = list(px.colors.sequential.Viridis)
# Escala fija y divergente: el mismo color significa el mismo cambio en los
# tres horizontes. Morado y naranja se distinguen sin depender del rojo/verde.
CHANGE_GRADIENT = [
    (0.0, "#542788"),
    (0.29, "#8073AC"),
    (0.43, "#B2ABD2"),
    (0.5, "#D9D9D9"),
    (0.57, "#FDB863"),
    (0.71, "#E08214"),
    (1.0, "#9B4B00"),
]
CHANGE_RANGE = (-35, 35)
STATION_CATALOG = ROOT / "data/processed/ecobici_viajes_por_estacion.csv"
STATION_ACTIVITY = ROOT / "data/processed/station_activity_latest_v2.csv"
TEMPORAL_FEATURES = ROOT / "data/processed/features_temporales_v2.csv"


@st.cache_data(max_entries=1)
def load_current_station_points():
    """Coordenadas del catálogo instalado; no disponibilidad en tiempo real."""
    columns = ["num_cicloe", "calle_prin", "calle_secu", "alcaldia", "latitud", "longitud", "estatus"]
    stations = pd.read_csv(STATION_CATALOG, usecols=columns, dtype={"num_cicloe": str})
    stations["latitud"] = pd.to_numeric(stations.latitud, errors="coerce")
    stations["longitud"] = pd.to_numeric(stations.longitud, errors="coerce")
    stations = stations[
        stations.estatus.eq("Instalada")
        & stations.latitud.between(19, 20)
        & stations.longitud.between(-100, -98)
        & stations.num_cicloe.notna()
    ].drop_duplicates("num_cicloe").copy()
    return stations


@st.cache_data(max_entries=1)
def load_station_activity():
    """Último mes reconstruible por estación; distinto del mes por colonia."""
    activity = pd.read_csv(STATION_ACTIVITY, dtype={"num_cicloe": str, "periodo": str})
    required = {"num_cicloe", "periodo", "viajes_origen", "viajes_destino", "viajes_total"}
    if not required.issubset(activity.columns) or activity.num_cicloe.duplicated().any():
        raise ValueError("Actividad por estación incompleta o con IDs duplicados")
    if activity.periodo.nunique() != 1:
        raise ValueError("La actividad por estación mezcla meses")
    if not (activity.viajes_origen + activity.viajes_destino).eq(activity.viajes_total).all():
        raise ValueError("Los movimientos por estación no cuadran")
    return activity


def station_points_with_activity(stations, activity, map_period):
    """Une por ID sin inferir ceros ni transferir actividad entre estaciones."""
    if activity.periodo.iloc[0] > map_period:
        raise ValueError("La actividad por estación es posterior al mapa actual")
    return stations.merge(
        activity[["num_cicloe", "periodo", "viajes_total"]],
        on="num_cicloe", how="left", validate="one_to_one",
    )


def add_station_points(fig, stations):
    """Puntos con halo claro para leerlos sobre cualquier color del mapa."""
    if stations.empty:
        return fig
    counts = pd.to_numeric(
        stations.get("viajes_total", pd.Series(np.nan, index=stations.index)), errors="coerce",
    ).fillna(0)
    max_count = max(float(counts.max()), 1)
    sizes = 4 + 4 * np.sqrt(counts / max_count)
    coords = {"lat": stations.latitud, "lon": stations.longitud, "mode": "markers", "showlegend": False}
    fig.add_trace(go.Scattermap(
        **coords, marker={"size": sizes + 4, "color": "#FFFFFF", "opacity": 0.94},
        hoverinfo="skip",
    ))
    streets = stations.calle_prin.fillna("").astype(str)
    periods = stations.get("periodo", pd.Series(pd.NA, index=stations.index))
    details = [
        f"Movimientos registrados en {period}: {int(count):,}"
        if pd.notna(period) and count > 0 else
        f"Sin movimientos registrados en {period}"
        if pd.notna(period) else "Actividad por estación no disponible"
        for period, count in zip(periods, counts)
    ]
    fig.add_trace(go.Scattermap(
        **coords, marker={"size": sizes, "color": "#152238", "opacity": 0.9},
        text=[
            f"Estación {number}<br>{street}<br>{detail}"
            for number, street, detail in zip(stations.num_cicloe, streets, details)
        ],
        hovertemplate="%{text}<extra></extra>",
    ))
    return fig


def _mapped_catalog(inputs):
    catalog = inputs["catalog"][["zone_id", "colonia", "alcaldia"]].copy()
    return catalog[catalog.zone_id.astype(str).isin(geometry_zone_ids(inputs["geometry"]))]


@st.cache_data(max_entries=1)
def load_latest_annual_trend():
    """Crecimiento interanual observado al último mes publicado."""
    features = pd.read_csv(
        TEMPORAL_FEATURES,
        usecols=["zone_id", "periodo", "viajes_total", "growth_12"],
        dtype={"zone_id": str, "periodo": str},
    )
    latest = features.periodo.max()
    latest = features[features.periodo.eq(latest)].copy()
    if latest.zone_id.duplicated().any() or latest.growth_12.isna().any():
        raise ValueError("La tendencia interanual no está completa")
    return latest, str(latest.periodo.iloc[0])


def current_demand_frame(inputs, history):
    """Último mes observado; nunca usa un valor posterior al origen publicado."""
    origin = (inputs.get("metadata") or {}).get("common_origin_period")
    if origin is None:
        raise ValueError("No hay un mes observado disponible")
    observed = history[
        history.periodo.eq(origin)
        & history.data_status.isin(["OBSERVED", "ZERO_DEMAND"])
    ][["zone_id", "viajes_total"]].rename(columns={"viajes_total": "map_value"})
    if observed.zone_id.duplicated().any():
        raise ValueError("Hay colonias duplicadas en la actividad actual")
    frame = _mapped_catalog(inputs).merge(observed, on="zone_id", how="left", validate="one_to_one")
    frame["target_period"] = origin
    frame["map_status"] = "Disponible"
    return frame


def future_demand_frame(inputs, horizon, scenario_name, scenarios=None):
    """Une el artefacto publicado del horizonte con las colonias dibujables."""
    if horizon == 12:
        product = inputs.get("current")
        if product is None:
            return None
        selected = product[product.horizon_months.eq(12)][
            ["zone_id", "reference_value"]
        ].copy()
        trends, origin = load_latest_annual_trend()
        selected = selected.merge(trends[["zone_id", "growth_12"]], on="zone_id", how="left", validate="one_to_one")
        selected["map_value"] = (selected.reference_value * (1 + selected.growth_12)).clip(lower=0)
        selected["target_period"] = str(pd.Period(origin, freq="M") + 12)
        selected["growth_12"] = selected.growth_12
        selected = selected.drop(columns="growth_12")
    else:
        if scenarios is None:
            return None
        value_column = SCENARIO_OPTIONS[scenario_name]["value"]
        selected = scenarios[scenarios.horizon_months.eq(horizon)][
            ["zone_id", "target_period", "scenario_status", value_column]
        ].rename(columns={value_column: "map_value"})
        selected.loc[selected.scenario_status.ne("READY"), "map_value"] = np.nan
        selected = selected.drop(columns="scenario_status")
        reference = inputs["current"]
        reference = reference[reference.horizon_months.eq(12)][["zone_id", "reference_value"]]
        selected = selected.merge(reference, on="zone_id", how="left", validate="one_to_one")
    if selected.zone_id.duplicated().any():
        raise ValueError("Hay colonias duplicadas en el horizonte elegido")
    frame = _mapped_catalog(inputs).merge(selected, on="zone_id", how="left", validate="one_to_one")
    frame["map_status"] = "Disponible"
    return frame


def simple_demand_map(frame, geometry, *, title, future=False, highlight_zone=None):
    selected = frame[frame.map_value.notna()].copy()
    if selected.empty:
        return None
    selected["alcaldia_display"] = selected.alcaldia.map(alcaldia_label)
    if future:
        selected["change_pct"] = np.where(
            selected.reference_value.gt(0),
            100 * (selected.map_value / selected.reference_value - 1),
            np.nan,
        )
        return _base_choropleth(
            selected, geometry, color="change_pct",
            hover_data={
                "zone_id": False, "alcaldia": False, "alcaldia_display": True,
                "change_pct": ":+.1f", "map_value": ":,.0f", "reference_value": ":,.0f",
                "target_period": False,
            },
            labels={
                "change_pct": "Cambio vs. hoy (%)", "map_value": "Actividad estimada",
                "reference_value": "Actividad actual", "alcaldia_display": "Alcaldía",
            },
            title=title, color_continuous_scale=CHANGE_GRADIENT,
            range_color=CHANGE_RANGE, highlight_zone=highlight_zone, height=660, zoom=11.3,
        )
    return _base_choropleth(
        selected,
        geometry,
        color="map_value",
        hover_data={
            "zone_id": False,
            "alcaldia": False,
            "alcaldia_display": True,
            "map_value": ":,.0f",
            "target_period": False,
        },
        labels={
            "map_value": "Actividad estimada" if future else "Actividad registrada",
            "alcaldia_display": "Alcaldía",
        },
        title=title,
        color_continuous_scale=ACTIVITY_GRADIENT,
        highlight_zone=highlight_zone,
        height=660,
        zoom=11.3,
    )


@st.cache_data(max_entries=3)
def load_expansion_scores(horizon_years):
    """Puntaje legacy de oportunidad; no es probabilidad de apertura."""
    return calcular_scoring(horizon_years, "general", "cualquiera", "medio")


def expansion_ranking(catalog, visible_zone_ids, horizon_years):
    """Top 10 del puntaje existente, limitado a las colonias del mapa."""
    scores = attach_scores(catalog, load_expansion_scores(horizon_years))
    visible = catalog[catalog.zone_id.isin(set(visible_zone_ids))][
        ["zone_id", "colonia", "alcaldia"]
    ]
    ranked = visible.merge(
        scores[["zone_id", "opportunity_score", "opportunity_category"]],
        on="zone_id", how="left", validate="one_to_one",
    )
    ranked = ranked[ranked.opportunity_score.notna()].sort_values(
        ["opportunity_score", "colonia"], ascending=[False, True],
    ).head(10).copy()
    ranked.insert(0, "puesto", range(1, len(ranked) + 1))
    return ranked


def estimate_additional_stations(stations_now, demand_now, demand_future):
    """Regla de tres, manteniendo la demanda actual por estación.

    Se redondea el total requerido hacia arriba. Datos sin denominador válido
    permanecen sin estimación; una caída de demanda no crea estaciones nuevas.
    """
    current = pd.to_numeric(stations_now, errors="coerce")
    observed = pd.to_numeric(demand_now, errors="coerce")
    future = pd.to_numeric(demand_future, errors="coerce")
    valid = current.gt(0) & observed.gt(0) & future.ge(0)
    result = pd.Series(pd.NA, index=current.index, dtype="Int64")
    estimate = np.ceil(current[valid] * future[valid] / observed[valid] - 1e-10)
    result.loc[valid] = np.maximum(0, estimate - current[valid]).astype("int64")
    return result


def render_expansion_ranking(inputs, visible_frame, horizon):
    try:
        ranked = expansion_ranking(inputs["catalog"], visible_frame.zone_id, horizon // 12)
    except (OSError, ValueError, KeyError):
        st.warning("El ranking de oportunidad no está disponible por ahora.")
        return
    if ranked.empty:
        return

    st.subheader("Top 10 para nuevas estaciones", anchor=False)
    st.caption(
        "Ranking orientativo entre las colonias del mapa. Cambia con los años elegidos, "
        "no con el escenario; no es una probabilidad real de apertura."
    )
    st.caption("Ordenado por nuevas estimadas. Regla de tres según demanda y estaciones actuales; no son aperturas confirmadas.")
    st.session_state["rank-future-ids"] = ranked.zone_id.tolist()
    ranked = ranked.merge(
        visible_frame[["zone_id", "reference_value", "map_value"]],
        on="zone_id", how="left", validate="one_to_one",
    ).merge(
        inputs["catalog"][["zone_id", "n_estaciones_catalogo_actual"]],
        on="zone_id", how="left", validate="one_to_one",
    )
    additional = estimate_additional_stations(
        ranked.n_estaciones_catalogo_actual, ranked.reference_value, ranked.map_value,
    )
    ranked["nuevas_estimadas"] = additional
    ranked = ranked.sort_values(
        ["nuevas_estimadas", "opportunity_score", "colonia"],
        ascending=[False, False, True],
        na_position="last",
    ).drop(columns="puesto").reset_index(drop=True)
    ranked.insert(0, "puesto", np.arange(1, len(ranked) + 1))
    additional = ranked.pop("nuevas_estimadas")
    st.session_state["rank-future-ids"] = ranked.zone_id.tolist()
    labels = {
        "Oportunidad alta": "Alto",
        "Oportunidad moderada": "Moderado",
        "Vigilar": "Por revisar",
        "No recomendada (saturada o alto riesgo)": "Bajo",
        "Datos insuficientes": "Sin datos",
    }
    table = pd.DataFrame({
        "#": ranked.puesto.to_numpy(),
        "Colonia": ranked.colonia.to_numpy(),
        "Alcaldía": ranked.alcaldia.map(alcaldia_label).to_numpy(),
        "Potencial": ranked.opportunity_category.map(labels).fillna("Sin datos").to_numpy(),
        "Nuevas estimadas": additional.to_numpy(),
    })
    st.dataframe(
        table, hide_index=True, width="stretch", height=392,
        key="rank-future", on_select=pick_zone_from_table("rank-future"),
        selection_mode="single-row",
    )


def page_current_simple(inputs):
    try:
        frame = current_demand_frame(inputs, load_observed_history())
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"No pudimos mostrar la actividad actual: {exc}")
        return

    station_col, municipality_col, zone_col = st.columns([2.2, 1.2, 1.6], vertical_alignment="bottom")
    with station_col:
        show_stations = st.toggle("Mostrar estaciones ECOBICI", value=True, key="show-current-stations")
    with municipality_col:
        municipality = st.selectbox(
            "Alcaldía", ["Todas", *ALCALDIAS_CDMX],
            format_func=lambda value: "Todas" if value == "Todas" else alcaldia_label(value),
            key="simple-municipality", persist_state="session",
        )
    filtered = frame if municipality == "Todas" else frame[frame.alcaldia.eq(municipality)]
    filtered = filtered[filtered.map_value.notna()].copy()
    if filtered.empty:
        disabled_zone_selector(zone_col, "Sin colonias disponibles")
        st.warning("Todavía no hay colonias para mostrar en esta alcaldía.")
        return
    zone = zone_selector(zone_col, filtered, widget_key="zone-pick-current")
    origin = filtered.target_period.iloc[0]
    fig = simple_demand_map(
        filtered, inputs["geometry"], title=f"Demanda actual por colonia · {origin}",
        highlight_zone=zone,
    )
    station_period = None
    if show_stations:
        try:
            stations = load_current_station_points()
            activity = load_station_activity()
            station_period = activity.periodo.iloc[0]
            stations = station_points_with_activity(stations, activity, origin)
            if municipality != "Todas":
                stations = stations[stations.alcaldia.eq(municipality)]
            add_station_points(fig, stations)
        except (OSError, ValueError, KeyError):
            st.warning("No pudimos cargar la actividad por estación.")
    render_map(fig, "map-current")
    if station_period is not None:
        st.caption(
            "Puntos: estaciones del catálogo actual; tamaño según movimientos registrados en "
            f"{station_period} (último mes disponible por estación). "
            "No muestran bicicletas en tiempo real."
        )


def page_future_simple(inputs):
    scenario_name = "Base"
    # La cabecera mantiene el orden y los controles de la imagen de referencia.
    if st.session_state.get("simple-horizon", 12) == 12:
        horizon_col, municipality_col, zone_col = st.columns(
            [1.15, 1.1, 1.5], vertical_alignment="bottom", gap="small",
        )
        scenario_col = None
    else:
        horizon_col, scenario_col, municipality_col, zone_col = st.columns(
            [1.6, 1.5, 1.1, 1.8], vertical_alignment="bottom", gap="small",
        )
    with horizon_col:
        horizon = st.segmented_control(
            "Horizonte", list(SIMPLE_HORIZONS), format_func=SIMPLE_HORIZONS.get,
            default=12, required=True, key="simple-horizon", persist_state="session", width="stretch",
        )
    if scenario_col is not None:
        with scenario_col:
            scenario_name = st.segmented_control(
                "¿Qué escenario quieres ver?", list(SCENARIO_OPTIONS),
                default="Base", required=True, key="simple-scenario",
                persist_state="session", width="stretch",
            )
    with municipality_col:
        municipality = st.selectbox(
            "Alcaldía", ["Todas", *ALCALDIAS_CDMX],
            format_func=lambda value: "Todas" if value == "Todas" else alcaldia_label(value),
            key="simple-municipality", persist_state="session",
        )

    try:
        scenarios = load_long_term_scenarios() if horizon in (36, 60) else None
        frame = future_demand_frame(inputs, horizon, scenario_name, scenarios)
    except (OSError, ValueError, KeyError) as exc:
        disabled_zone_selector(zone_col, "Sin datos disponibles")
        st.error(f"No pudimos mostrar este horizonte: {exc}")
        return
    if frame is None:
        disabled_zone_selector(zone_col, "Sin datos disponibles")
        st.warning("Este horizonte todavía no está disponible.")
        return
    filtered = frame if municipality == "Todas" else frame[frame.alcaldia.eq(municipality)]
    filtered = filtered[filtered.map_value.notna()].copy()
    if filtered.empty:
        disabled_zone_selector(zone_col, "Sin colonias disponibles")
        st.warning("Todavía no hay colonias para mostrar con esta selección.")
        return
    zone = zone_selector(zone_col, filtered, widget_key="zone-pick-future")
    target = filtered.target_period.iloc[0]
    title = (
        f"Cambio frente a hoy · tendencia anual · {target}" if horizon == 12
        else f"Cambio frente a hoy · escenario {scenario_name.lower()} · {target}"
    )
    fig = simple_demand_map(
        filtered, inputs["geometry"], title=title, future=True, highlight_zone=zone,
    )
    render_map(fig, "map-future")
    if horizon == 12:
        st.caption("1 año: tendencia interanual observada. Morado: menos actividad · Gris: sin cambio · Naranja: más actividad")
    else:
        st.caption("Morado: menos actividad · Gris: sin cambio · Naranja: más actividad")
    render_expansion_ranking(inputs, filtered, horizon)


# ============================================================
# ENTRADA
# ============================================================

def main():
    st.set_page_config(
        page_title="ECOBICI · ¿Qué puede pasar?",
        page_icon=":material/pedal_bike:",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    try:
        with st.spinner("Cargando datos…"):
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
        st.title("¿Qué puede pasar con ECOBICI?", anchor=False)
        ui.notice(
            "error",
            "No pudimos cargar los datos de la app",
            f"{exc}\n\nLa app solo lee resultados ya calculados; no entrena modelos aquí. "
            "Revisa que existan los archivos en data/processed/ y recarga la página.",
        )
        return

    render_header(inputs, ecobici_municipalities)

    current = st.navigation(
        [
            st.Page(lambda: page_current_simple(inputs), title="Panorama actual",
                    icon=":material/map:", url_path="panorama", default=True),
            st.Page(lambda: page_future_simple(inputs), title="A futuro",
                    icon=":material/timeline:", url_path="futuro"),
        ],
        position="top",
    )
    current.run()


if __name__ == "__main__":
    main()
