from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.boletin_repository import BoletinRepositorio
from app.boletin_routes import create_boletin_router
from app.boletin_service import (
    BoletinJobManager,
    content_hash_for,
    detect_state,
    detect_embedded_annexes,
    extract_emission_date,
    extract_expediente,
    extract_initial_preview,
    extract_provider,
    extract_resuelve,
    match_alerts,
    normalize_text,
    split_resolutions,
    stable_key_for,
)


SIMULATED_TEXT = """
ENTE REGULADOR DE LOS SERVICIOS PÚBLICOS - ERSeP
Resolución General N° 71 - Letra:D
Córdoba, 24 de abril de 2026.-
Ref.: Expte. N° 0521-000111/2026.-
Y VISTO: Que vienen las presentes actuaciones vinculadas con la presentación
promovida por la prestadora del Servicio de Agua Cooperativa Aguas de Capilla
del Monte Limitada, por la cual solicita una revisión tarifaria.
Y CONSIDERANDO: Que corresponde resolver.
RESUELVE:
ARTÍCULO 1°: APRUÉBASE un incremento del 9,11% para el servicio de agua
sobre los cargos fijos y variables de la Cooperativa Aguas de Capilla del Monte Limitada.
ARTÍCULO 2°: PROTOCOLÍCESE, publíquese y dese copia.
FDO.: AUTORIDAD DEL ERSEP.
"""


def finding(text: str = SIMULATED_TEXT) -> dict:
    resolution = split_resolutions(text)[0]
    state = detect_state(resolution["texto_resuelve"])
    return {
        "year": 2026,
        "fecha": "27/04/2026",
        "numero": resolution["numero"],
        "prestadora": resolution["prestadora"],
        "archivo": "1_Secc_270426.pdf",
        "url": "https://boletinoficial.cba.gov.ar/wp-content/test/1_Secc_270426.pdf",
        "extracto": "APRUÉBASE un incremento del 9,11%.",
        "texto_completo": resolution["texto_completo"],
        "texto_resuelve": resolution["texto_resuelve"],
        "estado_detectado": state,
        "alertas": ["Capilla del Monte"],
        "terminos_encontrados": ["incremento", "tarifaria"],
        "warning": "",
    }


def test_text_extraction_and_state():
    resolutions = split_resolutions(SIMULATED_TEXT)
    assert len(resolutions) == 1
    assert "71" in resolutions[0]["numero"]
    assert "Capilla del Monte" in resolutions[0]["prestadora"]
    assert "APRUÉBASE" in resolutions[0]["texto_resuelve"]
    assert detect_state(resolutions[0]["texto_resuelve"]) == "APROBACIÓN TARIFARIA"
    assert resolutions[0]["expediente"] == "0521-000111/2026"
    assert resolutions[0]["fecha_emision"] == "24/04/2026"


def test_provider_and_resuelve_are_independently_testable():
    assert "Capilla del Monte" in extract_provider(SIMULATED_TEXT)
    assert extract_resuelve(SIMULATED_TEXT).startswith("RESUELVE")



def test_provider_does_not_include_service_prefix():
    text = (
        "presentación promovida por la prestadora del Servicio de Agua "
        "Aguas Cordobesas S.A., por la cual solicita una revisión."
    )
    assert extract_provider(text) == "Aguas Cordobesas S.A"

def test_alert_matching_uses_complete_aliases_and_avoids_generic_words():
    alerts = [
        {"id": 1, "nombre": "Capilla del Monte", "aliases": "Aguas de Capilla del Monte; Capilla del Monte"},
        {"id": 2, "nombre": "Genérica", "aliases": "cooperativa; servicios públicos"},
    ]
    matches = match_alerts(SIMULATED_TEXT, alerts)
    assert [item["id"] for item in matches] == [1]


def test_preview_is_initial_paragraph_and_missing_expediente_is_not_invented():
    preview = extract_initial_preview(SIMULATED_TEXT)
    assert "Y VISTO" in preview
    assert "Y CONSIDERANDO" not in preview
    assert extract_expediente(SIMULATED_TEXT) == "0521-000111/2026"
    assert extract_emission_date(SIMULATED_TEXT) == "24/04/2026"
    assert extract_expediente("VISTO: las actuaciones administrativas.") == ""
    assert (
        extract_expediente("Ref.: Expediente EX-2024-00869502- -UNC-ME#FCE")
        == "EX-2024-00869502- -UNC-ME#FCE"
    )


def test_embedded_annex_detection_preserves_relationship_with_resolution():
    text = SIMULATED_TEXT + "\n\nANEXO I\nCUADRO TARIFARIO\nCargo fijo: $ 1.000"
    annexes = detect_embedded_annexes(text, "https://boletinoficial.cba.gov.ar/a.pdf")
    assert len(annexes) == 1
    assert annexes[0]["nombre"] == "ANEXO I"
    assert "CUADRO TARIFARIO" in annexes[0]["texto"]
    assert annexes[0]["tipo"] == "integrado"


