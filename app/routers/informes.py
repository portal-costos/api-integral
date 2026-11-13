from __future__ import annotations

import base64
import binascii
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse


REPORT_PROFILES = {
    "minorista_agua": {
        "label": "Minorista · solo agua",
        "caracter": "prestadora minorista",
        "servicio": "servicio de agua potable",
    },
    "minorista_cloaca": {
        "label": "Minorista · solo saneamiento",
        "caracter": "prestadora minorista",
        "servicio": "servicio de saneamiento cloacal",
    },
    "minorista_agua_cloaca": {
        "label": "Minorista · agua y saneamiento",
        "caracter": "prestadora minorista",
        "servicio": "servicios de agua potable y saneamiento cloacal",
    },
    "mayorista_agua": {
        "label": "Mayorista · solo agua",
        "caracter": "prestadora mayorista",
        "servicio": "servicio mayorista de agua potable",
    },
    "mayorista_cloaca": {
        "label": "Mayorista · solo saneamiento",
        "caracter": "prestadora mayorista",
        "servicio": "servicio mayorista de saneamiento cloacal",
    },
    "mayorista_agua_cloaca": {
        "label": "Mayorista · agua y saneamiento",
        "caracter": "prestadora mayorista",
        "servicio": "servicios mayoristas de agua potable y saneamiento cloacal",
    },
}

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BLOCKS = 40


def _text(datos: dict[str, Any], key: str, default: str = "") -> str:
    value = datos.get(key, default)
    return str(value).strip() if value is not None else default


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ _-]+", "", value).strip()
    value = re.sub(r"\s+", "_", value)
    return value[:70] or "Prestadora"


def _set_run_font(run, size: float = 11, *, bold: bool | None = None, italic: bool | None = None):
    from docx.shared import Pt

    run.font.name = "Calibri"
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def _set_cell_shading(cell, color: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    color = re.sub(r"[^0-9A-Fa-f]", "", color or "")
    if len(color) != 6:
        return
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), color.upper())


def _add_bottom_border(paragraph, color: str = "B7B7B7", size: str = "6"):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = p_pr.find(qn("w:pBdr"))
    if p_bdr is None:
        p_bdr = OxmlElement("w:pBdr")
        p_pr.append(p_bdr)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    p_bdr.append(bottom)


def _add_page_number(paragraph):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr_text)
    run._r.append(fld_char2)
    _set_run_font(run, 8)


def _configure_document(document):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    section = document.sections[0]
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)
    section.header_distance = Cm(0.7)
    section.footer_distance = Cm(0.8)

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.0
    normal.paragraph_format.space_after = Pt(0)

    header = section.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    logo_path = Path(__file__).resolve().parents[2] / "static" / "assets" / "img" / "institucional" / "logo-ersep.png"
    if logo_path.exists():
        run = hp.add_run()
        run.add_picture(str(logo_path), width=Cm(3.0))
    else:
        run = hp.add_run("ERSeP")
        _set_run_font(run, 12, bold=True)

    sub = header.add_paragraph()
    sub.paragraph_format.space_before = Pt(0)
    sub.paragraph_format.space_after = Pt(1)
    sr = sub.add_run("Subdirección de la Jurisdicción de Costos y Tarifas")
    _set_run_font(sr, 6.5)
    _add_bottom_border(sub, "B7B7B7", "5")

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number(fp)


def _add_body_paragraph(document, text: str, *, indent: float = 0.75, bold_prefix: str | None = None):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.left_indent = Cm(indent)
    paragraph.paragraph_format.right_indent = Cm(0)
    paragraph.paragraph_format.line_spacing = 1.0
    paragraph.paragraph_format.space_after = Pt(5)

    if bold_prefix and text.startswith(bold_prefix):
        prefix = paragraph.add_run(bold_prefix)
        _set_run_font(prefix, 11, bold=True)
        rest = paragraph.add_run(text[len(bold_prefix):])
        _set_run_font(rest, 11)
    else:
        run = paragraph.add_run(text)
        _set_run_font(run, 11)
    return paragraph


def _add_heading(document, numbering: str, title: str, *, level: int = 1):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.left_indent = Cm(0.75 if level == 1 else 1.0)
    paragraph.paragraph_format.space_before = Pt(7 if level == 1 else 5)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.keep_with_next = True
    prefix = f"{numbering} " if numbering else ""
    run = paragraph.add_run(prefix + title)
    _set_run_font(run, 11, bold=True)
    return paragraph


