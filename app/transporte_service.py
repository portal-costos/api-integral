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
except Exception as exc:  # pragma: no cover
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

# Admite las formas históricas más frecuentes del Boletín: "Resolución N 54",
# "Resolución N.º 54", "Resolución Nº 54" y "Resolución General N° 54".
PAT_RESOLUTION = re.compile(
    r"Resoluci[oó]n(?:\s+General)?\s+N(?:[°º\.]|ro\.?|úmero)?\s*(\d+)"
    r"(?:\s*[-/]\s*(\d{2,4}))?"
    r"(?:\s*[-–]\s*Letra\s*:?\s*[A-Z])?",
    re.IGNORECASE,
)
PAT_TRANSPORT_HEADING = re.compile(
    r"^[ \t]*SECRETAR[IÍ]A[ \t]*(?:\n[ \t]*)?DE[ \t]*(?:\n[ \t]*)?TRANSPORTE[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
PAT_TRANSPORT_MENTION = re.compile(
    r"(?<![A-ZÁÉÍÓÚÑ])SECRETAR[IÍ]A\s+DE\s+TRANSPORTE(?![A-ZÁÉÍÓÚÑ])",
    re.IGNORECASE,
)
PAT_TRANSPORT_AUTHORITY = re.compile(
    r"\bEL\s+SECRETARI[OA]\s+DE\s+TRANSPORTE\b[\s\S]{0,240}?\bRESUELVE\b",
    re.IGNORECASE,
)
PAT_TRANSPORT_SIGNER = re.compile(
    r"\bSECRETARI[OA]\s+DE\s+TRANSPORTE\b",
    re.IGNORECASE,
)
PAT_RESUELVE = re.compile(r"\bR\s*E\s*S\s*U\s*E\s*L\s*V\s*E\s*:?", re.IGNORECASE)
PAT_RESOLUTION_END = re.compile(
    r"(?:^|\n)\s*(?:fdo\.?\s*:|firmado|f\.d\.o\.|"
    r"anexo\s+(?:[ivxlc]+|\d+)|"
    r"resoluci[oó]n(?:\s+general)?\s+n(?:[°º\.]|ro\.?)?\s*\d)",
    re.IGNORECASE,
)

TRANSPORT_TERMS = [
    "transporte de pasajeros",
    "servicio regular",
    "servicio especial",
    "servicio diferencial",
    "permiso",
    "permisionario",
    "concesión",
    "autorización",
    "incorporación",
    "baja de unidad",
    "parque móvil",
    "cuadro tarifario",
    "tarifa",
    "boleto educativo gratuito",
    "licitación",
    "sanción",
    "multa",
    "prórroga",
    "recorrido",
    "corredor",
]


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
    if parsed.scheme != "https" or not (
        host == BOLETIN_ALLOWED_HOST or host.endswith("." + BOLETIN_ALLOWED_HOST)
    ):
        raise ValueError("La URL no pertenece al dominio oficial permitido del Boletín.")
    return url


def contains_transport(text: str) -> bool:
    return bool(PAT_TRANSPORT_MENTION.search(text) or PAT_TRANSPORT_AUTHORITY.search(text))


def is_body_resolution_match(full_text: str, match: re.Match) -> bool:
    after = full_text[match.end(): match.end() + 450]
    # Descarta el sumario, donde luego del número suele aparecer "Pág.".
    if re.search(r"\bP[aá]g\.?", after[:120], re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"C[oó]rdoba|VISTO|Y\s+CONSIDERANDO|En\s+uso|Expediente|Ref\.",
            after,
            re.IGNORECASE,
        )
    )


def is_transport_resolution(full_text: str, start: int, block: str) -> bool:
    # La cabecera institucional suele estar inmediatamente antes de la primera
    # resolución del organismo. Las resoluciones siguientes se validan por la
    # fórmula de autoridad o la firma dentro del propio bloque.
    prefix = full_text[max(0, start - 420):start]
    heading_matches = list(PAT_TRANSPORT_HEADING.finditer(prefix))
    if heading_matches:
        tail = prefix[heading_matches[-1].end():]
        if len(tail) <= 220 and not re.search(r"\bP[aá]g\.?", tail, re.IGNORECASE):
            return True
    if PAT_TRANSPORT_AUTHORITY.search(block):
        return True

    normalized = normalize_text(block)
    # Señal secundaria: firma de la autoridad más vocabulario propio del área.
    if PAT_TRANSPORT_SIGNER.search(block) and any(
        term in normalized
        for term in (
            "transporte de pasajeros",
            "servicio especial",
            "servicio regular",
            "parque movil",
            "permisionario",
            "chapa mop",
            "corredor",
        )
    ):
        return True
    return False


