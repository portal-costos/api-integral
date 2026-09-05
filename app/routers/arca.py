"""Endpoints web del módulo ARCA."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.arca_engine import MotorARCA, df_tasas_a_tramos, sugerir_mapeo
from app.services.arca_rates import (
    RATE_COLUMNS,
    cargar_tasas_respaldo,
    descargar_tasas_arca,
    guardar_tasas_respaldo,
    rate_metadata,
)

BASE_DIR = Path(__file__).resolve().parents[2]
FALLBACK_PATH = BASE_DIR / "data" / "arca_rates_fallback.json"
CACHE_PATH = BASE_DIR / "data" / "arca_rates_cache.json"


class CalculoRequest(BaseModel):
    fecha_vencimiento: str
    fecha_pago_capital: str
    importe_capital: float = Field(gt=0)
    fecha_pago_intereses: Optional[str] = None


class RateManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._df: Optional[pd.DataFrame] = None
        self._source = ""
        self._warnings: list[str] = []
        self._loaded_at = 0.0
        self.ttl = int(os.getenv("ARCA_RATES_CACHE_TTL", "21600"))
        self.http_timeout = int(os.getenv("ARCA_HTTP_TIMEOUT", "15"))

    def get(self, force: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
        now = time.time()
        if not force and self._df is not None and now - self._loaded_at < self.ttl:
            return self._df.copy(), self._info()

        with self._lock:
            now = time.time()
            if not force and self._df is not None and now - self._loaded_at < self.ttl:
                return self._df.copy(), self._info()

            warnings: list[str] = []
            try:
                df, download_warnings = descargar_tasas_arca(timeout=self.http_timeout)
                warnings.extend(download_warnings)
                self._source = "official"
                try:
                    guardar_tasas_respaldo(df, CACHE_PATH)
                except Exception as exc:
                    warnings.append(f"No se pudo guardar el caché local de tasas: {exc}")
            except Exception as exc:
                warnings.append(str(exc))
                source_path = CACHE_PATH if CACHE_PATH.exists() else FALLBACK_PATH
                try:
                    df = cargar_tasas_respaldo(source_path)
                except Exception as fallback_exc:
                    raise RuntimeError(
                        f"No se pudieron obtener tasas oficiales ni cargar el respaldo: {fallback_exc}"
                    ) from fallback_exc
                self._source = "cache" if source_path == CACHE_PATH else "fallback"
                warnings.append(
                    "Se están utilizando tasas de respaldo. Verificá el reporte antes de usar "
                    "el resultado con fines administrativos."
                )

            self._df = df.copy()
            self._warnings = warnings
            self._loaded_at = time.time()
            return self._df.copy(), self._info()

    def _info(self) -> dict[str, Any]:
        assert self._df is not None
        return {
            "source": self._source,
            "warnings": list(self._warnings),
            "loaded_at": datetime.fromtimestamp(self._loaded_at, tz=timezone.utc).isoformat(),
            **rate_metadata(self._df),
        }


RATE_MANAGER = RateManager()


def _validate_upload(filename: str, payload: bytes) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="El archivo debe ser .xlsx o .xls.")
    max_mb = int(os.getenv("MAX_UPLOAD_MB", "50"))
    if len(payload) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"El archivo supera el máximo de {max_mb} MB.")
    if not payload:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")


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
    return excel, df, selected


def _json_safe(value: Any) -> Any:
    """Convierte valores de pandas/numpy a tipos JSON válidos; NaN e infinitos pasan a null."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and (pd.isna(value) or value in (float("inf"), float("-inf"))):
        return None
    return value


