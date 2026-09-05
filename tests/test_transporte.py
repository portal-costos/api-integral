from app.transporte_service import (
    detect_state,
    split_transport_resolutions,
)


def test_extracts_only_secretaria_transporte_resolutions():
    text = """
SUMARIO
MINISTERIO DE ECONOMÍA
Resolución N 22 Pág. 1
SECRETARÍA DE TRANSPORTE
Resolución N 54 Pág. 3
ENTE REGULADOR DE SERVICIOS PÚBLICOS - ERSEP
Resolución General N 9 Pág. 5

MINISTERIO DE ECONOMÍA
Resolución N 22
Córdoba, 2 de mayo de 2024
VISTO: el expediente administrativo.
EL MINISTRO DE ECONOMÍA
RESUELVE:
Artículo 1.- APRUÉBASE el gasto.
FDO.: MINISTRO DE ECONOMÍA

SECRETARÍA DE TRANSPORTE
Resolución N 54
Córdoba, 20 de mayo de 2024
VISTO: El expediente Nº 0048-123456/2024 mediante el cual la empresa SIERRAS BUS S.R.L. solicita autorización.
Y CONSIDERANDO: Que corresponde hacer lugar.
EL SECRETARIO DE TRANSPORTE
RESUELVE:
Artículo 1º.- AUTORÍCESE a la empresa SIERRAS BUS S.R.L. a prestar el servicio regular de transporte de pasajeros.
Artículo 2º.- PROTOCOLÍCESE y archívese.
FDO.: JUAN PÉREZ, SECRETARIO DE TRANSPORTE

Resolución N 55
Córdoba, 21 de mayo de 2024
VISTO: el expediente Nº 0048-222222/2024.
EL SECRETARIO DE TRANSPORTE
RESUELVE:
Artículo 1º.- AUTORÍCESE la incorporación de una unidad al parque móvil de la empresa CAMINOS S.A.
FDO.: JUAN PÉREZ, SECRETARIO DE TRANSPORTE

ENTE REGULADOR DE SERVICIOS PÚBLICOS - ERSEP
Resolución General N 9
Córdoba, 22 de mayo de 2024
VISTO: las actuaciones.
EL DIRECTORIO DEL ERSEP
RESUELVE:
Artículo 1º.- APRUÉBASE un cuadro tarifario.
FDO.: DIRECTORIO ERSEP
"""
    result = split_transport_resolutions(text)
    assert [item["numero"] for item in result] == ["Resolución N 54", "Resolución N 55"]
    assert "SIERRAS BUS" in result[0]["prestadora"]
    assert "RESUELVE" in result[0]["texto_resuelve"].upper()


def test_does_not_confuse_a_simple_reference_to_transport():
    text = """
MINISTERIO DE SEGURIDAD
Resolución N 80
Córdoba, 1 de junio de 2024
VISTO: el expediente.
EL MINISTRO DE SEGURIDAD
RESUELVE:
Artículo 1.- Comuníquese a la Secretaría de Transporte y archívese.
FDO.: MINISTRO DE SEGURIDAD

MINISTERIO DE SALUD
Resolución N 81
Córdoba, 2 de junio de 2024
VISTO: el expediente.
EL MINISTRO DE SALUD
RESUELVE:
Artículo 1.- APRUÉBASE el procedimiento.
FDO.: MINISTRO DE SALUD
"""
    assert split_transport_resolutions(text) == []


def test_transport_state_classification():
    assert detect_state("RESUELVE: AUTORÍCESE la incorporación de la unidad al parque móvil") == "INCORPORACIÓN DE UNIDAD"
    assert detect_state("RESUELVE: RECTIFICAR la Resolución N 10") == "MODIFICACIÓN / RECTIFICACIÓN"
    assert detect_state("RESUELVE: APRUÉBASE el nuevo cuadro tarifario") == "TARIFA / CUADRO TARIFARIO"