def _add_caption(document, text: str):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    _set_run_font(r, 9, bold=True)
    return p


def _add_source(document, text: str):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    if not text.strip():
        return
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run(text.strip())
    _set_run_font(r, 8, italic=True)


def _add_front_matter(document, datos: dict[str, Any], profile: dict[str, str]):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_after = Pt(16)
    r = p.add_run(_text(datos, "fecha_documento", f"Córdoba, {datetime.now():%d/%m/%Y}.-"))
    _set_run_font(r, 11)

    for label, value in (
        ("Ref.:", _text(datos, "expediente", "Expte. N.º —")),
        ("Asunto:", _text(datos, "asunto", "REVISIÓN TARIFARIA")),
    ):
        p = document.add_paragraph()
        p.paragraph_format.left_indent = None
        p.paragraph_format.space_after = Pt(1)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r1 = p.add_run(label + " ")
        _set_run_font(r1, 10, bold=True)
        r2 = p.add_run(value)
        _set_run_font(r2, 10)

    document.add_paragraph()
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("INFORME TÉCNICO")
    _set_run_font(r, 12, bold=True)

    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(7)
    numero = _text(datos, "numero_it", "XX")
    anio = _text(datos, "anio_it", str(datetime.now().year))
    r = p.add_run(f"Costos y Tarifas N.º {numero}/{anio}")
    _set_run_font(r, 11, bold=True)

    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(12)
    titulo = _text(datos, "titulo_revision") or f"Revisión Tarifaria {_text(datos, 'nombre_prestadora', 'Prestadora')}"
    r = p.add_run(titulo)
    _set_run_font(r, 11, bold=True)


def _decode_image_data(value: str) -> bytes:
    if not value or not isinstance(value, str):
        raise ValueError("La imagen no contiene datos válidos.")
    if value.startswith("data:"):
        try:
            header, encoded = value.split(",", 1)
        except ValueError as exc:
            raise ValueError("Formato de imagen inválido.") from exc
        if ";base64" not in header or not header.lower().startswith("data:image/"):
            raise ValueError("Solo se admiten imágenes pegadas en formato imagen.")
    else:
        encoded = value
    if len(encoded) > MAX_IMAGE_BYTES * 2:
        raise ValueError("Una de las imágenes supera el tamaño máximo permitido.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("No se pudo decodificar una de las imágenes pegadas.") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Una de las imágenes supera 8 MB.")
    return raw


