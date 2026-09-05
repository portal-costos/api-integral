"""Endpoints del módulo de incidencia tarifaria basado en microdatos EPH."""
from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.incidencia_engine import IncidenciaResultado, procesar_incidencia, sugerir_mapeo


MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _validate_upload(filename: str, payload: bytes) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="El archivo debe ser .xlsx o .xls.")
    max_mb = int(os.getenv("MAX_UPLOAD_MB", "50"))
    if not payload:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(payload) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"El archivo supera el máximo de {max_mb} MB.")


def _read_excel(payload: bytes, sheet_name: Optional[str] = None) -> tuple[pd.ExcelFile, pd.DataFrame, str]:
    try:
        excel = pd.ExcelFile(BytesIO(payload))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo abrir el Excel: {exc}") from exc
    selected = sheet_name or excel.sheet_names[0]
    if selected not in excel.sheet_names:
        raise HTTPException(status_code=400, detail=f"La hoja '{selected}' no existe.")
    try:
        df = pd.read_excel(excel, sheet_name=selected)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer la hoja '{selected}': {exc}") from exc
    # Elimina columnas totalmente vacías; no elimina filas ni altera datos sustantivos.
    df = df.dropna(axis=1, how="all")
    return excel, df, selected


def _safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _preview(df: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    return [
        {str(k): _safe(v) for k, v in fila.items()}
        for fila in df.head(limit).to_dict(orient="records")
    ]


def _parse_mapping(mapping_json: str) -> dict[str, str]:
    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="El mapeo de columnas no es JSON válido.") from exc
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="El mapeo de columnas debe ser un objeto.")
    return {str(k): str(v or "") for k, v in mapping.items()}


def _parse_zonales(zonales_json: str) -> list[dict[str, Any]]:
    try:
        zonales = json.loads(zonales_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Los parámetros zonales no son JSON válido.") from exc
    if not isinstance(zonales, list):
        raise HTTPException(status_code=400, detail="Los parámetros zonales deben ser una lista.")
    return zonales


def _ejecutar(
    payload: bytes,
    sheet_name: str,
    mapping_json: str,
    zonales_json: str,
    aglomerado_valor: str,
    eliminar_duplicados: bool,
) -> IncidenciaResultado:
    _, df, _ = _read_excel(payload, sheet_name)
    mapping = _parse_mapping(mapping_json)
    zonales = _parse_zonales(zonales_json)
    try:
        return procesar_incidencia(
            df,
            mapping,
            zonales,
            aglomerado_valor=aglomerado_valor,
            eliminar_duplicados=eliminar_duplicados,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo calcular la incidencia: {exc}") from exc


def _autosize(ws, max_width: int = 42) -> None:
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        max_len = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_len = max(max_len, len(value))
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), max_width)


def _estilizar_encabezado(ws, fila: int = 1) -> None:
    fill = PatternFill("solid", fgColor="1557A6")
    for cell in ws[fila]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = f"A{fila + 1}"


def _build_workbook(resultado: IncidenciaResultado) -> bytes:
    buffer = BytesIO()
    zonales_df = pd.DataFrame(resultado.zonales)
    percentiles_df = pd.DataFrame(resultado.percentiles_eph)
    percentiles_z_df = pd.DataFrame(resultado.percentiles_zonales)
    resumen_df = pd.DataFrame(
        [{"Indicador": clave, "Valor": valor} for clave, valor in resultado.resumen.items()]
    )
    parametros_df = resultado.parametros.rename(
        columns={
            "zonal": "Zonal",
            "porcentaje_original": "Usuarios % original",
            "porcentaje_normalizado": "Usuarios % normalizado",
            "percentil_inicial": "Percentil inicial",
            "percentil_final": "Percentil final",
            "tarifa": "Tarifa promedio",
            "tarifa_sin_impuestos": "Tarifa sin impuestos",
        }
    )
    metodologia_df = pd.DataFrame(
        {
            "Tipo": ["Análisis"] * len(resultado.analisis)
            + ["Metodología"] * len(resultado.metodologia)
            + ["Advertencia"] * len(resultado.advertencias),
            "Detalle": resultado.analisis + resultado.metodologia + resultado.advertencias,
        }
    )

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        resumen_df.to_excel(writer, sheet_name="Resumen", index=False)
        zonales_df.to_excel(writer, sheet_name="Resultados zonales", index=False)
        parametros_df.to_excel(writer, sheet_name="Parámetros", index=False)
        percentiles_df.to_excel(writer, sheet_name="Percentiles EPH", index=False)
        percentiles_z_df.to_excel(writer, sheet_name="Percentiles por zonal", index=False)
        resultado.base_procesada.to_excel(writer, sheet_name="Base procesada", index=False)
        metodologia_df.to_excel(writer, sheet_name="Metodología", index=False)

        workbook = writer.book
        for ws in workbook.worksheets:
            _estilizar_encabezado(ws)
            _autosize(ws)
            ws.auto_filter.ref = ws.dimensions

        # Formatos principales.
        ws_z = workbook["Resultados zonales"]
        headers = {cell.value: cell.column for cell in ws_z[1]}
        for nombre in (
            "porcentaje_original",
            "porcentaje_normalizado",
            "percentil_inicial",
            "percentil_final",
            "incidencia_general",
            "carga_media_positivos",
            "incidencia_general_sin_impuestos",
            "carga_media_positivos_sin_impuestos",
            "proporcion_sin_ingreso",
        ):
            col = headers.get(nombre)
            if col:
                for row in range(2, ws_z.max_row + 1):
                    ws_z.cell(row, col).number_format = "0.00%"
        for nombre in (
            "tarifa",
            "tarifa_sin_impuestos",
            "itf_medio",
            "ipcf_medio",
            "itf_mediana",
            "ipcf_mediana",
        ):
            col = headers.get(nombre)
            if col:
                for row in range(2, ws_z.max_row + 1):
                    ws_z.cell(row, col).number_format = '$ #,##0.00'

        # Gráfico simple en Resumen.
        ws_res = workbook["Resumen"]
        start = ws_res.max_row + 3
        ws_res.cell(start, 1, "Zonal")
        ws_res.cell(start, 2, "Incidencia general")
        for idx, item in enumerate(resultado.zonales, start=start + 1):
            ws_res.cell(idx, 1, item["zonal"])
            ws_res.cell(idx, 2, item["incidencia_general"])
            ws_res.cell(idx, 2).number_format = "0.00%"
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "Incidencia tarifaria por zonal"
        chart.y_axis.title = "Tarifa / ITF medio"
        chart.x_axis.title = "Zonal"
        data = Reference(ws_res, min_col=2, min_row=start, max_row=start + 7)
        cats = Reference(ws_res, min_col=1, min_row=start + 1, max_row=start + 7)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.height = 8
        chart.width = 15
        ws_res.add_chart(chart, "D3")

    return buffer.getvalue()


