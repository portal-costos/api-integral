# -*- coding: utf-8 -*-
import io
import os
import calendar
import re
import time
import json
import hmac
import hashlib
import threading
import traceback
import unicodedata
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse
from datetime import date, datetime, timedelta, timezone

import jwt
import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from gspread.utils import DateTimeOption, ValueRenderOption, rowcol_to_a1
from google.oauth2.service_account import Credentials
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response
import gspread
from dotenv import load_dotenv

# Configuración local: .env.local tiene prioridad y no debe subirse al repositorio.
LOCAL_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(LOCAL_BASE_DIR / ".env.local", override=True)
load_dotenv(LOCAL_BASE_DIR / ".env", override=False)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================================================
# Configuración
# =========================================================
FILE_ID = os.getenv("GSHEET_ID", "1gF9d5ZBT1Rwa5yq9jJxiXgjwXke5jEAlCM-Qd99XDog").strip()
GSHEET_GID = os.getenv("GSHEET_GID", "883561078").strip()
GSHEET_PUBLIC_URL = f"https://docs.google.com/spreadsheets/d/{FILE_ID}/edit?gid={GSHEET_GID}#gid={GSHEET_GID}"
GSHEET_WORKSHEET_NAME = os.getenv("GSHEET_WORKSHEET_NAME", "Series originales").strip()
GOOGLE_CREDENTIALS_JSON_ENV = "GOOGLE_CREDENTIALS_JSON"

HEADER_ROW_1BASED = int(os.getenv("HEADER_ROW_1BASED", "1"))
HEADER_ROW = HEADER_ROW_1BASED - 1
CACHE_TTL = int(os.getenv("CACHE_TTL", "600"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7
RELOAD_TOKEN = os.getenv("RELOAD_TOKEN", "").strip()
HTTP_TIMEOUT = int(os.getenv("SCRAPER_HTTP_TIMEOUT", "35"))
UPDATE_MONTHS = max(1, int(os.getenv("UPDATE_MONTHS", "6")))
UPDATE_INCLUDE_CURRENT_MONTH = os.getenv("UPDATE_INCLUDE_CURRENT_MONTH", "false").strip().lower() in {"1", "true", "yes", "si", "sí"}
PUBLIC_READ_ONLY = os.getenv("PUBLIC_READ_ONLY", "true").strip().lower() not in {"0", "false", "no"}
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "https://portal-costos.github.io").split(",") if x.strip()]
BCRA_MONETARIAS_API_BASE = os.getenv(
    "BCRA_MONETARIAS_API_BASE",
    "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias",
).rstrip("/")
BCRA_B9791_VARIABLE_ID = int(os.getenv("BCRA_B9791_VARIABLE_ID", "4"))
# Variables oficiales de Estadísticas Monetarias v4.0 del BCRA.
# Las URLs históricas de Principales Variables continúan siendo referencias
# documentales, pero la API v4.0 es la fuente estructurada vigente.
BCRA_CER_VARIABLE_ID = int(os.getenv("BCRA_CER_VARIABLE_ID", "30"))
BCRA_ICL_VARIABLE_ID = int(os.getenv("BCRA_ICL_VARIABLE_ID", "40"))
BCRA_BADLAR_NA_VARIABLE_ID = int(os.getenv("BCRA_BADLAR_NA_VARIABLE_ID", "7"))
BCRA_BADLAR_EA_VARIABLE_ID = int(os.getenv("BCRA_BADLAR_EA_VARIABLE_ID", "35"))

# Fuente oficial del Índice del Costo de la Construcción de Córdoba.
ICC_CBA_DATASET_URL = os.getenv(
    "ICC_CBA_DATASET_URL",
    "https://datosestadistica.cba.gov.ar/dataset/indice-de-costo-de-la-construccion",
).strip()
ICC_CBA_RESOURCE_ID = os.getenv(
    "ICC_CBA_RESOURCE_ID",
    "853d79e8-5a61-42d7-ad6c-cedc5140c513",
).strip()
ICC_CBA_RESOURCE_PAGE = os.getenv(
    "ICC_CBA_RESOURCE_PAGE",
    f"{ICC_CBA_DATASET_URL}/resource/{ICC_CBA_RESOURCE_ID}",
).strip()
ICC_CBA_FALLBACK_XLSX_URL = os.getenv(
    "ICC_CBA_FALLBACK_XLSX_URL",
    (
        "https://datosestadistica.cba.gov.ar/dataset/"
        "14329433-faaf-48fb-90a0-3c141288622d/resource/"
        "853d79e8-5a61-42d7-ad6c-cedc5140c513/download/"
        "icc-cba-indice-general-y-rubros-valor-m2.xlsx"
    ),
).strip()

# Histórico de cotizaciones del Banco Nación.
BNA_HISTORICO_URL = os.getenv(
    "BNA_HISTORICO_URL",
    "https://www.bna.com.ar/Cotizador/HistoricoPrincipales?id=billetes&filtroEuro=0&filtroDolar=0",
).strip()
BNA_DESCARGA_URL = os.getenv(
    "BNA_DESCARGA_URL",
    "https://www.bna.com.ar/Cotizador/DescargarPorFecha",
).strip()

# JUS Córdoba, IPC de Estados Unidos, IPC San Luis e Índice de Obra Pública.
JUS_CORDOBA_URL = os.getenv(
    "JUS_CORDOBA_URL",
    "https://www.justiciacordoba.gob.ar/justiciacordoba/Servicios/JUSyUnidadEconomica/1",
).strip()
BLS_API_URL = os.getenv(
    "BLS_API_URL",
    "https://api.bls.gov/publicAPI/v2/timeseries/data/",
).strip()
BLS_CPI_US_SERIES_ID = os.getenv("BLS_CPI_US_SERIES_ID", "CUUR0000SA0").strip()
BLS_CPI_US_FLAT_FILE = os.getenv(
    "BLS_CPI_US_FLAT_FILE",
    "https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems",
).strip()
IPC_SAN_LUIS_URL = os.getenv(
    "IPC_SAN_LUIS_URL",
    "https://estadistica.sanluis.gov.ar/Categorias/economia/precios/ipc-sanluis",
).strip()
IOP_CBA_DATASET_URL = os.getenv(
    "IOP_CBA_DATASET_URL",
    "https://datosestadistica.cba.gov.ar/dataset/indice-de-obra-publica",
).strip()
IOP_CBA_RESOURCE_ID = os.getenv(
    "IOP_CBA_RESOURCE_ID",
    "718f796e-8460-4af1-8055-8c8194225018",
).strip()
IOP_CBA_RESOURCE_PAGE = os.getenv(
    "IOP_CBA_RESOURCE_PAGE",
    f"{IOP_CBA_DATASET_URL}/resource/{IOP_CBA_RESOURCE_ID}",
).strip()
IOP_CBA_FALLBACK_XLSX_URL = os.getenv(
    "IOP_CBA_FALLBACK_XLSX_URL",
    (
        "https://datosestadistica.cba.gov.ar/dataset/"
        "67139136-17a8-4d6f-8f8e-06ae5b969f45/resource/"
        "718f796e-8460-4af1-8055-8c8194225018/download/iop_mayo.xlsx"
    ),
).strip()


# Valor de la Gestión del Agua (VGA) y Coeficiente de Variación de Costos RAC.
VGA_CBA_DATASET_URL = os.getenv(
    "VGA_CBA_DATASET_URL",
    "https://datosestadistica.cba.gov.ar/dataset/valor-de-la-gestion-del-agua-vga",
).strip()
VGA_CBA_PACKAGE_ID = os.getenv(
    "VGA_CBA_PACKAGE_ID",
    "ef865ef3-80b0-4836-a6d8-201f84558b88",
).strip()

CVC_RAC_DATASET_URL = os.getenv(
    "CVC_RAC_DATASET_URL",
    "https://datosestadistica.cba.gov.ar/dataset/coeficiente-de-variacion-de-costos-cvc",
).strip()
CVC_RAC_XLSX_RESOURCE_ID = os.getenv(
    "CVC_RAC_XLSX_RESOURCE_ID",
    "eef2e553-bf2b-4e8e-84f7-2cb7f3caa6ad",
).strip()
CVC_RAC_CSV_RESOURCE_ID = os.getenv(
    "CVC_RAC_CSV_RESOURCE_ID",
    "abd61230-930d-4101-9ab0-98c298d1cf29",
).strip()
CVC_RAC_FALLBACK_XLSX_URL = os.getenv(
    "CVC_RAC_FALLBACK_XLSX_URL",
    (
        "https://datosestadistica.cba.gov.ar/dataset/"
        "d64afde3-bc2f-4220-b2f8-5b498a968b95/resource/"
        "eef2e553-bf2b-4e8e-84f7-2cb7f3caa6ad/download/"
        "202605_cvc_cuadro-publicacion_mayo.xlsx"
    ),
).strip()
CVC_RAC_FALLBACK_CSV_URL = os.getenv(
    "CVC_RAC_FALLBACK_CSV_URL",
    (
        "https://datosestadistica.cba.gov.ar/dataset/"
        "d64afde3-bc2f-4220-b2f8-5b498a968b95/resource/"
        "abd61230-930d-4101-9ab0-98c298d1cf29/download/"
        "202605_cvc_cuadro-publicacion_mayo.csv"
    ),
).strip()

# Fórmula de Actualización Mensual (FAM) de EPEC.
# El recurso XLSX/CSV se actualiza en CKAN; se descubre dinámicamente por package_show.
FAM_EPEC_DATASET_URL = os.getenv(
    "FAM_EPEC_DATASET_URL",
    "https://datosestadistica.cba.gov.ar/dataset/formula-de-actualizacion-mensual-fam-epec",
).strip()
FAM_EPEC_PACKAGE_ID = os.getenv(
    "FAM_EPEC_PACKAGE_ID",
    "b94ef3fe-496b-4b3d-b7cb-558f2f95a089",
).strip()
FAM_EPEC_XLSX_RESOURCE_ID = os.getenv(
    "FAM_EPEC_XLSX_RESOURCE_ID",
    "bc587480-8bd6-4d71-979b-7ce3b863d807",
).strip()
FAM_EPEC_CSV_RESOURCE_ID = os.getenv(
    "FAM_EPEC_CSV_RESOURCE_ID",
    "04fe37ad-9bc2-4725-94f0-785ee1cbd2dc",
).strip()

if not APP_PASSWORD:
    raise RuntimeError("Variable APP_PASSWORD no configurada.")
if not JWT_SECRET:
    raise RuntimeError("Variable JWT_SECRET no configurada.")

# =========================================================
# App + static
# =========================================================
app = FastAPI(title="API - Base propia")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
security = HTTPBearer(auto_error=False)


