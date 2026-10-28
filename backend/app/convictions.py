# SPDX-License-Identifier: AGPL-3.0-or-later
"""Convicções: previsões declaradas pelos agentes, conferidas depois e medidas (Brier e calibração).

Uma previsão é uma linha do parecer ou da fala no Conselho, num formato fixo:
    - 70% · 2027-03-31 · selic_meta < 10.5 · A meta da Selic estará abaixo de 10,5% ao ano.
probabilidade (1–99%) de a afirmação ser verdadeira NA data, a data, a condição verificável (série do catálogo ou
"cripto:BTC" em USDT) ou "—" quando só a pessoa pode conferir, e a afirmação. O Lastro grava a linha como foi dita
(probabilidade, data e condição nunca mudam depois: trigger no banco), confere com o dado coletado quando há
condição e pede à pessoa quando não há. Nada aqui chama modelo nem rede.
"""

import json
import re
import sqlite3
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from crypto import assets
from integrations.catalog import SERIES, SOURCE_NAMES

from .db import utcnow

LINE = re.compile(r"^[ \t]*[-*][ \t]*(\d{1,3})[ \t]*%[ \t]*[·|;][ \t]*(\d{4}-\d{2}-\d{2})[ \t]*[·|;][ \t]*([^·|;\n]+?)"
                  r"[ \t]*[·|;][ \t]*([^\n]+?)[ \t]*$", re.MULTILINE)
CHECK = re.compile(r"^(?:(cripto):)?([a-z0-9_]{2,20})[ \t]*(<=|>=|<|>)[ \t]*(-?\d+(?:[.,]\d+)?)$", re.IGNORECASE)
MANUAL = {"—", "-", "–", "manual", "pessoa", "sem condicao", "sem condição"}
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}
MAX_YEARS = 5
GRACE_DAYS = 45          # sem dado da fonte até aqui depois da data: "indeterminada" (fora da conta)
CRYPTO_FRESH_DAYS = 2
SMALL_SAMPLE = 10
MAX_PER_MESSAGE = 3
BASELINE = Decimal("0.25")  # Brier de quem sempre diz 50%
RESOLVED = ("aconteceu", "nao_aconteceu")


def parse(text: str, today: date) -> tuple[list[dict], list[str]]:
    """Previsões válidas e o motivo de cada linha recusada. Linha recusada não vira previsão."""
    found, refused = [], []
    for m in LINE.finditer(text or ""):
        pct, due, cond, statement = int(m.group(1)), m.group(2), m.group(3).strip(), m.group(4).strip()
        try:
            due_on = date.fromisoformat(due)
        except ValueError:
            refused.append(f"data inválida: {due}")
            continue
        if not 1 <= pct <= 99:
            refused.append(f"probabilidade fora de 1–99%: {pct}%")
        elif not today < due_on <= today + timedelta(days=365 * MAX_YEARS):
            refused.append(f"data fora do intervalo (amanhã a {MAX_YEARS} anos): {due}")
        elif not 10 <= len(statement) <= 300:
            refused.append("afirmação curta ou longa demais")
        else:
            check, why = _check(cond)
            if why:
                refused.append(why)
                continue
            found.append({"probability": (Decimal(pct) / 100).quantize(Decimal("0.01")), "due_on": due, "check": check, "statement": statement})
    return found, refused


def _check(cond: str) -> tuple[dict | None, str | None]:
    if cond.lower() in MANUAL:
        return None, None
    m = CHECK.match(cond)
    if not m:
        return None, f"condição não reconhecida: {cond[:40]}"
    crypto, ident, op, raw = m.groups()
    try:
        value = str(Decimal(raw.replace(",", ".")))
    except InvalidOperation:
        return None, f"valor inválido: {raw}"
    if crypto:
        try:
            asset = assets.get(ident.upper())
        except ValueError:
            return None, f"ativo fora do registro: {ident}"
        if not asset.binance_symbol:
            return None, f"sem cotação em USDT para {asset.symbol}"
        return {"kind": "cripto", "symbol": asset.symbol, "op": op, "value": value}, None
    if ident.lower() not in SERIES:
        return None, f"série fora do catálogo: {ident}"
    return {"kind": "serie", "series_id": ident.lower(), "op": op, "value": value}, None


def strip(text: str) -> str:
    """Texto sem as linhas de previsão: a probabilidade e o limiar não são números a auditar como dado."""
    return LINE.sub("", text or "")


