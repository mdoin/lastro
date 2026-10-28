# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conselho deliberativo: seleção, pauta, falas que respondem a falas, revisão justificada, limites, falhas,
intervenção da pessoa, retomada, auditoria que devolve questões, modos e histórico (docs/COUNCIL.md).

O runtime (provedor) é simulado; orquestrador, banco, auditoria e regras são os reais. As falas abaixo são respostas
do provedor simulado — o Lastro não escreve fala de agente.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import auth, store
from app.web import Settings, create_app
from team import deliberation
from team.deliberation import Limits

from .test_team import SNAP, FakeRuntime, agent_messages, conn, done, drain, orch, send, structured  # noqa: F401

STANCES = {"planejador": "contrária", "analista": "favorável", "riscos": "contrária", "comportamental": "condicional",
           "economista": "condicional", "cripto": "favorável", "mila": "condicional"}
PLAN_R1 = json.dumps({"concordancias": ["A reserva vem antes"], "divergencias": ["@caio vê espaço para investir"],
                      "falas": [{"quem": "@rui", "para": "@caio", "tipo": "contestacao", "pedido": "Mostre o risco"},
                                {"quem": "@caio", "para": "@rui", "tipo": "resposta", "pedido": "Responda ao Rui"},
                                {"quem": "@vera", "para": "@caio", "tipo": "pergunta", "pedido": "fora da reunião"}],
                      "encerrar": False})
END = '{"falas": [], "encerrar": true}'


def council_conv(conn):
    return store.create_conversation(conn, "Conselho", kind="panel", channel="council")


def script_factory(*, plans=(PLAN_R1, END), revise=None, debate_reaction="discordo", synth=None, audit=None):
    calls = {"pauta": 0}

    def script(role, mode, prompt, n):
        if mode == "conselho_parecer":
            return done(structured(STANCES[role], f"PONTO-{role.upper()}"))
        if mode == "conselho_pauta":
            calls["pauta"] += 1
            return done(plans[min(calls["pauta"], len(plans)) - 1])
        if mode == "conselho_debate":
            if revise and role == revise:
                return done("**Posição:** contrária (revista)\n**Reação:** reviso\n\nCom a reserva abaixo da meta, "
                            "reviso: investir agora não se sustenta. FALA-" + role.upper())
            return done(f"**Posição:** {STANCES[role]} (mantida)\n**Reação:** {debate_reaction}\n\nFALA-{role.upper()}")
        if mode == "conselho_sintese":
            return done(synth or "## Conclusão\nPriorizar a reserva.\n\n## Participação\n- @lia — reserva\n- @rui — "
                                 "risco\n- @caio — investimento\n\n## Divergências\n- @caio × @lia e @rui.")
        if role == "auditor":
            return done(audit(n) if callable(audit) else (audit or "VEREDITO: PASSA\n- coerente"))
        return done(f"Resposta de {role}.")
    return script


QUESTION = "Com R$ 2.000 sobrando, invisto em ações ou completo a reserva de emergência?"


def run_council(conn, script, text=QUESTION, **kw):
    conv = council_conv(conn)
    rt = FakeRuntime(script)
    o = orch(conn, rt, semantic_audit=kw.pop("semantic_audit", "council"))
    out = send(o, conv, text)
    asyncio.run(drain(o))
    return conv, rt, o, out


def modes_of(rt):
    return [(r["role"], r.get("mode")) for r in rt.requests]


# seleção dinâmica -----------------------------------------------------------------------------------------------------
def test_dynamic_selection_by_topic_mode_and_request():
    assert deliberation.select(QUESTION, "completo") == ["planejador", "analista", "riscos"]
    macro = deliberation.select("A Selic vai cair; muda algo nos meus investimentos em renda fixa?", "completo")
    assert "economista" in macro and "cripto" not in macro and "riscos" in macro
    assert "cripto" in deliberation.select("Coloco a reserva em bitcoin agora?", "completo")
    assert len(deliberation.select(QUESTION, "rapida")) <= 2
    assert deliberation.select("qualquer coisa", "debate", ["analista", "riscos"]) == ["analista", "riscos"]
    many = deliberation.select("Invisto tudo em bitcoin agora com medo da inflação, Selic e meu orçamento?",
                               "completo", limits=Limits(max_participants=4))
    assert len(many) == 4 and many[-1] == "riscos"  # o contraponto de riscos nunca é cortado
    assert deliberation.addressed("Bento, quero ouvir a Nina antes da decisão.") == ["mentor", "comportamental"]
    assert deliberation.addressed("@rui, por que você discorda do Caio?") == ["riscos", "analista"]