def _create_token() -> str:
    payload = {
        "sub": "cyt-user",
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _verify_token(token: str) -> bool:
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return True
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return False


def require_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials or not _verify_token(credentials.credentials):
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")
    return True


def require_stats_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Permite consultas estadísticas públicas cuando PUBLIC_READ_ONLY=true.

    El resto de la API continúa usando require_auth.
    """
    if PUBLIC_READ_ONLY:
        return True
    return require_auth(credentials)


@app.post("/api/login")
def login(body: dict):
    password = str(body.get("password", "")).strip()
    pwd_ok = hmac.compare_digest(
        hashlib.sha256(password.encode()).digest(),
        hashlib.sha256(APP_PASSWORD.encode()).digest(),
    )
    time.sleep(0.3)
    if not pwd_ok:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta.")
    return {"token": _create_token(), "expires_days": JWT_EXPIRE_DAYS}


@app.api_route("/", methods=["GET", "HEAD"])
def home(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.on_event("startup")
async def startup():
    try:
        _load_df()
    except Exception as e:
        print(f"[WARN] Pre-carga fallida: {e}")


# =========================================================
# Cache y carga para la WebApp
# =========================================================
_DF_CACHE: Optional[pd.DataFrame] = None
_CACHE_TS: float = 0.0
_CACHE_LOCK = threading.Lock()


def _invalidate_cache() -> None:
    global _DF_CACHE, _CACHE_TS
    with _CACHE_LOCK:
        _DF_CACHE = None
        _CACHE_TS = 0.0


def _make_unique_headers(headers: List[Any]) -> List[str]:
    """Normaliza encabezados y evita nombres duplicados en el DataFrame."""
    used: Dict[str, int] = {}
    result: List[str] = []
    for idx, value in enumerate(headers):
        base = str(value).strip() if value is not None else ""
        if not base:
            base = f"Col_{idx}"
        count = used.get(base, 0)
        used[base] = count + 1
        result.append(base if count == 0 else f"{base}__{count + 1}")
    return result


def _worksheet_to_dataframe(ws: gspread.Worksheet) -> pd.DataFrame:
    """Lee la hoja privada usando la cuenta de servicio, sin URLs públicas ni Excel intermedio."""
    values = ws.get_all_values(
        value_render_option=ValueRenderOption.unformatted,
        date_time_render_option=DateTimeOption.formatted_string,
        pad_values=True,
    )
    if not values or len(values) <= HEADER_ROW:
        raise RuntimeError(
            f"La pestaña '{ws.title}' no contiene la fila de encabezados configurada "
            f"(HEADER_ROW_1BASED={HEADER_ROW_1BASED})."
        )

    raw_headers = list(values[HEADER_ROW])
    non_empty = [i for i, value in enumerate(raw_headers) if str(value).strip()]
    if not non_empty:
        raise RuntimeError(f"La pestaña '{ws.title}' no tiene encabezados válidos.")

    last_col = max(non_empty) + 1
    headers = _make_unique_headers(raw_headers[:last_col])
    rows: List[List[Any]] = []
    for raw_row in values[HEADER_ROW + 1:]:
        row = list(raw_row[:last_col])
        if len(row) < last_col:
            row.extend([None] * (last_col - len(row)))
        if any(value not in (None, "") for value in row):
            rows.append(row)

    df = pd.DataFrame(rows, columns=headers)
    if df.empty:
        raise RuntimeError(f"La pestaña '{ws.title}' no contiene filas de datos.")
    return df


def _load_df(force: bool = False) -> pd.DataFrame:
    global _DF_CACHE, _CACHE_TS
    now = time.time()
    if not force and _DF_CACHE is not None and (now - _CACHE_TS < CACHE_TTL):
        return _DF_CACHE

    with _CACHE_LOCK:
        now = time.time()
        if not force and _DF_CACHE is not None and (now - _CACHE_TS < CACHE_TTL):
            return _DF_CACHE
        try:
            ws = _get_worksheet()
            df0 = _worksheet_to_dataframe(ws)
            df = df0.dropna(how="all").copy()
            df["__date_key__"] = _coerce_month_dates(df.iloc[:, 0]).dt.strftime("%Y-%m-%d")
            if df["__date_key__"].notna().sum() == 0:
                raise RuntimeError(
                    "La primera columna no contiene fechas reconocibles. "
                    "Revisá la pestaña y HEADER_ROW_1BASED."
                )
            _DF_CACHE = df
            _CACHE_TS = now
            return df
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "No se pudo leer la base privada de Google Sheets con la cuenta de servicio. "
                    f"Documento={FILE_ID}; pestaña={GSHEET_WORKSHEET_NAME}; detalle={exc}"
                ),
            ) from exc


def _to_tsv(df: pd.DataFrame) -> str:
    out = io.StringIO()
    df.to_csv(out, sep="\t", index=False, lineterminator="\r\n")
    return out.getvalue()


def _coerce_month_dates(values: pd.Series) -> pd.Series:
    """Interpreta la primera columna como períodos mensuales argentinos.

    Corrige también el patrón generado por una hoja con localidad incompatible:
    ``2001-01-02`` representa febrero, ``2001-01-03`` marzo, etc. En ese
    patrón el mes quedó fijado en enero y el número de mes terminó en el día.
    """
    series = values if isinstance(values, pd.Series) else pd.Series(values)
    raw = series.astype("string").str.strip()

    # Detectar el patrón ANTES de normalizar al primer día del mes, porque
    # _parse_sheet_date descarta deliberadamente el día.
    iso_parts = raw.str.extract(r"^(?P<year>\d{4})-01-(?P<day>\d{2})(?:[ T].*)?$")
    candidate_days = pd.to_numeric(iso_parts["day"], errors="coerce")
    candidate_mask = candidate_days.between(1, 12)
    valid_raw = raw.notna() & raw.ne("")
    candidate_ratio = float(candidate_mask.sum() / max(int(valid_raw.sum()), 1))
    distinct_candidate_days = set(candidate_days[candidate_mask].dropna().astype(int).tolist())
    malformed_month_pattern = candidate_ratio >= 0.90 and len(distinct_candidate_days) >= 6

    parsed_values = []
    for idx, value in series.items():
        if malformed_month_pattern and bool(candidate_mask.loc[idx]):
            year = int(iso_parts.loc[idx, "year"])
            month = int(candidate_days.loc[idx])
            parsed_values.append(date(year, month, 1))
        else:
            parsed_values.append(_parse_sheet_date(value))

    parsed = pd.Series(pd.to_datetime(parsed_values, errors="coerce"), index=series.index)
    return parsed.dt.to_period("M").dt.to_timestamp()


def _build_date_index(df: pd.DataFrame) -> pd.Series:
    if "__date_key__" in df.columns:
        return df["__date_key__"].astype("string")
    return _coerce_month_dates(df.iloc[:, 0]).dt.strftime("%Y-%m-%d")


# =========================================================
# Scraping migrado desde NO BORRAR POR NADA DE NADA.pyw
# =========================================================
MAPA_NUM_MESES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}

MAPA_MESES_NUMS_CORTO = {
    "Ene": "1", "Feb": "2", "Mar": "3", "Abr": "4",
    "May": "5", "Jun": "6", "Jul": "7", "Ago": "8",
    "Set": "9", "Sep": "9", "Oct": "10", "Nov": "11", "Dic": "12",
}

MAPA_MESES_NUMS_LARGO = {
    "Enero": "1", "Febrero": "2", "Marzo": "3", "Abril": "4",
    "Mayo": "5", "Junio": "6", "Julio": "7", "Agosto": "8",
    "Septiembre": "9", "Setiembre": "9", "Octubre": "10",
    "Noviembre": "11", "Diciembre": "12",
}


def normalizar_texto(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    texto = texto.replace(".", "")
    return texto.strip()


def _parse_number_locale(value: Any) -> Optional[float]:
    """Convierte números reales o textos con formato argentino/internacional sin alterar decimales válidos."""
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None

    if "," in text and "." in text:
        # El último separador se interpreta como decimal; el otro, como miles.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(text)
    except ValueError:
        return None


def _normalizar_numero_argentino(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie.apply(_parse_number_locale), errors="coerce")


def _month_start(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    ts = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return None
    return date(int(ts.year), int(ts.month), 1)


def _format_sheet_date(d: date) -> str:
    return f"1/{d.month}/{d.year}"


def _parse_sheet_date(value: Any) -> Optional[date]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return date(value.year, value.month, 1)

    # Con UNFORMATTED_VALUE Google Sheets puede devolver fechas como números
    # de serie. El origen 1899-12-30 coincide con Excel/Google Sheets.
    if isinstance(value, (int, float)) and pd.notna(value):
        serial = float(value)
        if 20000 <= serial <= 80000:
            dt = datetime(1899, 12, 30) + timedelta(days=serial)
            return date(dt.year, dt.month, 1)

    texto = str(value).strip()
    if not texto:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", texto):
        serial = float(texto)
        if 20000 <= serial <= 80000:
            dt = datetime(1899, 12, 30) + timedelta(days=serial)
            return date(dt.year, dt.month, 1)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            dt = datetime.strptime(texto.split(" ")[0], fmt)
            return date(dt.year, dt.month, 1)
        except ValueError:
            pass
    parsed = pd.to_datetime(texto, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return date(int(parsed.year), int(parsed.month), 1)


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def _meses_objetivo_actualizacion(reference_date: Optional[date] = None) -> List[date]:
    """Devuelve meses cerrados por defecto; evita tratar el mes en curso como dato mensual definitivo."""
    hoy = reference_date or datetime.now().date()
    current_month = date(hoy.year, hoy.month, 1)
    end_month = current_month if UPDATE_INCLUDE_CURRENT_MONTH else _add_months(current_month, -1)
    return [_add_months(end_month, i) for i in range(-(UPDATE_MONTHS - 1), 1)]


def _ultimos_6_meses_calendario() -> List[date]:
    # Alias conservado para compatibilidad con código anterior y pruebas externas.
    return _meses_objetivo_actualizacion()


def _value_or_none(value: Any) -> Optional[float]:
    return _parse_number_locale(value)


# IPC Nacional INDEC
URL_IPC_NACIONAL = "https://www.indec.gob.ar/ftp/cuadros/economia/serie_ipc_divisiones.csv"
CODIGOS_IPCN_OBJETIVO = ["0", "B", "S", "Estacional", "Núcleo", "Regulados"]
REEMPLAZO_CODIGOS_IPCN = {"0": "Nivel General", "B": "Bienes", "S": "Servicios"}
ORDEN_CODIGOS_IPCN = ["Nivel General", "Estacional", "Núcleo", "Regulados", "Bienes", "Servicios"]


def obtener_datos_ipcn() -> pd.DataFrame:
    response = requests.get(URL_IPC_NACIONAL, timeout=HTTP_TIMEOUT, verify=False)
    response.raise_for_status()
    df = pd.read_csv(BytesIO(response.content), sep=";", encoding="latin1")
    df.columns = df.columns.astype(str).str.strip()
    if "Region" in df.columns:
        df = df[df["Region"] == "Nacional"].copy()
    df["Codigo"] = df["Codigo"].astype(str).str.strip()
    df = df[df["Codigo"].isin(CODIGOS_IPCN_OBJETIVO)].copy()
    df["Codigo"] = df["Codigo"].replace(REEMPLAZO_CODIGOS_IPCN)
    df["Periodo"] = pd.to_numeric(df["Periodo"], errors="coerce")
    df = df.dropna(subset=["Periodo"]).copy()
    df["Periodo"] = df["Periodo"].astype(int)
    df["Fecha"] = pd.to_datetime(df["Periodo"].astype(str) + "01", format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["Fecha"]).copy()
    df["Mes"] = df["Fecha"].dt.month.map(MAPA_NUM_MESES)
    df["Mes-Año"] = df["Mes"] + "-" + df["Fecha"].dt.year.astype(str)
    df["Indice_IPC"] = (
        df["Indice_IPC"].astype(str).str.strip()
        .str.replace("\u00a0", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    df["Indice_IPC"] = pd.to_numeric(df["Indice_IPC"], errors="coerce")
    df = df[["Fecha", "Mes-Año", "Codigo", "Indice_IPC"]].copy()
    df["Orden"] = pd.Categorical(df["Codigo"], categories=ORDEN_CODIGOS_IPCN, ordered=True)
    return df.sort_values(["Fecha", "Orden"]).drop(columns=["Orden"], errors="ignore").reset_index(drop=True)


# IPC Córdoba
URL_RECURSO_IPC_CBA = "https://datosestadistica.cba.gov.ar/dataset/indic/resource/2b4a7c60-1c8a-45b1-be8f-2bd59bfe2364"
URL_BASE_CBA = "https://datosestadistica.cba.gov.ar"
DATASET_ID_REAL = "fedc5285-5517-41aa-9095-bb62c6dbc485"
RESOURCE_ID_IPC_CBA = "2b4a7c60-1c8a-45b1-be8f-2bd59bfe2364"
HEADERS_CBA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def _buscar_hoja(excel, posibles_nombres):
    hojas_norm = {normalizar_texto(n): n for n in excel.sheet_names}
    for posible in posibles_nombres:
        p_norm = normalizar_texto(posible)
        # Prioriza coincidencia exacta. Es importante para el IPC Córdoba,
        # porque el XLSX oficial contiene a la vez "IPC-Cba COICOP" y
        # "IPC-Cba COICOP var mensual".
        if p_norm in hojas_norm:
            return hojas_norm[p_norm]
    for posible in posibles_nombres:
        p_norm = normalizar_texto(posible)
        for h_norm, h_real in hojas_norm.items():
            if p_norm in h_norm:
                return h_real
    raise ValueError(f"No se encontró hoja compatible con: {posibles_nombres}")


def _detectar_fila_encabezado(df_raw, palabras):
    palabras_norm = [normalizar_texto(p) for p in palabras]
    for idx, row in df_raw.iterrows():
        texto_fila = " ".join(normalizar_texto(v) for v in row.tolist())
        if all(p in texto_fila for p in palabras_norm):
            return idx
    raise ValueError(f"No se pudo detectar fila de encabezado con: {palabras}")


def _a_largo_indice_cba(df, columna_codigo, columna_descripcion, fuente):
    """Convierte una tabla horizontal del IPC Córdoba a índice mensual largo."""
    columnas_fecha = [c for c in df.columns if pd.notna(pd.to_datetime(c, errors="coerce"))]
    base = [columna_descripcion]
    if columna_codigo and columna_codigo in df.columns:
        base.insert(0, columna_codigo)
    df = df[base + columnas_fecha].copy()
    df = df.dropna(subset=[columna_descripcion], how="all")
    largo = df.melt(
        id_vars=base,
        value_vars=columnas_fecha,
        var_name="Fecha",
        value_name="Indice",
    )
    largo["Fecha"] = pd.to_datetime(largo["Fecha"], errors="coerce")
    largo["Indice"] = _normalizar_numero_argentino(largo["Indice"])
    largo["Codigo"] = largo[columna_codigo].astype(str) if columna_codigo else ""
    largo["Descripcion"] = largo[columna_descripcion].astype(str)
    largo["Fuente"] = fuente
    return largo[["Fuente", "Codigo", "Descripcion", "Fecha", "Indice"]].dropna(
        subset=["Fecha", "Indice"]
    )


def _leer_coicop_indice(excel):
    # Nueva base: se toma el número índice de la hoja principal, no la hoja
    # de variaciones mensuales.
    hoja = _buscar_hoja(excel, ["IPC-Cba COICOP"])
    df_raw = pd.read_excel(excel, sheet_name=hoja, header=None)
    fila = _detectar_fila_encabezado(df_raw, ["Código", "Descripción"])
    df = pd.read_excel(excel, sheet_name=hoja, header=fila)
    df.columns = [str(c).strip() for c in df.columns]
    return _a_largo_indice_cba(df, "Código", "Descripción", "coicop")


def _leer_empalme_indice(excel):
    hoja = _buscar_hoja(excel, ["IPC Empalme desde 1968"])
    df_raw = pd.read_excel(excel, sheet_name=hoja, header=None)
    fila = _detectar_fila_encabezado(df_raw, ["Período", "Indice"])
    df = pd.read_excel(excel, sheet_name=hoja, header=fila)
    df.columns = [str(c).strip() for c in df.columns]
    col_per = next((c for c in df.columns if "periodo" in normalizar_texto(c)), None)
    col_indice = next(
        (
            c
            for c in df.columns
            if "indice" in normalizar_texto(c)
            and "variacion" not in normalizar_texto(c)
        ),
        None,
    )
    if not col_per or not col_indice:
        raise ValueError("No se detectaron columnas período/número índice en empalme.")
    out = df[[col_per, col_indice]].rename(
        columns={col_per: "Fecha", col_indice: "Indice"}
    ).copy()
    out["Fecha"] = pd.to_datetime(out["Fecha"], errors="coerce")
    out["Indice"] = _normalizar_numero_argentino(out["Indice"])
    out = out.dropna(subset=["Fecha", "Indice"])
    out["Fuente"] = "empalme"
    out["Codigo"] = ""
    out["Descripcion"] = "Nivel General"
    return out[["Fuente", "Codigo", "Descripcion", "Fecha", "Indice"]]


def _leer_bloque_indice_cba(excel, posibles_hojas, fuente):
    """Lee el primer bloque de números índice de las hojas de aperturas."""
    hoja = _buscar_hoja(excel, posibles_hojas)
    df_raw = pd.read_excel(excel, sheet_name=hoja, header=None)
    fila_indice = next(
        (
            idx
            for idx, row in df_raw.iterrows()
            if any(normalizar_texto(v) == "indice" for v in row.tolist())
            and any(normalizar_texto(v) == "mes" for v in row.tolist())
        ),
        None,
    )
    if fila_indice is None:
        raise ValueError(f"No se encontró bloque de número índice en hoja '{hoja}'.")

    fila_subtit = fila_indice + 1
    col_mes = next(
        (c for c in df_raw.columns if normalizar_texto(df_raw.iloc[fila_indice, c]) == "mes"),
        0,
    )
    col_inicio = next(
        (c for c in df_raw.columns if normalizar_texto(df_raw.iloc[fila_indice, c]) == "indice"),
        None,
    )
    if col_inicio is None:
        raise ValueError(f"No se detectó columna inicial del número índice en '{hoja}'.")
    col_fin = next(
        (
            c for c in range(col_inicio + 1, len(df_raw.columns))
            if normalizar_texto(df_raw.iloc[fila_indice, c]).startswith("variacion")
        ),
        len(df_raw.columns),
    )

    registros = []
    for fila in range(fila_subtit + 1, len(df_raw)):
        fecha = pd.to_datetime(df_raw.iloc[fila, col_mes], errors="coerce")
        if pd.isna(fecha):
            continue
        for col in range(col_inicio, col_fin):
            descripcion = df_raw.iloc[fila_subtit, col]
            if pd.isna(descripcion):
                continue
            valor = _value_or_none(df_raw.iloc[fila, col])
            if pd.isna(valor):
                continue
            registros.append({
                "Fuente": fuente,
                "Codigo": "",
                "Descripcion": str(descripcion).strip(),
                "Fecha": fecha,
                "Indice": float(valor),
            })
    return pd.DataFrame(registros)


def obtener_datos_ipccba_largo(fecha_desde=None) -> pd.DataFrame:
    """
    Obtiene los números índice oficiales del IPC Córdoba en la nueva base.

    A diferencia de la implementación anterior, no devuelve variaciones para
    encadenarlas en Google Sheets: devuelve el índice publicado directamente.
    """
    resp = requests.get(URL_RECURSO_IPC_CBA, headers=HEADERS_CBA, timeout=HTTP_TIMEOUT, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    links = sorted({urljoin(URL_BASE_CBA, a["href"].strip()) for a in soup.find_all("a", href=True)})
    prefijo = f"{URL_BASE_CBA}/dataset/{DATASET_ID_REAL}/resource/{RESOURCE_ID_IPC_CBA}/download/"
    links_xlsx = [l for l in links if l.startswith(prefijo) and l.lower().endswith(".xlsx")]
    if not links_xlsx:
        raise ValueError("No se encontró el link XLSX del IPC-CBA.")
    resp2 = requests.get(links_xlsx[0], headers=HEADERS_CBA, timeout=HTTP_TIMEOUT, verify=False)
    resp2.raise_for_status()
    archivo = BytesIO(resp2.content)
    excel = pd.ExcelFile(archivo)
    tablas = []
    lectores = [
        (_leer_empalme_indice, (excel,)),
        (_leer_bloque_indice_cba, (excel, ["Estac, Regulados y Núcleo", "IPC-Cba. Est. y Reg."], "estac_regulados")),
        (_leer_bloque_indice_cba, (excel, ["Bienes y Servicios", "IPC-Cba. Bs y Ss."], "bienes_servicios")),
        (_leer_coicop_indice, (excel,)),
    ]
    for lector, args in lectores:
        try:
            archivo.seek(0)
            tablas.append(lector(*args))
        except Exception as e:
            print(f"[WARN] IPC-CBA {lector.__name__}: {e}")
    if not tablas:
        raise ValueError("No se pudo leer ninguna tabla del IPC-CBA.")
    largo = pd.concat(tablas, ignore_index=True)
    largo["Fecha"] = pd.to_datetime(largo["Fecha"], errors="coerce")
    if fecha_desde:
        largo = largo[largo["Fecha"] >= pd.Timestamp(fecha_desde)].copy()
    largo["Codigo"] = largo["Codigo"].astype(str).str.strip()
    largo["Descripcion"] = largo["Descripcion"].astype(str).str.strip()
    largo["_codigo_norm"] = largo["Codigo"].apply(normalizar_texto)
    largo["_desc_norm"] = largo["Descripcion"].apply(normalizar_texto)
    return largo.dropna(subset=["Fecha", "Indice"]).reset_index(drop=True)


# ICC Córdoba: índice general, rubros y medias móviles interanuales.
ICC_CBA_TARGET_HEADERS = {
    "Nivel_General": "ICC Córdoba Nivel General Base 1986 = 100",
    "Materiales": "ICC Córdoba Materiales Base 1986 = 100",
    "Mano_de_Obra": "ICC Córdoba Mano de Obra Base 1986 = 100",
    "Varios": "ICC Córdoba Varios Base 1986 = 100",
}
ICC_CBA_MOVING_HEADERS = {
    "Nivel_General": "ICC Córdoba Nivel General Media Móvil interanual Base 1986 = 100",
    "Materiales": "ICC Córdoba Materiales Media Móvil interanual Base 1986 = 100",
    "Mano_de_Obra": "ICC Córdoba Mano de Obra Media Móvil interanual Base 1986 = 100",
    "Varios": "ICC Córdoba Varios Media Móvil interanual Base 1986 = 100",
}
ICC_CBA_MOVING_WINDOW = 13


def _is_allowed_cba_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url))
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname == "datosestadistica.cba.gov.ar"


def _discover_icc_cba_xlsx_url() -> str:
    """Resuelve el XLSX actual aun cuando CKAN cambie el nombre o package-id."""
    session = requests.Session()
    session.headers.update(HEADERS_CBA)

    # CKAN conserva el resource-id aunque cambien el nombre del archivo o la ruta del paquete.
    api_url = f"{URL_BASE_CBA}/api/3/action/resource_show"
    try:
        response = session.get(
            api_url,
            params={"id": ICC_CBA_RESOURCE_ID},
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        payload = response.json()
        candidate = str((payload.get("result") or {}).get("url") or "").strip()
        if candidate:
            candidate = urljoin(URL_BASE_CBA, candidate)
            if _is_allowed_cba_url(candidate) and candidate.lower().split("?")[0].endswith(".xlsx"):
                return candidate
    except Exception as exc:
        print(f"[WARN] ICC-CBA resource_show: {exc}")

    # Respaldo: leer las páginas HTML y localizar el enlace de descarga del recurso.
    for page_url in (ICC_CBA_RESOURCE_PAGE, ICC_CBA_DATASET_URL):
        try:
            response = session.get(page_url, timeout=HTTP_TIMEOUT, verify=False)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            candidates = []
            for anchor in soup.find_all("a", href=True):
                candidate = urljoin(URL_BASE_CBA, anchor["href"].strip())
                clean = candidate.lower().split("?")[0]
                if not _is_allowed_cba_url(candidate) or not clean.endswith(".xlsx"):
                    continue
                score = 0
                if ICC_CBA_RESOURCE_ID in candidate:
                    score += 10
                if "icc-cba-indice-general-y-rubros-valor-m2" in clean:
                    score += 5
                if "/download/" in clean:
                    score += 2
                candidates.append((score, candidate))
            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                return candidates[0][1]
        except Exception as exc:
            print(f"[WARN] ICC-CBA página {page_url}: {exc}")

    if _is_allowed_cba_url(ICC_CBA_FALLBACK_XLSX_URL):
        return ICC_CBA_FALLBACK_XLSX_URL
    raise ValueError("No se pudo resolver una URL oficial válida para el XLSX del ICC Córdoba.")


def _parse_icc_cba_excel(content: bytes, source_url: str = "") -> pd.DataFrame:
    """Lee las cuatro series de índices del archivo oficial de Córdoba."""
    if not content:
        raise ValueError("El archivo ICC Córdoba está vacío.")

    excel = pd.ExcelFile(BytesIO(content))
    sheet_name = next(
        (name for name in excel.sheet_names if "icc" in normalizar_texto(name)),
        excel.sheet_names[0],
    )
    raw = pd.read_excel(excel, sheet_name=sheet_name, header=None)

    header_row = None
    for idx, row in raw.iterrows():
        normalized = [normalizar_texto(value) for value in row.tolist()]
        wanted = {"nivel general", "materiales", "mano de obra", "varios"}
        if wanted.issubset(set(normalized)):
            header_row = int(idx)
            break
    if header_row is None:
        raise ValueError(
            "No se detectó la fila de encabezados Nivel General/Materiales/Mano de Obra/Varios."
        )

    data = raw.iloc[header_row + 1 :, :5].copy()
    data.columns = ["Fecha", "Nivel_General", "Materiales", "Mano_de_Obra", "Varios"]

    numeric_dates = pd.to_numeric(data["Fecha"], errors="coerce")
    parsed_dates = pd.to_datetime(data["Fecha"], errors="coerce", dayfirst=True)
    serial_mask = numeric_dates.between(20000, 80000)
    if serial_mask.any():
        parsed_dates.loc[serial_mask] = pd.to_datetime(
            numeric_dates.loc[serial_mask], unit="D", origin="1899-12-30", errors="coerce"
        )
    data["Fecha"] = parsed_dates.dt.to_period("M").dt.to_timestamp()

    for column in ["Nivel_General", "Materiales", "Mano_de_Obra", "Varios"]:
        data[column] = _normalizar_numero_argentino(data[column])

    data = data.dropna(
        subset=["Fecha", "Nivel_General", "Materiales", "Mano_de_Obra", "Varios"]
    ).copy()
    data = data.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    if data.empty:
        raise ValueError("El XLSX oficial no contiene filas utilizables del ICC Córdoba.")

    values = data[["Nivel_General", "Materiales", "Mano_de_Obra", "Varios"]]
    if (values <= 0).any().any() or (values > 1_000_000_000).any().any():
        raise ValueError("El ICC Córdoba contiene valores fuera de un rango razonable.")

    data["Fuente_URL"] = source_url
    return data.reset_index(drop=True)


def obtener_datos_icccba(fecha_desde=None) -> pd.DataFrame:
    source_url = _discover_icc_cba_xlsx_url()
    response = requests.get(
        source_url,
        headers=HEADERS_CBA,
        timeout=HTTP_TIMEOUT,
        verify=False,
    )
    response.raise_for_status()
    frame = _parse_icc_cba_excel(response.content, source_url=source_url)
    if fecha_desde is not None:
        frame = frame[frame["Fecha"] >= pd.Timestamp(fecha_desde)].copy()
    return frame.reset_index(drop=True)


# IPIM INDEC
URL_IPIM = "https://www.indec.gob.ar/ftp/cuadros/economia/series_sipm_dic2015.xls"
FILTRO_DESCRIPCIONES_IPIM = [
    "Mes", "Nivel general", "Productos nacionales",
    " Productos manufacturados", " Madera y productos de madera excepto muebles",
    " Productos refinados del petróleo", " Sustancias y productos químicos",
    " Jabones y detergentes", " Productos de minerales no metálicos",
    " Máquinas y equipos", " Máquinas y aparatos eléctricos",
    " Equipos para medicina e instrumentos de medición",
    " Instrumentos de medición de servicios domiciliarios",
    " Vehículos automotores, carrocerías y repuestos",
    " Energía eléctrica", "Productos importados",
]
ORDEN_DESCRIPCIONES_IPIM = [
    "Nivel general", "Productos nacionales", "Productos manufacturados",
    "Madera y productos de madera excepto muebles", "Productos refinados del petróleo",
    "Sustancias y productos químicos", "Jabones y detergentes",
    "Productos de minerales no metálicos", "Máquinas y equipos",
    "Máquinas y aparatos eléctricos", "Equipos para medicina e instrumentos de medición",
    "Instrumentos de medición de servicios domiciliarios",
    "Vehículos automotores, carrocerías y repuestos", "Energía eléctrica", "Productos importados",
]


def obtener_datos_ipim() -> pd.DataFrame:
    response = requests.get(URL_IPIM, timeout=HTTP_TIMEOUT, verify=False)
    response.raise_for_status()
    df = pd.read_excel(BytesIO(response.content), sheet_name="IPIM", skiprows=3)
    df.loc[0, "Código"] = "Mo"
    df.loc[0, "Descripción"] = "Mes"
    columnas = pd.Series(df.columns.to_list()).replace("Unnamed.*", pd.NA, regex=True).ffill()
    df.columns = columnas
    tabla = df[df["Descripción"].isin(FILTRO_DESCRIPCIONES_IPIM)].copy()
    if tabla.empty:
        raise ValueError("No se encontraron las descripciones IPIM objetivo.")
    fila_meses = tabla.iloc[0]
    nuevas_columnas = []
    for col, mes in zip(tabla.columns, fila_meses):
        if col in ["Código", "Descripción"]:
            nuevas_columnas.append(col)
        else:
            nuevas_columnas.append(f"{col}_{mes}".strip())
    tabla.columns = nuevas_columnas
    tabla = tabla.drop(index=0).reset_index(drop=True)
    df_long = tabla.melt(id_vars=["Código", "Descripción"], var_name="Periodo", value_name="Valor")
    df_long[["Año", "Mes"]] = df_long["Periodo"].str.extract(r"(\d{4})_([\w\*]+)")
    df_long = df_long[["Año", "Mes", "Código", "Descripción", "Valor"]]
    df_long["Valor"] = pd.to_numeric(df_long["Valor"], errors="coerce")
    df_long = df_long.dropna(subset=["Valor"])
    df_long["Mes-Año"] = df_long["Mes"] + "-" + df_long["Año"]
    df_long["Para_fecha"] = "1-" + df_long["Mes-Año"].astype(str).str.replace("*", "", regex=False).replace(MAPA_MESES_NUMS_CORTO, regex=True)
    df_long["Fecha"] = pd.to_datetime(df_long["Para_fecha"], format="%d-%m-%Y", errors="coerce")
    df_long = df_long.dropna(subset=["Fecha"])
    df_long["Descripción"] = df_long["Descripción"].astype(str).str.strip()
    df_long["Orden"] = pd.Categorical(df_long["Descripción"], categories=ORDEN_DESCRIPCIONES_IPIM, ordered=True)
    return df_long[["Fecha", "Mes-Año", "Descripción", "Valor", "Orden"]].sort_values(["Fecha", "Orden"]).drop(columns=["Orden"], errors="ignore").reset_index(drop=True)


# ICC INDEC
URL_ICC = "https://www.indec.gob.ar/ftp/cuadros/economia/icc_variaciones_indices_2016.xls"
HOJA_ICC = "Nivel general y capítulos_var%"
ORDEN_DESCRIPCIONES_ICC = ["Nivel general", "Materiales", "Mano de obra (1)", "Gastos generales"]


def _limpiar_texto_icc(valor):
    if pd.isna(valor):
        return ""
    return " ".join(str(valor).strip().replace("'", "").replace("*", "").split())


def _detectar_filas_encabezado_icc(df_raw):
    meses_posibles = set(MAPA_MESES_NUMS_LARGO.keys())
    for idx, row in df_raw.iterrows():
        valores = [_limpiar_texto_icc(v) for v in row.tolist()]
        if sum(1 for v in valores if v in meses_posibles) >= 6:
            return idx - 1, idx
    raise ValueError("No se pudo detectar la fila de meses en ICC.")


def _construir_columnas_periodo_icc(df_raw, fila_anios, fila_meses):
    columnas_periodo = []
    anio_actual = None
    for col in range(1, df_raw.shape[1]):
        valor_anio = df_raw.iloc[fila_anios, col]
        valor_mes = df_raw.iloc[fila_meses, col]
        if pd.notna(valor_anio):
            try:
                anio_actual = int(valor_anio)
            except Exception:
                pass
        mes_limpio = _limpiar_texto_icc(valor_mes)
        if not mes_limpio or mes_limpio not in MAPA_MESES_NUMS_LARGO or anio_actual is None:
            continue
        numero_mes = MAPA_MESES_NUMS_LARGO[mes_limpio]
        fecha = pd.to_datetime(f"1-{numero_mes}-{anio_actual}", format="%d-%m-%Y", errors="coerce")
        if pd.isna(fecha):
            continue
        columnas_periodo.append({"columna": col, "fecha": fecha, "mes_anio": f"{mes_limpio[:3]}-{anio_actual}"})
    return columnas_periodo


def obtener_datos_icc() -> pd.DataFrame:
    response = requests.get(URL_ICC, timeout=HTTP_TIMEOUT, verify=False)
    response.raise_for_status()
    df_raw = pd.read_excel(BytesIO(response.content), sheet_name=HOJA_ICC, header=None)
    fila_anios, fila_meses = _detectar_filas_encabezado_icc(df_raw)
    columnas_periodo = _construir_columnas_periodo_icc(df_raw, fila_anios, fila_meses)
    if not columnas_periodo:
        raise ValueError("No se detectaron columnas de períodos en ICC.")
    registros = []
    for fila in range(fila_meses + 1, df_raw.shape[0]):
        descripcion = _limpiar_texto_icc(df_raw.iloc[fila, 0])
        if descripcion not in ORDEN_DESCRIPCIONES_ICC:
            continue
        for item in columnas_periodo:
            valor = pd.to_numeric(df_raw.iloc[fila, item["columna"]], errors="coerce")
            if pd.isna(valor):
                continue
            registros.append({"Fecha": item["fecha"], "Mes-Año": item["mes_anio"], "Descripción": descripcion, "Valor": valor})
    df = pd.DataFrame(registros)
    if df.empty:
        raise ValueError("No se encontraron datos ICC.")
    df["Orden"] = pd.Categorical(df["Descripción"], categories=ORDEN_DESCRIPCIONES_ICC, ordered=True)
    return df.sort_values(["Fecha", "Orden"]).drop(columns=["Orden"], errors="ignore").reset_index(drop=True)


# Índice de salarios INDEC
URL_SALARIOS_PAGE = "https://www.indec.gob.ar/indec/web/Nivel4-Tema-4-31-61"
URL_SALARIOS_CSV = "https://www.indec.gob.ar/ftp/cuadros/sociedad/indice_salarios.csv"
URL_SALARIOS_FTP_BASE = "https://www.indec.gob.ar/ftp/cuadros/sociedad/"
SALARIOS_XLS_PATTERN = re.compile(
    r"(?:https?://(?:www\.)?indec\.gob\.ar)?"
    r"/ftp/cuadros/sociedad/variaciones_salarios_(\d{2})_(\d{2})\.xls",
    re.IGNORECASE,
)
HEADERS_INDEC_SALARIOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
}
SALARIOS_SERIES_XLS = {
    3: "Sector privado registrado",
    5: "Sector público",
    7: "Total registrado",
    9: "Sector privado no registrado",
    11: "Total índice de salarios",
}
SALARIOS_CSV_COLUMNS = {
    "IS_sector_privado_registrado": "Sector privado registrado",
    "IS_sector_publico": "Sector público",
    "IS_total_registrado": "Total registrado",
    "IS_sector_no_registrado": "Sector privado no registrado",
    "IS_indice_total": "Total índice de salarios",
}
SALARIOS_MONTHS = {
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


def _salarios_sort_key(url: str) -> Tuple[int, int]:
    match = SALARIOS_XLS_PATTERN.search(url)
    if not match:
        return (0, 0)
    month = int(match.group(1))
    year = 2000 + int(match.group(2))
    return (year, month)


def _extract_salarios_xls_urls(html: str) -> List[str]:
    """Extrae vínculos XLS oficiales tanto de href como del texto HTML."""
    if not html:
        return []

    found = set()
    soup = BeautifulSoup(html, "html.parser")
    candidates = [a.get("href", "") for a in soup.find_all("a", href=True)]
    candidates.extend(match.group(0) for match in SALARIOS_XLS_PATTERN.finditer(html))

    for candidate in candidates:
        candidate = str(candidate).strip()
        if not candidate:
            continue
        absolute = urljoin(URL_SALARIOS_PAGE, candidate)
        match = SALARIOS_XLS_PATTERN.search(absolute)
        if not match:
            continue
        normalized = urljoin(URL_SALARIOS_FTP_BASE, f"variaciones_salarios_{match.group(1)}_{match.group(2)}.xls")
        found.add(normalized)

    return sorted(found, key=_salarios_sort_key, reverse=True)


def _download_salarios_xls() -> Tuple[str, bytes]:
    """
    Localiza y descarga el XLS mensual más reciente.

    La página temática de INDEC se renderiza parcialmente con JavaScript, por
    lo que se intenta primero leer el vínculo publicado y, si no aparece en el
    HTML inicial, se prueban nombres mensuales recientes dentro del dominio
    oficial. El archivo es pequeño y el primer 200 válido detiene la búsqueda.
    """
    errors: List[str] = []
    discovered: List[str] = []

    try:
        page = requests.get(
            URL_SALARIOS_PAGE,
            headers=HEADERS_INDEC_SALARIOS,
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        page.raise_for_status()
        discovered = _extract_salarios_xls_urls(page.text)
    except Exception as exc:
        errors.append(f"página temática: {exc}")

    candidates = list(discovered)
    current_month = date.today().replace(day=1)
    for offset in range(0, 25):
        candidate_month = _add_months(current_month, -offset)
        candidate = urljoin(
            URL_SALARIOS_FTP_BASE,
            f"variaciones_salarios_{candidate_month.month:02d}_{candidate_month.year % 100:02d}.xls",
        )
        if candidate not in candidates:
            candidates.append(candidate)

    for url in candidates:
        try:
            response = requests.get(
                url,
                headers=HEADERS_INDEC_SALARIOS,
                timeout=HTTP_TIMEOUT,
                verify=False,
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            content = response.content
            if len(content) < 1024:
                errors.append(f"{url}: archivo demasiado pequeño")
                continue
            return url, content
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    detail = "; ".join(errors[-5:])
    raise RuntimeError(f"No se pudo localizar el XLS vigente del índice de salarios. {detail}")


def _parse_salarios_xls(content: bytes, source_url: str) -> pd.DataFrame:
    """Lee el Cuadro 1 y devuelve las cinco series de números índice."""
    raw = pd.read_excel(
        BytesIO(content),
        sheet_name="Cuadro 1",
        header=None,
        engine="xlrd",
    )
    if raw.shape[1] < 12:
        raise ValueError("El Cuadro 1 de salarios no contiene las columnas esperadas.")

    records: List[Dict[str, Any]] = []
    current_year: Optional[int] = None

    for _, row in raw.iterrows():
        year_value = _value_or_none(row.iloc[0] if len(row) > 0 else None)
        if year_value is not None:
            year_int = int(year_value)
            if 2000 <= year_int <= 2100 and abs(year_value - year_int) < 1e-9:
                current_year = year_int

        month_text = normalizar_texto(row.iloc[1] if len(row) > 1 else "")
        month_number = SALARIOS_MONTHS.get(month_text)
        if not month_number or current_year is None:
            continue

        fecha = pd.Timestamp(date(current_year, month_number, 1))
        for column_index, series_name in SALARIOS_SERIES_XLS.items():
            value = _value_or_none(row.iloc[column_index])
            if value is None:
                continue
            records.append({
                "Fecha": fecha,
                "Mes-Año": f"{MAPA_NUM_MESES[month_number]}-{current_year}",
                "Serie": series_name,
                "Valor": value,
                "Fuente": source_url,
            })

    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("No se detectaron números índice en el Cuadro 1 de salarios.")
    frame.attrs["source_url"] = source_url
    frame.attrs["source_format"] = "xls"
    return frame.sort_values(["Fecha", "Serie"]).reset_index(drop=True)


def _parse_salarios_csv(content: bytes, source_url: str) -> pd.DataFrame:
    """Respaldo oficial estable con las mismas cinco series del Cuadro 1."""
    frame = pd.read_csv(
        BytesIO(content),
        sep=";",
        encoding="utf-8-sig",
        dtype=str,
    )
    required = {"periodo", *SALARIOS_CSV_COLUMNS.keys()}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"El CSV de salarios no contiene columnas requeridas: {sorted(missing)}")

    records: List[Dict[str, Any]] = []
    for _, row in frame.iterrows():
        fecha = pd.to_datetime(row.get("periodo"), errors="coerce", dayfirst=True)
        if pd.isna(fecha):
            continue
        fecha = pd.Timestamp(date(int(fecha.year), int(fecha.month), 1))
        for source_column, series_name in SALARIOS_CSV_COLUMNS.items():
            value = _value_or_none(row.get(source_column))
            if value is None:
                continue
            records.append({
                "Fecha": fecha,
                "Mes-Año": f"{MAPA_NUM_MESES[int(fecha.month)]}-{int(fecha.year)}",
                "Serie": series_name,
                "Valor": value,
                "Fuente": source_url,
            })

    result = pd.DataFrame(records)
    if result.empty:
        raise ValueError("El CSV oficial de salarios no devolvió valores utilizables.")
    result.attrs["source_url"] = source_url
    result.attrs["source_format"] = "csv"
    return result.sort_values(["Fecha", "Serie"]).reset_index(drop=True)


def obtener_datos_salarios() -> pd.DataFrame:
    """
    Obtiene las cinco series salariales de INDEC.

    Prioridad:
    1. XLS mensual más reciente, descubierto dinámicamente.
    2. CSV histórico oficial de URL estable, para continuidad operativa.
    """
    xls_error: Optional[Exception] = None
    try:
        source_url, content = _download_salarios_xls()
        return _parse_salarios_xls(content, source_url)
    except Exception as exc:
        xls_error = exc
        print(f"[WARN] Índice de salarios XLS: {exc}. Se intenta el CSV oficial estable.")

    try:
        response = requests.get(
            URL_SALARIOS_CSV,
            headers=HEADERS_INDEC_SALARIOS,
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        return _parse_salarios_csv(response.content, URL_SALARIOS_CSV)
    except Exception as csv_exc:
        raise RuntimeError(
            "No se pudieron obtener los índices de salarios desde el XLS ni "
            f"desde el CSV oficial. XLS: {xls_error}. CSV: {csv_exc}"
        ) from csv_exc


# BCRA A3500 y B9791
URL_A3500 = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/com3500.xls"
COLUMNAS_ORDENADAS_A3500 = ["Fecha", "Mes-Año", "TC", "TC_promedio_mensual"]
# La serie B 9791 se obtiene de la API oficial de Estadísticas Monetarias v4.0.
# El id 4 corresponde a “Tipo de cambio minorista (promedio vendedor)”.
COLUMNAS_ORDENADAS_B9791 = ["Fecha", "Mes-Año", "Vendedor", "Promedio_mensual"]


def obtener_datos_a3500() -> pd.DataFrame:
    response = requests.get(URL_A3500, timeout=HTTP_TIMEOUT, verify=False)
    response.raise_for_status()
    df = pd.read_excel(BytesIO(response.content), skiprows=3)
    df.columns = [str(c).strip() for c in df.columns]
    col_fecha = next((c for c in df.columns if "fecha" in c.lower() and "promedio" not in c.lower()), None)
    col_tc = next((c for c in df.columns if "tipo" in c.lower() and "cambio" in c.lower() and "promedio" not in c.lower()), None)
    if not col_fecha:
        raise ValueError("No se encontró columna de fecha en A3500.")
    if not col_tc:
        col_tc = next((c for c in df.columns if "dólar" in c.lower() or "dolar" in c.lower()), None)
    if not col_tc:
        raise ValueError("No se encontró columna de TC en A3500.")
    df = df[[col_fecha, col_tc]].rename(columns={col_fecha: "Fecha", col_tc: "TC"})
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    # El XLS oficial ya entrega números decimales. La limpieza anterior quitaba el punto
    # y convertía 1483.0198 en 14830198.
    df["TC"] = _normalizar_numero_argentino(df["TC"])
    df = df.dropna(subset=["Fecha", "TC"]).copy()
    if (df["TC"] <= 0).any() or (df["TC"] > 100000).any():
        raise ValueError("Los valores A3500 quedaron fuera de un rango razonable; se aborta para no contaminar la hoja.")
    df["Mes-Año"] = df["Fecha"].dt.month.map(MAPA_NUM_MESES) + "-" + df["Fecha"].dt.year.astype(str)
    media_mensual = df.groupby([df["Fecha"].dt.year, df["Fecha"].dt.month])["TC"].transform("mean").round(4)
    df["TC_promedio_mensual"] = media_mensual
    return df[COLUMNAS_ORDENADAS_A3500].sort_values("Fecha").reset_index(drop=True)


def _extract_bcra_api_detail(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = payload.get("results") or []
    detail: List[Dict[str, Any]] = []
    for item in results:
        if isinstance(item, dict) and isinstance(item.get("detalle"), list):
            detail.extend(x for x in item["detalle"] if isinstance(x, dict))
        elif isinstance(item, dict) and "fecha" in item and "valor" in item:
            detail.append(item)
    return detail


def _bcra_daily_frame_from_payload(
    payload: Dict[str, Any],
    *,
    value_column: str,
    source_name: str,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> pd.DataFrame:
    """Normaliza una serie diaria del API monetaria del BCRA.

    El promedio mensual se calcula sobre la cantidad real de observaciones
    válidas del mes. Para CER e ICL suelen ser todos los días calendario;
    para BADLAR son los días para los que el BCRA publicó una tasa.
    """
    detail = _extract_bcra_api_detail(payload)
    if not detail:
        errors = payload.get("errorMessages") or []
        raise ValueError(f"La API BCRA no devolvió datos para {source_name}. {errors}")

    frame = pd.DataFrame(detail)
    if not {"fecha", "valor"}.issubset(frame.columns):
        raise ValueError(
            f"La respuesta BCRA de {source_name} no contiene las columnas fecha y valor."
        )

    frame = frame[["fecha", "valor"]].rename(
        columns={"fecha": "Fecha", "valor": value_column}
    )
    frame["Fecha"] = pd.to_datetime(frame["Fecha"], errors="coerce")
    frame[value_column] = _normalizar_numero_argentino(frame[value_column])
    frame = frame.dropna(subset=["Fecha", value_column]).copy()
    frame = frame.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")

    if frame.empty:
        raise ValueError(f"La API BCRA de {source_name} devolvió registros no utilizables.")
    if minimum is not None and (frame[value_column] < minimum).any():
        raise ValueError(f"{source_name}: se detectaron valores inferiores a {minimum}.")
    if maximum is not None and (frame[value_column] > maximum).any():
        raise ValueError(f"{source_name}: se detectaron valores superiores a {maximum}.")

    frame["Mes-Año"] = (
        frame["Fecha"].dt.month.map(MAPA_NUM_MESES)
        + "-"
        + frame["Fecha"].dt.year.astype(str)
    )
    groups = [frame["Fecha"].dt.year, frame["Fecha"].dt.month]
    frame["Promedio_mensual"] = frame.groupby(groups)[value_column].transform("mean")
    frame["Observaciones_mes"] = (
        frame.groupby(groups)[value_column].transform("count").astype(int)
    )
    return frame[
        ["Fecha", "Mes-Año", value_column, "Promedio_mensual", "Observaciones_mes"]
    ].reset_index(drop=True)


def _obtener_datos_bcra_variable(
    variable_id: int,
    *,
    value_column: str,
    source_name: str,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> pd.DataFrame:
    """Descarga una variable diaria desde Estadísticas Monetarias v4.0."""
    hasta = fecha_hasta or datetime.now().date()
    desde = fecha_desde or (hasta - timedelta(days=550))
    if desde > hasta:
        raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")

    url = f"{BCRA_MONETARIAS_API_BASE}/{int(variable_id)}"
    response = requests.get(
        url,
        params={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "limit": 3000},
        headers={"Accept-Language": "es-AR", "Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
        verify=False,
    )
    response.raise_for_status()
    return _bcra_daily_frame_from_payload(
        response.json(),
        value_column=value_column,
        source_name=source_name,
        minimum=minimum,
        maximum=maximum,
    )


def obtener_datos_cer(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    return _obtener_datos_bcra_variable(
        BCRA_CER_VARIABLE_ID,
        value_column="CER",
        source_name="CER",
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        minimum=0,
        maximum=1_000_000_000,
    )


def obtener_datos_icl(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    return _obtener_datos_bcra_variable(
        BCRA_ICL_VARIABLE_ID,
        value_column="ICL",
        source_name="ICL",
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        minimum=0,
        maximum=1_000_000,
    )


def obtener_datos_badlar_na(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    return _obtener_datos_bcra_variable(
        BCRA_BADLAR_NA_VARIABLE_ID,
        value_column="BADLAR_NA",
        source_name="BADLAR n.a.",
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        minimum=0,
        maximum=1_000,
    )


def obtener_datos_badlar_ea(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    return _obtener_datos_bcra_variable(
        BCRA_BADLAR_EA_VARIABLE_ID,
        value_column="BADLAR_EA",
        source_name="BADLAR e.a.",
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        minimum=0,
        maximum=10_000,
    )


def obtener_datos_b9791(fecha_desde: Optional[date] = None, fecha_hasta: Optional[date] = None) -> pd.DataFrame:
    """Obtiene el promedio vendedor B 9791 desde la API oficial vigente del BCRA."""
    hasta = fecha_hasta or datetime.now().date()
    desde = fecha_desde or (hasta - timedelta(days=550))
    url = f"{BCRA_MONETARIAS_API_BASE}/{BCRA_B9791_VARIABLE_ID}"
    response = requests.get(
        url,
        params={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "limit": 3000},
        headers={"Accept-Language": "es-AR", "Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
        verify=False,
    )
    response.raise_for_status()
    payload = response.json()
    detail = _extract_bcra_api_detail(payload)
    if not detail:
        errors = payload.get("errorMessages") or []
        raise ValueError(f"La API BCRA no devolvió datos para B 9791. {errors}")

    df = pd.DataFrame(detail)
    if not {"fecha", "valor"}.issubset(df.columns):
        raise ValueError("La respuesta BCRA B 9791 no contiene fecha y valor.")
    df = df[["fecha", "valor"]].rename(columns={"fecha": "Fecha", "valor": "Vendedor"})
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df["Vendedor"] = _normalizar_numero_argentino(df["Vendedor"])
    df = df.dropna(subset=["Fecha", "Vendedor"]).copy()
    if df.empty:
        raise ValueError("La API BCRA B 9791 devolvió registros sin valores utilizables.")
    if (df["Vendedor"] <= 0).any() or (df["Vendedor"] > 100000).any():
        raise ValueError("Los valores B 9791 quedaron fuera de un rango razonable.")
    df["Mes-Año"] = df["Fecha"].dt.month.map(MAPA_NUM_MESES) + "-" + df["Fecha"].dt.year.astype(str)
    df["Promedio_mensual"] = df.groupby([df["Fecha"].dt.year, df["Fecha"].dt.month])["Vendedor"].transform("mean").round(4)
    return df[COLUMNAS_ORDENADAS_B9791].sort_values("Fecha").reset_index(drop=True)


# Banco Nación: promedio mensual del punto medio compra/venta del dólar billete.
def _read_bna_csv(content: bytes) -> pd.DataFrame:
    last_error = None
    for encoding in ("utf-8-sig", "latin1", "cp1252"):
        try:
            frame = pd.read_csv(BytesIO(content), sep=";", encoding=encoding)
            if len(frame.columns) >= 3:
                return frame
        except Exception as exc:
            last_error = exc
    raise ValueError(f"No se pudo interpretar el CSV histórico del BNA: {last_error}")


def obtener_datos_bna(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    hasta = fecha_hasta or datetime.now().date()
    desde = fecha_desde or (hasta - timedelta(days=550))
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "es-AR,es;q=0.9",
    })

    landing = session.get(BNA_HISTORICO_URL, timeout=HTTP_TIMEOUT)
    landing.raise_for_status()
    soup = BeautifulSoup(landing.text, "html.parser")
    token_node = soup.find("input", {"name": "__RequestVerificationToken"})
    if token_node is None or not token_node.get("value"):
        raise ValueError("El BNA no devolvió el token de validación para la descarga histórica.")
    token = str(token_node["value"]).strip()

    base_params = {
        "RadioButton": "on",
        "filtroEuroDescarga": "0",
        "filtroDolarDescarga": "1",
        "fechaDesde": desde.strftime("%d/%m/%Y"),
        "fechaHasta": hasta.strftime("%d/%m/%Y"),
        "id": "billetes",
        "descargar": "",
    }
    attempts = []
    for token_value in (token, f"__{token}"):
        params = dict(base_params)
        params["__RequestVerificationToken"] = token_value
        attempts.extend([
            ("GET", params),
            ("POST", params),
        ])

    content = None
    errors = []
    for method, payload in attempts:
        try:
            if method == "GET":
                response = session.get(BNA_DESCARGA_URL, params=payload, timeout=HTTP_TIMEOUT)
            else:
                response = session.post(
                    BNA_DESCARGA_URL,
                    data=payload,
                    headers={"Referer": BNA_HISTORICO_URL},
                    timeout=HTTP_TIMEOUT,
                )
            response.raise_for_status()
            probe = response.content[:1000].decode("latin1", errors="ignore").lower()
            if ";" in probe and ("fecha" in probe or "cotizacion" in probe):
                content = response.content
                break
            errors.append(f"{method}: respuesta no reconocida ({response.status_code})")
        except Exception as exc:
            errors.append(f"{method}: {exc}")
    if content is None:
        raise ValueError("No se pudo descargar el histórico del BNA. " + " | ".join(errors[-4:]))

    frame = _read_bna_csv(content)
    frame.columns = [str(column).replace("\ufeff", "").strip() for column in frame.columns]
    normalized = {normalizar_texto(column): column for column in frame.columns}
    date_col = next((real for norm, real in normalized.items() if "fecha" in norm), None)
    buy_col = next((real for norm, real in normalized.items() if "compra" in norm), None)
    sell_col = next((real for norm, real in normalized.items() if "venta" in norm), None)
    if not date_col or not buy_col or not sell_col:
        raise ValueError(f"El CSV BNA no contiene Fecha, Compra y Venta. Columnas: {frame.columns.tolist()}")

    frame = frame[[date_col, buy_col, sell_col]].rename(
        columns={date_col: "Fecha", buy_col: "Compra", sell_col: "Venta"}
    )
    frame["Fecha"] = pd.to_datetime(frame["Fecha"], errors="coerce", dayfirst=True)
    frame["Compra"] = _normalizar_numero_argentino(frame["Compra"])
    frame["Venta"] = _normalizar_numero_argentino(frame["Venta"])
    frame = frame.dropna(subset=["Fecha", "Compra", "Venta"]).copy()
    frame = frame.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    if frame.empty:
        raise ValueError("El histórico BNA no devolvió cotizaciones utilizables.")
    if (frame[["Compra", "Venta"]] <= 0).any().any() or (frame[["Compra", "Venta"]] > 1_000_000).any().any():
        raise ValueError("Las cotizaciones BNA quedaron fuera de un rango razonable.")

    frame["Promedio"] = (frame["Compra"] + frame["Venta"]) / 2.0
    groups = [frame["Fecha"].dt.year, frame["Fecha"].dt.month]
    frame["Media_de_medias"] = frame.groupby(groups)["Promedio"].transform("mean")
    frame["Observaciones_mes"] = frame.groupby(groups)["Promedio"].transform("count").astype(int)
    frame["Mes-Año"] = frame["Fecha"].dt.month.map(MAPA_NUM_MESES) + "-" + frame["Fecha"].dt.year.astype(str)
    return frame[
        ["Fecha", "Mes-Año", "Media_de_medias", "Promedio", "Compra", "Venta", "Observaciones_mes"]
    ].reset_index(drop=True)



# =========================================================
# JUS Córdoba, IPC EE.UU., IPC San Luis e IOP Córdoba
# =========================================================
MESES_ES_NUMERO = {
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

IOP_CBA_TARGET_HEADERS = {
    "1": "IOP Córdoba Orden 1 Aceros",
    "7": "IOP Córdoba Orden 7 Áridos Triturados",
    "8": "IOP Córdoba Orden 8 Asfaltos",
    "14": "IOP Córdoba Orden 14 Combustible",
    "17": "IOP Córdoba Orden 17 Equipo - Amort. Equipo",
    "18": "IOP Córdoba Orden 18 Gastos Generales",
    "21": "IOP Córdoba Orden 21 Hormigón",
    "26": "IOP Córdoba Orden 26 Mano de Obra",
    "31": "IOP Córdoba Orden 31 Pintura termoplástica refl",
    "37": "IOP Córdoba Orden 37 Transporte",
    "45": "IOP Córdoba Orden 45 Conductores Subterráneos",
}


def _http_browser_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.7",
    }


def obtener_datos_jus() -> pd.DataFrame:
    """Extrae el valor mensual del JUS publicado por el Poder Judicial de Córdoba."""
    response = requests.get(
        JUS_CORDOBA_URL,
        headers=_http_browser_headers(),
        timeout=HTTP_TIMEOUT,
        verify=False,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records: List[Dict[str, Any]] = []

    for tr in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        if not cells:
            continue
        date_index = next(
            (i for i, value in enumerate(cells) if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value)),
            None,
        )
        if date_index is None:
            continue
        parsed_date = datetime.strptime(cells[date_index], "%d/%m/%Y")
        jus_value = None
        for value in cells[date_index + 1 :]:
            candidate = _value_or_none(value)
            if candidate is not None:
                jus_value = candidate
                break
        if jus_value is None:
            continue
        records.append({
            "Fecha": pd.Timestamp(date(parsed_date.year, parsed_date.month, 1)),
            "JUS": float(jus_value),
            "Fuente_URL": JUS_CORDOBA_URL,
        })

    if not records:
        compact = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        pattern = re.compile(
            r"(\d{2}/\d{2}/\d{4}).{0,120}?\$?\s*([\d.]+,\d{2})",
            flags=re.IGNORECASE,
        )
        for date_text, value_text in pattern.findall(compact):
            parsed_date = datetime.strptime(date_text, "%d/%m/%Y")
            value = _value_or_none(value_text)
            if value is not None:
                records.append({
                    "Fecha": pd.Timestamp(date(parsed_date.year, parsed_date.month, 1)),
                    "JUS": float(value),
                    "Fuente_URL": JUS_CORDOBA_URL,
                })

    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("No se detectaron filas históricas del JUS Córdoba.")
    frame = frame.dropna(subset=["Fecha", "JUS"]).sort_values("Fecha")
    frame = frame.drop_duplicates(subset=["Fecha"], keep="last")
    if (frame["JUS"] <= 0).any() or (frame["JUS"] > 1_000_000_000).any():
        raise ValueError("El JUS Córdoba contiene valores fuera de un rango razonable.")
    frame["Mes-Año"] = frame["Fecha"].dt.month.map(MAPA_NUM_MESES) + "-" + frame["Fecha"].dt.year.astype(str)
    return frame[["Fecha", "Mes-Año", "JUS", "Fuente_URL"]].reset_index(drop=True)


def _parse_bls_cpi_payload(payload: Dict[str, Any]) -> pd.DataFrame:
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS no completó la solicitud: {payload.get('message')}")
    series = ((payload.get("Results") or {}).get("series") or [])
    if not series:
        raise ValueError("BLS no devolvió la serie solicitada.")
    records = []
    for item in series[0].get("data") or []:
        period = str(item.get("period") or "")
        match = re.fullmatch(r"M(0[1-9]|1[0-2])", period)
        if not match:
            continue
        year = int(item["year"])
        month = int(match.group(1))
        value = _value_or_none(item.get("value"))
        if value is not None:
            records.append({
                "Fecha": pd.Timestamp(date(year, month, 1)),
                "Valor": float(value),
                "Serie": BLS_CPI_US_SERIES_ID,
                "Fuente_URL": BLS_API_URL,
            })
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("La API BLS no devolvió observaciones mensuales utilizables.")
    return frame


def _obtener_ipc_eeuu_flat_file() -> pd.DataFrame:
    response = requests.get(
        BLS_CPI_US_FLAT_FILE,
        headers={"User-Agent": _http_browser_headers()["User-Agent"]},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text), sep="\t", dtype=str)
    frame.columns = [str(col).strip() for col in frame.columns]
    needed = {"series_id", "year", "period", "value"}
    if not needed.issubset(frame.columns):
        raise ValueError("El archivo plano de BLS no contiene las columnas esperadas.")
    frame["series_id"] = frame["series_id"].astype(str).str.strip()
    frame["period"] = frame["period"].astype(str).str.strip()
    frame = frame[
        (frame["series_id"] == BLS_CPI_US_SERIES_ID)
        & frame["period"].str.fullmatch(r"M(0[1-9]|1[0-2])", na=False)
    ].copy()
    frame["Mes"] = pd.to_numeric(frame["period"].str[1:], errors="coerce")
    frame["Año"] = pd.to_numeric(frame["year"], errors="coerce")
    frame["Valor"] = pd.to_numeric(frame["value"].str.strip(), errors="coerce")
    frame = frame.dropna(subset=["Mes", "Año", "Valor"])
    frame["Fecha"] = pd.to_datetime(
        dict(year=frame["Año"].astype(int), month=frame["Mes"].astype(int), day=1),
        errors="coerce",
    )
    frame["Serie"] = BLS_CPI_US_SERIES_ID
    frame["Fuente_URL"] = BLS_CPI_US_FLAT_FILE
    return frame[["Fecha", "Valor", "Serie", "Fuente_URL"]].dropna(subset=["Fecha"])


def obtener_datos_ipc_eeuu(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    hasta = fecha_hasta or datetime.now().date()
    desde = fecha_desde or date(max(1913, hasta.year - 19), 1, 1)
    api_error: Optional[Exception] = None
    try:
        response = requests.post(
            BLS_API_URL,
            json={
                "seriesid": [BLS_CPI_US_SERIES_ID],
                "startyear": str(desde.year),
                "endyear": str(hasta.year),
            },
            headers={"Content-Type": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        frame = _parse_bls_cpi_payload(response.json())
    except Exception as exc:
        api_error = exc
        print(f"[WARN] IPC EE.UU. API BLS: {exc}. Se intenta el archivo plano oficial.")
        try:
            frame = _obtener_ipc_eeuu_flat_file()
        except Exception as fallback_exc:
            raise RuntimeError(
                f"No se pudo obtener el IPC EE.UU. API={api_error}; archivo={fallback_exc}"
            ) from fallback_exc

    frame["Fecha"] = pd.to_datetime(frame["Fecha"], errors="coerce")
    frame = frame.dropna(subset=["Fecha", "Valor"]).copy()
    frame = frame[(frame["Fecha"].dt.date >= desde) & (frame["Fecha"].dt.date <= hasta)]
    frame = frame.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    if frame.empty:
        raise ValueError("No hay datos del IPC EE.UU. en el rango solicitado.")
    if (frame["Valor"] <= 0).any() or (frame["Valor"] > 100_000).any():
        raise ValueError("El IPC EE.UU. contiene valores fuera de un rango razonable.")
    frame["Mes-Año"] = frame["Fecha"].dt.month.map(MAPA_NUM_MESES) + "-" + frame["Fecha"].dt.year.astype(str)
    return frame[["Fecha", "Mes-Año", "Valor", "Serie", "Fuente_URL"]].reset_index(drop=True)


def _spanish_month_year(text: str) -> Optional[date]:
    normalized = normalizar_texto(text)
    pattern = r"\b(" + "|".join(MESES_ES_NUMERO.keys()) + r")\b\s*(?:de\s*)?(20\d{2})"
    match = re.search(pattern, normalized, flags=re.IGNORECASE)
    if not match:
        return None
    return date(int(match.group(2)), MESES_ES_NUMERO[match.group(1)], 1)


def _extract_ipc_san_luis_index(pdf_text: str, report_month: date) -> Optional[float]:
    compact = re.sub(r"\s+", " ", pdf_text.replace("\u00a0", " "))
    patterns = [
        r"Nivel\s+General\s+[-+]?\d+(?:[.,]\d+)?\s+0\s+([\d.]+,\d+)",
        r"Nombre\s+del\s+grupo.{0,100}?Nivel\s+General.{0,40}?([\d.]+,\d+)",
    ]
    month_names = [name for name, number in MESES_ES_NUMERO.items() if number == report_month.month]
    if month_names:
        patterns.append(
            rf"\b(?:{'|'.join(month_names)})\b\s+([\d.]+,\d+)\s+[-+]?\d+(?:[.,]\d+)?"
        )
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            value = _value_or_none(match.group(1))
            if value is not None:
                return float(value)
    return None


def obtener_datos_ipc_san_luis(
    max_reports: int = 8,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    """Descarga los informes recientes y extrae el índice Nivel General Base 2003=100."""
    response = requests.get(
        IPC_SAN_LUIS_URL,
        headers=_http_browser_headers(),
        timeout=HTTP_TIMEOUT,
        verify=False,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    candidates: List[Tuple[date, str]] = []
    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(IPC_SAN_LUIS_URL, anchor["href"].strip())
        decoded = unquote(url).lower()
        if not decoded.split("?")[0].endswith(".pdf"):
            continue
        if "ipc" not in decoded or "san luis" not in decoded:
            continue
        if url in seen_urls:
            continue
        heading = anchor.find_previous(["h4", "h5", "h6"])
        report_month = _spanish_month_year(heading.get_text(" ", strip=True) if heading else "")
        if report_month is None:
            parent_text = anchor.parent.get_text(" ", strip=True) if anchor.parent else ""
            report_month = _spanish_month_year(parent_text)
        if report_month is None:
            continue
        seen_urls.add(url)
        candidates.append((report_month, url))

    if fecha_desde is not None:
        candidates = [item for item in candidates if item[0] >= fecha_desde]
    if fecha_hasta is not None:
        candidates = [item for item in candidates if item[0] <= fecha_hasta]
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        raise ValueError("No se localizaron informes PDF del IPC San Luis.")

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Falta la dependencia pypdf. Agregá 'pypdf>=5.0.0' a requirements.txt "
            "y ejecutá nuevamente PROBAR_AQUI.bat."
        ) from exc

    session = requests.Session()
    session.headers.update(_http_browser_headers())
    records = []
    for report_month, pdf_url in candidates[: max(1, int(max_reports))]:
        try:
            pdf_response = session.get(pdf_url, timeout=max(HTTP_TIMEOUT, 45), verify=False)
            pdf_response.raise_for_status()
            reader = PdfReader(BytesIO(pdf_response.content))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            value = _extract_ipc_san_luis_index(text, report_month)
            if value is None:
                print(f"[WARN] IPC San Luis {report_month}: no se detectó el índice Nivel General.")
                continue
            records.append({
                "Fecha": pd.Timestamp(report_month),
                "Valor": float(value),
                "Fuente_URL": pdf_url,
            })
        except Exception as exc:
            print(f"[WARN] IPC San Luis PDF {pdf_url}: {exc}")

    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("Los informes recientes del IPC San Luis no devolvieron valores utilizables.")
    frame = frame.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    if (frame["Valor"] <= 0).any() or (frame["Valor"] > 100_000_000).any():
        raise ValueError("El IPC San Luis contiene valores fuera de un rango razonable.")
    frame["Mes-Año"] = frame["Fecha"].dt.month.map(MAPA_NUM_MESES) + "-" + frame["Fecha"].dt.year.astype(str)
    return frame[["Fecha", "Mes-Año", "Valor", "Fuente_URL"]].reset_index(drop=True)


def _discover_iop_cba_xlsx_url() -> str:
    session = requests.Session()
    session.headers.update(HEADERS_CBA)
    api_url = f"{URL_BASE_CBA}/api/3/action/resource_show"
    try:
        response = session.get(
            api_url,
            params={"id": IOP_CBA_RESOURCE_ID},
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        payload = response.json()
        candidate = str((payload.get("result") or {}).get("url") or "").strip()
        if candidate:
            candidate = urljoin(URL_BASE_CBA, candidate)
            if _is_allowed_cba_url(candidate) and candidate.lower().split("?")[0].endswith(".xlsx"):
                return candidate
    except Exception as exc:
        print(f"[WARN] IOP Córdoba resource_show: {exc}")

    for page_url in (IOP_CBA_RESOURCE_PAGE, IOP_CBA_DATASET_URL):
        try:
            response = session.get(page_url, timeout=HTTP_TIMEOUT, verify=False)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            links = []
            for anchor in soup.find_all("a", href=True):
                candidate = urljoin(URL_BASE_CBA, anchor["href"].strip())
                clean = candidate.lower().split("?")[0]
                if _is_allowed_cba_url(candidate) and clean.endswith(".xlsx"):
                    score = (10 if IOP_CBA_RESOURCE_ID in candidate else 0) + (2 if "/download/" in clean else 0)
                    links.append((score, candidate))
            if links:
                links.sort(key=lambda item: item[0], reverse=True)
                return links[0][1]
        except Exception as exc:
            print(f"[WARN] IOP Córdoba página {page_url}: {exc}")

    return IOP_CBA_FALLBACK_XLSX_URL


def _parse_excel_month(value: Any) -> Optional[pd.Timestamp]:
    numeric = _value_or_none(value)
    if numeric is not None and 20_000 <= numeric <= 80_000:
        parsed = pd.Timestamp("1899-12-30") + pd.to_timedelta(numeric, unit="D")
    else:
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(date(int(parsed.year), int(parsed.month), 1))


def _parse_iop_cba_excel(content: bytes, source_url: str) -> pd.DataFrame:
    raw = pd.read_excel(BytesIO(content), sheet_name=0, header=None)
    header_row = None
    for idx, row in raw.iterrows():
        values = [normalizar_texto(value) for value in row.iloc[:3].tolist()]
        if len(values) >= 2 and values[0] == "orden" and values[1] == "factor":
            header_row = int(idx)
            break
    if header_row is None:
        raise ValueError("No se detectó la fila Orden/Factor del IOP Córdoba.")

    date_columns: List[Tuple[int, pd.Timestamp]] = []
    for col in range(2, raw.shape[1]):
        parsed = _parse_excel_month(raw.iloc[header_row, col])
        if parsed is not None:
            date_columns.append((col, parsed))
    if not date_columns:
        raise ValueError("El IOP Córdoba no contiene columnas mensuales reconocibles.")

    records = []
    for row_idx in range(header_row + 1, raw.shape[0]):
        order_value = _value_or_none(raw.iloc[row_idx, 0])
        if order_value is None:
            continue
        order = str(int(order_value))
        factor = str(raw.iloc[row_idx, 1]).strip()
        for col, month in date_columns:
            value = _value_or_none(raw.iloc[row_idx, col])
            if value is not None:
                records.append({
                    "Fecha": month,
                    "Orden": order,
                    "Factor": factor,
                    "Valor": float(value),
                    "Fuente_URL": source_url,
                })

    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("El IOP Córdoba no devolvió registros utilizables.")
    frame = frame.sort_values(["Fecha", "Orden"]).drop_duplicates(
        subset=["Fecha", "Orden"], keep="last"
    )
    if (frame["Valor"] <= 0).any() or (frame["Valor"] > 100_000_000).any():
        raise ValueError("El IOP Córdoba contiene valores fuera de un rango razonable.")
    return frame.reset_index(drop=True)


def obtener_datos_iop_cba(fecha_desde=None) -> pd.DataFrame:
    source_url = _discover_iop_cba_xlsx_url()
    response = requests.get(
        source_url,
        headers=HEADERS_CBA,
        timeout=HTTP_TIMEOUT,
        verify=False,
    )
    response.raise_for_status()
    frame = _parse_iop_cba_excel(response.content, source_url)
    if fecha_desde is not None:
        frame = frame[frame["Fecha"] >= pd.Timestamp(fecha_desde)].copy()
    return frame.reset_index(drop=True)



# =========================================================
# VGA Córdoba y CVC RAC
# =========================================================
_MESES_ES_ABREV_NUMERO = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


def _parse_month_period(value: Any) -> Optional[date]:
    """Convierte fechas, seriales de Excel y períodos españoles a primer día de mes."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (datetime, date, pd.Timestamp)):
        return date(int(value.year), int(value.month), 1)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            serial = float(value)
            if pd.notna(serial) and 20000 <= serial <= 80000:
                parsed = datetime(1899, 12, 30) + timedelta(days=serial)
                return date(parsed.year, parsed.month, 1)
        except Exception:
            pass

    raw = str(value).strip()
    if not raw:
        return None

    if re.fullmatch(r"\d+(?:[.,]\d+)?", raw):
        serial = _value_or_none(raw)
        if serial is not None and 20000 <= serial <= 80000:
            parsed = datetime(1899, 12, 30) + timedelta(days=float(serial))
            return date(parsed.year, parsed.month, 1)

    normalized = normalizar_texto(raw)

    # Nombres completos: mayo 2026, mayo de 2026.
    named = _spanish_month_year(normalized)
    if named is not None:
        return named

    # Abreviaturas: may-26, abr/2026, ene 25.
    short_match = re.search(
        r"\b(ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic)"
        r"[\s./_-]*(\d{2}|\d{4})\b",
        normalized,
    )
    if short_match:
        year = int(short_match.group(2))
        if year < 100:
            year += 2000
        return date(year, _MESES_ES_ABREV_NUMERO[short_match.group(1)], 1)

    # Prefijos o nombres de archivo: 202605_cuadro..., 2026-05.
    yyyymm = re.search(r"(?<!\d)(20\d{2})[\s./_-]?(0[1-9]|1[0-2])(?!\d)", normalized)
    if yyyymm:
        return date(int(yyyymm.group(1)), int(yyyymm.group(2)), 1)

    mmyyyy = re.search(r"(?<!\d)(0[1-9]|1[0-2])[\s./_-](20\d{2})(?!\d)", normalized)
    if mmyyyy:
        return date(int(mmyyyy.group(2)), int(mmyyyy.group(1)), 1)

    parsed = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return date(int(parsed.year), int(parsed.month), 1)


def _resource_month_hint(*parts: Any) -> Optional[date]:
    combined = " ".join(str(part or "") for part in parts)
    return _parse_month_period(combined)


def _discover_vga_cba_resources() -> List[Dict[str, Any]]:
    """
    Localiza los recursos mensuales del VGA.

    El dataset publica un XLSX y un CSV separados para cada mes. Se consulta
    package_show para no depender del nombre del archivo ni de un resource-id
    mensual que cambia en cada publicación.
    """
    session = requests.Session()
    session.headers.update(HEADERS_CBA)
    candidates: List[Dict[str, Any]] = []

    try:
        response = session.get(
            f"{URL_BASE_CBA}/api/3/action/package_show",
            params={"id": VGA_CBA_PACKAGE_ID},
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        payload = response.json()
        resources = (payload.get("result") or {}).get("resources") or []
        for resource in resources:
            name = str(resource.get("name") or "").strip()
            description = str(resource.get("description") or "").strip()
            raw_url = str(resource.get("url") or "").strip()
            if not raw_url:
                continue
            url = urljoin(URL_BASE_CBA, raw_url)
            if not _is_allowed_cba_url(url):
                continue
            fmt = str(resource.get("format") or "").strip().lower()
            clean = url.lower().split("?")[0]
            extension = "xlsx" if clean.endswith(".xlsx") or "xlsx" in fmt else (
                "csv" if clean.endswith(".csv") or fmt == "csv" else ""
            )
            combined_norm = normalizar_texto(f"{name} {description} {url}")
            if "vga" not in combined_norm or extension not in {"xlsx", "csv"}:
                continue
            month = _resource_month_hint(name, description, url)
            if month is None:
                continue
            candidates.append({
                "Fecha": month,
                "URL": url,
                "Formato": extension,
                "Nombre": name,
            })
    except Exception as exc:
        print(f"[WARN] VGA Córdoba package_show: {exc}")

    if not candidates:
        # Respaldo HTML para el caso excepcional de indisponibilidad de la API CKAN.
        response = session.get(
            VGA_CBA_DATASET_URL,
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for item in soup.select("li.resource-item"):
            item_text = item.get_text(" ", strip=True)
            month = _resource_month_hint(item_text)
            if month is None or "vga" not in normalizar_texto(item_text):
                continue
            for anchor in item.find_all("a", href=True):
                url = urljoin(URL_BASE_CBA, anchor["href"].strip())
                clean = url.lower().split("?")[0]
                extension = "xlsx" if clean.endswith(".xlsx") else (
                    "csv" if clean.endswith(".csv") else ""
                )
                if extension and _is_allowed_cba_url(url):
                    candidates.append({
                        "Fecha": month,
                        "URL": url,
                        "Formato": extension,
                        "Nombre": item_text,
                    })

    if not candidates:
        raise ValueError("No se localizaron recursos mensuales oficiales del VGA Córdoba.")

    # Un recurso por mes: se prefiere XLSX porque conserva la precisión completa.
    best: Dict[date, Dict[str, Any]] = {}
    for item in candidates:
        current = best.get(item["Fecha"])
        item_score = 20 if item["Formato"] == "xlsx" else 10
        if "actualizado" in normalizar_texto(item.get("Nombre")):
            item_score += 2
        current_score = -1
        if current:
            current_score = 20 if current["Formato"] == "xlsx" else 10
            if "actualizado" in normalizar_texto(current.get("Nombre")):
                current_score += 2
        if current is None or item_score > current_score:
            best[item["Fecha"]] = item

    return [best[key] for key in sorted(best)]


def _parse_two_column_month_value_table(
    raw: pd.DataFrame,
    *,
    value_name: str,
    source_url: str,
) -> pd.DataFrame:
    records: List[Dict[str, Any]] = []
    if raw.empty or raw.shape[1] < 2:
        return pd.DataFrame(columns=["Fecha", value_name, "Fuente_URL"])

    for _, row in raw.iterrows():
        month = _parse_month_period(row.iloc[0])
        value = _value_or_none(row.iloc[1])
        if month is None or value is None:
            continue
        records.append({
            "Fecha": pd.Timestamp(month),
            value_name: float(value),
            "Fuente_URL": source_url,
        })

    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=["Fecha", value_name, "Fuente_URL"])
    return (
        frame.sort_values("Fecha")
        .drop_duplicates(subset=["Fecha"], keep="last")
        .reset_index(drop=True)
    )


def _parse_vga_cba_content(
    content: bytes,
    *,
    source_url: str,
    file_format: str,
) -> pd.DataFrame:
    if not content:
        raise ValueError("El recurso VGA Córdoba está vacío.")

    if file_format == "xlsx":
        excel = pd.ExcelFile(BytesIO(content))
        frames = [
            pd.read_excel(excel, sheet_name=sheet, header=None)
            for sheet in excel.sheet_names
        ]
    else:
        decoded = None
        for encoding in ("utf-8-sig", "latin1", "cp1252"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ValueError("No se pudo decodificar el CSV del VGA Córdoba.")
        frames = [pd.read_csv(StringIO(decoded), sep=";", header=None, engine="python")]

    parsed_frames = [
        _parse_two_column_month_value_table(
            frame,
            value_name="Valor",
            source_url=source_url,
        )
        for frame in frames
    ]
    parsed_frames = [frame for frame in parsed_frames if not frame.empty]
    if not parsed_frames:
        raise ValueError("El recurso VGA Córdoba no contiene fecha y valor utilizables.")

    result = pd.concat(parsed_frames, ignore_index=True)
    result = result.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    if (result["Valor"] <= 0).any() or (result["Valor"] > 10_000_000).any():
        raise ValueError("El VGA Córdoba contiene valores fuera de un rango razonable.")
    return result.reset_index(drop=True)


def obtener_datos_vga_cba(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    max_resources: int = 18,
) -> pd.DataFrame:
    resources = _discover_vga_cba_resources()
    if fecha_desde is not None:
        resources = [item for item in resources if item["Fecha"] >= fecha_desde]
    if fecha_hasta is not None:
        resources = [item for item in resources if item["Fecha"] <= fecha_hasta]
    if max_resources > 0:
        resources = resources[-int(max_resources):]
    if not resources:
        raise ValueError("No existen recursos VGA Córdoba para el rango solicitado.")

    session = requests.Session()
    session.headers.update(HEADERS_CBA)
    frames: List[pd.DataFrame] = []
    errors: List[str] = []

    for item in resources:
        try:
            response = session.get(
                item["URL"],
                timeout=max(HTTP_TIMEOUT, 45),
                verify=False,
            )
            response.raise_for_status()
            parsed = _parse_vga_cba_content(
                response.content,
                source_url=item["URL"],
                file_format=item["Formato"],
            )
            frames.append(parsed)
        except Exception as exc:
            errors.append(f"{item['Fecha']}: {exc}")

    if not frames:
        raise ValueError(
            "Los recursos VGA Córdoba no devolvieron valores utilizables. "
            + (" | ".join(errors[:5]) if errors else "")
        )

    frame = pd.concat(frames, ignore_index=True)
    frame = frame.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    frame["Mes-Año"] = (
        frame["Fecha"].dt.month.map(MAPA_NUM_MESES)
        + "-"
        + frame["Fecha"].dt.year.astype(str)
    )
    return frame[["Fecha", "Mes-Año", "Valor", "Fuente_URL"]].reset_index(drop=True)


def _resolve_cvc_rac_resource_url(resource_id: str, fallback_url: str) -> str:
    session = requests.Session()
    session.headers.update(HEADERS_CBA)
    try:
        response = session.get(
            f"{URL_BASE_CBA}/api/3/action/resource_show",
            params={"id": resource_id},
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        payload = response.json()
        candidate = str((payload.get("result") or {}).get("url") or "").strip()
        if candidate:
            candidate = urljoin(URL_BASE_CBA, candidate)
            if _is_allowed_cba_url(candidate):
                return candidate
    except Exception as exc:
        print(f"[WARN] CVC RAC resource_show {resource_id}: {exc}")

    if fallback_url and _is_allowed_cba_url(fallback_url):
        return fallback_url
    raise ValueError(f"No se pudo resolver el recurso oficial CVC RAC {resource_id}.")


def _parse_cvc_rac_content(
    content: bytes,
    *,
    source_url: str,
    file_format: str,
) -> pd.DataFrame:
    if not content:
        raise ValueError("El recurso CVC RAC está vacío.")

    if file_format == "xlsx":
        excel = pd.ExcelFile(BytesIO(content))
        frames = [
            pd.read_excel(excel, sheet_name=sheet, header=None)
            for sheet in excel.sheet_names
        ]
    else:
        decoded = None
        for encoding in ("utf-8-sig", "latin1", "cp1252"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ValueError("No se pudo decodificar el CSV CVC RAC.")
        frames = [pd.read_csv(StringIO(decoded), sep=";", header=None, engine="python")]

    parsed_frames = [
        _parse_two_column_month_value_table(
            frame,
            value_name="CVC",
            source_url=source_url,
        )
        for frame in frames
    ]
    parsed_frames = [frame for frame in parsed_frames if not frame.empty]
    if not parsed_frames:
        raise ValueError("El recurso CVC RAC no contiene períodos y coeficientes utilizables.")

    result = pd.concat(parsed_frames, ignore_index=True)
    result = result.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    if (result["CVC"] < -100).any() or (result["CVC"] > 1_000).any():
        raise ValueError("El CVC RAC contiene valores fuera de un rango razonable.")
    return result.reset_index(drop=True)


def obtener_datos_cvc_rac(fecha_desde: Optional[date] = None) -> pd.DataFrame:
    attempts = [
        ("xlsx", CVC_RAC_XLSX_RESOURCE_ID, CVC_RAC_FALLBACK_XLSX_URL),
        ("csv", CVC_RAC_CSV_RESOURCE_ID, CVC_RAC_FALLBACK_CSV_URL),
    ]
    errors: List[str] = []
    session = requests.Session()
    session.headers.update(HEADERS_CBA)

    for file_format, resource_id, fallback_url in attempts:
        try:
            source_url = _resolve_cvc_rac_resource_url(resource_id, fallback_url)
            response = session.get(
                source_url,
                timeout=max(HTTP_TIMEOUT, 45),
                verify=False,
            )
            response.raise_for_status()
            frame = _parse_cvc_rac_content(
                response.content,
                source_url=source_url,
                file_format=file_format,
            )
            if fecha_desde is not None:
                frame = frame[frame["Fecha"] >= pd.Timestamp(fecha_desde)].copy()
            if frame.empty:
                raise ValueError("No hay datos CVC RAC para el rango solicitado.")
            frame["Mes-Año"] = (
                frame["Fecha"].dt.month.map(MAPA_NUM_MESES)
                + "-"
                + frame["Fecha"].dt.year.astype(str)
            )
            return frame[["Fecha", "Mes-Año", "CVC", "Fuente_URL"]].reset_index(drop=True)
        except Exception as exc:
            errors.append(f"{file_format}: {exc}")

    raise RuntimeError("No se pudo obtener el CVC RAC. " + " | ".join(errors))


def _discover_fam_epec_resources() -> List[Dict[str, Any]]:
    """Descubre los recursos oficiales FAM EPEC sin fijar el nombre del archivo."""
    session = requests.Session()
    session.headers.update(HEADERS_CBA)
    candidates: List[Dict[str, Any]] = []

    try:
        response = session.get(
            f"{URL_BASE_CBA}/api/3/action/package_show",
            params={"id": FAM_EPEC_PACKAGE_ID},
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        payload = response.json()
        resources = (payload.get("result") or {}).get("resources") or []
        for resource in resources:
            raw_url = str(resource.get("url") or "").strip()
            if not raw_url:
                continue
            url = urljoin(URL_BASE_CBA, raw_url)
            if not _is_allowed_cba_url(url):
                continue

            name = str(resource.get("name") or "").strip()
            description = str(resource.get("description") or "").strip()
            fmt = str(resource.get("format") or "").strip().lower()
            resource_id = str(resource.get("id") or "").strip()
            clean = url.lower().split("?")[0]
            extension = "xlsx" if clean.endswith(".xlsx") or "xlsx" in fmt else (
                "csv" if clean.endswith(".csv") or fmt == "csv" else ""
            )
            normalized = normalizar_texto(f"{name} {description} {url}")
            if extension not in {"xlsx", "csv"} or "fam" not in normalized or "epec" not in normalized:
                continue

            year_hint = None
            year_match = re.search(r"\b(20\d{2})\b", f"{name} {description} {url}")
            if year_match:
                year_hint = int(year_match.group(1))

            candidates.append({
                "URL": url,
                "Formato": extension,
                "Nombre": name,
                "Resource_ID": resource_id,
                "Anio": year_hint,
            })
    except Exception as exc:
        print(f"[WARN] FAM EPEC package_show: {exc}")

    if not candidates:
        # Respaldo por resource_show: los IDs son estables aunque cambie el nombre mensual.
        for resource_id, extension in (
            (FAM_EPEC_XLSX_RESOURCE_ID, "xlsx"),
            (FAM_EPEC_CSV_RESOURCE_ID, "csv"),
        ):
            try:
                response = session.get(
                    f"{URL_BASE_CBA}/api/3/action/resource_show",
                    params={"id": resource_id},
                    timeout=HTTP_TIMEOUT,
                    verify=False,
                )
                response.raise_for_status()
                result = response.json().get("result") or {}
                raw_url = str(result.get("url") or "").strip()
                if not raw_url:
                    continue
                url = urljoin(URL_BASE_CBA, raw_url)
                if not _is_allowed_cba_url(url):
                    continue
                candidates.append({
                    "URL": url,
                    "Formato": extension,
                    "Nombre": str(result.get("name") or f"FAM EPEC {extension}"),
                    "Resource_ID": resource_id,
                    "Anio": None,
                })
            except Exception as exc:
                print(f"[WARN] FAM EPEC resource_show {resource_id}: {exc}")

    if not candidates:
        # Último respaldo: enlaces publicados en la página del dataset.
        response = session.get(
            FAM_EPEC_DATASET_URL,
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            url = urljoin(URL_BASE_CBA, anchor["href"].strip())
            clean = url.lower().split("?")[0]
            extension = "xlsx" if clean.endswith(".xlsx") else (
                "csv" if clean.endswith(".csv") else ""
            )
            normalized = normalizar_texto(f"{anchor.get_text(' ', strip=True)} {url}")
            if extension in {"xlsx", "csv"} and "fam" in normalized and _is_allowed_cba_url(url):
                candidates.append({
                    "URL": url,
                    "Formato": extension,
                    "Nombre": anchor.get_text(" ", strip=True),
                    "Resource_ID": "",
                    "Anio": None,
                })

    # Evita duplicados y prioriza XLSX sobre CSV para el mismo recurso/año.
    unique: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        key = item.get("Resource_ID") or item["URL"].split("?")[0]
        unique[key] = item

    ordered = list(unique.values())
    ordered.sort(
        key=lambda item: (
            item.get("Anio") or 0,
            1 if item.get("Formato") == "xlsx" else 0,
        )
    )
    return ordered


def _parse_fam_epec_content(
    content: bytes,
    *,
    source_url: str,
    file_format: str,
) -> pd.DataFrame:
    if not content:
        raise ValueError("El recurso FAM EPEC está vacío.")

    if file_format == "xlsx":
        excel = pd.ExcelFile(BytesIO(content))
        raw_frames = [
            pd.read_excel(excel, sheet_name=sheet, header=None)
            for sheet in excel.sheet_names
        ]
    else:
        decoded = None
        for encoding in ("utf-8-sig", "latin1", "cp1252"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ValueError("No se pudo decodificar el CSV FAM EPEC.")
        raw_frames = [
            pd.read_csv(StringIO(decoded), sep=";", header=None, engine="python")
        ]

    parsed = [
        _parse_two_column_month_value_table(
            frame,
            value_name="FAM",
            source_url=source_url,
        )
        for frame in raw_frames
    ]
    parsed = [frame for frame in parsed if not frame.empty]
    if not parsed:
        raise ValueError("El recurso FAM EPEC no contiene períodos y valores utilizables.")

    result = pd.concat(parsed, ignore_index=True)
    result = result.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    # La publicación utiliza valores próximos a 1 (por ejemplo, 1,035...).
    # En la hoja esos valores se aplican como porcentaje: índice anterior*(1+FAM/100).
    if (result["FAM"] < -100).any() or (result["FAM"] > 100).any():
        raise ValueError("El FAM EPEC contiene valores fuera de un rango razonable.")
    return result.reset_index(drop=True)


def obtener_datos_fam_epec(
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> pd.DataFrame:
    resources = _discover_fam_epec_resources()
    if not resources:
        raise ValueError("No se encontraron recursos oficiales FAM EPEC.")

    session = requests.Session()
    session.headers.update(HEADERS_CBA)
    frames: List[pd.DataFrame] = []
    errors: List[str] = []

    # Intenta todos los recursos. Esto permite unir años distintos si CKAN
    # publica FAM_EPEC_2027, FAM_EPEC_2028, etc.
    for item in resources:
        try:
            response = session.get(
                item["URL"],
                timeout=max(HTTP_TIMEOUT, 45),
                verify=False,
            )
            response.raise_for_status()
            frame = _parse_fam_epec_content(
                response.content,
                source_url=item["URL"],
                file_format=item["Formato"],
            )
            frames.append(frame)
        except Exception as exc:
            errors.append(f"{item.get('Nombre') or item.get('URL')}: {exc}")

    if not frames:
        raise RuntimeError(
            "No se pudo obtener el FAM EPEC. "
            + (" | ".join(errors[:6]) if errors else "")
        )

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values("Fecha").drop_duplicates(subset=["Fecha"], keep="last")
    if fecha_desde is not None:
        result = result[result["Fecha"] >= pd.Timestamp(fecha_desde)].copy()
    if fecha_hasta is not None:
        result = result[result["Fecha"] <= pd.Timestamp(fecha_hasta)].copy()
    if result.empty:
        raise ValueError("No hay datos FAM EPEC para el rango solicitado.")

    result["Mes-Año"] = (
        result["Fecha"].dt.month.map(MAPA_NUM_MESES)
        + "-"
        + result["Fecha"].dt.year.astype(str)
    )
    return result[["Fecha", "Mes-Año", "FAM", "Fuente_URL"]].reset_index(drop=True)

# =========================================================
# Google Sheets: escritura automática
# =========================================================
def _get_gspread_client() -> gspread.Client:
    raw = os.getenv(GOOGLE_CREDENTIALS_JSON_ENV, "").strip()
    credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()

    if raw:
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{GOOGLE_CREDENTIALS_JSON_ENV} no contiene un JSON válido.") from exc
    elif credentials_file:
        path = Path(credentials_file).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        if not path.exists():
            raise RuntimeError(f"No se encontró GOOGLE_CREDENTIALS_FILE: {path}")
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"No se pudo leer la credencial de Google: {path}") from exc
    else:
        raise RuntimeError(
            "Falta GOOGLE_CREDENTIALS_JSON o GOOGLE_CREDENTIALS_FILE. "
            "Para pruebas locales se recomienda GOOGLE_CREDENTIALS_FILE."
        )

    if "private_key" in info:
        info["private_key"] = info["private_key"].replace("\\n", "\n")
    scopes = (
        ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]
        if PUBLIC_READ_ONLY
        else ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def _get_worksheet() -> gspread.Worksheet:
    """Abre siempre el documento nuevo y resuelve la pestaña por nombre o por gid."""
    client = _get_gspread_client()
    try:
        spreadsheet = client.open_by_key(FILE_ID)
    except Exception as exc:
        raise RuntimeError(
            "No se pudo abrir el Google Sheets configurado. "
            f"Verificá GSHEET_ID={FILE_ID} y que la cuenta de servicio tenga acceso. "
            f"Detalle: {exc}"
        ) from exc

    try:
        return spreadsheet.worksheet(GSHEET_WORKSHEET_NAME)
    except Exception as name_exc:
        if GSHEET_GID:
            try:
                return spreadsheet.get_worksheet_by_id(int(GSHEET_GID))
            except Exception:
                pass
        try:
            available = ", ".join(ws.title for ws in spreadsheet.worksheets())
        except Exception:
            available = "no disponible"
        raise RuntimeError(
            f"No se encontró la pestaña '{GSHEET_WORKSHEET_NAME}' ni el gid {GSHEET_GID}. "
            f"Pestañas disponibles: {available}. Detalle: {name_exc}"
        ) from name_exc


def _header_index(headers: List[str], required_terms: List[str], excluded_terms: Optional[List[str]] = None) -> Optional[int]:
    required = [normalizar_texto(t) for t in required_terms]
    excluded = [normalizar_texto(t) for t in (excluded_terms or [])]
    for idx, header in enumerate(headers, start=1):
        h = normalizar_texto(header)
        if not h:
            continue
        if all(term in h for term in required) and not any(term in h for term in excluded):
            return idx
    return None


def _headers_to_col_map(headers: List[str]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for i, header in enumerate(headers, start=1):
        raw = str(header).strip()
        if raw:
            result[raw] = i
            result.setdefault(normalizar_texto(raw), i)
    return result


def _find_header_column(headers: List[str], expected: str) -> Optional[int]:
    col_map = _headers_to_col_map(headers)
    return col_map.get(expected) or col_map.get(normalizar_texto(expected))


def _ensure_month_rows(ws: gspread.Worksheet, months: List[date], total_cols: int) -> Dict[date, int]:
    col_values = ws.col_values(1)
    existing: Dict[date, int] = {}
    for row_num, value in enumerate(col_values, start=1):
        parsed = _parse_sheet_date(value)
        if parsed:
            existing[parsed] = row_num

    missing_months = [m for m in months if m not in existing]
    if missing_months:
        rows = [[_format_sheet_date(m)] + [""] * (max(total_cols, 1) - 1) for m in missing_months]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        col_values = ws.col_values(1)
        existing = {}
        for row_num, value in enumerate(col_values, start=1):
            parsed = _parse_sheet_date(value)
            if parsed:
                existing[parsed] = row_num

    return {m: existing[m] for m in months if m in existing}


def _df_long_to_month_values(
    df: pd.DataFrame,
    months: List[date],
    key_col: str,
    value_col: str,
) -> Dict[str, Dict[date, float]]:
    wanted = set(months)
    out: Dict[str, Dict[date, float]] = {}
    work = df.copy()
    work["__month__"] = work["Fecha"].apply(_month_start)
    work = work[work["__month__"].isin(wanted)].copy()
    for _, row in work.iterrows():
        key = str(row.get(key_col, "")).strip()
        month = row.get("__month__")
        val = _value_or_none(row.get(value_col))
        if key and month and val is not None:
            out.setdefault(key, {})[month] = val
    return out


def _add_series_to_updates(
    *,
    module: str,
    series_by_key: Dict[str, Dict[date, float]],
    key_to_header: Dict[str, str],
    headers: List[str],
    months: List[date],
    updates: Dict[Tuple[date, int], Any],
    faltantes: List[Dict[str, Any]],
) -> int:
    managed = 0
    for key, header in key_to_header.items():
        col = _find_header_column(headers, header)
        if not col:
            faltantes.append({
                "tipo": "configuracion",
                "modulo": module,
                "indice": header,
                "mes": None,
                "motivo": "No se encontró el encabezado en la hoja.",
            })
            continue
        managed += 1
        values = series_by_key.get(key, {})
        for month in months:
            if month in values:
                updates[(month, col)] = values[month]
            else:
                # Nunca se escribe una cadena vacía: una publicación pendiente no debe borrar un dato existente.
                faltantes.append({
                    "tipo": "pendiente_publicacion",
                    "modulo": module,
                    "indice": header,
                    "mes": _format_sheet_date(month),
                    "motivo": "Dato todavía no publicado o no disponible en la fuente oficial.",
                })
    return managed


def _extract_cba_code_from_header(header: str) -> Optional[str]:
    m = re.search(r"\b(\d{5,6})\b", str(header))
    return m.group(1) if m else None


def _match_ipc_cba_value(header: str, month_df: pd.DataFrame) -> Optional[float]:
    if month_df.empty:
        return None
    h_norm = normalizar_texto(header)
    h_clean = h_norm.replace("ipc cordoba", "").strip()
    h_clean = re.sub(r"\b\d{5,6}\b", "", h_clean).strip()
    h_clean = re.sub(r"base\s*=?.*", "", h_clean).strip()

    code = _extract_cba_code_from_header(header)
    if code:
        by_code = month_df[month_df["_codigo_norm"].str.contains(code, na=False)]
        if not by_code.empty:
            return _value_or_none(by_code.iloc[0]["Indice"])

    aliases = []
    if "nivel general" in h_norm:
        aliases = [("empalme", "nivel general"), ("coicop", "nivel general")]
    elif "estacionales" in h_norm:
        aliases = [("estac_regulados", "estacionales"), ("estac_regulados", "estacional")]
    elif "regulados" in h_norm:
        aliases = [("estac_regulados", "regulados"), ("estac_regulados", "regulado")]
    elif "resto ipc" in h_norm or "nucleo" in h_norm:
        aliases = [("estac_regulados", "resto ipc"), ("estac_regulados", "nucleo")]
    elif "bienes" in h_norm and "servicios" not in h_norm:
        aliases = [("bienes_servicios", "bienes")]
    elif "servicios" in h_norm and "financieros" not in h_norm and "telefonico" not in h_norm:
        aliases = [("bienes_servicios", "servicios")]

    for fuente, desc in aliases:
        f_norm = normalizar_texto(fuente)
        d_norm = normalizar_texto(desc)
        sub = month_df[(month_df["Fuente"].apply(normalizar_texto) == f_norm) & (month_df["_desc_norm"].str.contains(d_norm, na=False))]
        if not sub.empty:
            return _value_or_none(sub.iloc[0]["Indice"])

    # Coincidencia semántica laxa para códigos COICOP del Sheet.
    words = [w for w in re.split(r"\s+", h_clean) if len(w) >= 4 and w not in {"cordoba", "base", "serie", "estimado", "servicios"}]
    if words:
        scored = []
        for _, row in month_df.iterrows():
            desc = str(row.get("_desc_norm", ""))
            score = sum(1 for w in words if w in desc)
            if score:
                scored.append((score, row))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return _value_or_none(scored[0][1]["Indice"])
    return None


def _formula_growth_marker(rate: float, mode: str) -> dict:
    """Marca un dato para escribirlo como fórmula encadenada en Google Sheets."""
    return {
        "__formula_growth__": True,
        "rate": float(rate),
        "mode": str(mode),
    }


def _formula_ratio_adjacent_marker(offset: int = 1) -> dict:
    """
    Marca una celda para calcularla a partir de la variación relativa de una
    columna adyacente.

    Con ``offset=1`` y una celda objetivo A2, la fórmula resultante es:
        =A1*(B2/B1)
    """
    return {
        "__formula_ratio_adjacent__": True,
        "offset": int(offset),
    }


def _formula_moving_average_marker(source_col: int, window: int = 13) -> dict:
    """Marca una celda para escribir un promedio móvil sobre otra columna."""
    return {
        "__formula_moving_average__": True,
        "source_col": int(source_col),
        "window": int(window),
    }



def _formula_cvc_factor_marker(rate_col: int) -> dict:
    """Marca la fórmula 100 * (1 + CVC/100)."""
    return {
        "__formula_cvc_factor__": True,
        "rate_col": int(rate_col),
    }


def _formula_cvc_index_marker(rate_col: int) -> dict:
    """Marca el índice encadenado: índice anterior * (1 + CVC/100)."""
    return {
        "__formula_cvc_index__": True,
        "rate_col": int(rate_col),
    }


def _formula_fam_index_marker(rate_col: int) -> dict:
    """Marca el Índice FAM: índice anterior * (1 + FAM/100)."""
    return {
        "__formula_fam_index__": True,
        "rate_col": int(rate_col),
    }

def _formula_decimal_argentina(rate: float) -> str:
    """Devuelve el número con coma decimal, por ejemplo 0.02 -> 0,02."""
    text = format(float(rate), ".15g")
    return text.replace(".", ",")


def _render_sheet_update(value, row: int, col: int):
    """
    Convierte marcadores internos en fórmulas encadenadas de Google Sheets.

    Modos admitidos:
    - ICC INDEC: valor anterior multiplicado por su variación.
    - Relación adyacente: valor anterior multiplicado por el cociente entre
      el índice adyacente actual y el índice adyacente anterior.

    IPC Córdoba ya no utiliza este mecanismo: desde la nueva base se escribe
    el número índice oficial directamente.
    """
    if not isinstance(value, dict):
        return value

    if value.get("__formula_ratio_adjacent__") is True:
        if row <= 2:
            raise RuntimeError(
                "No se puede construir la fórmula de empalme porque no existe "
                "una fila anterior con un valor base."
            )

        offset = int(value.get("offset", 1))
        reference_col = col + offset
        if reference_col <= 0:
            raise RuntimeError("La columna de referencia de la fórmula no es válida.")

        previous_target_cell = rowcol_to_a1(row - 1, col)
        current_reference_cell = rowcol_to_a1(row, reference_col)
        previous_reference_cell = rowcol_to_a1(row - 1, reference_col)

        return (
            f"={previous_target_cell}*"
            f"({current_reference_cell}/{previous_reference_cell})"
        )

    if value.get("__formula_moving_average__") is True:
        source_col = int(value.get("source_col", 0))
        window = int(value.get("window", 13))
        if source_col <= 0 or window <= 0:
            raise RuntimeError("Configuración inválida para la media móvil ICC Córdoba.")
        start_row = row - window + 1
        if start_row <= 1:
            raise RuntimeError(
                "No hay suficientes filas anteriores para calcular la media móvil ICC Córdoba."
            )
        start_cell = rowcol_to_a1(start_row, source_col)
        end_cell = rowcol_to_a1(row, source_col)
        return f"=AVERAGE({start_cell}:{end_cell})"


    if value.get("__formula_cvc_factor__") is True:
        rate_col = int(value.get("rate_col", 0))
        if rate_col <= 0:
            raise RuntimeError("No se configuró la columna del coeficiente CVC RAC.")
        rate_cell = rowcol_to_a1(row, rate_col)
        return f"=100*(1+{rate_cell}%)"

    if value.get("__formula_cvc_index__") is True:
        rate_col = int(value.get("rate_col", 0))
        if rate_col <= 0:
            raise RuntimeError("No se configuró la columna del coeficiente CVC RAC.")
        if row <= 2:
            raise RuntimeError(
                "No existe una fila anterior para encadenar el Índice RAC."
            )
        previous_index_cell = rowcol_to_a1(row - 1, col)
        rate_cell = rowcol_to_a1(row, rate_col)
        return f"={previous_index_cell}*(1+{rate_cell}%)"

    if value.get("__formula_fam_index__") is True:
        rate_col = int(value.get("rate_col", 0))
        if rate_col <= 0:
            raise RuntimeError("No se configuró la columna FAM de EPEC.")
        if row <= 2:
            raise RuntimeError(
                "No existe una fila anterior para encadenar el Índice FAM de EPEC."
            )
        previous_index_cell = rowcol_to_a1(row - 1, col)
        rate_cell = rowcol_to_a1(row, rate_col)
        return f"={previous_index_cell}*(1+{rate_cell}/100)"

    if value.get("__formula_growth__") is not True:
        return value

    if row <= 2:
        raise RuntimeError(
            "No se puede construir la fórmula porque no existe una fila "
            "anterior con un índice base."
        )

    previous_cell = rowcol_to_a1(row - 1, col)
    rate_text = _formula_decimal_argentina(value["rate"])
    mode = value.get("mode")

    if mode == "icc":
        return f"={previous_cell}*(1+{rate_text}/100)"

    if mode == "ipc_cordoba":
        raise RuntimeError(
            "IPC Córdoba ya no admite fórmulas por variación; debe escribirse "
            "el número índice oficial de la nueva base como valor directo."
        )

    raise RuntimeError(f"Modo de fórmula desconocido: {mode}")


def _scrape_ipcn_to_updates(headers, months, updates, faltantes) -> int:
    mapping = {
        "Nivel General": "IPC INDEC Nivel General Base 100 = dic 2016",
        "Estacional": "IPC INDEC  Estacional Base = 100 en dic 2016",
        "Núcleo": "IPC INDEC Núcleo Base = 100 en dic 2016",
        "Regulados": "IPC INDEC Regulados Base = 100 en dic 2016",
        "Bienes": "IPC INDEC Bienes Base = 100 en dic 2016",
        "Servicios": "IPC INDEC Servicios Base = 100 en dic 2016",
    }
    series = _df_long_to_month_values(obtener_datos_ipcn(), months, "Codigo", "Indice_IPC")
    return _add_series_to_updates(module="IPC INDEC", series_by_key=series, key_to_header=mapping, headers=headers, months=months, updates=updates, faltantes=faltantes)


EMPALME_IPC_INDEC_HEADER = (
    "EMPALME IPC INDEC pre2006 + San Luis + IPC GBA + INDEC 2017"
)
EMPALME_IPC_INDEC_REFERENCE_HEADER = (
    "IPC INDEC Nivel General Base 100 = dic 2016"
)


def _add_empalme_ipc_indec_updates(headers, months, updates, faltantes) -> int:
    """
    Repite la fórmula del empalme cuando se actualiza el IPC INDEC Nivel
    General del mismo mes.

    Si el empalme está en B y el IPC INDEC Nivel General en C, escribe:
        B_fila = B_fila_anterior * (C_fila / C_fila_anterior)

    Solo genera la fórmula para meses cuyo valor de referencia haya sido
    incorporado a ``updates``. Así se evita reemplazar una celda por una
    fórmula que apunte a un mes todavía no publicado por INDEC.
    """
    col_map = _headers_to_col_map(headers)
    target_col = (
        col_map.get(EMPALME_IPC_INDEC_HEADER)
        or col_map.get(normalizar_texto(EMPALME_IPC_INDEC_HEADER))
    )
    reference_col = (
        col_map.get(EMPALME_IPC_INDEC_REFERENCE_HEADER)
        or col_map.get(normalizar_texto(EMPALME_IPC_INDEC_REFERENCE_HEADER))
    )

    if not target_col:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "Empalme IPC INDEC",
            "indice": EMPALME_IPC_INDEC_HEADER,
            "mes": None,
            "motivo": "No se encontró el encabezado de la columna de empalme.",
        })
        return 0

    if not reference_col:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "Empalme IPC INDEC",
            "indice": EMPALME_IPC_INDEC_REFERENCE_HEADER,
            "mes": None,
            "motivo": "No se encontró la columna IPC INDEC Nivel General de referencia.",
        })
        return 0

    offset = reference_col - target_col
    if offset == 0:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "Empalme IPC INDEC",
            "indice": EMPALME_IPC_INDEC_HEADER,
            "mes": None,
            "motivo": "La columna objetivo y la columna de referencia coinciden.",
        })
        return 0

    formulas_added = 0
    for month in months:
        # El IPC INDEC Nivel General se carga en esta misma ejecución.
        if (month, reference_col) not in updates:
            continue

        updates[(month, target_col)] = _formula_ratio_adjacent_marker(
            offset=offset,
        )
        formulas_added += 1

    return 1 if formulas_added else 0


def _scrape_icc_to_updates(headers, months, updates, faltantes) -> int:
    """
    ICC INDEC publica variaciones porcentuales mensuales.
    Ejemplo: 2.9 representa 2,9 %, por lo que se divide por 100.
    """
    mapping = {
        "Nivel general": "ICC INDEC Nivel general - Base 1993 - 100",
        "Materiales": "ICC INDEC Materiales - Base 1993 - 100",
        "Mano de obra (1)": "ICC INDEC Mano de Obra - Base 1993 - 100",
        "Gastos generales": "ICC INDEC Gastos Generales - Base 1993 - 100",
    }

    series = _df_long_to_month_values(
        obtener_datos_icc(),
        months,
        "Descripción",
        "Valor",
    )
    col_map = _headers_to_col_map(headers)
    managed = 0

    for key, header in mapping.items():
        col = col_map.get(header) or col_map.get(normalizar_texto(header))

        if not col:
            faltantes.append({
                "tipo": "configuracion",
                "modulo": "ICC INDEC",
                "indice": header,
                "mes": None,
                "motivo": "No se encontró el encabezado en la hoja.",
            })
            continue

        managed += 1
        values = series.get(key, {})

        for month in months:
            rate = _value_or_none(values.get(month))

            if rate is None:
                faltantes.append({
                    "tipo": "pendiente_publicacion",
                    "modulo": "ICC INDEC",
                    "indice": header,
                    "mes": _format_sheet_date(month),
                    "motivo": "Variación todavía no publicada; la celda existente no fue modificada.",
                })
                continue

            updates[(month, col)] = _formula_growth_marker(
                rate,
                mode="icc",
            )

    return managed

def _scrape_ipim_to_updates(headers, months, updates, faltantes) -> int:
    mapping = {
        "Nivel general": "IPIM NG (Nivel general) - Base Diciembre - 2015",
        "Productos nacionales": "IPIM N (Productos Nacionales) - Base Diciembre - 2015",
        "Productos manufacturados": "IPIM D (Productos Manufacturados) - Base Diciembre - 2015",
        "Madera y productos de madera excepto muebles": "IPIM 20 (Madera y productos de madera excepto muebles) - Base Diciembre - 2015",
        "Productos refinados del petróleo": "IPIM 23 (Productos Refinados del Petróleo) - Base Diciembre - 2015",
        "Sustancias y productos químicos": "IPIM 24 (Sustancias y Productos Químicos) - Base Diciembre - 2015",
        "Jabones y detergentes": "IPIM 2424 (Jabones y detergentes) - Base Diciembre - 2015",
        "Productos de minerales no metálicos": "IPIM 26 (Productos de minerales no metálicos) - Base Diciembre - 2015",
        "Máquinas y equipos": "IPIM 29 (Máquinas y Equipos) - Base Diciembre - 2015",
        "Máquinas y aparatos eléctricos": "IPIM 31 (Máquinas y Aparatos Eléctricos) - Base Diciembre - 2015",
        "Equipos para medicina e instrumentos de medición": "IPIM 33 (Equipos para medicina e instrumentos de medición) - Base Diciembre - 2015",
        "Instrumentos de medición de servicios domiciliarios": "IPIM 3312 (Instrumentos de medición Servicios Domiciliarios) - Base Diciembre - 2015",
        "Vehículos automotores, carrocerías y repuestos": "IPIM 34 (Vehículos Automotores - Carrocerías y Repuestos) - Base Diciembre - 2015",
        "Energía eléctrica": "IPIM E (Energía Eléctrica) - Base Diciembre - 2015",
        "Productos importados": "IPIM I (Productos Importados) - Base Diciembre - 2015",
    }
    series = _df_long_to_month_values(obtener_datos_ipim(), months, "Descripción", "Valor")
    return _add_series_to_updates(module="IPIM INDEC", series_by_key=series, key_to_header=mapping, headers=headers, months=months, updates=updates, faltantes=faltantes)


SALARIOS_SHEET_HEADERS = {
    "Sector privado registrado": "Índice de salarios Sector Privado Registrado - Base Octubre 2016 -",
    "Sector público": "Índice de salarios Sector Público Registrado - Base Octubre 2016",
    "Total registrado": "Índice de salarios Total Registrado - Base Octubre 2016",
    "Sector privado no registrado": "Índice de salarios Sector Privado NO Registrado - Base Octubre 2016",
    "Total índice de salarios": "Índice de salarios Total - Base Octubre 2016",
}


def _scrape_salarios_to_updates(headers, months, updates, faltantes) -> int:
    frame = obtener_datos_salarios()
    series = _df_long_to_month_values(frame, months, "Serie", "Valor")
    return _add_series_to_updates(
        module="Índice de salarios INDEC",
        series_by_key=series,
        key_to_header=SALARIOS_SHEET_HEADERS,
        headers=headers,
        months=months,
        updates=updates,
        faltantes=faltantes,
    )


def _scrape_bcra_monthly_average_to_updates(
    *,
    module: str,
    loader,
    value_column: str,
    header_terms: List[str],
    excluded_terms: Optional[List[str]],
    headers: List[str],
    months: List[date],
    updates: Dict[Tuple[date, int], Any],
    faltantes: List[Dict[str, Any]],
    require_calendar_complete: bool = False,
) -> int:
    """Carga promedios mensuales de una serie diaria del BCRA.

    No usa un divisor fijo. El promedio se calcula con las observaciones
    realmente publicadas. Para CER e ICL, además, se exige que un mes cerrado
    contenga todos sus días calendario antes de escribirlo.
    """
    col = _header_index(headers, header_terms, excluded_terms)
    if not col:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": module,
            "indice": " / ".join(header_terms),
            "mes": None,
            "motivo": "No se encontró el encabezado correspondiente en la hoja.",
        })
        return 0

    first_day = min(months) if months else None
    last_month = max(months) if months else None
    last_day = None
    if last_month:
        last_day = date(
            last_month.year,
            last_month.month,
            calendar.monthrange(last_month.year, last_month.month)[1],
        )
    frame = loader(fecha_desde=first_day, fecha_hasta=last_day)
    frame = frame.copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)

    grouped = frame.dropna(subset=["__month__"]).groupby("__month__").agg(
        promedio=(value_column, "mean"),
        observaciones=(value_column, "count"),
    )

    for month in months:
        if month not in grouped.index:
            faltantes.append({
                "tipo": "pendiente_publicacion",
                "modulo": module,
                "indice": headers[col - 1],
                "mes": _format_sheet_date(month),
                "motivo": "No hay observaciones oficiales para el mes; la celda no fue modificada.",
            })
            continue

        row = grouped.loc[month]
        observations = int(row["observaciones"])
        if require_calendar_complete:
            expected = calendar.monthrange(month.year, month.month)[1]
            if observations < expected:
                faltantes.append({
                    "tipo": "pendiente_publicacion",
                    "modulo": module,
                    "indice": headers[col - 1],
                    "mes": _format_sheet_date(month),
                    "motivo": (
                        f"Mes incompleto: {observations} observaciones de {expected}; "
                        "la celda no fue modificada."
                    ),
                })
                continue

        value = _value_or_none(row["promedio"])
        if value is None:
            faltantes.append({
                "tipo": "pendiente_publicacion",
                "modulo": module,
                "indice": headers[col - 1],
                "mes": _format_sheet_date(month),
                "motivo": "El promedio mensual no pudo calcularse; la celda no fue modificada.",
            })
            continue
        updates[(month, col)] = float(value)

    return 1