def test_hash_is_stable_and_changes_with_content():
    first = finding()
    second = dict(first)
    assert stable_key_for(2026, first["numero"]) == stable_key_for(2026, first["numero"])
    assert content_hash_for(first) == content_hash_for(second)
    second["texto_resuelve"] += " TEXTO NUEVO"
    assert content_hash_for(first) != content_hash_for(second)
    assert normalize_text("Resolución ÁÉÍ") == "resolucion aei"


def test_repository_new_unchanged_modified_and_alert_crud():
    with tempfile.TemporaryDirectory() as directory:
        repo = BoletinRepositorio(Path(directory) / "test.sqlite3")
        created = repo.create_alert("Capilla del Monte", "Aguas de Capilla del Monte", True)
        assert created["active"] is True
        updated = repo.update_alert(created["id"], "Capilla del Monte", "Capilla; Aguas de Capilla del Monte", False)
        assert updated and updated["active"] is False
        active = repo.set_alert_state(created["id"], True)
        assert active and active["active"] is True

        item = finding()
        stable = stable_key_for(2026, item["numero"])

        run1 = repo.create_run(2026, {})
        result1 = repo.register_publication(run1, item, stable, content_hash_for(item))
        assert result1["novedad"] == "NUEVO"

        run2 = repo.create_run(2026, {})
        result2 = repo.register_publication(run2, item, stable, content_hash_for(item))
        assert result2["novedad"] == "SIN CAMBIOS"

        changed = dict(item)
        changed["texto_resuelve"] += "\nARTÍCULO 3°: MODIFÍCASE el cuadro tarifario."
        changed["estado_detectado"] = "RECTIFICACIÓN / MODIFICACIÓN"
        run3 = repo.create_run(2026, {})
        result3 = repo.register_publication(run3, changed, stable, content_hash_for(changed))
        assert result3["novedad"] == "MODIFICADO"

        detail = repo.get_publication(result3["publication_id"])
        assert detail and detail["verification_count"] == 3
        assert detail["last_change_type"] == "MODIFICADO"
        assert repo.delete_alert(created["id"]) is True


def test_duplicate_alert_is_updated_and_versioned_instead_of_duplicated():
    with tempfile.TemporaryDirectory() as directory:
        repo = BoletinRepositorio(Path(directory) / "test.sqlite3", seed_default_alerts=False)
        first = repo.create_alert("Prestadora Uno", "Nombre legal | Sigla", True)
        second = repo.create_alert(" prestadora uno ", "Nombre actualizado", True)
        assert first["id"] == second["id"]
        assert second["current_version"] == 2
        assert second["aliases"] == "Nombre actualizado"
        assert len(repo.list_alerts()) == 1


def test_complete_information_updates_metadata_and_annexes_without_new_record():
    with tempfile.TemporaryDirectory() as directory:
        repo = BoletinRepositorio(Path(directory) / "test.sqlite3", seed_default_alerts=False)
        item = finding()
        run_id = repo.create_run(2026, {})
        registered = repo.register_publication(
            run_id,
            item,
            stable_key_for(2026, item["numero"]),
            content_hash_for(item),
        )
        manager = BoletinJobManager(repo, timeout=10)
        manager._download_pdf_bytes = lambda *args, **kwargs: b"%PDF-fake"  # type: ignore[method-assign]
        manager._extract_pdf_text = lambda content: SIMULATED_TEXT + "\nANEXO I\nCUADRO TARIFARIO"  # type: ignore[method-assign]
        manager._discover_linked_annexes = lambda *args, **kwargs: []  # type: ignore[method-assign]
        detail = repo.get_publication(registered["publication_id"])
        updated = manager.extract_complete_information(detail)
        assert updated["id"] == registered["publication_id"]
        assert updated["expediente_number"] == "0521-000111/2026"
        assert updated["emission_date"] == "24/04/2026"
        assert updated["issuing_body"].endswith("(ERSeP)")
        assert updated["annexes"][0]["nombre"] == "ANEXO I"
        assert updated["informacion_completa"]["expediente"] == "0521-000111/2026"


def test_health_and_alert_endpoints_respond():
    with tempfile.TemporaryDirectory() as directory:
        app = FastAPI()

        def require_auth():
            return True

        app.include_router(create_boletin_router(require_auth, Path(directory), 10))
        client = TestClient(app)

        health = client.get("/api/boletin/health")
        assert health.status_code == 200
        assert "pymupdf_available" in health.json()

        response = client.post(
            "/api/boletin/alertas",
            json={"nombre": "Prueba", "aliases": "Cooperativa de Prueba", "active": True},
        )
        assert response.status_code == 201
        alert_id = response.json()["id"]

        assert client.get("/api/boletin/alertas").status_code == 200
        assert client.patch(
            f"/api/boletin/alertas/{alert_id}/estado", json={"active": False}
        ).status_code == 200
        assert client.delete(f"/api/boletin/alertas/{alert_id}").status_code == 200


