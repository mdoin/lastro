"""Acesso a dados do Lastro (uma pessoa, uso pessoal).

Funções puras sobre uma conexão SQLite. Valores monetários entram e saem como
strings decimais; a conversão para Decimal acontece no motor financeiro.
"""

import json
import sqlite3
import uuid
from decimal import Decimal

from financial_engine.budget import Debt, FinancialSnapshot
from financial_engine.money import to_decimal

from .db import utcnow

OWNER = "owner"

DEFAULT_SCENARIOS = (
    {"name": "conservador", "annual_return": "0.08", "annual_inflation": "0.055", "annual_fee": "0.005",
     "note": "Hipótese ilustrativa, não é previsão."},
    {"name": "base", "annual_return": "0.10", "annual_inflation": "0.045", "annual_fee": "0.005",
     "note": "Hipótese ilustrativa, não é previsão."},
    {"name": "otimista", "annual_return": "0.12", "annual_inflation": "0.035", "annual_fee": "0.005",
     "note": "Hipótese ilustrativa, não é previsão."},
)
ASSUMPTIONS_NOTE = ("Premissas são hipóteses suas ou ilustrativas. Não são dados de mercado verificados "
                    "nem previsão de rentabilidade.")


def new_id() -> str:
    return str(uuid.uuid4())


