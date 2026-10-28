# SPDX-License-Identifier: AGPL-3.0-or-later
"""Acesso a dados do Lastro (uma pessoa, uso pessoal).

Funções puras sobre uma conexão SQLite. Valores monetários entram e saem como
strings decimais; a conversão para Decimal acontece no motor financeiro.
"""

import json
import re
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

def create_conversation(conn: sqlite3.Connection, title: str, kind: str = "chat", *, channel: str | None = None,
                        agent_id: str | None = None, user_id: str = OWNER) -> dict:
    conv_id, now = new_id(), utcnow()
    channel = channel or {"panel": "council", "routine": "routine"}.get(kind, "direct")
    if channel == "direct":
        agent_id = agent_id or "mentor"
    conn.execute("INSERT INTO conversations (id, kind, title, channel, agent_id, user_id, created_at, updated_at) "
                 "VALUES (?,?,?,?,?,?,?,?)",
                 (conv_id, kind, (title or "Nova conversa").strip()[:120], channel, agent_id, user_id, now, now))
    return get_conversation(conn, conv_id)


def get_conversation(conn: sqlite3.Connection, conv_id: str) -> dict | None:
    row = conn.execute("SELECT id, kind, title, claude_session_id, session_connection, channel, agent_id, user_id, "
                       "created_at, updated_at FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    return dict(row) if row else None


def list_conversations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, kind, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_conversation(conn: sqlite3.Connection, conv_id: str) -> bool:
    return conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,)).rowcount > 0


def set_provider_session(conn: sqlite3.Connection, conv_id: str, session_id: str, connection: str | None) -> None:
    """Sessão nativa do provedor (cache descartável); o histórico de verdade são as mensagens desta conversa."""
    conn.execute("UPDATE conversations SET claude_session_id = ?, session_connection = ? WHERE id = ?",
                 (session_id, connection, conv_id))


# ---------- provedor de IA por agente e configurações da instalação ----------

def agent_models(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute("SELECT agent_id, connection_id, model, updated_at FROM agent_models").fetchall()
    return {r["agent_id"]: {"connection": r["connection_id"], "model": r["model"], "updated_at": r["updated_at"]}
            for r in rows}


def set_agent_model(conn: sqlite3.Connection, agent_id: str, connection_id: str | None, model: str = "") -> None:
    if not connection_id:
        conn.execute("DELETE FROM agent_models WHERE agent_id = ?", (agent_id,))
        return
    conn.execute("INSERT INTO agent_models (agent_id, connection_id, model, updated_at) VALUES (?,?,?,?) "
                 "ON CONFLICT(agent_id) DO UPDATE SET connection_id = excluded.connection_id, model = excluded.model, "
                 "updated_at = excluded.updated_at", (agent_id, connection_id, model or "", utcnow()))


def ai_route(conn: sqlite3.Connection, agent_id: str) -> dict:
    """Campos `connection`/`model` para a requisição ao worker. Vazio = conexão padrão da instalação."""
    row = conn.execute("SELECT connection_id, model FROM agent_models WHERE agent_id = ?", (agent_id,)).fetchone()
    if not row:
        return {}
    return {"connection": row["connection_id"], **({"model": row["model"]} if row["model"] else {})}


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
                 "value = excluded.value, updated_at = excluded.updated_at", (key, value, utcnow()))


MESSAGE_COLUMNS = ("id, role, content, status, tools_json, audit_json, created_at, agent_id, run_id, step_key, client_id, "
                   "reply_to_id, mentions_json, sources_json, kind, meta_json")


def add_message(conn: sqlite3.Connection, conv_id: str, role: str, content: str,
                status: str = "ok", tools: list | None = None, audit: dict | None = None, *,
                agent_id: str | None = None, run_id: str | None = None, step_key: str | None = None,
                client_id: str | None = None, reply_to_id: str | None = None, mentions: list | None = None,
                sources: list | None = None, kind: str = "message", meta: dict | None = None) -> dict:
    """Grava uma mensagem. Com (run_id, step_key) ou client_id repetidos, devolve a já existente (idempotente)."""
    if role == "assistant" and agent_id is None:
        agent_id = "mentor"
    msg_id, now = new_id(), utcnow()
    cur = conn.execute(
        "INSERT OR IGNORE INTO messages (id, conversation_id, role, content, status, tools_json, audit_json, created_at, "
        "agent_id, run_id, step_key, client_id, reply_to_id, mentions_json, sources_json, kind, meta_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (msg_id, conv_id, role, content, status, json.dumps(tools or [], ensure_ascii=False),
         json.dumps(audit, ensure_ascii=False) if audit else None, now, agent_id, run_id, step_key, client_id,
         reply_to_id, json.dumps(mentions or []), json.dumps(sources or [], ensure_ascii=False), kind,
         json.dumps(meta, ensure_ascii=False) if meta else None))
    if cur.rowcount == 0:
        where, args = (("run_id = ? AND step_key = ?", (run_id, step_key)) if run_id
                       else ("conversation_id = ? AND client_id = ?", (conv_id, client_id)))
        row = conn.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE {where}", args).fetchone()
        return {**_message_row(row), "duplicate": True}
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
    return get_message(conn, msg_id)


