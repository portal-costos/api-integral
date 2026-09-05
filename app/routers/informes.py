from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse


def _text(datos: dict[str, Any], key: str, default: str = "") -> str:
    value = datos.get(key, default)
    return str(value).strip() if value is not None else default


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ _-]+", "", value).strip()
    value = re.sub(r"\s+", "_", value)
    return value[:70] or "Prestadora"


def _set_cell_text(cell, value: str, *, bold: bool = False, align=None):
    from docx.shared import Pt

    cell.text = ""
    paragraph = cell.paragraphs[0]
    if align is not None:
        paragraph.alignment = align
    run = paragraph.add_run(value)
    run.bold = bold
    run.font.name = "Times New Roman"
    run.font.size = Pt(11)


def _add_body_paragraph(document, text: str, *, bold_prefix: str | None = None):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.line_spacing = 1
    paragraph.paragraph_format.space_after = Pt(6)

    if bold_prefix and text.startswith(bold_prefix):
        prefix = paragraph.add_run(bold_prefix)
        prefix.bold = True
        prefix.font.name = "Times New Roman"
        prefix.font.size = Pt(12)
        rest = paragraph.add_run(text[len(bold_prefix):])
        rest.font.name = "Times New Roman"
        rest.font.size = Pt(12)
    else:
        run = paragraph.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
    return paragraph


def _add_section_title(document, roman: str, title: str):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(6)
    prefix = f"{roman}. " if roman else ""
    run = paragraph.add_run(prefix + title.upper())
    run.bold = True
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    return paragraph


def _add_optional_text(document, title: str, content: str):
    if not content.strip():
        return
    _add_section_title(document, "", title)
    _add_body_paragraph(document, content.strip())


