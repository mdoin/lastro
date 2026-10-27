# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diário de Oportunidades: registro imutável, linha do tempo, decisões da pessoa e vínculos com conversas.

Os registros (`radar_snapshots`) são append-only no banco (triggers) e encadeados por SHA-256: cada um inclui o
hash do anterior, então qualquer alteração por fora do Lastro quebra a cadeia e aparece na verificação.
O registro da análise só é aceito antes de existir qualquer resultado posterior: depois disso, só correção
versionada, com motivo, mantendo o original.
"""

import hashlib
import json
import sqlite3
import uuid

STATES = ("detectada", "em_analise", "avaliada", "alerta_emitido", "em_acompanhamento", "encerrada", "invalidada",
          "inconclusiva")
TRANSITIONS = {
    "detectada": {"em_analise", "avaliada"},
    "em_analise": {"avaliada"},
    "avaliada": {"alerta_emitido", "em_acompanhamento"},
    "alerta_emitido": {"em_acompanhamento"},
    "em_acompanhamento": {"encerrada", "invalidada", "inconclusiva"},
    "encerrada": set(), "invalidada": set(), "inconclusiva": set(),
}
DECISIONS = ("analisei", "ignorei", "decidi_investir", "decidi_nao_investir", "acompanhar", "outra")


def canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev: str | None, body: str) -> str:
    return hashlib.sha256(((prev or "") + "\n" + body).encode("utf-8")).hexdigest()


def event(conn: sqlite3.Connection, opportunity_id: str, kind: str, now: str, **detail) -> None:
    conn.execute("INSERT INTO radar_events (id, opportunity_id, at, kind, detail_json) VALUES (?,?,?,?,?)",
                 (str(uuid.uuid4()), opportunity_id, now, kind, canonical(detail)))


def create(conn, *, user_id: str, signal_id: str, rule_id: str, category: str, series_id: str | None,
           asset_label: str, classification: int, score: str | None, now: str) -> dict:
    opp_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO radar_opportunities (id, user_id, signal_id, rule_id, category, series_id, asset_label, "
        "classification, score, state, created_at, state_changed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (opp_id, user_id, signal_id, rule_id, category, series_id, asset_label, classification, score, "detectada",
         now, now))
    event(conn, opp_id, "detectada", now, classificacao=classification)
    return get(conn, opp_id)


def get(conn, opp_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM radar_opportunities WHERE id = ?", (opp_id,)).fetchone()
    return dict(row) if row else None


def set_state(conn, opp_id: str, state: str, now: str, **detail) -> None:
    current = get(conn, opp_id)
    if state not in TRANSITIONS[current["state"]]:
        raise ValueError(f"transição inválida: {current['state']} → {state}")
    conn.execute("UPDATE radar_opportunities SET state = ?, state_changed_at = ? WHERE id = ?", (state, now, opp_id))
    event(conn, opp_id, state, now, **detail)


def add_snapshot(conn, opp_id: str, kind: str, payload: dict, now: str, *, reason: str = "") -> dict:
    last = conn.execute("SELECT seq, sha256 FROM radar_snapshots WHERE opportunity_id = ? ORDER BY seq DESC LIMIT 1",
                        (opp_id,)).fetchone()
    if kind == "deteccao" and last is not None:
        raise ValueError("o registro de detecção já existe")
    if kind != "deteccao" and last is None:
        raise ValueError("falta o registro de detecção")
    if kind == "analise":
        if conn.execute("SELECT 1 FROM radar_snapshots WHERE opportunity_id = ? AND kind = 'analise'", (opp_id,)).fetchone():
            raise ValueError("a análise original já foi registrada: use uma correção")
        if conn.execute("SELECT 1 FROM radar_outcomes WHERE opportunity_id = ? AND status != 'pendente'",
                        (opp_id,)).fetchone():
            raise ValueError("já há resultados posteriores: a análise original não pode mais ser registrada")
    if kind == "correcao" and not reason.strip():
        raise ValueError("correção exige motivo")
    body = canonical(payload)
    prev = last["sha256"] if last else None
    snap = {"id": str(uuid.uuid4()), "opportunity_id": opp_id, "seq": (last["seq"] + 1) if last else 1, "kind": kind,
            "payload_json": body, "sha256": _hash(prev, body), "prev_sha256": prev, "reason": reason[:500],
            "created_at": now}
    conn.execute("INSERT INTO radar_snapshots (id, opportunity_id, seq, kind, payload_json, sha256, prev_sha256, reason, "
                 "created_at) VALUES (:id,:opportunity_id,:seq,:kind,:payload_json,:sha256,:prev_sha256,:reason,"
                 ":created_at)", snap)
    event(conn, opp_id, f"registro_{kind}", now, seq=snap["seq"], sha256=snap["sha256"])
    return snap


def snapshots(conn, opp_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM radar_snapshots WHERE opportunity_id = ? ORDER BY seq", (opp_id,)).fetchall()
    return [{**{k: r[k] for k in r.keys() if k != "payload_json"}, "payload": json.loads(r["payload_json"])} for r in rows]


def original(conn, opp_id: str, kind: str = "deteccao") -> dict | None:
    row = conn.execute("SELECT payload_json FROM radar_snapshots WHERE opportunity_id = ? AND kind = ? ORDER BY seq "
                       "LIMIT 1", (opp_id, kind)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def verify_chain(conn, opp_id: str) -> dict:
    prev, problems = None, []
    rows = conn.execute("SELECT seq, payload_json, sha256, prev_sha256 FROM radar_snapshots WHERE opportunity_id = ? "
                        "ORDER BY seq", (opp_id,)).fetchall()
    for r in rows:
        if r["prev_sha256"] != prev or _hash(prev, r["payload_json"]) != r["sha256"]:
            problems.append(r["seq"])
        prev = r["sha256"]
    return {"ok": not problems, "registros": len(rows), "falhas": problems}


def timeline(conn, opp_id: str) -> list[dict]:
    rows = conn.execute("SELECT at, kind, detail_json FROM radar_events WHERE opportunity_id = ? ORDER BY at, rowid",
                        (opp_id,)).fetchall()
    return [{"at": r["at"], "kind": r["kind"], "detail": json.loads(r["detail_json"])} for r in rows]


def add_decision(conn, user_id: str, opp_id: str, decision: str, note: str, now: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError("decisão desconhecida")
    rec = {"id": str(uuid.uuid4()), "user_id": user_id, "opportunity_id": opp_id, "decision": decision,
           "note": note[:1000], "created_at": now}
    conn.execute("INSERT INTO radar_decisions (id, user_id, opportunity_id, decision, note, created_at) VALUES "
                 "(:id,:user_id,:opportunity_id,:decision,:note,:created_at)", rec)
    event(conn, opp_id, "decisao_da_pessoa", now, decisao=decision)
    return rec


def add_operation(conn, user_id: str, opp_id: str, data: dict, now: str) -> dict:
    """Operação real que a pessoa diz ter feito por conta própria: fica separada do desempenho hipotético."""
    from financial_engine.money import to_decimal

    if data.get("direction") not in ("entrada", "saida"):
        raise ValueError("direction: entrada ou saida")
    amount = to_decimal(str(data.get("amount")))
    if amount <= 0:
        raise ValueError("amount: precisa ser positivo")
    price = str(to_decimal(str(data["unit_price"]))) if data.get("unit_price") not in (None, "") else None
    rec = {"id": str(uuid.uuid4()), "user_id": user_id, "opportunity_id": opp_id,
           "operation_date": str(data["operation_date"]), "direction": data["direction"], "amount": str(amount),
           "unit_price": price, "note": str(data.get("note", ""))[:500], "created_at": now}
    conn.execute("INSERT INTO radar_user_operations (id, user_id, opportunity_id, operation_date, direction, amount, "
                 "unit_price, note, created_at) VALUES (:id,:user_id,:opportunity_id,:operation_date,:direction,"
                 ":amount,:unit_price,:note,:created_at)", rec)
    event(conn, opp_id, "operacao_informada", now)
    return rec


def link(conn, opp_id: str, conversation_id: str, purpose: str, now: str) -> None:
    conn.execute("INSERT OR IGNORE INTO radar_links (opportunity_id, conversation_id, purpose, created_at) VALUES "
                 "(?,?,?,?)", (opp_id, conversation_id, purpose, now))
    event(conn, opp_id, f"conversa_{purpose}", now, conversation_id=conversation_id)


def links(conn, opp_id: str) -> list[dict]:
    rows = conn.execute("SELECT l.conversation_id, l.purpose, l.created_at, c.title FROM radar_links l JOIN conversations c "
                        "ON c.id = l.conversation_id WHERE l.opportunity_id = ? ORDER BY l.created_at", (opp_id,))
    return [dict(r) for r in rows]


def opportunity_for_conversation(conn, conversation_id: str) -> str | None:
    row = conn.execute("SELECT opportunity_id FROM radar_links WHERE conversation_id = ?", (conversation_id,)).fetchone()
    return row["opportunity_id"] if row else None


def list_for(conn, user_id: str, *, category: str | None = None, state: str | None = None, rule_id: str | None = None,
             series: str | None = None, since: str | None = None, until: str | None = None,
             min_class: int | None = None, verdict: str | None = None, agent: str | None = None,
             limit: int = 200) -> list[dict]:
    sql = ("SELECT o.*, a.id AS alert_id, a.status AS alert_status, a.feedback AS alert_feedback, "
           "s.condition_text, s.reference_date FROM radar_opportunities o JOIN radar_signals s ON s.id = o.signal_id "
           "LEFT JOIN radar_alerts a ON a.opportunity_id = o.id WHERE o.user_id = ?")
    args: list = [user_id]
    for clause, value in (("o.category = ?", category), ("o.state = ?", state), ("o.rule_id = ?", rule_id),
                          ("o.created_at >= ?", since), ("o.created_at <= ?", until),
                          ("o.classification >= ?", min_class)):
        if value not in (None, ""):
            sql, args = f"{sql} AND {clause}", [*args, value]
    if series:
        sql, args = sql + " AND (o.series_id LIKE ? OR o.asset_label LIKE ?)", [*args, f"%{series}%", f"%{series}%"]
    if verdict:
        sql, args = sql + " AND EXISTS (SELECT 1 FROM radar_outcomes r WHERE r.opportunity_id = o.id AND r.verdict = ?)", \
            [*args, verdict]
    if agent:
        sql, args = (sql + " AND EXISTS (SELECT 1 FROM radar_snapshots x WHERE x.opportunity_id = o.id AND "
                     "x.kind = 'analise' AND x.payload_json LIKE ?)", [*args, f'%"agent_id":"{agent}"%'])
    rows = conn.execute(sql + " ORDER BY o.created_at DESC LIMIT ?", [*args, limit]).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["verdicts"] = [dict(v) for v in conn.execute(
            "SELECT horizon_days, status, verdict FROM radar_outcomes WHERE opportunity_id = ? ORDER BY horizon_days, "
            "method_version", (r["id"],))]
        out.append(item)
    return out