def extract_subject(block: str) -> str:
    compact = re.sub(r"\s+", " ", compact_pdf_text(block)).strip()
    company_suffix = r"(?:S\.?A\.?|S\.?R\.?L\.?|S\.?A\.?S\.?|U\.?T\.?E\.?|Ltda\.?)"
    patterns = [
        rf"(?:empresa|firma|operadora|prestataria|permisionaria)\s+([A-ZÁÉÍÓÚÑ0-9][^.;]{{2,150}}?{company_suffix})",
        rf"(?:a\s+la\s+empresa|a\s+la\s+firma)\s+([A-ZÁÉÍÓÚÑ0-9][^.;]{{2,150}}?{company_suffix})",
        r"(?:al\s+señor|a\s+la\s+señora|al\s+Sr\.|a\s+la\s+Sra\.)\s+([A-ZÁÉÍÓÚÑ][^,.;]{4,110})",
        r"(?:solicitud|presentaci[oó]n)\s+(?:efectuada|formulada|promovida)\s+por\s+([^,.;]{5,140})",
        r"(?:servicio|recorrido|corredor)\s+(?:entre|con\s+centro\s+en)\s+([^.;]{5,140})",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, re.IGNORECASE)
        if match:
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,.-")
            if len(candidate) >= 5:
                return candidate
    return "(destinatario o asunto no identificado)"


def extract_resuelve(resolution_text: str) -> str:
    start_match = PAT_RESUELVE.search(resolution_text)
    if not start_match:
        return ""
    start = start_match.start()
    rest = resolution_text[start:]
    end_match = PAT_RESOLUTION_END.search(rest[12:])
    if end_match:
        return rest[:12 + end_match.start()].strip()
    return rest.strip()