def _scrape_icl_to_updates(headers, months, updates, faltantes) -> int:
    return _scrape_bcra_monthly_average_to_updates(
        module="ICL BCRA",
        loader=obtener_datos_icl,
        value_column="ICL",
        header_terms=["indice", "contratos", "locacion", "promedio", "mensual"],
        excluded_terms=None,
        headers=headers,
        months=months,
        updates=updates,
        faltantes=faltantes,
        require_calendar_complete=True,
    )


def _scrape_cer_to_updates(headers, months, updates, faltantes) -> int:
    return _scrape_bcra_monthly_average_to_updates(
        module="CER BCRA",
        loader=obtener_datos_cer,
        value_column="CER",
        header_terms=["cer", "coeficiente", "estabilizacion", "referencia", "promedio", "mensual"],
        excluded_terms=None,
        headers=headers,
        months=months,
        updates=updates,
        faltantes=faltantes,
        require_calendar_complete=True,
    )


def _scrape_badlar_na_to_updates(headers, months, updates, faltantes) -> int:
    return _scrape_bcra_monthly_average_to_updates(
        module="BADLAR n.a. BCRA",
        loader=obtener_datos_badlar_na,
        value_column="BADLAR_NA",
        header_terms=["badlar", "bancos privados", "na"],
        excluded_terms=["ea"],
        headers=headers,
        months=months,
        updates=updates,
        faltantes=faltantes,
    )


