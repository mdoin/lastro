# SPDX-License-Identifier: AGPL-3.0-or-later
"""Laboratório do Conselho: independência e equivalência dos modos, bloqueio de dados futuros, hipóteses imutáveis,
reavaliações, idempotência, métricas, isolamento entre pessoas, recuperação, falhas e dados insuficientes.

O provedor de IA é simulado (as falas abaixo são respostas do provedor falso, não do Lastro); orquestrador, banco,
Auditor, contrato e avaliação são os reais. Os cenários com resultado conhecido usam séries de mercado inseridas
pelo teste — nada disso vai para o painel de produção.
"""
import asyncio
import json
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import auth, store
from app.web import Settings, create_app
from lab import contract, dossier, evaluate
from lab.service import Lab, LabError
from mentor.session import session_spec

from .test_council import script_factory
from .test_team import TODAY, FakeRuntime, conn, done, drain, orch  # noqa: F401

QUESTION = "Com a Selic alta, vale alongar a renda fixa agora ou manter tudo no pós-fixado?"
SOLO_MARK, COUNCIL_MARK = "MARCA-SOLO-7731", "MARCA-CONSELHO-5512"


def market(conn, series, ref, value, fetched="2026-10-01T00:00:00Z"):
    conn.execute("INSERT OR REPLACE INTO market_data (source, series_id, reference_date, value, unit, label, fetched_at) "
                 "VALUES ('bcb_sgs', ?, ?, ?, '% a.a.', 'x', ?)", (series, ref, value, fetched))


def record(hyps=(), **extra) -> str:
    body = {"cenario": "Renda fixa com juros altos", "horizonte_dias": 120, "hipotese": "Juros seguem altos",
            "resultado_esperado": "Selic estável", "metricas_observaveis": ["selic_meta"],
            "riscos_identificados": ["Risco de liquidez no resgate antecipado", "Marcação a mercado"],
            "premissas": ["Renda estável"], "fontes": ["dossiê do Laboratório"], "nivel_confianca": "media",
            "condicoes_invalidacao": ["Copom corta juros"], "conclusao": "Manter parte no pós-fixado.",
            "dados_insuficientes": False, "sem_hipotese_motivo": None, "hipoteses": list(hyps)} | extra
    return "\n\n```json\n" + json.dumps(body, ensure_ascii=False) + "\n```"


def hyp(p, cond="selic_meta < 14", due="2027-01-31"):
    return {"afirmacao": "A meta da Selic estará abaixo de 14% ao ano.", "probabilidade": p, "data": due, "condicao": cond}


def lab_script(solo=None, council=None, fail_solo=False):
    base = script_factory(synth="## Conclusão\nPriorizar o pós-fixado.\n\n## Participação\n- @lia — reserva\n\n"
                                "## Divergências\n- @caio × @lia e @rui. " + COUNCIL_MARK + (council or record()))

    def script(role, mode, prompt, n):
        if mode == "laboratorio_individual":
            if fail_solo:
                return [{"type": "error", "kind": "auth", "message": "provedor recusou"}]
            return done("## Conclusão\nManter no pós-fixado. " + SOLO_MARK + (solo or record()))
        return base(role, mode, prompt, n)
    return script


def run_lab(conn, script, *, user=store.OWNER, **kw):
    rt = FakeRuntime(script)
    o = orch(conn, rt)
    lab = Lab(conn, o, today=lambda: TODAY, app_version="teste")
    exp = lab.create(user, question=kw.pop("question", QUESTION), category="renda_fixa", **kw)
    asyncio.run(drain(o))
    lab.advance()
    return lab, rt, lab.experiment(user, exp["id"])


