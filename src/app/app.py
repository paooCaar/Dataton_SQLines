"""App interactiva (CONTEXT.md seccion 8): el entregable que faltaba en el
"Estado actual" de la seccion 12 - todo lo demas (indice de demanda, baseline,
LightGBM, algoritmo de puntuacion) ya estaba implementado y precalculado.

Principio de diseno (CONTEXT.md 8.1, no negociable): esta app NUNCA entrena ni
corre inferencia de un modelo. Solo lee las proyecciones ya calculadas en
`data/processed/` (via `calcular_scoring`, que a su vez lee los CSV de
`src/models/`) y filtra/rankea/visualiza en memoria - por eso puede responder
"en tiempo real" a los 4 inputs del usuario sin ningun riesgo de que un
modelo tarde o falle frente a los jueces.

Requisitos minimos duros que esta pantalla cubre (CONTEXT.md seccion 1,
rubrica de sesion):
  1. Mapa geoespacial            -> pestana "Mapa"
  2. Interfaz amigable           -> textos sin jerga CDMX (seccion 8.4),
                                     pensados para alguien que no conoce la
                                     ciudad ("un extranjero...")
  3. >=3 fuentes de datos, INEGI incluido -> expander "Fuentes de datos"
  4. Algoritmo de puntuacion/categorizacion segun datos + inputs del usuario
                                  -> src/app/algoritmo_puntuacion.py (ya
                                     implementado, seccion 7), esta app solo
                                     lo conecta a una interfaz real

Requisitos temporales del reto (CONTEXT.md seccion 1): horizonte de proyeccion
1/3/5 anios, con tendencia explicita e incertidumbre visible en cada horizonte
(seccion "Por que esta colonia").

Salidas del reto (CONTEXT.md 8.3): mapa coropletico, panel de ranking, panel
"por que" con factores/fuentes/confianza/advertencias por zona.

Ejecutar con: streamlit run src/app/app.py
"""
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from algoritmo_puntuacion import (  # noqa: E402
    HORIZONTES_VALIDOS,
    NIVELES_RIESGO_VALIDOS,
    POBLACIONES_OBJETIVO_VALIDAS,
    TIPOS_ZONA_USUARIO_VALIDOS,
    ROOT,
    _proyeccion_por_horizonte,
    calcular_scoring,
)

GEOMETRIA = ROOT / "data" / "processed" / "zonas_geometria.geojson"
PANEL = ROOT / "data" / "processed" / "panel_demanda_colonia.csv"
INDICE_COLONIA = ROOT / "data" / "processed" / "indice_demanda_colonia.csv"
VALIDACION_BASELINE = ROOT / "data" / "processed" / "validacion_retrospectiva_baseline.csv"
VALIDACION_LGBM = ROOT / "data" / "processed" / "validacion_retrospectiva_lgbm.csv"

# Periodo del primer mes del panel (data/processed/panel_demanda_colonia.csv,
# CONTEXT.md 5.1): time_idx=1 <-> 2023-01. Se usa para convertir time_idx a
# una fecha real y poder graficar el historico y la proyeccion en un mismo
# eje temporal continuo.
PRIMER_PERIODO = pd.Period("2023-01", freq="M")

CATEGORIAS_ORDEN = [
    "Oportunidad alta",
    "Oportunidad moderada",
    "Vigilar",
    "No recomendada (saturada o alto riesgo)",
    "Datos insuficientes",
]
COLOR_CATEGORIA = {
    "Oportunidad alta": "#1a9850",
    "Oportunidad moderada": "#91cf60",
    "Vigilar": "#fdae61",
    "No recomendada (saturada o alto riesgo)": "#d73027",
    "Datos insuficientes": "#999999",
}