def _message_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "role": r["role"], "content": r["content"], "status": r["status"],
            "tools": json.loads(r["tools_json"]), "audit": json.loads(r["audit_json"]) if r["audit_json"] else None,
            "created_at": r["created_at"], "agent_id": r["agent_id"], "run_id": r["run_id"], "step_key": r["step_key"],
            "client_id": r["client_id"], "reply_to_id": r["reply_to_id"], "mentions": json.loads(r["mentions_json"]),
            "sources": json.loads(r["sources_json"]), "kind": r["kind"],
            "meta": json.loads(r["meta_json"]) if r["meta_json"] else {}}


def get_message(conn: sqlite3.Connection, msg_id: str) -> dict | None:
    row = conn.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE id = ?", (msg_id,)).fetchone()
    return _message_row(row) if row else None


def list_messages(conn: sqlite3.Connection, conv_id: str) -> list[dict]:
    rows = conn.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid",
                        (conv_id,)).fetchall()
    return [_message_row(r) for r in rows]


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
    facts = [dict(r) for r in conn.execute("SELECT * FROM financial_facts ORDER BY created_at")]
    notes = [dict(r) for r in conn.execute("SELECT * FROM agent_notes ORDER BY created_at")]
    diary_drafts = [dict(r) for r in conn.execute("SELECT * FROM decision_drafts ORDER BY created_at")]
    diary_entries = [dict(r) for r in conn.execute("SELECT * FROM diary_entries ORDER BY user_id, seq")]
    return {"exported_at": utcnow(), "snapshots": snapshots, "financial_facts": facts, "agent_notes": notes, "assumptions": get_assumptions(conn),
            "goals": list_goals(conn), "decisions": list_decisions(conn), "diary_drafts": diary_drafts,
            "diary_entries": diary_entries, "conversations": conversations,
            "routines": routines, "routine_runs": runs}


# ---------- equipe: conversas e participantes ----------

def list_user_conversations(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT c.id, c.kind, c.channel, c.agent_id, c.title, c.created_at, c.updated_at, m.content AS last_message, "
        "m.agent_id AS last_agent_id FROM conversations c LEFT JOIN messages m ON m.rowid = ("
        "SELECT rowid FROM messages WHERE conversation_id = c.id ORDER BY created_at DESC, rowid DESC LIMIT 1) "
        "WHERE c.user_id = ? ORDER BY c.updated_at DESC", (user_id,)).fetchall()
    out = []
    for r in rows:
        conv = dict(r)
        conv["participants"] = participants(conn, conv["id"])
        conv["last_message"] = (conv["last_message"] or "")[:140]
        out.append(conv)
    return out


def user_conversation(conn: sqlite3.Connection, conv_id: str, user_id: str) -> dict | None:
    """A conversa só existe para o dono dela: a de outra pessoa responde igual a uma inexistente."""
    conv = get_conversation(conn, conv_id)
    if not conv or conv["user_id"] != user_id:
        return None
    return {**conv, "participants": participants(conn, conv_id)}


def participants(conn: sqlite3.Connection, conv_id: str) -> list[str]:
    conv = conn.execute("SELECT channel, agent_id FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    if conv and conv["channel"] == "direct":
        return [conv["agent_id"] or "mentor"]
    return [r[0] for r in conn.execute("SELECT agent_id FROM conversation_participants WHERE conversation_id = ? "
                                       "ORDER BY added_at, rowid", (conv_id,))]


def add_participant(conn: sqlite3.Connection, conv_id: str, agent_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO conversation_participants (conversation_id, agent_id, added_at) VALUES (?,?,?)",
                 (conv_id, agent_id, utcnow()))


def remove_participant(conn: sqlite3.Connection, conv_id: str, agent_id: str) -> bool:
    return conn.execute("DELETE FROM conversation_participants WHERE conversation_id = ? AND agent_id = ?",
                        (conv_id, agent_id)).rowcount > 0


def rename_conversation(conn: sqlite3.Connection, conv_id: str, title: str) -> None:
    conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title.strip()[:120], utcnow(), conv_id))