def build_report(datos: dict[str, Any], tipo: str) -> tuple[bytes, str]:
    try:
        from docx import Document
        from docx.enum.section import WD_SECTION
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Pt
    except ImportError as exc:
        raise RuntimeError(
            "Falta la dependencia python-docx. Ejecutá: pip install python-docx"
        ) from exc

    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(3)
    section.right_margin = Cm(3)

    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = 1
    normal.paragraph_format.space_after = Pt(6)

    # Encabezado institucional sobrio.
    header_table = document.add_table(rows=1, cols=2)
    header_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header_table.autofit = False
    header_table.columns[0].width = Cm(5)
    header_table.columns[1].width = Cm(10)
    _set_cell_text(header_table.cell(0, 0), "ERSeP", bold=True)
    _set_cell_text(
        header_table.cell(0, 1),
        "Gerencia de Agua y Saneamiento\nSubdirección de Jurisdicción de Costos y Tarifas",
        bold=True,
        align=WD_ALIGN_PARAGRAPH.RIGHT,
    )
    for cell in header_table.rows[0].cells:
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        tc_pr = cell._tc.get_or_add_tcPr()
        borders = OxmlElement("w:tcBorders")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "8")
        bottom.set(qn("w:color"), "1E3A8A")
        borders.append(bottom)
        tc_pr.append(borders)

    document.add_paragraph()

    date_paragraph = document.add_paragraph()
    date_paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date_run = date_paragraph.add_run(
        _text(datos, "fecha_documento", f"Córdoba, {datetime.now():%d/%m/%Y}.-")
    )
    date_run.font.name = "Times New Roman"
    date_run.font.size = Pt(12)

    reference = document.add_table(rows=2, cols=2)
    reference.alignment = WD_TABLE_ALIGNMENT.LEFT
    reference.style = "Table Grid"
    _set_cell_text(reference.cell(0, 0), "Ref.:", bold=True)
    _set_cell_text(reference.cell(0, 1), _text(datos, "expediente", "Sin especificar"))
    _set_cell_text(reference.cell(1, 0), "Asunto:", bold=True)
    _set_cell_text(reference.cell(1, 1), _text(datos, "asunto", "REVISIÓN TARIFARIA"))

    document.add_paragraph()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(12)
    title_run = title.add_run(
        "INFORME TÉCNICO DE COSTOS Y TARIFAS N.º "
        f"{_text(datos, 'numero_it', 'XX')}/{_text(datos, 'anio_it', str(datetime.now().year))}"
    )
    title_run.bold = True
    title_run.font.name = "Times New Roman"
    title_run.font.size = Pt(13)

    prestadora = _text(datos, "nombre_prestadora", "la prestadora")
    servicio = _text(datos, "servicio", "servicio público")
    periodo = _text(datos, "periodo_solicitado", "el período informado")
    porcentaje = _text(datos, "porcentaje_solicitado", "el porcentaje solicitado")

    _add_section_title(document, "I", "Objeto")
    _add_body_paragraph(
        document,
        "El presente Informe Técnico tiene por objeto analizar la solicitud de revisión tarifaria "
        f"presentada por {prestadora}, vinculada con {servicio}, correspondiente a {periodo}. "
        "El análisis se realiza con base en los antecedentes incorporados a las actuaciones, la "
        "información económica disponible y los criterios regulatorios aplicables.",
    )

    _add_section_title(document, "II", "Antecedentes")
    _add_body_paragraph(
        document,
        f"La solicitud fue presentada con fecha {_text(datos, 'fecha_solicitud', 'no informada')} "
        f"y propone una variación de {porcentaje}. El cuadro tarifario vigente surge de "
        f"{_text(datos, 'resolucion_cuadro_vigente', 'la resolución vigente')}. "
        f"La convocatoria a Audiencia Pública se instrumentó mediante "
        f"{_text(datos, 'resolucion_convocatoria_audiencia', 'el acto administrativo correspondiente')}, "
        f"celebrándose la instancia participativa el {_text(datos, 'fecha_audiencia', 'día informado en las actuaciones')}.",
    )
    antecedentes = _text(datos, "antecedentes_adicionales")
    if antecedentes:
        _add_body_paragraph(document, antecedentes)
    manifestacion = _text(datos, "manifestacion_audiencia")
    if manifestacion:
        _add_body_paragraph(document, manifestacion)

    _add_section_title(document, "III", "Análisis económico y tarifario")
    _add_body_paragraph(
        document,
        f"El período de análisis considerado comprende {_text(datos, 'periodo_analisis', periodo)}. "
        f"Para la actualización de los componentes se evaluaron los índices correspondientes a "
        f"{_text(datos, 'periodo_indices', periodo)}, tomando como referencia "
        f"{_text(datos, 'mes_base_revision_anterior', 'el mes base de la revisión anterior')}. "
        f"El promedio de variaciones informado asciende a {_text(datos, 'promedio_indices', '—')}, "
        f"mientras que el incremento calculado es de {_text(datos, 'incremento_calculado', '—')}.",
    )

    metrics = document.add_table(rows=1, cols=4)
    metrics.alignment = WD_TABLE_ALIGNMENT.CENTER
    metrics.style = "Table Grid"
    metric_items = (
        ("Pedido", porcentaje),
        ("Promedio de índices", _text(datos, "promedio_indices", "—")),
        ("Incremento calculado", _text(datos, "incremento_calculado", "—")),
        ("Sugerencia técnica", _text(datos, "incremento_final_sugerido", "—")),
    )
    for idx, (label, value) in enumerate(metric_items):
        cell = metrics.cell(0, idx)
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = p.add_run(label + "\n")
        r1.bold = True
        r1.font.name = "Times New Roman"
        r1.font.size = Pt(10)
        r2 = p.add_run(value)
        r2.font.name = "Times New Roman"
        r2.font.size = Pt(12)

    for title_text, key in (
        ("Canon", "texto_rubro_canon"),
        ("Agua en bloque", "texto_agua_en_bloque"),
        ("Estructura de costos", "cuadro_estructura_costos"),
        ("Variación de índices", "grafico_variacion_indices"),
    ):
        content = _text(datos, key)
        if content:
            _add_section_title(document, "", title_text)
            _add_body_paragraph(document, content)

    _add_section_title(document, "IV", "Base de facturación y cargos asociados")
    _add_body_paragraph(
        document,
        f"La base informada comprende {_text(datos, 'cantidad_cuentas', '—')} cuentas, distribuidas "
        f"entre {_text(datos, 'categorias_base_facturacion', 'las categorías tarifarias vigentes')}. "
        f"Se considera un consumo presuntivo de {_text(datos, 'consumo_presuntivo_m3', '—')} m³ cuando "
        "corresponde. Los cargos especiales fueron analizados con referencia a "
        f"{_text(datos, 'mes_actualizacion_cargos_especiales', 'el período pertinente')}.",
    )

    if tipo == "cargo_tarifario":
        _add_section_title(document, "V", "Cargo tarifario")
        _add_body_paragraph(
            document,
            f"El componente de Cargo Tarifario se analiza conforme "
            f"{_text(datos, 'resolucion_plan_obras', 'al acto administrativo aplicable')} y al "
            f"{_text(datos, 'it_seccion_tecnica', 'informe de la sección técnica')}. Se propone un plazo "
            f"de {_text(datos, 'plazo_cargo_tarifario', '—')} meses y un valor de "
            f"{_text(datos, 'valor_cargo_tarifario', '—')}.",
        )
        rebalanceo = _text(datos, "tabla_rebalanceo_cargo_tarifario")
        if rebalanceo:
            _add_body_paragraph(document, rebalanceo)
        conclusion_roman = "VI"
    else:
        conclusion_roman = "V"

    _add_section_title(document, conclusion_roman, "Conclusión")
    conclusion = _text(datos, "conclusion_adicional")
    if conclusion:
        _add_body_paragraph(document, conclusion)
    else:
        _add_body_paragraph(
            document,
            "En función del análisis desarrollado, esta Subdirección considera técnicamente procedente "
            f"un incremento de {_text(datos, 'incremento_final_sugerido', '—')}, sujeto a las decisiones "
            "que adopte la superioridad y a la verificación de los restantes extremos regulatorios y administrativos.",
        )

    optional_sections = (
        ("Tabla de variación del canon", "tabla_variacion_canon"),
        ("Tabla de agua en bloque", "tabla_agua_bloque"),
        ("Composición de la liquidación", "grafico_composicion_liquidacion"),
        ("Base de facturación", "tabla_base_facturacion"),
        ("Comparación de tarifa media", "tabla_comparacion_tarifa_media"),
        ("Cargo tarifario y tarifa media", "texto_adicional_cargo_tarifario_tarifa_media"),
        ("Variación de cargos especiales", "tabla_variacion_cargos_especiales"),
        ("Cargos especiales de cloacas", "texto_cargos_especiales_cloacas"),
        ("Anexo — Cuadro tarifario", "anexo_cuadro_tarifario"),
        ("Anexo — Listado de inversiones", "anexo_listado_inversiones"),
    )
    for heading, key in optional_sections:
        content = _text(datos, key)
        if content:
            document.add_page_break()
            _add_section_title(document, "ANEXO", heading)
            _add_body_paragraph(document, content)

    output = io.BytesIO()
    document.save(output)
    output.seek(0)

    filename = (
        f"IT_N_{_safe_filename(_text(datos, 'numero_it', 'XX'))}_"
        f"{_safe_filename(_text(datos, 'anio_it', str(datetime.now().year)))}_"
        f"{_safe_filename(prestadora)}.docx"
    )
    return output.getvalue(), filename


def create_informes_router(require_auth: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/informes", tags=["Informes Técnicos"])

    @router.post("/generar")
    def generar(body: dict, auth: bool = Depends(require_auth)):
        try:
            tipo = str(body.get("tipo", "comun")).strip().lower()
            if tipo not in {"comun", "cargo_tarifario"}:
                raise ValueError("El tipo de informe no es válido.")
            datos = body.get("datos")
            if not isinstance(datos, dict):
                raise ValueError("No se recibieron los datos del informe.")
            content, filename = build_report(datos, tipo)
            encoded = quote(filename)
            return StreamingResponse(
                io.BytesIO(content),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo generar el Informe Técnico: {exc}") from exc

    return router
