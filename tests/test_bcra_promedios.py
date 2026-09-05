from datetime import date

import main


def test_bcra_parser_promedia_cantidad_real_de_observaciones():
    payload = {
        "results": [{
            "detalle": [
                {"fecha": "2026-02-01", "valor": 10},
                {"fecha": "2026-02-02", "valor": 20},
                {"fecha": "2026-02-28", "valor": 30},
                {"fecha": "2026-03-03", "valor": 40},
                {"fecha": "2026-03-10", "valor": 50},
            ]
        }]
    }
    frame = main._bcra_daily_frame_from_payload(
        payload,
        value_column="TEST",
        source_name="TEST",
        minimum=0,
        maximum=100,
    )
    feb = frame[frame["Fecha"].dt.month.eq(2)].iloc[0]
    mar = frame[frame["Fecha"].dt.month.eq(3)].iloc[0]
    assert feb["Promedio_mensual"] == 20
    assert feb["Observaciones_mes"] == 3
    assert mar["Promedio_mensual"] == 45
    assert mar["Observaciones_mes"] == 2


def test_encabezados_reales_de_google_sheets():
    headers = [
        "Índice para Contratos de Locación\nPROMEDIO MENSUAL",
        "CER\n(Coeficiente de Estabilización de Referencia)\nPROMEDIO MENSUAL",
        "Tasa BADLAR (en pesos de bancos privados (en % n.a.) - BCRA",
        "Tasa BADLAR (en pesos de bancos privados (en % e.a.) - BCRA",
    ]
    assert main._header_index(headers, ["indice", "contratos", "locacion", "promedio", "mensual"]) == 1
    assert main._header_index(headers, ["cer", "coeficiente", "estabilizacion", "referencia", "promedio", "mensual"]) == 2
    assert main._header_index(headers, ["badlar", "bancos privados", "na"], ["ea"]) == 3
    assert main._header_index(headers, ["badlar", "bancos privados", "ea"]) == 4