def test_bulk_alert_import_previews_and_updates_duplicates():
    with tempfile.TemporaryDirectory() as directory:
        app = FastAPI()

        def require_auth():
            return True

        router = create_boletin_router(require_auth, Path(directory), 10)
        app.include_router(router)
        client = TestClient(app)
        client.post(
            "/api/boletin/alertas",
            json={"nombre": "Existente", "aliases": "Nombre anterior", "active": True},
        )
        stream = BytesIO()
        pd.DataFrame(
            [
                {"ALIAS": "Existente", "PALABRAS CLAVES": "Nombre nuevo | Sigla"},
                {"ALIAS": "Nueva", "PALABRAS CLAVES": "Nueva completa | Nueva abreviada"},
                {"ALIAS": "Incompleta", "PALABRAS CLAVES": ""},
            ]
        ).to_excel(stream, index=False)
        preview_response = client.post(
            "/api/boletin/alertas/importacion/vista-previa",
            files={
                "file": (
                    "alertas.xlsx",
                    stream.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["resumen"]["total_incorporar"] == 2
        assert preview["resumen"]["se_actualizaran"] == 1
        assert preview["resumen"]["filas_incompletas"] == 1
        confirmation = client.post(
            "/api/boletin/alertas/importacion/confirmar",
            json={
                "filas": [
                    {
                        "fila": row["fila"],
                        "alias": row["alias"],
                        "palabras_claves": row["palabras_claves"],
                        "accion": row["accion"],
                    }
                    for row in preview["filas"]
                ]
            },
        )
        assert confirmation.status_code == 200
        assert confirmation.json()["creadas"] == 1
        assert confirmation.json()["actualizadas"] == 1
        assert confirmation.json()["rechazadas"] == 1


def test_required_routes_and_frontend_files_exist():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "static/boletin.html",
        "static/boletin.css",
        "static/boletin.js",
        "app/boletin_models.py",
        "app/boletin_repository.py",
        "app/boletin_service.py",
        "app/boletin_routes.py",
    ):
        assert (root / relative).exists(), relative

    app = FastAPI()

    def require_auth():
        return True

    with tempfile.TemporaryDirectory() as directory:
        app.include_router(create_boletin_router(require_auth, Path(directory), 10))
        paths = {route.path for route in app.routes}
        expected = {
            "/api/boletin/health",
            "/api/boletin/alertas",
            "/api/boletin/monitorear",
            "/api/boletin/monitoreo/{run_id}",
            "/api/boletin/monitoreo/{run_id}/detener",
            "/api/boletin/monitoreo/{run_id}/resultados",
            "/api/boletin/historial",
            "/api/boletin/publicaciones/{publicacion_id}",
            "/api/boletin/publicaciones/{publicacion_id}/pdf",
            "/api/boletin/publicaciones/{publicacion_id}/extraer-completo",
            "/api/boletin/publicaciones/{publicacion_id}/obtener-informacion-completa",
            "/api/boletin/publicaciones/{publicacion_id}/anexos/{annex_index}/pdf",
            "/api/boletin/alertas/importacion/plantilla",
            "/api/boletin/alertas/importacion/vista-previa",
            "/api/boletin/alertas/importacion/confirmar",
            "/api/boletin/exportar",
        }
        assert expected.issubset(paths)

    index = (root / "static/index.html").read_text(encoding="utf-8")
    script = (root / "static/script.js").read_text(encoding="utf-8")
    assert 'id="menu_boletin"' in index
    assert 'id="btn_boletin"' in index
    assert '"/static/boletin.html"' in script
    boletin_html = (root / "static/boletin.html").read_text(encoding="utf-8")
    boletin_js = (root / "static/boletin.js").read_text(encoding="utf-8")
    assert "Fecha del Boletín" in boletin_html
    assert "Expediente no identificado" in boletin_js
    assert "Datos copiados al portapapeles" in boletin_js
    assert "Procesar todos" in boletin_html
    assert "PALABRAS CLAVES" in boletin_html


def test_new_module_has_no_developer_absolute_windows_paths():
    root = Path(__file__).resolve().parents[1]
    text = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in (
            "app/boletin_models.py",
            "app/boletin_repository.py",
            "app/boletin_service.py",
            "app/boletin_routes.py",
            "static/boletin.js",
        )
    )
    assert "C:\\Users\\" not in text
    assert "C:/Users/" not in text
