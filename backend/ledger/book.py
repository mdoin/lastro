# SPDX-License-Identifier: AGPL-3.0-or-later
"""Livro de movimentações: gravação validada, idempotência, conciliação, desfazer e totais.

Regras que valem para toda origem (conversa, documento, IA):
- valor em Decimal, com o sinal do fluxo de dinheiro (negativo = saiu); nunca float;
- só conta nos totais o que está `registrado` e efetivado (`settled`); pendências, duplicatas e desfeitos não;
- transferência, pagamento de fatura e saldo não são receita nem despesa;
- toda mudança de estado vai para `ledger_events` (append-only) com quem fez e o antes/depois;
- nada aqui cria ou altera retrato financeiro (financial_snapshots): o livro é outra camada, ao lado.
"""

import hashlib
import json
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.store import new_id, utcnow
from financial_engine.money import round_brl
from team.auditor import fold

KINDS = ("despesa", "receita", "transferencia", "pagamento_fatura", "estorno", "reembolso")
NEUTRAL = ("transferencia", "pagamento_fatura")
CONSENT_SCOPES = ("auto_register", "ai_documents")
MAX_ABS = Decimal("100000000")
DUPLICATE_WINDOW_DAYS = 3

# Categoria por palavras-chave (descrição/contraparte, sem acento). A primeira que casar vale.
CATEGORIES = (
    ("transporte", "Transporte", ("uber", "99 ", "99pop", "taxi", "onibus", "metro", "gasolina", "combustivel",
                                  "posto ", "estacionamento", "pedagio", "bilhete unico", "cabify")),
    ("alimentacao", "Alimentação", ("ifood", "rappi", "restaurante", "lanchonete", "lanche", "padaria", "almoco",
                                    "jantar", "cafe", "pizzaria", "hamburg", "delivery")),
    ("mercado", "Mercado", ("supermercado", "mercado", "feira", "atacadao", "carrefour", "pao de acucar", "assai",
                            "hortifruti", "sacolao")),
    ("moradia", "Moradia", ("aluguel", "condominio", "iptu", "conta de luz", "energia", "enel", "cemig", "sabesp",
                            "conta de agua", "gas ", "internet", "vivo fibra", "claro net")),
    ("saude", "Saúde", ("farmacia", "drogaria", "drogasil", "raia", "medico", "consulta", "plano de saude", "exame",
                        "hospital", "dentista", "unimed")),
    ("educacao", "Educação", ("curso", "escola", "faculdade", "livraria", "livro", "mensalidade escolar", "udemy",
                              "alura")),
    ("lazer", "Lazer", ("cinema", "netflix", "spotify", "show", "ingresso", "viagem", "hotel", "airbnb", "bar ",
                        "streaming", "disney", "prime video", "hbo")),
    ("compras", "Compras", ("loja", "amazon", "mercado livre", "mercadolivre", "shopee", "magalu", "renner", "roupa",
                            "shein", "aliexpress")),
    ("assinaturas", "Assinaturas", ("assinatura", "mensalidade", "icloud", "google one", "chatgpt", "youtube premium")),
    ("salario", "Salário", ("salario", "folha", "pagto salario", "vencimentos", "pro labore", "pro-labore")),
    ("trabalho_extra", "Trabalho extra", ("freela", "freelance", "bico", "servico prestado", "honorario")),
    ("investimentos", "Investimentos", ("tesouro", "cdb", "corretora", "aplicacao", "resgate", "dividendo",
                                        "rendimento")),
)
LABELS = {key: label for key, label, _ in CATEGORIES} | {"outros": "Outros", "outras_receitas": "Outras receitas",
                                                         "transferencias": "Transferências"}


class LedgerError(ValueError):
    """Mensagem em português, segura para mostrar à pessoa."""


def categorize(text: str, kind: str) -> str:
    folded = f" {fold(text)} "
    if kind in NEUTRAL:
        return "transferencias"
    for key, _label, words in CATEGORIES:
        if any(w in folded for w in words):
            if kind == "receita" and key not in ("salario", "trabalho_extra", "investimentos"):
                continue
            return key
    return "outras_receitas" if kind == "receita" else "outros"