def _safe_preview(df: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    records = df.head(limit).to_dict(orient="records")
    return [
        {str(key): _json_safe(value) for key, value in record.items()}
        for record in records
    ]


def _build_result_workbook(
    source_df: pd.DataFrame,
    rates_df: pd.DataFrame,
    motor: MotorARCA,
    col_vto: str,
    col_pago: str,
    col_importe: str,
    col_pago_intereses: Optional[str],
) -> tuple[bytes, dict[str, Any]]:
    required = [col_vto, col_pago, col_importe]
    missing = [col for col in required if col not in source_df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"Columnas no encontradas: {missing}")
    if col_pago_intereses and col_pago_intereses not in source_df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Columna de pago de intereses no encontrada: {col_pago_intereses}",
        )

    output_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    ok_count = 0
    error_count = 0
    total_interest = 0.0

    for row_number, (_, row) in enumerate(source_df.reset_index(drop=True).iterrows(), start=2):
        pago_intereses = row[col_pago_intereses] if col_pago_intereses else None
        result = motor.calcular_fila(
            row[col_vto],
            row[col_pago],
            row[col_importe],
            pago_intereses,
        )
        base = row.to_dict()
        base.update(
            {
                "ARCA - Estado": "OK" if result.ok else result.error,
                "ARCA - Fecha de Vencimiento": result.fecha_vencimiento,
                "ARCA - Fecha de Pago del Capital": result.fecha_pago_capital,
                "ARCA - Fecha de Pago de Intereses": result.fecha_pago_intereses,
                "ARCA - Días transcurridos": result.dias_transcurridos if result.ok else None,
                "ARCA - Intereses resarcitorios": result.intereses_resarcitorios if result.ok else None,
                "ARCA - Intereses capitalizados": result.intereses_capitalizados if result.ok else None,
                "ARCA - Intereses total": result.intereses_total if result.ok else None,
                "ARCA - Suma tasas intermedias": result.suma_tasas_intermedias if result.ok else None,
            }
        )
        output_rows.append(base)

        if result.ok:
            ok_count += 1
            total_interest += result.intereses_total
            for segment_number, detail in enumerate(result.detalle, start=1):
                detail_rows.append(
                    {
                        "Fila Excel": row_number,
                        "Tramo": segment_number,
                        "Desde": detail.desde_mostrado,
                        "Hasta": detail.hasta_mostrado,
                        "Tipo": detail.tipo,
                        "Importe": detail.importe,
                        "Tasa mensual": detail.tasa_mensual,
                        "Tasa diaria": detail.tasa_diaria,
                        "Meses": detail.meses,
                        "Días remanentes": detail.dias,
                        "Días computados": detail.dias_transcurridos,
                        "Intereses": detail.intereses,
                        "Norma": detail.norma,
                        "Fuente": detail.fuente,
                    }
                )
        else:
            error_count += 1

    result_df = pd.DataFrame(output_rows)
    detail_df = pd.DataFrame(detail_rows)
    summary_df = pd.DataFrame(
        [
            {"Concepto": "Filas totales", "Valor": len(source_df)},
            {"Concepto": "Filas OK", "Valor": ok_count},
            {"Concepto": "Filas con error", "Valor": error_count},
            {"Concepto": "Total intereses", "Valor": round(total_interest, 2)},
            {"Concepto": "Columna vencimiento", "Valor": col_vto},
            {"Concepto": "Columna pago capital", "Valor": col_pago},
            {"Concepto": "Columna importe", "Valor": col_importe},
            {"Concepto": "Columna pago intereses", "Valor": col_pago_intereses or "No utilizada"},
        ]
    )

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        result_df.to_excel(writer, sheet_name="Intereses ARCA", index=False)
        rates_df[RATE_COLUMNS].to_excel(writer, sheet_name="Tasas usadas", index=False)
        summary_df.to_excel(writer, sheet_name="Resumen", index=False)
        if detail_df.empty:
            pd.DataFrame([{"Detalle": "No se generaron tramos válidos."}]).to_excel(
                writer, sheet_name="Detalle por tramos", index=False
            )
        else:
            detail_df.to_excel(writer, sheet_name="Detalle por tramos", index=False)

    return buffer.getvalue(), {
        "total_rows": int(len(source_df)),
        "ok_rows": ok_count,
        "error_rows": error_count,
        "total_interest": round(total_interest, 2),
    }


def create_router(require_auth: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/arca", tags=["ARCA"])

    @router.get("/health")
    def health(auth: bool = Depends(require_auth)):
        return {"ok": True, "module": "arca"}

    @router.get("/tasas")
    def get_rates(force: bool = False, auth: bool = Depends(require_auth)):
        try:
            df, info = RATE_MANAGER.get(force=force)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        records = [{str(k): _json_safe(v) for k, v in row.items()} for row in df.to_dict(orient="records")]
        return {"ok": True, **info, "rates": records}

    @router.get("/tasas.xlsx")
    def download_rates(auth: bool = Depends(require_auth)):
        try:
            df, _ = RATE_MANAGER.get(force=False)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        buffer = BytesIO()
        df.to_excel(buffer, index=False, sheet_name="Tasas ARCA")
        return StreamingResponse(
            BytesIO(buffer.getvalue()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="tasas_arca_usadas.xlsx"'},
        )

    @router.post("/calcular")
    def calculate(body: CalculoRequest, auth: bool = Depends(require_auth)):
        try:
            rates_df, rate_info = RATE_MANAGER.get(force=False)
            motor = MotorARCA(df_tasas_a_tramos(rates_df))
            result = motor.calcular_fila(
                body.fecha_vencimiento,
                body.fecha_pago_capital,
                body.importe_capital,
                body.fecha_pago_intereses,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"rate_info": rate_info, **result.to_dict()}

    @router.post("/inspect-excel")
    async def inspect_excel(
        file: UploadFile = File(...),
        sheet_name: Optional[str] = Form(default=None),
        auth: bool = Depends(require_auth),
    ):
        payload = await file.read()
        _validate_upload(file.filename or "archivo.xlsx", payload)
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
            "preview": _safe_preview(df),
        }

    @router.post("/procesar-excel")
    async def process_excel(
        file: UploadFile = File(...),
        sheet_name: str = Form(...),
        col_vencimiento: str = Form(...),
        col_pago_capital: str = Form(...),
        col_importe: str = Form(...),
        col_pago_intereses: Optional[str] = Form(default=None),
        auth: bool = Depends(require_auth),
    ):
        payload = await file.read()
        filename = file.filename or "archivo.xlsx"
        _validate_upload(filename, payload)
        _, source_df, _ = _read_excel(payload, sheet_name)

        try:
            rates_df, _ = RATE_MANAGER.get(force=False)
            motor = MotorARCA(df_tasas_a_tramos(rates_df))
            workbook, _summary = _build_result_workbook(
                source_df=source_df,
                rates_df=rates_df,
                motor=motor,
                col_vto=col_vencimiento,
                col_pago=col_pago_capital,
                col_importe=col_importe,
                col_pago_intereses=col_pago_intereses or None,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"No se pudo procesar el Excel: {exc}") from exc

        stem = Path(filename).stem
        output_name = f"{stem}_con_intereses_arca.xlsx"
        return StreamingResponse(
            BytesIO(workbook),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{output_name}"'},
        )

    return router
