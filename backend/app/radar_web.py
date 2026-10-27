"""Rotas do Radar e do Diário de Oportunidades (docs/WEB_API.md §Radar).

Tudo filtra pelo dono (`user_id`): oportunidade, alerta ou regra de outra pessoa responde 404, igual a inexistente.
Nenhuma rota executa operação financeira; "operação informada" só registra o que a pessoa diz ter feito.
"""

import datetime as dt
import re
import uuid
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from radar import alerts, backtest, engine, journal, metrics, observations, rules
from team.agents import AGENTS

from . import db, store

TICKER = re.compile(r"^[A-Z]{4}[0-9]{1,2}[A-Z]?$")


class RuleIn(BaseModel):
    name: str = Field(max_length=120)
    kind: str = Field(max_length=30)
    category: str = Field(max_length=30)
    series_pattern: str = Field("", max_length=800)
    params: dict = Field(default_factory=dict)
    priority: int = 3
    interval_minutes: int = 360
    horizons: list[int] = Field(default_factory=lambda: list(rules.DEFAULT_HORIZONS), max_length=8)
    status: str = "ativa"
    note: str = Field("", max_length=500)


class StatusIn(BaseModel):
    status: str = Field(max_length=20)


class FeedbackIn(BaseModel):
    feedback: Literal["util", "irrelevante"]


class MuteIn(BaseModel):
    days: int = Field(30, ge=1, le=365)


class DecisionIn(BaseModel):
    decision: str = Field(max_length=30)
    note: str = Field("", max_length=1000)


class OperationIn(BaseModel):
    operation_date: dt.date
    direction: Literal["entrada", "saida"]
    amount: str = Field(max_length=30)
    unit_price: str | None = Field(None, max_length=30)
    note: str = Field("", max_length=500)


class CorrectionIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    changes: dict = Field(default_factory=dict)


class DiscussIn(BaseModel):
    target: Literal["mentor", "conselho"]


class AssetIn(BaseModel):
    ticker: str = Field(max_length=8)
    kind: Literal["acoes", "etf", "fii"]


class ObservationIn(BaseModel):
    reference_date: dt.date
    value: str = Field(max_length=30)
    kind: Literal["preco", "provento"] = "preco"


class CorporateEventIn(BaseModel):
    ex_date: dt.date
    kind: Literal["desdobramento", "grupamento", "bonificacao"]
    factor: str = Field(max_length=20)


class PrefsIn(BaseModel):
    min_priority: int | None = None
    quiet_start: str | None = Field(None, max_length=5)
    quiet_end: str | None = Field(None, max_length=5)
    max_per_day: int | None = None
    cooldown_hours: int | None = None
    max_analyses_per_day: int | None = None


class ChannelIn(BaseModel):
    enabled: bool
    consent: bool = False


class BacktestIn(BaseModel):
    start: dt.date | None = None
    end: dt.date | None = None