def amount_of(value) -> Decimal:
    try:
        number = round_brl(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        raise LedgerError("Valor inválido.") from None
    if not number.is_finite() or abs(number) > MAX_ABS:
        raise LedgerError("Valor fora do intervalo aceito.")
    return number


def fingerprint(user_id: str, *parts) -> str:
    raw = "|".join([user_id, *[fold(str(p)).strip() for p in parts]])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


# ---------- consentimento ----------

def consent(conn: sqlite3.Connection, user_id: str, scope: str) -> bool:
    row = conn.execute("SELECT granted FROM consents WHERE user_id = ? AND scope = ?", (user_id, scope)).fetchone()
    return bool(row and row[0])


def consents(conn: sqlite3.Connection, user_id: str) -> dict:
    rows = {r["scope"]: r for r in conn.execute("SELECT * FROM consents WHERE user_id = ?", (user_id,))}
    return {s: {"granted": bool(rows[s]["granted"]) if s in rows else False,
                "updated_at": rows[s]["updated_at"] if s in rows else None} for s in CONSENT_SCOPES}


def set_consent(conn: sqlite3.Connection, user_id: str, scope: str, granted: bool) -> dict:
    if scope not in CONSENT_SCOPES:
        raise LedgerError("Consentimento desconhecido.")
    conn.execute("INSERT INTO consents (user_id, scope, granted, updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id, "
                 "scope) DO UPDATE SET granted = excluded.granted, updated_at = excluded.updated_at",
                 (user_id, scope, int(bool(granted)), utcnow()))
    return consents(conn, user_id)


# ---------- movimentações ----------

def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    out = dict(r)
    out["missing"] = json.loads(out.pop("missing_json") or "[]")
    out["settled"] = bool(out["settled"])
    out["category_label"] = LABELS.get(out["category"], out["category"])
    return out


def get_entry(conn: sqlite3.Connection, user_id: str, entry_id: str) -> dict | None:
    return _row(conn.execute("SELECT * FROM ledger_entries WHERE id = ? AND user_id = ?", (entry_id, user_id)).fetchone())


def _event(conn, entry_id: str, user_id: str, action: str, before: dict | None, after: dict | None, actor: str) -> None:
    conn.execute("INSERT INTO ledger_events (id, entry_id, user_id, action, before_json, after_json, actor, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?)",
                 (new_id(), entry_id, user_id, action, json.dumps(before, ensure_ascii=False, default=str) if before else None,
                  json.dumps(after, ensure_ascii=False, default=str) if after else None, actor, utcnow()))


def add_entry(conn: sqlite3.Connection, user_id: str, *, kind: str, status: str, amount, occurred_on: date | None,
              source_kind: str, source_ref: str, confidence: str, actor: str, description: str = "",
              counterparty: str = "", category: str | None = None, currency: str = "BRL", institution: str = "",
              account: str = "", external_id: str = "", fp: str | None = None, installment: str = "",
              settled: bool = True, accrual_on: date | None = None, source_detail: str = "",
              missing: list | None = None, reconciliation: str = "nao_conciliado", matched_id: str | None = None,
              note: str = "") -> dict | None:
    """Grava uma movimentação. Devolve None se a impressão digital já existe (importação repetida)."""
    if kind not in KINDS:
        raise LedgerError("Tipo de movimentação desconhecido.")
    value = amount_of(amount) if amount is not None else None
    if status == "registrado" and (value is None or occurred_on is None or missing):
        raise LedgerError("Só registra com valor e data conhecidos.")
    if currency != "BRL" and status == "registrado":
        status = "pendente"  # shortcut: sem conversão de câmbio; outra moeda sempre passa pela pessoa
        missing = [*(missing or []), "cotação"]
    if fp and conn.execute("SELECT 1 FROM ledger_entries WHERE user_id = ? AND fingerprint = ?", (user_id, fp)).fetchone():
        return None
    entry_id, now = new_id(), utcnow()
    conn.execute(
        "INSERT INTO ledger_entries (id, user_id, kind, status, occurred_on, accrual_on, amount, currency, description, "
        "counterparty, category, institution, account, external_id, fingerprint, installment, settled, reconciliation, "
        "matched_id, confidence, source_kind, source_ref, source_detail, missing_json, note, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (entry_id, user_id, kind, status, occurred_on.isoformat() if occurred_on else None,
         accrual_on.isoformat() if accrual_on else None, str(value) if value is not None else None, currency,
         description[:200], counterparty[:120], category or categorize(f"{description} {counterparty}", kind),
         institution[:60], account[-4:], external_id[:80], fp, installment, int(bool(settled)), reconciliation,
         matched_id, confidence, source_kind, source_ref, source_detail[:80], json.dumps(missing or []), note[:300],
         now, now))
    entry = get_entry(conn, user_id, entry_id)
    _event(conn, entry_id, user_id, "criado", None, entry, actor)
    return entry


