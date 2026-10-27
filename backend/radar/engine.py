"""O laço do Radar: avalia regras, registra no Diário, aciona o Conselho quando vale a pena, alerta e acompanha.

Roda dentro do web app (que tem o banco e o orquestrador), sem rede: os dados chegam pelo coletor. Cada etapa é
retomável — o estado vive no banco (sinal → oportunidade → registro → alerta → avaliações), então um reinício
no meio continua de onde parou, e a unicidade (fingerprint do sinal, alerta por oportunidade, avaliação por
horizonte) impede duplicatas.
"""

import asyncio
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app import store, views
from integrations.catalog import SOURCE_NAMES
from team.agents import get as get_agent

from . import alerts, evaluator, journal, metrics, observations, outcomes, rules

log = logging.getLogger("lastro.radar")
USER_TZ = ZoneInfo(os.environ.get("LASTRO_TZ") or "America/Sao_Paulo")  # fuso da instalação
ANALYSIS_TIMEOUT = timedelta(hours=3)
HISTORY_DAYS = 400
MACRO_CONTEXT = ("selic_meta", "cdi", "ipca_12m")
LEARNING_KEY = "__aprendizado__"
RETENTION_KEY = "__retencao__"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def profile_for(conn, user_id: str, today: date) -> dict:
    snap = store.latest_snapshot(conn)
    if not snap:
        return {"has_snapshot": False}
    out = {"has_snapshot": True, "as_of": snap["as_of"]}
    try:
        diag = views.diagnosis_view(conn)
        out.update(stage=diag["guidance"]["stage"], next_step=diag["guidance"].get("next_step"),
                   reserve_months=diag["reserve"]["coverage_months"])
    except (views.NoData, ValueError, ArithmeticError):
        pass
    out["goal_years"] = sorted({round((date.fromisoformat(g["deadline"]) - today).days / 365.25, 1)
                                for g in store.list_goals(conn) if g["deadline"] >= today.isoformat()})
    facts = {f["key"]: f["value"] for f in store.list_facts(conn, user_id, "confirmed")}
    out["risk_profile"] = facts.get("perfil_risco")
    return out


def _point_dict(conn, series_id: str, today: date, known_at: str | None) -> dict | None:
    points = observations.history(conn, series_id, until=today.isoformat(), known_at=known_at,
                                  since=(today - timedelta(days=60)).isoformat())
    meta = observations.series_meta(conn, series_id)
    if not points or not meta:
        return None
    last = points[-1]
    return {**last.as_dict(), "series_id": series_id, "label": meta["label"], "unit": meta["unit"],
            "source": SOURCE_NAMES.get(meta["source"], meta["source"]),
            "validity": observations.validity(meta, last.reference_date, today)}


