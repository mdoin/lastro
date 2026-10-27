import re
import sqlite3
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"

SCHEMA = (BACKEND / "app" / "schema.sql").read_text(encoding="utf-8")
NOW = "2026-10-26T10:00:00-03:00"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO users VALUES ('u1', ?, '{}')", (NOW,))
    conn.execute("INSERT INTO accounts VALUES ('a1', 'u1', 'Banco X (fictício)', 'conta', 'BRL')")
    yield conn
    conn.close()


def test_no_float_columns():
    code = re.sub(r"--[^\n]*", "", SCHEMA)
    assert not re.search(r"\b(REAL|FLOAT|DOUBLE|NUMERIC)\b", code, re.IGNORECASE)


def test_repeated_import_does_not_duplicate(db):
    row = ("t1", "a1", None, "aplicacao", "2026-10-01", None, "150.00", "0", "0", "BRL", "hash-abc", "pendente", None, NOW)
    sql = "INSERT OR IGNORE INTO transactions VALUES (" + ",".join("?" * 14) + ")"
    db.execute(sql, row)
    db.execute(sql, ("t2",) + row[1:])  # mesmo import_hash, novo id
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_decision_log_is_append_only(db):
    db.execute("INSERT INTO decision_log (id, date, question, alternatives, user_choice) VALUES ('d1', ?, 'q', '[]', 'reserva')", (NOW,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE decision_log SET user_choice = 'outra' WHERE id = 'd1'")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM decision_log WHERE id = 'd1'")


def test_reconciled_transaction_cannot_be_deleted(db):
    db.execute("INSERT INTO transactions (id, account_id, type, date, gross_amount, import_hash, reconciliation_status, created_at) "
               "VALUES ('t1', 'a1', 'aplicacao', '2026-10-01', '100', 'h1', 'conciliado', ?)", (NOW,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM transactions WHERE id = 't1'")


def test_simulations_are_immutable(db):
    db.execute("INSERT INTO assumptions (id, scenario, annual_return, inflation_rate, created_at) VALUES ('s1','base','0.1','0.045',?)", (NOW,))
    db.execute("INSERT INTO simulations VALUES ('sim1', 's1', '0.1.0', 'fp', '{}', ?)", (NOW,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE simulations SET results_json = '{\"acertou\": true}'")