def record(conn: sqlite3.Connection, *, user_id: str, agent_id: str, message: dict, today: date) -> list[dict]:
    """Grava as previsões de uma mensagem publicada. Idempotente por (mensagem, ordem da linha)."""
    found = parse(message.get("content") or "", today)[0][:MAX_PER_MESSAGE]
    for i, p in enumerate(found):
        conn.execute(
            "INSERT OR IGNORE INTO predictions (id, user_id, agent_id, conversation_id, run_id, message_id, ordinal, "
            "statement, probability, due_on, check_json, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), user_id, agent_id, message.get("conversation_id"), message.get("run_id"),
             message["id"], i, p["statement"], str(p["probability"]), p["due_on"],
             json.dumps(p["check"]) if p["check"] else None, "aberta", utcnow()))
    return found


def _row(r) -> dict:
    d = dict(r)
    d["check"] = json.loads(d.pop("check_json")) if d.get("check_json") else None
    d["observed"] = json.loads(d.pop("observed_json")) if d.get("observed_json") else None
    d["brier"] = _num(brier(Decimal(d["probability"]), d["status"])) if d["status"] in RESOLVED else None
    return d


def _num(value: Decimal) -> str:
    return f"{round(value, 4).normalize():f}"


def brier(p: Decimal, status: str) -> Decimal:
    outcome = Decimal(1) if status == "aconteceu" else Decimal(0)
    return (p - outcome) ** 2


def _observe(conn, check: dict, due: date) -> tuple[dict | None, bool]:
    """(observação na data, a fonte já publicou depois da data). Observação velha demais não vale."""
    if check["kind"] == "serie":
        s = SERIES[check["series_id"]]
        row = conn.execute("SELECT reference_date, value FROM market_data WHERE source = ? AND series_id = ? "
                           "AND reference_date <= ? ORDER BY reference_date DESC LIMIT 1",
                           (s.source, s.id, due.isoformat())).fetchone()
        after = conn.execute("SELECT 1 FROM market_data WHERE source = ? AND series_id = ? AND reference_date > ?",
                             (s.source, s.id, due.isoformat())).fetchone() is not None
        if row and (due - date.fromisoformat(row["reference_date"][:10])).days <= s.max_age_days:
            return {"value": row["value"], "reference_date": row["reference_date"], "unit": s.unit, "label": s.label,
                    "source": SOURCE_NAMES[s.source]}, after
        return None, after
    end = f"{due.isoformat()}T23:59:59"
    row = conn.execute("SELECT price, reference_time, source FROM crypto_quotes WHERE symbol = ? AND quote_currency = "
                       "'USDT' AND reference_time <= ? ORDER BY reference_time DESC LIMIT 1",
                       (check["symbol"], end)).fetchone()
    after = conn.execute("SELECT 1 FROM crypto_quotes WHERE symbol = ? AND quote_currency = 'USDT' AND "
                         "reference_time > ?", (check["symbol"], end)).fetchone() is not None
    if row and (due - date.fromisoformat(row["reference_time"][:10])).days <= CRYPTO_FRESH_DAYS:
        return {"value": row["price"], "reference_date": row["reference_time"], "unit": "USDT",
                "label": f"{check['symbol']} em USDT", "source": row["source"]}, after
    return None, after


def resolve_due(conn: sqlite3.Connection, today: date) -> int:
    """Confere as previsões vencidas que têm condição. Espera a fonte publicar o dado da data (ou o prazo de
    tolerância); sem dado utilizável, a previsão fica "indeterminada" e não entra na conta."""
    done = 0
    for r in conn.execute("SELECT * FROM predictions WHERE status = 'aberta' AND check_json IS NOT NULL AND due_on <= ?",
                          (today.isoformat(),)).fetchall():
        check, due = json.loads(r["check_json"]), date.fromisoformat(r["due_on"])
        observed, after = _observe(conn, check, due)
        late = (today - due).days > GRACE_DAYS
        if observed and (after or late):
            ok = OPS[check["op"]](Decimal(observed["value"]), Decimal(check["value"]))
            status, note = ("aconteceu" if ok else "nao_aconteceu"), None
        elif late:
            status, note = "indeterminada", "A fonte não tem dado utilizável para a data; fica fora da medição."
        else:
            continue
        conn.execute("UPDATE predictions SET status = ?, observed_json = ?, resolved_by = 'dados', resolved_at = ?, "
                     "note = ? WHERE id = ? AND status = 'aberta'",
                     (status, json.dumps(observed) if observed else None, utcnow(), note, r["id"]))
        done += 1
    return done