def _scrape_badlar_ea_to_updates(headers, months, updates, faltantes) -> int:
    return _scrape_bcra_monthly_average_to_updates(
        module="BADLAR e.a. BCRA",
        loader=obtener_datos_badlar_ea,
        value_column="BADLAR_EA",
        header_terms=["badlar", "bancos privados", "ea"],
        excluded_terms=None,
        headers=headers,
        months=months,
        updates=updates,
        faltantes=faltantes,
    )


def _scrape_a3500_to_updates(headers, months, updates, faltantes) -> int:
    col = _header_index(headers, ["a3500"])
    if not col:
        faltantes.append({"tipo": "configuracion", "modulo": "A3500 BCRA", "indice": "Tipo de Cambio Mayorista A3500 BCRA", "mes": None, "motivo": "No se encontró encabezado A3500."})
        return 0
    df = obtener_datos_a3500().copy()
    df["__month__"] = df["Fecha"].apply(_month_start)
    grouped = df.dropna(subset=["__month__"]).groupby("__month__")["TC_promedio_mensual"].first().to_dict()
    for m in months:
        val = _value_or_none(grouped.get(m))
        if val is None:
            faltantes.append({"tipo": "pendiente_publicacion", "modulo": "A3500 BCRA", "indice": headers[col - 1], "mes": _format_sheet_date(m), "motivo": "Promedio mensual todavía no disponible; no se modificó la celda."})
        else:
            updates[(m, col)] = round(val, 4)
    return 1


