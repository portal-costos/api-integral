from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl.utils import get_column_letter

from .boletin_models import (
    AlertaCreate,
    AlertaEstadoUpdate,
    AlertaImportacionConfirmar,
    AlertaUpdate,
    MonitoreoRequest,
)
from .boletin_repository import BoletinRepositorio, canonical_keywords, normalize_alert_key
from .boletin_service import (
    FITZ_AVAILABLE,
    FITZ_IMPORT_ERROR,
    BoletinJobManager,
    llm_text,
)



def _flat_record(item: dict[str, Any]) -> dict[str, Any]:
    alerts = item.get("alertas") or item.get("matched_alerts") or []
    if alerts and isinstance(alerts[0], dict):
        alerts = [entry.get("nombre", "") for entry in alerts]
    terms = item.get("terminos_encontrados") or item.get("regulatory_terms") or []
    return {
        "Fecha del Boletín": item.get("fecha") or item.get("publication_date") or "",
        "Año": item.get("year") or "",
        "Resolución": item.get("numero") or item.get("resolution_number") or "",
        "Expediente": item.get("expediente") or item.get("expediente_number") or "Expediente no identificado",
        "Fecha de emisión": item.get("fecha_emision") or item.get("emission_date") or "No identificado",
        "Prestadora": item.get("prestadora") or item.get("provider") or "",
        "Organismo emisor": item.get("organismo_emisor") or item.get("issuing_body") or "No identificado",
        "Estado": item.get("estado_detectado") or item.get("detected_state") or "",
        "Novedad": item.get("novedad") or item.get("last_change_type") or "",
        "Alertas": ", ".join(str(value) for value in alerts),
        "Términos": ", ".join(str(value) for value in terms),
        "PDF": item.get("archivo") or item.get("source_pdf") or "",
        "URL": item.get("url") or item.get("source_url") or "",
        "Extracto": item.get("extracto") or item.get("extract_text") or "",
        "Primera detección": item.get("first_seen_at") or "",
        "Última verificación": item.get("last_seen_at") or "",
        "Verificaciones": item.get("verification_count") or "",
        "Hash": item.get("content_hash") or "",
        "Advertencia": item.get("warning") or "",
    }


