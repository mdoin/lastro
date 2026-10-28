# SPDX-License-Identifier: AGPL-3.0-or-later
"""Laboratório do Conselho: cria, executa, fecha, acompanha e mede experimentos (docs/LAB.md).

Execução: cada repetição abre DUAS conversas ocultas — o Bento sozinho (execução "individual", sem delegar) e o
Conselho completo — com o mesmo texto (pergunta + dossiê congelado) e as mesmas ferramentas (calculadora e, se o
experimento permitir, pesquisa). Nenhuma conversa enxerga a outra: o contexto de cada agente é montado só com a
própria conversa, sem anotações nem histórico de previsões. O orquestrador é o mesmo de sempre; nada aqui chama um
modelo diretamente, exceto a avaliação às cegas de utilidade, pedida explicitamente.

Nada aqui executa operação financeira: o Laboratório só lê, registra e compara.
"""

import asyncio
import json
import logging
import secrets
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from financial_engine import ENGINE_VERSION
from team import auditor, deliberation
from team.agents import get

from app import convictions, diary, store

from . import contract, dossier, evaluate

log = logging.getLogger("lastro.lab")

CATEGORIES = {"renda_fixa": "Renda fixa", "renda_variavel": "Renda variável", "cripto": "Cripto",
              "juros_e_inflacao": "Juros e inflação", "dividas": "Dívidas", "reserva": "Reserva e liquidez",
              "planejamento": "Planejamento", "outros": "Outros"}
DEFAULT_FOLLOWUPS = (30, 90, 180)
MAX_FOLLOWUPS = 4
MAX_SIMULATED_YEARS = 10
PROMPTS = Path(__file__).resolve().parents[1] / "mentor" / "prompts"
FINAL_KEYS = {"individual": "laboratorio:individual", "conselho": "conselho:sintese"}
SAMPLING = ("Temperatura e amostragem padrão de cada provedor (o Lastro não as configura). A variação entre execuções é "
            "medida pelas repetições, nunca presumida.")


