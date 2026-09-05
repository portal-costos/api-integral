from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .boletin_repository import BoletinRepositorio

try:
    import fitz  # PyMuPDF

    FITZ_AVAILABLE = True
    FITZ_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - depende del entorno
    fitz = None
    FITZ_AVAILABLE = False
    FITZ_IMPORT_ERROR = str(exc)


BOLETIN_BASE_URL = "https://boletinoficial.cba.gov.ar"
BOLETIN_ALLOWED_HOST = "boletinoficial.cba.gov.ar"
BOLETIN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MIN_TEXT_CHARS = 600

PAT_RESOLUTION = re.compile(
    r"Resoluci[oó]n\s+General\s+N[°º\.]\s*(\d+)"
    r"(?:\s*[-–]\s*Letra\s*:?\s*[A-Z])?",
    re.IGNORECASE,
)
PAT_ERSEP_SECTION = re.compile(
    r"ENTE\s+REGULADOR\s+DE\s+(?:LOS\s+)?SERVICIOS\s+P[ÚU]BLICOS"
    r"(?:\s*[-–\n]\s*ERSEP)?",
    re.IGNORECASE,
)
PAT_RESUELVE = re.compile(
    r"(?:el\s+(?:honorable\s+)?directorio\s+del\s+ente\s+regulador"
    r"(?:\s+de\s+(?:los\s+)?servicios\s+p[uú]blicos)?"
    r"(?:\s*\(ersep\))?\s*[,:]\s*(?:por\s+mayor[ií]a\s*[^)]*\)\s*)?)?"
    r"(?:el\s+directorio\s+)?resuelve\s*:",
    re.IGNORECASE,
)
PAT_RESOLUTION_END = re.compile(
    r"(?:^|\n)\s*(?:fdo\.|fdo:|firmado|f\.d\.o\.|"
    r"anexo\s+(?:[ivxlc]+|\d+)|"
    r"resoluci[oó]n\s+general\s+n[°º\.]\s*\d)",
    re.IGNORECASE,
)
PAT_EXPEDIENT_LABEL = re.compile(
    r"\b(?:expediente|expte\.?|actuaciones)\s*(?:administrativ[oa]s?\s*)?"
    r"(?:n(?:ro\.?|[°º.]?)\s*)?(?:[:#-]\s*)?",
    re.IGNORECASE,
)
PAT_EXPEDIENT_FORMATS = (
    re.compile(r"\b(?:EX|EE)-\d{4}-\d{5,12}(?:-\s*-[A-Z]{2,12}(?:-[A-Z0-9#-]+)?)?\b", re.IGNORECASE),
    re.compile(r"\b\d{3,6}\s*-\s*\d{3,12}\s*/\s*\d{2,4}\b"),
    re.compile(r"\b\d{3,6}\s*[-/]\s*\d{4,12}\b"),
)
PAT_EMISSION_DATE = re.compile(
    r"C[oó]rdoba\s*,?\s*(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
    r"\s+de\s+(\d{4})",
    re.IGNORECASE,
)
PAT_ANNEX_HEADING = re.compile(
    r"(?im)^\s*(ANEXO(?:\s+(?:[IVXLCDM]+|\d+))?(?:\s*[-–—:]\s*[^\n]{0,120})?)\s*$"
)
PAT_ANNEX_MENTION = re.compile(
    r"\b(?:forma\s+parte\s+integrante|cuadro\s+tarifario\s+adjunto|"
    r"anexo(?:\s+[IVXLCDM]+|\s+\d+)?)\b",
    re.IGNORECASE,
)

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

GENERIC_ALERT_PHRASES = {
    "cooperativa",
    "limitada",
    "servicios publicos",
    "agua potable",
    "municipalidad",
    "prestadora",
    "cordoba",
}


def now_label() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_pdf_text(value: Any) -> str:
    text = str(value or "").replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"[\t\r]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def validate_official_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == BOLETIN_ALLOWED_HOST or host.endswith("." + BOLETIN_ALLOWED_HOST)):
        raise ValueError("La URL no pertenece al dominio oficial permitido del Boletín.")
    return url


def contains_ersep(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        pattern in normalized
        for pattern in (
            "ente regulador de servicios publicos",
            "ente regulador de los servicios publicos",
            "ersep",
        )
    )


def is_body_resolution_match(full_text: str, match: re.Match) -> bool:
    after = full_text[match.end(): match.end() + 320]
    if re.search(r"\bP[aá]g\.", after[:100], re.IGNORECASE):
        return False
    return bool(re.search(r"C[oó]rdoba|VISTO|Y\s+CONSIDERANDO|Ref\.", after, re.IGNORECASE))


