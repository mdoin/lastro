# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conexões SQLite e migrações versionadas.

O web app abre o banco em leitura e escrita; a API dos agentes abre em
somente leitura (`mode=ro`), então nenhuma consulta dela consegue alterar dados.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
MIGRATIONS = (
    (1, APP_DIR / "schema.sql"),
    (2, APP_DIR / "migrations" / "002_lastro_app.sql"),
    (3, APP_DIR / "migrations" / "003_message_audit.sql"),
    (4, APP_DIR / "migrations" / "004_login_attempt_client.sql"),
    (5, APP_DIR / "migrations" / "005_team.sql"),
    (6, APP_DIR / "migrations" / "006_radar.sql"),
    (7, APP_DIR / "migrations" / "007_diario.sql"),
    (8, APP_DIR / "migrations" / "008_providers.sql"),
    (9, APP_DIR / "migrations" / "009_message_meta.sql"),
    (10, APP_DIR / "migrations" / "010_ledger.sql"),
    (11, APP_DIR / "migrations" / "011_council.sql"),
    (12, APP_DIR / "migrations" / "012_crypto.sql"),
)
LATEST_VERSION = MIGRATIONS[-1][0]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def connect(path: Path | str) -> sqlite3.Connection:
    conn = _configure(sqlite3.connect(str(path), isolation_level=None, check_same_thread=False))
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def connect_readonly(path: Path | str) -> sqlite3.Connection:
    uri = f"file:{Path(path).resolve()}?mode=ro"
    conn = _configure(sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False))
    conn.execute("PRAGMA query_only = ON")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
    if not exists:
        return 0
    return conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Aplica as migrações pendentes, cada uma numa transação. Retorna a versão final."""
    version = current_version(conn)
    for number, path in MIGRATIONS:
        if number <= version:
            continue
        script = path.read_text(encoding="utf-8")
        conn.execute("BEGIN")
        try:
            # executescript faria COMMIT implícito; executamos instrução a instrução.
            for statement in _split_statements(script):
                conn.execute(statement)
            if number > 1:
                conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (number, utcnow()))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        version = number
    return version


def _split_statements(script: str) -> list[str]:
    """Divide o SQL em instruções completas, respeitando blocos BEGIN ... END de triggers."""
    statements, buffer = [], []
    for line in script.splitlines():
        stripped = line.split("--", 1)[0].rstrip()
        if not stripped.strip():
            continue
        buffer.append(stripped)
        candidate = "\n".join(buffer)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            buffer = []
    if "".join(buffer).strip():
        raise ValueError("Migração com instrução SQL incompleta no fim do arquivo.")
    return statements
