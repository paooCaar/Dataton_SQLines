"""Independent, read-only Streamlit product for Phase 7."""
from pathlib import Path
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.algoritmo_puntuacion import (  # noqa: E402
    calcular_scoring, POBLACIONES_OBJETIVO_VALIDAS, TIPOS_ZONA_USUARIO_VALIDOS, NIVELES_RIESGO_VALIDOS,
)
from src.app.product_contract_v2 import (  # noqa: E402
    load_inputs, attach_scores, zone_view, number, safe_context,
)


def display_table(frame):
    # Explicit missing labels, including numeric columns in exportable UI tables.
    display = frame.copy()
    for column in display:
        if display[column].isna().any():
            display[column] = display[column].map(lambda value: "Sin dato" if pd.isna(value) else str(value))
    st.dataframe(display, hide_index=True, width="stretch")


def methodology(inputs):
    with st.expander("Validación por horizonte"):
        table = inputs["validation"].copy()
        table["observed_coverage"] = table.observed_coverage.map(lambda v: number(v * 100, 2, "%"))
        table["target_coverage"] = table.target_coverage.map(lambda v: number(v * 100, 0, "%"))
        display_table(table.rename(columns={"horizon_months": "Meses", "forecast_cuts": "Cortes forecast",
            "interval_cuts": "Cortes con intervalo evaluable", "observed_coverage": "Cobertura histórica",
            "target_coverage": "Cobertura objetivo", "n_predictions": "Intervalos evaluados", "validation_status": "Estado"}))
        st.caption("MAE y RMSE en endpoints; universo EVALUATION_ALL. Los intervalos tienen menos cortes por su historia mínima de calibración. LightGBM no sustituyó a persistencia.")
        st.warning("Cobertura inferior al objetivo de 80% en 1 y 3 meses. A 12 meses solo hay 3 cortes con intervalos evaluables; la evidencia es limitada.")
    with st.expander("Metodología y limitaciones"):
        st.write("Datos → panel colonia × mes → features temporales → validación rolling → comparación de modelos → selección de persistencia → incertidumbre conformal → contexto espacial.")
        st.markdown("""
- El forecast principal usa **persistencia**. Cambio esperado cero significa que conserva el nivel de referencia; no significa ausencia de riesgo.
- Intervalos empíricos/conformales globales por horizonte. Dependencia entre cortes, zonas y escalas: no hay garantía de cobertura individual ni futura.
- La emisión actual reutiliza radios congelados de Fase 6, sin recalibrarlos. La cobertura histórica no valida esta nueva emisión.
- 36/60 meses: **SCENARIO_ONLY**; escenario de largo plazo no disponible en esta versión.
- Geometría incompleta, contexto espacial parcial y vigencia histórica de estaciones incompleta.
- Targets provisionales; fechas históricas de publicación/revisión no verificadas. Octubre de 2024 permanece missing, nunca cero.
- Asociación no implica causalidad. Las señales contextuales no modifican el forecast de persistencia.
- El score usa fuentes y proyecciones legacy a 1 año, con snapshots territoriales y proxies demográficos. No es un forecast V2 ni una reconstrucción histórica del score.
""")


def map_figure(frame, geometry, choice):
    selected = frame[frame.map_status.eq("Disponible")].copy()
    column = {"Cambio esperado": "forecast_change_pct", "Dirección": "direction_label", "Opportunity Score": "opportunity_score"}[choice]
    selected = selected[selected[column].notna()]
    if selected.empty:
        return None
    kwargs = {}
    if choice == "Dirección":
        kwargs["color_discrete_map"] = {"AUMENTO": "#187f79", "ESTABLE": "#60748a", "DISMINUCIÓN": "#c26943", "Sin forecast": "#dddddd"}
    else:
        kwargs["color_continuous_scale"] = "Teal" if choice == "Opportunity Score" else "RdBu"
        if choice == "Cambio esperado":
            amplitude = max(1.0, selected[column].abs().max())
            kwargs["range_color"] = (-amplitude, amplitude)
    fig = px.choropleth_map(selected, geojson=geometry, locations="zone_id", featureidkey="id",
        color=column, hover_name="colonia", hover_data={"zone_id": False, "alcaldia": True},
        labels={column: choice}, map_style="white-bg", center={"lat": 19.411, "lon": -99.163},
        zoom=10.5, opacity=.85, **kwargs)
    fig.update_layout(height=470, margin=dict(l=0, r=0, t=0, b=0))
    return fig


