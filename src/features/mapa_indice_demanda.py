"""Mapa del indice de demanda COMPUESTO por colonia (uso Ecobici + aperturas
DENUE + brecha de infraestructura, ver CONTEXT.md 5.1 e indice_compuesto.py):
un marcador por colonia en el centroide de sus cicloestaciones, coloreado por
categoria de tendencia y con tamano proporcional al nivel del indice.

Entradas:
  - data/processed/indice_demanda_colonia.csv
  - datos_bici/Caracteristicas_estaciones.csv (para el centroide por colonia)

Salida: reports/figures/mapa_indice_demanda_colonia.html
"""
from pathlib import Path

import folium
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INDICE = ROOT / "data" / "processed" / "indice_demanda_colonia.csv"
ESTACIONES = ROOT / "datos_bici" / "Caracteristicas_estaciones.csv"
SALIDA = ROOT / "reports" / "figures" / "mapa_indice_demanda_colonia.html"

CDMX_CENTRO = [19.3910, -99.1650]

COLOR_POR_CATEGORIA = {
    "Creciente": "#1a9850",
    "Estable": "#4575b4",
    "Decreciente": "#d73027",
    "Datos insuficientes": "#999999",
}


def main() -> None:
    indice = pd.read_csv(INDICE)

    st = pd.read_csv(ESTACIONES, encoding="latin-1")
    st["num_cicloe"] = st["num_cicloe"].astype(str).str.strip()
    st = st.drop_duplicates(subset="num_cicloe", keep="first").dropna(subset=["colonia"])
    centroides = st.groupby("colonia")[["latitud", "longitud"]].mean()

    df = indice.join(centroides, on="colonia").dropna(subset=["latitud", "longitud"])

    m = folium.Map(location=CDMX_CENTRO, zoom_start=13, tiles="OpenStreetMap")

    nivel_min = df["indice_demanda_compuesto_promedio"].min()
    nivel_max = df["indice_demanda_compuesto_promedio"].max()

    def radio(nivel: float) -> float:
        # Escala 6-26 px segun el nivel del indice compuesto de la colonia.
        return 6 + 20 * (nivel - nivel_min) / (nivel_max - nivel_min)

    for _, row in df.iterrows():
        color = COLOR_POR_CATEGORIA.get(row["tendencia_categoria"], "#999999")
        pendiente = row["tendencia_pendiente_theilsen"]
        pendiente_txt = f"{pendiente:.4f}" if pd.notna(pendiente) else "N/D"
        km_txt = f"{row['km_ciclovia']:.1f} km" if pd.notna(row["km_ciclovia"]) else "sin dato"
        folium.CircleMarker(
            location=[row["latitud"], row["longitud"]],
            radius=radio(row["indice_demanda_compuesto_promedio"]),
            color=color,
            weight=1,
            fill=True,
            fill_color=color,
            fill_opacity=0.65,
            popup=folium.Popup(
                f"<b>{row['colonia']}</b> ({row['alcaldia']})<br>"
                f"Indice de demanda compuesto (promedio): {row['indice_demanda_compuesto_promedio']:.2f}<br>"
                f"&nbsp;&nbsp;- uso Ecobici: {row['indice_uso_ecobici_promedio']:.2f}<br>"
                f"Tendencia: <b>{row['tendencia_categoria']}</b> (pendiente Theil-Sen: {pendiente_txt})<br>"
                f"Viajes totales acumulados: {int(row['viajes_total_acumulado']):,}<br>"
                f"Ciclovia en la colonia: {km_txt}<br>"
                f"Establecimientos DENUE relacionados (bici/mensajeria): {int(row['establecimientos_denue_relacionados'])}<br>"
                f"Poblacion de la alcaldia (2020): {int(row['poblacion_alcaldia_2020']):,}<br>"
                f"Periodos con datos: {int(row['n_periodos_con_datos'])}",
                max_width=300,
            ),
        ).add_to(m)

    leyenda_html = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 9999;
                background: white; padding: 10px 14px; border: 1px solid #999;
                border-radius: 6px; font-size: 13px; font-family: sans-serif;">
      <b>Tendencia del indice de demanda compuesto</b><br>
      <span style="color:#1a9850;">&#9679;</span> Creciente<br>
      <span style="color:#4575b4;">&#9679;</span> Estable<br>
      <span style="color:#d73027;">&#9679;</span> Decreciente<br>
      <span style="color:#999999;">&#9679;</span> Datos insuficientes<br>
      <i>Tamano del circulo = nivel del indice compuesto</i>
    </div>
    """
    m.get_root().html.add_child(folium.Element(leyenda_html))

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(SALIDA))
    print(f"Guardado: {SALIDA}")


if __name__ == "__main__":
    main()