def _normalize_import_column(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").upper())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _read_alert_file(filename: str, content: bytes) -> pd.DataFrame:
    suffix = Path(filename or "").suffix.casefold()
    if suffix not in {".xlsx", ".csv"}:
        raise ValueError("El archivo debe ser .xlsx o .csv.")
    if not content:
        raise ValueError("El archivo está vacío.")
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("El archivo supera el límite de 5 MB.")
    if suffix == ".xlsx":
        frame = pd.read_excel(io.BytesIO(content), dtype=str)
    else:
        decoded = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ValueError("No se pudo interpretar la codificación del CSV.")
        frame = pd.read_csv(io.StringIO(decoded), sep=None, engine="python", dtype=str)
    columns = {_normalize_import_column(column): column for column in frame.columns}
    alias_column = columns.get("ALIAS")
    keywords_column = columns.get("PALABRAS CLAVES") or columns.get("PALBRAS CLAVES")
    if not alias_column or not keywords_column:
        raise ValueError("La planilla debe contener las columnas ALIAS y PALABRAS CLAVES.")
    return frame[[alias_column, keywords_column]].rename(
        columns={alias_column: "ALIAS", keywords_column: "PALABRAS CLAVES"}
    )


def _alert_import_preview(
    frame: pd.DataFrame, repository: BoletinRepositorio
) -> dict[str, Any]:
    existing = {
        normalize_alert_key(item.get("nombre")): item for item in repository.list_alerts()
    }
    seen_file: set[str] = set()
    rows: list[dict[str, Any]] = []
    incomplete = 0
    duplicates = 0
    for offset, source in frame.fillna("").iterrows():
        row_number = int(offset) + 2 if isinstance(offset, int) else len(rows) + 2
        alias = re.sub(r"\s+", " ", str(source.get("ALIAS") or "")).strip()
        keywords = canonical_keywords(source.get("PALABRAS CLAVES"), "")
        key = normalize_alert_key(alias)
        errors: list[str] = []
        duplicate_type = ""
        if not alias:
            errors.append("Falta ALIAS.")
        if not keywords:
            errors.append("Faltan PALABRAS CLAVES.")
        if key and key in seen_file:
            duplicate_type = "duplicada_archivo"
            errors.append("El ALIAS está repetido dentro del archivo.")
        if errors:
            action = "rechazar"
            state = "incompleta" if not duplicate_type else duplicate_type
            if duplicate_type:
                duplicates += 1
            else:
                incomplete += 1
        elif key in existing:
            action = "actualizar"
            state = "existente"
            duplicate_type = "existente"
            duplicates += 1
        else:
            action = "crear"
            state = "valida"
        if key:
            seen_file.add(key)
        rows.append(
            {
                "fila": row_number,
                "alias": alias,
                "palabras_claves": keywords,
                "estado": state,
                "accion": action,
                "errores": errors,
                "posible_duplicado": duplicate_type,
            }
        )
    accepted = sum(1 for row in rows if row["accion"] in {"crear", "actualizar"})
    return {
        "filas": rows,
        "resumen": {
            "total_filas": len(rows),
            "filas_validas": accepted,
            "filas_nuevas": sum(1 for row in rows if row["accion"] == "crear"),
            "filas_incompletas": incomplete,
            "posibles_duplicadas": duplicates,
            "se_actualizaran": sum(1 for row in rows if row["accion"] == "actualizar"),
            "total_incorporar": accepted,
        },
        "separador": "|",
    }


def _download_response(content: bytes, filename: str, media_type: str) -> StreamingResponse:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(io.BytesIO(content), media_type=media_type, headers=headers)


def create_boletin_router(
    require_auth: Callable[..., Any],
    base_dir: Path,
    http_timeout: int = 45,
) -> APIRouter:
    data_dir = Path(base_dir).resolve() / "datos_boletin_ersep"
    db_path = data_dir / "boletin_ersep.sqlite3"
    repository = BoletinRepositorio(db_path)
    manager = BoletinJobManager(repository, timeout=http_timeout)

    router = APIRouter(
        prefix="/api/boletin",
        tags=["Boletín Oficial"],
        dependencies=[Depends(require_auth)],
    )

    @router.get("/health")
    def health():
        counts = repository.counts()
        return {
            "status": "ok" if FITZ_AVAILABLE else "degraded",
            "module": "boletin-oficial",
            "pymupdf_available": FITZ_AVAILABLE,
            "pymupdf_error": FITZ_IMPORT_ERROR or None,
            "database_path": str(repository.db_path),
            **counts,
        }

    # ------------------------------------------------------------------
    # Alertas
    # ------------------------------------------------------------------
    @router.get("/alertas")
    def list_alerts():
        return {"items": repository.list_alerts()}

    @router.post("/alertas", status_code=201)
    def create_alert(body: AlertaCreate):
        try:
            return repository.create_alert(body.nombre, body.aliases, body.active)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/alertas/importacion/plantilla")
    def alert_import_template():
        stream = io.BytesIO()
        template = pd.DataFrame(
            [
                {
                    "ALIAS": "Ejemplo de prestadora",
                    "PALABRAS CLAVES": "Nombre completo | Nombre alternativo | Sigla",
                }
            ]
        )
        instructions = pd.DataFrame(
            [
                {
                    "INSTRUCCIONES": (
                        "Use una fila por alerta. Separe alternativas únicamente con |. "
                        "Cada alternativa se buscará con la condición O."
                    )
                }
            ]
        )
        with pd.ExcelWriter(stream, engine="openpyxl") as writer:
            template.to_excel(writer, sheet_name="ALERTAS", index=False)
            instructions.to_excel(writer, sheet_name="INSTRUCCIONES", index=False)
            worksheet = writer.sheets["ALERTAS"]
            worksheet.freeze_panes = "A2"
            worksheet.column_dimensions["A"].width = 34
            worksheet.column_dimensions["B"].width = 72
        return _download_response(
            stream.getvalue(),
            "plantilla_importacion_alertas.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @router.post("/alertas/importacion/vista-previa")
    async def preview_alert_import(file: UploadFile = File(...)):
        try:
            content = await file.read()
            frame = _read_alert_file(file.filename or "alertas.xlsx", content)
            return _alert_import_preview(frame, repository)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"No se pudo leer la planilla de alertas: {exc}"
            ) from exc

    @router.post("/alertas/importacion/confirmar")
    def confirm_alert_import(body: AlertaImportacionConfirmar):
        created = 0
        updated = 0
        rejected = 0
        details: list[dict[str, Any]] = []
        for row in body.filas:
            if row.accion == "rechazar" or not row.alias or not row.palabras_claves:
                rejected += 1
                details.append({"fila": row.fila, "resultado": "rechazada"})
                continue
            try:
                existing = repository.get_alert_by_name(row.alias)
                active = bool(existing.get("active")) if existing else True
                _, action = repository.upsert_alert(
                    row.alias, row.palabras_claves, active=active
                )
                if action == "crear":
                    created += 1
                else:
                    updated += 1
                details.append({"fila": row.fila, "resultado": action})
            except Exception as exc:
                rejected += 1
                details.append(
                    {"fila": row.fila, "resultado": "rechazada", "motivo": str(exc)}
                )
        return {
            "creadas": created,
            "actualizadas": updated,
            "rechazadas": rejected,
            "total": len(body.filas),
            "detalle": details,
        }

    @router.put("/alertas/{alerta_id}")
    def update_alert(alerta_id: int, body: AlertaUpdate):
        try:
            item = repository.update_alert(
                alerta_id, body.nombre, body.aliases, body.active
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not item:
            raise HTTPException(status_code=404, detail="Alerta no encontrada.")
        return item

    @router.patch("/alertas/{alerta_id}/estado")
    def update_alert_state(alerta_id: int, body: AlertaEstadoUpdate):
        item = repository.set_alert_state(alerta_id, body.active)
        if not item:
            raise HTTPException(status_code=404, detail="Alerta no encontrada.")
        return item

    @router.delete("/alertas/{alerta_id}")
    def delete_alert(alerta_id: int):
        if not repository.delete_alert(alerta_id):
            raise HTTPException(status_code=404, detail="Alerta no encontrada.")
        return {"ok": True}

    # ------------------------------------------------------------------
    # Monitoreo
    # ------------------------------------------------------------------
    @router.post("/monitorear", status_code=202)
    def start_monitoring(body: MonitoreoRequest):
        config = body.model_dump()
        try:
            run_id = manager.start(config)
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

    # ------------------------------------------------------------------
    # Historial y detalle
    # ------------------------------------------------------------------
    @router.get("/historial/filtros")
    def history_filters():
        return repository.distinct_filters()

    @router.get("/historial")
    def history(
        anio: Optional[int] = Query(default=None, ge=2000, le=2100),
        organismo: str = Query(default="", pattern="^(|ERSEP|APRHI)$"),
        prestadora: str = "",
        estado: str = "",
        alerta: str = "",
        texto: str = "",
        solo_novedades: bool = False,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=200),
    ):
        return repository.history(
            anio=anio,
            organismo=organismo,
            prestadora=prestadora,
            estado=estado,
            alerta=alerta,
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

    def _extract_publication(publicacion_id: int):
        item = repository.get_publication(publicacion_id)
        if not item:
            raise HTTPException(status_code=404, detail="Publicación no encontrada.")
        try:
            return manager.extract_complete_information(item)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"No se pudo extraer la información completa del documento oficial: {exc}",
            ) from exc

    @router.post("/publicaciones/{publicacion_id}/extraer-completo")
    def extract_complete_document(publicacion_id: int):
        return _extract_publication(publicacion_id)

    @router.post("/publicaciones/{publicacion_id}/obtener-informacion-completa")
    def obtain_complete_information(publicacion_id: int):
        return _extract_publication(publicacion_id)

    @router.get("/publicaciones/{publicacion_id}/anexos/{annex_index}/pdf")
    def publication_annex_pdf(publicacion_id: int, annex_index: int):
        item = repository.get_publication(publicacion_id)
        if not item:
            raise HTTPException(status_code=404, detail="Publicación no encontrada.")
        try:
            content, filename = manager.download_annex_pdf(item, annex_index)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"No se pudo descargar el anexo oficial: {exc}"
            ) from exc
        return _download_response(content, filename, "application/pdf")

    @router.get("/publicaciones/{publicacion_id}/pdf")
    def publication_pdf(publicacion_id: int):
        item = repository.get_publication(publicacion_id)
        if not item:
            raise HTTPException(status_code=404, detail="Publicación no encontrada.")
        try:
            content, filename = manager.download_official_pdf(item.get("source_url", ""))
        except (ValueError, requests.RequestException) as exc:
            raise HTTPException(status_code=502, detail=f"No se pudo descargar el PDF oficial: {exc}") from exc
        return _download_response(content, filename, "application/pdf")

    # ------------------------------------------------------------------
    # Exportación
    # ------------------------------------------------------------------
    @router.get("/exportar")
    def export(
        formato: str = Query(default="xlsx", pattern="^(xlsx|csv|json|txt)$"),
        scope: str = Query(default="historial", pattern="^(historial|run)$"),
        run_id: Optional[int] = None,
        anio: Optional[int] = Query(default=None, ge=2000, le=2100),
        organismo: str = Query(default="", pattern="^(|ERSEP|APRHI)$"),
        prestadora: str = "",
        estado: str = "",
        alerta: str = "",
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
            base_name = f"boletin_ersep_run_{run_id}"
        else:
            records = repository.history_all(
                anio=anio,
                organismo=organismo,
                prestadora=prestadora,
                estado=estado,
                alerta=alerta,
                texto=texto,
                solo_novedades=solo_novedades,
            )
            year = int(anio or datetime.now().year)
            base_name = "historial_boletin_ersep"

        if formato == "txt":
            if scope != "run":
                raise HTTPException(status_code=400, detail="La salida TXT para IA se genera por ejecución.")
            content = llm_text(records, year).encode("utf-8")
            return _download_response(content, base_name + "_ia.txt", "text/plain; charset=utf-8")

        if formato == "json":
            content = json.dumps(
                records, ensure_ascii=False, indent=2, default=str
            ).encode("utf-8")
            return _download_response(
                content, base_name + ".json", "application/json; charset=utf-8"
            )

        flat = [_flat_record(record) for record in records]
        # Mantiene los encabezados aun cuando el filtro no devuelve registros.
        frame = pd.DataFrame(flat, columns=list(_flat_record({}).keys()))
        if formato == "csv":
            stream = io.StringIO()
            frame.to_csv(stream, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
            return _download_response(
                stream.getvalue().encode("utf-8-sig"), base_name + ".csv", "text/csv; charset=utf-8"
            )

        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Boletín ERSeP", index=False)
            worksheet = writer.sheets["Boletín ERSeP"]
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

    # Se exponen para pruebas sin convertirlos en estado global mutable.
    router.state = {
        "repository": repository,
        "manager": manager,
        "database_path": db_path,
    }
    return router