def build_detection(conn, *, user_id: str, rule: dict, meta: dict | None, trigger: rules.Trigger,
                    points: list, profile: dict | None, today: date, now: str, known_at: str | None) -> dict:
    """Tudo o que se sabia no momento da detecção — e só isso (`known_at`: o que já tinha sido coletado; None no
    backtest, que só tem o valor vigente)."""
    point = next((p for p in reversed(points) if p.obs_id == trigger.observation_id), points[-1] if points else None)
    quality = evaluator.data_quality(meta, point, today) if meta else {
        "score": Decimal(1), "status": "valido", "issues": [], "reference_date": trigger.reference_date}
    suit = evaluator.suitability(profile or {}, rule["category"], meta, today) if profile is not None else {
        "status": "nao_avaliada", "score": Decimal("0.5"), "reasons": ["Backtest: adequação ao perfil não avaliada."]}
    cls = evaluator.classify(rule, trigger.magnitude, quality, suit)
    dados: dict = {"serie_recente": [p.as_dict() for p in points[-30:]]}
    context = {}
    if meta and meta["source"] == "tesouro_direto":
        prefix = meta["series_id"].rsplit("_", 2)[0]
        for metric in ("pu_compra", "pu_venda", "taxa_venda"):
            same_day = observations.history(conn, f"{prefix}_{metric}", since=trigger.reference_date,
                                            until=trigger.reference_date, known_at=known_at)
            dados[metric] = same_day[-1].as_dict() if same_day else None
        macro = {sid: _point_dict(conn, sid, today, known_at) for sid in MACRO_CONTEXT}
        dados["macro"] = macro
        context = evaluator.td_context(trigger.values, meta, today, (macro.get("ipca_12m") or {}).get("value"))
    elif rule["category"] in ("macro", "renda_fixa"):
        dados["macro"] = {sid: _point_dict(conn, sid, today, known_at) for sid in MACRO_CONTEXT}
    hyp = evaluator.hypothesis(rule, meta, trigger.values)
    analysis, why = evaluator.needs_analysis(rule, cls["classification"], quality)
    agents = evaluator.select_agents(rule["category"], rule["kind"], trigger.magnitude, suit) if analysis else []
    limitations = list(evaluator.LIMITATIONS_ALWAYS) + quality["issues"]
    if meta and meta["source"] == "pessoa":
        limitations.append("Preços informados por você: o Radar não tem fonte licenciada de cotações de ações, ETFs ou FIIs.")
    return {
        "versao_registro": 1, "user_id": user_id, "registrado_em": now,
        "regra": {k: rule[k] for k in ("id", "version", "name", "kind", "category", "series_pattern", "params",
                                       "priority", "horizons", "benchmark")},
        "sinal": {"reference_date": trigger.reference_date, "observation_id": trigger.observation_id,
                  "valor_observado": trigger.values.get("valor") or trigger.values.get("meses"),
                  "condicao": trigger.condition, "valores": trigger.values, "magnitude": str(trigger.magnitude)},
        "serie": {k: meta[k] for k in ("series_id", "source", "label", "unit", "currency", "frequency",
                                       "max_age_days", "url", "meta")} | {"fonte": SOURCE_NAMES.get(meta["source"])}
        if meta else None,
        "dados": dados, "qualidade": quality, "contexto": context,
        "adequacao": {**suit, "perfil": {k: v for k, v in (profile or {}).items() if k in (
            "as_of", "stage", "reserve_months", "goal_years", "risk_profile")}},
        "custos": evaluator.costs(rule["category"], meta), "classificacao": cls, "hipotese": hyp,
        "horizontes": rule["horizons"], "benchmark": rule["benchmark"],
        "analise_multiagente": {"acionada": analysis, "motivo": why, "agentes": agents},
        "limitacoes": limitations,
    }


def context_message(det: dict) -> str:
    """Contexto do sinal para a conversa do Conselho: só dados de mercado e da regra (sem dados do dono)."""
    s, serie = det["sinal"], det["serie"] or {}
    lines = [f"**Radar — {serie.get('label', det['regra']['name'])}**",
             f"- Regra: {det['regra']['name']} (versão {det['regra']['version']})",
             f"- Condição: {s['condicao']}",
             f"- Data de referência do dado: {s['reference_date']} · fonte: {serie.get('fonte') or '—'}",
             f"- Classificação determinística: {det['classificacao']['classification']} — "
             f"{rules.PRIORITY_LABELS[det['classificacao']['classification']]} (score {det['classificacao']['score']}, "
             "não é probabilidade)",
             f"- Hipótese registrada: {det['hipotese']['texto']}"]
    for k, v in (det.get("contexto") or {}).items():
        lines.append(f"- {k.replace('_', ' ')}: {v}")
    for sid, p in ((det.get("dados") or {}).get("macro") or {}).items():
        if p:
            lines.append(f"- {p['label']}: {p['value']} {p['unit']} (ref. {p['reference_date']}, {p['validity']})")
    lines.append("- Limitações: " + " ".join(det["limitacoes"]))
    return "\n".join(lines)


