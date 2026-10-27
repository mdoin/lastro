"""Indicadores de qualidade do Radar e propostas de ajuste controladas.

Só entram sinais e alertas reais (backtests ficam em radar_backtests, decisões e operações da pessoa à parte).
Toda taxa sai com o tamanho da amostra; abaixo de MIN_SAMPLE ela é marcada como não confiável.
"""

import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from financial_engine.money import to_decimal

from . import rules as rules_mod

MIN_SAMPLE = 20
PRIMARY_HORIZON = 90
EVALUABLE = ("confirmada", "nao_confirmada", "favoravel_por_outro_motivo", "inconclusivo")
LIMITATIONS = ("Taxas com menos de 20 casos são exibidas, mas não devem ser lidas como indicador confiável.",
               "Acerto é medido contra a hipótese e o critério registrados antes do resultado, por horizonte; "
               "'favorável por outro motivo' não conta como acerto do raciocínio original.",
               "Resultados de backtest (simulados) não entram aqui.")


def _rate(num: int, den: int) -> dict:
    value = (Decimal(num) / Decimal(den)).quantize(Decimal("0.001")) if den else None
    return {"valor": str(value) if value is not None else None, "n": den, "confiavel": den >= MIN_SAMPLE}


def _hours(a: str, b: str) -> Decimal:
    delta = datetime.fromisoformat(b) - datetime.fromisoformat(a)
    return (Decimal(delta.total_seconds()) / Decimal(3600)).quantize(Decimal("0.1"))


def _median(values: list) -> str | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return str(s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2)


def _latest_outcomes(conn, opp_ids: list[str], horizon: int | None) -> dict:
    """Último método de cada (oportunidade, horizonte), já calculado."""
    if not opp_ids:
        return {}
    marks = ",".join("?" * len(opp_ids))
    sql = (f"SELECT r.* FROM radar_outcomes r WHERE r.opportunity_id IN ({marks}) AND r.status != 'pendente' AND "
           "r.method_version = (SELECT MAX(i.method_version) FROM radar_outcomes i WHERE i.opportunity_id = "
           "r.opportunity_id AND i.horizon_days = r.horizon_days)")
    args = list(opp_ids)
    if horizon:
        sql, args = sql + " AND r.horizon_days = ?", [*args, horizon]
    out: dict = {}
    for r in conn.execute(sql, args):
        out.setdefault(r["opportunity_id"], []).append({**dict(r), "result": json.loads(r["result_json"])})
    return out


def _block(conn, opps: list[dict], horizon: int) -> dict:
    ids = [o["id"] for o in opps]
    outcomes = _latest_outcomes(conn, ids, horizon)
    verdicts = [r["verdict"] for rows in outcomes.values() for r in rows]
    evaluable = [v for v in verdicts if v in EVALUABLE]
    excess = [to_decimal(r["result"]["excesso_vs_cdi_pp"]) for rows in outcomes.values() for r in rows
              if r["verdict"] in EVALUABLE and r["result"].get("excesso_vs_cdi_pp")]
    alerts = [o for o in opps if o.get("alert_id")]
    rated = [o for o in alerts if o.get("feedback")]
    return {
        "sinais": len(opps), "alertas": len(alerts),
        "vereditos": {v: verdicts.count(v) for v in sorted(set(verdicts))},
        "precisao": _rate(evaluable.count("confirmada"), len(evaluable)),
        "favoravel_outro_motivo": _rate(evaluable.count("favoravel_por_outro_motivo"), len(evaluable)),
        "invalidados": _rate(verdicts.count("invalidada"), len(verdicts)),
        "dados_insuficientes": _rate(verdicts.count("dados_insuficientes"), len(verdicts)),
        "redundantes": _rate(sum(1 for o in opps if o["redundant_of"]), len(opps)),
        "utilidade_informada": _rate(sum(1 for o in rated if o["feedback"] == "util"), len(rated)),
        "excesso_medio_vs_cdi_pp": str((sum(excess, Decimal(0)) / len(excess)).quantize(Decimal("0.01")))
        if excess else None,
        "n_excesso": len(excess),
    }


