"""Genera un mapa de calor (folium/Leaflet) de los viajes Ecobici por
estacion sobre la Ciudad de Mexico.

Entrada: data/processed/ecobici_viajes_por_estacion.csv
Salida: reports/figures/mapa_calor_ecobici.html
"""
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import HeatMap

ROOT = Path(__file__).resolve().parents[2]
ENTRADA = ROOT / "data" / "processed" / "ecobici_viajes_por_estacion.csv"
SALIDA = ROOT / "reports" / "figures" / "mapa_calor_ecobici.html"

CDMX_CENTRO = [19.3910, -99.1650]


def main() -> None:
    df = pd.read_csv(ENTRADA)
    df = df.dropna(subset=["latitud", "longitud"])

    m = folium.Map(location=CDMX_CENTRO, zoom_start=13, tiles="OpenStreetMap")

    heat_data = df[["latitud", "longitud", "viajes_total"]].values.tolist()
    HeatMap(
        heat_data,
        radius=18,
        blur=22,
        max_zoom=14,
        min_opacity=0.35,
    ).add_to(m)

    # Marcadores discretos con info por estacion (top estaciones por volumen)
    top = df.sort_values("viajes_total", ascending=False).head(30)
    for _, row in top.iterrows():
        folium.CircleMarker(
            location=[row["latitud"], row["longitud"]],
            radius=4,
            color="#1f4e8c",
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(
                f"<b>Estacion {row['num_cicloe']}</b><br>"
                f"{row.get('calle_prin', '')} / {row.get('calle_secu', '')}<br>"
                f"Colonia: {row.get('colonia', 'N/D')}<br>"
                f"Alcaldia: {row.get('alcaldia', 'N/D')}<br>"
                f"Viajes totales: {int(row['viajes_total']):,}<br>"
                f"Retiros: {int(row['viajes_retiro']):,} | Arribos: {int(row['viajes_arribo']):,}",
                max_width=280,
            ),
        ).add_to(m)

    folium.LayerControl().add_to(m)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(SALIDA))
    print(f"Guardado: {SALIDA}")


if __name__ == "__main__":
    main()