# ---------- equipe: execuções e passos ----------

def create_run(conn: sqlite3.Connection, conv: dict, message_id: str, kind: str, route: dict) -> dict:
    """Uma execução por mensagem e tipo (UNIQUE): reenviar a mesma mensagem não enfileira de novo."""
    conn.execute("INSERT OR IGNORE INTO runs (id, conversation_id, user_id, message_id, kind, status, route_json, created_at) "
                 "VALUES (?,?,?,?,?,'queued',?,?)",
                 (new_id(), conv["id"], conv["user_id"], message_id, kind, json.dumps(route, ensure_ascii=False), utcnow()))
    row = conn.execute("SELECT id FROM runs WHERE message_id = ? AND kind = ?", (message_id, kind)).fetchone()
    return get_run(conn, row["id"])


def _run_row(r: sqlite3.Row) -> dict:
    data = {k: r[k] for k in r.keys() if k != "route_json"}
    return {**data, "route": json.loads(r["route_json"]), "cancel_requested": bool(r["cancel_requested"]),
            "close_requested": bool(r["close_requested"]) if "close_requested" in r.keys() else False}


def get_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _run_row(row) if row else None


def set_run(conn: sqlite3.Connection, run_id: str, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)  # chaves vêm só do código, nunca da requisição
    conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))