class Radar:
    def __init__(self, conn, *, orchestrator=None, now=utc_now, tz: ZoneInfo = USER_TZ, user_id: str = store.OWNER):
        self.conn, self.orchestrator, self.now, self.tz, self.user_id = conn, orchestrator, now, tz, user_id
        self.last_tick: dict | None = None

    def today(self) -> date:
        return self.now().astimezone(self.tz).date()

    def stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    # ---------- laço ----------

    async def run_forever(self, interval: int = 60) -> None:
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — o laço nunca morre; o erro fica no log e a próxima volta tenta de novo
                log.exception("volta do Radar falhou")
            await asyncio.sleep(interval)

    def tick(self, *, force: bool = False) -> dict:
        now = self.stamp()
        rules.seed_defaults(self.conn, self.user_id, now)
        result = {"sinais": self.evaluate_rules(force=force), "processadas": self.process_pending(),
                  "avaliacoes": outcomes.compute_due(self.conn, self.today(), now), "em": now}
        self._daily()
        self.last_tick = result
        return result

    def _daily(self) -> None:
        row = self.conn.execute("SELECT last_evaluated_at FROM radar_rule_state WHERE rule_id = ?",
                                (LEARNING_KEY,)).fetchone()
        if row and row[0] and row[0][:10] == self.today().isoformat():
            return
        now = self.stamp()
        metrics.propose_adjustments(self.conn, self.user_id, now, backtest=self._proposal_backtest)
        retention = int(os.environ.get("LASTRO_RADAR_RETENTION_DAYS", "3650"))
        observations.prune(self.conn, older_than=(self.today() - timedelta(days=retention)).isoformat())
        self.conn.execute("INSERT INTO radar_rule_state (rule_id, last_evaluated_at) VALUES (?,?) ON CONFLICT(rule_id) "
                          "DO UPDATE SET last_evaluated_at = excluded.last_evaluated_at", (LEARNING_KEY, now))

    def _proposal_backtest(self, proposed: dict) -> dict:
        from .backtest import run_backtest

        return run_backtest(self.conn, self.user_id, proposed, now=self.stamp())

    # ---------- regras → sinais ----------

    def evaluate_rules(self, *, force: bool = False) -> int:
        created = 0
        now_dt, today = self.now(), self.today()
        series = observations.list_series(self.conn)
        for rule in rules.current(self.conn, self.user_id):
            if rule["status"] != "ativa":
                continue
            state = self.conn.execute("SELECT last_evaluated_at FROM radar_rule_state WHERE rule_id = ?",
                                      (rule["id"],)).fetchone()
            if not force and state and state[0] and \
                    datetime.fromisoformat(state[0]) + timedelta(minutes=rule["interval_minutes"]) > now_dt:
                continue
            try:
                created += self._evaluate_rule(rule, series, today)
                outcome = "ok"
            except Exception as exc:  # noqa: BLE001 — uma regra com problema não impede as outras
                log.exception("regra %s falhou", rule["id"])
                outcome = f"erro: {type(exc).__name__}"
            self.conn.execute("INSERT INTO radar_rule_state (rule_id, last_evaluated_at, last_result) VALUES (?,?,?) "
                              "ON CONFLICT(rule_id) DO UPDATE SET last_evaluated_at = excluded.last_evaluated_at, "
                              "last_result = excluded.last_result", (rule["id"], self.stamp(), outcome))
        return created

    def _last_signal(self, rule_id: str, series_id: str | None) -> str | None:
        row = self.conn.execute("SELECT MAX(reference_date) FROM radar_signals WHERE rule_id = ? AND series_id IS ?",
                                (rule_id, series_id)).fetchone()
        return row[0] if row else None

    def _evaluate_rule(self, rule: dict, series: list[dict], today: date) -> int:
        now = self.stamp()
        if rule["kind"] == "reserva":
            trigger = rules.evaluate_reserve(rule, store.latest_snapshot(self.conn),
                                             last_signal_date=self._last_signal(rule["id"], None))
            return int(bool(trigger and self._register(rule, None, trigger, [], today)))
        created = 0
        for meta in rules.matching_series(rule, series, today):
            sid = meta["series_id"]
            points = observations.history(self.conn, sid, until=today.isoformat(), known_at=now,
                                          since=(today - timedelta(days=HISTORY_DAYS)).isoformat())
            last_signal = self._last_signal(rule["id"], sid)
            if rule["kind"] == "dado_desatualizado":
                trigger = rules.evaluate_stale(rule, meta, points[-1] if points else None, today,
                                               last_signal_date=last_signal)
            else:
                trigger = rules.evaluate(rule, points, last_signal_date=last_signal)
            if trigger and self._register(rule, meta, trigger, points, today):
                created += 1
        return created

    def _register(self, rule: dict, meta: dict | None, trigger: rules.Trigger, points: list, today: date) -> bool:
        """Sinal + oportunidade + registro de detecção numa transação: ou tudo existe, ou nada."""
        sid = meta["series_id"] if meta else None
        fingerprint = f"{rule['id']}:{sid or '-'}:{trigger.reference_date}"
        if self.conn.execute("SELECT 1 FROM radar_signals WHERE fingerprint = ?", (fingerprint,)).fetchone():
            return False
        now = self.stamp()
        profile = profile_for(self.conn, self.user_id, today)
        det = build_detection(self.conn, user_id=self.user_id, rule=rule, meta=meta, trigger=trigger, points=points,
                              profile=profile, today=today, now=now, known_at=now)
        signal_id = str(uuid.uuid4())
        self.conn.execute("BEGIN")
        try:
            self.conn.execute(
                "INSERT INTO radar_signals (id, user_id, rule_id, rule_version, series_id, observation_id, reference_date, "
                "detected_at, fingerprint, condition_text, values_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (signal_id, self.user_id, rule["id"], rule["version"], sid, trigger.observation_id,
                 trigger.reference_date, now, fingerprint, trigger.condition, journal.canonical(trigger.values)))
            opp = journal.create(self.conn, user_id=self.user_id, signal_id=signal_id, rule_id=rule["id"],
                                 category=rule["category"], series_id=sid,
                                 asset_label=meta["label"] if meta else rule["name"],
                                 classification=det["classificacao"]["classification"],
                                 score=det["classificacao"]["score"], now=now)
            journal.add_snapshot(self.conn, opp["id"], "deteccao", det, now)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return True

    # ---------- oportunidades: análise, alerta, acompanhamento ----------

    def process_pending(self) -> int:
        done = 0
        for opp in self.conn.execute("SELECT * FROM radar_opportunities WHERE state IN ('detectada', 'em_analise', "
                                     "'avaliada', 'alerta_emitido') AND user_id = ? ORDER BY created_at",
                                     (self.user_id,)).fetchall():
            # Cada avanço é atômico: uma queda no meio (alerta criado, estado não) nunca duplica alerta nem avaliação.
            self.conn.execute("BEGIN")
            try:
                done += self._advance(dict(opp))
                self.conn.execute("COMMIT")
            except Exception:  # noqa: BLE001
                self.conn.execute("ROLLBACK")
                log.exception("oportunidade %s não avançou", opp["id"])
        return done

    def _advance(self, opp: dict) -> int:
        now = self.stamp()
        det = journal.original(self.conn, opp["id"])
        if opp["state"] == "detectada":
            plan = det["analise_multiagente"]
            if plan["acionada"] and self.orchestrator is not None and self._analysis_budget_left():
                self._start_analysis(opp, det)
                return 1
            reason = plan["motivo"] or ("orquestrador indisponível" if self.orchestrator is None
                                        else "limite diário de análises do Conselho atingido")
            journal.set_state(self.conn, opp["id"], "avaliada", now, analise_multiagente=False, motivo=reason)
            opp["state"] = "avaliada"
        if opp["state"] == "em_analise":
            if not self._finish_analysis(opp):
                return 0
            opp["state"] = "avaliada"
        if opp["state"] == "avaliada":
            decision = alerts.process(self.conn, opp, det["sinal"]["condicao"], self.now(), self.tz)
            if decision["action"] == "alerta":
                journal.set_state(self.conn, opp["id"], "alerta_emitido", now, alerta=decision["alert_id"])
                opp["state"] = "alerta_emitido"
            else:
                journal.event(self.conn, opp["id"], "sem_alerta", now, acao=decision["action"],
                              motivo=decision.get("reason"))
        outcomes.schedule(self.conn, opp["id"], det["hipotese"]["metodo"], det["horizontes"],
                          det["sinal"]["reference_date"], now)
        journal.set_state(self.conn, opp["id"], "em_acompanhamento", now, horizontes=det["horizontes"])
        return 1

    def _analysis_budget_left(self) -> bool:
        limit = alerts.prefs(self.conn, self.user_id)["max_analyses_per_day"]
        day_start = self.now().astimezone(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        used = self.conn.execute("SELECT COUNT(*) FROM radar_events e JOIN radar_opportunities o ON o.id = "
                                 "e.opportunity_id WHERE o.user_id = ? AND e.kind = 'em_analise' AND e.at >= ?",
                                 (self.user_id, day_start.astimezone(timezone.utc).isoformat(timespec="seconds"))
                                 ).fetchone()[0]
        return used < limit

    def _start_analysis(self, opp: dict, det: dict) -> None:
        agents = det["analise_multiagente"]["agentes"]
        title = f"Radar · {opp['asset_label']} · {det['sinal']['reference_date']}"
        conv = store.create_conversation(self.conn, title, kind="panel", channel="council", user_id=self.user_id)
        for agent in ("mentor", *agents):
            store.add_participant(self.conn, conv["id"], agent)
        context = context_message(det)
        profile_note = ("\n\nSeu momento financeiro (dados do dono, só para quem pode vê-los):\n"
                        f"- adequação determinística: {det['adequacao']['status']}\n"
                        + "".join(f"- {r}\n" for r in det["adequacao"]["reasons"]))
        tasks = {a: context + (profile_note if get_agent(a).caps.data else "") for a in agents}
        run = self.orchestrator.submit_radar(store.get_conversation(self.conn, conv["id"]), context, agents=agents,
                                             tasks=tasks, opportunity_id=opp["id"],
                                             synthesis_extra=profile_note)
        now = self.stamp()
        self.conn.execute("UPDATE radar_opportunities SET analysis_run_id = ? WHERE id = ?", (run["id"], opp["id"]))
        journal.link(self.conn, opp["id"], conv["id"], "analise", now)
        journal.set_state(self.conn, opp["id"], "em_analise", now, run_id=run["id"], agentes=agents)

    def _finish_analysis(self, opp: dict) -> bool:
        run = store.get_run(self.conn, opp["analysis_run_id"]) if opp["analysis_run_id"] else None
        if run and run["status"] in ("queued", "running") and \
                self.now() - datetime.fromisoformat(run["created_at"]) < ANALYSIS_TIMEOUT:
            return False
        payload = {"run_id": opp["analysis_run_id"], "run_status": run["status"] if run else "indisponivel",
                   "conversation_id": run["conversation_id"] if run else None, "pareceres": [], "mentor": None}
        if run:
            if run["status"] in ("queued", "running"):
                payload["run_status"] = "tempo_esgotado"
            for m in store.list_messages(self.conn, run["conversation_id"]):
                if m["run_id"] != run["id"] or not (m["step_key"] or "").startswith("radar:"):
                    continue
                entry = {"agent_id": m["agent_id"], "texto": m["content"], "status": m["status"], "auditoria": m["audit"],
                         "fontes": m["sources"]}
                if m["step_key"] == "radar:sintese":
                    payload["mentor"] = entry
                else:
                    payload["pareceres"].append(entry)
        now = self.stamp()
        journal.add_snapshot(self.conn, opp["id"], "analise", payload, now)
        journal.set_state(self.conn, opp["id"], "avaliada", now, run_status=payload["run_status"])
        return True


def detail(conn, opp_id: str) -> dict:
    opp = journal.get(conn, opp_id)
    alert = conn.execute("SELECT * FROM radar_alerts WHERE opportunity_id = ?", (opp_id,)).fetchone()
    return {
        "opportunity": opp,
        "signal": dict(conn.execute("SELECT * FROM radar_signals WHERE id = ?", (opp["signal_id"],)).fetchone()),
        "snapshots": journal.snapshots(conn, opp_id),
        "chain": journal.verify_chain(conn, opp_id),
        "timeline": journal.timeline(conn, opp_id),
        "outcomes": outcomes.list_for(conn, opp_id),
        "alert": {**dict(alert), "deliveries": alerts.deliveries(conn, alert["id"])} if alert else None,
        "decisions": [dict(r) for r in conn.execute("SELECT * FROM radar_decisions WHERE opportunity_id = ? ORDER BY "
                                                    "created_at", (opp_id,))],
        "operations": [dict(r) for r in conn.execute("SELECT * FROM radar_user_operations WHERE opportunity_id = ? "
                                                     "ORDER BY operation_date", (opp_id,))],
        "links": journal.links(conn, opp_id),
        "evolution": _evolution(conn, opp),
    }


def _evolution(conn, opp: dict) -> list[dict]:
    """Série depois da detecção (informação posterior, exibida separada do registro original)."""
    if not opp["series_id"]:
        return []
    signal = conn.execute("SELECT reference_date FROM radar_signals WHERE id = ?", (opp["signal_id"],)).fetchone()
    return [p.as_dict() for p in observations.history(conn, opp["series_id"], since=signal[0])][:400]