def split_transport_resolutions(full_text: str) -> list[dict[str, Any]]:
    body_matches = [
        match for match in PAT_RESOLUTION.finditer(full_text)
        if is_body_resolution_match(full_text, match)
    ]
    output: list[dict[str, Any]] = []
    for index, match in enumerate(body_matches):
        start = match.start()
        end = body_matches[index + 1].start() if index + 1 < len(body_matches) else len(full_text)
        block = full_text[start:end].strip()
        if not is_transport_resolution(full_text, start, block):
            continue
        output.append(
            {
                "numero": re.sub(r"\s+", " ", match.group(0)).strip(),
                "prestadora": extract_subject(block),
                "texto_completo": block,
                "texto_resuelve": extract_resuelve(block),
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


def detect_state(text: str) -> str:
    normalized = normalize_text(text)
    if re.search(r"\b(rectific(?:ar|ase)|modific(?:ar|ase)|sustituy(?:ese|ase)|corregir)\b", normalized):
        return "MODIFICACIÓN / RECTIFICACIÓN"
    if re.search(r"\b(rechaz(?:ar|ase)|no hacer lugar|desestim(?:ar|ase))\b", normalized):
        return "RECHAZADO / DESESTIMADO"
    if "baja" in normalized and re.search(r"\b(unidad|vehiculo|parque movil|servicio)\b", normalized):
        return "BAJA DE UNIDAD / SERVICIO"
    if "incorpor" in normalized and re.search(r"\b(unidad|vehiculo|parque movil)\b", normalized):
        return "INCORPORACIÓN DE UNIDAD"
    if re.search(r"\b(multa|sancion|inhabilit)\b", normalized):
        return "SANCIÓN / MULTA"
    if re.search(r"\b(licitacion|convocatoria|llamado)\b", normalized):
        return "LICITACIÓN / CONVOCATORIA"
    if re.search(r"\b(cuadro tarifario|tarifa|valor del boleto|precio del pasaje)\b", normalized):
        return "TARIFA / CUADRO TARIFARIO"
    if re.search(r"\b(prorrog(?:ar|ase)|prorroga)\b", normalized):
        return "PRÓRROGA"
    if re.search(r"\b(autoriz(?:ar|ase)|otorg(?:ar|ase)|habilit(?:ar|ase))\b", normalized):
        return "AUTORIZACIÓN / HABILITACIÓN"
    if re.search(r"\b(aprueb(?:a|ase)|establec(?:er|ese))\b", normalized):
        return "APROBADO / ESTABLECIDO"
    return "RESOLUCIÓN DE TRANSPORTE"


def extract_excerpt(text: str, terms: list[str], max_chars: int = 560) -> str:
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
    return sha256_text(f"SECRETARIA_TRANSPORTE|{int(year)}|{normalize_text(resolution_number)}")


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
        "MONITOREO AUTOMÁTICO — RESOLUCIONES DE LA SECRETARÍA DE TRANSPORTE",
        "BOLETÍN OFICIAL DE LA PROVINCIA DE CÓRDOBA",
        f"AÑO ANALIZADO: {year}",
        f"FECHA DE GENERACIÓN: {now_label()}",
        f"NOVEDADES DETECTADAS: {len(news)}",
        "",
        "INSTRUCCIÓN PARA EL MODELO DE LENGUAJE:",
        "Resumí cada resolución sin inventar datos. Identificá el objeto, expediente,",
        "empresa o persona alcanzada, localidad o recorrido, unidades involucradas,",
        "plazos, tarifas, sanciones y decisiones expresamente dispuestas.",
        "",
    ]
    for index, item in enumerate(news, start=1):
        lines.extend(
            [
                "=" * 82,
                f"NOVEDAD {index} DE {len(news)}",
                f"TIPO DE CAMBIO: {item.get('novedad', '')}",
                f"NORMA: {item.get('numero', '')}",
                f"DESTINATARIO / ASUNTO: {item.get('prestadora', '')}",
                f"CLASIFICACIÓN HEURÍSTICA: {item.get('estado_detectado', '')}",
                f"FECHA DE PUBLICACIÓN: {item.get('fecha', '')}",
                f"ARCHIVO: {item.get('archivo', '')}",
                f"URL OFICIAL: {item.get('url', '')}",
                f"TEMAS DETECTADOS: {', '.join(item.get('terminos_encontrados', []))}",
                "",
                "EXTRACTO CLAVE:",
                item.get("extracto", ""),
                "",
                "BLOQUE RESUELVE:",
                item.get("texto_resuelve", "") or "(no detectado)",
                "",
                "TEXTO COMPLETO EXTRAÍDO:",
                item.get("texto_completo", ""),
                "",
            ]
        )
    if not news:
        lines.append("No se detectaron resoluciones nuevas ni modificadas en esta ejecución.")
    return "\n".join(lines)


@dataclass
class JobRuntime:
    run_id: int
    stop_event: threading.Event
    thread: threading.Thread


class TransporteJobManager:
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
                raise RuntimeError("Ya existe una búsqueda en ejecución. Detenela o esperá a que finalice.")
            run_id = self.repository.create_run(int(config["anio"]), config)
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._worker,
                args=(run_id, dict(config), stop_event),
                daemon=True,
                name=f"transporte-run-{run_id}",
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
                    int(run_id), status="STOPPING", message="Se solicitó detener la búsqueda."
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
        self.repository.update_run(
            run_id, status="RUNNING", stats=stats,
            message="Iniciando búsqueda automática anual de resoluciones de Transporte."
        )

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
                    self._progress(
                        run_id, stats, month, month / 12 * 100,
                        f"Mes {month:02d}: sin ejemplares de 1.ª Sección."
                    )
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
                            session, pdf, bool(config.get("revalidar_pdfs"))
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
                        term_matches = extract_keywords(text, TRANSPORT_TERMS)
                        stats["relevant_count"] += 1
                        state_source = resolution.get("texto_resuelve") or text
                        finding = {
                            "year": int(config["anio"]),
                            "month": month,
                            "fecha": pdf.get("fecha", ""),
                            "archivo": pdf.get("archivo", ""),
                            "url": pdf.get("url", ""),
                            "numero": resolution.get("numero", ""),
                            "prestadora": resolution.get("prestadora", ""),
                            "cooperativa": resolution.get("prestadora", ""),
                            "alertas": [],
                            "alertas_detalle": [],
                            "terminos_encontrados": term_matches,
                            "estado_detectado": detect_state(state_source),
                            "extracto": extract_excerpt(state_source, term_matches),
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
                            config.get("mostrar_sin_cambios")
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
                "COMPLETED": "Búsqueda anual finalizada.",
                "STOPPED": "Búsqueda detenida por el usuario.",
                "ERROR": "La búsqueda finalizó con un error general.",
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

    def _progress(
        self, run_id: int, stats: dict[str, Any], month: int,
        percentage: float, message: str
    ) -> None:
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

    def _list_month_pdfs(
        self, session: requests.Session, url: str, year: int, month: int
    ) -> list[dict[str, Any]]:
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

    def _analyze_pdf(
        self, session: requests.Session, pdf: dict[str, Any], revalidate: bool = False
    ) -> tuple[list[dict[str, Any]], bool, str]:
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
        document = fitz.open(stream=content, filetype="pdf")
        try:
            full_text = "\n".join(page.get_text("text") for page in document)
        finally:
            document.close()

        warning = ""
        if len(normalize_text(full_text)) < MIN_TEXT_CHARS:
            warning = "PDF posiblemente escaneado o con capa textual insuficiente; revisar manualmente."
        resolutions = split_transport_resolutions(full_text) if contains_transport(full_text) else []
        self.repository.save_pdf_cache(pdf, pdf_hash, resolutions, warning)
        return resolutions, False, warning

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
            response = session.get(url, timeout=max(self.timeout, 75), allow_redirects=True)
            response.raise_for_status()
            content = response.content
            if not content.startswith(b"%PDF"):
                raise ValueError("El archivo oficial descargado no parece ser un PDF.")
            filename = Path(urlparse(url).path).name or "boletin_oficial.pdf"
            filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            return content, filename
        finally:
            session.close()