def list_runs(conn: sqlite3.Connection, conv_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute("SELECT * FROM runs WHERE conversation_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                        (conv_id, limit)).fetchall()
    return [{**_run_row(r), "steps": list_steps(conn, r["id"])} for r in rows]


def queued_runs(conn: sqlite3.Connection) -> list[dict]:
    return [_run_row(r) for r in conn.execute("SELECT * FROM runs WHERE status = 'queued' ORDER BY created_at, rowid")]


def recover_runs(conn: sqlite3.Connection) -> int:
    """Depois de um reinício, o que estava rodando volta para a fila; passos concluídos são reaproveitados."""
    conn.execute("UPDATE run_steps SET status = 'failed', error = 'interrompido por reinício', finished_at = ? "
                 "WHERE status = 'running'", (utcnow(),))
    return conn.execute("UPDATE runs SET status = 'queued' WHERE status = 'running'").rowcount


def _step_row(r: sqlite3.Row) -> dict:
    return {**{k: r[k] for k in r.keys() if k != "tools_json"}, "tools": json.loads(r["tools_json"])}


def get_step(conn: sqlite3.Connection, run_id: str, step_key: str) -> dict | None:
    row = conn.execute("SELECT * FROM run_steps WHERE run_id = ? AND step_key = ?", (run_id, step_key)).fetchone()
    return _step_row(row) if row else None


def list_steps(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    return [_step_row(r) for r in conn.execute("SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at, rowid",
                                               (run_id,))]


def start_step(conn: sqlite3.Connection, run_id: str, step_key: str, *, agent_id: str, kind: str, task: str,
               parent_key: str | None = None, depth: int = 0) -> None:
    conn.execute("INSERT INTO run_steps (run_id, step_key, agent_id, kind, parent_key, depth, status, task, attempts, "
                 "started_at) VALUES (?,?,?,?,?,?,'running',?,1,?) "
                 "ON CONFLICT(run_id, step_key) DO UPDATE SET status = 'running', attempts = attempts + 1, error = NULL, "
                 "finished_at = NULL",
                 (run_id, step_key, agent_id, kind, parent_key, depth, task[:20000], utcnow()))


def finish_step(conn: sqlite3.Connection, run_id: str, step_key: str, status: str, *, output: str = "",
                tools: list | None = None, error: str | None = None) -> None:
    conn.execute("UPDATE run_steps SET status = ?, output = ?, tools_json = ?, error = ?, finished_at = ? "
                 "WHERE run_id = ? AND step_key = ?",
                 (status, output, json.dumps(tools or [], ensure_ascii=False), error, utcnow(), run_id, step_key))


def reject_step(conn: sqlite3.Connection, run_id: str, step_key: str, *, agent_id: str, parent_key: str, depth: int,
                task: str, reason: str) -> None:
    now = utcnow()
    conn.execute("INSERT OR IGNORE INTO run_steps (run_id, step_key, agent_id, kind, parent_key, depth, status, task, "
                 "error, started_at, finished_at) VALUES (?,?,?,'delegate',?,?,'rejected',?,?,?,?)",
                 (run_id, step_key, agent_id, parent_key, depth, task[:2000], reason, now, now))


# ---------- equipe: memória financeira (fatos com fonte, data e histórico) ----------

FACT_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def list_facts(conn: sqlite3.Connection, user_id: str, status: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM financial_facts WHERE user_id = ?", [user_id]
    if status:
        sql, args = sql + " AND status = ?", [*args, status]
    return [dict(r) for r in conn.execute(sql + " ORDER BY key, created_at DESC", args)]


def add_fact(conn: sqlite3.Connection, user_id: str, key: str, value: str, *, source: str, status: str,
             as_of: str, note: str = "", source_ref: str | None = None) -> dict:
    key = str(key).strip().lower()
    if not FACT_KEY.match(key):
        raise ValueError("key: use letras minúsculas, números e _ (ex.: horizonte_meses).")
    value = str(value).strip()[:500]
    if not value:
        raise ValueError("value: obrigatório.")
    fact_id, now = new_id(), utcnow()
    previous = None
    if status == "confirmed":
        previous = conn.execute("SELECT id FROM financial_facts WHERE user_id = ? AND key = ? AND status = 'confirmed'",
                                (user_id, key)).fetchone()
        conn.execute("UPDATE financial_facts SET status = 'superseded' WHERE user_id = ? AND key = ? AND status = 'confirmed'",
                     (user_id, key))
    conn.execute("INSERT INTO financial_facts (id, user_id, key, value, status, source, source_ref, note, as_of, "
                 "supersedes_id, created_at, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (fact_id, user_id, key, value, status, source, source_ref, str(note)[:500], as_of,
                  previous["id"] if previous else None, now, now if status == "confirmed" else None))
    return dict(conn.execute("SELECT * FROM financial_facts WHERE id = ?", (fact_id,)).fetchone())


def decide_fact(conn: sqlite3.Connection, user_id: str, fact_id: str, confirm: bool, as_of: str) -> dict | None:
    """Confirmar uma proposta cria o fato confirmado (com histórico); rejeitar só marca a proposta."""
    row = conn.execute("SELECT * FROM financial_facts WHERE id = ? AND user_id = ? AND status = 'proposed'",
                       (fact_id, user_id)).fetchone()
    if not row:
        return None
    conn.execute("UPDATE financial_facts SET status = 'rejected', decided_at = ? WHERE id = ?", (utcnow(), fact_id))
    if not confirm:
        return dict(conn.execute("SELECT * FROM financial_facts WHERE id = ?", (fact_id,)).fetchone())
    return add_fact(conn, user_id, row["key"], row["value"], source=row["source"], status="confirmed", as_of=as_of,
                    note=f"confirmado pela pessoa (proposta {fact_id[:8]})", source_ref=row["source_ref"])


# ---------- equipe: memória individual dos agentes ----------

def _own_direct(conv: dict, agent_id: str) -> bool:
    return conv["channel"] == "direct" and (conv.get("agent_id") or "mentor") == agent_id


def add_note(conn: sqlite3.Connection, user_id: str, agent_id: str, conv: dict, content: str, source_ref: str) -> None:
    scope = "private" if _own_direct(conv, agent_id) else "conversation"
    conn.execute("INSERT INTO agent_notes (id, user_id, agent_id, scope, conversation_id, content, source_ref, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?)",
                 (new_id(), user_id, agent_id, scope, conv["id"], content.strip()[:500], source_ref, utcnow()))


def notes_for(conn: sqlite3.Connection, user_id: str, agent_id: str, conv: dict, limit: int = 12) -> list[dict]:
    """Notas privadas só entram nas conversas individuais do próprio agente; as demais, só onde nasceram."""
    if _own_direct(conv, agent_id):
        where, args = "scope = 'private'", ()
    else:
        where, args = "scope = 'conversation' AND conversation_id = ?", (conv["id"],)
    rows = conn.execute(f"SELECT * FROM agent_notes WHERE user_id = ? AND agent_id = ? AND {where} "
                        "ORDER BY created_at DESC LIMIT ?", (user_id, agent_id, *args, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def list_notes(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM agent_notes WHERE user_id = ? ORDER BY created_at DESC",
                                          (user_id,))]


def delete_note(conn: sqlite3.Connection, user_id: str, note_id: str) -> bool:
    return conn.execute("DELETE FROM agent_notes WHERE id = ? AND user_id = ?", (note_id, user_id)).rowcount > 0