# Etiquetas amigables para los 4 inputs del usuario (CONTEXT.md 7 y 8.4: nada
# de jerga, texto pensado para alguien sin contexto previo de la CDMX).
ETIQUETAS_POBLACION = {
    "general": "Público general (sin preferencia)",
    "jovenes_estudiantes": "Jóvenes y estudiantes",
    "trabajadores": "Trabajadores / oficinistas",
    "adultos_mayores": "Adultos mayores",
}
ETIQUETAS_TIPO_ZONA = {
    "cualquiera": "Cualquier tipo de zona",
    "residencial": "Residencial",
    "mixta": "Mixta (residencial y comercial)",
    "comercial": "Comercial",
}
ETIQUETAS_RIESGO = {
    "bajo": "Bajo — prefiero certeza, aunque el crecimiento estimado sea menor",
    "medio": "Medio",
    "alto": "Alto — acepto más incertidumbre a cambio de mayor potencial",
}
ETIQUETAS_TIPO_ZONA_COLONIA = {
    "Residencial": "zona residencial",
    "Mixta": "zona mixta (residencial y comercial)",
    "Comercial": "zona comercial",
    "Sin clasificar": "zona sin clasificar (no hay suficiente información comercial para tipificarla)",
}


@st.cache_data
def cargar_geojson() -> dict:
    with open(GEOMETRIA, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def limites_mapa(_geojson: dict) -> dict:
    """Caja delimitadora (con margen) de todas las colonias con poligono, para
    encuadrar el mapa (MapLibre `bounds`) sin depender de un centro/zoom fijo
    a ojo. Las 6 alcaldias en alcance (CONTEXT.md 3) no estan centradas en el
    centro turistico de la CDMX - se extienden bastante hacia el poniente
    (Alvaro Obregon, Santa Fe), asi que un centro fijo cortaba colonias."""
    lons, lats = [], []
    for feature in _geojson["features"]:
        geom = feature["geometry"]
        poligonos = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for poligono in poligonos:
            for anillo in poligono:
                for lon, lat in anillo:
                    lons.append(lon)
                    lats.append(lat)
    margen_lon = (max(lons) - min(lons)) * 0.08
    margen_lat = (max(lats) - min(lats)) * 0.08
    return {
        "west": min(lons) - margen_lon,
        "east": max(lons) + margen_lon,
        "south": min(lats) - margen_lat,
        "north": max(lats) + margen_lat,
    }


@st.cache_data
def cargar_panel() -> pd.DataFrame:
    return pd.read_csv(PANEL, dtype={"periodo": str})


@st.cache_data
def cargar_indice_colonia() -> pd.DataFrame:
    return pd.read_csv(INDICE_COLONIA)


@st.cache_data
def calcular_scoring_cacheado(horizonte_anios, poblacion_objetivo, tipo_zona_usuario, riesgo_aceptable) -> pd.DataFrame:
    return calcular_scoring(horizonte_anios, poblacion_objetivo, tipo_zona_usuario, riesgo_aceptable)


@st.cache_data
def proyeccion_por_horizonte_cacheada(horizonte_anios: int) -> pd.DataFrame:
    return _proyeccion_por_horizonte(horizonte_anios)


@st.cache_data
def calcular_metricas_validacion() -> pd.DataFrame:
    """Metricas de la validacion retrospectiva (CONTEXT.md 6.3.3), calculadas
    en vivo sobre los CSV de hold-out (no se hardcodean los numeros del
    documento, para que la app siempre refleje el estado real de los
    archivos en data/processed/)."""
    baseline = pd.read_csv(VALIDACION_BASELINE)
    lgbm = pd.read_csv(VALIDACION_LGBM)

    filas = []
    for nombre, df in [("LightGBM cuantílico", lgbm), ("Tendencia Theil-Sen", baseline)]:
        filas.append(
            {
                "Modelo": nombre,
                "MAE": df["error_abs"].mean(),
                "RMSE": (df["error"] ** 2).mean() ** 0.5,
                "Cobertura P10-P90": df["dentro_p10_p90"].mean(),
                "Precisión direccional": df["categoria_acierto"].mean(),
            }
        )
    filas.append(
        {
            "Modelo": "Naive (persistencia)",
            "MAE": baseline["error_abs_naive"].mean(),
            "RMSE": (baseline["error_naive"] ** 2).mean() ** 0.5,
            "Cobertura P10-P90": float("nan"),
            "Precisión direccional": float("nan"),
        }
    )
    return pd.DataFrame(filas)


def time_idx_a_fecha(time_idx: int) -> pd.Timestamp:
    return (PRIMER_PERIODO + (int(time_idx) - 1)).to_timestamp()


def grafica_tendencia_y_pronostico(colonia: str, horizonte_seleccionado: int) -> go.Figure:
    panel = cargar_panel()
    historico = panel[(panel["colonia"] == colonia) & (panel["viajes_total"] > 0)].sort_values("time_idx")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=historico["time_idx"].map(time_idx_a_fecha),
            y=historico["indice_demanda_compuesto"],
            mode="lines+markers",
            name="Histórico (índice de demanda)",
            line=dict(color="#2c7fb8"),
            hovertemplate="%{x|%Y-%m}<br>Índice: %{y:.3f}<extra></extra>",
        )
    )

    if historico.empty:
        return fig

    ultimo_time_idx = historico["time_idx"].iloc[-1]
    ultimo_valor = historico["indice_demanda_compuesto"].iloc[-1]
    ultima_fecha = time_idx_a_fecha(ultimo_time_idx)

    for h in HORIZONTES_VALIDOS:
        proyeccion = proyeccion_por_horizonte_cacheada(h)
        if colonia not in proyeccion.index or pd.isna(proyeccion.loc[colonia, "prediccion_p50"]):
            continue
        fila = proyeccion.loc[colonia]
        fecha_h = ultima_fecha + pd.DateOffset(years=h)
        es_seleccionado = h == horizonte_seleccionado

        fig.add_trace(
            go.Scatter(
                x=[ultima_fecha, fecha_h],
                y=[ultimo_valor, fila["prediccion_p50"]],
                mode="lines",
                line=dict(color="#2c7fb8" if es_seleccionado else "#c9c9c9", dash="dot"),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[fecha_h],
                y=[fila["prediccion_p50"]],
                mode="markers",
                name=f"Proyección a {h} año(s)" + (" (seleccionado)" if es_seleccionado else ""),
                marker=dict(
                    size=16 if es_seleccionado else 9,
                    color="#1a9850" if es_seleccionado else "#c9c9c9",
                    symbol="diamond",
                ),
                error_y=dict(
                    type="data",
                    symmetric=False,
                    array=[fila["prediccion_p90"] - fila["prediccion_p50"]],
                    arrayminus=[fila["prediccion_p50"] - fila["prediccion_p10"]],
                    color="#1a9850" if es_seleccionado else "#c9c9c9",
                ),
                hovertemplate=(
                    f"+{h} año(s)<br>P50: %{{y:.3f}}<br>Rango P10-P90: "
                    f"{fila['prediccion_p10']:.3f} a {fila['prediccion_p90']:.3f}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis_title="Índice de demanda compuesto",
        xaxis_title=None,
        height=380,
    )
    return fig


def main() -> None:
    st.set_page_config(page_title="¿Dónde pedalear el futuro?", page_icon="🚲", layout="wide")

    st.title("🚲 ¿Dónde pedalear el futuro?")
    st.caption("Datatón 2026 (ITAM) · Movilidad, transporte e infraestructura ciclista · Ciudad de México")
    st.write(
        "Esta aplicación identifica colonias de la Ciudad de México donde podría "
        "crecer la demanda de infraestructura y servicios para bicicletas "
        "(ciclovías, estacionamientos, talleres, uso de bici pública) en los "
        "próximos años, explicando **por qué** y **con qué nivel de confianza**. "
        "Está pensada para alguien que no conoce las colonias de la ciudad: "
        "no se necesita saber geografía local para usarla."
    )

    st.sidebar.header("Ajusta tu búsqueda")
    horizonte_label = st.sidebar.radio(
        "Horizonte de proyección", options=HORIZONTES_VALIDOS, index=1,
        format_func=lambda h: f"{h} año" + ("s" if h != 1 else ""),
        help="¿A cuántos años quieres ver la proyección de demanda?",
    )
    poblacion_objetivo = st.sidebar.selectbox(
        "Población objetivo", options=POBLACIONES_OBJETIVO_VALIDAS,
        format_func=lambda k: ETIQUETAS_POBLACION[k],
        help="¿Para qué tipo de usuario final piensas ofrecer el servicio o la infraestructura?",
    )
    tipo_zona_usuario = st.sidebar.selectbox(
        "Tipo de zona buscada", options=TIPOS_ZONA_USUARIO_VALIDOS,
        format_func=lambda k: ETIQUETAS_TIPO_ZONA[k],
    )
    riesgo_aceptable = st.sidebar.select_slider(
        "Nivel de riesgo aceptable", options=NIVELES_RIESGO_VALIDOS,
        value="medio", format_func=lambda k: ETIQUETAS_RIESGO[k].split(" — ")[0],
    )
    st.sidebar.caption(ETIQUETAS_RIESGO[riesgo_aceptable])

    resultado = calcular_scoring_cacheado(horizonte_label, poblacion_objetivo, tipo_zona_usuario, riesgo_aceptable)

    conteo = resultado["categoria"].value_counts().reindex(CATEGORIAS_ORDEN, fill_value=0)
    columnas_kpi = st.columns(len(CATEGORIAS_ORDEN))
    for col, categoria in zip(columnas_kpi, CATEGORIAS_ORDEN):
        col.metric(categoria, int(conteo[categoria]))

    tab_mapa, tab_ranking = st.tabs(["🗺️ Mapa", "📊 Ranking y detalle por colonia"])

    with tab_mapa:
        vista = st.radio(
            "Colorear el mapa por:", ["Categoría de oportunidad", "Score (continuo)"],
            horizontal=True,
        )
        geojson = cargar_geojson()
        colonias_con_mapa = {f["properties"]["colonia"] for f in geojson["features"]}
        resultado_mapa = resultado[resultado["colonia"].isin(colonias_con_mapa)]

        if vista == "Categoría de oportunidad":
            resultado_mapa = resultado_mapa.copy()
            categorias_presentes = [c for c in CATEGORIAS_ORDEN if c in resultado_mapa["categoria"].unique()]
            resultado_mapa["categoria"] = pd.Categorical(
                resultado_mapa["categoria"], categories=categorias_presentes, ordered=True
            )
            fig = px.choropleth_map(
                resultado_mapa, geojson=geojson, locations="colonia", featureidkey="properties.colonia",
                color="categoria", color_discrete_map=COLOR_CATEGORIA,
                hover_name="colonia",
                hover_data={"alcaldia": True, "score": ":.2f", "tipo_zona": True, "categoria": False, "colonia": False},
                map_style="carto-positron", opacity=0.75,
            )
        else:
            fig = px.choropleth_map(
                resultado_mapa, geojson=geojson, locations="colonia", featureidkey="properties.colonia",
                color="score", color_continuous_scale="RdYlGn",
                hover_name="colonia",
                hover_data={"alcaldia": True, "categoria": True, "tipo_zona": True, "score": ":.2f"},
                map_style="carto-positron", opacity=0.75,
            )
        fig.update_maps(bounds=limites_mapa(geojson))
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=560)
        st.plotly_chart(fig, use_container_width=True)

        # Contar sobre la INTERSECCION, no sobre len(colonias_con_mapa): el
        # geojson puede traer polígonos de colonias que no están en el ranking
        # (o al revés) y entonces "X de Y … las Z restantes" dejaba de sumar.
        n_total = resultado["colonia"].nunique()
        n_en_mapa = len(colonias_con_mapa & set(resultado["colonia"]))
        st.caption(
            f"{n_en_mapa} de {n_total} colonias tienen polígono disponible "
            f"y se muestran en el mapa. Las {n_total - n_en_mapa} restantes sí aparecen en la pestaña de ranking — "
            "no tener polígono es una limitación de la capa geográfica usada, no evidencia de baja demanda."
        )

    with tab_ranking:
        st.subheader(f"Ranking de oportunidades a {horizonte_label} año(s)")
        tabla = resultado[["colonia", "alcaldia", "categoria", "score", "tipo_zona", "fuente_modelo"]].copy()
        tabla["score"] = tabla["score"].round(3)
        tabla["tipo_zona"] = tabla["tipo_zona"].fillna("Sin clasificar")
        tabla["fuente_modelo"] = tabla["fuente_modelo"].fillna("sin proyección")
        tabla.columns = ["Colonia", "Alcaldía", "Categoría", "Score", "Tipo de zona", "Modelo usado"]
        st.dataframe(tabla, use_container_width=True, hide_index=True, height=320)

        st.divider()
        st.subheader("¿Por qué esta colonia?")
        opciones_colonia = resultado["colonia"].tolist()
        colonia_sel = st.selectbox(
            "Selecciona una colonia (por defecto, la #1 del ranking actual):",
            options=opciones_colonia,
            format_func=lambda c: f"#{opciones_colonia.index(c) + 1} — {c}",
        )
        fila = resultado[resultado["colonia"] == colonia_sel].iloc[0]
        indice_colonia = cargar_indice_colonia().set_index("colonia")

        tipo_zona_txt = ETIQUETAS_TIPO_ZONA_COLONIA.get(fila["tipo_zona"], "zona sin clasificar")
        st.markdown(f"**Colonia {colonia_sel}, Alcaldía {fila['alcaldia']}** — {tipo_zona_txt}.")

        col_izq, col_der = st.columns([2, 1])
        with col_izq:
            st.plotly_chart(grafica_tendencia_y_pronostico(colonia_sel, horizonte_label), use_container_width=True)
            if colonia_sel in indice_colonia.index:
                pendiente = indice_colonia.loc[colonia_sel, "tendencia_pendiente_theilsen"]
                categoria_tendencia = indice_colonia.loc[colonia_sel, "tendencia_categoria"]
                pendiente_txt = f"{pendiente:+.4f}/mes" if pd.notna(pendiente) else "no calculable"
                st.caption(
                    f"Tendencia histórica de largo plazo (regresión Theil-Sen): {pendiente_txt} "
                    f"→ **{categoria_tendencia}**. Los diamantes de la gráfica son la proyección precalculada "
                    "a 1, 3 y 5 años, con su rango de incertidumbre P10–P90; a mayor horizonte, mayor incertidumbre."
                )

        with col_der:
            color_categoria = COLOR_CATEGORIA.get(fila["categoria"], "#999999")
            st.markdown(
                f"<span style='background-color:{color_categoria}; color:white; padding:4px 10px; "
                f"border-radius:6px; font-weight:600;'>{fila['categoria']}</span>",
                unsafe_allow_html=True,
            )
            st.metric("Score", f"{fila['score']:.3f}")
            # Por qué cayó en esa categoría: "No recomendada (saturada o alto
            # riesgo)" se alcanza tanto por el guardarropa de saturación/riesgo
            # como por quedar en el quintil inferior del score, y esos dos
            # casos NO significan lo mismo (ver algoritmo_puntuacion._categorizar).
            st.caption(f"Por qué esta categoría: {fila['motivo_categoria']}.")
            st.caption(f"Modelo de proyección usado: **{fila['fuente_modelo'] or 'sin proyección disponible'}**")

        st.markdown("**Qué explica este score** (contribución de cada factor, ya ponderada):")
        factores = pd.DataFrame(
            {
                "Factor": [
                    "Crecimiento proyectado",
                    "Oferta / infraestructura ya instalada",
                    "Incertidumbre del pronóstico",
                    "Afinidad con población objetivo",
                    "Afinidad con tipo de zona buscado",
                ],
                "Contribución": [
                    fila["crecimiento_norm"],
                    -fila["saturacion_penal"],
                    -fila["riesgo_penal"],
                    fila["afinidad_poblacion"],
                    fila["afinidad_zona"],
                ],
            }
        ).dropna()
        fig_factores = px.bar(
            factores, x="Contribución", y="Factor", orientation="h",
            color="Contribución", color_continuous_scale="RdYlGn", range_color=[-1, 1],
        )
        fig_factores.update_layout(
            showlegend=False, coloraxis_showscale=False, margin=dict(l=10, r=10, t=10, b=10), height=220,
            yaxis_title=None, xaxis_title=None, yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_factores, use_container_width=True)

        if fila["categoria"] == "Datos insuficientes":
            st.info(
                "No hay suficientes periodos con actividad registrada para proyectar esta colonia con "
                "confianza. **Esto no significa que la demanda sea baja** — solo que faltan datos "
                "históricos suficientes para estimarla (ver limitaciones más abajo)."
            )
        if bool(fila["datos_zona_incompletos"]):
            st.warning(
                "Esta colonia tiene información incompleta en al menos una fuente estática (población, "
                "tipo de zona o polígono de infraestructura). Los valores faltantes se trataron como "
                "neutrales, no como ausencia de demanda."
            )

    st.divider()
    with st.expander("📚 Fuentes de datos usadas (≥3 fuentes, INEGI incluido)"):
        st.markdown(
            """
El índice de demanda combina **5 fuentes**, documentadas con su cobertura temporal y geográfica en
[`docs/fuentes_datos.md`](../../docs/fuentes_datos.md):

| Fuente | Aporta | Cobertura |
|---|---|---|
| **Ecobici** (Datos Abiertos CDMX) | Viajes en bici pública por colonia y mes | 2023-01 a 2026-06, 107 colonias, mensual (la única fuente con densidad temporal real) |
| **INEGI — DENUE** | Aperturas de comercios/talleres de bici y mensajería | Snapshot mayo 2026, por colonia |
| **Infraestructura ciclista** (SEMOVI/ADIP, vía Datos Abiertos CDMX) | Km de ciclovía existente por colonia | Snapshot marzo 2025 |
| **INEGI — ATUS** | Accidentes con ciclistas, señal de necesidad de infraestructura | 2023-2025, por alcaldía-mes (resolución más gruesa que colonia) |
| **INEGI — Marco Geoestadístico + Censo 2020** | Población por colonia | Corte único 2020 |

Distintas fuentes tienen distinta resolución temporal (mensual a corte único) y geográfica
(colonia vs. alcaldía) — el índice compuesto (`CONTEXT.md`, sección 5) documenta cómo se combinan.
            """
        )

    with st.expander("✅ Validación retrospectiva (qué tan bien predice el modelo)"):
        st.write(
            "Esquema: hold-out temporal — se predice el último mes observado usando solo los meses "
            "anteriores, y se compara contra el valor real. Se reporta para ambos modelos candidatos, "
            "más una referencia ingenua (persistencia: 'igual que el mes pasado')."
        )
        metricas = calcular_metricas_validacion().copy()
        metricas["MAE"] = metricas["MAE"].round(4)
        metricas["RMSE"] = metricas["RMSE"].round(4)
        metricas["Cobertura P10-P90"] = metricas["Cobertura P10-P90"].map(lambda v: f"{v:.1%}" if pd.notna(v) else "—")
        metricas["Precisión direccional"] = metricas["Precisión direccional"].map(lambda v: f"{v:.1%}" if pd.notna(v) else "—")
        st.dataframe(metricas, use_container_width=True, hide_index=True)
        st.caption(
            "El modelo primario de esta app es LightGBM cuantílico cuando tiene predicción para la "
            "colonia/horizonte pedido; si no, usa como respaldo la tendencia Theil-Sen (ver 'Modelo usado' "
            "en el panel de cada colonia)."
        )

    with st.expander("⚠️ Limitaciones y consideraciones éticas"):
        st.markdown(
            """
- Las proyecciones son **estimaciones**, no certezas — por eso siempre se muestra el rango P10–P90,
  y ese rango crece con el horizonte (es normal y esperado a 3-5 años).
- Correlación histórica **no implica causalidad**: los "factores" son asociaciones observadas, no causas
  comprobadas.
- **Ausencia de datos ≠ ausencia de demanda.** Las colonias sin histórico suficiente se marcan como
  "Datos insuficientes", nunca como "baja demanda".
- 23 de 107 colonias no tienen polígono en la capa geográfica usada y no aparecen en el mapa (sí en el
  ranking) — es una limitación de esa capa, no una señal sobre la colonia.
- Los accidentes de ciclistas (ATUS) y la población están a resolución de alcaldía o de un solo corte
  censal (2020), más gruesa que la de Ecobici (mensual, por colonia) — el índice sigue dominado por la
  dinámica de Ecobici.
- El ranking no se revisó todavía contra el riesgo de que colonias de menor ingreso queden sistemáticamente
  abajo solo por tener menos datos u oferta comercial histórica — ver `CONTEXT.md`, sección 9.
            """
        )


if __name__ == "__main__":
    main()
