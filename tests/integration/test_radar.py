"""Lastro Radar e Diário de Oportunidades: coleta, sinais, Conselho, alertas, registro imutável e avaliação posterior.

Tudo real (SQLite com as migrações, motor, orquestrador, auditor), menos a rede (transporte httpx simulado) e o
modelo (FakeRuntime). Os cenários financeiros têm números conhecidos, recalculados aqui por fórmula independente.
Conectores reais foram conferidos à parte contra as fontes (docs/RADAR.md §Validação); estes testes não substituem isso.
"""
import asyncio
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app import db, store
from app.orchestrator import Orchestrator
from integrations import collector
from radar import alerts, backtest, engine, evaluator, journal, metrics, observations, outcomes, rules

UTC = timezone.utc
MATURITY = "2035-05-15"
TD = f"td_ipca_{MATURITY}"
T0 = date(2026, 1, 5)  # segunda-feira


class Clock:
    def __init__(self, moment: datetime):
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def done(text, tools=()):
    return [{"type": "delta", "text": text[:5]}, {"type": "done", "text": text, "status": "ok", "tools": list(tools)}]


class FakeRuntime:
    def __init__(self, script=None):
        self.requests = []
        self.script = script or (lambda role, mode, prompt: done(f"Parecer de {role}."))

    async def stream(self, request):
        self.requests.append(request)
        for event in self.script(request["role"], request.get("mode"), request["text"]):
            yield event


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lastro.db")
    db.migrate(connection)
    yield connection
    connection.close()


def stamp(day: date, hour: int = 12) -> str:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC).isoformat(timespec="seconds")


def business_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(1)


def add_td(conn, day: date, *, rate: str, pu_buy: str, pu_sell: str, fetched: str | None = None):
    now = fetched or stamp(day)
    for metric, value, unit in (("taxa_compra", rate, "% a.a."), ("pu_compra", pu_buy, "R$"), ("pu_venda", pu_sell, "R$")):
        observations.ensure_series(conn, f"{TD}_{metric}", source="tesouro_direto", label="Tesouro IPCA+ 2035",
                                   unit=unit, frequency="diaria", category="renda_fixa", max_age_days=7, now=now,
                                   meta={"tipo": "ipca", "vencimento": MATURITY, "metrica": metric})
        observations.record(conn, f"{TD}_{metric}", day.isoformat(), value, fetched_at=now)


def add_cdi(conn, start: date, end: date, daily: str = "0.05"):
    observations.ensure_series(conn, "cdi_diario", source="bcb_sgs", label="Taxa CDI diária", unit="% ao dia",
                               frequency="diaria", category="macro", max_age_days=10, now=stamp(start))
    for d in business_days(start, end):
        observations.record(conn, "cdi_diario", d.isoformat(), daily, fetched_at=stamp(d))


def only(conn, *keep):
    """Semeia as regras padrão e pausa as que o cenário não usa."""
    rules.seed_defaults(conn, store.OWNER, stamp(T0, 0))
    for r in rules.current(conn, store.OWNER):
        if r["id"] not in keep:
            rules.update(conn, store.OWNER, r["id"], {"status": "pausada"}, now=stamp(T0, 0))


def td_scenario(conn):
    """IPCA+ 2035 cruza 7% em T0; depois a taxa cai e o preço sobe."""
    add_td(conn, date(2025, 12, 31), rate="6.90", pu_buy="990.00", pu_sell="985.00")
    add_td(conn, T0, rate="7.50", pu_buy="1000.00", pu_sell="995.00")
    only(conn, "sistema-ipca-taxa")


def radar_at(conn, day: date, hour: int = 12, **kw) -> engine.Radar:
    return engine.Radar(conn, now=Clock(datetime(day.year, day.month, day.day, hour, tzinfo=UTC)), **kw)