def money(value, *, field: str, allow_negative: bool = False) -> str:
    try:
        number = to_decimal(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: valor inválido.") from exc
    if number < 0 and not allow_negative:
        raise ValueError(f"{field}: não pode ser negativo.")
    return str(number)


# ---------- snapshots ----------

SNAPSHOT_FIELDS = ("net_monthly_income", "essential_expenses", "variable_expenses", "liquid_reserve", "available_this_month")


def create_snapshot(conn: sqlite3.Connection, data: dict) -> dict:
    snapshot_id, now = new_id(), utcnow()
    values = {f: money(data[f], field=f) for f in SNAPSHOT_FIELDS}
    debts = []
    for i, d in enumerate(data.get("debts") or []):
        name = str(d.get("name", "")).strip()
        if not name:
            raise ValueError(f"debts[{i}]: nome obrigatório.")
        debts.append({"name": name[:120],
                      "balance": money(d["balance"], field=f"debts[{i}].balance"),
                      "monthly_rate": money(d["monthly_rate"], field=f"debts[{i}].monthly_rate"),
                      "monthly_payment": money(d["monthly_payment"], field=f"debts[{i}].monthly_payment")})
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO financial_snapshots (id, user_id, as_of, net_monthly_income, essential_expenses, "
            "variable_expenses, liquid_reserve, available_this_month, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (snapshot_id, OWNER, str(data["as_of"]), *(values[f] for f in SNAPSHOT_FIELDS), now))
        for d in debts:
            conn.execute(
                "INSERT INTO liabilities (id, user_id, name, balance, monthly_rate, monthly_payment, as_of, snapshot_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), OWNER, d["name"], d["balance"], d["monthly_rate"], d["monthly_payment"], str(data["as_of"]), snapshot_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_snapshot(conn, snapshot_id)


def _snapshot_row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    debts = conn.execute("SELECT name, balance, monthly_rate, monthly_payment FROM liabilities WHERE snapshot_id = ? "
                         "ORDER BY rowid", (row["id"],)).fetchall()
    return {"id": row["id"], "as_of": row["as_of"], **{f: row[f] for f in SNAPSHOT_FIELDS},
            "debts": [dict(d) for d in debts], "created_at": row["created_at"]}


def get_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM financial_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return _snapshot_row_to_dict(conn, row) if row else None


def latest_snapshot(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM financial_snapshots WHERE user_id = ? ORDER BY as_of DESC, created_at DESC LIMIT 1",
                       (OWNER,)).fetchone()
    return _snapshot_row_to_dict(conn, row) if row else None


def snapshot_history(conn: sqlite3.Connection) -> list[dict]:
    from financial_engine.budget import free_cash_flow

    rows = conn.execute("SELECT * FROM financial_snapshots WHERE user_id = ? ORDER BY as_of, created_at", (OWNER,)).fetchall()
    history = []
    for row in rows:
        snap = _snapshot_row_to_dict(conn, row)
        fin = to_financial(snap)
        history.append({"id": snap["id"], "as_of": snap["as_of"], "net_monthly_income": snap["net_monthly_income"],
                        "liquid_reserve": snap["liquid_reserve"],
                        "total_debt": str(sum((d.balance for d in fin.debts), Decimal(0))),
                        "free_cash_flow": str(free_cash_flow(fin))})
    return history


def to_financial(snap: dict) -> FinancialSnapshot:
    return FinancialSnapshot(
        net_monthly_income=snap["net_monthly_income"], essential_expenses=snap["essential_expenses"],
        variable_expenses=snap["variable_expenses"], liquid_reserve=snap["liquid_reserve"],
        available_this_month=snap["available_this_month"],
        debts=tuple(Debt(**d) for d in snap["debts"]), as_of=snap["as_of"])


# ---------- premissas ----------

def get_assumptions(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT scenarios_json FROM user_assumptions WHERE user_id = ?", (OWNER,)).fetchone()
    scenarios = json.loads(row["scenarios_json"]) if row else [dict(s) for s in DEFAULT_SCENARIOS]
    return {"scenarios": scenarios, "is_default": row is None, "note": ASSUMPTIONS_NOTE}


def save_assumptions(conn: sqlite3.Connection, scenarios: list[dict]) -> dict:
    if not 1 <= len(scenarios) <= 5:
        raise ValueError("Informe de 1 a 5 cenários.")
    clean, names = [], set()
    for i, s in enumerate(scenarios):
        name = str(s.get("name", "")).strip()[:40]
        if not name or name in names:
            raise ValueError(f"scenarios[{i}]: nome vazio ou repetido.")
        names.add(name)
        fee = to_decimal(money(s.get("annual_fee", "0"), field=f"scenarios[{i}].annual_fee"))
        if fee >= 1:
            raise ValueError(f"scenarios[{i}].annual_fee: precisa ser menor que 100%.")
        clean.append({"name": name,
                      "annual_return": money(s["annual_return"], field=f"scenarios[{i}].annual_return", allow_negative=True),
                      "annual_inflation": money(s["annual_inflation"], field=f"scenarios[{i}].annual_inflation", allow_negative=True),
                      "annual_fee": str(fee), "note": str(s.get("note", ""))[:200]})
    conn.execute("INSERT INTO user_assumptions (user_id, scenarios_json, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET scenarios_json = excluded.scenarios_json, updated_at = excluded.updated_at",
                 (OWNER, json.dumps(clean, ensure_ascii=False), utcnow()))
    return get_assumptions(conn)


# ---------- metas ----------

LIQUIDITY = ("diaria", "curto_prazo", "longo_prazo")


def _goal_values(data: dict) -> dict:
    name = str(data.get("name", "")).strip()[:120]
    if not name:
        raise ValueError("name: obrigatório.")
    priority = int(data.get("priority", 3))
    if not 1 <= priority <= 5:
        raise ValueError("priority: de 1 a 5.")
    liquidity = data.get("liquidity", "longo_prazo")
    if liquidity not in LIQUIDITY:
        raise ValueError(f"liquidity: use {', '.join(LIQUIDITY)}.")
    return {"name": name, "target_real_value": money(data["target_real_value"], field="target_real_value"),
            "deadline": str(data["deadline"]), "priority": priority, "liquidity": liquidity,
            "current_amount": money(data.get("current_amount", "0"), field="current_amount")}


def list_goals(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, target_real_value, base_date, deadline, priority, liquidity, current_amount "
                        "FROM goals WHERE user_id = ? ORDER BY priority, deadline", (OWNER,)).fetchall()
    return [dict(r) for r in rows]


def get_goal(conn: sqlite3.Connection, goal_id: str) -> dict | None:
    row = conn.execute("SELECT id, name, target_real_value, base_date, deadline, priority, liquidity, current_amount "
                       "FROM goals WHERE id = ? AND user_id = ?", (goal_id, OWNER)).fetchone()
    return dict(row) if row else None


def create_goal(conn: sqlite3.Connection, data: dict, today: str) -> dict:
    v, goal_id, now = _goal_values(data), new_id(), utcnow()
    conn.execute("INSERT INTO goals (id, user_id, name, target_real_value, base_date, deadline, priority, liquidity, "
                 "current_amount, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (goal_id, OWNER, v["name"], v["target_real_value"], today, v["deadline"], v["priority"],
                  v["liquidity"], v["current_amount"], now, now))
    return get_goal(conn, goal_id)


def update_goal(conn: sqlite3.Connection, goal_id: str, data: dict) -> dict | None:
    v = _goal_values(data)
    cur = conn.execute("UPDATE goals SET name=?, target_real_value=?, deadline=?, priority=?, liquidity=?, "
                       "current_amount=?, updated_at=? WHERE id=? AND user_id=?",
                       (v["name"], v["target_real_value"], v["deadline"], v["priority"], v["liquidity"],
                        v["current_amount"], utcnow(), goal_id, OWNER))
    return get_goal(conn, goal_id) if cur.rowcount else None


def delete_goal(conn: sqlite3.Connection, goal_id: str) -> bool:
    return conn.execute("DELETE FROM goals WHERE id = ? AND user_id = ?", (goal_id, OWNER)).rowcount > 0


# ---------- conversas ----------

def create_conversation(conn: sqlite3.Connection, title: str, kind: str = "chat") -> dict:
    conv_id, now = new_id(), utcnow()
    conn.execute("INSERT INTO conversations (id, kind, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                 (conv_id, kind, (title or "Nova conversa").strip()[:120], now, now))
    return get_conversation(conn, conv_id)


def get_conversation(conn: sqlite3.Connection, conv_id: str) -> dict | None:
    row = conn.execute("SELECT id, kind, title, claude_session_id, created_at, updated_at FROM conversations WHERE id = ?",
                       (conv_id,)).fetchone()
    return dict(row) if row else None


def list_conversations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, kind, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_conversation(conn: sqlite3.Connection, conv_id: str) -> bool:
    return conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,)).rowcount > 0


def set_claude_session(conn: sqlite3.Connection, conv_id: str, session_id: str) -> None:
    conn.execute("UPDATE conversations SET claude_session_id = ? WHERE id = ?", (session_id, conv_id))


def add_message(conn: sqlite3.Connection, conv_id: str, role: str, content: str,
                status: str = "ok", tools: list | None = None, audit: dict | None = None) -> dict:
    msg_id, now = new_id(), utcnow()
    conn.execute("INSERT INTO messages (id, conversation_id, role, content, status, tools_json, audit_json, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?)",
                 (msg_id, conv_id, role, content, status, json.dumps(tools or [], ensure_ascii=False),
                  json.dumps(audit, ensure_ascii=False) if audit else None, now))
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
    return {"id": msg_id, "role": role, "content": content, "status": status, "tools": tools or [],
            "audit": audit, "created_at": now}


def list_messages(conn: sqlite3.Connection, conv_id: str) -> list[dict]:
    rows = conn.execute("SELECT id, role, content, status, tools_json, audit_json, created_at FROM messages "
                        "WHERE conversation_id = ? ORDER BY created_at, rowid", (conv_id,)).fetchall()
    return [{"id": r["id"], "role": r["role"], "content": r["content"], "status": r["status"],
             "tools": json.loads(r["tools_json"]), "audit": json.loads(r["audit_json"]) if r["audit_json"] else None,
             "created_at": r["created_at"]} for r in rows]


# ---------- decisões ----------

def create_decision(conn: sqlite3.Connection, data: dict, today: str) -> dict:
    question = str(data.get("question", "")).strip()
    choice = str(data.get("user_choice", "")).strip()
    if not question or not choice:
        raise ValueError("question e user_choice são obrigatórios.")
    alternatives = [str(a)[:300] for a in (data.get("alternatives") or [])][:10]
    planned = data.get("planned_amount")
    review_of = data.get("review_of_id")
    if review_of and not conn.execute("SELECT 1 FROM decision_log WHERE id = ?", (review_of,)).fetchone():
        raise ValueError("review_of_id: decisão inexistente.")
    decision_id = new_id()
    conn.execute("INSERT INTO decision_log (id, date, question, alternatives, information, risk_accepted, user_choice, "
                 "planned_amount, confirmed, review_of_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (decision_id, str(data.get("date") or today), question[:500], json.dumps(alternatives, ensure_ascii=False),
                  str(data.get("information", ""))[:2000], str(data.get("risk_accepted", ""))[:1000], choice[:500],
                  money(planned, field="planned_amount") if planned not in (None, "") else None,
                  1 if data.get("confirmed") else 0, review_of))
    return next(d for d in list_decisions(conn) if d["id"] == decision_id)


def list_decisions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM decision_log ORDER BY date DESC, rowid DESC").fetchall()
    return [{"id": r["id"], "date": r["date"], "question": r["question"], "alternatives": json.loads(r["alternatives"]),
             "information": r["information"] or "", "risk_accepted": r["risk_accepted"] or "",
             "user_choice": r["user_choice"], "planned_amount": r["planned_amount"],
             "confirmed": bool(r["confirmed"]), "review_of_id": r["review_of_id"]} for r in rows]


# ---------- exportação ----------

def export_all(conn: sqlite3.Connection) -> dict:
    snapshots = [_snapshot_row_to_dict(conn, r) for r in
                 conn.execute("SELECT * FROM financial_snapshots ORDER BY as_of, created_at").fetchall()]
    conversations = []
    for conv in list_conversations(conn):
        conversations.append({**conv, "messages": list_messages(conn, conv["id"])})
    routines = [dict(r) for r in conn.execute("SELECT * FROM routines").fetchall()]
    runs = [dict(r) for r in conn.execute("SELECT * FROM routine_runs ORDER BY scheduled_for").fetchall()]
    return {"exported_at": utcnow(), "snapshots": snapshots, "assumptions": get_assumptions(conn),
            "goals": list_goals(conn), "decisions": list_decisions(conn), "conversations": conversations,
            "routines": routines, "routine_runs": runs}
