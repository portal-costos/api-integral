"""Obtención, normalización y respaldo de tasas oficiales de ARCA."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .arca_engine import date_to_s, normalizar_numero, parse_fecha, redondeo

URL_ARCA_EVOLUCION_TASAS = (
    "https://serviciosweb.afip.gob.ar/genericos/calculoInteres/punitorios.aspx"
)
URL_ARCA_CALCULADORA_RESARCITORIOS = (
    "https://serviciosweb.afip.gob.ar/genericos/calculoInteres/resarcitorios.aspx"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
)

RATE_COLUMNS = [
    "Desde",
    "Hasta",
    "Norma",
    "Resarcitorio mensual",
    "Resarcitorio diario",
    "Punitorio mensual",
    "Punitorio diario",
    "Fuente",
]


def _fila_contiene_fecha(celdas: list[str]) -> bool:
    return bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ".join(celdas)))


def _clean_cell(value: Any) -> str:
    value = "" if value is None else str(value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_rate_df(df: pd.DataFrame, source: str) -> pd.DataFrame:
    out = df.copy()
    for col in RATE_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out["Desde"] = out["Desde"].apply(lambda x: date_to_s(parse_fecha(x)))
    out["Hasta"] = out["Hasta"].apply(lambda x: date_to_s(parse_fecha(x)))
    for col in [
        "Resarcitorio mensual",
        "Resarcitorio diario",
        "Punitorio mensual",
        "Punitorio diario",
    ]:
        out[col] = out[col].apply(normalizar_numero)
    out["Norma"] = out["Norma"].fillna("").astype(str).str.strip()
    out["Fuente"] = out["Fuente"].fillna(source).replace("", source)
    out["__desde"] = out["Desde"].apply(parse_fecha)
    out = out.dropna(subset=["__desde", "Resarcitorio mensual"])
    out = out.sort_values("__desde").drop_duplicates("Desde", keep="last")
    return out[RATE_COLUMNS].reset_index(drop=True)


def extraer_tasas_de_tablas_html(html_text: str) -> pd.DataFrame:
    """Extrae la tabla de evolución de tasas, incluso con encabezados multinivel."""
    tablas = pd.read_html(StringIO(html_text))
    registros: list[dict[str, Any]] = []

    for tabla in tablas:
        matrix = tabla.astype(str).fillna("").values.tolist()
        for row in matrix:
            cells = [_clean_cell(c) for c in row if _clean_cell(c) not in {"", "nan", "None"}]
            if not cells or not _fila_contiene_fecha(cells):
                continue

            dates: list[tuple[int, str]] = []
            for idx, cell in enumerate(cells):
                match = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", cell)
                if match:
                    dates.append((idx, match.group(0)))
            if len(dates) < 2:
                continue

            _, desde = dates[0]
            idx_hasta, hasta = dates[1]
            rest = cells[idx_hasta + 1 :]

            numeric: list[float] = []
            text_parts: list[str] = []
            for cell in rest:
                cleaned = cell.replace("%", "").strip()
                num = normalizar_numero(cleaned)
                if num is not None and re.fullmatch(r"-?\d+(?:[\.,]\d+)?", cleaned):
                    numeric.append(num)
                elif not re.search(r"mensual|diario|resarc|punitor|r[eé]gimen", cell, re.I):
                    text_parts.append(cell)

            if len(numeric) >= 2:
                registros.append(
                    {
                        "Desde": desde,
                        "Hasta": hasta,
                        "Norma": " ".join(text_parts).strip(),
                        "Resarcitorio mensual": numeric[0],
                        "Resarcitorio diario": numeric[1],
                        "Punitorio mensual": numeric[2] if len(numeric) > 2 else None,
                        "Punitorio diario": numeric[3] if len(numeric) > 3 else None,
                        "Fuente": "ARCA evolución de tasas",
                    }
                )

    if not registros:
        raise ValueError("No se detectaron filas de tasas en la página de ARCA.")
    return _normalize_rate_df(pd.DataFrame(registros), "ARCA evolución de tasas")


def extraer_tasas_desde_script_calculadora(html_text: str) -> pd.DataFrame:
    """Fallback: extrae pares fecha[]/tasa[] del JavaScript oficial."""
    patterns = [
        re.compile(
            r"fecha\[(\d+)\]\s*=\s*['\"]([^'\"]+)['\"]\s*;\s*"
            r"tasa\[\1\]\s*=\s*([\d\.,]+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"fechas?\[(\d+)\]\s*=\s*['\"]([^'\"]+)['\"]\s*;.*?"
            r"tasas?\[\1\]\s*=\s*([\d\.,]+)",
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    found: list[tuple[str, str, str]] = []
    for pattern in patterns:
        matches = pattern.findall(html_text)
        if matches:
            found = matches
            break

    registros: list[dict[str, Any]] = []
    for _, fecha_txt, tasa_txt in found:
        tasa = normalizar_numero(tasa_txt)
        f = parse_fecha(fecha_txt)
        if not f or tasa is None:
            continue
        registros.append(
            {
                "Desde": date_to_s(f),
                "Hasta": "",
                "Norma": "Script calculadora ARCA",
                "Resarcitorio mensual": tasa,
                "Resarcitorio diario": redondeo(tasa / 30, 6),
                "Punitorio mensual": None,
                "Punitorio diario": None,
                "Fuente": "ARCA calculadora",
            }
        )

    if not registros:
        raise ValueError("No se detectaron fecha[]/tasa[] en la calculadora ARCA.")

    df = _normalize_rate_df(pd.DataFrame(registros), "ARCA calculadora")
    # Completa hasta como día anterior a la tasa siguiente.
    starts = [parse_fecha(v) for v in df["Desde"].tolist()]
    for idx, start in enumerate(starts):
        if idx + 1 < len(starts) and starts[idx + 1]:
            df.loc[idx, "Hasta"] = date_to_s(starts[idx + 1] - timedelta(days=1))
        elif start:
            df.loc[idx, "Hasta"] = "31/12/2999"
    return df


def descargar_tasas_arca(timeout: int = 40) -> tuple[pd.DataFrame, list[str]]:
    """Descarga tasas oficiales; devuelve DataFrame y advertencias acumuladas."""
    headers = {"User-Agent": USER_AGENT}
    warnings: list[str] = []

    attempts = [
        (URL_ARCA_EVOLUCION_TASAS, extraer_tasas_de_tablas_html),
        (URL_ARCA_CALCULADORA_RESARCITORIOS, extraer_tasas_desde_script_calculadora),
    ]
    for url, parser in attempts:
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return parser(response.text), warnings
        except Exception as exc:
            warnings.append(f"Falló {url}: {exc}")

    raise RuntimeError("No se pudieron descargar tasas ARCA. " + " | ".join(warnings))


def cargar_tasas_respaldo(path: Path) -> pd.DataFrame:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("El respaldo de tasas ARCA no es una lista.")
    return _normalize_rate_df(pd.DataFrame(raw), "Respaldo local")


def guardar_tasas_respaldo(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = df[RATE_COLUMNS].where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def rate_metadata(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"count": 0, "latest": None}
    ordered = df.copy()
    ordered["__desde"] = ordered["Desde"].apply(parse_fecha)
    ordered = ordered.sort_values("__desde")
    latest = ordered.iloc[-1]
    return {
        "count": int(len(ordered)),
        "latest": {
            "desde": latest["Desde"],
            "hasta": latest["Hasta"],
            "norma": latest["Norma"],
            "resarcitorio_mensual": latest["Resarcitorio mensual"],
            "resarcitorio_diario": latest["Resarcitorio diario"],
            "fuente": latest["Fuente"],
        },
    }