def compute(conn, user_id: str, *, since: str | None = None, until: str | None = None,
            horizon: int = PRIMARY_HORIZON) -> dict:
    rows = conn.execute(
        "SELECT o.*, a.id AS alert_id, a.feedback, a.created_at AS alert_at, a.occurrences, s.reference_date, "
        "s.detected_at FROM radar_opportunities o JOIN radar_signals s ON s.id = o.signal_id LEFT JOIN radar_alerts a "
        "ON a.opportunity_id = o.id WHERE o.user_id = ? AND o.created_at >= ? AND o.created_at <= ? "
        "ORDER BY o.created_at", (user_id, since or "0000", until or "9999")).fetchall()
    opps = [dict(r) for r in rows]
    states: dict = {}
    for o in opps:
        states[o["state"]] = states.get(o["state"], 0) + 1
    detect_lag = [Decimal((datetime.fromisoformat(o["detected_at"]).date() - date.fromisoformat(o["reference_date"])).days)
                  for o in opps]
    notify_lag = [_hours(o["detected_at"], o["alert_at"]) for o in opps if o.get("alert_at")]
    by_category = {c: _block(conn, [o for o in opps if o["category"] == c], horizon)
                   for c in sorted({o["category"] for o in opps})}
    rule_names = {r["id"]: r["name"] for r in rules_mod.current(conn, user_id, include_archived=True)}
    by_rule = {rid: {"nome": rule_names.get(rid, rid), **_block(conn, [o for o in opps if o["rule_id"] == rid], horizon)}
               for rid in sorted({o["rule_id"] for o in opps})}
    months = sorted({o["created_at"][:7] for o in opps})
    trend = [{"mes": m, **_block(conn, [o for o in opps if o["created_at"][:7] == m], horizon)} for m in months]
    return {
        "periodo": {"de": opps[0]["created_at"] if opps else since, "ate": opps[-1]["created_at"] if opps else until},
        "horizonte_dias": horizon, "amostra_minima": MIN_SAMPLE,
        "totais": {"sinais": len(opps), "alertas": sum(1 for o in opps if o["alert_id"]),
                   "estados": states},
        "geral": _block(conn, opps, horizon),
        "por_categoria": by_category, "por_regra": by_rule, "tendencia_mensal": trend,
        "latencia": {"evento_ate_deteccao_dias_mediana": _median(detect_lag), "n_deteccao": len(detect_lag),
                     "deteccao_ate_alerta_horas_mediana": _median(notify_lag), "n_alerta": len(notify_lag),
                     "nota": "Para dados diários, a latência inclui o atraso de publicação da fonte."},
        "limitacoes": list(LIMITATIONS),
    }


# ---------- aprendizado controlado ----------

def propose_adjustments(conn, user_id: str, now: str, *, backtest=None) -> list[dict]:
    """Propõe ajustes para regras ruidosas. Nada entra em vigor sem aprovação explícita da pessoa, e só com amostra
    mínima (MIN_SAMPLE) — poucos resultados nunca mudam uma regra."""
    data = compute(conn, user_id)["por_regra"]
    created = []
    for rule in rules_mod.current(conn, user_id):
        stats = data.get(rule["id"])
        if not stats or rule["status"] != "ativa":
            continue
        if conn.execute("SELECT 1 FROM radar_rule_proposals WHERE rule_id = ? AND status = 'pendente'",
                        (rule["id"],)).fetchone():
            continue
        change, why = _suggestion(rule, stats)
        if not change:
            continue
        backtest_id = None
        if backtest is not None and rule["kind"] in ("limite", "variacao", "queda"):
            proposed = {**rule, **change, "params": {**rule["params"], **change.get("params", {})}}
            backtest_id = backtest(proposed)["id"]
        rec = {"id": str(uuid.uuid4()), "user_id": user_id, "rule_id": rule["id"], "base_version": rule["version"],
               "change_json": json.dumps(change, ensure_ascii=False), "rationale_json": json.dumps(
                   {"motivo": why, "estatisticas": stats}, ensure_ascii=False), "backtest_id": backtest_id,
               "status": "pendente", "created_at": now}
        conn.execute("INSERT INTO radar_rule_proposals (id, user_id, rule_id, base_version, change_json, rationale_json, "
                     "backtest_id, status, created_at) VALUES (:id,:user_id,:rule_id,:base_version,:change_json,"
                     ":rationale_json,:backtest_id,:status,:created_at)", rec)
        created.append(rec)
    return created