def _scrape_b9791_to_updates(headers, months, updates, faltantes) -> int:
    col = _header_index(headers, ["9791"])
    if not col:
        faltantes.append({"tipo": "configuracion", "modulo": "B9791 BCRA", "indice": "Tipo de Cambio Minorista Comunicación B 9791", "mes": None, "motivo": "No se encontró encabezado B9791."})
        return 0
    df = obtener_datos_b9791().copy()
    df["__month__"] = df["Fecha"].apply(_month_start)
    grouped = df.dropna(subset=["__month__"]).groupby("__month__")["Promedio_mensual"].first().to_dict()
    for m in months:
        val = _value_or_none(grouped.get(m))
        if val is None:
            faltantes.append({"tipo": "pendiente_publicacion", "modulo": "B9791 BCRA", "indice": headers[col - 1], "mes": _format_sheet_date(m), "motivo": "Promedio mensual todavía no disponible; no se modificó la celda."})
        else:
            updates[(m, col)] = round(val, 4)
    return 1



def _scrape_bna_to_updates(headers, months, updates, faltantes) -> int:
    col = _find_header_column(headers, "Tipo de cambio nominal promedio mensual - BNA")
    if not col:
        col = _header_index(headers, ["tipo", "cambio", "nominal", "promedio", "mensual", "bna"])
    if not col:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "TC BNA",
            "indice": "Tipo de cambio nominal promedio mensual - BNA",
            "mes": None,
            "motivo": "No se encontró el encabezado del TC BNA.",
        })
        return 0

    first_day = months[0]
    last_month = months[-1]
    last_day = date(last_month.year, last_month.month, calendar.monthrange(last_month.year, last_month.month)[1])
    frame = obtener_datos_bna(fecha_desde=first_day, fecha_hasta=last_day).copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    grouped = frame.dropna(subset=["__month__"]).groupby("__month__").agg(
        promedio=("Promedio", "mean"),
        observaciones=("Promedio", "count"),
    )
    for month in months:
        if month not in grouped.index:
            faltantes.append({
                "tipo": "pendiente_publicacion",
                "modulo": "TC BNA",
                "indice": headers[col - 1],
                "mes": _format_sheet_date(month),
                "motivo": "No hay cotizaciones BNA para el mes; la celda no fue modificada.",
            })
            continue
        value = _value_or_none(grouped.loc[month, "promedio"])
        if value is not None:
            updates[(month, col)] = round(float(value), 4)
    return 1



