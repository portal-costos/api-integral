from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Callable

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException


SERIES_CONFIG = (
    {
        "key": "ipc_indec",
        "label": "IPC Nivel General INDEC",
        "required": ("ipc", "indec", "nivel", "general"),
        "excluded": ("cordoba",),
        "accent": "blue",
    },
    {
        "key": "ipc_cordoba_general",
        "label": "IPC Nivel General Córdoba",
        "required": ("ipc", "cordoba", "nivel", "general"),
        "excluded": (),
        "accent": "amber",
    },
    {
        "key": "ipc_cordoba_alimentos",
        "label": "IPC Alimentos y Bebidas Córdoba",
        "required": ("ipc", "cordoba", "alimentos", "bebidas"),
        "excluded": (),
        "accent": "teal",
    },
)


def _normalize(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip().replace("\u00a0", "").replace("$", "").replace("%", "")
    if not text or text.startswith("="):
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def _find_column(columns: list[str], required: tuple[str, ...], excluded: tuple[str, ...]) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    for column in columns:
        normalized = _normalize(column)
        if not all(token in normalized for token in required):
            continue
        if any(token in normalized for token in excluded):
            continue
        # Se prioriza el encabezado más directo y, luego, el más corto.
        extra_words = max(0, len(normalized.split()) - len(required))
        candidates.append((extra_words, len(normalized), column))
    return min(candidates)[2] if candidates else None


def _resolve_series(df: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [str(column) for column in df.columns[1:]]
    resolved = []
    for item in SERIES_CONFIG:
        column = _find_column(columns, item["required"], item["excluded"])
        resolved.append({**item, "column": column, "available": bool(column)})
    return resolved


def _date_series(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df.iloc[:, 0], errors="coerce", dayfirst=True)


def _month_label(value: pd.Timestamp | datetime | date) -> str:
    months = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
    ts = pd.Timestamp(value)
    return f"{months[ts.month - 1]}-{ts.year}"


def _month_value(df: pd.DataFrame, dates: pd.Series, column: str, month_iso: str) -> float | None:
    target = pd.to_datetime(month_iso, errors="coerce")
    if pd.isna(target):
        return None
    mask = (dates.dt.year == target.year) & (dates.dt.month == target.month)
    if not mask.any():
        return None
    values = df.loc[mask, column].map(_number).dropna()
    return float(values.iloc[-1]) if not values.empty else None


def build_meta(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or len(df.columns) < 2:
        raise ValueError("La base no contiene series suficientes para el panel.")

    series = _resolve_series(df)
    dates = _date_series(df).dropna().drop_duplicates().sort_values()
    months = [
        {"value": ts.strftime("%Y-%m-01"), "label": _month_label(ts)}
        for ts in dates
    ]
    if not months:
        raise ValueError("La base no contiene fechas mensuales válidas.")

    values = [item["value"] for item in months]
    preferred_base = "2026-01-01"
    default_base = preferred_base if preferred_base in values else values[max(0, len(values) - 2)]
    default_target = values[-1]

    return {
        "months": months,
        "default_base": default_base,
        "default_target": default_target,
        "default_amount": 10000,
        "series": [
            {
                "key": item["key"],
                "label": item["label"],
                "column": item["column"],
                "available": item["available"],
                "accent": item["accent"],
            }
            for item in series
        ],
    }


def calculate(df: pd.DataFrame, amount: float, base_month: str, target_month: str) -> dict[str, Any]:
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("El valor base debe ser mayor que cero.")

    dates = _date_series(df)
    series = _resolve_series(df)
    results = []

    for item in series:
        column = item["column"]
        if not column:
            results.append({
                "key": item["key"],
                "label": item["label"],
                "accent": item["accent"],
                "available": False,
                "reason": "No se encontró una columna compatible en la base.",
            })
            continue

        base_value = _month_value(df, dates, column, base_month)
        target_value = _month_value(df, dates, column, target_month)
        if base_value is None or target_value is None or base_value == 0:
            results.append({
                "key": item["key"],
                "label": item["label"],
                "accent": item["accent"],
                "available": False,
                "column": column,
                "reason": "La serie no tiene valores numéricos para ambos meses seleccionados.",
            })
            continue

        factor = target_value / base_value
        results.append({
            "key": item["key"],
            "label": item["label"],
            "accent": item["accent"],
            "available": True,
            "column": column,
            "base_index": round(base_value, 8),
            "target_index": round(target_value, 8),
            "factor": round(factor, 10),
            "variation_pct": round((factor - 1) * 100, 6),
            "updated_amount": round(amount * factor, 2),
        })

    return {
        "amount": round(amount, 2),
        "base_month": base_month,
        "target_month": target_month,
        "results": results,
        "available_count": sum(1 for item in results if item.get("available")),
    }


def create_cumpleanos_router(require_auth: Callable, load_dataframe: Callable[..., pd.DataFrame]) -> APIRouter:
    router = APIRouter(prefix="/api/cumpleanos", tags=["Panel de Cumpleaños"])

    @router.get("/meta")
    def meta(auth: bool = Depends(require_auth)):
        try:
            return build_meta(load_dataframe(force=False))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo preparar el panel: {exc}") from exc

    @router.post("/calcular")
    def calcular(body: dict, auth: bool = Depends(require_auth)):
        try:
            amount = float(body.get("amount", 0))
            base_month = str(body.get("base_month", "")).strip()
            target_month = str(body.get("target_month", "")).strip()
            if not base_month or not target_month:
                raise ValueError("Seleccioná el mes base y el mes objetivo.")
            return calculate(load_dataframe(force=False), amount, base_month, target_month)
        except HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo calcular el panel: {exc}") from exc

    return router
