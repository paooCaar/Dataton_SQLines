"""Algoritmo de puntuacion y categorizacion (CONTEXT.md 7, requisito duro de
la rubrica: "algoritmo que calcule una puntuacion y categorice las zonas
segun datos e informacion del usuario").

Es la capa que combina la prediccion PRECALCULADA del modelo (baseline
Theil-Sen o LightGBM cuantilico, ver src/models/) con los 4 inputs que pide
el reto para producir un ranking y una categoria por zona. No entrena ni
corre inferencia de ningun modelo - solo lee las proyecciones ya guardadas
en data/processed/ y hace aritmetica ligera sobre ~100 filas, asi que puede
llamarse en vivo desde la app (CONTEXT.md 8.1: "la app en vivo solo filtra,
rankea y visualiza").

Inputs del usuario (CONTEXT.md 7):
  - horizonte_anios: 1, 3 o 5 -> que fila de la proyeccion se usa.
  - poblacion_objetivo: general / jovenes_estudiantes / trabajadores /
    adultos_mayores -> pondera afinidad_poblacion.
  - tipo_zona_usuario: cualquiera / residencial / mixta / comercial ->
    pondera afinidad_zona contra tipo_zona_colonia.csv
    (src/features/indicadores_tipo_zona.py).
  - riesgo_aceptable: bajo / medio / alto -> multiplica cuanto penaliza la
    incertidumbre del pronostico (ancho del intervalo P10-P90).

Formula (pseudocodigo de CONTEXT.md 7, pesos documentados abajo como
razonados - "a calibrar" con feedback de negocio, igual que PESOS en
indice_compuesto.py):

  score[z, h] = w1*crecimiento_norm  - w2*saturacion_penal - w3*riesgo_penal
              + w4*afinidad_poblacion + w5*afinidad_zona

Todos los terminos se normalizan a [0, 1] (min-max entre las zonas validas
del horizonte pedido) para que los pesos sean comparables entre si.

Limitacion honesta (CONTEXT.md 9): no existe informacion demografica por
edad a nivel colonia (el Censo solo se agrego a poblacion total, ver
indicadores_poblacion_colonia.py), asi que `afinidad_poblacion` es un proxy
razonado a partir de densidad poblacional y densidad comercial (DENUE) por
colonia, NO una segmentacion demografica real por edad. Se documenta en vez
de fingir precision que los datos no tienen.

Categorias de salida (CONTEXT.md 7): 'Oportunidad alta', 'Oportunidad
moderada', 'Vigilar', 'No recomendada (saturada o alto riesgo)',
'Datos insuficientes'. Esta ultima es OBLIGATORIA y separada de "baja
demanda": una zona sin suficientes periodos de datos para proyectar nunca se
categoriza como si tuviera poca demanda (CONTEXT.md 7 y 9).

Entradas:
  - data/processed/panel_demanda_colonia.csv (nivel actual = ultimo periodo
    activo observado por colonia)
  - data/processed/proyeccion_demanda_colonia_lgbm.csv (modelo primario,
    CONTEXT.md 6.3.3: LightGBM es el candidato mas solido para produccion)
  - data/processed/proyeccion_demanda_colonia.csv (fallback: baseline
    Theil-Sen, por si LightGBM no tiene fila para una colonia/horizonte)
  - data/processed/indice_demanda_colonia.csv (km_ciclovia: proxy de oferta
    actual para saturacion_penal)
  - data/processed/poblacion_colonia.csv
  - data/processed/tipo_zona_colonia.csv

No genera un archivo de salida fijo: `calcular_scoring(...)` se llama con
los 4 inputs y devuelve el ranking en memoria (pensado para ser importado
por la futura app de Streamlit, CONTEXT.md 8.5). `main()` solo corre un par
de ejemplos para verificar manualmente que el score SI cambia con los
inputs.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "data" / "processed" / "panel_demanda_colonia.csv"
PROYECCION_LGBM = ROOT / "data" / "processed" / "proyeccion_demanda_colonia_lgbm.csv"
PROYECCION_BASELINE = ROOT / "data" / "processed" / "proyeccion_demanda_colonia.csv"
INDICE_COLONIA = ROOT / "data" / "processed" / "indice_demanda_colonia.csv"
POBLACION_COLONIA = ROOT / "data" / "processed" / "poblacion_colonia.csv"
TIPO_ZONA_COLONIA = ROOT / "data" / "processed" / "tipo_zona_colonia.csv"

HORIZONTES_VALIDOS = (1, 3, 5)
POBLACIONES_OBJETIVO_VALIDAS = ("general", "jovenes_estudiantes", "trabajadores", "adultos_mayores")
TIPOS_ZONA_USUARIO_VALIDOS = ("cualquiera", "residencial", "mixta", "comercial")
NIVELES_RIESGO_VALIDOS = ("bajo", "medio", "alto")

# w1..w5 de la formula de CONTEXT.md 7, en el mismo orden.
PESOS = {
    "crecimiento": 0.40,
    "saturacion": 0.15,
    "riesgo": 0.15,
    "afinidad_poblacion": 0.15,
    "afinidad_zona": 0.15,
}

# riesgo_aceptable del usuario -> multiplicador de riesgo_penal. "bajo" (poco
# tolerante a incertidumbre) penaliza mas fuerte un intervalo P10-P90 ancho;
# "alto" (tolera incertidumbre) casi no la penaliza.
RIESGO_MULTIPLICADOR = {"bajo": 1.5, "medio": 1.0, "alto": 0.5}

# poblacion_objetivo -> pesos (densidad_poblacional_z, densidad_comercial_z)
# para construir afinidad_poblacion. Heuristica razonada, no calibrada (ver
# limitacion en el docstring del modulo): "general" no tiene preferencia,
# "trabajadores" favorece zonas de alta actividad comercial/empleo,
# "jovenes_estudiantes" favorece zonas densas y con vida comercial activa,
# "adultos_mayores" favorece zonas mas pobladas pero MENOS comerciales
# (mas residenciales/tranquilas).
PERFIL_POBLACION_OBJETIVO = {
    "general": (0.0, 0.0),
    "jovenes_estudiantes": (0.3, 0.7),
    "trabajadores": (0.0, 1.0),
    "adultos_mayores": (0.5, -0.5),
}

# Coincidencia tipo_zona[colonia] vs tipo_zona_usuario (funcion `coincide()`
# de CONTEXT.md 7): match exacto = 1, adyacente ("Mixta" vs cualquier otro) =
# 0.5, opuestos (Residencial vs Comercial) = 0.
AFINIDAD_TIPO_ZONA = {
    ("Residencial", "Residencial"): 1.0, ("Residencial", "Mixta"): 0.5, ("Residencial", "Comercial"): 0.0,
    ("Mixta", "Residencial"): 0.5, ("Mixta", "Mixta"): 1.0, ("Mixta", "Comercial"): 0.5,
    ("Comercial", "Residencial"): 0.0, ("Comercial", "Mixta"): 0.5, ("Comercial", "Comercial"): 1.0,
}

# Percentiles de score para las 3 categorias "positivas" (entre las zonas que
# no cayeron en el guardarropa de saturacion/riesgo ni en "Datos
# insuficientes").
PERCENTIL_OPORTUNIDAD_ALTA = 0.80
PERCENTIL_OPORTUNIDAD_MODERADA = 0.50
PERCENTIL_VIGILAR = 0.20

# Guardarropa de "No recomendada": si la oferta actual u la incertidumbre ya
# estan en el quintil mas alto entre las zonas del horizonte pedido, la zona
# se marca como no recomendada sin importar el resto del score - la propia
# CONTEXT.md 7 define esta categoria como "(saturada o alto riesgo)".
UMBRAL_SATURACION_ALTA = 0.80
UMBRAL_RIESGO_ALTO = 0.80

CATEGORIA_DATOS_INSUFICIENTES = "Datos insuficientes"
CATEGORIA_NO_RECOMENDADA = "No recomendada (saturada o alto riesgo)"


def validar_inputs(horizonte_anios: int, poblacion_objetivo: str, tipo_zona_usuario: str, riesgo_aceptable: str) -> None:
    if horizonte_anios not in HORIZONTES_VALIDOS:
        raise ValueError(f"horizonte_anios debe ser uno de {HORIZONTES_VALIDOS}, se recibio {horizonte_anios!r}")
    if poblacion_objetivo not in POBLACIONES_OBJETIVO_VALIDAS:
        raise ValueError(f"poblacion_objetivo debe ser uno de {POBLACIONES_OBJETIVO_VALIDAS}, se recibio {poblacion_objetivo!r}")
    if tipo_zona_usuario not in TIPOS_ZONA_USUARIO_VALIDOS:
        raise ValueError(f"tipo_zona_usuario debe ser uno de {TIPOS_ZONA_USUARIO_VALIDOS}, se recibio {tipo_zona_usuario!r}")
    if riesgo_aceptable not in NIVELES_RIESGO_VALIDOS:
        raise ValueError(f"riesgo_aceptable debe ser uno de {NIVELES_RIESGO_VALIDOS}, se recibio {riesgo_aceptable!r}")


def normalizar_minmax(serie: pd.Series) -> pd.Series:
    """Escala una serie a [0, 1] entre su propio minimo y maximo. Si todos
    los valores son iguales (o la serie esta vacia de datos validos) no hay
    forma de discriminar entre zonas por esta senal, asi que se devuelve un
    valor neutral (0.5) en vez de dividir entre cero."""
    lo, hi = serie.min(), serie.max()
    if pd.isna(hi - lo) or hi - lo == 0:
        return pd.Series(0.5, index=serie.index)
    return (serie - lo) / (hi - lo)


def zscore_estatico(serie: pd.Series) -> pd.Series:
    """Z-score de una serie estatica. Robusto ante no-finitos: un solo +/-inf
    hace que serie.std() sea NaN, y el guardarropa de abajo devolvia entonces
    0.0 para TODAS las zonas - es decir, la senal desaparecia entera sin avisar
    (fue exactamente lo que paso con densidad_comercial_por_mil_hab cuando
    tenia +inf por division entre poblacion 0). Los inf se tratan como dato
    ausente: no participan en media/sigma y salen como 0.0 (neutral)."""
    serie = serie.replace([np.inf, -np.inf], np.nan)
    finitos = serie.dropna()
    if len(finitos) < 2:
        return pd.Series(0.0, index=serie.index)
    media, sigma = finitos.mean(), finitos.std()
    if not sigma or pd.isna(sigma):
        return pd.Series(0.0, index=serie.index)
    return ((serie - media) / sigma).fillna(0.0)


def _nivel_actual_por_colonia() -> pd.Series:
    """Ultimo valor observado (periodo mas reciente con viajes_total > 0) del
    indice de demanda compuesto por colonia - mismo "valor_ultimo" que usa
    src/models/baseline_tendencia.py como punto de partida de la
    extrapolacion."""
    panel = pd.read_csv(PANEL, dtype={"periodo": str})
    activos = panel[panel["viajes_total"] > 0].sort_values("time_idx")
    return activos.groupby("colonia")["indice_demanda_compuesto"].last()


def _componentes_estaticos_por_colonia() -> pd.DataFrame:
    """Senales por colonia que NO dependen del horizonte ni de los inputs
    del usuario: nivel actual, oferta actual (proxy) y los dos z-scores que
    alimentan afinidad_poblacion."""
    nivel_actual = _nivel_actual_por_colonia().rename("nivel_actual")

    indice = pd.read_csv(INDICE_COLONIA)[["colonia", "alcaldia", "km_ciclovia"]].set_index("colonia")
    # Oferta actual (para saturacion_penal): km de ciclovia existente como
    # proxy de infraestructura/madurez ya instalada en la zona - a mas km ya
    # construidos, menor la urgencia marginal de una expansion nueva. No hay
    # un conteo de estaciones Ecobici por colonia procesado todavia (ver
    # datos_bici/Caracteristicas_estaciones.csv, sin integrar) - se documenta
    # como limitacion, igual que otros proxies del proyecto.
    oferta_actual = indice["km_ciclovia"].rename("oferta_actual")
    alcaldia = indice["alcaldia"]

    poblacion = pd.read_csv(POBLACION_COLONIA).set_index("colonia")["poblacion_colonia_2020"]
    densidad_poblacional_z = zscore_estatico(poblacion).rename("densidad_poblacional_z")

    tipo_zona = pd.read_csv(TIPO_ZONA_COLONIA).set_index("colonia")
    # log1p antes del z-score: establecimientos_totales_denue esta muy
    # sesgado (colonias como "Centro" concentran decenas de miles de
    # negocios) - sin esto, esa unica colonia domina la escala del z-score.
    densidad_comercial_z = zscore_estatico(
        np.log1p(tipo_zona["densidad_comercial_por_mil_hab"])
    ).rename("densidad_comercial_z")
    tipo_zona_col = tipo_zona["tipo_zona"].rename("tipo_zona")

    componentes = pd.concat(
        [alcaldia, nivel_actual, oferta_actual, densidad_poblacional_z, densidad_comercial_z, tipo_zona_col],
        axis=1,
    )

    # Bandera de transparencia (CONTEXT.md 8.3, "advertencias de limitacion
    # si aplica"): colonias que faltaban en alguna de las fuentes de arriba
    # ANTES de imputar - se guarda antes del fillna(0.0) siguiente, que ya
    # las deja con valores numericos neutrales pero no distinguibles de una
    # colonia con dato real igual a 0.
    componentes["datos_estaticos_incompletos"] = (
        componentes["oferta_actual"].isna()
        | componentes["densidad_poblacional_z"].isna()
        | componentes["densidad_comercial_z"].isna()
    )

    # zscore_estatico ya rellena NaN internas con 0.0 (neutral, media del
    # z-score), pero esas dos columnas se calcularon sobre un indice mas
    # chico (84/100 colonias) que el universo completo (107, via indice
    # demanda colonia) - el concat de arriba introduce NaN NUEVOS para las
    # colonias que faltaban en cada fuente, y esos no pasaron por el
    # fillna(0.0) de zscore_estatico. Se repite aqui para cubrir tambien esos
    # casos (colonia sin match censal o sin match DENUE, ver
    # indicadores_poblacion_colonia.py / indicadores_tipo_zona.py).
    componentes[["densidad_poblacional_z", "densidad_comercial_z"]] = componentes[
        ["densidad_poblacional_z", "densidad_comercial_z"]
    ].fillna(0.0)
    return componentes


def _proyeccion_por_horizonte(horizonte_anios: int) -> pd.DataFrame:
    """Prediccion P10/P50/P90 por colonia para el horizonte pedido. LightGBM
    (CONTEXT.md 6.3.3) es el modelo primario; si para alguna colonia no tiene
    fila valida se cae al baseline Theil-Sen. Si ninguno de los dos tiene una
    prediccion, la colonia queda con prediccion_p50 = NaN y se categoriza mas
    adelante como 'Datos insuficientes' (nunca como 'baja demanda')."""
    columnas = ["prediccion_p50", "prediccion_p10", "prediccion_p90"]

    lgbm = pd.read_csv(PROYECCION_LGBM)
    lgbm = lgbm[lgbm["horizonte_anios"] == horizonte_anios].set_index("colonia")

    baseline = pd.read_csv(PROYECCION_BASELINE)
    baseline = baseline[baseline["horizonte_anios"] == horizonte_anios].set_index("colonia")

    colonias = lgbm.index.union(baseline.index)
    lgbm = lgbm.reindex(colonias)
    baseline = baseline.reindex(colonias)

    usa_lgbm = lgbm[columnas].notna().all(axis=1)
    proyeccion = baseline[columnas].copy()
    proyeccion.loc[usa_lgbm, columnas] = lgbm.loc[usa_lgbm, columnas]

    tiene_prediccion = proyeccion[columnas].notna().all(axis=1)
    proyeccion["fuente_modelo"] = None
    proyeccion.loc[tiene_prediccion & ~usa_lgbm, "fuente_modelo"] = "baseline_theilsen"
    proyeccion.loc[usa_lgbm, "fuente_modelo"] = "lightgbm"
    return proyeccion


def calcular_scoring(
    horizonte_anios: int,
    poblacion_objetivo: str = "general",
    tipo_zona_usuario: str = "cualquiera",
    riesgo_aceptable: str = "medio",
) -> pd.DataFrame:
    """Punto de entrada del algoritmo de puntuacion (CONTEXT.md 7). Devuelve
    una fila por colonia con su score, categoria y los componentes que lo
    explican (para el panel "por que" de CONTEXT.md 8.3), ordenada de mayor a
    menor score."""
    validar_inputs(horizonte_anios, poblacion_objetivo, tipo_zona_usuario, riesgo_aceptable)

    base = _componentes_estaticos_por_colonia().join(_proyeccion_por_horizonte(horizonte_anios))
    valido = base["prediccion_p50"].notna()

    # crecimiento_norm: cuanto mas crece la prediccion respecto al nivel
    # actual, mejor - normalizado entre las zonas con prediccion valida.
    delta_demanda = base["prediccion_p50"] - base["nivel_actual"]
    base["crecimiento_norm"] = np.where(valido, normalizar_minmax(delta_demanda.where(valido)), np.nan)

    # saturacion_penal: mas oferta actual ya instalada -> mas penalizacion.
    # oferta_actual (km_ciclovia) es NaN para colonias sin poligono de
    # ciclovias (ver indice_compuesto.py) - eso es una AUSENCIA de dato, no
    # evidencia de saturacion ni de lo contrario, asi que se imputa con el
    # PROMEDIO de las colonias con dato real (no con un 0.5 fijo despues de
    # normalizar: la distribucion de km_ciclovia esta muy sesgada - la
    # mayoria de colonias tiene poca ciclovia y unas pocas mucha - asi que
    # 0.5 en la escala normalizada penalizaria a estas colonias MAS que a la
    # colonia promedio real. Se imputa antes de normalizar para que caigan
    # exactamente en el promedio observado, no en un punto arbitrario de una
    # escala sesgada) - CONTEXT.md 7 y 9: nunca confundir falta de datos con
    # una senal negativa.
    oferta_actual_valida = base["oferta_actual"].where(valido)
    oferta_actual_imputada = oferta_actual_valida.fillna(oferta_actual_valida.mean())
    base["saturacion_penal"] = np.where(valido, normalizar_minmax(oferta_actual_imputada), np.nan)

    # riesgo_penal: ancho del intervalo de incertidumbre, escalado por que
    # tan tolerante al riesgo dijo ser el usuario.
    ancho_intervalo = base["prediccion_p90"] - base["prediccion_p10"]
    ancho_intervalo_norm = normalizar_minmax(ancho_intervalo.where(valido))
    base["riesgo_penal"] = np.where(
        valido, (ancho_intervalo_norm * RIESGO_MULTIPLICADOR[riesgo_aceptable]).clip(upper=1.0), np.nan
    )

    # afinidad_poblacion: densidad_poblacional_z / densidad_comercial_z ya
    # vienen imputadas a 0.0 (neutral) para colonias sin match censal/DENUE
    # (ver _componentes_estaticos_por_colonia), asi que esta combinacion
    # nunca es NaN para una zona con prediccion valida.
    peso_pob, peso_com = PERFIL_POBLACION_OBJETIVO[poblacion_objetivo]
    afinidad_poblacion_raw = peso_pob * base["densidad_poblacional_z"] + peso_com * base["densidad_comercial_z"]
    base["afinidad_poblacion"] = np.where(valido, normalizar_minmax(afinidad_poblacion_raw.where(valido)), np.nan)

    if tipo_zona_usuario == "cualquiera":
        base["afinidad_zona"] = np.where(valido, 1.0, np.nan)
    else:
        objetivo_cap = tipo_zona_usuario.capitalize()
        base["afinidad_zona"] = base["tipo_zona"].map(
            lambda z: AFINIDAD_TIPO_ZONA.get((objetivo_cap, z), 0.5)  # "Sin clasificar" -> neutral (sin dato, no se penaliza)
        )
        base.loc[~valido, "afinidad_zona"] = np.nan

    base["datos_zona_incompletos"] = base["datos_estaticos_incompletos"] | base["tipo_zona"].isna()

    base["score"] = (
        PESOS["crecimiento"] * base["crecimiento_norm"]
        - PESOS["saturacion"] * base["saturacion_penal"]
        - PESOS["riesgo"] * base["riesgo_penal"]
        + PESOS["afinidad_poblacion"] * base["afinidad_poblacion"]
        + PESOS["afinidad_zona"] * base["afinidad_zona"]
    )

    base["categoria"], base["motivo_categoria"] = _categorizar(base, valido)
    base["horizonte_anios"] = horizonte_anios

    columnas_salida = [
        "alcaldia", "horizonte_anios", "nivel_actual", "prediccion_p50", "prediccion_p10", "prediccion_p90",
        "fuente_modelo", "tipo_zona", "crecimiento_norm", "saturacion_penal", "riesgo_penal",
        "afinidad_poblacion", "afinidad_zona", "score", "categoria", "motivo_categoria",
        "datos_zona_incompletos",
    ]
    return base[columnas_salida].sort_values("score", ascending=False).rename_axis("colonia").reset_index()


def _categorizar(base: pd.DataFrame, valido: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Devuelve (categoria, motivo_categoria).

    `motivo_categoria` existe porque a "No recomendada (saturada o alto
    riesgo)" se llega por DOS caminos muy distintos, y el nombre de la
    categoria solo describe el primero:

      1. el guardarropa explicito - la zona esta en el quintil superior de
         oferta ya instalada o de incertidumbre. Ahi el nombre es literal.
      2. el corte de percentil - la zona quedo en el quintil INFERIOR del
         score. Con los datos actuales esto son ~22 de las ~23 colonias
         marcadas "No recomendada", y la mayoria no esta saturada ni es
         especialmente incierta: simplemente puntuo bajo. Afirmarles
         "saturada o alto riesgo" es una conclusion que el dato no sostiene.

    Las 5 categorias de CONTEXT.md 7 se mantienen intactas (son requisito de
    la rubrica); lo que se agrega es el porque, para que la app pueda decirlo
    en vez de dejar que el usuario lea una causa inventada."""
    categoria = pd.Series(CATEGORIA_DATOS_INSUFICIENTES, index=base.index)
    motivo = pd.Series("Ningun modelo tiene prediccion para esta colonia en este horizonte", index=base.index)

    saturada = valido & (base["saturacion_penal"] >= UMBRAL_SATURACION_ALTA)
    riesgosa = valido & (base["riesgo_penal"] >= UMBRAL_RIESGO_ALTO)
    no_recomendada = saturada | riesgosa
    categoria.loc[no_recomendada] = CATEGORIA_NO_RECOMENDADA
    motivo.loc[saturada & ~riesgosa] = "Oferta de ciclovia ya instalada en el quintil mas alto (saturacion)"
    motivo.loc[riesgosa & ~saturada] = "Incertidumbre del pronostico en el quintil mas alto (alto riesgo)"
    motivo.loc[saturada & riesgosa] = "Saturacion y alto riesgo simultaneos"

    pendientes = valido & ~no_recomendada
    if pendientes.any():
        score_pendientes = base.loc[pendientes, "score"]
        p_alta = score_pendientes.quantile(PERCENTIL_OPORTUNIDAD_ALTA)
        p_moderada = score_pendientes.quantile(PERCENTIL_OPORTUNIDAD_MODERADA)
        p_vigilar = score_pendientes.quantile(PERCENTIL_VIGILAR)

        def bucket(score: float) -> str:
            if score >= p_alta:
                return "Oportunidad alta"
            if score >= p_moderada:
                return "Oportunidad moderada"
            if score >= p_vigilar:
                return "Vigilar"
            return CATEGORIA_NO_RECOMENDADA

        categoria.loc[pendientes] = score_pendientes.map(bucket)
        motivo.loc[pendientes] = "Corte por percentil del score frente a las demas colonias"
        cola = pendientes & (categoria == CATEGORIA_NO_RECOMENDADA)
        motivo.loc[cola] = (
            "Quintil inferior del score (NO esta saturada ni tiene alto riesgo: "
            "puntuo bajo frente a las demas colonias)"
        )

    return categoria, motivo


def main() -> None:
    pd.set_option("display.width", 120)
    ejemplos = [
        dict(horizonte_anios=3, poblacion_objetivo="general", tipo_zona_usuario="cualquiera", riesgo_aceptable="medio"),
        dict(horizonte_anios=3, poblacion_objetivo="trabajadores", tipo_zona_usuario="comercial", riesgo_aceptable="bajo"),
        dict(horizonte_anios=5, poblacion_objetivo="adultos_mayores", tipo_zona_usuario="residencial", riesgo_aceptable="alto"),
    ]
    for inputs in ejemplos:
        resultado = calcular_scoring(**inputs)
        print(f"\n=== {inputs} ===")
        print(resultado["categoria"].value_counts())
        print("\nTop 5:")
        print(
            resultado.head(5)[["colonia", "alcaldia", "score", "categoria", "tipo_zona", "fuente_modelo"]].to_string(index=False)
        )


if __name__ == "__main__":
    main()
