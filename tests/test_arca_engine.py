from pathlib import Path

import pandas as pd

from app.services.arca_engine import MotorARCA, df_tasas_a_tramos, normalizar_numero, parse_fecha
from app.services.arca_rates import cargar_tasas_respaldo

BASE = Path(__file__).resolve().parents[1]


def motor():
    rates = cargar_tasas_respaldo(BASE / "data" / "arca_rates_fallback.json")
    return MotorARCA(df_tasas_a_tramos(rates))


def test_normaliza_fechas_y_numeros():
    assert str(parse_fecha("31/01/2025")) == "2025-01-31"
    assert str(parse_fecha("2025-01-31")) == "2025-01-31"
    assert normalizar_numero("1.234,56") == 1234.56
    assert normalizar_numero("1234.56") == 1234.56


def test_calculo_valido_genera_detalle():
    result = motor().calcular_fila("10/01/2025", "10/07/2025", "100.000,00")
    assert result.ok is True
    assert result.intereses_total > 0
    assert result.dias_transcurridos > 0
    assert len(result.detalle) >= 2
    assert all(item.norma for item in result.detalle)


def test_capitalizacion_opcional():
    result = motor().calcular_fila("10/01/2025", "10/03/2025", 100000, "10/05/2025")
    assert result.ok is True
    assert result.intereses_resarcitorios > 0
    assert result.intereses_capitalizados > 0
    assert result.intereses_total == round(
        result.intereses_resarcitorios + result.intereses_capitalizados, 2
    )


def test_validaciones():
    assert motor().calcular_fila("fecha mala", "10/03/2025", 1000).ok is False
    assert motor().calcular_fila("10/03/2025", "10/03/2025", 1000).ok is False
    assert motor().calcular_fila("10/03/2025", "11/03/2025", 0).ok is False