def register(app: FastAPI, conn, *, current_user, radar: engine.Radar, bad_request, log_access, today) -> None:
    def now() -> str:
        return db.utcnow()

    def own_opp(opp_id: str, user: str) -> dict:
        try:
            uuid.UUID(opp_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Oportunidade inexistente.") from None
        opp = journal.get(conn, opp_id)
        if not opp or opp["user_id"] != user:
            raise HTTPException(status_code=404, detail="Oportunidade inexistente.")
        return opp

    def own_alert(alert_id: str, user: str) -> dict:
        alert = alerts.get(conn, alert_id)
        if not alert or alert["user_id"] != user:
            raise HTTPException(status_code=404, detail="Alerta inexistente.")
        return alert

    def own_rule(rule_id: str, user: str) -> dict:
        rule = rules.get(conn, rule_id)
        if not rule or rule["user_id"] != user:
            raise HTTPException(status_code=404, detail="Regra inexistente.")
        return rule

    # --- monitoramento ---
    @app.get("/api/radar/overview")
    async def radar_overview(user: str = Depends(current_user)):
        rules.seed_defaults(conn, user, now())
        series = observations.list_series(conn)
        by_source: dict = {}
        for s in series:
            by_source.setdefault(s["source"], 0)
            by_source[s["source"]] += 1
        sources = [dict(r) for r in conn.execute("SELECT source, checked_at, ok, error, next_at FROM market_source_status")]
        fetch = [dict(r) for r in conn.execute("SELECT source, series_id, checked_at, ok, error FROM market_fetch_status "
                                               "ORDER BY source, series_id")]
        from integrations.catalog import NOT_CONNECTED, SOURCE_NAMES
        return {"series_by_source": by_source, "source_names": SOURCE_NAMES, "sources": sources, "series_status": fetch,
                "not_connected": list(NOT_CONNECTED), "rules": len(rules.current(conn, user)),
                "unread_alerts": alerts.unread_count(conn, user), "last_tick": radar.last_tick,
                "prefs": alerts.prefs(conn, user), "channels": alerts.channels(conn, user),
                "realtime": False}

    @app.post("/api/radar/tick")
    async def radar_tick(user: str = Depends(current_user)):
        log_access(user, "radar.tick", "-")
        return radar.tick(force=True)

    @app.get("/api/radar/series")
    async def radar_series(category: str | None = Query(None, max_length=20), user: str = Depends(current_user)):
        out = []
        for s in observations.list_series(conn, category=category):
            if s["series_id"].endswith("_proventos"):
                continue
            if s["source"] == "tesouro_direto" and s["meta"].get("metrica") != "taxa_compra":
                continue
            pts = observations.history(conn, s["series_id"], until=today().isoformat(),
                                       since=(today() - dt.timedelta(days=45)).isoformat())
            last = pts[-1] if pts else None
            if s["source"] == "tesouro_direto" and (not last or s["meta"]["vencimento"] <= today().isoformat()):
                continue  # títulos vencidos ou sem preço recente
            out.append({"series_id": s["series_id"], "label": s["label"], "source": s["source"], "unit": s["unit"],
                        "category": s["category"], "frequency": s["frequency"], "meta": s["meta"],
                        "last": last.as_dict() if last else None,
                        "validity": observations.validity(s, last.reference_date if last else None, today())})
        return out

    @app.get("/api/radar/series/{series_id}/history")
    async def radar_series_history(series_id: str, days: int = Query(180, ge=7, le=3650),
                                   user: str = Depends(current_user)):
        meta = observations.series_meta(conn, series_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Série inexistente.")
        pts = observations.history(conn, series_id, since=(today() - dt.timedelta(days=days)).isoformat())
        return {"series": meta, "points": [p.as_dict() for p in pts]}

    @app.post("/api/radar/assets", status_code=201)
    async def radar_asset_create(body: AssetIn, user: str = Depends(current_user)):
        ticker = body.ticker.strip().upper()
        if not TICKER.match(ticker):
            raise HTTPException(status_code=422, detail="Código de negociação inválido (ex.: PETR4, BOVA11, HGLG11).")
        sid = f"user_{body.kind}_{ticker.lower()}"
        observations.ensure_series(conn, sid, source="pessoa", label=ticker, unit="R$", currency="BRL",
                                   frequency="eventual", category=body.kind, max_age_days=10, now=now(),
                                   meta={"ticker": ticker})
        observations.ensure_series(conn, f"{sid}_proventos", source="pessoa", label=f"{ticker} — proventos",
                                   unit="R$ por cota", currency="BRL", frequency="eventual", category=body.kind,
                                   max_age_days=3650, now=now(), meta={"ticker": ticker})
        log_access(user, "radar.asset", sid)
        return observations.series_meta(conn, sid)

    def user_series(series_id: str) -> dict:
        meta = observations.series_meta(conn, series_id)
        if not meta or meta["source"] != "pessoa" or series_id.endswith("_proventos"):
            raise HTTPException(status_code=404, detail="Ativo inexistente.")
        return meta

    @app.post("/api/radar/assets/{series_id}/observations", status_code=201)
    async def radar_asset_observation(series_id: str, body: ObservationIn, user: str = Depends(current_user)):
        user_series(series_id)
        if body.reference_date > today():
            raise HTTPException(status_code=422, detail="Data futura não é aceita.")
        target = series_id if body.kind == "preco" else f"{series_id}_proventos"
        result = bad_request(observations.record, conn, target, body.reference_date.isoformat(), body.value,
                             fetched_at=now())
        return {"result": result}

    @app.post("/api/radar/assets/{series_id}/events", status_code=201)
    async def radar_asset_event(series_id: str, body: CorporateEventIn, user: str = Depends(current_user)):
        user_series(series_id)
        from financial_engine.money import to_decimal
        factor = bad_request(lambda: to_decimal(body.factor))
        if factor <= 0:
            raise HTTPException(status_code=422, detail="Fator precisa ser positivo.")
        conn.execute("INSERT OR IGNORE INTO radar_corporate_events (id, series_id, ex_date, kind, factor, source, "
                     "created_at) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), series_id, body.ex_date.isoformat(),
                                                            body.kind, str(factor), "pessoa", now()))
        return {"ok": True}

    # --- alertas ---
    @app.get("/api/radar/alerts")
    async def radar_alerts(status: str | None = Query(None, max_length=20), user: str = Depends(current_user)):
        return alerts.list_for(conn, user, status=status)

    @app.post("/api/radar/alerts/{alert_id}/status")
    async def radar_alert_status(alert_id: str, body: StatusIn, user: str = Depends(current_user)):
        own_alert(alert_id, user)
        bad_request(alerts.set_status, conn, alert_id, body.status, now())
        return alerts.get(conn, alert_id)

    @app.post("/api/radar/alerts/{alert_id}/feedback")
    async def radar_alert_feedback(alert_id: str, body: FeedbackIn, user: str = Depends(current_user)):
        own_alert(alert_id, user)
        alerts.set_feedback(conn, alert_id, body.feedback, now())
        return alerts.get(conn, alert_id)

    @app.post("/api/radar/alerts/{alert_id}/mute")
    async def radar_alert_mute(alert_id: str, body: MuteIn, user: str = Depends(current_user)):
        alert = own_alert(alert_id, user)
        rec = alerts.mute(conn, user, alert["group_key"], body.days, dt.datetime.now(dt.timezone.utc))
        alerts.set_status(conn, alert_id, "silenciado", now())
        log_access(user, "radar.mute", alert["group_key"])
        return rec

    # --- regras ---
    @app.get("/api/radar/rules")
    async def radar_rules(user: str = Depends(current_user)):
        rules.seed_defaults(conn, user, now())
        state = {r["rule_id"]: dict(r) for r in conn.execute("SELECT * FROM radar_rule_state")}
        return [{**r, "state": state.get(r["id"])} for r in rules.current(conn, user, include_archived=True)]

    @app.post("/api/radar/rules", status_code=201)
    async def radar_rule_create(body: RuleIn, user: str = Depends(current_user)):
        rule = bad_request(rules.create, conn, user, body.model_dump(), now=now())
        log_access(user, "radar.rule.create", rule["id"])
        return rule

    @app.put("/api/radar/rules/{rule_id}")
    async def radar_rule_update(rule_id: str, body: RuleIn, user: str = Depends(current_user)):
        own_rule(rule_id, user)
        rule = bad_request(rules.update, conn, user, rule_id, body.model_dump(), now=now(), origin="pessoa")
        log_access(user, "radar.rule.update", rule_id)
        return rule

    @app.post("/api/radar/rules/{rule_id}/status")
    async def radar_rule_status(rule_id: str, body: StatusIn, user: str = Depends(current_user)):
        own_rule(rule_id, user)
        rule = bad_request(rules.update, conn, user, rule_id, {"status": body.status}, now=now(), origin="pessoa")
        log_access(user, f"radar.rule.{body.status}", rule_id)
        return rule

    @app.get("/api/radar/rules/{rule_id}/versions")
    async def radar_rule_versions(rule_id: str, user: str = Depends(current_user)):
        own_rule(rule_id, user)
        return {"versions": rules.versions(conn, rule_id), "backtests": backtest.list_for(conn, rule_id)}

    @app.post("/api/radar/rules/{rule_id}/backtest")
    async def radar_rule_backtest(rule_id: str, body: BacktestIn, user: str = Depends(current_user)):
        rule = own_rule(rule_id, user)
        return bad_request(backtest.run_backtest, conn, user, rule, now=now(),
                           start=body.start.isoformat() if body.start else None,
                           end=body.end.isoformat() if body.end else None)

    @app.get("/api/radar/proposals")
    async def radar_proposals(user: str = Depends(current_user)):
        return metrics.list_proposals(conn, user)

    @app.post("/api/radar/proposals/{proposal_id}/{decision}")
    async def radar_proposal_decide(proposal_id: str, decision: Literal["approve", "reject"],
                                    user: str = Depends(current_user)):
        result = bad_request(metrics.decide_proposal, conn, user, proposal_id, decision == "approve", now())
        if not result:
            raise HTTPException(status_code=404, detail="Proposta inexistente ou já decidida.")
        log_access(user, f"radar.proposal.{decision}", proposal_id)
        return result

    # --- preferências e canais ---
    @app.get("/api/radar/prefs")
    async def radar_prefs(user: str = Depends(current_user)):
        return {"prefs": alerts.prefs(conn, user), "channels": alerts.channels(conn, user)}

    @app.put("/api/radar/prefs")
    async def radar_prefs_put(body: PrefsIn, user: str = Depends(current_user)):
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        return bad_request(alerts.save_prefs, conn, user, data, now())

    @app.put("/api/radar/channels/{channel}")
    async def radar_channel_put(channel: str, body: ChannelIn, user: str = Depends(current_user)):
        result = bad_request(alerts.set_channel, conn, user, channel, body.enabled, body.consent, now())
        log_access(user, f"radar.channel.{'on' if body.enabled else 'off'}", channel)
        return result

    # --- Diário ---
    @app.get("/api/radar/journal")
    async def radar_journal(category: str | None = Query(None, max_length=20), state: str | None = Query(None, max_length=30),
                            rule_id: str | None = Query(None, max_length=60), asset: str | None = Query(None, max_length=60),
                            since: dt.date | None = None, until: dt.date | None = None,
                            min_class: int | None = Query(None, ge=1, le=5),
                            verdict: str | None = Query(None, max_length=40),
                            agent: str | None = Query(None, max_length=40), user: str = Depends(current_user)):
        if agent and agent not in AGENTS:
            raise HTTPException(status_code=422, detail="Agente desconhecido.")
        return journal.list_for(conn, user, category=category, state=state, rule_id=rule_id, series=asset,
                                since=since.isoformat() if since else None,
                                until=f"{until.isoformat()}T23:59:59+99:99" if until else None,
                                min_class=min_class, verdict=verdict, agent=agent)

    @app.get("/api/radar/journal/{opp_id}")
    async def radar_journal_detail(opp_id: str, user: str = Depends(current_user)):
        own_opp(opp_id, user)
        return engine.detail(conn, opp_id)

    @app.post("/api/radar/journal/{opp_id}/decisions", status_code=201)
    async def radar_decision(opp_id: str, body: DecisionIn, user: str = Depends(current_user)):
        own_opp(opp_id, user)
        return bad_request(journal.add_decision, conn, user, opp_id, body.decision, body.note, now())

    @app.post("/api/radar/journal/{opp_id}/operations", status_code=201)
    async def radar_operation(opp_id: str, body: OperationIn, user: str = Depends(current_user)):
        own_opp(opp_id, user)
        rec = bad_request(journal.add_operation, conn, user, opp_id, body.model_dump(mode="json"), now())
        log_access(user, "radar.operation.record", opp_id)
        return rec

    @app.post("/api/radar/journal/{opp_id}/corrections", status_code=201)
    async def radar_correction(opp_id: str, body: CorrectionIn, user: str = Depends(current_user)):
        own_opp(opp_id, user)
        snap = bad_request(journal.add_snapshot, conn, opp_id, "correcao", {"alteracoes": body.changes, "por": "pessoa"},
                           now(), reason=body.reason)
        log_access(user, "radar.journal.correction", opp_id)
        return snap

    @app.post("/api/radar/journal/{opp_id}/discuss", status_code=201)
    async def radar_discuss(opp_id: str, body: DiscussIn, user: str = Depends(current_user)):
        """Abre uma conversa (Mentor ou Conselho) já com o registro do Diário como contexto, e guarda o vínculo."""
        opp = own_opp(opp_id, user)
        info = engine.detail(conn, opp_id)
        det = next(s["payload"] for s in info["snapshots"] if s["kind"] == "deteccao")
        analysis = next((s["payload"] for s in info["snapshots"] if s["kind"] == "analise"), None)
        lines = [engine.context_message(det), "",
                 f"_Registro do Diário de {opp['created_at'][:10]} (dados de então); estado atual: {opp['state']}._"]
        if analysis and analysis.get("mentor"):
            lines += ["", "**Conclusão registrada do Mentor (na época):**", analysis["mentor"]["texto"][:2000]]
        done = [o for o in info["outcomes"] if o["status"] == "calculado"]
        if done:
            lines += ["", "**Avaliações posteriores já calculadas (informação descoberta depois):**"]
            lines += [f"- {o['horizon_days']} dias: {o['verdict']} (excesso vs CDI: "
                      f"{o['result'].get('excesso_vs_cdi_pp', '—')} p.p.)" for o in done]
        purpose = "mentor" if body.target == "mentor" else "conselho"
        title = f"{'Mentor' if purpose == 'mentor' else 'Conselho'} · {opp['asset_label']}"[:120]
        if purpose == "mentor":
            conv = store.create_conversation(conn, title, channel="direct", agent_id="mentor", user_id=user)
        else:
            conv = store.create_conversation(conn, title, kind="panel", channel="council", user_id=user)
            from team.agents import SPECIALISTS
            for agent in ("mentor", *SPECIALISTS):
                store.add_participant(conn, conv["id"], agent)
        store.add_message(conn, conv["id"], "assistant", "\n".join(lines), agent_id="lastro", kind="analysis")
        journal.link(conn, opp_id, conv["id"], purpose, now())
        log_access(user, "radar.discuss", opp_id)
        return store.user_conversation(conn, conv["id"], user)

    @app.get("/api/radar/links/{conversation_id}")
    async def radar_link(conversation_id: str, user: str = Depends(current_user)):
        conv = store.user_conversation(conn, conversation_id, user)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversa inexistente.")
        opp_id = journal.opportunity_for_conversation(conn, conversation_id)
        opp = journal.get(conn, opp_id) if opp_id else None
        return {"opportunity_id": opp_id, "asset_label": opp["asset_label"] if opp else None}

    @app.get("/api/radar/metrics")
    async def radar_metrics(days: int = Query(365, ge=7, le=3650), horizon: int = Query(metrics.PRIMARY_HORIZON, ge=1,
                                                                                       le=3650),
                            user: str = Depends(current_user)):
        return metrics.compute(conn, user, since=metrics.since_days(today(), days), horizon=horizon)