# independência e equivalência ----------------------------------------------------------------------------------------
def test_modes_get_the_same_dossier_and_never_see_each_other(conn):
    market(conn, "selic_meta", "2026-10-20", "15")
    lab, rt, exp = run_lab(conn, lab_script())
    assert exp["status"] == "concluido" and {a["mode"] for a in exp["analyses"]} == {"individual", "conselho"}
    text = dossier.render(QUESTION, exp["snapshot"]["dossie"])
    solo = [r for r in rt.requests if r.get("mode") == "laboratorio_individual"]
    council = [r for r in rt.requests if r.get("mode") != "laboratorio_individual"]
    assert len(solo) == 1 and solo[0]["role"] == "mentor"  # sozinho: nenhuma outra chamada na execução individual
    assert text in solo[0]["text"] and all(text in r["text"] for r in council if r.get("mode") == "conselho_parecer")
    assert "Meta da taxa Selic" in text and "15" in text
    assert not any(SOLO_MARK in r["text"] for r in council) and COUNCIL_MARK not in solo[0]["text"]
    assert not any("PONTO-" in r["text"] for r in solo)  # nada dos pareceres chega ao Bento sozinho
    assert all(r.get("lab") == {"research": False} for r in rt.requests)
    assert contract.SUFFIX.strip()[:40] in solo[0]["text"]
    assert any(contract.SUFFIX.strip()[:40] in r["text"] for r in council if r.get("mode") == "conselho_sintese")
    assert not any(contract.SUFFIX.strip()[:40] in r["text"] for r in council if r.get("mode") == "conselho_parecer")
    # conversas do Laboratório não aparecem para a equipe; nada vira Convicção nem rascunho do Diário
    visible = {c["id"] for c in store.list_user_conversations(conn, store.OWNER)}
    assert not visible & {a["conversation_id"] for a in exp["analyses"]}
    assert conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM decision_drafts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM council_records").fetchone()[0] == 0
    # controle experimental registrado
    snap = exp["snapshot"]
    assert snap["dossie_sha256"] == dossier.sha256(snap["dossie"]) and snap["prompts"] and snap["modelos"]
    assert snap["agentes"]["conselho"][0] == "mentor" and snap["motor_financeiro"]
    assert all(a["usage"] and "chamadas" in a["usage"] for a in exp["analyses"])
    council_eval = next(a for a in exp["analyses"] if a["mode"] == "conselho")["evaluation"]
    assert council_eval["debate"]["falas"] >= 1
    assert exp["journal"] and exp["journal"][0]["kind"] == "analise_ia"
    assert "não é decisão" in exp["journal"][0]["payload"]["aviso"]


def test_lab_sessions_get_identical_tools_and_no_live_owner_data(tmp_path):
    names = lambda role, research: {t.name for t in session_spec(role=role, workdir=tmp_path,  # noqa: E731
                                                                    lab={"research": research}).tools}
    for role in ("mentor", "planejador", "riscos", "economista", "auditor"):
        assert names(role, False) == {"calcular"}
        assert names(role, True) == {"calcular", "pesquisar_web"}
    normal = {t.name for t in session_spec(role="mentor", workdir=tmp_path).tools}
    assert "situacao_atual" in normal  # fora do Laboratório nada muda


# bloqueio de dados futuros -------------------------------------------------------------------------------------------
def test_simulated_date_blocks_future_data_and_is_flagged_not_comparable(conn):
    market(conn, "selic_meta", "2026-06-10", "14.75")
    market(conn, "selic_meta", "2026-09-20", "15")  # depois da data simulada: não pode aparecer
    built = dossier.build(conn, store.OWNER, as_of=date(2026, 7, 1), today=TODAY)
    assert [m["valor"] for m in built["dossie"]["mercado"]] == ["14.75"]
    assert built["dossie"]["retrato_financeiro"] is None  # o retrato foi registrado depois da data simulada
    assert built["comparavel"] is False and any("treinamento" in n for n in built["avisos"])
    lab = Lab(conn, None, today=lambda: TODAY)
    with pytest.raises(LabError):
        lab.create(store.OWNER, question=QUESTION, as_of="2026-07-01", research=True, start=False)
    with pytest.raises(LabError):
        lab.create(store.OWNER, question=QUESTION, as_of=(TODAY + timedelta(days=1)).isoformat(), start=False)
    exp = lab.create(store.OWNER, question=QUESTION, as_of="2026-07-01", start=False)
    assert exp["comparable"] is False and exp["snapshot"]["comparabilidade"]["motivos"]


