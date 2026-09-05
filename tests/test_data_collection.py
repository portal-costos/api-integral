from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd

import main


class FakeResponse:
    def __init__(self, *, content: bytes = b"", payload=None):
        self.content = content
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_parse_number_locale_preserves_decimal_float():
    assert main._parse_number_locale(1483.0198) == 1483.0198
    assert main._parse_number_locale("1.483,0198") == 1483.0198
    assert main._parse_number_locale("1483.0198") == 1483.0198
    assert main._parse_number_locale("1.234,56") == 1234.56


def test_months_target_closed_months(monkeypatch):
    monkeypatch.setattr(main, "UPDATE_MONTHS", 3)
    monkeypatch.setattr(main, "UPDATE_INCLUDE_CURRENT_MONTH", False)
    assert main._meses_objetivo_actualizacion(date(2026, 7, 14)) == [
        date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)
    ]


def test_missing_source_does_not_write_blank():
    updates = {}
    missing = []
    managed = main._add_series_to_updates(
        module="Prueba",
        series_by_key={"Serie": {date(2026, 5, 1): 123.4}},
        key_to_header={"Serie": "Encabezado"},
        headers=["Fecha", "Encabezado"],
        months=[date(2026, 5, 1), date(2026, 6, 1)],
        updates=updates,
        faltantes=missing,
    )
    assert managed == 1
    assert updates == {(date(2026, 5, 1), 2): 123.4}
    assert (date(2026, 6, 1), 2) not in updates
    assert missing[0]["tipo"] == "pendiente_publicacion"


def test_a3500_keeps_official_decimal(monkeypatch, tmp_path):
    source = tmp_path / "a3500.xlsx"
    raw = pd.DataFrame({
        "Fecha": [pd.Timestamp("2026-05-04"), pd.Timestamp("2026-05-05")],
        "Tipo de cambio": [1483.0198, 1485.5000],
    })
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        raw.to_excel(writer, index=False, startrow=3)
    content = source.read_bytes()
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: FakeResponse(content=content))

    result = main.obtener_datos_a3500()
    assert result["TC"].max() < 2000
    assert round(float(result.iloc[0]["TC"]), 4) == 1483.0198
    assert round(float(result.iloc[0]["TC_promedio_mensual"]), 4) == 1484.2599


def test_b9791_uses_official_v4_detail(monkeypatch):
    payload = {
        "status": 200,
        "results": [{
            "idVariable": 4,
            "detalle": [
                {"fecha": "2026-05-02", "valor": 1200.0},
                {"fecha": "2026-05-05", "valor": 1210.0},
            ],
        }],
    }
    calls = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["params"] = kwargs.get("params")
        return FakeResponse(payload=payload)

    monkeypatch.setattr(main.requests, "get", fake_get)
    result = main.obtener_datos_b9791(date(2026, 5, 1), date(2026, 5, 31))

    assert calls["url"].endswith("/4")
    assert calls["params"]["desde"] == "2026-05-01"
    assert result["Vendedor"].tolist() == [1200.0, 1210.0]
    assert result["Promedio_mensual"].tolist() == [1205.0, 1205.0]


def test_month_dates_use_argentine_day_first_format():
    raw = pd.Series(["1/1/2022", "1/2/2022", "1/4/2022", "1/12/2022"])
    parsed = main._coerce_month_dates(raw)
    assert parsed.dt.strftime("%Y-%m-%d").tolist() == [
        "2022-01-01",
        "2022-02-01",
        "2022-04-01",
        "2022-12-01",
    ]


def test_month_dates_accept_google_sheets_serial_numbers():
    raw = pd.Series([44562, 44593])  # 01/01/2022 y 01/02/2022
    parsed = main._coerce_month_dates(raw)
    assert parsed.dt.strftime("%Y-%m-%d").tolist() == ["2022-01-01", "2022-02-01"]


def test_meta_and_data_keep_real_months(monkeypatch):
    frame = pd.DataFrame({
        "FECHA": ["1/1/2022", "1/2/2022", "1/3/2022", "1/4/2022"],
        "Serie": [100.0, 110.0, 120.0, 130.0],
    })
    frame["__date_key__"] = main._coerce_month_dates(frame["FECHA"]).dt.strftime("%Y-%m-%d")
    monkeypatch.setattr(main, "_load_df", lambda force=False: frame)

    metadata = main.meta(force=False, auth=True)
    assert [item["label"] for item in metadata["index_values"]] == [
        "Ene-2022", "Feb-2022", "Mar-2022", "Abr-2022"
    ]
    assert "__date_key__" not in [item["name"] for item in metadata["value_columns"]]

    payload = main.data(
        col_idxs="Serie",
        desde="2022-02-01",
        hasta="2022-04-01",
        auth=True,
    )
    assert [row[0] for row in payload["rows"]] == ["Feb-2022", "Mar-2022", "Abr-2022"]
