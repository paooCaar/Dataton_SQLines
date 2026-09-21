"""Componentes visuales nativos para la aplicación ECOBICI V2.

Este módulo contiene únicamente presentación. No transforma los contratos de
datos, no calcula pronósticos y no modifica artefactos procesados.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import numpy as np
import plotly.graph_objects as go
import streamlit as st


LEVELS = ["Muy baja", "Baja", "Media", "Alta", "Muy alta"]

# Paletas perceptualmente ordenadas y con contraste suficiente sobre fondo claro.
ACTIVITY_COLORS = {
    "Muy baja": "#D9F0E8",
    "Baja": "#A6DCCB",
    "Media": "#58B7A0",
    "Alta": "#177E72",
    "Muy alta": "#064E4A",
}
UNCERTAINTY_COLORS = {
    "Muy baja": "#2A9D8F",
    "Baja": "#83C5BE",
    "Media": "#E9C46A",
    "Alta": "#F4A261",
    "Muy alta": "#C8553D",
}
SCENARIO_COLORS = {
    "Muy baja": "#EEEAF7",
    "Baja": "#D0C4E8",
    "Media": "#A790CF",
    "Alta": "#7452A8",
    "Muy alta": "#43266F",
}
OPPORTUNITY_COLORS = {
    "Muy baja": "#E4EDF4",
    "Baja": "#B7CEE0",
    "Media": "#76A5C5",
    "Alta": "#39799F",
    "Muy alta": "#164B68",
}
TREND_COLORS = {
    "Subiendo": "#167D67",
    "Estable": "#5C677D",
    "Bajando": "#B35C44",
    "Sin dato": "#B8BEC5",
}
DIRECTION_COLORS = {
    "AUMENTO": "#167D67",
    "ESTABLE": "#5C677D",
    "DISMINUCIÓN": "#B35C44",
    "Sin forecast": "#B8BEC5",
    "Sin dato": "#B8BEC5",
}
DIVERGING_SCALE = [
    [0.0, "#A64034"],
    [0.25, "#E2A58F"],
    [0.5, "#F4F1EA"],
    [0.75, "#82B9AE"],
    [1.0, "#176B61"],
]

TREND_META = {
    "Subiendo": (":material/trending_up:", "green"),
    "Estable": (":material/trending_flat:", "gray"),
    "Bajando": (":material/trending_down:", "orange"),
    "Sin dato": (":material/horizontal_rule:", "gray"),
}
TREND_GLYPH = {
    "Subiendo": "↑",
    "Estable": "→",
    "Bajando": "↓",
    "Sin dato": "·",
}


def stat(label: str, value: str, note: str | None = None) -> None:
    """Tarjeta numérica sin ``st.metric`` para escenarios no validados."""
    with st.container(border=True):
        st.caption(label)
        st.subheader(str(value), anchor=False)
        if note:
            st.caption(note)


def notice(kind: str, title: str, body: str) -> None:
    """Aviso semántico compacto con título estable."""
    renderers = {
        "info": (st.info, ":material/info:"),
        "warning": (st.warning, ":material/warning:"),
        "error": (st.error, ":material/error:"),
        "success": (st.success, ":material/check_circle:"),
    }
    renderer, icon = renderers.get(kind, renderers["info"])
    renderer(f"**{title}**\n\n{body}", icon=icon)


def mode_banner(
    kind: str,
    detail: str,
    trailing: Callable[[], Any] | None = None,
) -> None:
    """Etiqueta el modo activo para evitar mezclar forecast y escenarios."""
    metadata = {
        "validated": ("Forecast validado", "green", ":material/verified:"),
        "historical": ("Validación histórica", "orange", ":material/history:"),
        "scenario": ("Escenario condicionado", "violet", ":material/timeline:"),
    }
    label, color, icon = metadata.get(kind, ("Información", "gray", ":material/info:"))
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.badge(label, color=color, icon=icon)
        st.caption(detail)
        if trailing is not None:
            trailing()


def range_bar(lower: Any, center: Any, upper: Any, *, fmt: Callable[[Any], str]) -> bool:
    """Muestra un intervalo y su punto central en una barra accesible."""
    try:
        values = np.asarray([lower, center, upper], dtype=float)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(values).all() or values[0] > values[1] or values[1] > values[2]:
        return False
    lower, center, upper = values

    span = max(float(upper - lower), abs(float(center)) * 0.08, 1.0)
    margin = span * 0.18
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[lower, upper],
            y=[0, 0],
            mode="lines",
            line={"color": "#6AAFA4", "width": 14},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[center],
            y=[0],
            mode="markers",
            marker={"color": "#0B5D55", "size": 15, "line": {"color": "#FFFFFF", "width": 2}},
            hovertemplate=f"Actividad prevista: {fmt(center)}<extra></extra>",
            showlegend=False,
        )
    )
    figure.update_layout(
        height=92,
        margin={"l": 8, "r": 8, "t": 4, "b": 24},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={
            "range": [lower - margin, upper + margin],
            "tickmode": "array",
            "tickvals": [lower, center, upper],
            "ticktext": [fmt(lower), fmt(center), fmt(upper)],
            "fixedrange": True,
            "showgrid": False,
            "zeroline": False,
        },
        yaxis={"visible": False, "fixedrange": True, "range": [-0.5, 0.5]},
        showlegend=False,
    )
    st.plotly_chart(
        figure,
        width="stretch",
        config={"displayModeBar": False, "responsive": True},
    )
    st.caption("Rango inferior · punto central · rango superior")
    return True


def trend_badge(value: str, *, label: str | None = None) -> None:
    icon, color = TREND_META.get(value, TREND_META["Sin dato"])
    st.badge(label or value, icon=icon, color=color)


def direction_badge(value: str) -> None:
    metadata = {
        "AUMENTO": ("Aumento", "green", ":material/trending_up:"),
        "ESTABLE": ("Estable", "gray", ":material/trending_flat:"),
        "DISMINUCIÓN": ("Disminución", "orange", ":material/trending_down:"),
    }
    label, color, icon = metadata.get(value, ("Sin dato", "gray", ":material/horizontal_rule:"))
    st.badge(label, color=color, icon=icon)


def share_bar(items: Iterable[tuple[str, int]]) -> None:
    """Composición proporcional de categorías de tendencia."""
    pairs = [(name, max(0, int(value))) for name, value in items]
    total = sum(value for _, value in pairs)
    if total == 0:
        st.caption("Sin tendencias disponibles")
        return

    figure = go.Figure()
    for name, value in pairs:
        figure.add_trace(
            go.Bar(
                x=[value],
                y=["Colonias"],
                name=f"{name}: {value}",
                orientation="h",
                marker_color=TREND_COLORS.get(name, "#B8BEC5"),
                hovertemplate=f"{name}: {value} ({value / total:.0%})<extra></extra>",
            )
        )
    figure.update_layout(
        barmode="stack",
        height=112,
        margin={"l": 0, "r": 0, "t": 4, "b": 34},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False, "fixedrange": True},
        yaxis={"visible": False, "fixedrange": True},
        legend={"orientation": "h", "y": -0.15, "x": 0, "font": {"size": 10}},
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def style_map(
    figure: go.Figure,
    *,
    title: str,
    height: int,
    tag: str | None = None,
    continuous: bool = False,
) -> None:
    """Aplica una jerarquía consistente a todos los mapas Plotly."""
    subtitle = f"<br><sup>{tag}</sup>" if tag else ""
    figure.update_layout(
        title={"text": f"{title}{subtitle}", "x": 0.01, "xanchor": "left"},
        height=height,
        margin={"l": 0, "r": 0, "t": 58 if tag else 44, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 0.01, "x": 0.01},
        hoverlabel={"bgcolor": "#FFFFFF", "font": {"color": "#18312F"}},
        clickmode="event+select",
    )
    if continuous:
        figure.update_coloraxes(
            colorbar={"orientation": "h", "y": 0.02, "x": 0.5, "len": 0.55, "thickness": 12}
        )


def add_zone_highlight(figure: go.Figure, geometry: dict[str, Any], zone_id: Any) -> None:
    """Dibuja un contorno oscuro sobre la colonia activa."""
    if zone_id is None:
        return
    zone_id = str(zone_id)
    feature = next(
        (item for item in geometry.get("features", []) if str(item.get("id")) == zone_id),
        None,
    )
    if feature is None:
        return

    figure.add_trace(
        go.Choroplethmap(
            geojson={"type": "FeatureCollection", "features": [feature]},
            locations=[zone_id],
            featureidkey="id",
            z=[1],
            colorscale=[[0, "rgba(255,255,255,0.05)"], [1, "rgba(255,255,255,0.05)"]],
            marker={"line": {"color": "#102A27", "width": 3}},
            showscale=False,
            hoverinfo="skip",
            name="Colonia seleccionada",
        )
    )


def coverage_chart(horizons: Iterable[Any], observed: Iterable[Any], target: float) -> go.Figure:
    x = list(horizons)
    y = [float(value) * 100 for value in observed]
    target_pct = float(target) * 100
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines+markers+text",
            text=[f"{value:.1f}%" for value in y],
            textposition="top center",
            name="Cobertura observada",
            line={"color": "#0B6B61", "width": 3},
            marker={"size": 9},
        )
    )
    figure.add_hline(
        y=target_pct,
        line_dash="dot",
        line_color="#7A5AA6",
        annotation_text=f"Objetivo {target_pct:.0f}%",
        annotation_position="bottom right",
    )
    figure.update_layout(
        height=320,
        margin={"l": 12, "r": 12, "t": 28, "b": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"title": "Horizonte (meses)", "fixedrange": True},
        yaxis={"title": "Cobertura", "ticksuffix": "%", "range": [0, max(100, max(y, default=0) + 8)], "fixedrange": True},
        showlegend=False,
    )
    return figure


def scenario_range_chart(
    rows: Iterable[tuple[str, dict[str, Any]]],
    anchor: Any,
    *,
    fmt: Callable[[Any], str],
) -> go.Figure:
    """Compara bajo/base/alto por horizonte sin sugerir probabilidad."""
    labels: list[str] = []
    low: list[float] = []
    base: list[float] = []
    high: list[float] = []
    for label, values in rows:
        trio = [values.get("Bajo"), values.get("Base"), values.get("Alto")]
        try:
            numeric_trio = np.asarray(trio, dtype=float)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(numeric_trio).all():
            continue
        labels.append(label)
        low.append(float(numeric_trio[0]))
        base.append(float(numeric_trio[1]))
        high.append(float(numeric_trio[2]))

    figure = go.Figure()
    for label, lo, mid, hi in zip(labels, low, base, high):
        figure.add_trace(
            go.Scatter(
                x=[lo, hi], y=[label, label], mode="lines",
                line={"color": "#B9A8D4", "width": 12},
                hovertemplate=f"Bajo: {fmt(lo)}<br>Alto: {fmt(hi)}<extra></extra>",
                showlegend=False,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=[mid], y=[label], mode="markers+text",
                marker={"color": "#60408A", "size": 12},
                text=[fmt(mid)], textposition="top center",
                hovertemplate=f"Base: {fmt(mid)}<extra></extra>",
                showlegend=False,
            )
        )
    try:
        anchor_value = float(anchor)
    except (TypeError, ValueError):
        anchor_value = float("nan")
    if np.isfinite(anchor_value):
        figure.add_vline(
            x=anchor_value, line_dash="dot", line_color="#4B5E5B",
            annotation_text="Ancla 12 meses", annotation_position="top",
        )
    figure.update_layout(
        height=max(230, 100 + 80 * len(labels)),
        margin={"l": 12, "r": 12, "t": 36, "b": 24},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"title": "Endpoints mensuales", "fixedrange": True},
        yaxis={"title": None, "fixedrange": True},
        showlegend=False,
    )
    return figure
