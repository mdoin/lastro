# SPDX-License-Identifier: AGPL-3.0-or-later
"""Avaliação posterior das oportunidades: um método por tipo de produto, versionado e determinístico.

Regras de honestidade:
- a hipótese e os critérios vêm do registro de detecção (escritos antes do resultado), nunca de dado posterior;
- cada horizonte é calculado uma vez por versão de método; corrigir a metodologia = nova versão, a antiga fica;
- se o dado do horizonte ainda não saiu, a avaliação espera (até GRACE_DAYS); depois vira "dados insuficientes";
- renda fixa distingue retorno contratado (carregamento) de resgate antecipado (preço de recompra do dia);
- renda variável usa retorno total com proventos e eventos corporativos; nunca a mesma fórmula para tudo.

Veredictos (docs/RADAR.md §Metodologia): confirmada, nao_confirmada, favoravel_por_outro_motivo, inconclusivo,
invalidada, dados_insuficientes, sem_hipotese.
"""

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal, localcontext

from financial_engine.money import CALC_CONTEXT, to_decimal

from . import journal
from .evaluator import TD_CUSTODY_ANNUAL
from .observations import history, revisions_after

METHOD_VERSION = "1"
GRACE_DAYS = 10
HORIZON_SLACK_DAYS = 7          # o primeiro dado até 7 dias depois da data do horizonte serve
MAX_ATTEMPTS = 40
ONE, ZERO, HUNDRED = Decimal(1), Decimal(0), Decimal(100)
# IOF regressivo sobre o rendimento (Decreto 6.306/2007, anexo): % por dia corrido de aplicação, 1..29.
IOF_TABLE = (96, 93, 90, 86, 83, 80, 76, 73, 70, 66, 63, 60, 56, 53, 50, 46, 43, 40, 36, 33, 30, 26, 23, 20, 16, 13,
             10, 6, 3)
VERDICTS = ("confirmada", "nao_confirmada", "favoravel_por_outro_motivo", "inconclusivo", "invalidada",
            "dados_insuficientes", "sem_hipotese")


class NotYet(Exception):
    """O dado do horizonte ainda não foi publicado: tentar de novo depois."""


def ir_rate(days: int) -> Decimal:
    """IR regressivo de renda fixa (Lei 11.033/2004, art. 1º)."""
    return Decimal("0.225") if days <= 180 else Decimal("0.20") if days <= 360 else Decimal("0.175") if days <= 720 \
        else Decimal("0.15")


def iof_rate(days: int) -> Decimal:
    return Decimal(IOF_TABLE[days - 1]) / HUNDRED if 1 <= days < 30 else ZERO


def net_of_taxes(gain: Decimal, days: int) -> tuple[Decimal, Decimal, Decimal]:
    """(ganho líquido, IOF, IR) sobre um ganho em fração do capital. Perda não paga imposto."""
    if gain <= 0:
        return gain, ZERO, ZERO
    iof = gain * iof_rate(days)
    ir = (gain - iof) * ir_rate(days)
    return gain - iof - ir, iof, ir


def _first_from(points, day: str, slack: int = HORIZON_SLACK_DAYS):
    limit = (date.fromisoformat(day) + timedelta(slack)).isoformat()
    return next((p for p in points if day <= p.reference_date <= limit), None)


def _due(t0: str, horizon: int) -> str:
    return (date.fromisoformat(t0) + timedelta(horizon)).isoformat()


def _wait_or_fail(day: str, today: date, what: str, slack: int = HORIZON_SLACK_DAYS):
    """Espera o dado sair (data do horizonte + folga de publicação + GRACE_DAYS); depois, dados insuficientes."""
    if today <= date.fromisoformat(day) + timedelta(slack + GRACE_DAYS):
        raise NotYet(what)
    return "dados_insuficientes", "dados_insuficientes", {"motivo": what}


