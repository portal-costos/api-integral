from io import BytesIO
from pathlib import Path

import pandas as pd

from app.routers.arca import _build_result_workbook
from app.services.arca_engine import MotorARCA, df_tasas_a_tramos, sugerir_mapeo
from app.services.arca_rates import cargar_tasas_respaldo

BASE = Path(__file__).resolve().parents[1]


def test_sugerencia_de_columnas():
    mapping = sugerir_mapeo([
        "Fecha de Vencimiento",
        "Fecha de Pago del Capital",
        "Importe del Capital",
        "Fecha de Pago de Intereses",
    ])
    assert mapping["fecha_vencimiento"] == "Fecha de Vencimiento"
    assert mapping["importe_capital"] == "Importe del Capital"


def test_genera_libro_con_cuatro_hojas():
    source = pd.read_excel(BASE / "ejemplo_arca.xlsx", sheet_name="Obligaciones")
    rates = cargar_tasas_respaldo(BASE / "data" / "arca_rates_fallback.json")
    engine = MotorARCA(df_tasas_a_tramos(rates))
    payload, summary = _build_result_workbook(
        source,
        rates,
        engine,
        "Fecha de Vencimiento",
        "Fecha de Pago del Capital",
        "Importe del Capital",
        "Fecha de Pago de Intereses",
    )
    assert summary["total_rows"] == 4
    assert summary["ok_rows"] == 3
    assert summary["error_rows"] == 1
    excel = pd.ExcelFile(BytesIO(payload))
    assert set(excel.sheet_names) == {
        "Intereses ARCA",
        "Tasas usadas",
        "Resumen",
        "Detalle por tramos",
    }