def _suggestion(rule: dict, stats: dict) -> tuple[dict, str]:
    if stats["redundantes"]["confiavel"] and to_decimal(stats["redundantes"]["valor"]) >= Decimal("0.5"):
        rearm = min(rule["params"].get("rearme_dias", 7) * 2, 365)
        return {"params": {"rearme_dias": rearm}}, "Metade ou mais dos sinais repetiu um alerta recente."
    if stats["dados_insuficientes"]["confiavel"] and to_decimal(stats["dados_insuficientes"]["valor"]) >= Decimal("0.5"):
        return {"status": "pausada"}, "Metade ou mais das avaliações ficou sem dados suficientes."
    useful = stats["utilidade_informada"]
    if useful["confiavel"] and to_decimal(useful["valor"]) <= Decimal("0.3") and rule["priority"] > 1:
        return {"priority": rule["priority"] - 1}, "Você marcou 70% ou mais destes alertas como irrelevantes."
    precision = stats["precisao"]
    if precision["confiavel"] and to_decimal(precision["valor"]) < Decimal("0.3") and rule["kind"] == "limite":
        op, value = rule["params"]["operador"], to_decimal(rule["params"]["valor"])
        step = to_decimal(rule["params"]["tolerancia"])
        new = value + step if op == ">=" else value - step
        return {"params": {"valor": str(new)}}, "Menos de 30% das hipóteses avaliáveis se confirmaram: limite mais exigente."
    return {}, ""


def decide_proposal(conn, user_id: str, proposal_id: str, approve: bool, now: str) -> dict | None:
    row = conn.execute("SELECT * FROM radar_rule_proposals WHERE id = ? AND user_id = ? AND status = 'pendente'",
                       (proposal_id, user_id)).fetchone()
    if not row:
        return None
    current = rules_mod.get(conn, row["rule_id"])
    if approve and current["version"] != row["base_version"]:
        conn.execute("UPDATE radar_rule_proposals SET status = 'obsoleta', decided_at = ? WHERE id = ?", (now, proposal_id))
        raise ValueError("A regra mudou depois da proposta; a proposta ficou obsoleta.")
    if approve:
        rules_mod.update(conn, user_id, row["rule_id"], json.loads(row["change_json"]), now=now, origin="proposta")
    conn.execute("UPDATE radar_rule_proposals SET status = ?, decided_at = ? WHERE id = ?",
                 ("aprovada" if approve else "recusada", now, proposal_id))
    return dict(conn.execute("SELECT * FROM radar_rule_proposals WHERE id = ?", (proposal_id,)).fetchone())


def list_proposals(conn, user_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM radar_rule_proposals WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    return [{**dict(r), "change": json.loads(r["change_json"]), "rationale": json.loads(r["rationale_json"])}
            for r in rows]


def journal_summary(conn, user_id: str, today: date, days: int = 30) -> dict:
    """Resumo do Diário para os agentes (somente leitura): o que foi detectado, o que aconteceu e a qualidade."""
    from . import journal

    since = since_days(today, days)
    items = [{"id": o["id"], "detectada_em": o["created_at"][:10], "ativo": o["asset_label"], "categoria": o["category"],
              "regra": o["rule_id"], "classificacao": o["classification"], "estado": o["state"],
              "condicao": o["condition_text"], "alerta": bool(o["alert_id"]), "utilidade": o["alert_feedback"],
              "avaliacoes": [{"horizonte_dias": v["horizon_days"], "veredito": v["verdict"]} for v in o["verdicts"]
                             if v["status"] != "pendente"]}
             for o in journal.list_for(conn, user_id, since=since, limit=60)]
    m = compute(conn, user_id, since=since)
    return {"data_kind": "owner", "periodo_dias": days, "oportunidades": items,
            "metricas": {"totais": m["totais"], "geral": m["geral"], "por_regra": m["por_regra"]},
            "limitacoes": m["limitacoes"],
            "nota": "Registros do Diário: classificação e hipótese são as originais; avaliações vêm depois, por horizonte."}


def since_days(today: date, days: int) -> str:
    return (today - timedelta(days=days)).isoformat()
