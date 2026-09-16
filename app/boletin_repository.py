from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_ALERTS = [
    ("Aguas Cordobesas S.A.", "Aguas Cordobesas | Aguas Cordobesas S.A."),
    ("COOPI", "COOPI | Cooperativa Integral Regional | Cooperativa Integral"),
    (
        "Cooperativa de Trabajo Sudeste Ltda.",
        "Cooperativa de Trabajo Sudeste | Sudeste Ltda. | Cooperativa Sudeste",
    ),
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def normalize_alert_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip()


def canonical_keywords(value: Any, fallback: str = "") -> str:
    """Guarda alternativas con `|`; la interfaz las presenta con la palabra «O»."""
    raw = str(value or "").strip()
    pieces = re.split(r"\s*(?:\||;|\n|\r)\s*", raw) if raw else []
    if not pieces and fallback:
        pieces = [fallback]
    output: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        phrase = re.sub(r"\s+", " ", str(piece or "")).strip(" .,-")
        key = normalize_alert_key(phrase)
        if not phrase or key in seen:
            continue
        seen.add(key)
        output.append(phrase)
    return " | ".join(output)


class BoletinRepositorio:
    """Persistencia SQLite aislada del frontend y segura para varios hilos.

    Cada operación abre su propia conexión. SQLite conserva el historial,
    mientras que el administrador de trabajos solo mantiene el estado temporal
    de ejecución en memoria.
    """

    def __init__(self, db_path: Path | str, seed_default_alerts: bool = True):
        self.db_path = Path(db_path).resolve()
        self.seed_default_alerts = bool(seed_default_alerts)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    current_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alert_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    version_number INTEGER NOT NULL,
                    nombre TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    changed_at TEXT NOT NULL,
                    UNIQUE(alert_id, version_number),
                    FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    current_month INTEGER NOT NULL DEFAULT 0,
                    current_message TEXT NOT NULL DEFAULT '',
                    progress_percent REAL NOT NULL DEFAULT 0,
                    months_scanned INTEGER NOT NULL DEFAULT 0,
                    pdfs_seen INTEGER NOT NULL DEFAULT 0,
                    pdfs_processed INTEGER NOT NULL DEFAULT 0,
                    pdfs_cached INTEGER NOT NULL DEFAULT 0,
                    resolutions_seen INTEGER NOT NULL DEFAULT 0,
                    relevant_count INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0,
                    changed_count INTEGER NOT NULL DEFAULT 0,
                    unchanged_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    config_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stable_key TEXT NOT NULL UNIQUE,
                    year INTEGER NOT NULL,
                    publication_date TEXT,
                    emission_date TEXT,
                    resolution_number TEXT NOT NULL,
                    expediente_number TEXT,
                    provider TEXT,
                    issuing_body TEXT,
                    source_pdf TEXT,
                    source_url TEXT,
                    source_page_url TEXT,
                    extract_text TEXT,
                    text_full TEXT,
                    text_resuelve TEXT,
                    annexes_json TEXT NOT NULL DEFAULT '[]',
                    annex_text TEXT,
                    complete_extracted_at TEXT,
                    content_hash TEXT NOT NULL,
                    detected_state TEXT,
                    matched_alerts_json TEXT NOT NULL DEFAULT '[]',
                    regulatory_terms_json TEXT NOT NULL DEFAULT '[]',
                    warning TEXT NOT NULL DEFAULT '',
                    first_seen_run INTEGER,
                    last_seen_run INTEGER,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    verification_count INTEGER NOT NULL DEFAULT 1,
                    last_change_type TEXT NOT NULL DEFAULT 'NUEVO',
                    is_modified INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_id INTEGER NOT NULL,
                    run_id INTEGER NOT NULL,
                    change_type TEXT NOT NULL,
                    previous_hash TEXT,
                    new_hash TEXT,
                    previous_state TEXT,
                    new_state TEXT,
                    detected_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    FOREIGN KEY(publication_id) REFERENCES publications(id),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );

                CREATE TABLE IF NOT EXISTS pdf_cache (
                    url TEXT PRIMARY KEY,
                    year INTEGER,
                    month INTEGER,
                    filename TEXT,
                    publication_date TEXT,
                    pdf_hash TEXT,
                    parser_version INTEGER NOT NULL DEFAULT 1,
                    resolutions_json TEXT NOT NULL,
                    warning TEXT NOT NULL DEFAULT '',
                    last_checked_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    publication_id INTEGER NOT NULL,
                    change_type TEXT NOT NULL,
                    visible INTEGER NOT NULL DEFAULT 1,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, publication_id),
                    FOREIGN KEY(run_id) REFERENCES runs(id),
                    FOREIGN KEY(publication_id) REFERENCES publications(id)
                );

                CREATE TABLE IF NOT EXISTS run_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    month INTEGER,
                    source_url TEXT,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active);
                CREATE INDEX IF NOT EXISTS idx_alert_versions_alert ON alert_versions(alert_id, version_number);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, started_at);
                CREATE INDEX IF NOT EXISTS idx_publications_year_date ON publications(year, publication_date);
                CREATE INDEX IF NOT EXISTS idx_publications_provider ON publications(provider);
                CREATE INDEX IF NOT EXISTS idx_publications_state ON publications(detected_state);
                CREATE INDEX IF NOT EXISTS idx_publications_last_run ON publications(last_seen_run);
                CREATE INDEX IF NOT EXISTS idx_changes_run ON changes(run_id, change_type);
                CREATE INDEX IF NOT EXISTS idx_run_results_run ON run_results(run_id, visible);
                """
            )
            self._migrate_columns(con)
            count = int(con.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
            if self.seed_default_alerts and count == 0:
                current = now_iso()
                con.executemany(
                    "INSERT INTO alerts(nombre, keywords, active, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                    [(name, aliases, current, current) for name, aliases in DEFAULT_ALERTS],
                )
            con.execute(
                """
                INSERT OR IGNORE INTO alert_versions(
                    alert_id, version_number, nombre, keywords, active, changed_at
                )
                SELECT id, COALESCE(current_version, 1), nombre, keywords, active, updated_at
                FROM alerts
                """
            )

    @staticmethod
    def _migrate_columns(con: sqlite3.Connection) -> None:
        """Agrega columnas nuevas al abrir una base creada por la versión Tkinter."""
        expected: dict[str, dict[str, str]] = {
            "runs": {
                "current_month": "INTEGER NOT NULL DEFAULT 0",
                "current_message": "TEXT NOT NULL DEFAULT ''",
                "progress_percent": "REAL NOT NULL DEFAULT 0",
                "warning_count": "INTEGER NOT NULL DEFAULT 0",
                "config_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "publications": {
                "extract_text": "TEXT",
                "emission_date": "TEXT",
                "expediente_number": "TEXT",
                "issuing_body": "TEXT",
                "source_page_url": "TEXT",
                "annexes_json": "TEXT NOT NULL DEFAULT '[]'",
                "annex_text": "TEXT",
                "complete_extracted_at": "TEXT",
                "warning": "TEXT NOT NULL DEFAULT ''",
                "verification_count": "INTEGER NOT NULL DEFAULT 1",
                "last_change_type": "TEXT NOT NULL DEFAULT 'NUEVO'",
                "is_modified": "INTEGER NOT NULL DEFAULT 0",
            },
            "pdf_cache": {
                "warning": "TEXT NOT NULL DEFAULT ''",
                "parser_version": "INTEGER NOT NULL DEFAULT 1",
            },
            "alerts": {"current_version": "INTEGER NOT NULL DEFAULT 1"},
        }
        for table, columns in expected.items():
            existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    # ------------------------------------------------------------------
    # Alertas
    # ------------------------------------------------------------------
    def list_alerts(self, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM alerts"
        params: list[Any] = []
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY active DESC, nombre COLLATE NOCASE"
        with self.connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._alert_row(row) for row in rows]

    def get_alert(self, alert_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM alerts WHERE id=?", (int(alert_id),)).fetchone()
        return self._alert_row(row) if row else None

    def get_alert_by_name(self, nombre: str) -> Optional[dict[str, Any]]:
        target = normalize_alert_key(nombre)
        if not target:
            return None
        for item in self.list_alerts():
            if normalize_alert_key(item.get("nombre")) == target:
                return item
        return None

    @staticmethod
    def _alert_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["active"] = bool(data.get("active"))
        data["aliases"] = data.pop("keywords", "")
        return data

    def create_alert(self, nombre: str, aliases: str, active: bool = True) -> dict[str, Any]:
        nombre = str(nombre or "").strip()
        if not nombre:
            raise ValueError("El nombre de la alerta es obligatorio.")
        aliases = canonical_keywords(aliases, nombre)
        existing = self.get_alert_by_name(nombre)
        if existing:
            updated = self.update_alert(int(existing["id"]), nombre, aliases, active)
            if updated:
                updated["import_action"] = "actualizar"
                return updated
        current = now_iso()
        with self.connect() as con:
            cursor = con.execute(
                "INSERT INTO alerts(nombre, keywords, active, current_version, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                (nombre, aliases, int(active), current, current),
            )
            alert_id = int(cursor.lastrowid)
            con.execute(
                "INSERT INTO alert_versions(alert_id, version_number, nombre, keywords, active, changed_at) "
                "VALUES (?, 1, ?, ?, ?, ?)",
                (alert_id, nombre, aliases, int(active), current),
            )
        created = self.get_alert(alert_id)  # type: ignore[assignment]
        created["import_action"] = "crear"
        return created

    def update_alert(self, alert_id: int, nombre: str, aliases: str, active: bool) -> Optional[dict[str, Any]]:
        nombre = str(nombre or "").strip()
        if not nombre:
            raise ValueError("El nombre de la alerta es obligatorio.")
        aliases = canonical_keywords(aliases, nombre)
        duplicate = self.get_alert_by_name(nombre)
        if duplicate and int(duplicate["id"]) != int(alert_id):
            raise ValueError("Ya existe otra alerta con ese alias; editá la alerta existente.")
        current = now_iso()
        with self.connect() as con:
            current_row = con.execute(
                "SELECT current_version FROM alerts WHERE id=?", (int(alert_id),)
            ).fetchone()
            if not current_row:
                return None
            version = int(current_row["current_version"] or 1) + 1
            cursor = con.execute(
                "UPDATE alerts SET nombre=?, keywords=?, active=?, current_version=?, updated_at=? WHERE id=?",
                (nombre, aliases, int(active), version, current, int(alert_id)),
            )
            if cursor.rowcount == 0:
                return None
            con.execute(
                "INSERT INTO alert_versions(alert_id, version_number, nombre, keywords, active, changed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (int(alert_id), version, nombre, aliases, int(active), current),
            )
        return self.get_alert(alert_id)

    def upsert_alert(self, nombre: str, aliases: str, active: bool = True) -> tuple[dict[str, Any], str]:
        existing = self.get_alert_by_name(nombre)
        if existing:
            updated = self.update_alert(int(existing["id"]), nombre, aliases, active)
            if not updated:  # pragma: no cover - carrera defensiva
                raise ValueError("No se pudo actualizar la alerta existente.")
            return updated, "actualizar"
        created = self.create_alert(nombre, aliases, active)
        return created, "crear"

    def set_alert_state(self, alert_id: int, active: bool) -> Optional[dict[str, Any]]:
        item = self.get_alert(alert_id)
        if not item:
            return None
        return self.update_alert(
            int(alert_id), item.get("nombre", ""), item.get("aliases", ""), bool(active)
        )

    def delete_alert(self, alert_id: int) -> bool:
        with self.connect() as con:
            cursor = con.execute("DELETE FROM alerts WHERE id=?", (int(alert_id),))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Ejecuciones y progreso
    # ------------------------------------------------------------------
    def create_run(self, year: int, config: dict[str, Any]) -> int:
        with self.connect() as con:
            cursor = con.execute(
                "INSERT INTO runs(year, started_at, status, config_json, current_message) VALUES (?, ?, 'PENDING', ?, ?)",
                (int(year), now_iso(), json.dumps(config, ensure_ascii=False), "Ejecución en cola."),
            )
            return int(cursor.lastrowid)

    def update_run(self, run_id: int, *, status: Optional[str] = None, stats: Optional[dict[str, Any]] = None,
                   current_month: Optional[int] = None, progress_percent: Optional[float] = None,
                   message: Optional[str] = None, finished: bool = False) -> None:
        assignments: list[str] = []
        values: list[Any] = []
        if status is not None:
            assignments.append("status=?")
            values.append(status)
        if current_month is not None:
            assignments.append("current_month=?")
            values.append(int(current_month))
        if progress_percent is not None:
            assignments.append("progress_percent=?")
            values.append(max(0.0, min(100.0, float(progress_percent))))
        if message is not None:
            assignments.append("current_message=?")
            values.append(str(message)[:1000])
        if stats:
            for field in (
                "months_scanned", "pdfs_seen", "pdfs_processed", "pdfs_cached",
                "resolutions_seen", "relevant_count", "new_count", "changed_count",
                "unchanged_count", "error_count", "warning_count",
            ):
                if field in stats:
                    assignments.append(f"{field}=?")
                    values.append(int(stats[field]))
        if finished:
            assignments.append("finished_at=?")
            values.append(now_iso())
        if not assignments:
            return
        values.append(int(run_id))
        with self.connect() as con:
            con.execute(f"UPDATE runs SET {', '.join(assignments)} WHERE id=?", values)

    def get_run(self, run_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM runs WHERE id=?", (int(run_id),)).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["config"] = json.loads(data.pop("config_json", "{}"))
        except Exception:
            data["config"] = {}
        data["run_id"] = data.pop("id")
        return data

    def interrupt_unfinished_runs(self) -> None:
        """Marca como interrumpidas las ejecuciones que quedaron abiertas tras un cierre del servidor."""
        with self.connect() as con:
            con.execute(
                "UPDATE runs SET status='INTERRUPTED', finished_at=?, "
                "current_message='Ejecución interrumpida por reinicio del servidor.' "
                "WHERE status IN ('PENDING','RUNNING','STOPPING')",
                (now_iso(),),
            )

    def has_active_run(self) -> bool:
        with self.connect() as con:
            count = con.execute(
                "SELECT COUNT(*) FROM runs WHERE status IN ('PENDING','RUNNING','STOPPING')"
            ).fetchone()[0]
        return bool(count)

    def add_run_error(self, run_id: int, month: Optional[int], source_url: str, message: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO run_errors(run_id, month, source_url, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (int(run_id), month, str(source_url or "")[:1500], str(message)[:4000], now_iso()),
            )

    def list_run_errors(self, run_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT month, source_url, message, created_at FROM run_errors WHERE run_id=? ORDER BY id DESC LIMIT ?",
                (int(run_id), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Caché PDF
    # ------------------------------------------------------------------
    def get_pdf_cache(self, url: str) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM pdf_cache WHERE url=?", (url,)).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["resolutions"] = json.loads(data.pop("resolutions_json", "[]"))
        except Exception:
            return None
        return data

    def save_pdf_cache(
        self,
        pdf: dict[str, Any],
        pdf_hash: str,
        resolutions: list[dict[str, Any]],
        warning: str = "",
        parser_version: int = 1,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO pdf_cache(url, year, month, filename, publication_date, pdf_hash,
                                      parser_version, resolutions_json, warning, last_checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    year=excluded.year, month=excluded.month, filename=excluded.filename,
                    publication_date=excluded.publication_date, pdf_hash=excluded.pdf_hash,
                    parser_version=excluded.parser_version,
                    resolutions_json=excluded.resolutions_json, warning=excluded.warning,
                    last_checked_at=excluded.last_checked_at
                """,
                (
                    pdf["url"], pdf.get("year"), pdf.get("month"), pdf.get("archivo"),
                    pdf.get("fecha"), pdf_hash, int(parser_version),
                    json.dumps(resolutions, ensure_ascii=False), warning, now_iso(),
                ),
            )

    # ------------------------------------------------------------------
    # Publicaciones y delta
    # ------------------------------------------------------------------
    def register_publication(self, run_id: int, finding: dict[str, Any], stable_key: str,
                             content_hash: str) -> dict[str, Any]:
        alerts_json = json.dumps(finding.get("alertas", []), ensure_ascii=False, sort_keys=True)
        terms_json = json.dumps(finding.get("terminos_encontrados", []), ensure_ascii=False)
        annexes_json = json.dumps(finding.get("anexos", []), ensure_ascii=False)
        current = now_iso()

        with self.connect() as con:
            previous_row = con.execute(
                "SELECT * FROM publications WHERE stable_key=?", (stable_key,)
            ).fetchone()
            previous = dict(previous_row) if previous_row else None

            if previous is None:
                cursor = con.execute(
                    """
                    INSERT INTO publications(
                        stable_key, year, publication_date, emission_date, resolution_number,
                        expediente_number, provider, issuing_body, source_pdf, source_url,
                        source_page_url, extract_text, text_full, text_resuelve,
                        annexes_json, annex_text, content_hash, detected_state, matched_alerts_json,
                        regulatory_terms_json, warning, first_seen_run, last_seen_run,
                        first_seen_at, last_seen_at, verification_count,
                        last_change_type, is_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'NUEVO', 0)
                    """,
                    (
                        stable_key, finding["year"], finding.get("fecha"),
                        finding.get("fecha_emision"), finding["numero"],
                        finding.get("expediente"), finding.get("prestadora"),
                        finding.get("organismo_emisor"), finding.get("archivo"),
                        finding.get("url"), finding.get("pagina_publicacion"),
                        finding.get("extracto"), finding.get("texto_completo"),
                        finding.get("texto_resuelve"), annexes_json,
                        finding.get("texto_anexos", ""), content_hash,
                        finding.get("estado_detectado"), alerts_json, terms_json,
                        finding.get("warning", ""), int(run_id), int(run_id), current, current,
                    ),
                )
                publication_id = int(cursor.lastrowid)
                change_type = "NUEVO"
                previous_hash = None
                previous_state = None
            else:
                publication_id = int(previous["id"])
                changed = (
                    previous.get("content_hash") != content_hash
                    or previous.get("detected_state") != finding.get("estado_detectado")
                )
                change_type = "MODIFICADO" if changed else "SIN CAMBIOS"
                previous_hash = previous.get("content_hash")
                previous_state = previous.get("detected_state")
                con.execute(
                    """
                    UPDATE publications SET
                        publication_date=?, emission_date=?, resolution_number=?, expediente_number=?,
                        provider=?, issuing_body=?, source_pdf=?, source_url=?, source_page_url=?,
                        extract_text=?, text_full=?, text_resuelve=?, content_hash=?, detected_state=?,
                        matched_alerts_json=?, regulatory_terms_json=?, warning=?, last_seen_run=?,
                        last_seen_at=?, verification_count=verification_count+1,
                        last_change_type=?, is_modified=?
                    WHERE id=?
                    """,
                    (
                        finding.get("fecha"), finding.get("fecha_emision"), finding["numero"],
                        finding.get("expediente"), finding.get("prestadora"),
                        finding.get("organismo_emisor"), finding.get("archivo"), finding.get("url"),
                        finding.get("pagina_publicacion"), finding.get("extracto"),
                        finding.get("texto_completo"), finding.get("texto_resuelve"), content_hash,
                        finding.get("estado_detectado"), alerts_json, terms_json,
                        finding.get("warning", ""), int(run_id), current, change_type,
                        int(changed), publication_id,
                    ),
                )

            if change_type in {"NUEVO", "MODIFICADO"}:
                snapshot = {
                    "stable_key": stable_key,
                    "numero": finding.get("numero"),
                    "organismo_emisor": finding.get("organismo_emisor"),
                    "prestadora": finding.get("prestadora"),
                    "fecha": finding.get("fecha"),
                    "archivo": finding.get("archivo"),
                    "url": finding.get("url"),
                    "alertas": finding.get("alertas", []),
                    "estado_detectado": finding.get("estado_detectado"),
                }
                con.execute(
                    """
                    INSERT INTO changes(publication_id, run_id, change_type, previous_hash,
                                        new_hash, previous_state, new_state, detected_at, snapshot_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        publication_id, int(run_id), change_type, previous_hash, content_hash,
                        previous_state, finding.get("estado_detectado"), current,
                        json.dumps(snapshot, ensure_ascii=False),
                    ),
                )

        result = dict(finding)
        result.update(
            publication_id=publication_id,
            stable_key=stable_key,
            content_hash=content_hash,
            novedad=change_type,
        )
        return result

    def save_run_result(self, run_id: int, finding: dict[str, Any], visible: bool) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO run_results(run_id, publication_id, change_type, visible, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, publication_id) DO UPDATE SET
                    change_type=excluded.change_type,
                    visible=excluded.visible,
                    result_json=excluded.result_json,
                    created_at=excluded.created_at
                """,
                (
                    int(run_id), int(finding["publication_id"]), finding.get("novedad", ""),
                    int(bool(visible)), json.dumps(finding, ensure_ascii=False), now_iso(),
                ),
            )

    def list_run_results(self, run_id: int, visible_only: bool = True, compact: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT result_json FROM run_results WHERE run_id=?"
        params: list[Any] = [int(run_id)]
        if visible_only:
            sql += " AND visible=1"
        sql += " ORDER BY id"
        with self.connect() as con:
            rows = con.execute(sql, params).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            try:
                item = json.loads(row["result_json"])
                if compact:
                    item.pop("texto_completo", None)
                    item.pop("texto_resuelve", None)
                    item.pop("alertas_detalle", None)
                output.append(item)
            except Exception:
                continue
        return output

    def get_publication(self, publication_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM publications WHERE id=?", (int(publication_id),)).fetchone()
            changes = con.execute(
                "SELECT change_type, previous_hash, new_hash, previous_state, new_state, detected_at "
                "FROM changes WHERE publication_id=? ORDER BY id DESC",
                (int(publication_id),),
            ).fetchall()
        if not row:
            return None
        data = self._publication_row(row, include_text=True)
        data["changes"] = [dict(item) for item in changes]
        return data

    def update_complete_extraction(
        self, publication_id: int, extracted: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        annexes = list(extracted.get("anexos") or [])
        annex_text = "\n\n".join(
            str(item.get("texto") or "").strip() for item in annexes if item.get("texto")
        )
        current = now_iso()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE publications SET
                    resolution_number=COALESCE(NULLIF(?, ''), resolution_number),
                    expediente_number=?, emission_date=?, issuing_body=?,
                    source_page_url=COALESCE(NULLIF(?, ''), source_page_url),
                    extract_text=COALESCE(NULLIF(?, ''), extract_text),
                    text_full=COALESCE(NULLIF(?, ''), text_full),
                    text_resuelve=COALESCE(NULLIF(?, ''), text_resuelve),
                    annexes_json=?, annex_text=?, complete_extracted_at=?,
                    warning=CASE WHEN ?<>'' THEN ? ELSE warning END
                WHERE id=?
                """,
                (
                    extracted.get("numero_resolucion", ""),
                    extracted.get("numero_expediente", ""),
                    extracted.get("fecha_emision", ""),
                    extracted.get("organismo_emisor", ""),
                    extracted.get("pagina_publicacion", ""),
                    extracted.get("vista_previa", ""),
                    extracted.get("resolucion_completa", ""),
                    extracted.get("texto_resuelve", ""),
                    json.dumps(annexes, ensure_ascii=False),
                    annex_text,
                    current,
                    extracted.get("advertencia", ""),
                    extracted.get("advertencia", ""),
                    int(publication_id),
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_publication(publication_id)

    @staticmethod
    def _publication_row(row: sqlite3.Row, include_text: bool = False) -> dict[str, Any]:
        data = dict(row)
        for source, target in (
            ("matched_alerts_json", "matched_alerts"),
            ("regulatory_terms_json", "regulatory_terms"),
            ("annexes_json", "annexes"),
        ):
            try:
                data[target] = json.loads(data.pop(source, "[]"))
            except Exception:
                data[target] = []
        data["is_modified"] = bool(data.get("is_modified"))
        if not include_text:
            data.pop("text_full", None)
            data.pop("text_resuelve", None)
        return data

    def history(self, *, anio: Optional[int] = None, organismo: str = "", prestadora: str = "", estado: str = "",
                alerta: str = "", texto: str = "", solo_novedades: bool = False,
                page: int = 1, page_size: int = 25) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if anio:
            clauses.append("year=?")
            params.append(int(anio))
        if organismo:
            code = re.sub(r"[^A-Z0-9]+", "", organismo.upper())
            if code not in {"ERSEP", "APRHI"}:
                raise ValueError("Organismo inválido. Use ERSEP o APRHI.")
            clauses.append("UPPER(issuing_body) LIKE ?")
            params.append(f"%{code}%")
        if prestadora:
            clauses.append("provider LIKE ?")
            params.append(f"%{prestadora.strip()}%")
        if estado:
            clauses.append("detected_state=?")
            params.append(estado.strip())
        if alerta:
            clauses.append("matched_alerts_json LIKE ?")
            params.append(f"%{alerta.strip()}%")
        if texto:
            clauses.append(
                "(resolution_number LIKE ? OR expediente_number LIKE ? OR provider LIKE ? "
                "OR issuing_body LIKE ? OR text_full LIKE ? OR text_resuelve LIKE ?)"
            )
            term = f"%{texto.strip()}%"
            params.extend([term, term, term, term, term, term])
        if solo_novedades:
            clauses.append("last_change_type IN ('NUEVO','MODIFICADO')")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        offset = (int(page) - 1) * int(page_size)
        with self.connect() as con:
            total = int(con.execute(f"SELECT COUNT(*) FROM publications{where}", params).fetchone()[0])
            rows = con.execute(
                "SELECT * FROM publications" + where +
                " ORDER BY year DESC, publication_date DESC, id DESC LIMIT ? OFFSET ?",
                [*params, int(page_size), offset],
            ).fetchall()
        return {
            "items": [self._publication_row(row) for row in rows],
            "total": total,
            "page": int(page),
            "page_size": int(page_size),
            "pages": max(1, (total + int(page_size) - 1) // int(page_size)),
        }

    def history_all(self, **filters) -> list[dict[str, Any]]:
        filters = dict(filters)
        filters["page"] = 1
        filters["page_size"] = 200
        first = self.history(**filters)
        items = list(first["items"])
        for page in range(2, int(first["pages"]) + 1):
            filters["page"] = page
            items.extend(self.history(**filters)["items"])
        return items

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        with self.connect() as con:
            return {
                "alertas": int(con.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]),
                "alertas_activas": int(con.execute("SELECT COUNT(*) FROM alerts WHERE active=1").fetchone()[0]),
                "publicaciones": int(con.execute("SELECT COUNT(*) FROM publications").fetchone()[0]),
                "ejecuciones": int(con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]),
            }

    def distinct_filters(self) -> dict[str, list[Any]]:
        with self.connect() as con:
            years = [row[0] for row in con.execute("SELECT DISTINCT year FROM publications ORDER BY year DESC")]
            states = [row[0] for row in con.execute(
                "SELECT DISTINCT detected_state FROM publications WHERE detected_state<>'' ORDER BY detected_state"
            )]
            providers = [row[0] for row in con.execute(
                "SELECT DISTINCT provider FROM publications WHERE provider<>'' ORDER BY provider COLLATE NOCASE LIMIT 500"
            )]
            issuers = [row[0] for row in con.execute(
                "SELECT DISTINCT issuing_body FROM publications WHERE issuing_body<>'' ORDER BY issuing_body COLLATE NOCASE"
            )]
        return {"years": years, "states": states, "providers": providers, "issuers": issuers}