def _build_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "EPH hogares"
    headers = [
        "CODUSU",
        "ANO4",
        "TRIMESTRE",
        "NRO_HOGAR",
        "AGLOMERADO",
        "IX_TOT",
        "ITF",
        "IPCF",
        "PONDIH",
        "ADECIFR",
        "ADECCFR",
    ]
    ws.append(headers)
    ws.append(["Ejemplo-no-usar", 2025, 4, 1, 13, 3, 1500000, 500000, 1000, 5, 5])
    _estilizar_encabezado(ws)
    _autosize(ws)
    ws["A4"] = "Pegue una fila por hogar. ITF, IPCF y PONDIH son obligatorios."
    ws.merge_cells("A4:K4")
    ws["A4"].alignment = Alignment(wrap_text=True)
    ws["A4"].font = Font(italic=True, color="64748B")
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def create_incidencia_router(require_auth: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/incidencia", tags=["Incidencia tarifaria"])

    @router.get("/health")
    def health(auth: bool = Depends(require_auth)):
        return {"ok": True, "module": "incidencia_tarifaria"}

    @router.get("/plantilla.xlsx")
    def plantilla(auth: bool = Depends(require_auth)):
        return StreamingResponse(
            BytesIO(_build_template()),
            media_type=MIME_XLSX,
            headers={"Content-Disposition": 'attachment; filename="plantilla_eph_incidencia.xlsx"'},
        )

    @router.post("/inspect-excel")
    async def inspect_excel(
        file: UploadFile = File(...),
        sheet_name: Optional[str] = Form(default=None),
        auth: bool = Depends(require_auth),
    ):
        payload = await file.read()
        _validate_upload(file.filename or "eph.xlsx", payload)
        excel, df, selected = _read_excel(payload, sheet_name)
        columns = [str(c) for c in df.columns]
        return {
            "ok": True,
            "filename": file.filename,
            "sheet_names": excel.sheet_names,
            "selected_sheet": selected,
            "columns": columns,
            "suggested_mapping": sugerir_mapeo(columns),
            "rows": int(len(df)),
            "preview": _preview(df),
        }

    @router.post("/calcular")
    async def calcular(
        file: UploadFile = File(...),
        sheet_name: str = Form(...),
        mapping_json: str = Form(...),
        zonales_json: str = Form(...),
        aglomerado_valor: str = Form(default="13"),
        eliminar_duplicados: bool = Form(default=False),
        auth: bool = Depends(require_auth),
    ):
        payload = await file.read()
        _validate_upload(file.filename or "eph.xlsx", payload)
        resultado = _ejecutar(
            payload,
            sheet_name,
            mapping_json,
            zonales_json,
            aglomerado_valor,
            eliminar_duplicados,
        )
        return {
            "ok": True,
            "resumen": resultado.resumen,
            "zonales": resultado.zonales,
            "percentiles_eph": resultado.percentiles_eph,
            "percentiles_zonales": resultado.percentiles_zonales,
            "advertencias": resultado.advertencias,
            "analisis": resultado.analisis,
            "metodologia": resultado.metodologia,
        }

    @router.post("/exportar.xlsx")
    async def exportar(
        file: UploadFile = File(...),
        sheet_name: str = Form(...),
        mapping_json: str = Form(...),
        zonales_json: str = Form(...),
        aglomerado_valor: str = Form(default="13"),
        eliminar_duplicados: bool = Form(default=False),
        auth: bool = Depends(require_auth),
    ):
        payload = await file.read()
        filename = file.filename or "eph.xlsx"
        _validate_upload(filename, payload)
        resultado = _ejecutar(
            payload,
            sheet_name,
            mapping_json,
            zonales_json,
            aglomerado_valor,
            eliminar_duplicados,
        )
        stem = Path(filename).stem
        return StreamingResponse(
            BytesIO(_build_workbook(resultado)),
            media_type=MIME_XLSX,
            headers={
                "Content-Disposition": f'attachment; filename="{stem}_incidencia_tarifaria.xlsx"'
            },
        )

    return router
