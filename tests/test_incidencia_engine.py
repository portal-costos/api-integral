import math

import pandas as pd

from app.services.incidencia_engine import procesar_incidencia, sugerir_mapeo


def _zonales():
    return [
        {"zonal": f"Zonal {i}", "porcentaje": p, "tarifa": 10000 * i, "tarifa_sin_impuestos": 7000 * i}
        for i, p in enumerate([10, 20, 20, 20, 15, 10, 5], start=1)
    ]


def test_sugerir_mapeo_reconoce_nombres_amigables():
    mapping = sugerir_mapeo(
        ["Ingreso per cápita del hogar", "Ingreso total del hogar/familiar", "PONDIH", "Habitantes per Casa"]
    )
    assert mapping["ipcf"] == "Ingreso per cápita del hogar"
    assert mapping["itf"] == "Ingreso total del hogar/familiar"
    assert mapping["pondih"] == "PONDIH"
    assert mapping["miembros"] == "Habitantes per Casa"


def test_asignacion_percentil_suma_uno_y_calcula_incidencia():
    df = pd.DataFrame(
        {
            "IPCF": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
            "ITF": [200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000],
            "PONDIH": [1] * 10,
            "IX_TOT": [2] * 10,
            "AGLOMERADO": [13] * 10,
            "CODUSU": [f"H{i}" for i in range(10)],
            "NRO_HOGAR": [1] * 10,
        }
    )
    result = procesar_incidencia(
        df,
        {
            "ipcf": "IPCF",
            "itf": "ITF",
            "pondih": "PONDIH",
            "miembros": "IX_TOT",
            "aglomerado": "AGLOMERADO",
            "codusu": "CODUSU",
            "nro_hogar": "NRO_HOGAR",
        },
        _zonales(),
        aglomerado_valor="13",
    )
    assert len(result.zonales) == 7
    assert math.isclose(sum(z["porcentaje_normalizado"] for z in result.zonales), 1.0)
    assert math.isclose(result.base_procesada[[f"Solape Z{i}" for i in range(1, 8)]].to_numpy().sum(), 1.0)
    assert result.zonales[0]["itf_medio"] == 200
    assert result.zonales[0]["incidencia_general"] == 50.0
    assert len(result.percentiles_eph) == 101
    assert len(result.percentiles_zonales) == 49


def test_hogares_sin_ingreso_se_conservan_y_no_rompen_carga_media():
    df = pd.DataFrame({"IPCF": [0, 100], "ITF": [0, 200], "PONDIH": [1, 1]})
    result = procesar_incidencia(
        df,
        {"ipcf": "IPCF", "itf": "ITF", "pondih": "PONDIH"},
        _zonales(),
        aglomerado_valor="",
    )
    assert result.resumen["filas_utilizadas"] == 2
    assert result.resumen["proporcion_total_sin_ingreso"] == 0.5
    assert result.zonales[0]["carga_media_positivos"] is None