# hipóteses, reavaliações e resultados conhecidos ---------------------------------------------------------------------
@pytest.mark.parametrize("solo_p, council_p, observed, expected", [
    (0.9, 0.2, "13.5", "individual"),   # o Bento sozinho acerta (a Selic caiu e só ele apostou nisso)
    (0.2, 0.9, "13.5", "conselho"),     # o Conselho acerta
    (0.9, 0.9, "15", "empate"),          # ambos erram com a mesma confiança
])
def test_known_outcomes_are_measured_by_brier(conn, solo_p, council_p, observed, expected):
    lab, _, exp = run_lab(conn, lab_script(solo=record([hyp(solo_p)]), council=record([hyp(council_p)])),
                          followups=[30, 120])
    assert len(exp["hypotheses"]) == 2 and all(h["status"] == "aberta" for h in exp["hypotheses"])
    market(conn, "selic_meta", "2027-01-31", observed)
    market(conn, "selic_meta", "2027-02-05", observed)  # a fonte já publicou depois da data
    assert lab.resolve_due(date(2027, 2, 6)) == 2
    assert lab.resolve_due(date(2027, 2, 6)) == 0  # idempotente
    exp = lab.experiment(store.OWNER, exp["id"])
    assert exp["pairs"][0]["calibracao"] == expected
    if expected == "empate":
        assert all(h["status"] == "nao_aconteceu" and h["brier"] == "0.81" for h in exp["hypotheses"])


def test_no_testable_hypothesis_means_no_winner(conn):
    none = record(hipoteses=[], sem_hipotese_motivo="Não há variável observável que decida a questão.")
    lab, _, exp = run_lab(conn, lab_script(solo=none, council=none))
    assert exp["pairs"][0]["calibracao"] == "sem_avaliacao"
    board = lab.dashboard(store.OWNER)
    assert board["calibracao"]["vencedor"] is None and "insuficiente" in board["calibracao"]["texto"]
    assert board["por_modo"]["conselho"]["factual_sem_ressalva"]["pct"] is None  # amostra pequena: sem porcentagem


def test_hypotheses_are_frozen_and_resolved_once(conn):
    lab, _, exp = run_lab(conn, lab_script(solo=record([hyp(0.6), hyp(0.5, cond="manual", due="2026-12-01")])))
    h = next(x for x in exp["hypotheses"] if x["check"])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE lab_hypotheses SET probability = '0.99' WHERE id = ?", (h["id"],))
    manual = next(x for x in exp["hypotheses"] if not x["check"])
    with pytest.raises(LabError):  # a data ainda não chegou
        lab.resolve_manual(store.OWNER, manual["id"], "aconteceu", "")
    late = Lab(conn, None, today=lambda: date(2026, 12, 2))
    late.resolve_manual(store.OWNER, manual["id"], "aconteceu", "conferi")
    with pytest.raises(LabError):
        late.resolve_manual(store.OWNER, manual["id"], "nao_aconteceu", "")
    with pytest.raises(LabError):  # condição verificável: só os dados conferem
        late.resolve_manual(store.OWNER, h["id"], "aconteceu", "")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE lab_analyses SET final_text = 'outra coisa' WHERE experiment_id = ?", (exp["id"],))


def test_checkpoints_wait_for_data_then_record_once(conn):
    lab, _, exp = run_lab(conn, lab_script(solo=record([hyp(0.7, due="2026-11-20")]),
                                           council=record([hyp(0.4, due="2026-11-20")])), followups=[30, 90])
    assert [c["days"] for c in exp["checkpoints"]] == [30, 90]
    assert lab.checkpoints(date(2026, 11, 27)) == 0  # hipótese vencida sem dado: reavaliação pendente
    assert lab.experiment(store.OWNER, exp["id"])["checkpoints"][0]["status"] == "pendente"
    market(conn, "selic_meta", "2026-11-20", "13.75")
    market(conn, "selic_meta", "2026-11-25", "13.75")
    lab.resolve_due(date(2026, 11, 27))
    assert lab.checkpoints(date(2026, 11, 27)) == 1
    assert lab.checkpoints(date(2026, 11, 28)) == 0  # idempotente
    entries = [j for j in lab.journal(store.OWNER) if j["kind"] == "resultado_observado"]
    assert len(entries) == 1 and entries[0]["payload"]["reavaliacao_dias"] == 30
    assert entries[0]["payload"]["comparacoes"][0]["calibracao"] == "individual"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM lab_journal")


