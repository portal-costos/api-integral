from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl.utils import get_column_letter

from .boletin_repository import BoletinRepositorio
from .transporte_models import TransporteMonitoreoRequest
from .transporte_service import (
    FITZ_AVAILABLE,
    FITZ_IMPORT_ERROR,
    TransporteJobManager,
    llm_text,
)


def _flat_record(item: dict[str, Any]) -> dict[str, Any]:
    terms = item.get("terminos_encontrados") or item.get("regulatory_terms") or []
    return {
        "Fecha": item.get("fecha") or item.get("publication_date") or "",
        "Año": item.get("year") or "",
        "Resolución": item.get("numero") or item.get("resolution_number") or "",
        "Destinatario / asunto": item.get("prestadora") or item.get("provider") or "",
        "Clasificación": item.get("estado_detectado") or item.get("detected_state") or "",
        "Novedad": item.get("novedad") or item.get("last_change_type") or "",
        "Temas detectados": ", ".join(str(value) for value in terms),
        "PDF": item.get("archivo") or item.get("source_pdf") or "",
        "URL": item.get("url") or item.get("source_url") or "",
        "Extracto": item.get("extracto") or item.get("extract_text") or "",
        "Primera detección": item.get("first_seen_at") or "",
        "Última verificación": item.get("last_seen_at") or "",
        "Verificaciones": item.get("verification_count") or "",
        "Hash": item.get("content_hash") or "",
        "Advertencia": item.get("warning") or "",
    }


def _download_response(content: bytes, filename: str, media_type: str) -> StreamingResponse:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(io.BytesIO(content), media_type=media_type, headers=headers)


