from __future__ import annotations

from pydantic import BaseModel, Field


class TransporteMonitoreoRequest(BaseModel):
    anio: int = Field(ge=2000, le=2100)
    revalidar_pdfs: bool = False
    mostrar_sin_cambios: bool = False
