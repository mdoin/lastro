# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backup, restauração e atualização de versão sem perda de dados."""

import os
import sqlite3
import sys

import pytest

from app import admin, db, store

SNAP = {"as_of": "2026-10-01", "net_monthly_income": "4200.00", "essential_expenses": "2600.00",
        "variable_expenses": "700.00", "liquid_reserve": "200.00", "available_this_month": "300.00", "debts": []}


def old_database(path, version):
    """Banco numa versão antiga do esquema, com dados (simula uma instalação existente)."""
    conn = db.connect(path)
    for number, script in db.MIGRATIONS:
        if number > version:
            break
        for statement in db._split_statements(script.read_text(encoding="utf-8")):
            conn.execute(statement)
        if number > 1:
            conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (number, db.utcnow()))
    store.create_snapshot(conn, SNAP)
    conn.execute("INSERT INTO conversations (id, kind, title, claude_session_id, created_at, updated_at) "
                 "VALUES ('c1', 'chat', 'Reserva', 'sess-1', '2026-10-01', '2026-10-01')")
    conn.execute("INSERT INTO messages (id, conversation_id, role, content, status, created_at) "
                 "VALUES ('m1', 'c1', 'user', 'Quanto guardo?', 'ok', '2026-10-01')")
    return conn


def fingerprint(conn):
    return (conn.execute("SELECT net_monthly_income, liquid_reserve FROM financial_snapshots").fetchall(),
            conn.execute("SELECT id, content FROM messages").fetchall())


def test_backup_and_restore_round_trip(tmp_path):
    conn = old_database(tmp_path / "lastro.db", db.LATEST_VERSION)
    before = [tuple(r) for rows in fingerprint(conn) for r in rows]
    saved = admin.backup(conn, tmp_path / "backups" / "copia.db")
    if os.name == "posix":
        assert saved.stat().st_mode & 0o077 == 0
    conn.execute("DELETE FROM messages")                               # um acidente depois do backup
    conn.close()
    assert admin.restore(saved, tmp_path / "lastro.db") == db.LATEST_VERSION
    restored = db.connect(tmp_path / "lastro.db")
    assert [tuple(r) for rows in fingerprint(restored) for r in rows] == before


def test_restore_refuses_corrupted_or_newer_backups(tmp_path):
    target = tmp_path / "lastro.db"
    old_database(target, db.LATEST_VERSION).close()
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"isto nao e sqlite" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        admin.restore(junk, target)
    newer = tmp_path / "newer.db"
    conn = old_database(newer, db.LATEST_VERSION)
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (db.LATEST_VERSION + 1, db.utcnow()))
    conn.close()
    with pytest.raises(RuntimeError, match="mais nova"):
        admin.restore(newer, target)
    assert db.current_version(db.connect(target)) == db.LATEST_VERSION  # o banco atual ficou intacto


def test_upgrade_keeps_data_and_leaves_a_backup(tmp_path):
    from app.web import Settings, create_app

    path = tmp_path / "lastro.db"
    old = old_database(path, 7)
    before = [tuple(r) for rows in fingerprint(old) for r in rows]
    old.close()
    app = create_app(Settings(db_path=path, mentor_socket=tmp_path / "x.sock", cookie_secure=False,
                              run_scheduler=False, run_orchestrator=False))
    conn = app.state.conn
    assert db.current_version(conn) == db.LATEST_VERSION
    assert [tuple(r) for rows in fingerprint(conn) for r in rows] == before
    assert store.get_conversation(conn, "c1")["claude_session_id"] == "sess-1"
    backups = list((tmp_path / "backups").glob("pre-v*.db"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    assert db.current_version(copy) == 7                              # cópia do estado antes da migração
    # reiniciar não gera outra cópia (nada a migrar)
    create_app(Settings(db_path=path, mentor_socket=tmp_path / "x.sock", cookie_secure=False,
                        run_scheduler=False, run_orchestrator=False))
    assert len(list((tmp_path / "backups").glob("pre-v*.db"))) == 1


def test_clean_install_needs_no_backup(tmp_path):
    conn = db.connect(tmp_path / "novo.db")
    assert admin.pre_migration_backup(conn, tmp_path / "novo.db") is None


def test_admin_cli_backup_and_restore(tmp_path, capsys):
    path = tmp_path / "lastro.db"
    old_database(path, db.LATEST_VERSION).close()
    assert admin.main(["backup", str(tmp_path / "b.db"), "--db", str(path)]) == 0
    assert admin.main(["restore", str(tmp_path / "b.db"), "--db", str(path)]) == 0
    assert admin.main(["restore", str(tmp_path / "nao-existe.db"), "--db", str(path)]) == 1
    assert admin.main(["backup", "--db", str(path)]) == 2
    out = capsys.readouterr().out
    assert "Backup gravado" in out and "restaurado" in out