def _scrape_jus_to_updates(headers, months, updates, faltantes) -> int:
    header = "JUS - Cordoba"
    col = _find_header_column(headers, header)
    if not col:
        faltantes.append({"tipo": "configuracion", "modulo": "JUS Córdoba", "indice": header, "mes": None, "motivo": "No se encontró el encabezado JUS - Cordoba."})
        return 0
    frame = obtener_datos_jus().copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    values = frame.dropna(subset=["__month__"]).set_index("__month__")["JUS"].to_dict()
    for month in months:
        value = _value_or_none(values.get(month))
        if value is None:
            faltantes.append({"tipo": "pendiente_publicacion", "modulo": "JUS Córdoba", "indice": headers[col - 1], "mes": _format_sheet_date(month), "motivo": "No existe un valor JUS publicado para ese mes; la celda no fue modificada."})
        else:
            updates[(month, col)] = float(value)
    return 1


def _scrape_ipc_eeuu_to_updates(headers, months, updates, faltantes) -> int:
    header = "IPC EEUU Base 1982-84=100"
    col = _find_header_column(headers, header)
    if not col:
        faltantes.append({"tipo": "configuracion", "modulo": "IPC EE.UU.", "indice": header, "mes": None, "motivo": "No se encontró el encabezado del IPC EE.UU."})
        return 0
    frame = obtener_datos_ipc_eeuu(fecha_desde=months[0], fecha_hasta=_add_months(months[-1], 1) - timedelta(days=1)).copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    values = frame.dropna(subset=["__month__"]).set_index("__month__")["Valor"].to_dict()
    for month in months:
        value = _value_or_none(values.get(month))
        if value is None:
            faltantes.append({"tipo": "pendiente_publicacion", "modulo": "IPC EE.UU.", "indice": headers[col - 1], "mes": _format_sheet_date(month), "motivo": "Dato BLS todavía no publicado; la celda no fue modificada."})
        else:
            updates[(month, col)] = float(value)
    return 1


