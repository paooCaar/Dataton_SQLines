"""Prepara la fuente ATUS (CONTEXT.md 4, fuente #6 - siniestros viales,
componente 5 "señal de seguridad" de CONTEXT.md 5).

Origen real de los datos: ya estaban en el repo, subidos completos (todo
Mexico, 1997-2025) en el commit inicial "csvs inegi upload" (c9bc25b), dentro
de `data/csvs inegi/conjunto_de_datos_atus_anual_csv/`. Ese commit se
interpreto en su momento como "indicadores economicos no relacionados" y esos
archivos se borraron del working tree (ver docs/fuentes_datos.md,
version anterior) - un error, porque esta fuente especifica SI es la que pide
el reto (ATUS = Estadistica de Accidentes de Transito Terrestre en Zonas
Urbanas y Suburbanas, con columnas TIPACCID/CICLMUERTO/CICLHERIDO). Este
script la restaura desde el historial de git en vez de descargarla de nuevo
de INEGI, y de una vez la filtra a Ciudad de Mexico (CVE_ENT=09) porque el
archivo nacional pesa ~90-100 MB por anio.

Anios extraidos: 2023-2025 (los que solapan con el panel Ecobici, que va de
2023-01 a 2026-06 - ATUS 2026 aun no esta publicado, ver metadatos del
conjunto de datos).

Salidas (en data/raw/atus/, gitignored igual que el resto de data/raw/):
  - atus_cdmx_<anio>.csv (accidentes de la CDMX, columnas relevantes)
  - tc_municipio_cdmx.csv (catalogo CVE_MUN -> nombre de alcaldia, filtrado a CDMX)

Uso: python3 src/data/preparar_atus.py
"""
import subprocess
from io import StringIO
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "atus"

COMMIT = "c9bc25b"
BASE_GIT_PATH = "data/csvs inegi/conjunto_de_datos_atus_anual_csv"
ANIOS = [2023, 2024, 2025]

COLUMNAS_RELEVANTES = [
    "CVE_ENT", "CVE_MUN", "ANIO", "MES", "TIPACCID", "CICLMUERTO", "CICLHERIDO",
]


def leer_de_git(ruta_relativa: str) -> str:
    resultado = subprocess.run(
        ["git", "show", f"{COMMIT}:{ruta_relativa}"],
        cwd=ROOT, capture_output=True, check=True, text=True,
    )
    return resultado.stdout


def preparar_municipios() -> None:
    destino = RAW / "tc_municipio_cdmx.csv"
    if destino.exists():
        print(f"Ya existe, se omite: {destino}")
        return
    texto = leer_de_git(f"{BASE_GIT_PATH}/catalogos/tc_municipio.csv")
    municipios = pd.read_csv(StringIO(texto), dtype=str)
    municipios = municipios[municipios["CVE_ENT"] == "09"]
    RAW.mkdir(parents=True, exist_ok=True)
    municipios.to_csv(destino, index=False)
    print(f"Guardado: {destino} ({len(municipios)} alcaldias)")


def preparar_anio(anio: int) -> None:
    destino = RAW / f"atus_cdmx_{anio}.csv"
    if destino.exists():
        print(f"Ya existe, se omite: {destino}")
        return
    print(f"Extrayendo y filtrando ATUS {anio} (commit {COMMIT}, archivo nacional completo)...")
    texto = leer_de_git(f"{BASE_GIT_PATH}/conjunto_de_datos/atus_anual_{anio}.csv")
    df = pd.read_csv(StringIO(texto), dtype=str, usecols=COLUMNAS_RELEVANTES)
    cdmx = df[df["CVE_ENT"] == "09"].copy()
    for col in ["CICLMUERTO", "CICLHERIDO"]:
        cdmx[col] = pd.to_numeric(cdmx[col], errors="coerce").fillna(0).astype(int)
    RAW.mkdir(parents=True, exist_ok=True)
    cdmx.to_csv(destino, index=False)
    print(f"Guardado: {destino} ({len(cdmx)} de {len(df)} accidentes nacionales son de CDMX)")


def main() -> None:
    preparar_municipios()
    for anio in ANIOS:
        preparar_anio(anio)


if __name__ == "__main__":
    main()
