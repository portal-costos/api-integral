from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


DEFAULT_REGULATORY_TERMS = [
    "tarifaria",
    "cuadro tarifario",
    "incremento",
    "aumento",
    "cargo tarifario",
    "audiencia pública",
    "canon",
    "valor gestión del agua",
    "VGA",
]


class AlertaCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=180)
    aliases: str = Field(default="", max_length=1500)
    active: bool = True

    @field_validator("nombre", "aliases", mode="before")
    @classmethod
    def strip_text(cls, value):
        return str(value or "").strip()


class AlertaUpdate(BaseModel):
    nombre: str = Field(min_length=2, max_length=180)
    aliases: str = Field(default="", max_length=1500)
    active: bool = True

    @field_validator("nombre", "aliases", mode="before")
    @classmethod
    def strip_text(cls, value):
        return str(value or "").strip()


class AlertaEstadoUpdate(BaseModel):
    active: bool


class MonitoreoRequest(BaseModel):
    anio: int = Field(ge=2000, le=2100)
    terminos: List[str] = Field(default_factory=lambda: list(DEFAULT_REGULATORY_TERMS))
    organismos: List[Literal["ERSEP", "APRHI"]] = Field(
        default_factory=lambda: ["ERSEP", "APRHI"], min_length=1
    )
    revalidar_pdfs: bool = False
    incluir_todas_ersep: bool = False
    mostrar_sin_cambios: bool = False
    procesar_todos: bool = False

    @field_validator("organismos", mode="before")
    @classmethod
    def normalize_issuers(cls, value):
        if value is None:
            return ["ERSEP", "APRHI"]
        if isinstance(value, str):
            value = re.split(r"[,;|\n]+", value)
        aliases = {
            "ERSEP": "ERSEP",
            "ENTEREGULADORDELOSSERVICIOSPUBLICOS": "ERSEP",
            "ENTEREGULADORDESERVICIOSPUBLICOS": "ERSEP",
            "APRHI": "APRHI",
            "ADMINISTRACIONPROVINCIALDERECURSOSHIDRICOS": "APRHI",
        }
        result: list[str] = []
        for item in value:
            key = re.sub(r"[^A-Z0-9]+", "", str(item or "").upper())
            canonical = aliases.get(key)
            if canonical and canonical not in result:
                result.append(canonical)
        return result

    @field_validator("terminos", mode="before")
    @classmethod
    def normalize_terms(cls, value):
        if value is None:
            return list(DEFAULT_REGULATORY_TERMS)
        if isinstance(value, str):
            value = re.split(r"\s+(?:O|OR)\s+|[,;|\n]+", value, flags=re.IGNORECASE)
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            key = text.casefold()
            if len(text) < 2 or key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result


class AlertaImportacionFila(BaseModel):
    fila: int = Field(ge=2)
    alias: str = Field(default="", max_length=180)
    palabras_claves: str = Field(default="", max_length=1500)
    accion: Literal["crear", "actualizar", "rechazar"]

    @field_validator("alias", "palabras_claves", mode="before")
    @classmethod
    def strip_import_text(cls, value):
        return str(value or "").strip()


class AlertaImportacionConfirmar(BaseModel):
    filas: List[AlertaImportacionFila] = Field(default_factory=list, max_length=5000)


class HistorialFilters(BaseModel):
    anio: Optional[int] = None
    organismo: Optional[str] = None
    prestadora: Optional[str] = None
    estado: Optional[str] = None
    alerta: Optional[str] = None
    texto: Optional[str] = None
    solo_novedades: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=200)