def _scrape_ipc_san_luis_to_updates(headers, months, updates, faltantes) -> int:
    header = "IPC SAN LUIS"
    col = _find_header_column(headers, header)
    if not col:
        faltantes.append({"tipo": "configuracion", "modulo": "IPC San Luis", "indice": header, "mes": None, "motivo": "No se encontró el encabezado IPC SAN LUIS."})
        return 0
    frame = obtener_datos_ipc_san_luis(
        max_reports=max(8, len(months) + 2),
        fecha_desde=months[0],
        fecha_hasta=months[-1],
    ).copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    values = frame.dropna(subset=["__month__"]).set_index("__month__")["Valor"].to_dict()
    for month in months:
        value = _value_or_none(values.get(month))
        if value is None:
            faltantes.append({"tipo": "pendiente_publicacion", "modulo": "IPC San Luis", "indice": headers[col - 1], "mes": _format_sheet_date(month), "motivo": "No se pudo obtener el informe mensual; la celda no fue modificada."})
        else:
            updates[(month, col)] = float(value)
    return 1


def _scrape_iop_cba_to_updates(headers, months, updates, faltantes) -> int:
    frame = obtener_datos_iop_cba(fecha_desde=months[0]).copy()
    series = _df_long_to_month_values(frame, months, "Orden", "Valor")
    return _add_series_to_updates(
        module="Índice de Obra Pública Córdoba",
        series_by_key=series,
        key_to_header=IOP_CBA_TARGET_HEADERS,
        headers=headers,
        months=months,
        updates=updates,
        faltantes=faltantes,
    )



def _scrape_vga_cba_to_updates(headers, months, updates, faltantes) -> int:
    col = _header_index(headers, ["valor", "gestion", "agua", "vga"])
    if not col:
        col = _header_index(headers, ["vga"], excluded_terms=["link"])
    if not col:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "VGA Córdoba",
            "indice": "Valor de la Gestión del Agua (VGA)",
            "mes": None,
            "motivo": "No se encontró el encabezado de la columna VGA.",
        })
        return 0

    frame = obtener_datos_vga_cba(
        fecha_desde=months[0],
        fecha_hasta=months[-1],
        max_resources=max(len(months) + 2, 8),
    ).copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    values = (
        frame.dropna(subset=["__month__"])
        .drop_duplicates(subset=["__month__"], keep="last")
        .set_index("__month__")["Valor"]
        .to_dict()
    )

    for month in months:
        value = _value_or_none(values.get(month))
        if value is None:
            faltantes.append({
                "tipo": "pendiente_publicacion",
                "modulo": "VGA Córdoba",
                "indice": headers[col - 1],
                "mes": _format_sheet_date(month),
                "motivo": "El VGA del mes todavía no fue publicado; la celda no fue modificada.",
            })
        else:
            updates[(month, col)] = float(value)
    return 1


def _find_cvc_rac_columns(headers: List[str]) -> Dict[str, Optional[int]]:
    found: Dict[str, Optional[int]] = {
        "coefficient": None,
        "factor": None,
        "index": None,
    }
    for idx, header in enumerate(headers, start=1):
        normalized = normalizar_texto(header)
        if not normalized:
            continue

        if (
            found["coefficient"] is None
            and "cvc" in normalized
            and "rac" in normalized
            and "coeficiente" in normalized
            and "variacion" not in normalized
            and "indice" not in normalized
        ):
            found["coefficient"] = idx
            continue

        if (
            found["factor"] is None
            and "cvc" in normalized
            and "rac" in normalized
            and "variacion" in normalized
            and "indice" not in normalized
        ):
            found["factor"] = idx
            continue

        if (
            found["index"] is None
            and "rac" in normalized
            and "indice" in normalized
            and "ipc" not in normalized
        ):
            found["index"] = idx

    return found


def _scrape_cvc_rac_to_updates(headers, months, updates, faltantes) -> int:
    cols = _find_cvc_rac_columns(headers)
    managed = 0

    labels = {
        "coefficient": "Coeficiente cvc rac (no usar en api)",
        "factor": "CVC RAC 1 + Variacion (no usar en api)",
        "index": "Índice RAC",
    }
    for key, label in labels.items():
        if cols[key]:
            managed += 1
        else:
            faltantes.append({
                "tipo": "configuracion",
                "modulo": "CVC RAC",
                "indice": label,
                "mes": None,
                "motivo": "No se encontró el encabezado correspondiente en la hoja.",
            })

    coefficient_col = cols["coefficient"]
    if not coefficient_col:
        return managed

    frame = obtener_datos_cvc_rac(fecha_desde=months[0]).copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    values = (
        frame.dropna(subset=["__month__"])
        .drop_duplicates(subset=["__month__"], keep="last")
        .set_index("__month__")["CVC"]
        .to_dict()
    )

    for month in months:
        value = _value_or_none(values.get(month))
        if value is None:
            faltantes.append({
                "tipo": "pendiente_publicacion",
                "modulo": "CVC RAC",
                "indice": headers[coefficient_col - 1],
                "mes": _format_sheet_date(month),
                "motivo": "El CVC RAC del mes todavía no fue publicado; las celdas no fueron modificadas.",
            })
            continue

        updates[(month, coefficient_col)] = float(value)
        if cols["factor"]:
            updates[(month, cols["factor"])] = _formula_cvc_factor_marker(
                rate_col=coefficient_col
            )
        if cols["index"]:
            updates[(month, cols["index"])] = _formula_cvc_index_marker(
                rate_col=coefficient_col
            )

    return managed

def _scrape_fam_epec_to_updates(headers, months, updates, faltantes) -> int:
    fam_header = "FAM de EPEC (Variacion porcentual)(No usar en la API)"
    index_header = "Índice FAM (de EPEC) (Usar este en la API)"

    fam_col = _find_header_column(headers, fam_header)
    index_col = _find_header_column(headers, index_header)
    managed = 0

    if fam_col:
        managed += 1
    else:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "FAM EPEC",
            "indice": fam_header,
            "mes": None,
            "motivo": "No se encontró la columna de variación FAM EPEC.",
        })

    if index_col:
        managed += 1
    else:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "FAM EPEC",
            "indice": index_header,
            "mes": None,
            "motivo": "No se encontró la columna Índice FAM de EPEC.",
        })

    if not fam_col:
        return managed

    frame = obtener_datos_fam_epec(
        fecha_desde=months[0],
        fecha_hasta=_add_months(months[-1], 1) - timedelta(days=1),
    ).copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    values = (
        frame.dropna(subset=["__month__"])
        .drop_duplicates(subset=["__month__"], keep="last")
        .set_index("__month__")["FAM"]
        .to_dict()
    )

    for month in months:
        value = _value_or_none(values.get(month))
        if value is None:
            faltantes.append({
                "tipo": "pendiente_publicacion",
                "modulo": "FAM EPEC",
                "indice": headers[fam_col - 1],
                "mes": _format_sheet_date(month),
                "motivo": "El FAM EPEC del mes todavía no fue publicado; las celdas no fueron modificadas.",
            })
            continue

        # El valor se copia directamente desde la fuente (por ejemplo, 1,035188854).
        updates[(month, fam_col)] = float(value)
        if index_col:
            # Ejemplo: DK1365 = DK1364 * (1 + DJ1365/100)
            updates[(month, index_col)] = _formula_fam_index_marker(
                rate_col=fam_col
            )

    return managed


def _scrape_icccba_to_updates(headers, months, updates, faltantes) -> int:
    """Carga cuatro índices directos y cuatro medias móviles interanuales de 13 meses."""
    base_cols = {}
    moving_cols = {}
    managed = 0

    for key, header in ICC_CBA_TARGET_HEADERS.items():
        col = _find_header_column(headers, header)
        if not col:
            faltantes.append({
                "tipo": "configuracion",
                "modulo": "ICC Córdoba",
                "indice": header,
                "mes": None,
                "motivo": "No se encontró el encabezado de la serie ICC Córdoba.",
            })
        else:
            base_cols[key] = col
            managed += 1

    for key, header in ICC_CBA_MOVING_HEADERS.items():
        col = _find_header_column(headers, header)
        if not col:
            faltantes.append({
                "tipo": "configuracion",
                "modulo": "ICC Córdoba",
                "indice": header,
                "mes": None,
                "motivo": "No se encontró el encabezado de la media móvil ICC Córdoba.",
            })
        else:
            moving_cols[key] = col
            managed += 1

    if not base_cols:
        return managed

    frame = obtener_datos_icccba(fecha_desde=months[0]).copy()
    frame["__month__"] = frame["Fecha"].apply(_month_start)
    frame = frame.dropna(subset=["__month__"]).drop_duplicates(subset=["__month__"], keep="last")
    by_month = frame.set_index("__month__")

    for month in months:
        if month not in by_month.index:
            for key, col in base_cols.items():
                faltantes.append({
                    "tipo": "pendiente_publicacion",
                    "modulo": "ICC Córdoba",
                    "indice": headers[col - 1],
                    "mes": _format_sheet_date(month),
                    "motivo": "Dato todavía no publicado; la celda existente no fue modificada.",
                })
            continue

        row = by_month.loc[month]
        for key, source_col in base_cols.items():
            value = _value_or_none(row.get(key))
            if value is None:
                faltantes.append({
                    "tipo": "pendiente_publicacion",
                    "modulo": "ICC Córdoba",
                    "indice": headers[source_col - 1],
                    "mes": _format_sheet_date(month),
                    "motivo": "El índice oficial no pudo interpretarse; la celda no fue modificada.",
                })
                continue
            updates[(month, source_col)] = float(value)
            target_moving_col = moving_cols.get(key)
            if target_moving_col:
                updates[(month, target_moving_col)] = _formula_moving_average_marker(
                    source_col=source_col,
                    window=ICC_CBA_MOVING_WINDOW,
                )

    return managed