# falhas, recuperação, idempotência e isolamento ----------------------------------------------------------------------
def test_provider_failure_marks_experiment_incomplete_and_out_of_metrics(conn):
    lab, _, exp = run_lab(conn, lab_script(fail_solo=True))
    assert exp["status"] == "incompleto"
    solo = next(a for a in exp["analyses"] if a["mode"] == "individual")
    assert solo["status"] == "falhou" and solo["text"] is None
    board = lab.dashboard(store.OWNER)
    assert board["por_modo"]["individual"]["analises"] == 0 and board["por_modo"]["conselho"]["analises"] == 1


def test_interrupted_runs_resume_and_closing_is_idempotent(conn):
    rt = FakeRuntime(lab_script())
    lab = Lab(conn, orch(conn, rt), today=lambda: TODAY)
    exp = lab.create(store.OWNER, question=QUESTION, client_id="exp-1")
    assert lab.create(store.OWNER, question=QUESTION, client_id="exp-1")["id"] == exp["id"]  # reenvio
    conn.execute("UPDATE runs SET status = 'running'")  # o serviço caiu no meio
    lab.advance()
    assert lab.experiment(store.OWNER, exp["id"])["status"] == "executando"
    store.recover_runs(conn)  # o que o orquestrador faz ao reiniciar
    restarted = orch(conn, rt)
    asyncio.run(drain(restarted))
    assert lab.advance() >= 1 and lab.advance() == 0
    assert lab.experiment(store.OWNER, exp["id"])["status"] == "concluido"
    assert len([j for j in lab.journal(store.OWNER) if j["kind"] == "analise_ia"]) == 1


def test_experiments_are_isolated_between_people(conn):
    lab = Lab(conn, None, today=lambda: TODAY)
    mine = lab.create(store.OWNER, question=QUESTION, start=False)
    with pytest.raises(LookupError):
        lab.experiment("outra-pessoa", mine["id"])
    assert lab.listing("outra-pessoa") == [] and lab.dashboard("outra-pessoa")["experimentos"] == 0


def test_insufficient_data_is_an_accepted_answer(tmp_path):
    from app import db
    c = db.connect(tmp_path / "vazio.db")
    db.migrate(c)
    insufficient = record(hipoteses=[], dados_insuficientes=True, nivel_confianca="baixa",
                          conclusao="Os dados não bastam para concluir.")
    lab, _, exp = run_lab(c, lab_script(solo=insufficient, council=insufficient))
    assert exp["snapshot"]["dossie"]["retrato_financeiro"] is None and exp["snapshot"]["avisos"]
    for a in exp["analyses"]:
        assert a["record_status"] == "ok" and a["record"]["dados_insuficientes"] is True
        assert not any("Nenhuma hipótese" in p for p in a["evaluation"]["consistencia"]["problemas"])


# Radar e automação ---------------------------------------------------------------------------------------------------
def test_radar_proposals_respect_switch_limits_and_dedupe(conn):
    lab = Lab(conn, orch(conn, FakeRuntime(lab_script())), today=lambda: TODAY)
    assert lab.propose_from_radar(store.OWNER, opportunity_id="opp-1", summary="Selic subiu.") is None  # desligada
    lab.set_settings(store.OWNER, {"automation": "propor", "max_per_week": 1})
    first = lab.propose_from_radar(store.OWNER, opportunity_id="opp-1", summary="Selic subiu.")
    assert first["status"] == "proposto" and first["analyses"] == [] and first["origin"] == "radar"
    assert lab.propose_from_radar(store.OWNER, opportunity_id="opp-2", summary="IPCA subiu.") is None  # limite semanal
    lab.set_settings(store.OWNER, {"max_per_week": 3})
    again = lab.propose_from_radar(store.OWNER, opportunity_id="opp-1", summary="Selic subiu.")
    assert again["id"] == first["id"]  # mesmo sinal: mesmo experimento
    lab.set_settings(store.OWNER, {"automation": "executar"})
    started = lab.propose_from_radar(store.OWNER, opportunity_id="opp-3", summary="Dólar disparou.")
    assert started["status"] == "executando" and len(started["analyses"]) == 2
    with pytest.raises(LabError):
        lab.set_settings(store.OWNER, {"automation": "sempre"})