EDITABLE = {"kind", "category", "amount", "occurred_on", "description", "counterparty", "settled"}


def update_entry(conn: sqlite3.Connection, user_id: str, entry_id: str, action: str, *, actor: str,
                 changes: dict | None = None) -> dict:
    """Transições permitidas (validadas aqui, não na rota):
    confirmar (pendente → registrado), descartar (pendente → descartado), desfazer (registrado → desfeito),
    restaurar (desfeito → registrado), corrigir (campos editáveis), e_duplicada / nao_e_duplicada."""
    before = get_entry(conn, user_id, entry_id)
    if not before:
        raise LedgerError("Movimentação inexistente.")
    fields: dict = {}
    for key, value in (changes or {}).items():
        if key not in EDITABLE:
            raise LedgerError(f"Campo não editável: {key}.")
        if key == "kind" and value not in KINDS:
            raise LedgerError("Tipo de movimentação desconhecido.")
        if key == "category" and value not in LABELS:
            raise LedgerError("Categoria desconhecida.")
        if key == "amount":
            value = amount_of(value)
            kind = (changes or {}).get("kind", before["kind"])
            # a pessoa digita o valor sem sinal; o sinal vem do tipo (despesa sai, receita entra)
            value = str(-abs(value) if kind in ("despesa", "pagamento_fatura") else abs(value) if kind in (
                "receita", "estorno", "reembolso") else value)
        if key == "occurred_on":
            value = date.fromisoformat(str(value)).isoformat()
        if key == "settled":
            value = int(bool(value))
        fields[key] = str(value)[:200] if key in ("description", "counterparty") else value
    merged = {**before, **fields}
    missing = [m for m in before["missing"] if not ((m == "valor" and merged.get("amount"))
                                                    or (m == "data" and merged.get("occurred_on")))]
    status, extra = before["status"], {}
    if action == "confirmar":
        if status not in ("pendente", "duplicada"):
            raise LedgerError("Só pendências podem ser confirmadas.")
        if not merged.get("amount") or not merged.get("occurred_on") or missing:
            raise LedgerError("Falta informação: " + ", ".join(missing or ["valor", "data"]) + ".")
        status, extra = "registrado", {"reconciliation": "conciliado" if before["matched_id"] else "nao_conciliado"}
    elif action == "descartar":
        if status not in ("pendente", "duplicada"):
            raise LedgerError("Só pendências podem ser descartadas.")
        status = "descartado"
    elif action == "desfazer":
        if status != "registrado":
            raise LedgerError("Só lançamentos registrados podem ser desfeitos.")
        status = "desfeito"
    elif action == "restaurar":
        if status != "desfeito":
            raise LedgerError("Só lançamentos desfeitos podem ser restaurados.")
        status = "registrado"
    elif action == "e_duplicada":
        if status not in ("pendente", "registrado") or not before["matched_id"]:
            raise LedgerError("Não há movimentação parecida ligada a esta.")
        status, extra = "duplicada", {"reconciliation": "conciliado"}
    elif action == "nao_e_duplicada":
        if before["reconciliation"] != "possivel_duplicata" and status != "duplicada":
            raise LedgerError("Esta movimentação não está marcada como possível duplicata.")
        status, extra = "pendente", {"reconciliation": "nao_conciliado", "matched_id": None}
    elif action != "corrigir":
        raise LedgerError("Ação desconhecida.")
    if status == "registrado" and before["currency"] != "BRL":
        raise LedgerError("Movimentação em outra moeda: informe o valor em reais antes de registrar.")
    sets = {**fields, **extra, "status": status, "missing_json": json.dumps(missing), "updated_at": utcnow()}
    conn.execute(f"UPDATE ledger_entries SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ? AND user_id = ?",
                 (*sets.values(), entry_id, user_id))
    after = get_entry(conn, user_id, entry_id)
    _event(conn, entry_id, user_id, action, before, after, actor)
    return after