class LabError(ValueError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def prompt_versions() -> dict[str, str]:
    """Hash de cada arquivo de instruções (versão dos prompts no momento do experimento)."""
    return {str(p.relative_to(PROMPTS)): dossier.sha256(p.read_text(encoding="utf-8"))[:16]
            for p in sorted(PROMPTS.rglob("*.md"))}


class Lab:
    def __init__(self, conn: sqlite3.Connection, orchestrator=None, *, today=None, app_version: str = ""):
        self.conn, self.orchestrator, self.app_version = conn, orchestrator, app_version
        self.today = today or date.today

    # ---------------------------------------------------------------- configuração

    def settings(self, user_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM lab_settings WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return {"automation": "desligada", "max_per_week": 2, "monthly_token_budget": 0, "repetitions": 1}
        return {k: row[k] for k in ("automation", "max_per_week", "monthly_token_budget", "repetitions")}

    def set_settings(self, user_id: str, data: dict) -> dict:
        cur = self.settings(user_id) | {k: v for k, v in data.items() if v is not None}
        if cur["automation"] not in ("desligada", "propor", "executar"):
            raise LabError("Automação: desligada, propor ou executar.")
        if not 0 <= int(cur["max_per_week"]) <= 14 or not 1 <= int(cur["repetitions"]) <= 5 \
                or int(cur["monthly_token_budget"]) < 0:
            raise LabError("Limites fora do intervalo permitido.")
        self.conn.execute("INSERT INTO lab_settings (user_id, automation, max_per_week, monthly_token_budget, repetitions, "
                          "updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET automation=excluded.automation, "
                          "max_per_week=excluded.max_per_week, monthly_token_budget=excluded.monthly_token_budget, "
                          "repetitions=excluded.repetitions, updated_at=excluded.updated_at",
                          (user_id, cur["automation"], int(cur["max_per_week"]), int(cur["monthly_token_budget"]),
                           int(cur["repetitions"]), utcnow()))
        return self.settings(user_id)

    # ---------------------------------------------------------------- criação

    def create(self, user_id: str, *, question: str, category: str = "outros", repetitions: int = 1,
               research: bool = False, as_of: str | None = None, followups: list[int] | None = None,
               client_id: str | None = None, origin: str = "pessoa", origin_ref: str | None = None,
               dedupe_key: str | None = None, start: bool = True) -> dict:
        if client_id:
            row = self.conn.execute("SELECT id FROM lab_experiments WHERE user_id = ? AND client_id = ?",
                                    (user_id, client_id)).fetchone()
            if row:
                return self.experiment(user_id, row["id"])
        question = " ".join((question or "").split())
        if not 10 <= len(question) <= 2000:
            raise LabError("Escreva a pergunta do experimento (de 10 a 2.000 caracteres).")
        if category not in CATEGORIES:
            raise LabError("Categoria desconhecida.")
        if not 1 <= int(repetitions) <= 5:
            raise LabError("Repetições: de 1 a 5 por modo.")
        today = self.today()
        try:
            cut = date.fromisoformat(as_of) if as_of else today
        except ValueError:
            raise LabError("Data simulada inválida.") from None
        if cut > today or cut < today - timedelta(days=365 * MAX_SIMULATED_YEARS):
            raise LabError(f"A data de corte vai de {MAX_SIMULATED_YEARS} anos atrás até hoje.")
        simulated = cut < today
        if simulated and research:
            raise LabError("Com data simulada, a pesquisa na internet fica desligada: ela traria fatos posteriores.")
        days = sorted({int(d) for d in (followups or DEFAULT_FOLLOWUPS)})
        if not days or len(days) > MAX_FOLLOWUPS or any(not 1 <= d <= 1825 for d in days):
            raise LabError("Reavaliações: até 4 prazos, de 1 a 1.825 dias.")
        built = dossier.build(self.conn, user_id, as_of=cut, today=today)
        text = dossier.render(question, built["dossie"])
        lineup = ["mentor", *deliberation.select(question, "completo"), "auditor"]
        agents = sorted({"mentor", *lineup})
        reasons = list(built["avisos"]) if simulated else []
        snapshot = {
            "contrato": contract.CONTRACT_VERSION, "pergunta": question, "categoria": category, "criado_em": utcnow(),
            "data_de_corte": cut.isoformat(), "simulado": simulated, "dossie": built["dossie"],
            "dossie_sha256": dossier.sha256(built["dossie"]), "texto_entregue_sha256": dossier.sha256(text),
            "fontes": built["fontes"], "avisos": built["avisos"],
            "comparabilidade": {"comparavel": built["comparavel"], "motivos": reasons},
            "prompts": (prompts := prompt_versions()), "prompts_sha256": dossier.sha256(prompts),
            "modelos": {a: store.ai_route(self.conn, a) or {"conexao": "padrão da instalação"} for a in agents},
            "agentes": {"individual": ["mentor"], "conselho": lineup},
            "ferramentas": {"todos_os_agentes": ["calcular"] + (["pesquisar_web"] if research else []),
                            "leitura_ao_vivo": "desligada (dados só pelo dossiê)"},
            "motor_financeiro": ENGINE_VERSION, "versao_lastro": self.app_version,
            "parametros": {"repeticoes": int(repetitions), "pesquisa_web": bool(research),
                           "limites_do_conselho": vars(deliberation.Limits.from_env()),
                           "esforco": {a: get(a).effort for a in agents}, "reavaliacoes_dias": days},
            "amostragem": SAMPLING,
        }
        exp_id, now = str(uuid.uuid4()), utcnow()
        try:
            self.conn.execute(
                "INSERT INTO lab_experiments (id, user_id, client_id, dedupe_key, origin, origin_ref, category, question, "
                "status, as_of, simulated, comparable, repetitions, research, followups_json, snapshot_json, "
                "snapshot_sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (exp_id, user_id, client_id, dedupe_key, origin, origin_ref, category, question, "proposto",
                 cut.isoformat(), int(simulated), int(built["comparavel"]), int(repetitions), int(research),
                 json.dumps(days), json.dumps(snapshot, ensure_ascii=False, default=str), dossier.sha256(snapshot), now))
        except sqlite3.IntegrityError:
            row = self.conn.execute("SELECT id FROM lab_experiments WHERE user_id = ? AND dedupe_key = ?",
                                    (user_id, dedupe_key)).fetchone()
            if row:
                return self.experiment(user_id, row["id"])
            raise
        for d in days:
            self.conn.execute("INSERT OR IGNORE INTO lab_checkpoints (id, experiment_id, user_id, days, due_on) "
                              "VALUES (?,?,?,?,?)", (str(uuid.uuid4()), exp_id, user_id, d,
                                                     (cut + timedelta(days=d)).isoformat()))
        if start:
            self.start(user_id, exp_id)
        return self.experiment(user_id, exp_id)

    def start(self, user_id: str, exp_id: str) -> dict:
        """Abre as conversas e enfileira as execuções. Idempotente: só sai de 'proposto' uma vez."""
        exp = self._row(user_id, exp_id)
        if exp["status"] != "proposto":
            return self.experiment(user_id, exp_id)
        snap = json.loads(exp["snapshot_json"])
        text = dossier.render(exp["question"], snap["dossie"])
        base = {"lab_research": bool(exp["research"]), "lab_suffix": contract.SUFFIX, "lab_experiment": exp_id,
                "reason": "Laboratório do Conselho"}
        now = utcnow()
        for rep in range(1, exp["repetitions"] + 1):
            for mode in ("individual", "conselho"):
                title = f"Laboratório · {'Bento sozinho' if mode == 'individual' else 'Conselho'} · {rep}"
                conv = store.create_conversation(self.conn, title, channel="direct" if mode == "individual" else "council",
                                                 agent_id="mentor" if mode == "individual" else None, user_id=user_id)
                aid = str(uuid.uuid4())
                # a análise é registrada antes da execução: a conversa já nasce oculta da lista da equipe
                self.conn.execute("INSERT INTO lab_analyses (id, experiment_id, user_id, mode, repetition, conversation_id, "
                                  "status, created_at) VALUES (?,?,?,?,?,?, 'na_fila', ?)",
                                  (aid, exp_id, user_id, mode, rep, conv["id"], now))
                if mode == "conselho":
                    for agent in snap["agentes"]["conselho"]:
                        store.add_participant(self.conn, conv["id"], agent)
                message = store.add_message(self.conn, conv["id"], "user", text)
                if mode == "individual":
                    run = store.create_run(self.conn, conv, message["id"], "reply",
                                           {**base, "lab": "individual", "agents": ["mentor"]})
                else:
                    run = store.create_run(self.conn, conv, message["id"], "council",
                                           {**base, "lab": "conselho", "mode": "completo", "agents": [],
                                            "lineup": snap["agentes"]["conselho"]})
                self.conn.execute("UPDATE lab_analyses SET run_id = ? WHERE id = ?", (run["id"], aid))
        self.conn.execute("UPDATE lab_experiments SET status = 'executando', started_at = ? WHERE id = ?", (now, exp_id))
        if self.orchestrator is not None:
            self.orchestrator._wake.set()
        return self.experiment(user_id, exp_id)

    def refuse(self, user_id: str, exp_id: str) -> dict:
        self._row(user_id, exp_id)
        self.conn.execute("UPDATE lab_experiments SET status = 'recusado', finished_at = ? WHERE id = ? AND status = "
                          "'proposto'", (utcnow(), exp_id))
        return self.experiment(user_id, exp_id)

    async def cancel(self, user_id: str, exp_id: str) -> dict:
        self._row(user_id, exp_id)
        for a in self.conn.execute("SELECT run_id FROM lab_analyses WHERE experiment_id = ? AND run_id IS NOT NULL",
                                   (exp_id,)).fetchall():
            run = store.get_run(self.conn, a["run_id"])
            if run and run["status"] in ("queued", "running") and self.orchestrator is not None:
                await self.orchestrator.cancel(run)
        self.conn.execute("UPDATE lab_experiments SET status = 'cancelado', finished_at = ? WHERE id = ? AND status IN "
                          "('proposto', 'executando')", (utcnow(), exp_id))
        self.advance()
        return self.experiment(user_id, exp_id)

    # ---------------------------------------------------------------- fechamento das análises

    def advance(self) -> int:
        """Fecha as análises cujas execuções terminaram e conclui os experimentos completos. Idempotente."""
        done = 0
        rows = self.conn.execute(
            "SELECT a.*, e.as_of, e.status AS exp_status FROM lab_analyses a JOIN lab_experiments e ON e.id = a.experiment_id "
            "WHERE a.finished_at IS NULL AND a.run_id IS NOT NULL").fetchall()
        for a in rows:
            run = store.get_run(self.conn, a["run_id"])
            if not run:
                continue
            if run["status"] in ("queued", "running"):
                if run["status"] == "running" and a["status"] == "na_fila":
                    self.conn.execute("UPDATE lab_analyses SET status = 'executando' WHERE id = ?", (a["id"],))
                continue
            self._close(dict(a), run)
            done += 1
        for e in self.conn.execute("SELECT * FROM lab_experiments WHERE status = 'executando'").fetchall():
            open_ = self.conn.execute("SELECT COUNT(*) FROM lab_analyses WHERE experiment_id = ? AND finished_at IS NULL",
                                      (e["id"],)).fetchone()[0]
            if open_:
                continue
            statuses = [r[0] for r in self.conn.execute("SELECT status FROM lab_analyses WHERE experiment_id = ?",
                                                        (e["id"],))]
            final = "concluido" if statuses and all(s == "concluida" for s in statuses) else "incompleto"
            self.conn.execute("UPDATE lab_experiments SET status = ?, finished_at = COALESCE(finished_at, ?) WHERE id = ?",
                              (final, utcnow(), e["id"]))
            self._journal_analysis(e["id"])
            done += 1
        return done

    def _close(self, a: dict, run: dict) -> None:
        result = json.loads(run["result_json"]) if run.get("result_json") else {}
        usage = result.get("consumo") or {}
        row = self.conn.execute("SELECT id FROM messages WHERE run_id = ? AND step_key = ? ORDER BY created_at DESC "
                                "LIMIT 1", (run["id"], FINAL_KEYS[a["mode"]])).fetchone()
        message = store.get_message(self.conn, row["id"]) if row else None
        ok = message is not None and message["status"] == "ok" and run["status"] in ("succeeded", "partial")
        status = "concluida" if ok else "cancelada" if run["status"] == "cancelled" else "falhou"
        text, record, record_status, evaluation = None, None, None, None
        if ok:
            as_of = date.fromisoformat(a["as_of"])
            text = message["content"]
            record, record_status, problems = contract.parse(text, as_of)
            for h in (record or {}).get("hipoteses", []):
                h["_dias"] = (date.fromisoformat(h["data"]) - as_of).days
            audit = message.get("audit")
            meeting = result.get("reuniao")
            turn_texts = []
            for t in (meeting or {}).get("falas") or []:
                m = store.get_message(self.conn, t["message_id"]) if t.get("message_id") else None
                if m:
                    turn_texts.append(m["content"])
            corrections = self.conn.execute("SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND step_key LIKE "
                                            "'%:correcao' AND status = 'succeeded'", (run["id"],)).fetchone()[0]
            evaluation = {
                "registro": {"status": record_status, "problemas": problems},
                "factual": {"veredito": (audit or {}).get("verdict"), "numeros_conferidos": (audit or {}).get(
                    "checked_numbers", 0), "ressalvas": (audit or {}).get("reasons", [])},
                "riscos": {"categorias": evaluate.risk_categories(record, contract.strip(text)),
                           "itens": len((record or {}).get("riscos_identificados") or [])},
                "consistencia": {"problemas": evaluate.consistency(record, problems, audit)},
                "debate": evaluate.debate(meeting, turn_texts, corrections) if a["mode"] == "conselho" else None,
                "fontes": message.get("sources") or [],
            }
            for h in (record or {}).get("hipoteses", []):
                h.pop("_dias", None)
            for i, h in enumerate((record or {}).get("hipoteses", [])):
                self.conn.execute(
                    "INSERT OR IGNORE INTO lab_hypotheses (id, analysis_id, experiment_id, user_id, ordinal, statement, "
                    "probability, due_on, check_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), a["id"], a["experiment_id"], a["user_id"], i, h["afirmacao"], h["probabilidade"],
                     h["data"], json.dumps(h["check"]) if h["check"] else None, utcnow()))
        self.conn.execute(
            "UPDATE lab_analyses SET status = ?, final_text = ?, record_json = ?, record_status = ?, evaluation_json = ?, "
            "usage_json = ?, finished_at = ? WHERE id = ? AND finished_at IS NULL",
            (status, text, json.dumps(record, ensure_ascii=False) if record else None, record_status,
             json.dumps(evaluation, ensure_ascii=False, default=str) if evaluation else None,
             json.dumps(usage), utcnow(), a["id"]))

    # ---------------------------------------------------------------- acompanhamento

    def resolve_due(self, today: date | None = None) -> int:
        """Hipóteses vencidas com condição: conferidas nas séries oficiais (mesma regra das Convicções)."""
        today = today or self.today()
        done = 0
        for r in self.conn.execute("SELECT * FROM lab_hypotheses WHERE status = 'aberta' AND check_json IS NOT NULL "
                                   "AND due_on <= ?", (today.isoformat(),)).fetchall():
            check, due = json.loads(r["check_json"]), date.fromisoformat(r["due_on"])
            observed, after = convictions._observe(self.conn, check, due)
            late = (today - due).days > convictions.GRACE_DAYS
            if observed and (after or late):
                ok = convictions.OPS[check["op"]](Decimal(observed["value"]), Decimal(check["value"]))
                status, note = ("aconteceu" if ok else "nao_aconteceu"), None
            elif late:
                status, note = "indeterminada", "A fonte não tem dado utilizável para a data; fica fora da medição."
            else:
                continue
            self.conn.execute("UPDATE lab_hypotheses SET status = ?, observed_json = ?, resolved_by = 'dados', "
                              "resolved_at = ?, note = ? WHERE id = ? AND status = 'aberta'",
                              (status, json.dumps(observed) if observed else None, utcnow(), note, r["id"]))
            done += 1
        return done

    def resolve_manual(self, user_id: str, hyp_id: str, outcome: str, note: str) -> dict:
        r = self.conn.execute("SELECT * FROM lab_hypotheses WHERE id = ? AND user_id = ?", (hyp_id, user_id)).fetchone()
        if not r:
            raise LookupError("Hipótese inexistente.")
        if outcome not in ("aconteceu", "nao_aconteceu", "indeterminada"):
            raise LabError("Resultado: aconteceu, nao_aconteceu ou indeterminada.")
        if r["status"] != "aberta":
            raise LabError("Hipótese já conferida: o registro original não muda.")
        if r["check_json"]:
            raise LabError("Esta hipótese tem condição verificável: o Lastro confere nas séries oficiais.")
        if date.fromisoformat(r["due_on"]) > self.today():
            raise LabError("A data da hipótese ainda não chegou.")
        self.conn.execute("UPDATE lab_hypotheses SET status = ?, resolved_by = 'pessoa', resolved_at = ?, note = ? "
                          "WHERE id = ? AND status = 'aberta'", (outcome, utcnow(), (note or "")[:500], hyp_id))
        return dict(self.conn.execute("SELECT * FROM lab_hypotheses WHERE id = ?", (hyp_id,)).fetchone())

    def checkpoints(self, today: date | None = None) -> int:
        """Reavaliações vencidas: grava o retrato das métricas do experimento naquele dia. Hipótese com prazo até a
        reavaliação ainda sem dado deixa a reavaliação 'pendente' (tenta de novo) até a tolerância da fonte."""
        today = today or self.today()
        done = 0
        rows = self.conn.execute(
            "SELECT c.*, e.status AS exp_status FROM lab_checkpoints c JOIN lab_experiments e ON e.id = c.experiment_id "
            "WHERE c.status != 'feita' AND c.due_on <= ?", (today.isoformat(),)).fetchall()
        for c in rows:
            if c["exp_status"] not in ("concluido", "incompleto"):
                continue
            waiting = self.conn.execute("SELECT COUNT(*) FROM lab_hypotheses WHERE experiment_id = ? AND status = 'aberta' "
                                        "AND due_on <= ?", (c["experiment_id"], c["due_on"])).fetchone()[0]
            late = (today - date.fromisoformat(c["due_on"])).days > convictions.GRACE_DAYS
            report = self.pairs(c["user_id"], c["experiment_id"])
            evaluation = {"em": today.isoformat(), "dias": c["days"], "pares": report,
                          "hipoteses_sem_resultado": waiting}
            if waiting and not late:
                self.conn.execute("UPDATE lab_checkpoints SET status = 'pendente', evaluation_json = ? WHERE id = ?",
                                  (json.dumps(evaluation, ensure_ascii=False), c["id"]))
                continue
            self.conn.execute("UPDATE lab_checkpoints SET status = 'feita', evaluation_json = ?, done_at = ? WHERE id = ?",
                              (json.dumps(evaluation, ensure_ascii=False), utcnow(), c["id"]))
            self._journal(c["user_id"], c["experiment_id"], "resultado_observado", f"reavaliacao:{c['id']}",
                          {"reavaliacao_dias": c["days"], "data": today.isoformat(), "comparacoes": report,
                           "hipoteses": self._hypotheses(c["experiment_id"]),
                           "aprendizado": self._learning(report),
                           "aviso": "Resultado observado das hipóteses da IA. Não é decisão nem operação sua."})
            done += 1
        return done

    def tick(self) -> dict:
        return {"fechadas": self.advance(), "conferidas": self.resolve_due(), "reavaliacoes": self.checkpoints()}

    async def run_forever(self, interval: int = 60) -> None:
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — o laço do Laboratório nunca derruba o app
                log.exception("ciclo do Laboratório falhou")
            await asyncio.sleep(interval)

    # ---------------------------------------------------------------- Diário do Laboratório

    def _journal(self, user_id: str, exp_id: str, kind: str, ref: str, payload: dict) -> dict | None:
        """Acrescenta ao Diário do Laboratório (encadeado por SHA-256, como o Diário de Decisões). Idempotente por ref."""
        if self.conn.execute("SELECT 1 FROM lab_journal WHERE user_id = ? AND ref = ?", (user_id, ref)).fetchone():
            return None
        last = self.conn.execute("SELECT seq, sha256 FROM lab_journal WHERE user_id = ? ORDER BY seq DESC LIMIT 1",
                                 (user_id,)).fetchone()
        now, entry_id, body = utcnow(), str(uuid.uuid4()), diary.canonical(payload)
        sha = diary._sha(last["sha256"] if last else None,
                         diary.canonical({"kind": kind, "experiment_id": exp_id, "ref": ref, "created_at": now,
                                          "payload": body}))
        self.conn.execute("INSERT INTO lab_journal (id, user_id, seq, experiment_id, kind, ref, payload_json, created_at, "
                          "prev_sha256, sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (entry_id, user_id, (last["seq"] + 1) if last else 1, exp_id, kind, ref, body, now,
                           last["sha256"] if last else None, sha))
        return {"id": entry_id, "kind": kind}

    def _journal_analysis(self, exp_id: str) -> None:
        e = self.conn.execute("SELECT * FROM lab_experiments WHERE id = ?", (exp_id,)).fetchone()
        analyses = [dict(a) for a in self.conn.execute("SELECT * FROM lab_analyses WHERE experiment_id = ? ORDER BY "
                                                       "repetition, mode", (exp_id,))]

        def side(mode: str) -> list[dict]:
            out = []
            for a in analyses:
                if a["mode"] != mode:
                    continue
                rec = json.loads(a["record_json"]) if a["record_json"] else {}
                ev = json.loads(a["evaluation_json"]) if a["evaluation_json"] else {}
                out.append({"repeticao": a["repetition"], "status": a["status"], "conclusao": rec.get("conclusao"),
                            "hipoteses": [h["afirmacao"] for h in rec.get("hipoteses", [])],
                            "riscos": rec.get("riscos_identificados", []),
                            "evidencias": rec.get("fontes", []) or [s.get("label") or s.get("url") for s in ev.get("fontes", [])],
                            "divergencias": (ev.get("debate") or {}).get("divergencias_finais", [])})
            return out
        self._journal(e["user_id"], exp_id, "analise_ia", f"analise:{exp_id}",
                      {"problema": e["question"], "categoria": e["category"], "data_de_corte": e["as_of"],
                       "comparavel": bool(e["comparable"]), "individual": side("individual"),
                       "coletiva": side("conselho"), "status": e["status"],
                       "aviso": "Análise produzida por IA no Laboratório. Recomendação não é decisão: só existe decisão "
                                "quando você a registra no Diário de Decisões, e operação só quando você a executa."})

    def link_decision(self, user_id: str, exp_id: str, decision_id: str) -> dict:
        """A pessoa registrou uma decisão no Diário a partir deste experimento: o vínculo fica no Diário do Laboratório."""
        self._row(user_id, exp_id)
        if not diary.decision(self.conn, user_id, decision_id):
            raise LookupError("Decisão inexistente.")
        self._journal(user_id, exp_id, "decisao_vinculada", f"decisao:{exp_id}:{decision_id}",
                      {"decisao_id": decision_id, "aviso": "Decisão registrada pela pessoa no Diário de Decisões."})
        return self.experiment(user_id, exp_id)

    def journal(self, user_id: str, limit: int = 100) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM lab_journal WHERE user_id = ? ORDER BY seq DESC LIMIT ?",
                                 (user_id, limit)).fetchall()
        return [{**{k: r[k] for k in ("id", "seq", "experiment_id", "kind", "created_at", "sha256", "prev_sha256")},
                 "payload": json.loads(r["payload_json"])} for r in rows]

    # ---------------------------------------------------------------- Radar

    def propose_from_radar(self, user_id: str, *, opportunity_id: str, summary: str, category: str = "juros_e_inflacao") -> dict | None:
        """O Radar viu algo relevante: propõe (ou executa, se a pessoa permitiu) um experimento, com limites."""
        cfg = self.settings(user_id)
        if cfg["automation"] == "desligada":
            return None
        week = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        recent = self.conn.execute("SELECT COUNT(*) FROM lab_experiments WHERE user_id = ? AND origin = 'radar' AND "
                                   "created_at >= ?", (user_id, week)).fetchone()[0]
        if recent >= cfg["max_per_week"]:
            log.info("Laboratório: limite semanal de experimentos automáticos atingido")
            return None
        if cfg["monthly_token_budget"] and self.tokens_this_month(user_id) >= cfg["monthly_token_budget"]:
            log.info("Laboratório: orçamento mensal de tokens atingido")
            return None
        question = (f"O Radar do Lastro registrou: {summary.strip()[:600]} Considerando a situação da pessoa, o que "
                    "isso muda para as finanças dela nos próximos meses, e o que seria prudente observar?")
        return self.create(user_id, question=question, category=category if category in CATEGORIES else "outros",
                           repetitions=cfg["repetitions"], origin="radar", origin_ref=opportunity_id,
                           dedupe_key=f"radar:{opportunity_id}", start=cfg["automation"] == "executar")

    def tokens_this_month(self, user_id: str) -> int:
        start = self.today().replace(day=1).isoformat()
        total = 0
        for r in self.conn.execute("SELECT a.usage_json FROM lab_analyses a WHERE a.user_id = ? AND a.created_at >= ?",
                                   (user_id, start)):
            total += int((json.loads(r[0]) if r[0] else {}).get("tokens") or 0)
        for r in self.conn.execute("SELECT usage_json FROM lab_reviews WHERE user_id = ? AND created_at >= ?",
                                   (user_id, start)):
            total += int((json.loads(r[0]) if r[0] else {}).get("tokens") or 0)
        return total

    # ---------------------------------------------------------------- utilidade (avaliação às cegas e da pessoa)

    async def judge(self, user_id: str, exp_id: str, repetition: int) -> dict:
        """Avaliação de utilidade por IA às cegas: rótulos A/B sorteados, critérios explícitos, notas só com trecho
        literal conferido. É um avaliador entre outros, não a verdade."""
        self._row(user_id, exp_id)
        texts = self._final_texts(exp_id, repetition)
        if set(texts) != {"individual", "conselho"}:
            raise LabError("As duas análises desta repetição precisam estar concluídas.")
        order = ["individual", "conselho"]
        if secrets.randbelow(2):
            order.reverse()
        blind = {"A": order[0], "B": order[1]}
        prompt = (f"Questão:\n{self._row(user_id, exp_id)['question']}\n\n"
                  + "\n\n".join(f"### Análise {label}\n{texts[mode]}" for label, mode in blind.items()))
        request = {"op": "ephemeral", "role": "auditor", "mode": "laboratorio_juiz", "text": prompt, "effort": "medium",
                   "lab": {"research": False}, **store.ai_route(self.conn, "auditor")}
        final: dict = {}
        async for event in self.orchestrator.stream(request):
            if event.get("type") in ("done", "error"):
                final = event
        if final.get("type") != "done":
            raise LabError(f"O avaliador não respondeu ({final.get('message') or 'falha'}).")
        found = contract.BLOCK.findall(final.get("text") or "")
        try:
            raw = json.loads(found[-1]) if found else {}
        except json.JSONDecodeError:
            raw = {}
        scores = evaluate.utility_scores({"A": raw.get("A"), "B": raw.get("B")}, {k: texts[v] for k, v in blind.items()})
        usage = final.get("usage") or {}
        payload = {"por_modo": {blind[k]: v for k, v in scores.items()}, "observacao": str(raw.get("observacao") or "")[:300],
                   "sem_resposta_valida": not raw}
        self.conn.execute("INSERT INTO lab_reviews (id, experiment_id, user_id, repetition, reviewer, blind_json, "
                          "scores_json, usage_json, created_at) VALUES (?,?,?,?, 'ia', ?,?,?,?)",
                          (str(uuid.uuid4()), exp_id, user_id, repetition, json.dumps(blind),
                           json.dumps(payload, ensure_ascii=False),
                           json.dumps({"tokens": int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)}),
                           utcnow()))
        return self.experiment(user_id, exp_id)

    def human_review(self, user_id: str, exp_id: str, repetition: int, scores: dict, note: str = "") -> dict:
        self._row(user_id, exp_id)
        clean = {}
        for mode in ("individual", "conselho"):
            crit = {}
            for c in evaluate.UTILITY_CRITERIA:
                v = (scores.get(mode) or {}).get(c)
                if v is None:
                    continue
                if v not in (0, 1, 2):
                    raise LabError("Notas de 0 a 2.")
                crit[c] = {"nota": v}
            clean[mode] = {"criterios": crit, "descartados": [], "total": sum(x["nota"] for x in crit.values()),
                           "max": 2 * len(crit)}
        if not any(v["criterios"] for v in clean.values()):
            raise LabError("Dê ao menos uma nota.")
        self.conn.execute("INSERT INTO lab_reviews (id, experiment_id, user_id, repetition, reviewer, scores_json, "
                          "created_at) VALUES (?,?,?,?, 'pessoa', ?, ?)",
                          (str(uuid.uuid4()), exp_id, user_id, repetition,
                           json.dumps({"por_modo": clean, "observacao": (note or "")[:500]}, ensure_ascii=False), utcnow()))
        return self.experiment(user_id, exp_id)

    def _final_texts(self, exp_id: str, repetition: int) -> dict[str, str]:
        return {r["mode"]: contract.strip(r["final_text"]) for r in self.conn.execute(
            "SELECT mode, final_text FROM lab_analyses WHERE experiment_id = ? AND repetition = ? AND status = 'concluida'",
            (exp_id, repetition))}

    # ---------------------------------------------------------------- leitura

    def _row(self, user_id: str, exp_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM lab_experiments WHERE id = ? AND user_id = ?", (exp_id, user_id)).fetchone()
        if not row:
            raise LookupError("Experimento inexistente.")
        return row

    def _hypotheses(self, exp_id: str) -> list[dict]:
        out = []
        for r in self.conn.execute("SELECT h.*, a.mode, a.repetition FROM lab_hypotheses h JOIN lab_analyses a ON "
                                   "a.id = h.analysis_id WHERE h.experiment_id = ? ORDER BY a.repetition, a.mode, "
                                   "h.ordinal", (exp_id,)):
            d = {k: r[k] for k in r.keys() if k not in ("check_json", "observed_json", "user_id")}
            d["check"] = json.loads(r["check_json"]) if r["check_json"] else None
            d["observed"] = json.loads(r["observed_json"]) if r["observed_json"] else None
            d["brier"] = (f"{round(convictions.brier(Decimal(r['probability']), r['status']), 4).normalize():f}"
                          if r["probability"] and r["status"] in convictions.RESOLVED else None)
            out.append(d)
        return out

    def pairs(self, user_id: str, exp_id: str) -> list[dict]:
        """Uma comparação por repetição (mesmo dossiê): calibração conferida e utilidade registrada."""
        exp = self._row(user_id, exp_id)
        hyps = self._hypotheses(exp_id)
        reviews = self._reviews(exp_id)
        out = []
        for rep in range(1, exp["repetitions"] + 1):
            by = {m: [h for h in hyps if h["repetition"] == rep and h["mode"] == m] for m in ("individual", "conselho")}
            item = {"repeticao": rep,
                    "calibracao": evaluate.pair_outcome(by["individual"], by["conselho"]) if exp["comparable"]
                    else "nao_comparavel",
                    "brier": {m: evaluate.brier_summary(v) for m, v in by.items()}}
            for who in ("ia", "pessoa"):
                latest = next((r for r in reviews if r["repetition"] == rep and r["reviewer"] == who), None)
                if latest:
                    t = {m: latest["scores"]["por_modo"].get(m, {}).get("total", 0) for m in ("individual", "conselho")}
                    item[f"utilidade_{who}"] = ("empate" if t["individual"] == t["conselho"]
                                                else max(t, key=t.get))
            out.append(item)
        return out

    def _reviews(self, exp_id: str) -> list[dict]:
        return [{"id": r["id"], "repetition": r["repetition"], "reviewer": r["reviewer"], "created_at": r["created_at"],
                 "blind": json.loads(r["blind_json"]) if r["blind_json"] else None,
                 "scores": json.loads(r["scores_json"])}
                for r in self.conn.execute("SELECT * FROM lab_reviews WHERE experiment_id = ? ORDER BY created_at DESC",
                                           (exp_id,))]

    @staticmethod
    def _learning(pairs: list[dict]) -> str:
        cal = [p["calibracao"] for p in pairs]
        if all(c in ("sem_avaliacao", "nao_comparavel") for c in cal):
            return "Ainda sem hipótese conferida com probabilidade: nada a concluir sobre calibração."
        counts = {k: cal.count(k) for k in ("conselho", "individual", "empate")}
        return (f"Calibração nesta reavaliação: Conselho melhor em {counts['conselho']}, Bento sozinho em "
                f"{counts['individual']}, empate em {counts['empate']} repetição(ões). Um experimento isolado não "
                "basta para generalizar.")

    def experiment(self, user_id: str, exp_id: str) -> dict:
        e = self._row(user_id, exp_id)
        snap = json.loads(e["snapshot_json"])
        analyses = []
        for a in self.conn.execute("SELECT * FROM lab_analyses WHERE experiment_id = ? ORDER BY repetition, mode", (exp_id,)):
            analyses.append({**{k: a[k] for k in ("id", "mode", "repetition", "conversation_id", "run_id", "status",
                                                  "record_status", "created_at", "finished_at")},
                             "text": contract.strip(a["final_text"]) if a["final_text"] else None,
                             "record": json.loads(a["record_json"]) if a["record_json"] else None,
                             "evaluation": json.loads(a["evaluation_json"]) if a["evaluation_json"] else None,
                             "usage": json.loads(a["usage_json"]) if a["usage_json"] else None})
        checkpoints = [{**{k: c[k] for k in ("id", "days", "due_on", "status", "done_at")},
                        "evaluation": json.loads(c["evaluation_json"]) if c["evaluation_json"] else None}
                       for c in self.conn.execute("SELECT * FROM lab_checkpoints WHERE experiment_id = ? ORDER BY days",
                                                  (exp_id,))]
        journal = [j for j in self.journal(user_id, 500) if j["experiment_id"] == exp_id]
        return {**{k: e[k] for k in ("id", "origin", "origin_ref", "category", "question", "status", "as_of",
                                     "repetitions", "created_at", "started_at", "finished_at", "snapshot_sha256")},
                "simulated": bool(e["simulated"]), "comparable": bool(e["comparable"]), "research": bool(e["research"]),
                "followups": json.loads(e["followups_json"]), "snapshot": snap, "analyses": analyses,
                "hypotheses": self._hypotheses(exp_id), "checkpoints": checkpoints, "reviews": self._reviews(exp_id),
                "pairs": self.pairs(user_id, exp_id), "journal": journal}

    def listing(self, user_id: str, *, category: str | None = None, since: str | None = None,
                status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM lab_experiments WHERE user_id = ?", [user_id]
        if category:
            sql, args = sql + " AND category = ?", [*args, category]
        if since:
            sql, args = sql + " AND created_at >= ?", [*args, since]
        if status:
            sql, args = sql + " AND status = ?", [*args, status]
        out = []
        for e in self.conn.execute(sql + " ORDER BY created_at DESC LIMIT 200", args):
            hyp = self.conn.execute("SELECT status, COUNT(*) FROM lab_hypotheses WHERE experiment_id = ? GROUP BY status",
                                    (e["id"],)).fetchall()
            out.append({**{k: e[k] for k in ("id", "origin", "category", "question", "status", "as_of", "repetitions",
                                             "created_at", "finished_at")},
                        "simulated": bool(e["simulated"]), "comparable": bool(e["comparable"]),
                        "hypotheses": {r[0]: r[1] for r in hyp}, "pairs": self.pairs(user_id, e["id"])})
        return out

    def dashboard(self, user_id: str, *, category: str | None = None, since: str | None = None) -> dict:
        """Métricas agregadas com amostra e incerteza. Sem amostra válida, sem porcentagem e sem vencedor."""
        exps = self.listing(user_id, category=category, since=since)
        closed = [e for e in exps if e["status"] in ("concluido", "incompleto")]
        ids = [e["id"] for e in closed]
        q = ",".join("?" * len(ids)) or "''"
        analyses = [dict(a) for a in self.conn.execute(
            f"SELECT a.*, e.comparable FROM lab_analyses a JOIN lab_experiments e ON e.id = a.experiment_id "
            f"WHERE a.experiment_id IN ({q}) AND a.status = 'concluida'", ids)]
        hyps = [dict(h) for h in self.conn.execute(
            f"SELECT h.*, a.mode, e.comparable FROM lab_hypotheses h JOIN lab_analyses a ON a.id = h.analysis_id "
            f"JOIN lab_experiments e ON e.id = h.experiment_id WHERE h.experiment_id IN ({q})", ids)]
        per_mode = {}
        for mode in ("individual", "conselho"):
            mine = [a for a in analyses if a["mode"] == mode]
            evs = [json.loads(a["evaluation_json"]) for a in mine if a["evaluation_json"]]
            usage = [json.loads(a["usage_json"]) for a in mine if a["usage_json"]]
            passed = sum(1 for ev in evs if ev["factual"]["veredito"] == auditor.PASSA)
            risk_counts = [len(ev["riscos"]["categorias"]) for ev in evs]
            tokens = [u.get("tokens") for u in usage if u.get("tokens")]
            secs = [u.get("segundos") for u in usage if u.get("segundos") is not None]
            per_mode[mode] = {
                "analises": len(mine),
                "factual_sem_ressalva": evaluate.proportion(passed, len(evs)),
                "registro_valido": evaluate.proportion(sum(1 for a in mine if a["record_status"] == "ok"), len(mine)),
                "calibracao": evaluate.brier_summary([h for h in hyps if h["mode"] == mode and h["comparable"]]),
                "categorias_de_risco_media": round(sum(risk_counts) / len(risk_counts), 2) if risk_counts else None,
                "problemas_de_consistencia": sum(len(ev["consistencia"]["problemas"]) for ev in evs),
                "erros_apontados_pelo_auditor": sum(1 for ev in evs if ev["factual"]["veredito"] in (auditor.RESSALVAS,
                                                                                                      auditor.REPROVA)),
                "tokens_medio": round(sum(tokens) / len(tokens)) if tokens else None, "tokens_amostra": len(tokens),
                "segundos_medio": round(sum(secs) / len(secs), 1) if secs else None,
                "hipoteses": sum(1 for h in hyps if h["mode"] == mode),
            }
        pair_list = [(e, p) for e in closed for p in e["pairs"]]
        cal = [p["calibracao"] for _, p in pair_list]
        by_category = {}
        for e, p in pair_list:
            slot = by_category.setdefault(e["category"], {"conselho": 0, "individual": 0, "empate": 0, "sem_avaliacao": 0})
            key = p["calibracao"] if p["calibracao"] in slot else "sem_avaliacao"
            slot[key] += 1
        utility = {}
        for who in ("ia", "pessoa"):
            res = [p.get(f"utilidade_{who}") for _, p in pair_list if p.get(f"utilidade_{who}")]
            utility[who] = evaluate.verdict(res.count("conselho"), res.count("individual"), res.count("empate"))
        debates = [json.loads(a["evaluation_json"]).get("debate") for a in analyses
                   if a["mode"] == "conselho" and a["evaluation_json"]]
        debates = [d for d in debates if d]
        return {
            "experimentos": len(exps), "concluidos": sum(e["status"] == "concluido" for e in exps),
            "incompletos": sum(e["status"] == "incompleto" for e in exps),
            "em_execucao": sum(e["status"] == "executando" for e in exps),
            "propostos": sum(e["status"] == "proposto" for e in exps),
            "nao_comparaveis": sum(not e["comparable"] for e in exps),
            "avaliaveis": sum(1 for e in closed if any(p["calibracao"] in ("conselho", "individual", "empate")
                                                       for p in e["pairs"])),
            "pendentes": sum(1 for h in hyps if h["status"] == "aberta"),
            "por_modo": per_mode,
            "calibracao": evaluate.verdict(cal.count("conselho"), cal.count("individual"), cal.count("empate")),
            "utilidade": utility, "por_categoria": by_category,
            "debate": {"reunioes": len(debates),
                       "com_mudanca_de_posicao": sum(1 for d in debates if d["mudancas_de_posicao"]),
                       "com_correcao_apos_auditor": sum(1 for d in debates if d["correcoes_apos_auditor"]),
                       "com_divergencia_preservada": sum(1 for d in debates if d["divergencias_finais"]),
                       "falas_repetitivas": sum(d["falas_repetitivas"] for d in debates)},
            "evolucao": self._evolution(hyps),
        }

    @staticmethod
    def _evolution(hyps: list[dict]) -> list[dict]:
        """Brier acumulado por modo, na ordem em que as hipóteses foram conferidas (só experimentos comparáveis)."""
        resolved = sorted((h for h in hyps if h["comparable"] and h["probability"] and h["status"] in convictions.RESOLVED),
                          key=lambda h: h["resolved_at"] or "")
        out, acc = [], {"individual": [], "conselho": []}
        for h in resolved:
            acc[h["mode"]].append(convictions.brier(Decimal(h["probability"]), h["status"]))
            out.append({"data": (h["resolved_at"] or "")[:10], "modo": h["mode"],
                        **{m: (f"{round(sum(v) / len(v), 4):f}" if v else None) for m, v in acc.items()},
                        **{f"n_{m}": len(v) for m, v in acc.items()}})
        return out
