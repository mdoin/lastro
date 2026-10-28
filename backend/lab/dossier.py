# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dossiê congelado de um experimento: a ÚNICA fonte de dados dos dois modos (as ferramentas de leitura ao vivo
ficam desligadas no Laboratório). Montado uma vez, guardado com hash e entregue igual ao Bento e ao Conselho.

Bloqueio de look-ahead: nada com data de referência posterior à data de corte entra; numa data simulada também
fica de fora o que foi registrado depois dela (retrato, fatos). Mesmo assim, com data simulada o experimento é
marcado NÃO COMPARÁVEL para previsões: o modelo pode conhecer o período pela base de treinamento e as séries podem ter
sido revisadas depois — isso o Laboratório não tem como impedir, então declara.
"""

import hashlib
import json
import sqlite3
from datetime import date

from integrations.catalog import SERIES, SOURCE_NAMES

from app import store, views

LOOKAHEAD_MODEL = ("Data simulada no passado: o modelo de IA pode conhecer o que aconteceu depois pela base de "
                   "treinamento. O Laboratório não consegue apagar essa memória, então as previsões deste experimento "
                   "não entram nas métricas de calibração.")
LOOKAHEAD_REVISION = "Séries oficiais podem ter sido revisadas depois da data simulada (o valor usado é o atual)."


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _snapshot(conn: sqlite3.Connection, user_id: str, cutoff: str, simulated: bool) -> dict | None:
    sql = "SELECT * FROM financial_snapshots WHERE user_id = ? AND as_of <= ?"
    args = [user_id, cutoff[:10]]
    if simulated:
        sql, args = sql + " AND created_at <= ?", [*args, cutoff]
    row = conn.execute(sql + " ORDER BY as_of DESC, created_at DESC LIMIT 1", args).fetchone()
    if not row:
        return None
    snap = store._snapshot_row_to_dict(conn, row)
    out = {k: snap[k] for k in ("as_of", "net_monthly_income", "essential_expenses", "variable_expenses",
                                "liquid_reserve", "available_this_month")}
    out["dividas"] = [{k: d.get(k) for k in ("name", "balance", "monthly_rate", "monthly_payment")} for d in snap["debts"]]
    return out


def build(conn: sqlite3.Connection, user_id: str, *, as_of: date, today: date) -> dict:
    """Dossiê com a data de corte `as_of` (hoje ou data simulada no passado)."""
    simulated = as_of < today
    cutoff = f"{as_of.isoformat()}T23:59:59"
    dossier: dict = {"data_de_corte": as_of.isoformat(), "simulado": simulated}
    dossier["retrato_financeiro"] = _snapshot(conn, user_id, cutoff, simulated)
    if not simulated and dossier["retrato_financeiro"]:
        try:  # diagnóstico do motor determinístico sobre o mesmo retrato (só na data de hoje: é calculado ao vivo)
            diag = views.diagnosis_view(conn)
            dossier["diagnostico_do_motor"] = {"fluxo_livre_mensal": diag["free_cash_flow"],
                                               "divida_total": diag["total_debt"],
                                               "meses_de_reserva": diag["reserve"]["coverage_months"],
                                               "etapa": diag["guidance"]["stage"]}
        except (views.NoData, ValueError, KeyError):
            pass
    facts = [f for f in store.list_facts(conn, user_id, "confirmed") if f["created_at"] <= cutoff]
    dossier["fatos_confirmados"] = [{"chave": f["key"], "valor": f["value"], "desde": f["created_at"][:10]}
                                    for f in facts[:40]]
    market, sources = [], []
    for s in SERIES.values():
        row = conn.execute("SELECT reference_date, value, fetched_at FROM market_data WHERE source = ? AND series_id = ? "
                           "AND reference_date <= ? ORDER BY reference_date DESC LIMIT 1",
                           (s.source, s.id, as_of.isoformat())).fetchone()
        if not row:
            continue
        stale = (as_of - date.fromisoformat(row["reference_date"][:10])).days > s.max_age_days
        market.append({"serie": s.id, "rotulo": s.label, "valor": row["value"], "unidade": s.unit,
                       "data_referencia": row["reference_date"][:10], "desatualizada": stale})
        sources.append({"serie": s.id, "fonte": SOURCE_NAMES[s.source], "data_referencia": row["reference_date"][:10],
                        "coletado_em": row["fetched_at"], "coletado_depois_do_corte": row["fetched_at"] > cutoff})
    dossier["mercado"] = market
    notes = []
    if simulated:
        notes += [LOOKAHEAD_MODEL, LOOKAHEAD_REVISION]
        if any(x["coletado_depois_do_corte"] for x in sources):
            notes.append("Parte das séries foi coletada depois da data simulada (valor de referência anterior a ela).")
    if not dossier["retrato_financeiro"]:
        notes.append("Sem retrato financeiro registrado até a data de corte: a análise fica sem a situação da pessoa.")
    if not market:
        notes.append("Sem séries de mercado até a data de corte.")
    return {"dossie": dossier, "fontes": sources, "avisos": notes, "comparavel": not simulated}


def render(question: str, dossier: dict) -> str:
    """Texto entregue igual aos dois modos (o mesmo dossiê, a mesma ordem, os mesmos números)."""
    d = dossier
    lines = [f"Pergunta: {question}", "", f"Data de corte das informações: {d['data_de_corte']}"
             + (" (data simulada: não use nada que tenha acontecido depois dela)" if d["simulado"] else "")]
    snap = d.get("retrato_financeiro")
    if snap:
        lines += ["", f"Retrato financeiro da pessoa (registrado em {snap['as_of']}):",
                  f"- Renda líquida mensal: R$ {snap['net_monthly_income']}",
                  f"- Despesas essenciais: R$ {snap['essential_expenses']}",
                  f"- Despesas variáveis: R$ {snap['variable_expenses']}",
                  f"- Reserva líquida: R$ {snap['liquid_reserve']}",
                  f"- Disponível no mês: R$ {snap['available_this_month']}"]
        for debt in snap["dividas"]:
            lines.append(f"- Dívida {debt['name']}: saldo R$ {debt['balance']}, juros {debt['monthly_rate']} ao mês, "
                         f"parcela R$ {debt['monthly_payment']}")
    else:
        lines += ["", "Retrato financeiro da pessoa: não registrado até a data de corte."]
    diag = d.get("diagnostico_do_motor")
    if diag:
        lines += ["", "Diagnóstico do motor determinístico:",
                  f"- Fluxo livre mensal: R$ {diag['fluxo_livre_mensal']}", f"- Dívida total: R$ {diag['divida_total']}",
                  f"- Meses de reserva: {diag['meses_de_reserva']}", f"- Etapa: {diag['etapa']}"]
    if d["fatos_confirmados"]:
        lines += ["", "Fatos confirmados pela pessoa:"] + [f"- {f['chave']}: {f['valor']} (desde {f['desde']})"
                                                           for f in d["fatos_confirmados"]]
    if d["mercado"]:
        lines += ["", "Séries oficiais (valor mais recente até a data de corte):"]
        lines += [f"- {m['rotulo']} ({m['serie']}): {m['valor']} {m['unidade']}, referência {m['data_referencia']}"
                  + (" — DESATUALIZADA" if m["desatualizada"] else "") for m in d["mercado"]]
    else:
        lines += ["", "Séries oficiais: nenhuma disponível até a data de corte."]
    return "\n".join(lines)
