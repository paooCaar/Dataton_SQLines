"""Indicador de siniestralidad ciclista (CONTEXT.md 5, componente 5 "señal
de seguridad"): accidentes de transito con ciclistas involucrados, por
alcaldia y mes, a partir de ATUS.

Resolucion geografica: ATUS viene a nivel MUNICIPIO/ALCALDIA (CVE_MUN), no
colonia (ver CONTEXT.md 6.1.1) - se asigna el mismo valor a todas las
colonias de una alcaldia, resolucion mas gruesa que el resto de componentes,
documentado aqui y en CONTEXT.md en vez de ocultarlo.

Resolucion temporal: ATUS solo tiene cifras definitivas hasta 2025 (ver
metadatos del conjunto de datos) - el panel Ecobici llega a 2026-06, asi que
los periodos 2026-01 a 2026-06 quedan sin dato de siniestros (NaN -> 0 al
integrarse al indice, igual que colonias sin poligono de infraestructura).

Definicion de "accidente con ciclista": TIPACCID == "Colision con ciclista"
O CICLMUERTO+CICLHERIDO > 0 (algunos atropellamientos a ciclistas se
clasifican bajo otro TIPACCID pero igual reportan victimas ciclistas - ver
diccionario ATUS en docs/fuentes_datos.md).

Entradas:
  - data/raw/atus/atus_cdmx_<anio>.csv (2023-2025, ver preparar_atus.py)
  - data/raw/atus/tc_municipio_cdmx.csv

Salida: data/processed/atus_accidentes_alcaldia_mes.csv
  columnas: alcaldia, periodo (YYYY-MM), accidentes_ciclistas, victimas_ciclistas
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ATUS_RAW = ROOT / "data" / "raw" / "atus"
ANIOS = [2023, 2024, 2025]

SALIDA = ROOT / "data" / "processed" / "atus_accidentes_alcaldia_mes.csv"

# Mismos nombres ASCII sin acento que usa Caracteristicas_estaciones.csv de
# Ecobici (ver indicadores_poblacion.py, MAPA_NOMBRES) - solo las 6 alcaldias
# en alcance (CONTEXT.md seccion 3).
MAPA_NOMBRES = {
    "Cuauhtémoc": "Cuauhtemoc",
    "Benito Juárez": "Benito Juarez",
    "Miguel Hidalgo": "Miguel Hidalgo",
    "Coyoacán": "Coyoacan",
    "Azcapotzalco": "Azcapotzalco",
    "Álvaro Obregón": "Alvaro Obregon",
}


def main() -> None:
    atus = pd.concat(
        [pd.read_csv(ATUS_RAW / f"atus_cdmx_{anio}.csv", dtype={"CVE_MUN": str}) for anio in ANIOS],
        ignore_index=True,
    )

    municipios = pd.read_csv(ATUS_RAW / "tc_municipio_cdmx.csv", dtype={"CVE_MUN": str})
    atus = atus.merge(municipios[["CVE_MUN", "NOM_MUNICIPIO"]], on="CVE_MUN", how="left")
    atus["alcaldia"] = atus["NOM_MUNICIPIO"].map(MAPA_NOMBRES)

    ciclistas = atus[
        (atus["TIPACCID"] == "Colisión con ciclista") | ((atus["CICLMUERTO"] + atus["CICLHERIDO"]) > 0)
    ].copy()
    ciclistas["periodo"] = ciclistas["ANIO"].astype(str) + "-" + ciclistas["MES"].astype(str).str.zfill(2)
    ciclistas["victimas"] = ciclistas["CICLMUERTO"] + ciclistas["CICLHERIDO"]

    resultado = (
        ciclistas.groupby(["alcaldia", "periodo"])
        .agg(accidentes_ciclistas=("TIPACCID", "size"), victimas_ciclistas=("victimas", "sum"))
        .reset_index()
    )
    resultado = resultado.dropna(subset=["alcaldia"])

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(SALIDA, index=False)

    print(f"Accidentes con ciclista en CDMX 2023-2025: {len(ciclistas)} (de {len(atus)} accidentes totales)")
    print(f"Guardado: {SALIDA} ({len(resultado)} filas alcaldia x mes)")
    print("\nAccidentes con ciclista por alcaldia (2023-2025, subconjunto en alcance):")
    print(
        resultado[resultado["alcaldia"].isin(MAPA_NOMBRES.values())]
        .groupby("alcaldia")["accidentes_ciclistas"].sum().sort_values(ascending=False)
    )


if __name__ == "__main__":
    main()