# troca real de mensagens, contestação e pauta validada ---------------------------------------------------------------
def test_agents_reply_to_each_other_following_a_validated_agenda(conn):
    conv, rt, _, out = run_council(conn, script_factory())
    assert out["run"]["route"]["lineup"] == ["mentor", "planejador", "analista", "riscos", "auditor"]
    modes = modes_of(rt)
    debaters = sorted(role for role, mode in modes if mode == "conselho_debate")
    assert debaters == ["analista", "riscos"]  # a fala pedida para @vera (fora da reunião) foi descartada
    msgs = {m["step_key"]: m for m in agent_messages(conn, conv)}
    rui, caio = msgs["conselho:debate:1:riscos"], msgs["conselho:debate:1:analista"]
    assert rui["reply_to_id"] == msgs["conselho:analista"]["id"]  # responde ao parecer real do Caio
    assert rui["meta"]["deliberation"]["responds_to"]["agent"] == "analista"
    assert rui["meta"]["deliberation"]["reaction"] == "discorda" and "FALA-RISCOS" in rui["content"]
    caio_prompt = next(r["text"] for r in rt.requests if r["role"] == "analista" and r.get("mode") == "conselho_debate")
    assert "Responda a @rui" in caio_prompt and "PONTO-RISCOS" in caio_prompt
    pauta = msgs["conselho:pauta:1"]
    assert "A reserva vem antes" in pauta["content"] and "@rui → @caio" in pauta["content"]
    assert ("mentor", "conselho_pauta") in modes and modes.count(("mentor", "conselho_pauta")) == 2  # 2ª rodada encerra
    final = agent_messages(conn, conv)[-1]
    part = next(s for s in final["meta"]["verdict"]["sections"] if s["key"] == "participacao")
    assert [seg["agent"] for item in part["items"] for seg in item if "agent" in seg] == ["planejador", "riscos", "analista"]


def test_justified_revision_is_recorded_and_unresolved_divergence_stays_visible(conn):
    conv, rt, _, out = run_council(conn, script_factory(revise="analista"))
    msgs = {m["step_key"]: m for m in agent_messages(conn, conv)}
    assert msgs["conselho:debate:1:analista"]["meta"]["deliberation"]["revised"] is True
    positions = msgs["conselho:posicoes"]["meta"]["positions"]
    assert positions["analista"] == {"initial": "favoravel", "final": "contraria"}
    record = json.loads(conn.execute("SELECT record_json FROM council_records").fetchone()[0])
    assert record["mudancas"] == ["analista"] and record["posicoes_finais"]["analista"] == "contraria"
    assert "Não é uma decisão sua" in record["aviso"]

    conn2_conv, rt2, _, _ = run_council(conn, script_factory())  # sem revisão: divergência continua no mapa
    m2 = {m["step_key"]: m for m in agent_messages(conn, conn2_conv)}
    assert m2["conselho:posicoes"]["meta"]["conflict"] is True
    assert "Divergência material mantida" in m2["conselho:posicoes"]["content"]


# limites ------------------------------------------------------------------------------------------------------------
def test_rounds_messages_and_calls_are_capped(conn, monkeypatch):
    endless = json.dumps({"falas": [{"quem": "@rui", "para": "@caio", "tipo": "contestacao"},
                                    {"quem": "@caio", "para": "@rui", "tipo": "resposta"}], "encerrar": False})
    monkeypatch.setenv("LASTRO_COUNCIL_MAX_ROUNDS", "3")
    conv, rt, _, _ = run_council(conn, script_factory(plans=(endless,)))
    assert sum(1 for _, m in modes_of(rt) if m == "conselho_pauta") == 3  # nunca passa de 3 rodadas

    monkeypatch.setenv("LASTRO_COUNCIL_MAX_MESSAGES", "2")
    conv, rt, _, _ = run_council(conn, script_factory(plans=(endless,)))
    assert sum(1 for _, m in modes_of(rt) if m == "conselho_debate") == 2
    notices = [m["content"] for m in store.list_messages(conn, conv["id"]) if m["kind"] == "notice"]
    assert any("limite de 2 falas" in n for n in notices)
    final = agent_messages(conn, conv)[-1]
    assert final["meta"]["deliberation"]["limits_hit"] == ["limite de 2 falas"]

    monkeypatch.setenv("LASTRO_COUNCIL_MAX_MESSAGES", "16")
    monkeypatch.setenv("LASTRO_COUNCIL_MAX_CALLS", "5")  # enquadramento + 3 pareceres + 1 pauta
    conv, rt, _, _ = run_council(conn, script_factory(plans=(endless,)))
    assert not any(m == "conselho_debate" for _, m in modes_of(rt))
    assert agent_messages(conn, conv)[-1]["step_key"] == "conselho:sintese"  # chega ao veredito mesmo assim


