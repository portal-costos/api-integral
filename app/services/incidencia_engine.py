"""Motor de asignación percentílica e incidencia tarifaria.

El módulo recibe una base de hogares EPH y siete parámetros zonales. No depende
 de la interfaz web: puede probarse de forma aislada y reutilizarse en otros
 módulos del portal.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd


ZONAL_COUNT = 7
PERCENTILES_EPH = list(range(0, 101))
PERCENTILES_ZONALES = [0, 10, 25, 50, 75, 90, 100]


@dataclass(slots=True)
class IncidenciaResultado:
    resumen: dict[str, Any]
    zonales: list[dict[str, Any]]
    percentiles_eph: list[dict[str, Any]]
    percentiles_zonales: list[dict[str, Any]]
    advertencias: list[str]
    analisis: list[str]
    metodologia: list[str]
    base_procesada: pd.DataFrame
    parametros: pd.DataFrame


def normalizar_nombre(valor: Any) -> str:
    texto = str(valor or "").strip().lower()
    texto = "".join(
        caracter for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    )
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _buscar_columna(columnas: Iterable[str], candidatos: list[str]) -> str:
    reales = [str(c) for c in columnas]
    normalizadas = {normalizar_nombre(c): c for c in reales}
    for candidato in candidatos:
        clave = normalizar_nombre(candidato)
        if clave in normalizadas:
            return normalizadas[clave]
    for candidato in candidatos:
        clave = normalizar_nombre(candidato)
        for normalizada, real in normalizadas.items():
            if clave and (clave in normalizada or normalizada in clave):
                return real
    return ""


def sugerir_mapeo(columnas: Iterable[str]) -> dict[str, str]:
    columnas = [str(c) for c in columnas]
    return {
        "ipcf": _buscar_columna(
            columnas,
            [
                "IPCF",
                "ingreso per capita familiar",
                "ingreso per capita del hogar",
                "ingreso per cápita del hogar",
                "ingreso per capita",
            ],
        ),
        "itf": _buscar_columna(
            columnas,
            [
                "ITF",
                "ingreso total familiar",
                "ingreso total del hogar familiar",
                "ingreso total del hogar/familiar",
                "ingreso familiar",
            ],
        ),
        "pondih": _buscar_columna(
            columnas,
            [
                "PONDIH",
                "ponderador especifico de ingresos",
                "ponderador de ingresos",
                "ponderador",
                "pondii",
            ],
        ),
        "miembros": _buscar_columna(
            columnas,
            ["IX_TOT", "cantidad de integrantes", "miembros", "habitantes per casa"],
        ),
        "codusu": _buscar_columna(columnas, ["CODUSU", "codigo usuario", "código usuario"]),
        "nro_hogar": _buscar_columna(columnas, ["NRO_HOGAR", "numero hogar", "número hogar"]),
        "anio": _buscar_columna(columnas, ["ANO4", "AÑO", "ANIO", "año encuesta"]),
        "trimestre": _buscar_columna(columnas, ["TRIMESTRE", "trimestre encuesta"]),
        "aglomerado": _buscar_columna(columnas, ["AGLOMERADO", "aglomerado eph"]),
        "decil_itf": _buscar_columna(columnas, ["ADECIFR", "decil itf"]),
        "decil_ipcf": _buscar_columna(columnas, ["ADECCFR", "decil ipcf"]),
    }


def _numero(valor: Any) -> Optional[float]:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass
    if isinstance(valor, (int, float, np.number)) and not isinstance(valor, bool):
        numero = float(valor)
        return numero if math.isfinite(numero) else None
    texto = str(valor).strip().replace("\u00a0", "").replace("$", "").replace("%", "")
    if not texto:
        return None
    if "," in texto and "." in texto:
        # Convención argentina: 1.234.567,89
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    else:
        partes = texto.split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            texto = texto.replace(".", "")
    try:
        numero = float(texto)
        return numero if math.isfinite(numero) else None
    except ValueError:
        return None


def _serie_numerica(serie: pd.Series) -> pd.Series:
    return serie.map(_numero).astype(float)


def _valor_json(valor: Any) -> Any:
    if valor is None:
        return None
    if isinstance(valor, (np.integer,)):
        return int(valor)
    if isinstance(valor, (np.floating,)):
        valor = float(valor)
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, pd.Timestamp):
        return valor.isoformat()
    return valor


def _cuantil_ponderado(valores: np.ndarray, pesos: np.ndarray, cuantiles: Iterable[float]) -> list[Optional[float]]:
    mascara = np.isfinite(valores) & np.isfinite(pesos) & (pesos > 0)
    valores = valores[mascara]
    pesos = pesos[mascara]
    if valores.size == 0 or pesos.sum() <= 0:
        return [None for _ in cuantiles]
    orden = np.argsort(valores, kind="mergesort")
    valores = valores[orden]
    pesos = pesos[orden]
    acumulado = np.cumsum(pesos)
    total = float(acumulado[-1])
    salida: list[Optional[float]] = []
    for q in cuantiles:
        q = min(1.0, max(0.0, float(q)))
        if q <= 0:
            salida.append(float(valores[0]))
            continue
        if q >= 1:
            salida.append(float(valores[-1]))
            continue
        indice = int(np.searchsorted(acumulado, q * total, side="left"))
        indice = min(indice, valores.size - 1)
        salida.append(float(valores[indice]))
    return salida


def _validar_zonales(zonales: list[dict[str, Any]]) -> pd.DataFrame:
    if len(zonales) != ZONAL_COUNT:
        raise ValueError("Deben informarse exactamente siete zonales.")
    filas: list[dict[str, Any]] = []
    for indice, item in enumerate(zonales, start=1):
        porcentaje = _numero(item.get("porcentaje"))
        tarifa = _numero(item.get("tarifa"))
        tarifa_sin = _numero(item.get("tarifa_sin_impuestos"))
        if porcentaje is None or porcentaje < 0:
            raise ValueError(f"El porcentaje del Zonal {indice} no es válido.")
        if tarifa is None or tarifa < 0:
            raise ValueError(f"La tarifa promedio del Zonal {indice} no es válida.")
        if tarifa_sin is None or tarifa_sin < 0:
            raise ValueError(f"La tarifa sin impuestos del Zonal {indice} no es válida.")
        filas.append(
            {
                "zonal": str(item.get("zonal") or f"Zonal {indice}"),
                "porcentaje_original": float(porcentaje) / 100.0,
                "tarifa": float(tarifa),
                "tarifa_sin_impuestos": float(tarifa_sin),
            }
        )
    frame = pd.DataFrame(filas)
    total = float(frame["porcentaje_original"].sum())
    if total <= 0:
        raise ValueError("La suma de porcentajes zonales debe ser mayor que cero.")
    frame["porcentaje_normalizado"] = frame["porcentaje_original"] / total
    frame["percentil_final"] = frame["porcentaje_normalizado"].cumsum()
    frame["percentil_inicial"] = frame["percentil_final"].shift(fill_value=0.0)
    frame.loc[frame.index[-1], "percentil_final"] = 1.0
    return frame


def _filtrar_aglomerado(df: pd.DataFrame, columna: str, valor: str) -> tuple[pd.DataFrame, int]:
    if not columna or columna not in df.columns or str(valor).strip() == "":
        return df, 0
    antes = len(df)
    valor_num = _numero(valor)
    serie_num = _serie_numerica(df[columna])
    if valor_num is not None and serie_num.notna().any():
        filtrado = df[serie_num == float(valor_num)].copy()
    else:
        objetivo = normalizar_nombre(valor)
        filtrado = df[df[columna].map(normalizar_nombre) == objetivo].copy()
    return filtrado, antes - len(filtrado)


def procesar_incidencia(
    source_df: pd.DataFrame,
    mapping: dict[str, str],
    zonales: list[dict[str, Any]],
    *,
    aglomerado_valor: str = "13",
    eliminar_duplicados: bool = False,
) -> IncidenciaResultado:
    requeridas = {"ipcf": "IPCF", "itf": "ITF", "pondih": "PONDIH"}
    faltantes = [etiqueta for clave, etiqueta in requeridas.items() if not mapping.get(clave)]
    if faltantes:
        raise ValueError(f"Falta mapear: {', '.join(faltantes)}.")
    columnas_inexistentes = [
        columna for columna in mapping.values() if columna and columna not in source_df.columns
    ]
    if columnas_inexistentes:
        raise ValueError(f"Columnas no encontradas en el Excel: {columnas_inexistentes}")

    parametros = _validar_zonales(zonales)
    df = source_df.copy()
    filas_originales = int(len(df))
    df, excluidas_aglomerado = _filtrar_aglomerado(
        df, mapping.get("aglomerado", ""), aglomerado_valor
    )
    filas_post_aglomerado = int(len(df))

    # Columnas normalizadas internas. Se preservan las originales para el Excel final.
    df["__IPCF"] = _serie_numerica(df[mapping["ipcf"]])
    df["__ITF"] = _serie_numerica(df[mapping["itf"]])
    df["__PONDIH"] = _serie_numerica(df[mapping["pondih"]])
    if mapping.get("miembros"):
        df["__MIEMBROS"] = _serie_numerica(df[mapping["miembros"]])
    else:
        df["__MIEMBROS"] = np.nan

    mascara_valida = (
        df["__IPCF"].notna()
        & df["__ITF"].notna()
        & df["__PONDIH"].notna()
        & (df["__PONDIH"] > 0)
    )
    filas_invalidas = int((~mascara_valida).sum())
    df = df[mascara_valida].copy()

    duplicados_detectados = 0
    claves_duplicado = [mapping.get("codusu", ""), mapping.get("nro_hogar", "")]
    claves_duplicado = [c for c in claves_duplicado if c]
    if claves_duplicado:
        duplicados_detectados = int(df.duplicated(subset=claves_duplicado, keep="first").sum())
        if eliminar_duplicados and duplicados_detectados:
            df = df.drop_duplicates(subset=claves_duplicado, keep="first").copy()

    if df.empty:
        raise ValueError("No quedaron hogares válidos después de aplicar los filtros.")

    orden_columnas = ["__IPCF", "__ITF"]
    for clave in ("codusu", "nro_hogar"):
        columna = mapping.get(clave, "")
        if columna:
            orden_columnas.append(columna)
    df = df.sort_values(orden_columnas, kind="mergesort").reset_index(drop=True)

    total_ponderado = float(df["__PONDIH"].sum())
    if total_ponderado <= 0:
        raise ValueError("La suma de PONDIH debe ser mayor que cero.")

    df["Peso relativo hogar"] = df["__PONDIH"] / total_ponderado
    df["Percentil final"] = df["Peso relativo hogar"].cumsum()
    df["Percentil inicial"] = df["Percentil final"].shift(fill_value=0.0)
    df.loc[df.index[-1], "Percentil final"] = 1.0
    df["Percentil medio"] = (df["Percentil inicial"] + df["Percentil final"]) / 2.0
    df["Dummy ingreso positivo"] = (df["__ITF"] > 0).astype(int)
    df["1/ITF"] = np.where(df["__ITF"] > 0, 1.0 / df["__ITF"], 0.0)

    inicio_h = df["Percentil inicial"].to_numpy(dtype=float)[:, None]
    final_h = df["Percentil final"].to_numpy(dtype=float)[:, None]
    inicio_z = parametros["percentil_inicial"].to_numpy(dtype=float)[None, :]
    final_z = parametros["percentil_final"].to_numpy(dtype=float)[None, :]
    solapes = np.maximum(0.0, np.minimum(final_h, final_z) - np.maximum(inicio_h, inicio_z))

    for indice in range(ZONAL_COUNT):
        df[f"Solape Z{indice + 1}"] = solapes[:, indice]

    advertencias: list[str] = []
    total_original_pct = float(parametros["porcentaje_original"].sum())
    if abs(total_original_pct - 1.0) > 1e-9:
        advertencias.append(
            f"Los porcentajes informados suman {total_original_pct * 100:.4f} %. "
            "El sistema los normalizó proporcionalmente para que sumen 100 %."
        )
    if duplicados_detectados:
        accion = "se eliminaron" if eliminar_duplicados else "se conservaron"
        advertencias.append(
            f"Se detectaron {duplicados_detectados} filas repetidas según las claves de hogar; {accion}."
        )
    if not mapping.get("miembros"):
        advertencias.append(
            "No se mapeó IX_TOT/cantidad de miembros; el promedio de integrantes no se calcula."
        )
    if not mapping.get("aglomerado"):
        advertencias.append(
            "No se mapeó AGLOMERADO. Se supone que el Excel ya contiene únicamente el universo deseado."
        )

    itf = df["__ITF"].to_numpy(dtype=float)
    ipcf = df["__IPCF"].to_numpy(dtype=float)
    miembros = df["__MIEMBROS"].to_numpy(dtype=float)
    positivo = (itf > 0).astype(float)
    sin_ingreso = (itf <= 0).astype(float)
    inversa_itf = np.zeros_like(itf, dtype=float)
    np.divide(1.0, itf, out=inversa_itf, where=itf > 0)

    resultados_zonales: list[dict[str, Any]] = []
    percentiles_zonales: list[dict[str, Any]] = []
    for indice, parametro in parametros.iterrows():
        pesos = solapes[:, indice]
        participacion = float(parametro["porcentaje_normalizado"])
        denominador = float(pesos.sum())
        # Debe coincidir con la participación, pero se usa la suma efectiva por estabilidad numérica.
        if denominador <= 0:
            raise ValueError(f"El {parametro['zonal']} no recibe observaciones ponderadas.")

        itf_medio = float(np.sum(itf * pesos) / denominador)
        ipcf_medio = float(np.sum(ipcf * pesos) / denominador)
        miembros_validos = np.isfinite(miembros)
        miembros_den = float(np.sum(pesos[miembros_validos]))
        miembros_medio = (
            float(np.sum(miembros[miembros_validos] * pesos[miembros_validos]) / miembros_den)
            if miembros_den > 0
            else None
        )
        peso_positivo = float(np.sum(pesos * positivo))
        proporcion_sin_ingreso = float(np.sum(pesos * sin_ingreso) / denominador)
        tarifa = float(parametro["tarifa"])
        tarifa_sin = float(parametro["tarifa_sin_impuestos"])
        incidencia_general = tarifa / itf_medio if itf_medio > 0 else None
        incidencia_general_sin = tarifa_sin / itf_medio if itf_medio > 0 else None
        carga_media = (
            tarifa * float(np.sum(pesos * inversa_itf)) / peso_positivo
            if peso_positivo > 0
            else None
        )
        carga_media_sin = (
            tarifa_sin * float(np.sum(pesos * inversa_itf)) / peso_positivo
            if peso_positivo > 0
            else None
        )

        cuantiles = [p / 100.0 for p in PERCENTILES_ZONALES]
        itf_q = _cuantil_ponderado(itf, pesos, cuantiles)
        ipcf_q = _cuantil_ponderado(ipcf, pesos, cuantiles)
        for p, q_itf, q_ipcf in zip(PERCENTILES_ZONALES, itf_q, ipcf_q):
            percentiles_zonales.append(
                {
                    "zonal": parametro["zonal"],
                    "percentil": p,
                    "itf": q_itf,
                    "ipcf": q_ipcf,
                }
            )

        resultados_zonales.append(
            {
                "zonal": parametro["zonal"],
                "porcentaje_original": float(parametro["porcentaje_original"]),
                "porcentaje_normalizado": participacion,
                "percentil_inicial": float(parametro["percentil_inicial"]),
                "percentil_final": float(parametro["percentil_final"]),
                "tarifa": tarifa,
                "tarifa_sin_impuestos": tarifa_sin,
                "itf_medio": itf_medio,
                "ipcf_medio": ipcf_medio,
                "miembros_promedio": miembros_medio,
                "incidencia_general": incidencia_general,
                "carga_media_positivos": carga_media,
                "incidencia_general_sin_impuestos": incidencia_general_sin,
                "carga_media_positivos_sin_impuestos": carga_media_sin,
                "proporcion_sin_ingreso": proporcion_sin_ingreso,
                "hogares_expandidos": denominador * total_ponderado,
                "itf_mediana": itf_q[PERCENTILES_ZONALES.index(50)],
                "ipcf_mediana": ipcf_q[PERCENTILES_ZONALES.index(50)],
            }
        )

    percentiles_eph: list[dict[str, Any]] = []
    cuantiles_eph = [p / 100.0 for p in PERCENTILES_EPH]
    pesos_eph = df["__PONDIH"].to_numpy(dtype=float)
    itf_q_eph = _cuantil_ponderado(itf, pesos_eph, cuantiles_eph)
    ipcf_q_eph = _cuantil_ponderado(ipcf, pesos_eph, cuantiles_eph)
    for p, q_itf, q_ipcf in zip(PERCENTILES_EPH, itf_q_eph, ipcf_q_eph):
        percentiles_eph.append({"percentil": p, "itf": q_itf, "ipcf": q_ipcf})

    shares = np.array([z["porcentaje_normalizado"] for z in resultados_zonales], dtype=float)
    tarifas = np.array([z["tarifa"] for z in resultados_zonales], dtype=float)
    tarifas_sin = np.array([z["tarifa_sin_impuestos"] for z in resultados_zonales], dtype=float)
    incidencias = np.array([z["incidencia_general"] or 0 for z in resultados_zonales], dtype=float)
    cargas = np.array([z["carga_media_positivos"] or 0 for z in resultados_zonales], dtype=float)
    incidencias_sin = np.array(
        [z["incidencia_general_sin_impuestos"] or 0 for z in resultados_zonales], dtype=float
    )
    cargas_sin = np.array(
        [z["carga_media_positivos_sin_impuestos"] or 0 for z in resultados_zonales], dtype=float
    )

    periodos: list[str] = []
    if mapping.get("anio") and mapping.get("trimestre"):
        pares = (
            df[[mapping["anio"], mapping["trimestre"]]]
            .drop_duplicates()
            .astype(str)
            .values.tolist()
        )
        periodos = [f"{a} · T{t}" for a, t in pares]

    resumen = {
        "filas_archivo": filas_originales,
        "filas_post_aglomerado": filas_post_aglomerado,
        "filas_utilizadas": int(len(df)),
        "filas_excluidas_aglomerado": int(excluidas_aglomerado),
        "filas_invalidas_o_pondih_cero": filas_invalidas,
        "duplicados_detectados": duplicados_detectados,
        "duplicados_eliminados": duplicados_detectados if eliminar_duplicados else 0,
        "hogares_expandidos": total_ponderado,
        "periodos": periodos,
        "aglomerado_filtro": aglomerado_valor if mapping.get("aglomerado") else "No aplicado",
        "tarifa_promedio_ponderada": float(np.sum(shares * tarifas)),
        "tarifa_sin_impuestos_promedio_ponderada": float(np.sum(shares * tarifas_sin)),
        "itf_medio_general": float(np.sum(itf * df["Peso relativo hogar"].to_numpy())),
        "ipcf_medio_general": float(np.sum(ipcf * df["Peso relativo hogar"].to_numpy())),
        "incidencia_general_ponderada": float(np.sum(shares * incidencias)),
        "carga_media_positivos_ponderada": float(np.sum(shares * cargas)),
        "incidencia_general_sin_impuestos_ponderada": float(np.sum(shares * incidencias_sin)),
        "carga_media_positivos_sin_impuestos_ponderada": float(np.sum(shares * cargas_sin)),
        "proporcion_total_sin_ingreso": float(
            np.sum(df["Peso relativo hogar"].to_numpy() * sin_ingreso)
        ),
        "zonal_mayor_incidencia": max(
            resultados_zonales, key=lambda z: z["incidencia_general"] or -1
        )["zonal"],
        "zonal_menor_incidencia": min(
            resultados_zonales, key=lambda z: z["incidencia_general"] if z["incidencia_general"] is not None else math.inf
        )["zonal"],
    }

    # Nombres amigables de las columnas calculadas y base final de auditoría.
    base_salida = df.copy()
    base_salida.insert(0, "Orden percentílico", np.arange(1, len(base_salida) + 1))
    base_salida["IPCF utilizado"] = base_salida["__IPCF"]
    base_salida["ITF utilizado"] = base_salida["__ITF"]
    base_salida["PONDIH utilizado"] = base_salida["__PONDIH"]
    base_salida["Miembros utilizados"] = base_salida["__MIEMBROS"]
    base_salida = base_salida.drop(columns=["__IPCF", "__ITF", "__PONDIH", "__MIEMBROS"])

    mayor = max(resultados_zonales, key=lambda z: z["incidencia_general"] or -1)
    menor = min(
        resultados_zonales,
        key=lambda z: z["incidencia_general"] if z["incidencia_general"] is not None else math.inf,
    )
    brecha_impuestos = (
        float(resumen["incidencia_general_ponderada"])
        - float(resumen["incidencia_general_sin_impuestos_ponderada"])
    )
    analisis = [
        f"La incidencia general ponderada de la tarifa con impuestos es {float(resumen['incidencia_general_ponderada']) * 100:.2f} % del ITF medio imputado.",
        f"Sin impuestos, la incidencia ponderada desciende a {float(resumen['incidencia_general_sin_impuestos_ponderada']) * 100:.2f} %, una diferencia de {brecha_impuestos * 100:.2f} puntos porcentuales.",
        f"{mayor['zonal']} presenta la mayor incidencia general ({float(mayor['incidencia_general']) * 100:.2f} %), mientras que {menor['zonal']} presenta la menor ({float(menor['incidencia_general']) * 100:.2f} %).",
        f"La carga media entre hogares con ingresos positivos es {float(resumen['carga_media_positivos_ponderada']) * 100:.2f} %, superior a la incidencia sobre el ITF medio porque es más sensible a los hogares de ingresos bajos.",
        f"Los hogares con ITF menor o igual a cero representan {float(resumen['proporcion_total_sin_ingreso']) * 100:.2f} % de la distribución ponderada y se informan por separado.",
    ]

    metodologia = [
        "Se conserva el orden socioeconómico Zonal 1 a Zonal 7, de menor a mayor ingreso.",
        "Los hogares se ordenan por IPCF ascendente; ITF, CODUSU y NRO_HOGAR actúan como desempate cuando están disponibles.",
        "PONDIH se normaliza para construir una distribución acumulada entre 0 y 100 %.",
        "Los porcentajes de usuarios definen el ancho de cada tramo zonal y se normalizan si no suman exactamente 100 %.",
        "Cuando un hogar cruza un corte zonal, su ponderación se fracciona con la fórmula de solape entre intervalos.",
        "La incidencia general es Tarifa / ITF medio imputado. La carga media calcula Tarifa / ITF hogar por hogar y luego promedia entre ingresos positivos.",
        "Los hogares con ITF menor o igual a cero se informan por separado y no integran la carga media de ingresos positivos.",
        "La correspondencia entre zonal e ingreso es un supuesto de imputación; la EPH no identifica el zonal tarifario real del hogar.",
    ]

    # Convierte numpy a Python nativo para respuestas JSON limpias.
    resumen = {k: _valor_json(v) for k, v in resumen.items()}
    resultados_zonales = [
        {k: _valor_json(v) for k, v in fila.items()} for fila in resultados_zonales
    ]
    percentiles_eph = [
        {k: _valor_json(v) for k, v in fila.items()} for fila in percentiles_eph
    ]
    percentiles_zonales = [
        {k: _valor_json(v) for k, v in fila.items()} for fila in percentiles_zonales
    ]

    return IncidenciaResultado(
        resumen=resumen,
        zonales=resultados_zonales,
        percentiles_eph=percentiles_eph,
        percentiles_zonales=percentiles_zonales,
        advertencias=advertencias,
        analisis=analisis,
        metodologia=metodologia,
        base_procesada=base_salida,
        parametros=parametros,
    )
