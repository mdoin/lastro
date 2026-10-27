"""Backtest de regras sobre o histórico coletado, sem informação futura.

- a regra é avaliada dia a dia só com os pontos até aquele dia (mesma função do monitoramento);
- o resultado de cada sinal usa o mesmo método das avaliações reais (custos e impostos estimados incluídos);
- horizontes que passam do fim dos dados são descartados, não "completados";
- títulos que venceram continuam no histórico (sem viés de sobrevivência no Tesouro Direto);
- validação fora da amostra: os primeiros 60% do período versus os últimos 40%, mais segmentos sequenciais
  (walk-forward) para ver se o comportamento é estável ao longo do tempo.
Os resultados ficam em radar_backtests, rotulados como simulados, e nunca entram nas métricas dos alertas reais.
"""

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

from financial_engine.money import to_decimal

from . import engine, observations, outcomes, rules

IN_SAMPLE = Decimal("0.6")
LIMITATIONS = (
    "Resultado simulado: não é desempenho real nem promessa de desempenho futuro.",
    "Revisões anteriores ao início da coleta do Lastro não são conhecidas: o histórico usa o valor vigente.",
    "Adequação ao perfil não é avaliada no backtest.",
    "O período disponível é curto (o coletor guarda cerca de 400 dias): poucos sinais não sustentam conclusões.",
)


def _candidates(conn, rule: dict, today: date) -> list[dict]:
    """Séries pelo padrão; o filtro de vencimento é aplicado em cada data avaliada (e inclui títulos já vencidos)."""
    loose = {**rule, "params": {k: v for k, v in rule["params"].items() if not k.startswith("vencimento_")}}
    return rules.matching_series(loose, observations.list_series(conn), date.min)


def _maturity_ok(rule: dict, meta: dict, day: date) -> bool:
    maturity = meta["meta"].get("vencimento")
    if not maturity:
        return True
    years = (date.fromisoformat(maturity) - day).days / 365.25
    return years > 0 and years >= rule["params"].get("vencimento_min_anos", 0) and \
        years <= rule["params"].get("vencimento_max_anos", 999)


def _block(items: list[dict]) -> dict:
    verdicts = [v for item in items for v in item["vereditos"].values()]
    evaluable = [v for v in verdicts if v in ("confirmada", "nao_confirmada", "favoravel_por_outro_motivo", "inconclusivo")]
    excess = [to_decimal(x) for item in items for x in item["excessos"].values() if x is not None]
    return {"sinais": len(items), "avaliacoes": len(verdicts), "avaliaveis": len(evaluable),
            "confirmadas": evaluable.count("confirmada"),
            "taxa_confirmacao": str((Decimal(evaluable.count("confirmada")) / len(evaluable)).quantize(Decimal("0.001")))
            if evaluable else None,
            "excesso_medio_vs_cdi_pp": str((sum(excess, Decimal(0)) / len(excess)).quantize(Decimal("0.01")))
            if excess else None}


def run_backtest(conn, user_id: str, rule: dict, *, now: str, start: str | None = None, end: str | None = None,
                 segments: int = 3, save: bool = True) -> dict:
    if rule["kind"] not in ("limite", "variacao", "queda"):
        raise ValueError("Backtest disponível para regras de limite, variação e queda.")
    end_day = date.fromisoformat(end) if end else date.fromisoformat(now[:10])
    signals, considered = [], []
    for meta in _candidates(conn, rule, end_day):
        points = observations.history(conn, meta["series_id"], until=end_day.isoformat(), since=start)
        if not points:
            continue
        considered.append(meta["series_id"])
        last_signal = None
        for i in range(len(points)):
            day = date.fromisoformat(points[i].reference_date)
            if not _maturity_ok(rule, meta, day):
                continue
            window = points[: i + 1]  # só o passado: nada depois de `day` entra na avaliação
            trigger = rules.evaluate(rule, window, last_signal_date=last_signal)
            if trigger is None:
                continue
            last_signal = trigger.reference_date
            det = engine.build_detection(conn, user_id=user_id, rule=rule, meta=meta, trigger=trigger, points=window,
                                         profile=None, today=day, now=f"{day.isoformat()}T23:59:59+00:00",
                                         known_at=None)
            verdicts, excess = {}, {}
            for h in rule["horizons"]:
                if day + timedelta(h + outcomes.HORIZON_SLACK_DAYS) > end_day:
                    continue  # horizonte além dos dados: descartado
                try:
                    _status, verdict, result = outcomes.METHODS[det["hipotese"]["metodo"]](
                        conn, det, h, end_day + timedelta(outcomes.GRACE_DAYS + 1))
                except outcomes.NotYet:
                    verdict, result = "dados_insuficientes", {}
                verdicts[str(h)], excess[str(h)] = verdict, result.get("excesso_vs_cdi_pp")
            signals.append({"data": trigger.reference_date, "serie": meta["series_id"], "condicao": trigger.condition,
                            "vereditos": verdicts, "excessos": excess})
    signals.sort(key=lambda s: s["data"])
    first = min((s["data"] for s in signals), default=start or end_day.isoformat())
    span_start = date.fromisoformat(start) if start else date.fromisoformat(first)
    cut = span_start + timedelta(days=int((end_day - span_start).days * IN_SAMPLE))
    seg_len = max((end_day - span_start).days // max(segments, 1), 1)
    segs = []
    for k in range(segments):
        a = span_start + timedelta(days=k * seg_len)
        b = end_day if k == segments - 1 else a + timedelta(days=seg_len)
        segs.append({"de": a.isoformat(), "ate": b.isoformat(),
                     **_block([s for s in signals if a.isoformat() <= s["data"] <= b.isoformat()])})
    result = {"tipo": "simulado", "regra": {k: rule[k] for k in ("id", "version", "name", "kind", "params", "horizons")},
              "periodo": {"de": span_start.isoformat(), "ate": end_day.isoformat()}, "series": considered,
              "dentro_da_amostra": {"ate": cut.isoformat(), **_block([s for s in signals if s["data"] <= cut.isoformat()])},
              "fora_da_amostra": {"de": cut.isoformat(), **_block([s for s in signals if s["data"] > cut.isoformat()])},
              "segmentos": segs, "sinais": signals[-200:], "limitacoes": list(LIMITATIONS)}
    rec_id = str(uuid.uuid4())
    if save:
        conn.execute("INSERT INTO radar_backtests (id, user_id, rule_id, rule_version, params_json, result_json, "
                     "created_at) VALUES (?,?,?,?,?,?,?)",
                     (rec_id, user_id, rule["id"], rule.get("version", 0), json.dumps(rule["params"], sort_keys=True),
                      json.dumps(result, ensure_ascii=False), now))
    return {"id": rec_id, **result}


def list_for(conn, rule_id: str) -> list[dict]:
    rows = conn.execute("SELECT id, rule_version, params_json, result_json, created_at FROM radar_backtests WHERE "
                        "rule_id = ? ORDER BY created_at DESC LIMIT 20", (rule_id,))
    return [{"id": r["id"], "rule_version": r["rule_version"], "params": json.loads(r["params_json"]),
             "result": json.loads(r["result_json"]), "created_at": r["created_at"]} for r in rows]