# falhas -------------------------------------------------------------------------------------------------------------
def test_provider_failure_keeps_other_contributions(conn):
    base = script_factory()

    def script(role, mode, prompt, n):
        if role == "planejador" and mode == "conselho_parecer":
            return [{"type": "error", "kind": "timeout", "message": "tempo esgotado"}]
        return base(role, mode, prompt, n)
    conv, rt, _, out = run_council(conn, script)
    msgs = {m["step_key"]: m for m in agent_messages(conn, conv)}
    assert msgs["conselho:planejador"]["status"] == "error" and msgs["conselho:analista"]["status"] == "ok"
    assert msgs["conselho:sintese"]["status"] == "ok"
    assert store.get_run(conn, out["run"]["id"])["status"] == "partial"


# retomada sem duplicar --------------------------------------------------------------------------------------------
def test_restart_reuses_finished_steps_without_duplicates(conn):
    conv, rt, o, out = run_council(conn, script_factory())
    before = [(m["id"], m["step_key"]) for m in agent_messages(conn, conv)]
    calls = len(rt.requests)
    store.set_run(conn, out["run"]["id"], status="running")  # como se o serviço tivesse caído no fim
    assert store.recover_runs(conn) == 1
    asyncio.run(drain(o))
    assert len(rt.requests) == calls  # nenhum passo concluído foi refeito
    assert [(m["id"], m["step_key"]) for m in agent_messages(conn, conv)] == before


# intervenção da pessoa ------------------------------------------------------------------------------------------------
def test_user_intervention_during_meeting_is_answered_in_the_next_round(conn):
    conv = council_conv(conn)
    rt = FakeRuntime(script_factory(plans=(END,)))
    o = orch(conn, rt)
    first = send(o, conv, QUESTION)
    asked = send(o, conv, "@rui, por que você discorda do Caio?")  # chega com a reunião na fila
    assert asked["run"] is None and asked["message"]["meta"]["intervention_for"] == first["run"]["id"]
    assert "entrou na reunião" in asked["notices"][-1]["content"]
    asyncio.run(drain(o))
    rui = next(m for m in agent_messages(conn, conv) if m["step_key"] == "conselho:debate:1:riscos")
    assert rui["reply_to_id"] == asked["message"]["id"] and rui["meta"]["deliberation"]["responds_to"]["person"]
    prompt = next(r["text"] for r in rt.requests if r["role"] == "riscos" and r.get("mode") == "conselho_debate")
    assert "por que você discorda do Caio" in prompt
    assert len(store.list_runs(conn, conv["id"])) == 1  # nenhuma execução duplicada


def test_close_command_stops_discussion_and_still_gives_a_verdict(conn):
    conv = council_conv(conn)
    rt = FakeRuntime(script_factory())
    o = orch(conn, rt)
    first = send(o, conv, QUESTION)
    assert send(o, conv, "/encerrar")["run"] is None
    assert store.get_run(conn, first["run"]["id"])["close_requested"] is True
    asyncio.run(drain(o))
    assert not any(m == "conselho_debate" for _, m in modes_of(rt))
    assert agent_messages(conn, conv)[-1]["step_key"] == "conselho:sintese"


def test_direct_questions_after_the_meeting(conn):
    conv, rt, o, _ = run_council(conn, script_factory(plans=(END,)))
    out = send(o, conv, "@caio, responda aos argumentos do Rui.")
    assert out["run"]["kind"] == "reply" and out["run"]["route"]["agents"] == ["analista", "riscos"]
    out = send(o, conv, "Bento, quero ouvir a Nina antes da decisão.")
    assert out["run"]["route"]["agents"] == ["comportamental"]
    asyncio.run(drain(o))
    nina_prompt = rt.prompt_for("comportamental")
    assert "PONTO-PLANEJADOR" in nina_prompt  # a reunião anterior está no contexto da pergunta direta