def find_ersep_section_start(full_text: str) -> int:
    for match in PAT_ERSEP_SECTION.finditer(full_text):
        region = full_text[match.start(): match.start() + 850]
        resolution = PAT_RESOLUTION.search(region)
        if not resolution:
            continue
        after = region[resolution.end(): resolution.end() + 350]
        if "Pag." not in after[:100] and re.search(
            r"C[oó]rdoba|VISTO|Y\s+CONSIDERANDO|Ref\.", after, re.IGNORECASE
        ):
            return match.start()
    return -1


def extract_provider(block: str) -> str:
    compact = re.sub(r"\s+", " ", compact_pdf_text(block)).strip()
    entity = (
        r"(?:Cooperativa|Aguas?|Municipalidad|Comuna|Empresa|Asociaci[oó]n|Acci[oó]n)"
        r"[^.;]{3,240}?(?:Limitada|Ltda\.?|S\.?A\.?|Sociedad\s+An[oó]nima)"
    )
    patterns = [
        rf"prestadora[^.;]{{0,180}}?({entity})(?=\s*,|\s+por\s+la\s+cual|\s+mediante)",
        rf"presentaci[oó]n\s+promovida\s+por[^.;]{{0,100}}?({entity})",
        rf"correspondiente\s+a\s+la\s+prestadora[^.;]{{0,100}}?({entity})",
        rf"\b({entity})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, re.IGNORECASE)
        if match:
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,.-")
            candidate = re.sub(
                r"^(?:Agua(?:s)?(?: Potable)?(?: y Saneamiento)?|Saneamiento(?: Cloacal)?)"
                r"(?:\s+la)?\s+(?=(?:Cooperativa|Aguas|Municipalidad|Comuna|Empresa|Asociaci[oó]n|Acci[oó]n)\b)",
                "",
                candidate,
                flags=re.IGNORECASE,
            ).strip(" ,.-")
            if len(candidate) >= 8:
                return candidate
    return ""


def extract_resuelve(resolution_text: str) -> str:
    start_match = PAT_RESUELVE.search(resolution_text)
    if not start_match:
        return ""
    start = start_match.start()
    rest = resolution_text[start:]
    end_match = PAT_RESOLUTION_END.search(rest[10:])
    if end_match:
        return rest[:10 + end_match.start()].strip()
    return rest.strip()


def extract_expediente(text: str) -> str:
    """Extrae formatos de expediente habituales sin completar datos por inferencia."""
    def clean(value: str) -> str:
        protected = re.sub(r"-\s+-", "§", value)
        protected = re.sub(r"\s*([-/])\s*", r"\1", protected)
        return protected.replace("§", "- -").strip(" .,:;-")

    source = compact_pdf_text(text)
    for label in PAT_EXPEDIENT_LABEL.finditer(source):
        region = source[label.end(): label.end() + 180]
        for pattern in PAT_EXPEDIENT_FORMATS:
            match = pattern.search(region)
            if match:
                value = clean(match.group(0))
                if value:
                    return value
    # Los expedientes electrónicos poseen un prefijo inequívoco y pueden aparecer sin etiqueta.
    electronic = PAT_EXPEDIENT_FORMATS[0].search(source)
    if electronic:
        return clean(electronic.group(0))
    return ""


def extract_emission_date(text: str) -> str:
    match = PAT_EMISSION_DATE.search(compact_pdf_text(text))
    if not match:
        return ""
    day = int(match.group(1))
    month = SPANISH_MONTHS.get(match.group(2).casefold())
    year = int(match.group(3))
    if not month:
        return ""
    try:
        return datetime(year, month, day).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def extract_issuing_body(text: str, ersep_context: bool = False) -> str:
    if ersep_context or contains_ersep(text):
        return "Ente Regulador de los Servicios Públicos (ERSeP)"
    return ""


def extract_initial_preview(text: str, max_chars: int = 760) -> str:
    """Devuelve únicamente el encabezado y primer párrafo, no un resumen inventado."""
    source = compact_pdf_text(text).strip()
    if not source:
        return "(vista previa no disponible)"
    considered = source
    considering = re.search(r"\bY\s+CONSIDERANDO\s*:", considered, re.IGNORECASE)
    if considering:
        considered = considered[:considering.start()]
    else:
        blank = re.search(r"\n\s*\n", considered)
        if blank and blank.start() > 80:
            considered = considered[:blank.start()]
    preview = re.sub(r"\s+", " ", considered).strip()
    if len(preview) > max_chars:
        preview = preview[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return preview or "(vista previa no disponible)"


def detect_embedded_annexes(text: str, source_url: str = "") -> list[dict[str, Any]]:
    source = compact_pdf_text(text)
    matches = list(PAT_ANNEX_HEADING.finditer(source))
    annexes: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[match.start():end].strip()
        annexes.append(
            {
                "nombre": re.sub(r"\s+", " ", match.group(1)).strip(),
                "tipo": "integrado",
                "url": source_url,
                "texto": body,
            }
        )
    if not annexes:
        mention = PAT_ANNEX_MENTION.search(source)
        if mention:
            start = max(0, mention.start() - 160)
            end = min(len(source), mention.end() + 900)
            annexes.append(
                {
                    "nombre": "Anexo mencionado en la resolución",
                    "tipo": "mencionado",
                    "url": source_url,
                    "texto": source[start:end].strip(),
                }
            )
    return annexes


def split_resolutions(full_text: str) -> list[dict[str, Any]]:
    section_start = find_ersep_section_start(full_text)
    if section_start < 0:
        return []
    body_matches = [
        match for match in PAT_RESOLUTION.finditer(full_text)
        if is_body_resolution_match(full_text, match) and match.start() >= section_start
    ]
    output: list[dict[str, Any]] = []
    for index, match in enumerate(body_matches):
        start = match.start()
        end = body_matches[index + 1].start() if index + 1 < len(body_matches) else len(full_text)
        block = full_text[start:end].strip()
        output.append(
            {
                "numero": re.sub(r"\s+", " ", match.group(0)).strip(),
                "prestadora": extract_provider(block),
                "texto_completo": block,
                "texto_resuelve": extract_resuelve(block),
                "expediente": extract_expediente(block),
                "fecha_emision": extract_emission_date(block),
                "organismo_emisor": extract_issuing_body(block, ersep_context=True),
            }
        )
    return output


def extract_keywords(text: str, keywords: list[str]) -> list[str]:
    normalized = " " + normalize_text(text) + " "
    matches: list[str] = []
    for keyword in keywords:
        key = normalize_text(keyword)
        if key and f" {key} " in normalized:
            matches.append(keyword)
    return matches


def alert_phrases(alert: dict[str, Any]) -> list[str]:
    raw = str(alert.get("aliases") or alert.get("keywords") or "")
    pieces = re.split(r"[;|\n]+", raw)
    pieces.append(str(alert.get("nombre") or ""))
    output: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        phrase = re.sub(r"\s+", " ", piece).strip(" .,-")
        key = normalize_text(phrase)
        if len(key) < 4 or key in seen or key in GENERIC_ALERT_PHRASES:
            continue
        if len(key.split()) == 1 and len(key) < 6:
            continue
        seen.add(key)
        output.append(phrase)
    return output


def match_alerts(text: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = " " + normalize_text(text) + " "
    output: list[dict[str, Any]] = []
    for alert in alerts:
        found: list[str] = []
        for phrase in alert_phrases(alert):
            key = normalize_text(phrase)
            if key and f" {key} " in normalized:
                found.append(phrase)
        if found:
            output.append({"id": alert.get("id"), "nombre": alert.get("nombre", ""), "claves": found})
    return output


def detect_state(text: str) -> str:
    normalized = normalize_text(text)
    if re.search(r"\b(rectific(?:ar|ase)|modific(?:ar|ase)|sustituy(?:ese|ase)|corregir)\b", normalized):
        return "RECTIFICACIÓN / MODIFICACIÓN"
    if re.search(r"\b(rechaz(?:ar|ase)|no hacer lugar|desestim(?:ar|ase))\b", normalized):
        return "RECHAZADO / DESESTIMADO"
    if "audiencia publica" in normalized and re.search(r"\b(convoc(?:ar|ase)|llamar)\b", normalized):
        return "CONVOCA AUDIENCIA PÚBLICA"
    if re.search(r"\b(aprueb(?:a|ase)|autoriz(?:ar|ase)|fij(?:ar|ase)|establec(?:er|ese))\b", normalized):
        if re.search(r"tarif|increment|aument|cuadro tarifario|cargo tarifario", normalized):
            return "APROBACIÓN TARIFARIA"
        return "APROBADO / AUTORIZADO"
    if re.search(r"\b(prorrog(?:ar|ase))\b", normalized):
        return "PRÓRROGA"
    return "PUBLICACIÓN ERSeP"


def extract_excerpt(text: str, terms: list[str], max_chars: int = 520) -> str:
    compact = re.sub(r"\s+", " ", compact_pdf_text(text)).strip()
    if not compact:
        return "(sin extracto disponible)"
    normalized = normalize_text(compact)
    positions = [normalized.find(normalize_text(term)) for term in terms if normalize_text(term)]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - 130)
    end = min(len(compact), start + max_chars)
    excerpt = compact[start:end].strip()
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(compact):
        excerpt += "…"
    return excerpt


def stable_key_for(year: int, resolution_number: str) -> str:
    return sha256_text(f"ERSEP|{int(year)}|{normalize_text(resolution_number)}")


def content_hash_for(finding: dict[str, Any]) -> str:
    content = "\n".join(
        [
            finding.get("numero", ""),
            finding.get("prestadora", ""),
            finding.get("texto_completo", ""),
            finding.get("texto_resuelve", ""),
            finding.get("estado_detectado", ""),
        ]
    )
    return sha256_text(normalize_text(content))


def llm_text(findings: list[dict[str, Any]], year: int) -> str:
    news = [item for item in findings if item.get("novedad") in {"NUEVO", "MODIFICADO"}]
    lines = [
        "MONITOREO DE RESOLUCIONES TARIFARIAS — ERSeP / BOLETÍN OFICIAL DE CÓRDOBA",
        f"AÑO ANALIZADO: {year}",
        f"FECHA DE GENERACIÓN: {now_label()}",
        f"NOVEDADES DETECTADAS: {len(news)}",
        "",
        "INSTRUCCIÓN PARA EL MODELO DE LENGUAJE:",
        "Analizá cada publicación y respondé en dos líneas por resolución. Indicá si se aprueba,",
        "rechaza, rectifica o convoca una revisión/audiencia tarifaria; identificá expediente,",
        "prestadora y porcentaje o valor aprobado cuando esos datos estén expresamente informados.",
        "No inventes datos ausentes y diferenciá claramente lo solicitado de lo efectivamente aprobado.",
        "",
    ]
    for index, item in enumerate(news, start=1):
        lines.extend(
            [
                "=" * 82,
                f"NOVEDAD {index} DE {len(news)}",
                f"TIPO DE CAMBIO: {item.get('novedad', '')}",
                f"COOPERATIVA / ALERTA: {item.get('cooperativa', '')}",
                f"PRESTADORA EXTRAÍDA: {item.get('prestadora', '')}",
                f"NORMA: {item.get('numero', '')}",
                f"ESTADO HEURÍSTICO: {item.get('estado_detectado', '')}",
                f"FECHA DEL BOLETÍN: {item.get('fecha', '')}",
                f"EXPEDIENTE: {item.get('expediente') or 'Expediente no identificado'}",
                f"ARCHIVO: {item.get('archivo', '')}",
                f"URL OFICIAL: {item.get('url', '')}",
                f"TÉRMINOS COINCIDENTES: {', '.join(item.get('terminos_encontrados', []))}",
                "",
                "EXTRACTO CLAVE:",
                item.get("extracto", ""),
                "",
                "BLOQUE RESUELVE:",
                item.get("texto_resuelve", "") or "(no detectado)",
                "",
                "TEXTO COMPLETO DE LA SUBRESOLUCIÓN EXTRAÍDA:",
                item.get("texto_completo", ""),
                "",
            ]
        )
    if not news:
        lines.append("No se detectaron publicaciones nuevas ni modificadas en esta ejecución.")
    return "\n".join(lines)


@dataclass
class JobRuntime:
    run_id: int
    stop_event: threading.Event
    thread: threading.Thread


class BoletinJobManager:
    def __init__(self, repository: BoletinRepositorio, timeout: int = 45):
        self.repository = repository
        self.timeout = max(10, int(timeout))
        self._lock = threading.RLock()
        self._jobs: dict[int, JobRuntime] = {}
        self.repository.interrupt_unfinished_runs()

    def start(self, config: dict[str, Any]) -> int:
        if not FITZ_AVAILABLE:
            raise RuntimeError(f"PyMuPDF no está disponible: {FITZ_IMPORT_ERROR or 'instalá pymupdf'}")
        with self._lock:
            self._cleanup_finished_locked()
            if any(runtime.thread.is_alive() for runtime in self._jobs.values()):
                raise RuntimeError("Ya existe un monitoreo en ejecución. Detenelo o esperá a que finalice.")
            run_id = self.repository.create_run(int(config["anio"]), config)
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._worker,
                args=(run_id, dict(config), stop_event),
                daemon=True,
                name=f"boletin-run-{run_id}",
            )
            self._jobs[run_id] = JobRuntime(run_id, stop_event, thread)
            thread.start()
            return run_id

    def stop(self, run_id: int) -> bool:
        with self._lock:
            runtime = self._jobs.get(int(run_id))
            if runtime and runtime.thread.is_alive():
                runtime.stop_event.set()
                self.repository.update_run(
                    int(run_id), status="STOPPING", message="Se solicitó detener el monitoreo."
                )
                return True
        run = self.repository.get_run(int(run_id))
        return bool(run and run.get("status") == "STOPPING")

    def _cleanup_finished_locked(self) -> None:
        finished = [run_id for run_id, runtime in self._jobs.items() if not runtime.thread.is_alive()]
        for run_id in finished:
            self._jobs.pop(run_id, None)

    def _worker(self, run_id: int, config: dict[str, Any], stop_event: threading.Event) -> None:
        stats = {
            "months_scanned": 0,
            "pdfs_seen": 0,
            "pdfs_processed": 0,
            "pdfs_cached": 0,
            "resolutions_seen": 0,
            "relevant_count": 0,
            "new_count": 0,
            "changed_count": 0,
            "unchanged_count": 0,
            "error_count": 0,
            "warning_count": 0,
        }
        status = "COMPLETED"
        session = self._create_session()
        active_alerts = self.repository.list_alerts(active_only=True)
        self.repository.update_run(run_id, status="RUNNING", stats=stats, message="Iniciando monitoreo anual.")

        try:
            for month in range(1, 13):
                if stop_event.is_set():
                    status = "STOPPED"
                    break
                month_url = f"{BOLETIN_BASE_URL}/{int(config['anio'])}/{month:02d}/"
                stats["months_scanned"] = month
                self._progress(run_id, stats, month, (month - 1) / 12 * 100, f"Consultando mes {month:02d}.")
                try:
                    pdfs = self._list_month_pdfs(session, month_url, int(config["anio"]), month)
                except Exception as exc:
                    stats["error_count"] += 1
                    message = f"Mes {month:02d}: no se pudo consultar el archivo mensual: {exc}"
                    self.repository.add_run_error(run_id, month, month_url, message)
                    self._progress(run_id, stats, month, month / 12 * 100, message)
                    continue

                pdfs = [item for item in pdfs if item.get("seccion") == "1"]
                stats["pdfs_seen"] += len(pdfs)
                if not pdfs:
                    self._progress(run_id, stats, month, month / 12 * 100, f"Mes {month:02d}: sin ejemplares de 1.ª Sección.")
                    continue

                for index, pdf in enumerate(pdfs, start=1):
                    if stop_event.is_set():
                        status = "STOPPED"
                        break
                    fractional = index / max(len(pdfs), 1)
                    percentage = ((month - 1) + fractional) / 12 * 100
                    message = f"Mes {month:02d} · PDF {index}/{len(pdfs)} · {pdf['archivo']}"
                    self._progress(run_id, stats, month, percentage, message)
                    try:
                        resolutions, cached, warning = self._analyze_pdf(
                            session,
                            pdf,
                            bool(config.get("revalidar_pdfs") or config.get("procesar_todos")),
                        )
                        stats["pdfs_processed"] += 1
                        if cached:
                            stats["pdfs_cached"] += 1
                        if warning:
                            stats["warning_count"] += 1
                    except Exception as exc:
                        stats["error_count"] += 1
                        error_message = f"Error en {pdf['archivo']}: {exc}"
                        self.repository.add_run_error(run_id, month, pdf.get("url", ""), error_message)
                        self._progress(run_id, stats, month, percentage, error_message)
                        continue

                    stats["resolutions_seen"] += len(resolutions)
                    for resolution in resolutions:
                        text = resolution.get("texto_completo", "")
                        alerts_match = match_alerts(text, active_alerts)
                        term_matches = extract_keywords(text, list(config.get("terminos") or []))

                        if config.get("procesar_todos"):
                            relevant = True
                        else:
                            relevant = bool(config.get("incluir_todas_ersep") or alerts_match)
                            if config.get("terminos") and not term_matches:
                                relevant = False
                        if not relevant:
                            continue

                        stats["relevant_count"] += 1
                        alert_names = [item["nombre"] for item in alerts_match]
                        extraction_terms = [key for item in alerts_match for key in item.get("claves", [])]
                        extraction_terms.extend(term_matches)
                        state_source = resolution.get("texto_resuelve") or text
                        finding = {
                            "year": int(config["anio"]),
                            "month": month,
                            "fecha": pdf.get("fecha", ""),
                            "archivo": pdf.get("archivo", ""),
                            "url": pdf.get("url", ""),
                            "pagina_publicacion": pdf.get("page_url", ""),
                            "numero": resolution.get("numero", ""),
                            "expediente": resolution.get("expediente") or extract_expediente(text),
                            "fecha_emision": resolution.get("fecha_emision") or extract_emission_date(text),
                            "organismo_emisor": resolution.get("organismo_emisor") or extract_issuing_body(text, True),
                            "prestadora": resolution.get("prestadora", ""),
                            "cooperativa": ", ".join(alert_names) or resolution.get("prestadora", ""),
                            "alertas": alert_names,
                            "alertas_detalle": alerts_match,
                            "terminos_encontrados": term_matches,
                            "estado_detectado": detect_state(state_source),
                            "extracto": extract_initial_preview(text),
                            "texto_completo": text,
                            "texto_resuelve": resolution.get("texto_resuelve", ""),
                            "desde_cache": cached,
                            "warning": warning,
                        }
                        stable_key = stable_key_for(finding["year"], finding["numero"])
                        content_hash = content_hash_for(finding)
                        finding = self.repository.register_publication(
                            run_id, finding, stable_key, content_hash
                        )
                        if finding["novedad"] == "NUEVO":
                            stats["new_count"] += 1
                        elif finding["novedad"] == "MODIFICADO":
                            stats["changed_count"] += 1
                        else:
                            stats["unchanged_count"] += 1
                        visible = finding["novedad"] != "SIN CAMBIOS" or bool(
                            config.get("mostrar_sin_cambios") or config.get("procesar_todos")
                        )
                        self.repository.save_run_result(run_id, finding, visible)
                    time.sleep(0.03)

                if status == "STOPPED":
                    break

            if stop_event.is_set():
                status = "STOPPED"
        except Exception as exc:
            status = "ERROR"
            stats["error_count"] += 1
            self.repository.add_run_error(run_id, None, "", f"Error general: {exc}")
        finally:
            message = {
                "COMPLETED": "Monitoreo anual finalizado.",
                "STOPPED": "Monitoreo detenido por el usuario.",
                "ERROR": "El monitoreo finalizó con un error general.",
            }[status]
            self.repository.update_run(
                run_id,
                status=status,
                stats=stats,
                progress_percent=100 if status == "COMPLETED" else None,
                message=message,
                finished=True,
            )
            session.close()

    def _progress(self, run_id: int, stats: dict[str, Any], month: int,
                  percentage: float, message: str) -> None:
        self.repository.update_run(
            run_id,
            stats=stats,
            current_month=month,
            progress_percent=percentage,
            message=message,
        )

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=5, pool_maxsize=5)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "User-Agent": BOLETIN_USER_AGENT,
                "Accept-Language": "es-AR,es;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            }
        )
        return session

    def _list_month_pdfs(self, session: requests.Session, url: str, year: int,
                         month: int) -> list[dict[str, Any]]:
        validate_official_url(url)
        response = session.get(url, timeout=self.timeout, allow_redirects=True)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if ".pdf" not in href.lower():
                continue
            pdf_url = urljoin(url, href)
            try:
                validate_official_url(pdf_url)
            except ValueError:
                continue
            if pdf_url in seen:
                continue
            seen.add(pdf_url)
            filename = Path(urlparse(pdf_url).path).name
            link_text = " ".join(anchor.get_text(" ", strip=True).split())
            section = self._extract_section(filename)
            if not section:
                match = re.match(r"\s*(\d+)[°º]?\s*Secci", link_text, re.IGNORECASE)
                section = match.group(1) if match else ""
            output.append(
                {
                    "url": pdf_url,
                    "archivo": filename,
                    "texto_link": link_text,
                    "fecha": self._extract_date(filename),
                    "seccion": section,
                    "year": year,
                    "month": month,
                    "page_url": url,
                }
            )
        return output

    def _analyze_pdf(self, session: requests.Session, pdf: dict[str, Any],
                     revalidate: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
        cache = self.repository.get_pdf_cache(pdf["url"])
        if cache and not revalidate:
            return cache.get("resolutions", []), True, cache.get("warning", "")

        validate_official_url(pdf["url"])
        response = session.get(
            pdf["url"],
            timeout=max(self.timeout, 75),
            headers={
                "Referer": pdf.get("page_url", BOLETIN_BASE_URL),
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            },
            allow_redirects=True,
        )
        response.raise_for_status()
        validate_official_url(response.url)
        content = response.content
        content_type = response.headers.get("Content-Type", "").lower()
        if not content.startswith(b"%PDF") and "pdf" not in content_type:
            raise ValueError("La respuesta no parece ser un PDF válido.")

        pdf_hash = hashlib.sha256(content).hexdigest()
        if cache and cache.get("pdf_hash") == pdf_hash:
            self.repository.save_pdf_cache(
                pdf, pdf_hash, cache.get("resolutions", []), cache.get("warning", "")
            )
            return cache.get("resolutions", []), True, cache.get("warning", "")

        if not FITZ_AVAILABLE or fitz is None:
            raise RuntimeError("PyMuPDF no está disponible.")
        full_text = self._extract_pdf_text(content)

        warning = ""
        if len(normalize_text(full_text)) < MIN_TEXT_CHARS:
            warning = "PDF posiblemente escaneado o con capa textual insuficiente; revisar manualmente."
        resolutions = split_resolutions(full_text) if contains_ersep(full_text) else []
        self.repository.save_pdf_cache(pdf, pdf_hash, resolutions, warning)
        return resolutions, False, warning

    @staticmethod
    def _extract_pdf_text(content: bytes) -> str:
        if not FITZ_AVAILABLE or fitz is None:
            raise RuntimeError("PyMuPDF no está disponible.")
        document = fitz.open(stream=content, filetype="pdf")
        try:
            return "\n".join(page.get_text("text") for page in document)
        finally:
            document.close()

    @staticmethod
    def _select_resolution(
        resolutions: list[dict[str, Any]], resolution_number: str
    ) -> dict[str, Any] | None:
        target = normalize_text(resolution_number)
        for item in resolutions:
            if normalize_text(item.get("numero")) == target:
                return item
        target_digits = re.findall(r"\d+", target)
        if target_digits:
            for item in resolutions:
                item_digits = re.findall(r"\d+", normalize_text(item.get("numero")))
                if item_digits and item_digits[0] == target_digits[0]:
                    return item
        return None

    @staticmethod
    def _publication_page_url(publication: dict[str, Any]) -> str:
        explicit = str(publication.get("source_page_url") or "").strip()
        if explicit:
            return explicit
        date_match = re.match(
            r"\d{1,2}/(\d{1,2})/(\d{4})", str(publication.get("publication_date") or "")
        )
        if date_match:
            return f"{BOLETIN_BASE_URL}/{int(date_match.group(2)):04d}/{int(date_match.group(1)):02d}/"
        year = publication.get("year")
        return f"{BOLETIN_BASE_URL}/{int(year):04d}/" if year else ""

    def _download_pdf_bytes(
        self, session: requests.Session, url: str, referer: str = ""
    ) -> bytes:
        validate_official_url(url)
        response = session.get(
            url,
            timeout=max(self.timeout, 75),
            headers={
                "Referer": referer or BOLETIN_BASE_URL,
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            },
            allow_redirects=True,
        )
        response.raise_for_status()
        validate_official_url(response.url)
        content = response.content
        if not content.startswith(b"%PDF"):
            raise ValueError("El archivo oficial descargado no parece ser un PDF.")
        return content

    def _discover_linked_annexes(
        self,
        session: requests.Session,
        page_url: str,
        source_url: str,
        resolution_number: str,
    ) -> list[dict[str, Any]]:
        if not page_url:
            return []
        validate_official_url(page_url)
        response = session.get(page_url, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()
        validate_official_url(response.url)
        soup = BeautifulSoup(response.text, "html.parser")
        resolution_digits = re.findall(r"\d+", normalize_text(resolution_number))
        annexes: list[dict[str, Any]] = []
        seen: set[str] = {source_url}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if ".pdf" not in href.casefold():
                continue
            linked_url = urljoin(page_url, href)
            if linked_url in seen:
                continue
            try:
                validate_official_url(linked_url)
            except ValueError:
                continue
            link_text = " ".join(anchor.get_text(" ", strip=True).split())
            filename = Path(urlparse(linked_url).path).name
            descriptor = normalize_text(f"{link_text} {filename}")
            if not any(term in descriptor for term in ("anexo", "adjunto", "cuadro tarifario")):
                continue
            if resolution_digits and re.search(r"\d+", descriptor):
                if resolution_digits[0] not in re.findall(r"\d+", descriptor):
                    continue
            seen.add(linked_url)
            name = link_text or filename or f"Anexo vinculado {len(annexes) + 1}"
            annex: dict[str, Any] = {
                "nombre": name,
                "tipo": "vinculado",
                "url": linked_url,
                "texto": "",
            }
            try:
                annex["texto"] = self._extract_pdf_text(
                    self._download_pdf_bytes(session, linked_url, page_url)
                )
            except Exception as exc:
                annex["advertencia"] = f"No se pudo extraer el texto del anexo: {exc}"
            annexes.append(annex)
            if len(annexes) >= 20:
                break
        return annexes

    def extract_complete_information(self, publication: dict[str, Any]) -> dict[str, Any]:
        """Relee el documento oficial completo y actualiza la resolución sin inventar metadatos."""
        publication_id = int(publication.get("id") or 0)
        source_url = str(publication.get("source_url") or "")
        page_url = self._publication_page_url(publication)
        session = self._create_session()
        warning = ""
        try:
            full_document_text = self._extract_pdf_text(
                self._download_pdf_bytes(session, source_url, page_url)
            )
            resolutions = split_resolutions(full_document_text) if contains_ersep(full_document_text) else []
            selected = self._select_resolution(
                resolutions, str(publication.get("resolution_number") or "")
            )
            if selected:
                resolution_text = str(selected.get("texto_completo") or "")
            else:
                resolution_text = str(publication.get("text_full") or "")
                warning = (
                    "No se pudo volver a aislar automáticamente la resolución dentro del PDF; "
                    "se conservó el último texto identificado."
                )
                selected = {
                    "numero": publication.get("resolution_number") or "",
                    "texto_completo": resolution_text,
                    "texto_resuelve": publication.get("text_resuelve") or "",
                    "expediente": publication.get("expediente_number") or "",
                    "fecha_emision": publication.get("emission_date") or "",
                    "organismo_emisor": publication.get("issuing_body") or "",
                }

            embedded = detect_embedded_annexes(resolution_text, source_url)
            try:
                linked = self._discover_linked_annexes(
                    session,
                    page_url,
                    source_url,
                    str(selected.get("numero") or publication.get("resolution_number") or ""),
                )
            except Exception as exc:
                linked = []
                warning = " ".join(
                    part for part in (warning, f"No se pudieron revisar PDFs vinculados: {exc}") if part
                )
            annexes = embedded + linked
            extracted = {
                "numero_resolucion": selected.get("numero") or publication.get("resolution_number") or "",
                "numero_expediente": selected.get("expediente") or extract_expediente(resolution_text),
                "fecha_emision": selected.get("fecha_emision") or extract_emission_date(resolution_text),
                "fecha_boletin": publication.get("publication_date") or "",
                "enlace_publicacion": source_url,
                "pagina_publicacion": page_url,
                "organismo_emisor": selected.get("organismo_emisor") or extract_issuing_body(full_document_text),
                "terminos_tarifarios": publication.get("regulatory_terms") or [],
                "vista_previa": extract_initial_preview(resolution_text),
                "resolucion_completa": resolution_text,
                "texto_resuelve": selected.get("texto_resuelve") or extract_resuelve(resolution_text),
                "anexos": annexes,
                "texto_anexos": "\n\n".join(
                    str(item.get("texto") or "") for item in annexes if item.get("texto")
                ),
                "advertencia": warning,
            }
            updated = self.repository.update_complete_extraction(publication_id, extracted)
            if not updated:
                raise ValueError("La publicación ya no existe en el historial.")
            updated["informacion_completa"] = {
                "resolucion": extracted["numero_resolucion"] or "No identificado",
                "expediente": extracted["numero_expediente"] or "No identificado",
                "fecha_emision": extracted["fecha_emision"] or "No identificado",
                "fecha_boletin": extracted["fecha_boletin"] or "No identificado",
                "enlace_publicacion": extracted["enlace_publicacion"] or "No identificado",
                "organismo_emisor": extracted["organismo_emisor"] or "No identificado",
                "terminos_tarifarios": extracted["terminos_tarifarios"],
                "anexos": annexes,
                "texto_anexos": extracted["texto_anexos"] or "No identificado",
            }
            return updated
        finally:
            session.close()

    def download_annex_pdf(
        self, publication: dict[str, Any], annex_index: int
    ) -> tuple[bytes, str]:
        annexes = list(publication.get("annexes") or [])
        if annex_index < 0 or annex_index >= len(annexes):
            raise ValueError("Anexo no encontrado.")
        annex = annexes[annex_index]
        url = str(annex.get("url") or publication.get("source_url") or "")
        content, fallback = self.download_official_pdf(url)
        suggested = str(annex.get("nombre") or fallback)
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", suggested).strip("_") or fallback
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        return content, filename

    @staticmethod
    def _extract_date(filename: str) -> str:
        match = re.search(r"_(\d{6})(?:[a-z]*)\.pdf", filename, re.IGNORECASE)
        if not match:
            match = re.search(r"_(\d{6})", filename)
        if not match:
            return ""
        raw = match.group(1)
        return f"{raw[0:2]}/{raw[2:4]}/20{raw[4:6]}"

    @staticmethod
    def _extract_section(filename: str) -> str:
        match = re.search(r"(?:^|/)(\d+)_Secc", filename, re.IGNORECASE)
        return match.group(1) if match else ""

    def download_official_pdf(self, url: str) -> tuple[bytes, str]:
        validate_official_url(url)
        session = self._create_session()
        try:
            content = self._download_pdf_bytes(session, url, BOLETIN_BASE_URL)
            filename = Path(urlparse(url).path).name or "boletin_oficial.pdf"
            filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            return content, filename
        finally:
            session.close()
