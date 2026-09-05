"""Motor de intereses resarcitorios ARCA, independiente de la interfaz.

La implementación conserva la convención utilizada por la calculadora oficial:
meses completos + días/30 y redondeo por tramo.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

FMIN = "27/01/1988"
FMAX_INT = 20991231


@dataclass(slots=True)
class TasaTramo:
    desde: date
    hasta: Optional[date]
    norma: str
    resarcitorio_mensual: float
    resarcitorio_diario: Optional[float] = None
    punitorio_mensual: Optional[float] = None
    punitorio_diario: Optional[float] = None
    fuente: str = "ARCA"


@dataclass(slots=True)
class DetalleTramo:
    desde_calc_int: int
    hasta_calc_int: int
    desde_mostrado: str
    hasta_mostrado: str
    importe: float
    tipo: str
    tasa_mensual: float
    tasa_diaria: float
    meses: int
    dias: int
    dias_transcurridos: int
    intereses: float
    norma: str = ""
    fuente: str = ""


@dataclass(slots=True)
class ResultadoCalculo:
    ok: bool
    error: str = ""
    fecha_vencimiento: str = ""
    fecha_pago_capital: str = ""
    fecha_pago_intereses: str = ""
    importe_capital: float = 0.0
    intereses_resarcitorios: float = 0.0
    intereses_capitalizados: float = 0.0
    intereses_total: float = 0.0
    dias_transcurridos: int = 0
    suma_tasas_intermedias: float = 0.0
    detalle: list[DetalleTramo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def redondeo(valor: float, prec: int) -> float:
    if valor is None or pd.isna(valor):
        return 0.0
    return round(float(valor) * (10**prec)) / (10**prec)


def parse_fecha(valor: Any) -> Optional[date]:
    """Acepta fechas de Excel, strings, datetime, date o serial Excel."""
    if valor is None:
        return None

    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass

    if isinstance(valor, pd.Timestamp):
        return valor.date()
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            if float(valor) > 1000:
                return (datetime(1899, 12, 30) + timedelta(days=int(valor))).date()
        except Exception:
            pass

    s = str(valor).strip()
    if not s or s.lower() in {"nat", "nan", "none"}:
        return None

    s = re.sub(r"\s+00:00:00$", "", s)
    for fmt in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%y",
        "%d-%m-%y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if not pd.isna(dt):
        return pd.Timestamp(dt).date()
    return None


def s_to_d(valor: Any) -> int:
    f = parse_fecha(valor)
    if not f:
        return 0
    return f.year * 10000 + f.month * 100 + f.day


def d_to_date(n: int) -> date:
    s = str(int(n)).zfill(8)
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def d_to_s(n: int) -> str:
    f = d_to_date(n)
    return f"{f.day:02d}/{f.month:02d}/{f.year:04d}"


def date_to_s(f: Any) -> str:
    parsed = parse_fecha(f)
    if not parsed:
        return ""
    return f"{parsed.day:02d}/{parsed.month:02d}/{parsed.year:04d}"


def dia_menos(n: int) -> int:
    return s_to_d(d_to_date(n) - timedelta(days=1))


def dia_mas(n: int) -> int:
    return s_to_d(d_to_date(n) + timedelta(days=1))


def sum_meses(n: int, meses: int) -> int:
    f = d_to_date(n)
    total_month = f.month + meses
    year = f.year + (total_month - 1) // 12
    month = ((total_month - 1) % 12) + 1
    day = f.day
    while day > 0:
        try:
            return s_to_d(date(year, month, day))
        except ValueError:
            day -= 1
    raise ValueError("No se pudo sumar meses a la fecha.")


def dif_dias(fec_mayor: int, fec_menor: int) -> int:
    return (d_to_date(fec_mayor) - d_to_date(fec_menor)).days


def dif_fecha(fec_mayor: int, fec_menor: int) -> tuple[int, int]:
    """Devuelve meses y días siguiendo la lógica financiera de ARCA."""
    f7 = d_to_date(fec_mayor)
    f6 = d_to_date(fec_menor)
    meses = (f7.year - f6.year) * 12 + f7.month - f6.month
    if f6.day > f7.day:
        meses -= 1
        dias = dif_dias(fec_mayor, sum_meses(fec_menor, meses))
    else:
        dias = f7.day - f6.day
    return meses, dias


def normalizar_numero(valor: Any) -> Optional[float]:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass

    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if math.isnan(float(valor)):
            return None
        return float(valor)

    s = str(valor).strip().replace("$", "").replace("%", "").replace("\u00a0", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    else:
        partes = s.split(".")
        if len(partes) > 1 and len(partes[-1]) == 3 and all(p.isdigit() for p in partes):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def normalizar_col(valor: Any) -> str:
    s = str(valor).strip().lower()
    s = s.translate(str.maketrans("áéíóúüñ", "aeiouun"))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def buscar_columna(cols_norm: dict[str, str], candidatos: list[str]) -> Optional[str]:
    cand_norm = [normalizar_col(c) for c in candidatos]
    for candidate in cand_norm:
        if candidate in cols_norm:
            return cols_norm[candidate]
    for candidate in cand_norm:
        for normalized, real in cols_norm.items():
            if candidate in normalized or normalized in candidate:
                return real
    return None


def sugerir_mapeo(columnas: list[str]) -> dict[str, str]:
    norm = {normalizar_col(c): c for c in columnas}
    return {
        "fecha_vencimiento": buscar_columna(
            norm, ["fecha vencimiento", "vencimiento", "rdesde", "fecha vto", "vto"]
        )
        or "",
        "fecha_pago_capital": buscar_columna(
            norm, ["fecha pago capital", "pago capital", "rhasta", "fecha pago", "pago"]
        )
        or "",
        "importe_capital": buscar_columna(
            norm, ["importe capital", "importe", "capital", "rimpor", "monto", "deuda"]
        )
        or "",
        "fecha_pago_intereses": buscar_columna(
            norm, ["fecha pago intereses", "pago intereses", "rcapit", "intereses"]
        )
        or "",
    }


def df_tasas_a_tramos(df: pd.DataFrame) -> list[TasaTramo]:
    tramos: list[TasaTramo] = []
    for _, row in df.iterrows():
        f_desde = parse_fecha(row.get("Desde"))
        tasa = normalizar_numero(row.get("Resarcitorio mensual"))
        if not f_desde or tasa is None:
            continue
        tramos.append(
            TasaTramo(
                desde=f_desde,
                hasta=parse_fecha(row.get("Hasta")),
                norma=str(row.get("Norma", "") or ""),
                resarcitorio_mensual=float(tasa),
                resarcitorio_diario=normalizar_numero(row.get("Resarcitorio diario")),
                punitorio_mensual=normalizar_numero(row.get("Punitorio mensual")),
                punitorio_diario=normalizar_numero(row.get("Punitorio diario")),
                fuente=str(row.get("Fuente", "") or ""),
            )
        )
    tramos.sort(key=lambda x: x.desde)
    if not tramos:
        raise ValueError("No hay tramos de tasas válidos.")
    return tramos


class MotorARCA:
    """Motor de cálculo compatible con la lógica histórica del panel ARCA."""

    def __init__(self, tramos: list[TasaTramo]):
        self.tramos = sorted(tramos, key=lambda t: t.desde)
        self._construir_indices()

    def _construir_indices(self) -> None:
        self.tdes = [0]
        self.thas = [0]
        self.tasas = [0.0]
        self.normas = [""]
        self.fuentes = [""]

        n = len(self.tramos)
        for i, tramo in enumerate(self.tramos, start=1):
            self.tdes.append(s_to_d(tramo.desde))
            self.thas.append(0)
            self.tasas.append(float(tramo.resarcitorio_mensual))
            self.normas.append(tramo.norma)
            self.fuentes.append(tramo.fuente)
            if i > 1:
                self.thas[i - 1] = dia_menos(self.tdes[i])
                # Particularidad preservada de la calculadora histórica. El día que se
                # muestra al usuario se corrige con dia_mas(des_x).
                self.tdes[i] = self.thas[i - 1]
        self.thas[n] = FMAX_INT

    def calc(
        self,
        fecha_inicio: Any,
        fecha_fin: Any,
        capital: float,
        tipo: str,
    ) -> tuple[float, int, float, list[DetalleTramo]]:
        f001 = s_to_d(fecha_inicio)
        f002 = s_to_d(fecha_fin)
        total_intereses = 0.0
        dias_totales = 0
        suma_tasas = 0.0
        detalles: list[DetalleTramo] = []
        mini = False
        maxi = False

        for x in range(1, len(self.tdes)):
            todo = True
            des_x: Optional[int] = None
            has_x: Optional[int] = None

            if not mini and self.tdes[x] <= f001 <= self.thas[x]:
                des_x = f001
                mini = True
                todo = False

            if mini:
                if f002 <= self.thas[x]:
                    if todo:
                        des_x = self.tdes[x]
                    has_x = f002
                    maxi = True
                else:
                    if not todo:
                        has_x = self.thas[x]
                    else:
                        des_x = self.tdes[x]
                        has_x = self.thas[x]

                if des_x is not None and has_x is not None:
                    meses, dias = dif_fecha(has_x, des_x)
                    dias_tramo = meses * 30 + dias
                    tasa_mensual = self.tasas[x]
                    tasa_diaria = redondeo(tasa_mensual / 30, 6)
                    interes_tramo = redondeo(
                        (meses + dias / 30) * tasa_mensual * float(capital) / 100,
                        2,
                    )
                    total_intereses += interes_tramo
                    dias_totales += dias_tramo
                    suma_tasas += tasa_diaria
                    detalles.append(
                        DetalleTramo(
                            desde_calc_int=des_x,
                            hasta_calc_int=has_x,
                            desde_mostrado=d_to_s(dia_mas(des_x)),
                            hasta_mostrado=d_to_s(has_x),
                            importe=float(capital),
                            tipo=tipo,
                            tasa_mensual=tasa_mensual,
                            tasa_diaria=tasa_diaria,
                            meses=meses,
                            dias=dias,
                            dias_transcurridos=dias_tramo,
                            intereses=interes_tramo,
                            norma=self.normas[x],
                            fuente=self.fuentes[x],
                        )
                    )

            if mini and maxi:
                break

        return (
            redondeo(total_intereses, 2),
            dias_totales,
            redondeo(suma_tasas, 6),
            detalles,
        )

    def calcular_fila(
        self,
        vencimiento: Any,
        pago_capital: Any,
        importe: Any,
        pago_intereses: Any = None,
    ) -> ResultadoCalculo:
        f_vto = parse_fecha(vencimiento)
        f_pago = parse_fecha(pago_capital)
        f_int = parse_fecha(pago_intereses) if pago_intereses not in (None, "") else None
        imp = normalizar_numero(importe)

        if not f_vto:
            return ResultadoCalculo(False, "Fecha de vencimiento inválida")
        if s_to_d(f_vto) < s_to_d(FMIN):
            return ResultadoCalculo(False, f"Fecha de vencimiento menor a {FMIN}")
        if not f_pago:
            return ResultadoCalculo(False, "Fecha de pago del capital inválida")
        if s_to_d(f_pago) <= s_to_d(f_vto):
            return ResultadoCalculo(False, "Fecha de pago del capital debe ser mayor al vencimiento")
        if imp is None or imp <= 0:
            return ResultadoCalculo(False, "Importe del capital inválido o cero")
        if f_int and s_to_d(f_int) <= s_to_d(f_vto):
            return ResultadoCalculo(False, "Fecha de pago de intereses debe ser mayor al vencimiento")

        tres, dias1, tasas1, detalle1 = self.calc(f_vto, f_pago, imp, "Res")
        tcap = 0.0
        dias2 = 0
        tasas2 = 0.0
        detalle2: list[DetalleTramo] = []

        if f_int and s_to_d(f_int) > s_to_d(f_pago):
            tcap, dias2, tasas2, detalle2 = self.calc(f_pago, f_int, tres, "Cap")

        return ResultadoCalculo(
            ok=True,
            fecha_vencimiento=date_to_s(f_vto),
            fecha_pago_capital=date_to_s(f_pago),
            fecha_pago_intereses=date_to_s(f_int) if f_int else "",
            importe_capital=float(imp),
            intereses_resarcitorios=redondeo(tres, 2),
            intereses_capitalizados=redondeo(tcap, 2),
            intereses_total=redondeo(tres + tcap, 2),
            dias_transcurridos=dias1 + dias2,
            suma_tasas_intermedias=redondeo(tasas1 + tasas2, 6),
            detalle=detalle1 + detalle2,
        )