def _scrape_ipccba_to_updates(headers, months, updates, faltantes) -> int:
    """
    Carga directamente los números índice oficiales del IPC Córdoba.

    El parámetro ``months`` se conserva por compatibilidad con el resto de los
    módulos, pero Córdoba ya no queda limitado por UPDATE_MONTHS: se recorren
    todos los meses disponibles en la nueva base oficial y se mantiene el
    mismo criterio histórico de coincidencia por código/nombre/alias.
    """
    cba_cols = [
        (i, h)
        for i, h in enumerate(headers, start=1)
        if "ipc cordoba" in normalizar_texto(h)
    ]

    if not cba_cols:
        faltantes.append({
            "tipo": "configuracion",
            "modulo": "IPC Córdoba",
            "indice": "IPC Córdoba",
            "mes": None,
            "motivo": "No se encontraron encabezados IPC Córdoba.",
        })
        return 0

    # No se pasa fecha_desde: la nueva base se usa completa. Esto permite
    # actualizar también los meses anteriores a la ventana global de 6 meses.
    largo = obtener_datos_ipccba_largo()
    largo["__month__"] = largo["Fecha"].apply(_month_start)

    # Se mantiene la regla general de no tratar el mes en curso como mensual
    # definitivo, salvo que UPDATE_INCLUDE_CURRENT_MONTH esté habilitado.
    today = datetime.now().date()
    current_month = date(today.year, today.month, 1)
    max_month = current_month if UPDATE_INCLUDE_CURRENT_MONTH else _add_months(current_month, -1)
    available_months = sorted(
        {
            month
            for month in largo["__month__"].dropna().tolist()
            if month <= max_month
        }
    )

    for col, header in cba_cols:
        matched_any = False
        for month in available_months:
            month_df = largo[largo["__month__"] == month]
            index_value = _match_ipc_cba_value(header, month_df)

            if index_value is None:
                continue

            # Se escribe el número índice oficial como valor directo. Ya no se
            # genera fórmula índice_anterior * (1 + variación).
            updates[(month, col)] = float(index_value)
            matched_any = True

        if not matched_any:
            faltantes.append({
                "tipo": "configuracion",
                "modulo": "IPC Córdoba",
                "indice": header,
                "mes": None,
                "motivo": "No se encontró una serie compatible en la nueva base de números índice del IPC Córdoba.",
            })

    return len(cba_cols)

def ejecutar_actualizacion_indices() -> Dict[str, Any]:
    inicio = datetime.now()
    months = _meses_objetivo_actualizacion()
    month_labels = [_format_sheet_date(m) for m in months]
    ws = _get_worksheet()
    headers = [str(h).strip() if h is not None else "" for h in ws.row_values(1)]
    if not headers:
        raise RuntimeError("La hoja no tiene encabezados en la fila 1.")

    updates: Dict[Tuple[date, int], Any] = {}
    faltantes: List[Dict[str, Any]] = []
    errores: List[Dict[str, Any]] = []
    modulos_ok: List[str] = []
    columnas_gestionadas = 0

    modules = [
        ("IPC INDEC", _scrape_ipcn_to_updates),
        ("ICC INDEC", _scrape_icc_to_updates),
        ("IPIM INDEC", _scrape_ipim_to_updates),
        ("Índice de salarios INDEC", _scrape_salarios_to_updates),
        ("ICL BCRA", _scrape_icl_to_updates),
        ("CER BCRA", _scrape_cer_to_updates),
        ("BADLAR n.a. BCRA", _scrape_badlar_na_to_updates),
        ("BADLAR e.a. BCRA", _scrape_badlar_ea_to_updates),
        ("TC BNA", _scrape_bna_to_updates),
        ("JUS Córdoba", _scrape_jus_to_updates),
        ("IPC EE.UU.", _scrape_ipc_eeuu_to_updates),
        ("IPC San Luis", _scrape_ipc_san_luis_to_updates),
        ("A3500 BCRA", _scrape_a3500_to_updates),
        ("B9791 BCRA", _scrape_b9791_to_updates),
        ("ICC Córdoba", _scrape_icccba_to_updates),
        ("Índice de Obra Pública Córdoba", _scrape_iop_cba_to_updates),
        ("VGA Córdoba", _scrape_vga_cba_to_updates),
        ("CVC RAC", _scrape_cvc_rac_to_updates),
        ("FAM EPEC", _scrape_fam_epec_to_updates),
        ("IPC Córdoba", _scrape_ipccba_to_updates),
    ]

    for module_name, func in modules:
        try:
            columnas_gestionadas += func(headers, months, updates, faltantes)
            modulos_ok.append(module_name)
        except Exception as exc:
            errores.append({
                "modulo": module_name,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })

    # El empalme se calcula después de preparar IPC INDEC, porque su fórmula
    # depende del Nivel General de la columna inmediata a la derecha.
    try:
        columnas_gestionadas += _add_empalme_ipc_indec_updates(
            headers,
            months,
            updates,
            faltantes,
        )
        modulos_ok.append("Empalme IPC INDEC")
    except Exception as exc:
        errores.append({
            "modulo": "Empalme IPC INDEC",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })

    months_to_write = sorted({month for month, _ in updates.keys()})
    rows_by_month = _ensure_month_rows(ws, months_to_write, total_cols=len(headers)) if months_to_write else {}

    batch = []
    for (month, col), value in sorted(updates.items(), key=lambda x: (x[0][0], x[0][1])):
        row = rows_by_month.get(month)
        if not row:
            faltantes.append({"modulo": "Google Sheets", "indice": f"Columna {col}", "mes": _format_sheet_date(month), "motivo": "No se encontró o creó fila mensual."})
            continue
        rendered_value = _render_sheet_update(value, row, col)
        batch.append({"range": rowcol_to_a1(row, col), "values": [[rendered_value]]})
    updated_cells = 0
    if batch:
        # Google limita el tamaño razonable de algunas operaciones; se envía por lotes chicos.
        for i in range(0, len(batch), 400):
            chunk = batch[i:i + 400]
            ws.batch_update(chunk, value_input_option="USER_ENTERED")
            updated_cells += len(chunk)

    _invalidate_cache()

    fin = datetime.now()
    pendientes = [x for x in faltantes if x.get("tipo") == "pendiente_publicacion"]
    incidencias = [x for x in faltantes if x.get("tipo") != "pendiente_publicacion"]

    status = "ok"
    if errores or incidencias:
        status = "partial"
    if errores and updated_cells == 0:
        status = "error"

    return {
        "ok": status in {"ok", "partial"},
        "status": status,
        "message": "Actualización de índices finalizada sin borrar datos existentes.",
        "sheet_url": GSHEET_PUBLIC_URL,
        "worksheet": GSHEET_WORKSHEET_NAME,
        "months_requested": month_labels,
        "includes_current_month": UPDATE_INCLUDE_CURRENT_MONTH,
        "modules_ok": modulos_ok,
        "managed_columns": columnas_gestionadas,
        "updated_cells": updated_cells,
        "missing_count": len(faltantes),
        "pending_count": len(pendientes),
        "issue_count": len(incidencias),
        "error_count": len(errores),
        "faltantes": faltantes,
        "pendientes": pendientes,
        "incidencias": incidencias,
        "errores": errores,
        "started_at": inicio.isoformat(timespec="seconds"),
        "finished_at": fin.isoformat(timespec="seconds"),
        "duration_seconds": round((fin - inicio).total_seconds(), 2),
    }


# =========================================================
# API Endpoints
# =========================================================
@app.get("/api/meta")
def meta(force: bool = False, auth: bool = Depends(require_stats_access)):
    df = _load_df(force=force)
    cols = [str(c) for c in df.columns.tolist() if not str(c).startswith("__")]
    index_col = cols[0]
    dt_index = _coerce_month_dates(df.iloc[:, 0])
    meses = {
        1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
        5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
        9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
    }
    index_values = []
    for x in dt_index:
        if pd.isna(x):
            continue
        index_values.append({
            "value": x.strftime("%Y-%m-%d"),
            "label": f"{meses[x.month]}-{x.year}",
        })
    value_columns = [{"id": cols[i], "name": cols[i]} for i in range(1, len(cols))]
    return {"index_column": index_col, "index_values": index_values, "value_columns": value_columns, "worksheet": GSHEET_WORKSHEET_NAME, "read_only": PUBLIC_READ_ONLY}


@app.get("/api/data")
def data(
    col_idxs: str = Query(..., description="Nombres de columnas separados por coma"),
    desde: str = Query(..., description="Valor inicial"),
    hasta: str = Query(..., description="Valor final"),
    auth: bool = Depends(require_stats_access),
):
    df = _load_df(force=False)
    col_names = [c.strip() for c in col_idxs.split(",") if c.strip()]
    missing = [c for c in col_names if c not in df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"Columnas no encontradas: {missing}")
    dt_index = _build_date_index(df)
    try:
        mask_desde = dt_index == str(desde).strip()
        mask_hasta = dt_index == str(hasta).strip()
        if not mask_desde.any() or not mask_hasta.any():
            raise HTTPException(status_code=400, detail=f"Fecha desde/hasta inválida. desde={desde} hasta={hasta}")
        idx_desde = df.index[mask_desde][0]
        idx_hasta = df.index[mask_hasta][0]
        inicio, fin = min(idx_desde, idx_hasta), max(idx_desde, idx_hasta)
        cols_a_extraer = [df.columns[0]] + col_names
        df_slice = df.loc[inicio:fin, cols_a_extraer].copy()
        col_fecha = df_slice.columns[0]
        dt = _coerce_month_dates(df_slice[col_fecha])
        meses = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun", 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
        df_slice[col_fecha] = dt.apply(lambda x: f"{meses.get(int(x.month), '')}-{int(x.year)}" if pd.notnull(x) else "")
        df_slice = df_slice.fillna("")
        stats = {"count": 0, "mean": None}
        if len(cols_a_extraer) > 1:
            valor_num = pd.to_numeric(df_slice[cols_a_extraer[1]], errors="coerce")
            stats = {"count": int(valor_num.count()), "mean": None if valor_num.count() == 0 else float(valor_num.mean())}
        return {"headers": df_slice.columns.tolist(), "rows": df_slice.values.tolist(), "stats": stats, "tsv": _to_tsv(df_slice)}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error en data: {e}")
        raise HTTPException(status_code=400, detail="No se pudo procesar el rango o hay valores inválidos.")


@app.get("/api/reload")
def reload_base(auth: bool = Depends(require_auth)):
    _load_df(force=True)
    return {"ok": True}


@app.post("/api/actualizar-indices")
async def actualizar_indices(auth: bool = Depends(require_auth)):
    if PUBLIC_READ_ONLY:
        raise HTTPException(status_code=403, detail="Actualización deshabilitada en el módulo público de estadísticas (solo lectura).")
    # Se procesa en un hilo para no bloquear el event loop. Los errores vuelven como JSON legible.
    try:
        return await run_in_threadpool(ejecutar_actualizacion_indices)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail=f"Falló la actualización automática: {exc}",
        ) from exc


@app.get("/api/diagnostico-fuentes")
async def diagnostico_fuentes(auth: bool = Depends(require_auth)):
    """Prueba de solo lectura: no modifica Google Sheets y muestra la última fecha de cada fuente."""
    def run_checks() -> Dict[str, Any]:
        checks = [
            ("IPC INDEC", obtener_datos_ipcn),
            ("ICC INDEC", obtener_datos_icc),
            ("IPIM INDEC", obtener_datos_ipim),
            ("Índice de salarios INDEC", obtener_datos_salarios),
            ("ICL BCRA", obtener_datos_icl),
            ("CER BCRA", obtener_datos_cer),
            ("BADLAR n.a. BCRA", obtener_datos_badlar_na),
            ("BADLAR e.a. BCRA", obtener_datos_badlar_ea),
            ("TC BNA", obtener_datos_bna),
            ("JUS Córdoba", obtener_datos_jus),
            ("IPC EE.UU.", obtener_datos_ipc_eeuu),
            ("IPC San Luis", obtener_datos_ipc_san_luis),
            ("A3500 BCRA", obtener_datos_a3500),
            ("B9791 BCRA API", obtener_datos_b9791),
            ("ICC Córdoba", obtener_datos_icccba),
            ("Índice de Obra Pública Córdoba", obtener_datos_iop_cba),
            ("VGA Córdoba", obtener_datos_vga_cba),
            ("CVC RAC", obtener_datos_cvc_rac),
            ("FAM EPEC", obtener_datos_fam_epec),
            ("IPC Córdoba", obtener_datos_ipccba_largo),
        ]
        results = []
        for name, func in checks:
            started = time.time()
            try:
                frame = func()
                latest = None
                if "Fecha" in frame.columns and not frame.empty:
                    latest_ts = pd.to_datetime(frame["Fecha"], errors="coerce").max()
                    latest = None if pd.isna(latest_ts) else latest_ts.strftime("%Y-%m-%d")
                result_item = {
                    "fuente": name,
                    "ok": True,
                    "filas": int(len(frame)),
                    "ultima_fecha": latest,
                    "segundos": round(time.time() - started, 2),
                }
                if latest and "Promedio_mensual" in frame.columns:
                    latest_month = pd.Timestamp(latest).to_period("M")
                    month_rows = frame[
                        pd.to_datetime(frame["Fecha"], errors="coerce").dt.to_period("M")
                        == latest_month
                    ]
                    if not month_rows.empty:
                        result_item["ultimo_promedio_mensual"] = float(
                            month_rows["Promedio_mensual"].iloc[-1]
                        )
                        if "Observaciones_mes" in month_rows.columns:
                            result_item["observaciones_ultimo_mes"] = int(
                                month_rows["Observaciones_mes"].iloc[-1]
                            )
                results.append(result_item)
            except Exception as exc:
                results.append({
                    "fuente": name,
                    "ok": False,
                    "error": str(exc),
                    "segundos": round(time.time() - started, 2),
                })
        failed = sum(1 for item in results if not item["ok"])
        return {
            "ok": failed == 0,
            "status": "ok" if failed == 0 else "partial",
            "total_fuentes": len(results),
            "fallidas": failed,
            "results": results,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }

    return await run_in_threadpool(run_checks)


@app.get("/api/variaciones")
def obtener_variaciones(
    col_idxs: str = Query(..., description="Nombres de columnas separados por coma"),
    desde: str = Query(..., description="Inicio"),
    hasta: str = Query(..., description="Fin"),
    auth: bool = Depends(require_stats_access),
):
    df = _load_df(force=False)
    col_names = [c.strip() for c in col_idxs.split(",") if c.strip()]
    missing = [c for c in col_names if c not in df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"Columnas no encontradas: {missing}")
    try:
        dt_index = _build_date_index(df)
        mask_desde = dt_index == str(desde).strip()
        mask_hasta = dt_index == str(hasta).strip()
        if not mask_desde.any() or not mask_hasta.any():
            raise HTTPException(status_code=400, detail=f"Fecha desde/hasta inválida. desde={desde} hasta={hasta}")
        idx_desde = df.index[mask_desde][0]
        idx_hasta = df.index[mask_hasta][0]
        inicio, fin = min(idx_desde, idx_hasta), max(idx_desde, idx_hasta)
        resultados = []
        for col in col_names:
            serie = pd.to_numeric(df.loc[inicio:fin, col], errors="coerce")
            v_inicial = serie.iloc[0] if len(serie) else pd.NA
            v_final = serie.iloc[-1] if len(serie) else pd.NA
            variacion = None
            if pd.notnull(v_inicial) and pd.notnull(v_final) and float(v_inicial) != 0.0:
                variacion = ((float(v_final) / float(v_inicial)) - 1.0) * 100.0
            resultados.append({
                "serie": col,
                "inicial": float(v_inicial) if pd.notnull(v_inicial) else None,
                "final": float(v_final) if pd.notnull(v_final) else None,
                "variacion": float(variacion) if variacion is not None else None,
            })
        return {"periodo": f"{desde} a {hasta}", "data": resultados}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/serie")
def obtener_serie(
    col: str = Query(..., description="Nombre de la columna/serie"),
    desde: str = Query(..., description="Inicio YYYY-MM-DD"),
    hasta: str = Query(..., description="Fin YYYY-MM-DD"),
    auth: bool = Depends(require_stats_access),
):
    df = _load_df(force=False)
    if col not in df.columns:
        raise HTTPException(status_code=400, detail=f"Columna no encontrada: {col}")
    dt_index = _build_date_index(df)
    mask_desde = dt_index == str(desde).strip()
    mask_hasta = dt_index == str(hasta).strip()
    if not mask_desde.any() or not mask_hasta.any():
        raise HTTPException(status_code=400, detail=f"Fecha desde/hasta inválida. desde={desde} hasta={hasta}")
    idx_desde = df.index[mask_desde][0]
    idx_hasta = df.index[mask_hasta][0]
    inicio, fin = min(idx_desde, idx_hasta), max(idx_desde, idx_hasta)
    fechas_iso = dt_index.iloc[inicio:fin + 1].tolist()
    s = pd.to_numeric(df.loc[inicio:fin, col], errors="coerce").reset_index(drop=True)
    values = [None if pd.isna(x) else float(x) for x in s.tolist()]
    pct = s.pct_change() * 100.0
    pct_list = [None if pd.isna(x) else float(x) for x in pct.tolist()]
    v0 = s.iloc[0] if len(s) else pd.NA
    v1 = s.iloc[-1] if len(s) else pd.NA
    total_growth = None
    if pd.notnull(v0) and pd.notnull(v1) and float(v0) != 0.0:
        total_growth = ((float(v1) / float(v0)) - 1.0) * 100.0
    avg_mom = float(pct.mean()) if pct.count() > 0 else None
    return {
        "col": col,
        "desde": desde,
        "hasta": hasta,
        "n": int(s.count()),
        "dates": fechas_iso,
        "values": values,
        "mom_pct": pct_list,
        "metrics": {"total_growth_pct": total_growth, "avg_mom_pct": avg_mom},
    }


@app.get("/api/series")
def obtener_series(
    col_idxs: str = Query(..., description="Nombres de columnas separados por coma"),
    desde: str = Query(..., description="Inicio YYYY-MM-DD"),
    hasta: str = Query(..., description="Fin YYYY-MM-DD"),
    auth: bool = Depends(require_stats_access),
):
    df = _load_df(force=False)
    cols = [c.strip() for c in col_idxs.split(",") if c.strip()]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"Columnas no encontradas: {missing}")
    dt_index = _build_date_index(df)
    mask_desde = dt_index == str(desde).strip()
    mask_hasta = dt_index == str(hasta).strip()
    if not mask_desde.any() or not mask_hasta.any():
        raise HTTPException(status_code=400, detail=f"Fecha desde/hasta inválida. desde={desde} hasta={hasta}")
    idx_desde = df.index[mask_desde][0]
    idx_hasta = df.index[mask_hasta][0]
    inicio, fin = min(idx_desde, idx_hasta), max(idx_desde, idx_hasta)
    fechas_iso = dt_index.iloc[inicio:fin + 1].tolist()
    out_series = []
    for col in cols:
        s = pd.to_numeric(df.loc[inicio:fin, col], errors="coerce").reset_index(drop=True)
        values = [None if pd.isna(x) else float(x) for x in s.tolist()]
        base100 = [None] * len(s)
        base_idx = None
        base_val = None
        for i, x in enumerate(s.tolist()):
            if pd.notnull(x) and float(x) != 0.0:
                base_idx = i
                base_val = float(x)
                break
        if base_idx is not None and base_val:
            for i, x in enumerate(s.tolist()):
                if pd.notnull(x):
                    base100[i] = (float(x) / base_val) * 100.0
        pct = s.pct_change() * 100.0
        mom_pct = [None if pd.isna(x) else float(x) for x in pct.tolist()]
        v0 = s.iloc[0] if len(s) else pd.NA
        v1 = s.iloc[-1] if len(s) else pd.NA
        total_growth = None
        if pd.notnull(v0) and pd.notnull(v1) and float(v0) != 0.0:
            total_growth = ((float(v1) / float(v0)) - 1.0) * 100.0
        avg_mom = float(pct.mean()) if pct.count() > 0 else None
        vol_mom = float(pct.std(ddof=0)) if pct.count() > 1 else None
        best_m = None
        worst_m = None
        if pct.count() > 0:
            best_idx = int(pct.idxmax())
            worst_idx = int(pct.idxmin())
            best_m = {"date": fechas_iso[best_idx], "pct": float(pct.iloc[best_idx])}
            worst_m = {"date": fechas_iso[worst_idx], "pct": float(pct.iloc[worst_idx])}
        out_series.append({
            "col": col,
            "values": values,
            "base100": base100,
            "mom_pct": mom_pct,
            "metrics": {
                "total_growth_pct": total_growth,
                "avg_mom_pct": avg_mom,
                "vol_mom_pct": vol_mom,
                "best_month": best_m,
                "worst_month": worst_m,
            },
        })
    return {"desde": desde, "hasta": hasta, "dates": fechas_iso, "series": out_series}

# =========================================================
# Módulos web integrados
# =========================================================
from app.routers.arca import create_router as create_arca_router
from app.routers.cumpleanos import create_cumpleanos_router
from app.routers.informes import create_informes_router
from app.routers.incidencia import create_incidencia_router
from app.boletin_routes import create_boletin_router
from app.transporte_routes import create_transporte_router

app.include_router(create_arca_router(require_auth))
app.include_router(create_cumpleanos_router(require_auth, _load_df))
app.include_router(create_informes_router(require_auth))
app.include_router(create_incidencia_router(require_auth))
app.include_router(create_boletin_router(require_auth, BASE_DIR, HTTP_TIMEOUT))
app.include_router(create_transporte_router(require_auth, BASE_DIR, HTTP_TIMEOUT))


@app.get("/api/health")
def api_health():
    return {
        "ok": True,
        "service": "API Estadísticas integrada",
        "arca": True,
        "cumpleanos": True,
        "boletin": True,
        "boletin_transporte": True,
        "informes_tecnicos": True,
        "incidencia_tarifaria": True,
    }