# avaliação às cegas e métricas -------------------------------------------------------------------------------------
def test_blind_judge_hides_authorship_and_drops_unverifiable_scores(conn):
    def script(role, mode, prompt, n):
        if mode == "laboratorio_juiz":
            assert "Análise A" in prompt and "Análise B" in prompt
            body = {"A": {"alternativas": {"nota": 2, "trecho": "Manter no pós-fixado"},
                          "clareza": {"nota": 2, "trecho": "trecho que não existe em lugar nenhum"}},
                    "B": {"alternativas": {"nota": 1, "trecho": "Priorizar o pós-fixado"}}}
            return done("```json\n" + json.dumps(body) + "\n```")
        return lab_script()(role, mode, prompt, n)
    lab, rt, exp = run_lab(conn, script)
    exp = asyncio.run(lab.judge(store.OWNER, exp["id"], 1))
    review = exp["reviews"][0]
    assert review["reviewer"] == "ia" and set(review["blind"].values()) == {"individual", "conselho"}
    judged = next(r for r in rt.requests if r.get("mode") == "laboratorio_juiz")
    assert "individual" not in judged["text"] and judged["lab"] == {"research": False}
    by_mode = review["scores"]["por_modo"]
    assert "clareza" in by_mode[review["blind"]["A"]]["descartados"]  # trecho inventado: nota descartada
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE lab_reviews SET scores_json = '{}'")


def test_statistics_are_honest_about_sample_size():
    assert evaluate.proportion(3, 4)["pct"] is None
    p = evaluate.proportion(8, 10)
    assert p["pct"] == 80.0 and p["ic95"][0] < 80 < p["ic95"][1]
    assert evaluate.verdict(4, 1, 0)["vencedor"] is None  # poucos pares
    strong = evaluate.verdict(12, 1, 2)
    assert strong["vencedor"] == "conselho" and strong["p_valor"] < 0.05
    assert evaluate.verdict(6, 5, 0)["vencedor"] is None
    assert evaluate.sign_test(0, 0) is None
    assert evaluate.risk_categories({"riscos_identificados": ["Inflação acima da meta", "resgate com carência"]}, "") \
        == ["inflacao", "liquidez"]


def test_contract_parser_refuses_bad_hypotheses_without_dropping_the_record():
    text = record([hyp(1.5), hyp(0.6, cond="poupanca_magica > 1"), hyp(0.6, due="2020-01-01"), hyp(0.55)])
    rec, status, problems = contract.parse(text, TODAY)
    assert status == "ok" and len(rec["hipoteses"]) == 1 and len(problems) == 3
    assert contract.parse("sem registro", TODAY)[1] == "ausente"
    assert contract.parse("```json\n{quebrado\n```", TODAY)[1] == "invalido"


# API -----------------------------------------------------------------------------------------------------------------
def test_api_requires_login_and_creates_experiments(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "l.db", mentor_socket=tmp_path / "x.sock", cookie_secure=False,
                              run_scheduler=False, run_orchestrator=False))
    with TestClient(app, base_url="http://lastro.test") as client:
        H = {"X-Lastro": "1"}
        assert client.get("/api/lab").status_code == 401
        auth.set_password(app.state.conn, "senha-de-teste-123")
        assert client.post("/api/auth/login", json={"password": "senha-de-teste-123"}, headers=H).status_code == 204
        made = client.post("/api/lab", json={"question": QUESTION, "category": "renda_fixa", "client_id": "a1"}, headers=H)
        assert made.status_code == 201 and made.json()["status"] == "executando"
        assert client.post("/api/lab", json={"question": "curta"}, headers=H).status_code == 422
        listing = client.get("/api/lab").json()
        assert len(listing["experiments"]) == 1 and listing["dashboard"]["em_execucao"] == 1
        assert client.get("/api/lab/nao-existe").status_code == 404
        assert client.get("/api/team/conversations").json() == []  # conversas do experimento ficam ocultas