# auditoria que devolve questões ---------------------------------------------------------------------------------------
def test_auditor_can_send_questions_back_once(conn):
    def audit(n):
        return ("VEREDITO: PASSA COM RESSALVAS\n- risco de liquidez sem resposta\n"
                "DEVOLVER: @rui — quanto a reserva cobre depois do aporte?" if n == 1 else "VEREDITO: PASSA\n- ok")
    conv, rt, _, _ = run_council(conn, script_factory(plans=(END,), audit=audit))
    msgs = {m["step_key"]: m for m in agent_messages(conn, conv)}
    assert "quanto a reserva cobre" in msgs["conselho:devolucao:1"]["content"] and msgs["conselho:devolucao:1"]["agent_id"] == "auditor"
    assert "conselho:debate:auditoria-1:riscos" in msgs
    assert [m for _, m in modes_of(rt)].count("conselho_sintese") == 2  # novo veredito depois da resposta
    assert msgs["conselho:auditoria"]["meta"]["deliberation"]["phase"] == "auditoria"


# modos --------------------------------------------------------------------------------------------------------------
def test_quick_mode_skips_meeting_machinery(conn):
    conv, rt, _, out = run_council(conn, script_factory(), text="/rapida Vale a pena antecipar parcelas do financiamento?")
    assert out["run"]["route"]["mode"] == "rapida" and len(out["run"]["route"]["lineup"]) <= 4
    modes = {m for _, m in modes_of(rt)}
    assert not modes & {"conselho_enquadramento", "conselho_pauta", "conselho_debate"}
    assert agent_messages(conn, conv)[-1]["step_key"] == "conselho:sintese"


def test_debate_mode_assigns_analysis_roles(conn):
    conv, rt, _, out = run_council(conn, script_factory(plans=(END,)),
                                   text="/debate @caio @rui Bitcoin protege contra a inflação?")
    assert out["run"]["route"]["lineup"] == ["mentor", "analista", "riscos", "auditor"]
    caio = next(r["text"] for r in rt.requests if r["role"] == "analista" and r.get("mode") == "conselho_parecer")
    rui = next(r["text"] for r in rt.requests if r["role"] == "riscos" and r.get("mode") == "conselho_parecer")
    assert "SUSTENTAM" in caio and "CONTRARIAM" in rui and "não uma crença" in caio


def test_new_round_and_verdict_review_reuse_the_last_meeting(conn):
    conv, rt, o, _ = run_council(conn, script_factory(plans=(END,)))
    out = send(o, conv, "/rodada")
    assert out["run"]["route"]["mode"] == "rodada"
    asyncio.run(drain(o))
    second = [r for r in rt.requests if r.get("mode") == "conselho_parecer"]
    assert len(second) == 3  # os pareceres da reunião anterior foram reaproveitados, não refeitos
    out = send(o, conv, "/revisar Considere que a reserva já cobre 6 meses.")
    asyncio.run(drain(o))
    last = rt.requests[-2]
    assert last["role"] == "mentor" and last["mode"] == "conselho_sintese" and "PONTO-ANALISTA" in last["text"]
    assert "reserva já cobre 6 meses" in last["text"]


# histórico e isolamento -----------------------------------------------------------------------------------------------
def test_meeting_history_is_per_user(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "none.sock",
                              cookie_secure=False, run_scheduler=False, run_orchestrator=False))
    with TestClient(app, base_url="http://lastro.test") as client:
        conn = app.state.conn
        auth.set_password(conn, "uma senha longa e boa")
        client.post("/api/auth/login", json={"password": "uma senha longa e boa"}, headers={"X-Lastro": "1"})
        store.create_snapshot(conn, SNAP)
        conn.execute("INSERT INTO users (id, created_at) VALUES ('outra', '2026-10-01')")
        for user in (store.OWNER, "outra"):
            conn.execute("INSERT INTO council_records (run_id, user_id, conversation_id, mode, topic, record_json, "
                         "created_at) VALUES (?,?,?,?,?,?,?)", (f"r-{user}", user, "c", "completo", f"tema {user}",
                                                                 '{"tema": "x"}', "2026-10-28"))
        topics = [m["topic"] for m in client.get("/api/team/meetings").json()]
        assert topics == [f"tema {store.OWNER}"]
        other_run = store.create_run(conn, {"id": store.create_conversation(conn, "x", channel="council",
                                                                           user_id="outra")["id"], "user_id": "outra"},
                                     "m", "council", {})
        assert client.post(f"/api/team/runs/{other_run['id']}/close", headers={"X-Lastro": "1"}).status_code == 404


@pytest.fixture(autouse=True)
def _clean_limits(monkeypatch):
    for name in Limits.__dataclass_fields__:
        monkeypatch.delenv(f"LASTRO_COUNCIL_{name.upper()}", raising=False)