def create_transporte_router(
    require_auth: Callable[..., Any],
    base_dir: Path,
    http_timeout: int = 45,
) -> APIRouter:
    data_dir = Path(base_dir).resolve() / "datos_boletin_transporte"
    db_path = data_dir / "boletin_transporte.sqlite3"
    repository = BoletinRepositorio(db_path, seed_default_alerts=False)
    manager = TransporteJobManager(repository, timeout=http_timeout)

    router = APIRouter(
        prefix="/api/transporte",
        tags=["Boletín Oficial - Secretaría de Transporte"],
        dependencies=[Depends(require_auth)],
    )

    @router.get("/health")
    def health():
        counts = repository.counts()
        return {
            "status": "ok" if FITZ_AVAILABLE else "degraded",
            "module": "boletin-transporte",
            "pymupdf_available": FITZ_AVAILABLE,
            "pymupdf_error": FITZ_IMPORT_ERROR or None,
            "database_path": str(repository.db_path),
            "publicaciones": counts.get("publicaciones", 0),
            "ejecuciones": counts.get("ejecuciones", 0),
        }

    @router.post("/monitorear", status_code=202)
    def start_monitoring(body: TransporteMonitoreoRequest):
        try:
            run_id = manager.start(body.model_dump())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run_id": run_id, "status": "PENDING"}

    @router.get("/monitoreo/{run_id}")
    def monitoring_status(run_id: int):
        run = repository.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Ejecución no encontrada.")
        run["errors"] = repository.list_run_errors(run_id, limit=20)
        run["novedades"] = int(run.get("new_count", 0)) + int(run.get("changed_count", 0))
        run["meses_procesados"] = run.get("months_scanned", 0)
        run["pdfs_analizados"] = run.get("pdfs_processed", 0)
        run["resoluciones_detectadas"] = run.get("resolutions_seen", 0)
        run["porcentaje"] = run.get("progress_percent", 0)
        run["mensaje"] = run.get("current_message", "")
        return run

    @router.post("/monitoreo/{run_id}/detener")
    def stop_monitoring(run_id: int):
        run = repository.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Ejecución no encontrada.")
        if run.get("status") not in {"PENDING", "RUNNING", "STOPPING"}:
            return {"run_id": run_id, "status": run.get("status"), "stopping": False}
        stopped = manager.stop(run_id)
        return {"run_id": run_id, "status": "STOPPING", "stopping": stopped}

    @router.get("/monitoreo/{run_id}/resultados")
    def monitoring_results(run_id: int):
        run = repository.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Ejecución no encontrada.")
        return {
            "run": run,
            "items": repository.list_run_results(run_id, visible_only=True, compact=True),
        }

    @router.get("/historial/filtros")
    def history_filters():
        return repository.distinct_filters()

    @router.get("/historial")
    def history(
        anio: Optional[int] = Query(default=None, ge=2000, le=2100),
        destinatario: str = "",
        estado: str = "",
        texto: str = "",
        solo_novedades: bool = False,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=200),
    ):
        return repository.history(
            anio=anio,
            prestadora=destinatario,
            estado=estado,
            alerta="",
            texto=texto,
            solo_novedades=solo_novedades,
            page=page,
            page_size=page_size,
        )

    @router.get("/publicaciones/{publicacion_id}")
    def publication_detail(publicacion_id: int):
        item = repository.get_publication(publicacion_id)
        if not item:
            raise HTTPException(status_code=404, detail="Publicación no encontrada.")
        return item

    @router.get("/publicaciones/{publicacion_id}/pdf")
    def publication_pdf(publicacion_id: int):
        item = repository.get_publication(publicacion_id)
        if not item:
            raise HTTPException(status_code=404, detail="Publicación no encontrada.")
        try:
            content, filename = manager.download_official_pdf(item.get("source_url", ""))
        except (ValueError, requests.RequestException) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"No se pudo descargar el PDF oficial: {exc}",
            ) from exc
        return _download_response(content, filename, "application/pdf")

    @router.get("/exportar")
    def export(
        formato: str = Query(default="xlsx", pattern="^(xlsx|csv|json|txt)$"),
        scope: str = Query(default="historial", pattern="^(historial|run)$"),
        run_id: Optional[int] = None,
        anio: Optional[int] = Query(default=None, ge=2000, le=2100),
        destinatario: str = "",
        estado: str = "",
        texto: str = "",
        solo_novedades: bool = False,
    ):
        if scope == "run":
            if not run_id:
                raise HTTPException(status_code=400, detail="Indicá run_id para exportar una ejecución.")
            run = repository.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Ejecución no encontrada.")
            records = repository.list_run_results(run_id, visible_only=False, compact=False)
            year = int(run.get("year") or anio or datetime.now().year)
            base_name = f"boletin_transporte_run_{run_id}"
        else:
            records = repository.history_all(
                anio=anio,
                prestadora=destinatario,
                estado=estado,
                alerta="",
                texto=texto,
                solo_novedades=solo_novedades,
            )
            year = int(anio or datetime.now().year)
            base_name = "historial_boletin_transporte"

        if formato == "txt":
            if scope != "run":
                raise HTTPException(status_code=400, detail="La salida TXT para IA se genera por ejecución.")
            return _download_response(
                llm_text(records, year).encode("utf-8"),
                base_name + "_ia.txt",
                "text/plain; charset=utf-8",
            )

        if formato == "json":
            content = json.dumps(records, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            return _download_response(
                content,
                base_name + ".json",
                "application/json; charset=utf-8",
            )

        flat = [_flat_record(record) for record in records]
        frame = pd.DataFrame(flat, columns=list(_flat_record({}).keys()))
        if formato == "csv":
            stream = io.StringIO()
            frame.to_csv(stream, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
            return _download_response(
                stream.getvalue().encode("utf-8-sig"),
                base_name + ".csv",
                "text/csv; charset=utf-8",
            )

        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Transporte", index=False)
            worksheet = writer.sheets["Transporte"]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for index, column_name in enumerate(frame.columns, start=1):
                values = [str(column_name)] + [
                    "" if value is None else str(value)
                    for value in frame[column_name].head(500).tolist()
                ]
                width = min(max(len(value) for value in values) + 2, 55)
                worksheet.column_dimensions[get_column_letter(index)].width = max(width, 11)
        return _download_response(
            stream.getvalue(),
            base_name + ".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    router.state = {
        "repository": repository,
        "manager": manager,
        "database_path": db_path,
    }
    return router
