"""Descarga reproducible de las fuentes confirmadas en docs/fuentes_datos.md
(2026-09-15): DENUE, Censo 2020 por AGEB/manzana, infraestructura vial
ciclista CDMX, colonias CDMX y Marco Geoestadistico (poligonos de AGEB).

No se descarga automaticamente Ecobici (ya vive en datos_bici/, provisto por
el equipo) ni ATUS (ver src/data/preparar_atus.py - se restaura del propio
historial de git en vez de descargarse de nuevo) ni OSM (pendiente/opcional,
ver docs/fuentes_datos.md).

Uso: python3 src/data/descargar_denue_censo_ciclovias.py
"""
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

FUENTES = [
    {
        "nombre": "DENUE Ciudad de Mexico (ed. 2026-05)",
        "url": "https://www.inegi.org.mx/contenidos/masiva/denue/denue_09_csv.zip",
        "destino": RAW / "denue" / "denue_09_csv.zip",
        "descomprimir_en": RAW / "denue",
    },
    {
        "nombre": "Censo 2020 - AGEB/manzana urbana CDMX",
        "url": "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/ageb_manzana/ageb_mza_urbana_09_cpv2020_csv.zip",
        "destino": RAW / "censo_ageb_manzana2020" / "ageb_mza_urbana_09_cpv2020_csv.zip",
        "descomprimir_en": RAW / "censo_ageb_manzana2020",
    },
    {
        "nombre": "Censo 2020 - ITER (referencia a nivel alcaldia)",
        "url": "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/iter/iter_09_cpv2020_csv.zip",
        "destino": RAW / "censo_iter2020" / "iter_09_cpv2020_csv.zip",
        "descomprimir_en": RAW / "censo_iter2020",
    },
    {
        "nombre": "Infraestructura vial ciclista CDMX (SHP)",
        "url": (
            "https://datos.cdmx.gob.mx/dataset/7a017dd2-0dec-44f2-b550-10af1a6ee120/"
            "resource/6e541083-1399-4c14-a210-0493167c7b16/download/"
            "6e541083-1399-4c14-a210-0493167c7b16.zip"
        ),
        "destino": RAW / "infraestructura_ciclista" / "infraestructura_vial_ciclista.zip",
        "descomprimir_en": RAW / "infraestructura_ciclista" / "shp",
    },
    {
        "nombre": "Infraestructura vial ciclista CDMX (diccionario de datos)",
        "url": (
            "https://datos.cdmx.gob.mx/dataset/7a017dd2-0dec-44f2-b550-10af1a6ee120/"
            "resource/d70d3ddd-25c8-42ba-8bf9-fe2a855ded25/download/"
            "d70d3ddd-25c8-42ba-8bf9-fe2a855ded25.xlsx"
        ),
        "destino": RAW / "infraestructura_ciclista" / "diccionario_de_datos.xlsx",
        "descomprimir_en": None,
    },
    {
        "nombre": "Colonias CDMX (limites, catalogo IECM)",
        "url": (
            "https://datos.cdmx.gob.mx/dataset/04a1900a-0c2f-41ed-94dc-3d2d5bad4065/"
            "resource/f1408eeb-4e97-4548-bc69-61ff83838b1d/download/"
            "f1408eeb-4e97-4548-bc69-61ff83838b1d.zip"
        ),
        "destino": RAW / "colonias_cdmx" / "colonias_cdmx.zip",
        "descomprimir_en": RAW / "colonias_cdmx" / "shp",
    },
    {
        "nombre": "Marco Geoestadistico - AGEB urbana CDMX (edicion 2020, via Datos Abiertos CDMX)",
        "url": (
            "https://datos.cdmx.gob.mx/dataset/d2ccf6ae-fdf4-407c-a15f-e7dfac2d509d/"
            "resource/b2e17ed0-f2d9-4540-94a1-e57e988b6668/download/"
            "b2e17ed0-f2d9-4540-94a1-e57e988b6668.zip"
        ),
        "destino": RAW / "marco_geoestadistico" / "ageb_urbana_cdmx.zip",
        "descomprimir_en": RAW / "marco_geoestadistico" / "shp",
    },
]


def descargar(fuente: dict) -> None:
    destino = fuente["destino"]
    if destino.exists():
        print(f"Ya existe, se omite: {destino}")
    else:
        destino.parent.mkdir(parents=True, exist_ok=True)
        print(f"Descargando {fuente['nombre']} -> {destino}")
        urlretrieve(fuente["url"], destino)

    carpeta_descompresion = fuente["descomprimir_en"]
    if carpeta_descompresion and destino.suffix == ".zip":
        if carpeta_descompresion.exists() and any(carpeta_descompresion.iterdir()):
            print(f"  Ya descomprimido en: {carpeta_descompresion}")
            return
        carpeta_descompresion.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destino) as z:
            z.extractall(carpeta_descompresion)
        print(f"  Descomprimido en: {carpeta_descompresion}")


def main() -> None:
    for fuente in FUENTES:
        descargar(fuente)


if __name__ == "__main__":
    main()