def resolve_manual(conn: sqlite3.Connection, user_id: str, pred_id: str, outcome: str, note: str, today: date) -> dict:
    """A pessoa confere uma previsão sem condição automática (depois da data) ou anula qualquer uma aberta."""
    r = conn.execute("SELECT * FROM predictions WHERE id = ? AND user_id = ?", (pred_id, user_id)).fetchone()
    if r is None:
        raise LookupError("Previsão inexistente.")
    if r["status"] != "aberta":
        raise ValueError("Esta previsão já foi conferida.")
    if outcome not in (*RESOLVED, "anulada"):
        raise ValueError("Resultado inválido.")
    if outcome != "anulada":
        if r["check_json"]:
            raise ValueError("Esta previsão é conferida pelos dados da fonte, não manualmente.")
        if r["due_on"] > today.isoformat():
            raise ValueError("A previsão vale para a data combinada; confira a partir dela.")
    conn.execute("UPDATE predictions SET status = ?, resolved_by = 'pessoa', resolved_at = ?, note = ? WHERE id = ?",
                 (outcome, utcnow(), (note or "").strip()[:300] or None, pred_id))
    return _row(conn.execute("SELECT * FROM predictions WHERE id = ?", (pred_id,)).fetchone())


def listing(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM predictions WHERE user_id = ? ORDER BY due_on, created_at", (user_id,))
    return [_row(r) for r in rows]


def stats(rows: list[dict]) -> dict:
    """Brier médio (0 é perfeito; 0,25 é dizer sempre 50%), acertos e calibração por faixa de probabilidade."""
    resolved = [r for r in rows if r["status"] in RESOLVED]
    n = len(resolved)
    out = {"resolved": n, "open": sum(r["status"] == "aberta" for r in rows),
           "indeterminate": sum(r["status"] == "indeterminada" for r in rows), "small_sample": n < SMALL_SAMPLE,
           "baseline": str(BASELINE), "brier": None, "hits": 0, "mean_probability": None, "observed_rate": None,
           "buckets": []}
    if not n:
        return out
    ps = [Decimal(r["probability"]) for r in resolved]
    hits = [r["status"] == "aconteceu" for r in resolved]
    out["brier"] = _num(sum(brier(p, r["status"]) for p, r in zip(ps, resolved)) / n)
    out["hits"] = sum((p >= Decimal("0.5")) == h for p, h in zip(ps, hits))
    out["mean_probability"] = _num(sum(ps) / n)
    out["observed_rate"] = _num(Decimal(sum(hits)) / n)
    for lo in range(0, 100, 20):
        inside = [(p, h) for p, h in zip(ps, hits) if lo <= p * 100 < lo + 20 or (lo == 80 and p * 100 == 100)]
        if inside:
            out["buckets"].append({"from": lo, "to": lo + 20, "n": len(inside),
                                   "mean_probability": _num(sum(p for p, _ in inside) / len(inside)),
                                   "observed_rate": _num(Decimal(sum(h for _, h in inside)) / len(inside))})
    return out


def by_agent(conn: sqlite3.Connection, user_id: str) -> dict[str, dict]:
    rows = listing(conn, user_id)
    agents = dict.fromkeys(r["agent_id"] for r in rows)
    return {a: stats([r for r in rows if r["agent_id"] == a]) for a in agents}


def track_line(conn: sqlite3.Connection, user_id: str, agent_id: str) -> str | None:
    """Uma linha para o próprio agente ver o histórico dele (prestação de contas), só com previsões conferidas."""
    s = stats([r for r in listing(conn, user_id) if r["agent_id"] == agent_id])
    if not s["resolved"]:
        return None
    pct = lambda v: f"{Decimal(v) * 100:.0f}%"  # noqa: E731
    text = (f"Seu histórico de previsões: {s['resolved']} conferida(s), Brier {s['brier']} (0 é perfeito; 0,25 é "
            f"dizer sempre 50%), probabilidade média {pct(s['mean_probability'])} e acerto observado "
            f"{pct(s['observed_rate'])}.")
    if s["small_sample"]:
        text += " Amostra pequena: não tire conclusões fortes dela."
    return text