def list_entries(conn: sqlite3.Connection, user_id: str, *, status: str | None = None, source_ref: str | None = None,
                 limit: int = 300) -> list[dict]:
    sql, args = "SELECT * FROM ledger_entries WHERE user_id = ?", [user_id]
    if status:
        sql, args = sql + " AND status = ?", [*args, status]
    if source_ref:
        sql, args = sql + " AND source_ref = ?", [*args, source_ref]
    rows = conn.execute(sql + " ORDER BY COALESCE(occurred_on, '9999') DESC, created_at DESC LIMIT ?", (*args, limit))
    return [_row(r) for r in rows]


def events(conn: sqlite3.Connection, user_id: str, entry_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT id, action, actor, created_at FROM ledger_events WHERE entry_id = ? "
                                          "AND user_id = ? ORDER BY created_at", (entry_id, user_id))]


# ---------- conciliação ----------

def similar(conn: sqlite3.Connection, user_id: str, *, amount: Decimal, occurred_on: date, kind: str,
            exclude_ref: str, counterparty: str = "") -> tuple[dict | None, bool]:
    """Movimentação já existente (registrada ou pendente, de OUTRA origem) com o mesmo valor em até 3 dias.
    Devolve (a parecida, exata?) — exata quando mesma data e contraparte compatível."""
    low = (occurred_on - timedelta(days=DUPLICATE_WINDOW_DAYS)).isoformat()
    high = (occurred_on + timedelta(days=DUPLICATE_WINDOW_DAYS)).isoformat()
    rows = conn.execute("SELECT * FROM ledger_entries WHERE user_id = ? AND amount = ? AND kind = ? AND "
                        "status IN ('registrado', 'pendente') AND occurred_on BETWEEN ? AND ? AND source_ref != ? "
                        "ORDER BY occurred_on", (user_id, str(amount_of(amount)), kind, low, high, exclude_ref)).fetchall()
    if not rows:
        return None, False
    words = {w for w in fold(counterparty).split() if len(w) > 2}
    for r in rows:
        theirs = {w for w in fold(f"{r['counterparty']} {r['description']}").split() if len(w) > 2}
        if r["occurred_on"] == occurred_on.isoformat() and (not words or not theirs or words & theirs):
            return _row(r), True
    return _row(rows[0]), False


# ---------- totais ----------

def summary(conn: sqlite3.Connection, user_id: str, start: date, end: date) -> dict:
    """Totais do período só com movimentações registradas e efetivadas. Estorno e reembolso abatem despesas;
    transferências e pagamento de fatura aparecem à parte e não somam."""
    rows = conn.execute("SELECT * FROM ledger_entries WHERE user_id = ? AND occurred_on BETWEEN ? AND ?",
                        (user_id, start.isoformat(), end.isoformat())).fetchall()
    income = expenses = refunds = neutral = Decimal("0")
    by_category: dict[str, Decimal] = {}
    counts = {"registrado": 0, "pendente": 0, "duplicada": 0, "futuro": 0}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] += 1
        if r["status"] != "registrado" or r["amount"] is None:
            continue
        if not r["settled"]:
            counts["futuro"] += 1
            continue
        value = Decimal(r["amount"])
        if r["kind"] == "receita":
            income += value
        elif r["kind"] == "despesa":
            expenses += -value
            by_category[r["category"]] = by_category.get(r["category"], Decimal("0")) + -value
        elif r["kind"] in ("estorno", "reembolso"):
            refunds += value
            by_category[r["category"]] = by_category.get(r["category"], Decimal("0")) - value
        else:
            neutral += abs(value)
    pending = conn.execute("SELECT COUNT(*) FROM ledger_entries WHERE user_id = ? AND status = 'pendente'",
                           (user_id,)).fetchone()[0]
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "income": str(round_brl(income)), "expenses": str(round_brl(expenses - refunds)),
        "refunds": str(round_brl(refunds)), "neutral_moves": str(round_brl(neutral)),
        "by_category": [{"category": k, "label": LABELS.get(k, k), "amount": str(round_brl(v))}
                        for k, v in sorted(by_category.items(), key=lambda kv: -kv[1]) if v],
        "counts": counts, "pending_total": pending,
        "basis": "Derivado de movimentações registradas e efetivadas. Não altera seus retratos financeiros; "
                 "transferências, pagamento de fatura e saldos não contam como receita ou despesa.",
    }


def month_bounds(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end