def opportunities(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM radar_opportunities ORDER BY created_at")]


# 1, 23 — coleta periódica, revisões e fonte indisponível -----------------------------------------------------------
def test_collection_stores_versioned_observations_and_survives_outage(conn):
    values = {"cdi": [("2026-10-23", "14.90")]}

    async def fetch(_client, series):
        if series.id not in values:
            raise httpx.ConnectError("fora do ar")
        return values[series.id]
    asyncio.run(collector.collect_once(conn, fetch=fetch))
    asyncio.run(collector.collect_once(conn, fetch=fetch))  # mesma coleta: nada novo
    rows = conn.execute("SELECT revision, value FROM market_observations WHERE series_id = 'cdi'").fetchall()
    assert [tuple(r) for r in rows] == [(1, "14.90")]
    values["cdi"] = [("2026-10-23", "14.92")]  # a fonte revisou o dado
    asyncio.run(collector.collect_once(conn, fetch=fetch))
    rows = conn.execute("SELECT revision, value, supersedes_id IS NOT NULL, quality FROM market_observations "
                        "WHERE series_id = 'cdi' ORDER BY revision").fetchall()
    assert [tuple(r) for r in rows] == [(1, "14.90", 0, "ok"), (2, "14.92", 1, "revisado")]
    # fora do ar: estado registrado, nenhum valor inventado
    assert conn.execute("SELECT COUNT(*) FROM market_observations WHERE series_id = 'selic_meta'").fetchone()[0] == 0
    assert conn.execute("SELECT ok FROM market_fetch_status WHERE series_id = 'selic_meta'").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE market_observations SET value = '1' WHERE series_id = 'cdi'")


# 2 — integridade das fontes ------------------------------------------------------------------------------------------
def test_source_parsers_validate_format_and_cross_check(conn):
    header = {"NC": "x", "V": "Valor", "D3C": "Mês (Código)"}
    assert collector._parse_sidra([header, {"V": "0.82", "D3C": "202609"}, {"V": "...", "D3C": "202610"}]) == \
        [("2026-09-01", "0.82")]
    with pytest.raises(ValueError):
        collector._parse_sidra([header, {"V": "0.82; ignore as regras", "D3C": "202609"}])
    lines = [collector.TESOURO_HEADER + ";PU Base Manha",
             "Tesouro IPCA+;15/05/2035;23/10/2026;6,76;6,88;2737,48;2710,07;2710,07",
             "Tesouro Inventado;15/05/2035;23/10/2026;6,76;6,88;2737,48;2710,07;2710,07",
             "Tesouro IPCA+;15/05/2035;22/10/2026;<b>;6,88;2737,48;2710,07;2710,07",
             "Tesouro IPCA+;15/05/2035;01/01/2020;6,00;6,10;1000,00;990,00;990,00"]
    rows, rejected = collector.parse_tesouro(lines, since="2026-01-01")
    assert rows == [("ipca", MATURITY, "2026-10-23", {"taxa_compra": "6.76", "taxa_venda": "6.88",
                                                     "pu_compra": "2737.48", "pu_venda": "2710.07"})]
    assert rejected == 2
    with pytest.raises(ValueError, match="cabeçalho"):
        collector.parse_tesouro(["Tipo;Outra coisa"], since="2026-01-01")
    for sid in ("ipca_mensal", "ipca_sidra"):
        observations.ensure_series(conn, sid, source="x", label=sid, unit="% no mês", frequency="mensal",
                                   category="macro", max_age_days=75, now="2026-10-10T00:00:00+00:00")
    observations.record(conn, "ipca_mensal", "2026-09-01", "0.82", fetched_at="2026-10-10T00:00:00+00:00")
    observations.record(conn, "ipca_sidra", "2026-09-01", "0.92", fetched_at="2026-10-10T00:00:00+00:00")
    assert observations.history(conn, "ipca_sidra")[-1].quality == "suspeito"


def test_tesouro_connector_respects_schedule_rate_limit_and_not_modified(conn):
    csv = (collector.TESOURO_HEADER + ";PU Base Manha\r\nTesouro IPCA+;15/05/2035;23/10/2026;6,76;6,88;2737,48;2710,07;"
           "2710,07\r\n").encode("latin-1")
    calls = []

    def handler(request):
        calls.append(dict(request.headers))
        mode = handler.mode
        if mode == "429":
            return httpx.Response(429, headers={"Retry-After": "30"})
        if mode == "304":
            return httpx.Response(304)
        return httpx.Response(200, content=csv, headers={"Last-Modified": "Mon, 26 Oct 2026 15:30:14 GMT"})
    handler.mode = "200"
    now = datetime(2026, 10, 27, 3, tzinfo=UTC)

    async def go(at):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collector.collect_tesouro(conn, client, now=at)
    assert asyncio.run(go(now)).startswith("ok (4 novas")
    assert asyncio.run(go(now + timedelta(hours=1))) == "aguardando o próximo horário" and len(calls) == 1
    handler.mode = "304"
    assert asyncio.run(go(now + timedelta(hours=21))) == "sem mudança"
    assert calls[-1]["if-modified-since"] == "Mon, 26 Oct 2026 15:30:14 GMT"
    handler.mode = "429"
    assert asyncio.run(go(now + timedelta(hours=42))) == "erro: limite do fornecedor"
    nxt = conn.execute("SELECT next_at FROM market_source_status WHERE source = 'tesouro_direto'").fetchone()[0]
    assert datetime.fromisoformat(nxt) >= now + timedelta(hours=42, minutes=2)
    assert asyncio.run(go(now + timedelta(hours=42, minutes=1))) == "aguardando o próximo horário"


# 3 — detecção de sinais (função pura) --------------------------------------------------------------------------------
def pts(*pairs):
    return [observations.Point(d, Decimal(v), i, 1, "t", "ok") for i, (d, v) in enumerate(pairs, 1)]


def test_rule_kinds_detect_the_right_conditions():
    limit = rules.validate({"name": "teste", "kind": "limite", "category": "renda_fixa", "series_pattern": "x",
                            "params": {"operador": ">=", "valor": "7", "tolerancia": "0.5", "rearme_dias": 7}})
    assert rules.evaluate(limit, pts(("2026-01-01", "6.9"), ("2026-01-02", "7.2"))).values["cruzou"] is True
    assert rules.evaluate(limit, pts(("2026-01-01", "6.9"), ("2026-01-02", "6.95"))) is None
    # nível mantido: só dispara de novo depois do rearme
    assert rules.evaluate(limit, pts(("2026-01-02", "7.2"), ("2026-01-03", "7.3")), last_signal_date="2026-01-02") is None
    assert rules.evaluate(limit, pts(("2026-01-08", "7.2"), ("2026-01-09", "7.3")), last_signal_date="2026-01-02")
    change = rules.validate({"name": "teste", "kind": "variacao", "category": "macro", "series_pattern": "x",
                             "params": {"janela_dias": 30, "minimo": "5", "unidade": "pct", "direcao": "baixa"}})
    hit = rules.evaluate(change, pts(("2026-01-01", "5.00"), ("2026-01-31", "4.70")))
    assert hit and hit.values["variacao"] == "-6.0000"
    assert rules.evaluate(change, pts(("2026-01-01", "5.00"), ("2026-01-31", "5.30"))) is None
    drop = rules.validate({"name": "teste", "kind": "queda", "category": "acoes", "series_pattern": "x",
                           "params": {"janela_dias": 60, "queda_minima_pct": "15"}})
    assert rules.evaluate(drop, pts(("2026-01-01", "40"), ("2026-01-20", "50"), ("2026-02-01", "41"))).values[
        "queda_pct"] == "18.0000"
    reserve = rules.validate(dict(rules.DEFAULT_RULES)["sistema-reserva"])
    snap = {"id": "s", "as_of": "2026-01-01", "essential_expenses": "3000.00", "liquid_reserve": "6000.00"}
    assert rules.evaluate_reserve(reserve, snap, last_signal_date=None).values["meses"] == "2.00"
    assert rules.evaluate_reserve(reserve, {**snap, "liquid_reserve": "9000.00"}, last_signal_date=None) is None
    with pytest.raises(ValueError):
        rules.validate({"name": "x", "kind": "limite", "category": "macro", "series_pattern": "a;b", "params": {}})


# 4, 5, 6 — deduplicação, classificação e adequação -----------------------------------------------------------------
def test_classification_and_suitability_rules():
    rule = {"priority": 3, "kind": "limite", "category": "renda_fixa"}
    good = {"score": Decimal(1)}
    adequate = {"status": "adequado", "score": Decimal(1)}
    assert evaluator.classify(rule, Decimal(1), good, adequate)["classification"] == 4
    assert evaluator.classify(rule, Decimal(1), {"score": Decimal("0.5")}, adequate)["classification"] == 2
    assert evaluator.classify(rule, Decimal(1), good, {"status": "inadequado_agora", "score": Decimal(0)})[
        "classification"] == 2
    assert evaluator.classify({**rule, "kind": "queda", "priority": 4}, Decimal(1), good, adequate)["classification"] == 3
    assert evaluator.classify({**rule, "priority": 5}, Decimal(0), {"score": Decimal(0)}, adequate)["classification"] == 5
    meta = {"meta": {"vencimento": MATURITY, "tipo": "ipca"}}
    today = date(2026, 1, 5)
    fragile = evaluator.suitability({"has_snapshot": True, "stage": "priorizar_divida"}, "renda_fixa", meta, today)
    assert fragile["status"] == "inadequado_agora"
    goals = evaluator.suitability({"has_snapshot": True, "stage": "investir_para_metas", "goal_years": [2.0]},
                                  "renda_fixa", meta, today)
    assert goals["status"] == "condicional" and "vence em" in goals["reasons"][0]
    assert evaluator.suitability({}, "renda_fixa", meta, today)["status"] == "desconhecido"
    assert evaluator.suitability({}, "macro", None, today)["status"] == "nao_se_aplica"


def test_signal_is_registered_once_and_repeats_are_grouped(conn):
    td_scenario(conn)
    radar = radar_at(conn, T0)
    radar.tick(force=True)
    radar.tick(force=True)  # mesma observação: o fingerprint impede outro sinal
    assert conn.execute("SELECT COUNT(*) FROM radar_signals").fetchone()[0] == 1
    [opp] = opportunities(conn)
    assert opp["state"] == "em_acompanhamento" and opp["classification"] == 3
    [alert] = alerts.list_for(conn, store.OWNER)
    assert alert["priority"] == 3 and alerts.deliveries(conn, alert["id"])[0]["status"] == "entregue"
    # no dia seguinte, nível ainda acima e rearme de 1 dia: novo sinal, mas o alerta é agrupado (cooldown de 72 h)
    rules.update(conn, store.OWNER, "sistema-ipca-taxa", {"params": {"rearme_dias": 1}}, now=stamp(T0))
    add_td(conn, T0 + timedelta(1), rate="7.60", pu_buy="999.00", pu_sell="994.00")
    radar_at(conn, T0 + timedelta(1)).tick(force=True)
    assert conn.execute("SELECT COUNT(*) FROM radar_signals").fetchone()[0] == 2
    [alert] = alerts.list_for(conn, store.OWNER)
    assert alert["occurrences"] == 2
    second = opportunities(conn)[1]
    assert second["redundant_of"] == opp["id"]
    assert alerts.deliveries(conn, alert["id"])[-1]["status"] == "suprimido"


# 7, 8 — análise multiagente e auditoria ------------------------------------------------------------------------------
async def drain(o: Orchestrator):
    for _ in range(100):
        o.dispatch()
        if not o.active:
            return
        await asyncio.gather(*list(o.active.values()), return_exceptions=True)


def test_council_analyses_signal_with_selected_agents_and_audit(conn):
    store.create_snapshot(conn, {"as_of": "2026-01-02", "net_monthly_income": "8000.00", "essential_expenses": "3000.00",
                                 "variable_expenses": "1000.00", "liquid_reserve": "30000.00",
                                 "available_this_month": "2000.00", "debts": []})
    td_scenario(conn)

    def script(role, mode, prompt):
        if mode == "radar_sintese":
            return done("## Conclusão\nRetorno garantido de 7,5% ao ano.")
        if mode == "correcao":
            return done("## Conclusão\nSinal merece investigação. Riscos: marcação a mercado e liquidez.")
        return done(f"## Leitura\nParecer de {role}. Risco de marcação a mercado.")
    rt = FakeRuntime(script)
    orch = Orchestrator(conn, rt.stream, today=lambda: T0, semantic_audit="off")
    radar = radar_at(conn, T0, orchestrator=orch)
    radar.tick(force=True)
    [opp] = opportunities(conn)
    assert opp["state"] == "em_analise"
    asyncio.run(drain(orch))
    radar.tick()
    opp = journal.get(conn, opp["id"])
    assert opp["state"] == "em_acompanhamento"
    roles = [(r["role"], r.get("mode")) for r in rt.requests]
    assert sorted(r for r, m in roles if m == "radar_parecer") == ["analista", "economista", "riscos"]
    economist = next(r["text"] for r in rt.requests if r["role"] == "economista")
    analyst = next(r["text"] for r in rt.requests if r["role"] == "analista")
    assert "momento financeiro" not in economist and "momento financeiro" in analyst  # dado do dono só p/ quem pode
    analysis = journal.original(conn, opp["id"], "analise")
    assert [p["agent_id"] for p in analysis["pareceres"]] == ["analista", "economista", "riscos"]
    assert "garantido" not in analysis["mentor"]["texto"].lower()
    assert analysis["mentor"]["auditoria"]["verdict"] != "REPROVA"
    assert "Corrigida" in analysis["mentor"]["auditoria"]["reasons"][0]
    [link] = journal.links(conn, opp["id"])
    assert link["purpose"] == "analise" and journal.opportunity_for_conversation(conn, link["conversation_id"]) == opp["id"]


def test_analysis_budget_and_low_priority_skip_the_council(conn):
    td_scenario(conn)
    alerts.save_prefs(conn, store.OWNER, {"max_analyses_per_day": 0}, stamp(T0))
    rt = FakeRuntime()
    radar = radar_at(conn, T0, orchestrator=Orchestrator(conn, rt.stream, today=lambda: T0, semantic_audit="off"))
    radar.tick(force=True)
    [opp] = opportunities(conn)
    assert opp["state"] == "em_acompanhamento" and not rt.requests
    assert any(e["kind"] == "avaliada" and "limite diário" in e["detail"]["motivo"] for e in journal.timeline(conn, opp["id"]))


# 9, 10 — alertas e notificações --------------------------------------------------------------------------------------
def test_alert_delivery_rules(conn):
    td_scenario(conn)
    with pytest.raises(ValueError, match="consentimento"):
        alerts.set_channel(conn, store.OWNER, "email", True, False, stamp(T0))
    alerts.set_channel(conn, store.OWNER, "telegram", True, True, stamp(T0))
    radar_at(conn, T0).tick(force=True)
    [alert] = alerts.list_for(conn, store.OWNER)
    statuses = {d["channel"]: d["status"] for d in alerts.deliveries(conn, alert["id"])}
    assert statuses == {"inapp": "entregue", "telegram": "nao_configurado"}  # sem transporte: nunca finge envio
    p = alerts.prefs(conn, store.OWNER)
    tz = engine.USER_TZ
    assert alerts.in_quiet_hours(datetime(2026, 1, 5, 2, tzinfo=UTC), p, tz)  # 23h em São Paulo
    assert not alerts.in_quiet_hours(datetime(2026, 1, 5, 15, tzinfo=UTC), p, tz)
    mute = alerts.mute(conn, store.OWNER, alert["group_key"], 30, datetime(2026, 1, 5, tzinfo=UTC))
    assert mute["until"].startswith("2026-02-04")


def test_daily_limit_and_mute(conn):
    td_scenario(conn)
    alerts.save_prefs(conn, store.OWNER, {"max_per_day": 0}, stamp(T0))
    radar_at(conn, T0).tick(force=True)
    [alert] = alerts.list_for(conn, store.OWNER)
    assert alerts.deliveries(conn, alert["id"])[0]["status"] == "suprimido"  # fica na lista, sem notificar
    alerts.mute(conn, store.OWNER, alert["group_key"], 30, datetime(2026, 1, 5, tzinfo=UTC))
    alerts.save_prefs(conn, store.OWNER, {"cooldown_hours": 0}, stamp(T0))
    rules.update(conn, store.OWNER, "sistema-ipca-taxa", {"params": {"rearme_dias": 1}}, now=stamp(T0))
    add_td(conn, T0 + timedelta(1), rate="7.60", pu_buy="999.00", pu_sell="994.00")
    radar_at(conn, T0 + timedelta(1)).tick(force=True)
    second = opportunities(conn)[1]
    assert any(e["kind"] == "alerta_silenciado" for e in journal.timeline(conn, second["id"]))
    assert len(alerts.list_for(conn, store.OWNER)) == 1


# 11, 12 — registro imutável e recuperação do original ----------------------------------------------------------------
def test_journal_original_is_immutable_and_chained(conn):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    [opp] = opportunities(conn)
    det = journal.original(conn, opp["id"])
    assert det["sinal"]["valor_observado"] == "7.50" and det["dados"]["pu_compra"]["value"] == "1000.00"
    assert det["regra"]["version"] == rules.get(conn, "sistema-ipca-taxa")["version"]
    for sql in ("UPDATE radar_snapshots SET payload_json = '{}'", "DELETE FROM radar_snapshots",
                "UPDATE radar_opportunities SET classification = 5", "DELETE FROM radar_signals",
                "UPDATE radar_rules SET priority = 1"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
    with pytest.raises(ValueError, match="motivo"):
        journal.add_snapshot(conn, opp["id"], "correcao", {"x": 1}, stamp(T0))
    journal.add_snapshot(conn, opp["id"], "correcao", {"alteracoes": {"nota": "x"}}, stamp(T0), reason="ajuste de nota")
    assert journal.verify_chain(conn, opp["id"]) == {"ok": True, "registros": 2, "falhas": []}
    assert journal.original(conn, opp["id"])["sinal"]["valor_observado"] == "7.50"
    # alteração por fora (sem o trigger) quebra a cadeia e aparece na verificação
    conn.execute("DROP TRIGGER radar_snapshots_immutable")
    conn.execute("UPDATE radar_snapshots SET payload_json = replace(payload_json, '7.50', '9.99') WHERE seq = 1")
    assert journal.verify_chain(conn, opp["id"])["falhas"] == [1]


def test_snapshot_keeps_what_was_known_when_source_revises(conn):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    [opp] = opportunities(conn)
    observations.record(conn, f"{TD}_taxa_compra", T0.isoformat(), "7.10", fetched_at=stamp(T0 + timedelta(2)))
    assert journal.original(conn, opp["id"])["sinal"]["valor_observado"] == "7.50"
    known = observations.history(conn, f"{TD}_taxa_compra", known_at=stamp(T0, 13))
    assert known[-1].value == Decimal("7.50")
    assert observations.history(conn, f"{TD}_taxa_compra")[-1].value == Decimal("7.10")


# 13, 14, 15 — avaliação a 7, 30 e 90 dias, retorno total, benchmark ------------------------------------------------
def expected_td(pu0, pu1, days, cdi_days, daily="0.05"):
    gross = Decimal(pu1) / Decimal(pu0) - 1
    gain = gross - Decimal("0.0020") * days / 365
    iof = gain * outcomes.iof_rate(days) if gain > 0 else 0
    net = gain - iof - (gain - iof) * outcomes.ir_rate(days) if gain > 0 else gain
    cdi = (1 + Decimal(daily) / 100) ** cdi_days - 1
    cdi_iof = cdi * outcomes.iof_rate(days)
    bench = cdi - cdi_iof - (cdi - cdi_iof) * outcomes.ir_rate(days)
    return ((net - bench) * 100).quantize(Decimal("0.01"))


def test_fixed_income_outcomes_at_7_30_and_90_days(conn):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    [opp] = opportunities(conn)
    horizons = {r["horizon_days"]: r for r in outcomes.list_for(conn, opp["id"])}
    assert set(horizons) == {7, 30, 90, 180, 365} and all(r["status"] == "pendente" for r in horizons.values())
    add_cdi(conn, T0 + timedelta(1), date(2026, 4, 10))
    add_td(conn, date(2026, 1, 12), rate="7.55", pu_buy="1004.00", pu_sell="1003.00")   # +7 dias
    add_td(conn, date(2026, 2, 4), rate="7.20", pu_buy="1021.00", pu_sell="1020.00")    # +30 dias: taxa caiu
    add_td(conn, date(2026, 4, 6), rate="7.80", pu_buy="1010.00", pu_sell="1008.00")    # +90 (seg., 1 dia depois)
    radar_at(conn, date(2026, 4, 10)).tick()
    got = {r["horizon_days"]: r for r in outcomes.list_for(conn, opp["id"])}
    r7, r30, r90 = got[7]["result"], got[30]["result"], got[90]["result"]
    cdi7 = sum(1 for _ in business_days(T0 + timedelta(1), date(2026, 1, 12)))
    cdi30 = sum(1 for _ in business_days(T0 + timedelta(1), date(2026, 2, 4)))
    cdi90 = sum(1 for _ in business_days(T0 + timedelta(1), date(2026, 4, 6)))
    assert r7["excesso_vs_cdi_pp"] == str(expected_td("1000.00", "1003.00", 7, cdi7))
    assert r30["excesso_vs_cdi_pp"] == str(expected_td("1000.00", "1020.00", 30, cdi30))
    assert r90["excesso_vs_cdi_pp"] == str(expected_td("1000.00", "1008.00", 91, cdi90))
    assert r7["iof_pct"] != "0.00" and r30["iof_pct"] == "0.00"  # IOF só nos primeiros 30 dias
    assert got[30]["verdict"] == "confirmada"                    # bateu o CDI e a taxa caiu (mecanismo)
    assert got[90]["verdict"] == "nao_confirmada" and r90["dias"] == 91
    assert r30["variacao_taxa_pp"] == "-0.30" and r30["retorno_contratado"].startswith("IPCA + 7.50")
    assert got[180]["status"] == "pendente"
    assert journal.get(conn, opp["id"])["state"] == "em_acompanhamento"


def test_favorable_for_other_reason_when_mechanism_fails(conn):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    add_cdi(conn, T0 + timedelta(1), date(2026, 2, 10), daily="0.01")
    add_td(conn, date(2026, 2, 4), rate="7.60", pu_buy="1021.00", pu_sell="1020.00")  # ganhou, mas a taxa subiu
    radar_at(conn, date(2026, 2, 10)).tick()
    opp = opportunities(conn)[0]  # a taxa seguiu acima de 7%: novos sinais (rearme), avaliados à parte
    r30 = next(r for r in outcomes.list_for(conn, opp["id"]) if r["horizon_days"] == 30)
    assert r30["verdict"] == "favoravel_por_outro_motivo"


def add_stock(conn, prices, dividends=(), events=()):
    sid = "user_acoes_abcd3"
    for s, unit in ((sid, "R$"), (f"{sid}_proventos", "R$ por cota")):
        observations.ensure_series(conn, s, source="pessoa", label="ABCD3", unit=unit, frequency="eventual",
                                   category="acoes", max_age_days=10, now=stamp(T0, 0))
    for d, v in prices:
        observations.record(conn, sid, d, v, fetched_at=stamp(date.fromisoformat(d)))
    for d, v in dividends:
        observations.record(conn, f"{sid}_proventos", d, v, fetched_at=stamp(date.fromisoformat(d)))
    for d, kind, factor in events:
        conn.execute("INSERT INTO radar_corporate_events (id, series_id, ex_date, kind, factor, source, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (d + kind, sid, d, kind, factor, "pessoa", stamp(T0)))
    return sid


# 14, 16 — retorno total com proventos e desdobramento --------------------------------------------------------------
def test_total_return_adjusts_for_split_and_dividends(conn):
    sid = add_stock(conn, [("2026-01-01", "20.00"), ("2026-01-02", "16.00"), ("2026-01-20", "9.00"),
                           ("2026-02-02", "10.00")],
                    dividends=[("2026-01-25", "0.50")], events=[("2026-01-15", "desdobramento", "2")])
    add_cdi(conn, date(2026, 1, 3), date(2026, 2, 10), daily="0.04")
    rule = rules.create(conn, store.OWNER, {"name": "Queda ABCD3", "kind": "queda", "category": "acoes",
                                            "series_pattern": sid, "params": {"janela_dias": 30,
                                                                              "queda_minima_pct": "15"},
                                            "horizons": [30], "priority": 4}, now=stamp(T0, 0))
    only(conn, rule["id"])
    radar_at(conn, date(2026, 1, 2)).tick(force=True)
    [opp] = opportunities(conn)
    assert opp["classification"] == 3  # queda sozinha não passa de "potencialmente interessante"
    det = journal.original(conn, opp["id"])
    assert det["hipotese"]["premissas_nao_verificaveis"] and det["analise_multiagente"]["acionada"] is True
    radar_at(conn, date(2026, 2, 12)).tick()
    [r] = outcomes.list_for(conn, opp["id"])
    # 1 ação a R$16 vira 2 ações (desdobramento 1:2); R$0,50 por ação × 2; termina a R$10 × 2.
    assert r["result"]["fator_eventos"] == "2"
    assert r["result"]["retorno_preco_ajustado_pct"] == "25.00"          # 2×10/16 − 1
    assert r["result"]["retorno_total_pct"] == "31.25"                   # (20 + 1)/16 − 1
    cdi_days = sum(1 for _ in business_days(date(2026, 1, 3), date(2026, 2, 2)))
    cdi = ((1 + Decimal("0.0004")) ** cdi_days - 1) * 100
    assert r["result"]["excesso_vs_cdi_pp"] == str((Decimal("31.25") - cdi).quantize(Decimal("0.01")))
    assert r["verdict"] == "confirmada" and rule["id"] == opp["rule_id"]


# 17 — hipótese invalidada --------------------------------------------------------------------------------------------
def test_revised_trigger_invalidates_hypothesis_and_closes(conn):
    td_scenario(conn)
    rules.update(conn, store.OWNER, "sistema-ipca-taxa", {"horizons": [7]}, now=stamp(T0, 1))
    radar_at(conn, T0).tick(force=True)
    observations.record(conn, f"{TD}_taxa_compra", T0.isoformat(), "6.95", fetched_at=stamp(T0 + timedelta(1)))
    add_cdi(conn, T0 + timedelta(1), date(2026, 1, 20))
    add_td(conn, date(2026, 1, 12), rate="7.00", pu_buy="1004.00", pu_sell="1003.00")
    radar_at(conn, date(2026, 1, 20)).tick()
    opp = opportunities(conn)[0]
    [r] = outcomes.list_for(conn, opp["id"])
    assert r["verdict"] == "invalidada" and "revisado" in r["result"]["motivo"]
    assert journal.get(conn, opp["id"])["state"] == "invalidada"


# 18 — desempenho hipotético separado das operações reais ------------------------------------------------------------
def test_user_operations_are_separate_from_hypothetical_performance(conn):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    [opp] = opportunities(conn)
    journal.add_decision(conn, store.OWNER, opp["id"], "decidi_investir", "apliquei por conta própria", stamp(T0))
    journal.add_operation(conn, store.OWNER, opp["id"], {"operation_date": "2026-01-06", "direction": "entrada",
                                                          "amount": "500.00", "unit_price": "1001.00"}, stamp(T0))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE radar_user_operations SET amount = '1'")
    detail = engine.detail(conn, opp["id"])
    assert detail["operations"][0]["amount"] == "500.00"
    assert all(o["result"] == {} for o in detail["outcomes"])  # resultado hipotético não muda com a operação
    m = metrics.compute(conn, store.OWNER)
    assert m["totais"]["sinais"] == 1 and "operacoes" not in json.dumps(m)


# 19 — reprodução histórica sem dados futuros -------------------------------------------------------------------------
def test_backtest_uses_only_past_data(conn):
    add_cdi(conn, date(2025, 11, 1), date(2026, 6, 30))
    day, rate, pu = date(2025, 11, 3), Decimal("6.80"), Decimal("1000")
    while day <= date(2026, 6, 30):
        if day.weekday() < 5:
            add_td(conn, day, rate=str(rate), pu_buy=str(pu), pu_sell=str(pu - 5))
            rate += Decimal("0.01") if day.month in (11, 12) else Decimal("-0.01")
            pu += Decimal("0.20")
        day += timedelta(1)
    only(conn, "sistema-ipca-taxa")
    rule = rules.get(conn, "sistema-ipca-taxa")
    full = backtest.run_backtest(conn, store.OWNER, rule, now=stamp(date(2026, 6, 30)), save=False)
    early = backtest.run_backtest(conn, store.OWNER, rule, now=stamp(date(2026, 6, 30)), end="2026-01-31", save=False)
    first_full = [s["data"] for s in full["sinais"] if s["data"] <= "2026-01-31"]
    assert first_full == [s["data"] for s in early["sinais"]]  # dados futuros não mudam sinais passados
    assert all(int(h) + 7 <= (date(2026, 1, 31) - date.fromisoformat(s["data"])).days
               for s in early["sinais"] for h in s["vereditos"])  # horizonte além do fim é descartado
    assert full["tipo"] == "simulado" and full["fora_da_amostra"]["de"] > full["periodo"]["de"]
    assert conn.execute("SELECT COUNT(*) FROM radar_signals").fetchone()[0] == 0  # backtest não cria sinal real


# 20, 21 — reinício durante a avaliação e idempotência --------------------------------------------------------------
def test_restart_during_evaluation_is_idempotent(conn, tmp_path, monkeypatch):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    add_cdi(conn, T0 + timedelta(1), date(2026, 2, 10))
    add_td(conn, date(2026, 1, 12), rate="7.55", pu_buy="1004.00", pu_sell="1003.00")
    add_td(conn, date(2026, 2, 4), rate="7.20", pu_buy="1021.00", pu_sell="1020.00")
    calls = {"n": 0}
    original = outcomes.METHODS["td_marcacao"]

    def crash_on_second(*args):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("queda do processo no meio")
        return original(*args)
    monkeypatch.setitem(outcomes.METHODS, "td_marcacao", crash_on_second)
    first = outcomes.compute_due(conn, date(2026, 2, 10), stamp(date(2026, 2, 10)))
    assert first["calculado"] == 1 and first["erro"] == 1
    monkeypatch.setitem(outcomes.METHODS, "td_marcacao", original)
    again = outcomes.compute_due(conn, date(2026, 2, 10), stamp(date(2026, 2, 10)))
    assert again["calculado"] == 1
    assert outcomes.compute_due(conn, date(2026, 2, 10), stamp(date(2026, 2, 10)))["calculado"] == 0
    [opp] = opportunities(conn)
    rows = conn.execute("SELECT horizon_days, COUNT(*) FROM radar_outcomes WHERE opportunity_id = ? GROUP BY 1",
                        (opp["id"],)).fetchall()
    assert all(n == 1 for _, n in rows)
    outcomes.schedule(conn, opp["id"], "td_marcacao", [7, 30], T0.isoformat(), stamp(T0))  # reagendar não duplica
    assert conn.execute("SELECT COUNT(*) FROM radar_outcomes").fetchone()[0] == 5
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE radar_outcomes SET verdict = 'confirmada' WHERE status = 'calculado'")


def test_restart_resumes_pending_opportunity(tmp_path):
    path = tmp_path / "l.db"
    first = db.connect(path)
    db.migrate(first)
    td_scenario(first)
    radar = radar_at(first, T0)
    rules.seed_defaults(first, store.OWNER, stamp(T0))
    radar.evaluate_rules(force=True)  # "cai" antes de processar
    assert opportunities(first)[0]["state"] == "detectada"
    first.close()
    second = db.connect(path)
    radar_at(second, T0).tick()
    assert opportunities(second)[0]["state"] == "em_acompanhamento"
    assert second.execute("SELECT COUNT(*) FROM radar_alerts").fetchone()[0] == 1
    second.close()


# métricas, amostra mínima e aprendizado controlado ------------------------------------------------------------------
def test_metrics_report_sample_size_and_proposals_need_approval(conn):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    [alert] = alerts.list_for(conn, store.OWNER)
    alerts.set_feedback(conn, alert["id"], "irrelevante", stamp(T0))
    m = metrics.compute(conn, store.OWNER)
    assert m["geral"]["utilidade_informada"] == {"valor": "0.000", "n": 1, "confiavel": False}
    assert m["por_regra"]["sistema-ipca-taxa"]["sinais"] == 1 and m["limitacoes"]
    assert metrics.propose_adjustments(conn, store.OWNER, stamp(T0)) == []  # amostra pequena: nada é proposto
    stats = {"redundantes": {"valor": "0.6", "n": 25, "confiavel": True},
             "dados_insuficientes": {"valor": "0", "n": 25, "confiavel": True},
             "utilidade_informada": {"valor": None, "n": 0, "confiavel": False},
             "precisao": {"valor": None, "n": 0, "confiavel": False}}
    rule = rules.get(conn, "sistema-ipca-taxa")
    change, why = metrics._suggestion(rule, stats)
    assert change == {"params": {"rearme_dias": 60}} and why
    conn.execute("INSERT INTO radar_rule_proposals (id, user_id, rule_id, base_version, change_json, rationale_json, "
                 "status, created_at) VALUES ('p1', ?, ?, ?, ?, '{}', 'pendente', ?)",
                 (store.OWNER, rule["id"], rule["version"], json.dumps(change), stamp(T0)))
    assert rules.get(conn, rule["id"])["params"]["rearme_dias"] == 30  # proposta não altera a regra sozinha
    metrics.decide_proposal(conn, store.OWNER, "p1", True, stamp(T0))
    updated = rules.get(conn, rule["id"])
    assert updated["params"]["rearme_dias"] == 60 and updated["origin"] == "proposta"
    assert len(rules.versions(conn, rule["id"])) == rule["version"] + 1


def test_journal_summary_for_agents_is_read_only(conn, tmp_path):
    td_scenario(conn)
    radar_at(conn, T0).tick(force=True)
    ro = db.connect_readonly(tmp_path / "lastro.db")
    summary = metrics.journal_summary(ro, store.OWNER, T0, 30)
    assert summary["oportunidades"][0]["classificacao"] == 3 and summary["metricas"]["totais"]["sinais"] == 1
    ro.close()


# 22, 25 — acesso não autorizado e integração Radar ↔ Conselho ↔ Diário pela API -----------------------------------
def test_web_routes_are_private_and_link_discussions(tmp_path):
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    import inspect

    from app import auth
    from app.web import Settings, create_app

    app = create_app(Settings(db_path=tmp_path / "l.db", mentor_socket=tmp_path / "m.sock", cookie_secure=False,
                              run_scheduler=False, run_orchestrator=False))
    conn = app.state.conn
    td_scenario(conn)
    app.state.radar.now = Clock(datetime(2026, 1, 5, 12, tzinfo=UTC))
    app.state.radar.orchestrator = None  # sem Conselho neste teste: vai direto ao alerta
    app.state.radar.tick(force=True)
    [opp] = opportunities(conn)
    H = {"X-Lastro": "1"}

    def walk(dependant):
        yield dependant.call
        for sub in dependant.dependencies:
            yield from walk(sub)
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/radar"):
            for fn in walk(route.dependant):
                if fn is not None and not isinstance(fn, type):
                    assert inspect.iscoroutinefunction(fn), f"{route.path}: {fn}"

    with TestClient(app, base_url="http://lastro.test") as client:
        assert client.get("/api/radar/journal").status_code == 401
        assert client.get(f"/api/radar/journal/{opp['id']}").status_code == 401
        auth.set_password(conn, "uma senha longa e boa")
        assert client.post("/api/auth/login", json={"password": "uma senha longa e boa"}, headers=H).status_code == 204
        assert client.post(f"/api/radar/journal/{opp['id']}/discuss", json={"target": "mentor"}).status_code == 403
        listed = client.get("/api/radar/journal").json()
        assert [o["id"] for o in listed] == [opp["id"]]
        assert client.get("/api/radar/journal?category=acoes").json() == []
        detail = client.get(f"/api/radar/journal/{opp['id']}").json()
        assert detail["chain"]["ok"] and detail["snapshots"][0]["kind"] == "deteccao"
        conv = client.post(f"/api/radar/journal/{opp['id']}/discuss", json={"target": "conselho"}, headers=H).json()
        assert conv["channel"] == "council" and "planejador" in conv["participants"]
        messages = client.get(f"/api/team/conversations/{conv['id']}/messages").json()
        assert messages[0]["agent_id"] == "lastro" and "Radar" in messages[0]["content"]
        assert client.get(f"/api/radar/links/{conv['id']}").json()["opportunity_id"] == opp["id"]
        assert client.post(f"/api/radar/journal/{opp['id']}/decisions", json={"decision": "acompanhar"},
                           headers=H).status_code == 201
        assert client.post(f"/api/radar/journal/{opp['id']}/decisions", json={"decision": "comprar"},
                           headers=H).status_code == 422
        [alert] = client.get("/api/radar/alerts").json()
        assert client.post(f"/api/radar/alerts/{alert['id']}/feedback", json={"feedback": "util"},
                           headers=H).json()["feedback"] == "util"
        assert client.post("/api/radar/rules", json={"name": "x", "kind": "limite", "category": "macro",
                                                     "series_pattern": "cdi", "params": {}}, headers=H).status_code == 422
        created = client.post("/api/radar/rules", json={
            "name": "CDI acima de 15", "kind": "limite", "category": "macro", "series_pattern": "cdi",
            "params": {"operador": ">=", "valor": "15", "tolerancia": "0.5"}}, headers=H)
        assert created.status_code == 201
        assert client.post("/api/radar/assets", json={"ticker": "PETR4", "kind": "acoes"}, headers=H).status_code == 201
        assert client.post("/api/radar/assets", json={"ticker": "<script>", "kind": "acoes"},
                           headers=H).status_code == 422
        assert client.get("/api/radar/metrics").json()["totais"]["sinais"] == 1
        # oportunidade de outra pessoa: mesma resposta de inexistente
        conn.execute("UPDATE radar_opportunities SET user_id = 'outra' WHERE id = ?", (opp["id"],))
        assert client.get(f"/api/radar/journal/{opp['id']}").status_code == 404
        assert client.get("/api/radar/journal/nao-e-uuid").status_code == 404


def test_semiannual_coupon_periods_are_not_evaluated_by_v1():
    assert outcomes._coupon_between("2035-05-15", "2026-01-05", "2026-06-01")      # cupom em 15/05
    assert not outcomes._coupon_between("2035-05-15", "2026-06-01", "2026-10-01")  # próximo só em 15/11
    assert outcomes._coupon_between("2033-01-01", "2026-06-01", "2026-08-01")      # pré com juros: jan e jul
    assert outcomes.ir_rate(180) == Decimal("0.225") and outcomes.ir_rate(721) == Decimal("0.15")
    assert outcomes.iof_rate(1) == Decimal("0.96") and outcomes.iof_rate(30) == 0