def _rgb_to_hex(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    if m:
        return m.group(1).upper()
    m = re.fullmatch(r"rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,[^)]*)?\)", value)
    if m:
        return "".join(f"{min(255, int(part)):02X}" for part in m.groups())
    return ""


def _add_pasted_table(document, rows: list[Any]):
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    if not rows or not isinstance(rows, list):
        return
    normalized: list[list[dict[str, Any]]] = []
    max_cols = 0
    for row in rows[:250]:
        if not isinstance(row, list):
            continue
        out_row = []
        for cell in row[:20]:
            if isinstance(cell, dict):
                out_row.append(cell)
            else:
                out_row.append({"text": str(cell)})
        max_cols = max(max_cols, len(out_row))
        normalized.append(out_row)
    if not normalized or max_cols == 0:
        return

    table = document.add_table(rows=len(normalized), cols=max_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    table.autofit = True

    for ridx, row in enumerate(normalized):
        for cidx in range(max_cols):
            spec = row[cidx] if cidx < len(row) else {"text": ""}
            cell = table.cell(ridx, cidx)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell.text = ""
            p = cell.paragraphs[0]
            align = str(spec.get("align", "")).lower()
            if align == "center":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif align == "right":
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(str(spec.get("text", "")))
            _set_run_font(r, 8, bold=bool(spec.get("bold", ridx == 0)))
            bg = _rgb_to_hex(str(spec.get("bg", "")))
            if bg and bg not in {"FFFFFF", "00000000"}:
                _set_cell_shading(cell, bg)
        # Repeat the first row on page breaks.
        if ridx == 0:
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            tr_pr = table.rows[0]._tr.get_or_add_trPr()
            tbl_header = OxmlElement("w:tblHeader")
            tbl_header.set(qn("w:val"), "true")
            tr_pr.append(tbl_header)

    after = document.add_paragraph()
    after.paragraph_format.space_after = Pt(2)


def _add_rich_content(document, payload: dict[str, Any]):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    kind = str(payload.get("kind", "")).lower()
    if kind == "image":
        raw = _decode_image_data(str(payload.get("data", "")))
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run()
        try:
            from docx.image.image import Image
            picture = Image.from_blob(raw)
            max_w = Cm(15.3)
            max_h = Cm(20.5)
            if picture.width and picture.height and (picture.height / picture.width) * max_w > max_h:
                run.add_picture(io.BytesIO(raw), height=max_h)
            else:
                run.add_picture(io.BytesIO(raw), width=max_w)
        except Exception as exc:
            raise ValueError("Una imagen pegada no tiene un formato compatible con Word (use PNG o JPG).") from exc
    elif kind == "table":
        _add_pasted_table(document, payload.get("rows") or [])
    elif kind == "text":
        content = str(payload.get("text", "")).strip()
        if content:
            _add_body_paragraph(document, content)


def _add_content_block(document, block: dict[str, Any]):
    title = str(block.get("title", "")).strip()
    text = str(block.get("text", "")).strip()
    source = str(block.get("source", "")).strip()
    payload = block.get("payload") if isinstance(block.get("payload"), dict) else None

    if title:
        _add_caption(document, title)
    if text:
        _add_body_paragraph(document, text)
    if payload:
        _add_rich_content(document, payload)
    if source:
        _add_source(document, source)


def _blocks_by_position(blocks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    valid = {"analisis", "canon", "agua_bloque", "metodologia", "base", "cargos", "cargo", "pre_conclusion", "anexo"}
    grouped = {key: [] for key in valid}
    for block in blocks[:MAX_BLOCKS]:
        if not isinstance(block, dict):
            continue
        pos = str(block.get("position", "analisis")).strip().lower()
        if pos not in valid:
            pos = "analisis"
        if block.get("payload") or str(block.get("text", "")).strip():
            grouped[pos].append(block)
    return grouped


def _add_blocks(document, grouped: dict[str, list[dict[str, Any]]], position: str):
    for block in grouped.get(position, []):
        _add_content_block(document, block)


def _add_legacy_text_or_caption(document, datos: dict[str, Any], key: str, caption: str):
    content = _text(datos, key)
    if content:
        _add_caption(document, caption)
        _add_body_paragraph(document, content)


def _build_revision_report(document, datos: dict[str, Any], tipo: str, profile: dict[str, str], grouped):
    prestadora = _text(datos, "nombre_prestadora", "la prestadora")
    servicio = _text(datos, "servicio", profile["servicio"])
    caracter = _text(datos, "caracter_prestadora", profile["caracter"])
    periodo = _text(datos, "periodo_solicitado", "el período informado")
    porcentaje = _text(datos, "porcentaje_solicitado", "—")

    _add_heading(document, "1.", "Introducción")
    intro = _text(datos, "introduccion") or (
        f"El presente informe tiene por objeto analizar la solicitud presentada por {prestadora}, "
        f"en su carácter de {caracter}, respecto del {servicio}, en el marco del procedimiento de revisión tarifaria vigente."
    )
    _add_body_paragraph(document, intro)

    _add_heading(document, "2.", "Alcance")
    alcance = _text(datos, "alcance") or (
        "El presente informe se circunscribe al análisis de la actualización tarifaria en función de los costos de operación "
        "y mantenimiento del servicio, conforme a la metodología establecida y la normativa vigente aplicable."
    )
    _add_body_paragraph(document, alcance)

    _add_heading(document, "3.", "Antecedentes")
    resolucion = _text(datos, "resolucion_cuadro_vigente")
    if resolucion:
        _add_body_paragraph(document, resolucion)
    convocatoria = _text(datos, "resolucion_convocatoria_audiencia")
    if convocatoria:
        _add_body_paragraph(document, convocatoria)
    antecedentes = _text(datos, "antecedentes_adicionales")
    if antecedentes:
        _add_body_paragraph(document, antecedentes)

    _add_heading(document, "4.", "Análisis de Incremento Tarifario")
    _add_heading(document, "4.1.", "Introducción", level=2)
    texto_solicitud = _text(datos, "texto_solicitud") or (
        f"Con fecha {_text(datos, 'fecha_solicitud', '—')}, la prestadora solicita una revisión tarifaria por un porcentaje "
        f"global de {porcentaje}, correspondiente al período {periodo}."
    )
    _add_body_paragraph(document, texto_solicitud)
    audiencia = _text(datos, "manifestacion_audiencia")
    if audiencia:
        _add_body_paragraph(document, audiencia)
    elif _text(datos, "fecha_audiencia"):
        _add_body_paragraph(
            document,
            f"Con fecha {_text(datos, 'fecha_audiencia')}, se celebró la Audiencia Pública convocada para dar tratamiento "
            "a la solicitud de revisión tarifaria de las prestadoras reguladas por el ERSeP.",
        )

    _add_heading(document, "4.2.", "Definición del período de análisis", level=2)
    periodo_analisis = _text(datos, "periodo_analisis", periodo)
    base = _text(datos, "mes_base_revision_anterior", "el período considerado en la revisión anterior")
    _add_body_paragraph(
        document,
        f"El análisis de costos comprende el período {periodo_analisis}, atento a que la revisión tarifaria anterior "
        f"consideró la variación de precios hasta {base} para la estructura general de costos.",
    )

    _add_heading(document, "4.3.", "Análisis de Costos", level=2)
    promedio = _text(datos, "promedio_indices", "—")
    periodo_indices = _text(datos, "periodo_indices", periodo_analisis)
    _add_body_paragraph(
        document,
        f"A continuación, se analiza la evolución de las variables e índices de precios correspondientes al período "
        f"{periodo_indices}. El promedio de los índices relacionados informado asciende a {promedio}.",
    )
    _add_blocks(document, grouped, "analisis")
    _add_legacy_text_or_caption(document, datos, "grafico_variacion_indices", f"GRÁFICO N.º 1: Variación de Índices de Precios – {periodo_indices}")

    canon = _text(datos, "texto_rubro_canon")
    if canon:
        _add_heading(document, "", "RUBRO CANON", level=2)
        _add_body_paragraph(document, canon)
        _add_blocks(document, grouped, "canon")
        _add_legacy_text_or_caption(document, datos, "tabla_variacion_canon", "TABLA: Variación del Canon")

    agua_bloque = _text(datos, "texto_agua_en_bloque")
    if agua_bloque:
        _add_heading(document, "", "AGUA EN BLOQUE", level=2)
        _add_body_paragraph(document, agua_bloque)
        _add_blocks(document, grouped, "agua_bloque")
        _add_legacy_text_or_caption(document, datos, "tabla_agua_bloque", "TABLA: Agua en Bloque")

    _add_heading(document, "4.4.", "Metodología", level=2)
    metodologia = _text(datos, "metodologia") or (
        "Para determinar la evolución de los costos en el período definido, se utiliza la estructura de costos reconocida, "
        "actualizando sus componentes mediante los índices y comprobantes que resultan aplicables a cada rubro."
    )
    _add_body_paragraph(document, metodologia)
    _add_blocks(document, grouped, "metodologia")
    _add_legacy_text_or_caption(document, datos, "cuadro_estructura_costos", "CUADRO: Estructura de Costos")

    section_no = 5
    if _text(datos, "cantidad_cuentas") or grouped.get("base") or _text(datos, "tabla_base_facturacion"):
        _add_heading(document, f"{section_no}.", "Análisis de Base de Facturación")
        cuentas = _text(datos, "cantidad_cuentas", "—")
        categorias = _text(datos, "categorias_base_facturacion", "las categorías tarifarias vigentes")
        _add_body_paragraph(document, f"La base de facturación informada comprende {cuentas} cuentas, distribuidas entre {categorias}.")
        _add_blocks(document, grouped, "base")
        _add_legacy_text_or_caption(document, datos, "tabla_base_facturacion", "TABLA: Resumen Base de Facturación")
        _add_legacy_text_or_caption(document, datos, "grafico_composicion_liquidacion", "GRÁFICO: Composición de Liquidación")
        _add_legacy_text_or_caption(document, datos, "tabla_comparacion_tarifa_media", "TABLA: Comparación de Tarifa Media")
        section_no += 1

    _add_heading(document, f"{section_no}.", "Cargos Especiales")
    cargos_text = _text(datos, "texto_cargos_especiales") or (
        "Los cargos especiales se actualizan conforme a los índices y criterios regulatorios aplicables a cada concepto, "
        "de acuerdo con la documentación incorporada a las actuaciones."
    )
    _add_body_paragraph(document, cargos_text)
    _add_blocks(document, grouped, "cargos")
    _add_legacy_text_or_caption(document, datos, "tabla_variacion_cargos_especiales", "TABLA: Variación de Cargos Especiales")
    if _text(datos, "texto_cargos_especiales_cloacas"):
        _add_body_paragraph(document, _text(datos, "texto_cargos_especiales_cloacas"))
    section_no += 1

    if tipo == "cargo_tarifario":
        _add_heading(document, f"{section_no}.", "Cargo Tarifario por Amortización e Inversiones")
        _add_body_paragraph(
            document,
            f"El Cargo Tarifario se analiza conforme a {_text(datos, 'resolucion_plan_obras', 'la resolución aplicable')} y "
            f"{_text(datos, 'it_seccion_tecnica', 'el informe de la Sección Técnica')}. Se considera un plazo de "
            f"{_text(datos, 'plazo_cargo_tarifario', '—')} meses y un valor de {_text(datos, 'valor_cargo_tarifario', '—')}."
        )
        _add_blocks(document, grouped, "cargo")
        _add_legacy_text_or_caption(document, datos, "tabla_rebalanceo_cargo_tarifario", "TABLA: Rebalanceo del Cargo Tarifario")
        section_no += 1

    _add_blocks(document, grouped, "pre_conclusion")
    _add_heading(document, f"{section_no}.", "Conclusión")
    conclusion = _text(datos, "conclusion_adicional") or (
        "En base al análisis desarrollado, se sugiere aplicar un incremento de "
        f"{_text(datos, 'incremento_final_sugerido', '—')} sobre los cargos que correspondan del cuadro tarifario vigente, "
        "conforme a los criterios expuestos en el presente informe."
    )
    _add_body_paragraph(document, conclusion)


def _build_initial_report(document, datos: dict[str, Any], tipo: str, profile: dict[str, str], grouped):
    prestadora = _text(datos, "nombre_prestadora", "la prestadora")
    servicio = _text(datos, "servicio", profile["servicio"])

    _add_heading(document, "1.", "Antecedentes")
    for key in ("resolucion_cuadro_vigente", "resolucion_convocatoria_audiencia", "antecedentes_adicionales"):
        value = _text(datos, key)
        if value:
            _add_body_paragraph(document, value)

    _add_heading(document, "2.", "Introducción")
    intro = _text(datos, "introduccion") or (
        f"Se elabora el presente informe técnico con el objeto de determinar una tarifa inicial para {prestadora}, "
        f"correspondiente al {servicio}, sobre la base de la información incorporada al expediente de la referencia."
    )
    _add_body_paragraph(document, intro)

    _add_heading(document, "3.", "Análisis Tarifario")
    _add_heading(document, "3.1.", "Objetivo", level=2)
    objetivo = _text(datos, "objetivo") or f"El objeto del presente informe es determinar un valor tarifario inicial de referencia para el {servicio}."
    _add_body_paragraph(document, objetivo)

    _add_heading(document, "3.2.", "Definición del período de análisis", level=2)
    _add_body_paragraph(document, _text(datos, "texto_periodo_inicial") or f"El período de costos considerado corresponde a {_text(datos, 'periodo_analisis', 'la información presentada por la prestadora')}.")

    _add_heading(document, "3.3.", "Metodología", level=2)
    _add_body_paragraph(document, _text(datos, "metodologia") or "La estructura de costos se construye a partir de los costos de operación y mantenimiento informados y respaldados en las actuaciones, con el objeto de determinar el recupero requerido por la prestación.")
    _add_blocks(document, grouped, "analisis")

    _add_heading(document, "4.", "Determinación de la Estructura de Costos")
    costos = _text(datos, "texto_estructura_inicial") or "Se detallan a continuación los principales rubros considerados para la determinación de la estructura de costos del servicio."
    _add_body_paragraph(document, costos)
    _add_blocks(document, grouped, "metodologia")
    _add_legacy_text_or_caption(document, datos, "cuadro_estructura_costos", "CUADRO: Estructura de Costos")

    _add_heading(document, "5.", "Estructura Tarifaria Única")
    _add_body_paragraph(document, _text(datos, "texto_etu") or "En este apartado se definen los valores del cuadro tarifario conforme a la Estructura Tarifaria Única y a la normativa regulatoria aplicable.")
    _add_blocks(document, grouped, "base")
    _add_legacy_text_or_caption(document, datos, "tabla_base_facturacion", "CUADRO: Recupero y estructura tarifaria")

    _add_heading(document, "6.", "Cargos Especiales")
    _add_body_paragraph(document, _text(datos, "texto_cargos_especiales") or "Se determinan los cargos especiales aplicables conforme a la Estructura Tarifaria Única y a los costos asociados a cada prestación específica.")
    _add_blocks(document, grouped, "cargos")
    _add_legacy_text_or_caption(document, datos, "tabla_variacion_cargos_especiales", "CUADRO: Cargos Especiales")

    section_no = 7
    if tipo == "cargo_tarifario":
        _add_heading(document, "7.", "Cargo Tarifario")
        _add_body_paragraph(document, _text(datos, "texto_cargo_tarifario") or f"Se analiza el Cargo Tarifario propuesto por un plazo de {_text(datos, 'plazo_cargo_tarifario', '—')} meses y un valor de {_text(datos, 'valor_cargo_tarifario', '—')}.")
        _add_blocks(document, grouped, "cargo")
        section_no = 8

    _add_blocks(document, grouped, "pre_conclusion")
    _add_heading(document, f"{section_no}.", "Conclusión")
    _add_body_paragraph(document, _text(datos, "conclusion_adicional") or "En base al estudio desarrollado, se sugiere la aprobación del cuadro tarifario inicial que se expone en el Anexo del presente informe.")


def build_report(
    datos: dict[str, Any],
    tipo: str,
    perfil: str = "minorista_agua",
    modalidad: str = "revision",
    bloques: list[dict[str, Any]] | None = None,
) -> tuple[bytes, str]:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("Falta la dependencia python-docx. Ejecutá: pip install python-docx") from exc

    profile = REPORT_PROFILES.get(perfil, REPORT_PROFILES["minorista_agua"])
    bloques = bloques or []
    grouped = _blocks_by_position(bloques)

    document = Document()
    _configure_document(document)
    _add_front_matter(document, datos, profile)

    if modalidad == "tarifa_inicial":
        _build_initial_report(document, datos, tipo, profile, grouped)
    else:
        _build_revision_report(document, datos, tipo, profile, grouped)

    annex_blocks = grouped.get("anexo", [])
    legacy_annexes = [
        ("ANEXO I: CUADRO TARIFARIO", _text(datos, "anexo_cuadro_tarifario")),
        ("ANEXO: LISTADO DE INVERSIONES", _text(datos, "anexo_listado_inversiones")),
    ]
    if annex_blocks or any(content for _, content in legacy_annexes):
        document.add_page_break()
        for title, content in legacy_annexes:
            if content:
                _add_caption(document, title)
                _add_body_paragraph(document, content)
        for block in annex_blocks:
            _add_content_block(document, block)

    output = io.BytesIO()
    document.save(output)
    output.seek(0)

    prestadora = _text(datos, "nombre_prestadora", "Prestadora")
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

            perfil = str(body.get("perfil", "minorista_agua")).strip().lower()
            if perfil not in REPORT_PROFILES:
                raise ValueError("El perfil del informe no es válido.")

            modalidad = str(body.get("modalidad", "revision")).strip().lower()
            if modalidad not in {"revision", "tarifa_inicial"}:
                raise ValueError("La modalidad del informe no es válida.")

            datos = body.get("datos")
            if not isinstance(datos, dict):
                raise ValueError("No se recibieron los datos del informe.")

            bloques = body.get("bloques") or []
            if not isinstance(bloques, list):
                raise ValueError("Los bloques técnicos no tienen un formato válido.")
            if len(bloques) > MAX_BLOCKS:
                raise ValueError(f"Se admiten como máximo {MAX_BLOCKS} bloques técnicos por informe.")

            content, filename = build_report(datos, tipo, perfil, modalidad, bloques)
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
