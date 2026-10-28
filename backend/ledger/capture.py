# SPDX-License-Identifier: AGPL-3.0-or-later
"""Memória financeira automática: o que a pessoa disse EXPLICITAMENTE na conversa vira registro (com
consentimento) ou pendência, para ela não ter de repetir tudo num formulário.

Determinístico de propósito: a frase é da própria pessoa, mas a interpretação não passa por modelo, então
"talvez eu compre", "e se eu colocar" ou "vou receber" nunca viram movimentação, e um texto de agente nunca
registra nada (só mensagens com role "user" chegam aqui). Na dúvida, vira pendência que pede só o que falta.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app import store
from app.store import new_id, utcnow
from financial_engine.money import parse_brl
from team.auditor import fold

from . import book

CLASSES = {
    "fato": "Fato financeiro", "receita": "Receita realizada", "despesa": "Despesa realizada",
    "transferencia": "Transferência", "saldo": "Saldo ou disponibilidade", "recorrente": "Despesa recorrente",
    "divida": "Dívida", "meta": "Meta", "decisao": "Decisão", "intencao": "Intenção futura", "simulacao": "Simulação",
    "insuficiente": "Informação insuficiente",
}

_MONEY = re.compile(r"(?:R\$\s?(?P<a>\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)(?P<am>\s?mil\b)?)|"
                    r"(?:(?P<b>\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)(?P<bm>\s?mil)?\s?reais\b)", re.I)
_NEG = re.compile(r"\bnao\s+(gastei|paguei|comprei|recebi|transferi|tenho|devo|ganhei)\b")
_SIM = re.compile(r"\b(se eu|e se|caso eu|supondo|simula\w*|imagina se|hipotetic\w*)\b")
_DECISION = re.compile(r"\b(decidi|resolvi|bati o martelo|optei)\b")
_GOAL = re.compile(r"\b(minha meta|meu objetivo|meta de|objetivo de)\b|\b(quero|pretendo|planejo|preciso)\b.{0,40}"
                   r"\b(juntar|guardar|economizar|acumular|poupar|atingir)\b")
_INTENT = re.compile(r"\b(talvez|pretendo|vou|quero|queria|penso em|pensando em|planejo|gostaria|estou querendo|"
                     r"pode ser que|cogitando|considerando|devo comprar|vou receber|irei)\b")
_FACT_INCOME = re.compile(r"\b(minha renda|meu salario|ganho|recebo)\b.{0,50}\b(por mes|mensal\w*|ao mes|todo mes)\b")
_RECURRING = re.compile(r"\b(por mes|ao mes|mensal\w*|todo mes|todos os meses)\b")
_DEBT = re.compile(r"\b(devo|divida|estou devendo|financiamento|emprestimo|cheque especial|rotativo)\b")
_INCOME = re.compile(r"\b(recebi|ganhei|caiu|entrou|me pagaram|depositaram|recebemos)\b")
_EXPENSE = re.compile(r"\b(gastei|paguei|comprei|torrei|desembolsei|gastamos|pagamos|compramos|saiu)\b")
_TRANSFER = re.compile(r"\b(transferi|mandei|enviei|fiz um pix|fiz pix|passei|depositei|apliquei|guardei)\b")
_BALANCE = re.compile(r"\b(tenho|sobrou|sobraram|sobrando|disponivel|na conta|saldo)\b")
_OWN_ACCOUNT = re.compile(r"\b(minha conta|minha poupanca|poupanca|minha reserva|reserva|investimento|corretora|"
                          r"tesouro|cdb|outra conta)\b")
_DATE = re.compile(r"\b(?P<rel>hoje|ontem|anteontem)\b|\bdia (?P<day>\d{1,2})\b|\b(?P<d>\d{1,2})/(?P<m>\d{1,2})"
                   r"(?:/(?P<y>\d{2,4}))?\b")
_PLACE = re.compile(r"\b(?:no|na|nos|nas|em|com|pro|pra|de|do|da)\s+(?!R\$)(?P<p>[A-Za-zÀ-ÿ0-9][\wÀ-ÿ&'.-]*(?:\s+(?!hoje\b|"
                    r"ontem\b|dia\b|por\b|de\b|e\b|no\b|na\b|em\b|com\b|para\b|pra\b|R\$)[A-Za-zÀ-ÿ0-9][\wÀ-ÿ&'.-]*){0,2})")
_STOP_PLACE = {"hoje", "ontem", "anteontem", "dia", "mes", "mês", "reais", "salario", "salário"}


@dataclass
class Capture:
    classification: str
    span: str
    amount: Decimal | None = None
    occurred_on: date | None = None
    date_assumed: bool = False
    counterparty: str = ""
    missing: list = field(default_factory=list)
    own_account: bool = False

    def fields(self) -> dict:
        return {"amount": str(self.amount) if self.amount is not None else None,
                "occurred_on": self.occurred_on.isoformat() if self.occurred_on else None,
                "date_assumed": self.date_assumed, "counterparty": self.counterparty}


def _amounts(text: str) -> list[Decimal]:
    found = []
    for m in _MONEY.finditer(text):
        raw, thousand = (m.group("a"), m.group("am")) if m.group("a") else (m.group("b"), m.group("bm"))
        try:
            value = parse_brl(raw)
        except (ValueError, InvalidOperation):
            continue
        found.append(value * 1000 if thousand else value)
    return found


def _date(folded: str, today: date) -> tuple[date | None, bool]:
    m = _DATE.search(folded)
    if not m:
        return None, False
    if m.group("rel"):
        return today - timedelta(days={"hoje": 0, "ontem": 1, "anteontem": 2}[m.group("rel")]), False
    try:
        if m.group("day"):
            day = int(m.group("day"))
            when = today.replace(day=day)
            if when > today:  # "dia 30" dito no dia 5: mês passado
                when = (today.replace(day=1) - timedelta(days=1)).replace(day=day)
            return when, False
        year = int(m.group("y") or today.year)
        year = year + 2000 if year < 100 else year
        when = date(year, int(m.group("m")), int(m.group("d")))
        return (when if when <= today else None), False
    except ValueError:
        return None, False


def _place(original: str) -> str:
    for m in _PLACE.finditer(original):
        text = m.group("p").strip(" .,;")
        if fold(text.split()[0]) not in _STOP_PLACE and not text[0].isdigit():
            return text[:60]
    return ""


def _classify(folded: str) -> str | None:
    if _NEG.search(folded):
        return None
    if _SIM.search(folded):
        return "simulacao"
    if _DECISION.search(folded):
        return "decisao"
    if _GOAL.search(folded):
        return "meta"
    past = _INCOME.search(folded) or _EXPENSE.search(folded) or _TRANSFER.search(folded)
    if _INTENT.search(folded) and not past:
        return "intencao"
    if _FACT_INCOME.search(folded):
        return "fato"
    if _RECURRING.search(folded) and not past:
        return "recorrente"
    if _DEBT.search(folded) and not past:
        return "divida"
    if _INCOME.search(folded):
        return "receita"
    if _EXPENSE.search(folded):
        return "despesa"
    if _TRANSFER.search(folded):
        return "transferencia"
    if _BALANCE.search(folded):
        return "saldo"
    return None


def extract(text: str, today: date) -> list[Capture]:
    """Frases da pessoa → capturas. Frase sem valor só vira captura se for um registro claramente faltando valor."""
    out = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text or ""):
        sentence = sentence.strip()
        if not sentence or len(sentence) > 400:
            continue
        folded = fold(sentence)
        kind = _classify(folded)
        if kind is None:
            continue
        amounts = _amounts(sentence)
        if len(amounts) > 1 and kind in ("despesa", "receita"):
            # "gastei R$ 50 no mercado e R$ 20 no Uber": um registro por valor, cada um com o próprio lugar
            parts = re.split(r",\s*|\s+e\s+(?=R\$|\d)", sentence)
            pieces = [(p, _amounts(p)) for p in parts if _amounts(p)]
        else:
            pieces = [(sentence, amounts)]
        for piece, values in pieces:
            when, assumed = _date(fold(piece), today)
            if when is None:
                when, assumed = _date(folded, today)
            if when is None and kind in ("despesa", "receita", "transferencia"):
                when, assumed = today, True  # data da mensagem, marcada como suposta
            cap = Capture(kind, piece[:200], values[0] if len(values) == 1 else None, when, assumed,
                          _place(piece), own_account=bool(_OWN_ACCOUNT.search(fold(piece))))
            if kind in ("despesa", "receita", "transferencia", "saldo", "recorrente", "divida", "fato"):
                if cap.amount is None:
                    cap.missing.append("valor")
                    if kind in ("saldo", "recorrente", "divida", "fato"):
                        continue  # sem valor, não há o que guardar nem perguntar
                    cap.classification = "insuficiente" if not values else kind
            out.append(cap)
    return out


# ---------- aplicação ----------

def _slug(cap: "Capture", fallback: str) -> str:
    """Nome curto para a chave do fato: "Meu aluguel é…" → aluguel; senão o lugar citado."""
    folded = fold(cap.span)
    m = re.search(r"\b(?:meu|minha|meus|minhas|o|a|do|da|de)\s+([a-z]{3,})", folded)
    text = m.group(1) if m else fold(cap.counterparty)
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:24] or fallback


def _label(cap: Capture) -> str:
    value = f"R$ {cap.amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if cap.amount is not None else ""
    return " ".join(p for p in (CLASSES[cap.classification].lower(), value, cap.counterparty and f"({cap.counterparty})") if p)


def _save(conn, user_id: str, message: dict, cap: Capture, status: str, target_kind: str | None,
          target_id: str | None) -> dict:
    cap_id, now = new_id(), utcnow()
    conn.execute("INSERT OR IGNORE INTO captures (id, user_id, message_id, conversation_id, span, classification, "
                 "fields_json, missing_json, status, target_kind, target_id, created_at, updated_at) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (cap_id, user_id, message["id"], message.get("conversation_id") or "", cap.span, cap.classification,
                  json.dumps(cap.fields(), ensure_ascii=False), json.dumps(cap.missing), status, target_kind,
                  target_id, now, now))
    return {"id": cap_id, "classification": cap.classification, "label": _label(cap), "status": status,
            "missing": cap.missing, "target_kind": target_kind, "target_id": target_id, **cap.fields()}


def process_message(conn: sqlite3.Connection, user_id: str, conv_id: str, message: dict, today: date) -> list[dict]:
    """Reconhece e aplica. Devolve o que aconteceu (para a confirmação discreta no chat)."""
    if message.get("role") != "user":
        return []
    auto = book.consent(conn, user_id, "auto_register")
    message = {**message, "conversation_id": conv_id}
    done = []
    for cap in extract(message["content"], today):
        ref, detail = message["id"], cap.span[:80]
        if cap.classification in ("intencao", "simulacao"):
            done.append(_save(conn, user_id, message, cap, "informativo", None, None))
        elif cap.classification == "decisao":
            done.append(_save(conn, user_id, message, cap, "pendente", "diario", None))
        elif cap.classification in ("despesa", "receita", "transferencia", "insuficiente"):
            kind = "despesa" if cap.classification == "insuficiente" else cap.classification
            if cap.classification == "insuficiente" and _INCOME.search(fold(cap.span)):
                kind = "receita"
            amount = None if cap.amount is None else (-cap.amount if kind == "despesa" or
                                                      (kind == "transferencia") else cap.amount)
            complete = amount is not None and cap.occurred_on is not None
            # transferência só é neutra com certeza se for para conta própria; para outra pessoa pode ser gasto
            clear = complete and (kind != "transferencia" or cap.own_account)
            match, exact = (book.similar(conn, user_id, amount=amount, occurred_on=cap.occurred_on, kind=kind,
                                         exclude_ref=ref, counterparty=cap.counterparty) if complete else (None, False))
            status = "registrado" if auto and clear and not match else "pendente"
            entry = book.add_entry(
                conn, user_id, kind=kind, status=status, amount=amount, occurred_on=cap.occurred_on,
                source_kind="conversa", source_ref=ref, source_detail=detail, confidence="alta" if clear else "media",
                actor="pessoa:conversa" if status == "registrado" else "lastro", description=cap.span[:200],
                counterparty=cap.counterparty, fp=book.fingerprint(user_id, "conversa", ref, cap.span),
                missing=cap.missing + ([] if kind != "transferencia" or cap.own_account else ["destino"]),
                reconciliation="possivel_duplicata" if match else "nao_conciliado",
                matched_id=match["id"] if match else None,
                note="data da mensagem (não informada)" if cap.date_assumed else "")
            if entry:
                done.append(_save(conn, user_id, message, cap, status, "ledger", entry["id"]))
        else:  # saldo, fato, recorrente, dívida, meta → memória financeira (fato datado), nunca movimentação
            key = {"saldo": "disponivel_para_investir" if "invest" in fold(cap.span) else "saldo_disponivel",
                   "fato": "renda_mensal_informada",
                   "recorrente": f"recorrente_{_slug(cap, 'despesa')}",
                   "divida": f"divida_{_slug(cap, 'informada')}",
                   "meta": f"meta_{_slug(cap, 'informada')}"}[cap.classification]
            value = (f"{cap.amount}" + (" por mês" if cap.classification == "recorrente" else "")) if cap.amount \
                else cap.span[:200]
            # Despesa recorrente, dívida e meta são sempre propostas: a pessoa confirma o compromisso.
            confirmed = auto and cap.classification in ("saldo", "fato")
            fact = store.add_fact(conn, user_id, key, value, source="pessoa:conversa",
                                  status="confirmed" if confirmed else "proposed",
                                  as_of=(cap.occurred_on or today).isoformat(), note=cap.span[:200], source_ref=ref)
            done.append(_save(conn, user_id, message, cap, "registrado" if confirmed else "pendente", "fato", fact["id"]))
    return done


def notice_text(done: list[dict]) -> str | None:
    shown = [d for d in done if d["status"] != "informativo"]
    if not shown:
        return None
    registered = [d["label"] for d in shown if d["status"] == "registrado"]
    pending = [d for d in shown if d["status"] == "pendente"]
    parts = []
    if registered:
        parts.append("Registrei: " + "; ".join(registered) + ".")
    if pending:
        asks = [f"{d['label']}" + (f" — falta: {', '.join(d['missing'])}" if d["missing"] else "") for d in pending]
        parts.append("Para revisar: " + "; ".join(asks) + ".")
    return " ".join(parts)


# ---------- ações da pessoa sobre uma captura ----------

def _capture(conn, user_id: str, capture_id: str) -> dict:
    row = conn.execute("SELECT * FROM captures WHERE id = ? AND user_id = ?", (capture_id, user_id)).fetchone()
    if not row:
        raise book.LedgerError("Registro inexistente.")
    return dict(row)


def _set(conn, capture_id: str, status: str) -> None:
    conn.execute("UPDATE captures SET status = ?, updated_at = ? WHERE id = ?", (status, utcnow(), capture_id))


def _retract_fact(conn, user_id: str, fact_id: str) -> None:
    row = conn.execute("SELECT * FROM financial_facts WHERE id = ? AND user_id = ?", (fact_id, user_id)).fetchone()
    if not row:
        return
    conn.execute("UPDATE financial_facts SET status = 'rejected', decided_at = ? WHERE id = ?", (utcnow(), fact_id))
    if row["status"] == "confirmed" and row["supersedes_id"]:  # volta o valor confirmado anterior
        conn.execute("UPDATE financial_facts SET status = 'confirmed' WHERE id = ? AND status = 'superseded'",
                     (row["supersedes_id"],))


def act(conn: sqlite3.Connection, user_id: str, capture_id: str, action: str, today: date,
        changes: dict | None = None) -> dict:
    """desfazer | confirmar (com os campos que faltavam) | descartar."""
    cap = _capture(conn, user_id, capture_id)
    kind, target = cap["target_kind"], cap["target_id"]
    if action == "desfazer":
        if cap["status"] != "registrado":
            raise book.LedgerError("Só registros feitos podem ser desfeitos.")
        if kind == "ledger":
            book.update_entry(conn, user_id, target, "desfazer", actor="pessoa")
        elif kind == "fato":
            _retract_fact(conn, user_id, target)
        _set(conn, capture_id, "desfeito")
    elif action == "confirmar":
        if cap["status"] != "pendente":
            raise book.LedgerError("Este registro não está pendente.")
        if kind == "ledger":
            book.update_entry(conn, user_id, target, "confirmar", actor="pessoa", changes=changes or {})
        elif kind == "fato":
            if not store.decide_fact(conn, user_id, target, True, today.isoformat()):
                raise book.LedgerError("Proposta já decidida.")
        else:
            raise book.LedgerError("Decisões são confirmadas no Diário de Decisões.")
        _set(conn, capture_id, "registrado")
    elif action == "descartar":
        if cap["status"] != "pendente":
            raise book.LedgerError("Este registro não está pendente.")
        if kind == "ledger":
            book.update_entry(conn, user_id, target, "descartar", actor="pessoa")
        elif kind == "fato":
            store.decide_fact(conn, user_id, target, False, today.isoformat())
        _set(conn, capture_id, "descartado")
    else:
        raise book.LedgerError("Ação desconhecida.")
    return {**_capture(conn, user_id, capture_id), "fields": json.loads(cap["fields_json"])}


def list_captures(conn: sqlite3.Connection, user_id: str, status: str | None = None, limit: int = 100) -> list[dict]:
    sql, args = "SELECT * FROM captures WHERE user_id = ?", [user_id]
    if status:
        sql, args = sql + " AND status = ?", [*args, status]
    rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
    return [{**dict(r), "fields": json.loads(r["fields_json"]), "missing": json.loads(r["missing_json"]),
             "label": CLASSES.get(r["classification"], r["classification"])} for r in rows]