def main():
    st.set_page_config(page_title="ECOBICI — Demanda V2", page_icon="🚲", layout="wide")
    st.title("ECOBICI — DEMANDA POR COLONIA")
    st.caption("Actividad esperada · rango de error · contexto territorial · oportunidad")
    try:
        inputs = load_inputs()
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"No se pudieron cargar los contratos V2: {exc}")
        st.info("Verifica los artefactos y su metadata. La app no regenera ni entrena modelos.")
        return

    with st.sidebar:
        st.header("Explorar")
        view = st.radio("Vista", ["Emisión actual", "Validación histórica"])
        horizon = st.selectbox("Horizonte", [1, 3, 6, 12, 36, 60], format_func=lambda h: f"{h} meses" if h != 1 else "1 mes")
        municipality = st.selectbox("Alcaldía", ["Todas"] + sorted(inputs["catalog"].alcaldia.unique()))
        uncertainty_filter = st.selectbox("Incertidumbre", ["Todas", "Con intervalo", "Sin intervalo", "Ancho ≤ actividad prevista", "Ancho > actividad prevista"])
        with st.expander("Preferencias del Opportunity Score"):
            st.caption("Solo afectan el score legacy a 1 año. No cambian el forecast V2.")
            population = st.selectbox("Población objetivo", POBLACIONES_OBJETIVO_VALIDAS)
            zone_type = st.selectbox("Tipo de zona preferido", TIPOS_ZONA_USUARIO_VALIDOS)
            risk = st.selectbox("Riesgo aceptable del score", NIVELES_RIESGO_VALIDOS, index=1)

    if horizon in (36, 60):
        st.subheader("SCENARIO_ONLY")
        st.info("Escenario de largo plazo no disponible en esta versión.")
        methodology(inputs)
        return
    current = view == "Emisión actual"
    product = inputs["current"] if current else inputs["historical"]
    if product is None:
        st.warning("Emisión actual no disponible. La validación histórica puede consultarse por separado.")
        methodology(inputs)
        return
    if current:
        metadata = inputs["metadata"]
        st.info(f"CURRENT FORECAST · origen común: {metadata['common_origin_period']} · {metadata['n_zones']} zonas · emisión registrada: {metadata['issued_at'][:10]}")
    else:
        st.warning("BACKTEST / HISTORICAL FORECAST · últimos pronósticos retrospectivos por zona y horizonte, con orígenes distintos. No es una emisión actual.")

    try:
        scores = attach_scores(inputs["catalog"], calcular_scoring(1, population, zone_type, risk))
    except (OSError, ValueError, KeyError) as exc:
        st.warning(f"Opportunity Score no disponible: {exc}")
        scores = pd.DataFrame({"zone_id": inputs["catalog"].zone_id, "opportunity_score": float("nan"), "opportunity_category": "Sin dato"})
    frame = zone_view(product, inputs["catalog"], inputs["geometry"], scores, horizon)
    if municipality != "Todas":
        frame = frame[frame.alcaldia.eq(municipality)]
    has_interval = frame.interval_lower_80.notna() & frame.interval_upper_80.notna()
    filters = {"Con intervalo": has_interval, "Sin intervalo": ~has_interval,
        "Ancho ≤ actividad prevista": frame.relative_interval_width.le(1),
        "Ancho > actividad prevista": frame.relative_interval_width.gt(1)}
    if uncertainty_filter in filters:
        frame = frame[filters[uncertainty_filter]]
    if frame.empty:
        st.info("No hay zonas que cumplan los filtros. Amplía la selección.")
        methodology(inputs)
        return
    labels = frame.set_index("zone_id").apply(lambda r: f"{r.colonia} · {r.alcaldia}", axis=1).to_dict()
    zone = st.sidebar.selectbox("Colonia", frame.sort_values(["colonia", "alcaldia"]).zone_id.tolist(), format_func=labels.get)
    row = frame[frame.zone_id.eq(zone)].iloc[0]

    st.subheader("MAPA")
    choice = st.selectbox("Mostrar en mapa", ["Cambio esperado", "Dirección", "Opportunity Score"])
    fig = map_figure(frame, inputs["geometry"], choice)
    if fig is None:
        st.info("Sin geometría o valores disponibles para esta selección.")
    else:
        st.plotly_chart(fig, width="stretch")
    st.caption(f"{frame.map_status.eq('Disponible').sum()} zonas con geometría en esta selección. Las demás siguen en búsqueda y ranking. Mapa de polígonos sin servicios cartográficos externos.")

    st.subheader("FORECAST" if current else "FORECAST HISTÓRICO")
    st.markdown(f"**{row.colonia} · {row.alcaldia}**")
    if row.map_status != "Disponible":
        st.info("Sin geometría disponible para mapa")
    if pd.isna(row.forecast_value):
        st.warning("Sin forecast disponible para esta zona y horizonte; no se interpreta como cero.")
    else:
        st.caption(f"{horizon} mes(es) · referencia {row.origin_period} → objetivo {row.target_period}")
        cols = st.columns(3)
        cols[0].metric("Actividad de referencia", number(row.reference_value, suffix=" endpoints"))
        cols[1].metric("Forecast", number(row.forecast_value, suffix=" endpoints"))
        cols[2].metric("Cambio", number(row.forecast_change_pct, 1, "%"))
        st.write(f"Dirección: **{row.direction_label}** · Modelo usado: **{row.model_used}** · Estado: **{row.validation_status}**")
        st.write("El forecast mantiene como referencia el nivel reciente porque persistencia fue seleccionada por su desempeño en validación retrospectiva para este horizonte.")
        st.caption("Endpoints = inicios + finales de viajes registrados en la colonia durante el mes; no son viajes únicos ni personas.")

    st.subheader("INCERTIDUMBRE")
    if pd.notna(row.interval_lower_80) and pd.notna(row.interval_upper_80):
        st.metric("Intervalo 80% · objetivo nominal", f"[{number(row.interval_lower_80)}, {number(row.interval_upper_80)}] endpoints")
        if current:
            st.caption(f"Radio congelado de Fase 6 · corte {row.calibration_origin_period}. Sin recalibración; cobertura de la emisión actual todavía no evaluada.")
    else:
        st.info("Intervalo no disponible: historia de calibración o forecast insuficiente.")
    coverage = inputs["coverage"].set_index("horizon_months").loc[horizon]
    st.write(f"En la validación retrospectiva, el método cubrió {number(coverage.observed_coverage * 100, 2, '%')} de los valores observados para este horizonte. Cobertura objetivo: 80%.")
    if coverage.observed_coverage < .8:
        st.warning("La cobertura histórica estuvo por debajo del objetivo de 80%.")

    st.subheader("CONTEXTO")
    for signal in safe_context(row):
        st.write(f"• {signal}")
    st.caption(f"Cobertura espacial: {number(row.context_coverage * 100, 1, '%')}")
    st.info("Estas señales describen el contexto de la zona y no implican causalidad ni modifican el forecast operativo de persistencia.")

    st.subheader("OPPORTUNITY SCORE")
    st.metric("Score territorial · escala legacy", number(row.opportunity_score, 3))
    st.write(row.opportunity_category)
    st.caption("El score combina criterios de oportunidad territorial y no representa una predicción directa de viajes. Se conserva el algoritmo de Santiago, con fuentes legacy a 1 año; su horizonte y unidad son independientes del forecast V2.")

    with st.expander("Ranking de zonas"):
        ranking = st.selectbox("Ordenar ranking por", ["forecast_change_pct", "opportunity_score"])
        display_table(frame.sort_values([ranking, "colonia"], ascending=[False, True], na_position="last")[["colonia", "alcaldia", ranking, "map_status"]])
        st.caption("Persistencia implica empate en cambio porcentual para niveles positivos; desempate alfabético. No se combina forecast con score.")
    if not current:
        with st.expander("Cortes históricos de esta zona"):
            backtest = inputs["backtest"]
            history = backtest[backtest.zone_id.eq(zone) & backtest.horizon_months.eq(horizon)].copy()
            history["error_forecast_minus_actual"] = history.forecast_value - history.actual
            display_table(history[["origin_period", "target_period", "forecast_value", "actual", "interval_lower_80", "interval_upper_80", "error_forecast_minus_actual"]])
    methodology(inputs)


if __name__ == "__main__":
    main()