def accumulate_cdi(conn, start: str, end: str, today: date) -> dict:
    """CDI acumulado entre start (exclusive) e end (inclusive), com a cobertura verificada."""
    points = history(conn, "cdi_diario", since=(date.fromisoformat(start) + timedelta(1)).isoformat(), until=end)
    if not points or points[-1].reference_date < (date.fromisoformat(end) - timedelta(4)).isoformat() or \
            points[0].reference_date > (date.fromisoformat(start) + timedelta(6)).isoformat():
        raise NotYet("CDI diário do período ainda incompleto")
    weekdays = sum(1 for i in range(1, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
                   if (date.fromisoformat(start) + timedelta(i)).weekday() < 5)
    if len(points) < weekdays * Decimal("0.85"):
        raise NotYet("CDI diário com falhas no período")
    with localcontext(CALC_CONTEXT):
        factor = ONE
        for p in points:
            factor *= ONE + p.value / HUNDRED
    return {"acumulado": factor - ONE, "dias_uteis": len(points), "de": points[0].reference_date,
            "ate": points[-1].reference_date}


def accumulate_ipca(conn, start: str, end: str) -> Decimal | None:
    """IPCA dos meses inteiros entre as datas (aproximação mensal); None se algum mês ainda não saiu."""
    first = date.fromisoformat(start).replace(day=1)
    last = date.fromisoformat(end).replace(day=1)
    months, cursor = [], first
    while cursor < last:
        months.append(cursor.isoformat())
        cursor = (cursor + timedelta(32)).replace(day=1)
    if not months:
        return ZERO
    values = {p.reference_date: p.value for p in history(conn, "ipca_mensal", since=months[0], until=months[-1])}
    if any(m not in values for m in months):
        return None
    with localcontext(CALC_CONTEXT):
        factor = ONE
        for m in months:
            factor *= ONE + values[m] / HUNDRED
    return factor - ONE


def path_stats(values: list[Decimal]) -> dict:
    """Maior queda (pico a vale) e volatilidade anualizada (√252) de uma trajetória de valores."""
    if len(values) < 2:
        return {"maior_queda": None, "volatilidade_anual": None}
    with localcontext(CALC_CONTEXT):
        peak, worst = values[0], ZERO
        for v in values:
            peak = max(peak, v)
            worst = max(worst, ONE - v / peak)
        vol = None
        if len(values) >= 10:
            rets = [(b / a).ln() for a, b in zip(values, values[1:]) if a > 0 and b > 0]
            mean = sum(rets, ZERO) / len(rets)
            var = sum(((r - mean) ** 2 for r in rets), ZERO) / (len(rets) - 1)
            vol = var.sqrt() * Decimal(252).sqrt()
    return {"maior_queda": str(worst.quantize(Decimal("0.0001"))),
            "volatilidade_anual": str(vol.quantize(Decimal("0.0001"))) if vol is not None else None}


def _revised(conn, detection: dict) -> bool:
    obs = detection["sinal"].get("observation_id")
    if not obs:
        return False
    base = to_decimal(detection["sinal"]["valor_observado"]) if detection["sinal"].get("valor_observado") else None
    return any(base is None or to_decimal(r["value"]) != base for r in revisions_after(conn, obs))


def _verdict(hyp: dict, excess_pp: Decimal, mechanism_ok: bool | None) -> str:
    band = to_decimal(hyp["criterio"].get("banda_inconclusiva_pp", "0"))
    if abs(excess_pp) < band:
        return "inconclusivo"
    if excess_pp >= to_decimal(hyp["criterio"]["valor"]):
        return "confirmada" if mechanism_ok in (True, None) else "favoravel_por_outro_motivo"
    return "nao_confirmada"


def _pct(x: Decimal | None) -> str | None:
    return None if x is None else str((x * HUNDRED).quantize(Decimal("0.01")))


# ---------- métodos ----------

def _coupon_between(maturity: str, start: str, end: str) -> bool:
    """Títulos com juros semestrais pagam cupom no dia e mês do vencimento e seis meses depois."""
    m = date.fromisoformat(maturity)
    months = {m.month, (m.month + 5) % 12 + 1}
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return any(date(y, mo, m.day) > a and date(y, mo, m.day) <= b for y in range(a.year, b.year + 1) for mo in months)


def method_td(conn, detection: dict, horizon: int, today: date):
    meta, t0 = detection["serie"], detection["sinal"]["reference_date"]
    kind, maturity = meta["meta"]["tipo"], meta["meta"]["vencimento"]
    pu0 = (detection["dados"].get("pu_compra") or {}).get("value")
    rate0 = to_decimal(detection["sinal"]["valor_observado"])
    if not pu0:
        return "dados_insuficientes", "dados_insuficientes", {"motivo": "preço de compra na detecção indisponível"}
    d1 = _due(t0, horizon)
    if maturity <= d1:
        return "dados_insuficientes", "dados_insuficientes", {
            "motivo": "o título venceu antes do horizonte; o método v1 só avalia resgate antecipado"}
    if kind.endswith("_js") and _coupon_between(maturity, t0, d1):
        return "dados_insuficientes", "dados_insuficientes", {
            "motivo": "houve pagamento de cupom semestral no período; o método v1 não soma cupons, então não avalia"}
    prefix = f"td_{kind}_{maturity}"
    exit_path = history(conn, f"{prefix}_pu_venda", since=t0, until=(date.fromisoformat(d1) + timedelta(
        HORIZON_SLACK_DAYS)).isoformat())
    exit_point = _first_from(exit_path, d1)
    if exit_point is None:
        return _wait_or_fail(d1, today, "preço de recompra do Tesouro na data do horizonte ainda indisponível")
    rate_point = _first_from(history(conn, f"{prefix}_taxa_compra", since=d1), d1)
    days = (date.fromisoformat(exit_point.reference_date) - date.fromisoformat(t0)).days
    cdi = accumulate_cdi(conn, t0, exit_point.reference_date, today)
    with localcontext(CALC_CONTEXT):
        gross = exit_point.value / to_decimal(pu0) - ONE
        custody = TD_CUSTODY_ANNUAL * Decimal(days) / Decimal(365)
        net, iof, ir = net_of_taxes(gross - custody, days)
        bench_net, _, _ = net_of_taxes(cdi["acumulado"], days)
        excess_pp = (net - bench_net) * HUNDRED
        ipca = accumulate_ipca(conn, t0, exit_point.reference_date)
        real = (ONE + net) / (ONE + ipca) - ONE if ipca is not None else None
    rate_change = rate_point.value - rate0 if rate_point else None
    path = [p.value for p in exit_path if p.reference_date <= exit_point.reference_date]
    result = {
        "metodo": "td_marcacao", "versao_metodo": METHOD_VERSION, "data_inicial": t0,
        "data_final": exit_point.reference_date, "dias": days,
        "preco_inicial_compra": pu0, "preco_final_recompra": str(exit_point.value),
        "retorno_bruto_pct": _pct(gross), "custodia_pct": _pct(custody), "iof_pct": _pct(iof), "ir_pct": _pct(ir),
        "retorno_liquido_pct": _pct(net), "retorno_real_pct": _pct(real),
        "ipca_periodo_pct": _pct(ipca) if ipca is not None else None,
        "cdi_bruto_pct": _pct(cdi["acumulado"]), "cdi_liquido_pct": _pct(bench_net),
        "excesso_vs_cdi_pp": str(excess_pp.quantize(Decimal("0.01"))),
        "taxa_inicial": str(rate0), "taxa_final": str(rate_point.value) if rate_point else None,
        "variacao_taxa_pp": str(rate_change) if rate_change is not None else None,
        "retorno_contratado": detection.get("contexto", {}).get("retorno_contratado"),
        **path_stats(path),
        "notas": ["Resgate antecipado ao preço de recompra do Tesouro (marcação a mercado); levar ao vencimento "
                  "entrega o retorno contratado, que é outra coisa.",
                  "Impostos e custódia estimados pelas premissas do registro original."],
    }
    if _revised(conn, detection):
        return "calculado", "invalidada", {**result, "motivo": "o dado que disparou o sinal foi revisado pela fonte"}
    mechanism = rate_change < 0 if rate_change is not None else None
    return "calculado", _verdict(detection["hipotese"], excess_pp, mechanism), result


def method_price(conn, detection: dict, horizon: int, today: date):
    meta, t0 = detection["serie"], detection["sinal"]["reference_date"]
    sid, p0 = meta["series_id"], to_decimal(detection["sinal"]["valor_observado"])
    d1 = _due(t0, horizon)
    path = history(conn, sid, since=t0, until=(date.fromisoformat(d1) + timedelta(HORIZON_SLACK_DAYS)).isoformat())
    end = _first_from(path, d1)
    if end is None:
        return _wait_or_fail(d1, today, "preço do ativo na data do horizonte não informado")
    path = [p for p in path if p.reference_date <= end.reference_date]
    events = conn.execute("SELECT ex_date, kind, factor FROM radar_corporate_events WHERE series_id = ? AND ex_date > ? "
                          "AND ex_date <= ? ORDER BY ex_date", (sid, t0, end.reference_date)).fetchall()
    dividends = history(conn, f"{sid}_proventos", since=(date.fromisoformat(t0) + timedelta(1)).isoformat(),
                        until=end.reference_date)
    cdi = accumulate_cdi(conn, t0, end.reference_date, today)
    with localcontext(CALC_CONTEXT):
        def shares_at(day: str) -> Decimal:
            s = ONE
            for e in events:
                if e["ex_date"] <= day:
                    s *= to_decimal(e["factor"])
            return s
        cash = sum((shares_at(d.reference_date) * d.value for d in dividends), ZERO)
        held = shares_at(end.reference_date)
        price_ret = held * end.value / p0 - ONE
        total = (held * end.value + cash) / p0 - ONE
        excess_pp = (total - cdi["acumulado"]) * HUNDRED
        adjusted = [shares_at(p.reference_date) * p.value for p in path]
    result = {
        "metodo": "preco_total", "versao_metodo": METHOD_VERSION, "data_inicial": t0, "data_final": end.reference_date,
        "preco_inicial": str(p0), "preco_final": str(end.value), "fator_eventos": str(held),
        "eventos_corporativos": [dict(e) for e in events], "proventos_por_acao": [d.as_dict() for d in dividends],
        "retorno_preco_ajustado_pct": _pct(price_ret), "retorno_total_pct": _pct(total),
        "cdi_bruto_pct": _pct(cdi["acumulado"]), "excesso_vs_cdi_pp": str(excess_pp.quantize(Decimal("0.01"))),
        **path_stats(adjusted),
        "notas": ["Comparação bruta (antes de impostos e custos de negociação, que dependem de você).",
                  "Proventos somados em dinheiro, sem reinvestimento."],
    }
    if _revised(conn, detection):
        return "calculado", "invalidada", {**result, "motivo": "o dado que disparou o sinal foi revisado"}
    return "calculado", _verdict(detection["hipotese"], excess_pp, price_ret >= 0), result


def method_macro(conn, detection: dict, horizon: int, today: date):
    sid, t0 = detection["serie"]["series_id"], detection["sinal"]["reference_date"]
    d1 = _due(t0, horizon)
    slack = 45 if detection["serie"]["frequency"] == "mensal" else HORIZON_SLACK_DAYS
    end = _first_from(history(conn, sid, since=d1), d1, slack=slack)
    if detection["sinal"].get("valor_observado") is None:
        # Sinal de dado desatualizado: o que se acompanha é se a fonte voltou a publicar.
        back = next(iter(history(conn, sid, since=(date.fromisoformat(t0) + timedelta(1)).isoformat(), until=d1)), None)
        return "calculado", "sem_hipotese", {
            "metodo": "serie_macro", "versao_metodo": METHOD_VERSION, "data_inicial": t0, "data_final": d1,
            "voltou_a_publicar": back is not None, "primeiro_dado_depois": back.reference_date if back else None}
    if end is None:
        return _wait_or_fail(d1, today, "série ainda sem dado para o horizonte", slack)
    v0 = to_decimal(detection["sinal"]["valor_observado"])
    result = {"metodo": "serie_macro", "versao_metodo": METHOD_VERSION, "data_inicial": t0,
              "data_final": end.reference_date, "valor_inicial": str(v0), "valor_final": str(end.value),
              "variacao": str(end.value - v0)}
    if _revised(conn, detection):
        return "calculado", "invalidada", {**result, "motivo": "o dado que disparou o sinal foi revisado"}
    return "calculado", "sem_hipotese", result


def method_reserve(conn, detection: dict, horizon: int, today: date):
    t0 = detection["sinal"]["reference_date"]
    d1 = _due(t0, horizon)
    row = conn.execute("SELECT as_of, liquid_reserve, essential_expenses FROM financial_snapshots WHERE user_id = ? AND "
                       "as_of > ? AND as_of <= ? ORDER BY as_of DESC, created_at DESC LIMIT 1",
                       (detection["user_id"], t0, d1)).fetchone()
    if row is None:
        return _wait_or_fail(d1, today, "retrato financeiro não foi atualizado no período")
    essential = to_decimal(row["essential_expenses"])
    months = to_decimal(row["liquid_reserve"]) / essential if essential > 0 else None
    minimum = to_decimal(detection["hipotese"]["criterio"]["valor"])
    result = {"metodo": "reserva", "versao_metodo": METHOD_VERSION, "data_inicial": t0, "retrato_de": row["as_of"],
              "meses_inicial": detection["sinal"]["valores"].get("meses"),
              "meses_final": str(months.quantize(Decimal("0.01"))) if months is not None else None,
              "minimo": str(minimum)}
    if months is None:
        return "dados_insuficientes", "dados_insuficientes", {**result, "motivo": "despesas essenciais zeradas"}
    return "calculado", "confirmada" if months < minimum else "nao_confirmada", result


METHODS = {"td_marcacao": method_td, "preco_total": method_price, "serie_macro": method_macro,
           "reserva": method_reserve}


# ---------- agenda e execução ----------

def schedule(conn, opp_id: str, method: str, horizons: list[int], t0: str, now: str,
             version: str = METHOD_VERSION) -> None:
    for h in horizons:
        conn.execute("INSERT OR IGNORE INTO radar_outcomes (id, opportunity_id, horizon_days, method, method_version, "
                     "due_date, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4()), opp_id, h, method, version, _due(t0, h), "pendente", now))


def compute_one(conn, row, today: date) -> tuple[str, str, dict] | None:
    detection = journal.original(conn, row["opportunity_id"])
    return METHODS[row["method"]](conn, detection, row["horizon_days"], today)


def compute_due(conn, today: date, now: str, *, limit: int = 200) -> dict:
    """Calcula o que venceu. Cada avaliação é um UPDATE condicional ao status 'pendente': reexecutar depois de uma
    queda (ou em paralelo) nunca calcula duas vezes nem sobrescreve um resultado."""
    counts = {"calculado": 0, "dados_insuficientes": 0, "aguardando": 0, "erro": 0}
    rows = conn.execute("SELECT * FROM radar_outcomes WHERE status = 'pendente' AND due_date <= ? ORDER BY due_date "
                        "LIMIT ?", (today.isoformat(), limit)).fetchall()
    for row in rows:
        try:
            status, verdict, result = compute_one(conn, row, today)
        except NotYet as wait:
            conn.execute("UPDATE radar_outcomes SET attempts = attempts + 1, last_error = ? WHERE id = ? AND "
                         "status = 'pendente'", (str(wait), row["id"]))
            counts["aguardando"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 — erro num cálculo não para os outros; fica registrado
            failed = row["attempts"] + 1 >= MAX_ATTEMPTS
            conn.execute("UPDATE radar_outcomes SET attempts = attempts + 1, last_error = ?, status = ?, verdict = ?, "
                         "computed_at = ? WHERE id = ? AND status = 'pendente'",
                         (f"{type(exc).__name__}: {str(exc)[:200]}", "dados_insuficientes" if failed else "pendente",
                          "dados_insuficientes" if failed else None, now if failed else None, row["id"]))
            counts["erro"] += 1
            continue
        cur = conn.execute("UPDATE radar_outcomes SET status = ?, verdict = ?, result_json = ?, computed_at = ?, "
                           "attempts = attempts + 1, last_error = NULL WHERE id = ? AND status = 'pendente'",
                           (status, verdict, json.dumps(result, ensure_ascii=False, sort_keys=True), now, row["id"]))
        if cur.rowcount:
            counts[status] += 1
            journal.event(conn, row["opportunity_id"], "avaliacao_posterior", now, horizonte=row["horizon_days"],
                          veredito=verdict)
    close_finished(conn, now)
    return counts


def close_finished(conn, now: str) -> None:
    rows = conn.execute("SELECT o.id FROM radar_opportunities o WHERE o.state = 'em_acompanhamento' AND NOT EXISTS "
                        "(SELECT 1 FROM radar_outcomes r WHERE r.opportunity_id = o.id AND r.status = 'pendente')")
    for (opp_id,) in rows.fetchall():
        verdicts = [r[0] for r in conn.execute("SELECT verdict FROM radar_outcomes WHERE opportunity_id = ?", (opp_id,))]
        if not verdicts:
            continue
        if "invalidada" in verdicts:
            state = "invalidada"
        elif all(v in ("dados_insuficientes", "inconclusivo") for v in verdicts):
            state = "inconclusiva"
        else:
            state = "encerrada"
        journal.set_state(conn, opp_id, state, now)


def reschedule_method(conn, version: str, now: str) -> int:
    """Metodologia corrigida: agenda nova versão para tudo que já foi calculado; os resultados antigos ficam."""
    rows = conn.execute("SELECT DISTINCT opportunity_id, horizon_days, method, due_date FROM radar_outcomes WHERE "
                        "method_version != ?", (version,)).fetchall()
    for r in rows:
        conn.execute("INSERT OR IGNORE INTO radar_outcomes (id, opportunity_id, horizon_days, method, method_version, "
                     "due_date, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4()), r["opportunity_id"], r["horizon_days"], r["method"], version, r["due_date"],
                      "pendente", now))
    return len(rows)


def list_for(conn, opp_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM radar_outcomes WHERE opportunity_id = ? ORDER BY horizon_days, method_version",
                        (opp_id,)).fetchall()
    return [{**{k: r[k] for k in r.keys() if k != "result_json"}, "result": json.loads(r["result_json"])} for r in rows]
