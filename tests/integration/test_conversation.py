# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conversa natural com a equipe: intenção antes de qualquer reunião, grupo em que os agentes reagem uns aos outros
com limite, oferta do Bento para levar uma decisão ao Conselho, intervenções nunca perdidas e a identidade da pessoa
vinda do perfil. O runtime é simulado (FakeRuntime); banco, orquestrador e roteamento são os reais."""
import asyncio

import pytest

from app import db, store
from app.orchestrator import CHAT_MAX_TURNS, Orchestrator
from ledger import book
from mentor.session import load_prompt
from team import intent

from .test_team import SNAP, TODAY, FakeRuntime, agent_messages, done, drain, group


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lastro.db")
    db.migrate(connection)
    store.create_snapshot(connection, SNAP)
    yield connection
    connection.close()


def orch(conn, rt):
    return Orchestrator(conn, rt.stream, today=lambda: TODAY, semantic_audit="off")


def send(o, conv, text, **kw):
    return o.submit(store.get_conversation(o.conn, conv["id"]), text, **kw)


def council_room(conn):
    return store.create_conversation(conn, "Conselho", kind="panel", channel="council")


def runs(conn, conv):
    return store.list_runs(conn, conv["id"], limit=50)


# intenção ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("Oi, pessoal!", intent.CONVERSA),
    ("Como vocês estão?", intent.CONVERSA),
    ("Tô entediado hoje.", intent.CONVERSA),
    ("@nina, me conta alguma coisa.", intent.CONVERSA),
    ("@rui, por que você é tão desconfiado?", intent.CONVERSA),
    ("Só queria bater um papo com vcs, como vocês estão?", intent.CONVERSA),
    ("@caio e @rui, vocês concordam sobre Bitcoin?", intent.PERGUNTA),
    ("Quero discutir minha carteira.", intent.DECISAO),
    ("Galera, estou pensando em investir R$ 1.000 em Bitcoin.", intent.DECISAO),
    ("Bento, convoca uma reunião.", intent.REUNIAO),
    ("Pessoal, o que vocês acham desse assunto?", intent.PERGUNTA),
    ("Analisa minha carteira de ações", intent.ANALISE),
    ("Oi! Quanto devo ter de reserva?", intent.PERGUNTA),   # saudação com assunto financeiro não é só papo
    ("Quem o Bento convocou?", intent.PERGUNTA),            # falar de reunião não é pedir reunião
])
def test_intent(text, expected):
    assert intent.classify(text) == expected


SOCIAL = ["Oi, pessoal!", "Como vocês estão?", "Tô entediado hoje.", "@nina, me conta alguma coisa.",
          "@rui, por que você é tão desconfiado?"]


@pytest.mark.parametrize("room", ["group", "council"])
def test_small_talk_never_starts_an_analysis_and_gets_real_answers(conn, room):
    conv = group(conn, "comportamental", "riscos", "analista") if room == "group" else council_room(conn)
    rt = FakeRuntime(lambda r, m, p, n: done(f"Oi! Aqui é {r}."))
    o = orch(conn, rt)
    for text in SOCIAL:
        out = send(o, conv, text)
        assert out["run"]["kind"] == "reply" and out["run"]["route"]["style"] == "conversa", text
        asyncio.run(drain(o))
    assert all(r["kind"] == "reply" for r in runs(conn, conv))
    assert {r["mode"] for r in rt.requests} == {"conversa"}
    assert not any(r["mode"].startswith("conselho") for r in rt.requests)
    by_text = {}
    for m in store.list_messages(conn, conv["id"]):
        if m["role"] == "user":
            current = m["content"]
        elif m["kind"] != "notice":
            by_text.setdefault(current, []).append(m["agent_id"])
    assert by_text["Oi, pessoal!"][0] == "mentor" and len(by_text["Oi, pessoal!"]) == 3  # o grupo responde, não só um
    assert by_text["@nina, me conta alguma coisa."] == ["comportamental"]
    assert by_text["@rui, por que você é tão desconfiado?"] == ["riscos"]


def test_two_mentions_both_answer_and_the_second_reads_the_first(conn):
    conv = group(conn, "analista", "riscos")
    rt = FakeRuntime(lambda r, m, p, n: done("Bitcoin pode fazer sentido numa fatia pequena." if r == "analista"
                                             else "Discordo um pouco do @caio: a volatilidade pesa."))
    o = orch(conn, rt)
    out = send(o, conv, "@caio e @rui, vocês concordam sobre Bitcoin?")
    asyncio.run(drain(o))
    assert out["run"]["kind"] == "reply" and rt.roles() == ["analista", "riscos"]
    assert "Bitcoin pode fazer sentido numa fatia pequena." in rt.prompt_for("riscos")
    assert [m["agent_id"] for m in agent_messages(conn, conv)] == ["analista", "riscos"]


def test_agents_call_each_other_with_a_hard_limit(conn):
    conv = group(conn, "comportamental", "riscos", "analista", "economista", "planejador")
    # todo mundo chama todo mundo: sem limite, seria um laço
    rt = FakeRuntime(lambda r, m, p, n: done("@lia @caio @vera @rui @nina, o que acham?"))
    o = orch(conn, rt)
    send(o, conv, "Oi, gente!")
    asyncio.run(drain(o))
    said = agent_messages(conn, conv)
    assert len(said) == CHAT_MAX_TURNS
    assert len({m["agent_id"] for m in said}) == len(said)  # cada um fala uma vez por mensagem
    spontaneous = [m for m in said if m["meta"]["chat"].get("responds_to")]
    ids = {m["id"] for m in said}
    assert len(spontaneous) == 1 and spontaneous[0]["reply_to_id"] in ids  # responde à fala do colega que o chamou


def test_decision_gets_an_offer_and_accepting_convenes_with_the_original_question(conn):
    conv = group(conn, "analista", "riscos", "cripto")
    rt = FakeRuntime(lambda r, m, p, n: done("Dá para conversar. Quer que eu reúna os especialistas?"))
    o = orch(conn, rt)
    question = "Galera, estou pensando em investir R$ 1.000 em Bitcoin."
    out = send(o, conv, question)
    assert out["run"]["kind"] == "reply" and out["run"]["route"]["offer"] is True
    asyncio.run(drain(o))
    assert "pergunte se ela quer que você reúna os especialistas" in rt.prompt_for("mentor")
    offer = agent_messages(conn, conv)[-1]
    assert offer["meta"]["council_offer"]["question"] == question

    accepted = send(o, conv, "Sim, pode reunir")
    assert accepted["run"]["kind"] == "council" and accepted["run"]["route"]["question"] == question
    assert "cripto" in accepted["run"]["route"]["lineup"]  # escalação pelo tema original, não pelo "sim"


def test_yes_without_an_offer_is_just_conversation(conn):
    conv = group(conn, "analista")
    o = orch(conn, FakeRuntime())
    assert send(o, conv, "Sim, pode ser")["run"]["kind"] == "reply"


def test_meeting_request_uses_the_topic_of_the_conversation(conn):
    conv = group(conn, "analista", "riscos")
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, conv, "Quero discutir minha carteira.")
    asyncio.run(drain(o))
    out = send(o, conv, "Bento, convoca uma reunião.")
    assert out["run"]["kind"] == "council" and out["run"]["route"]["question"] == "Quero discutir minha carteira."
    asyncio.run(drain(o))
    assert "Quero discutir minha carteira." in rt.prompt_for("planejador")


def test_meeting_request_without_topic_asks_for_one(conn):
    conv = group(conn, "analista")
    rt = FakeRuntime()
    o = orch(conn, rt)
    out = send(o, conv, "Bento, convoca uma reunião.")
    assert out["run"]["kind"] == "reply" and out["run"]["route"]["ask_topic"] is True
    asyncio.run(drain(o))
    assert "Pergunte, em uma frase, o que ela quer que o Conselho analise" in rt.prompt_for("mentor")


def test_open_question_to_everyone_is_answered_without_a_meeting(conn):
    conv = group(conn, "analista", "riscos")
    rt = FakeRuntime()
    o = orch(conn, rt)
    out = send(o, conv, "Pessoal, o que vocês acham desse assunto?")
    asyncio.run(drain(o))
    assert out["run"]["kind"] == "reply" and agent_messages(conn, conv)


def test_council_room_still_meets_on_financial_questions(conn):
    conv = council_room(conn)
    o = orch(conn, FakeRuntime())
    assert send(o, conv, "Quanto devo ter de reserva?")["run"]["kind"] == "council"


def test_individual_chat_answers_directly_and_simple_question_does_not_convene(conn):
    conv = store.create_conversation(conn, "Nina", channel="direct", agent_id="comportamental")
    rt = FakeRuntime()
    o = orch(conn, rt)
    assert send(o, conv, "Oi, Nina!")["run"]["route"]["style"] == "conversa"
    out = send(o, conv, "Me explica o que significa volatilidade.")
    asyncio.run(drain(o))
    assert out["run"]["kind"] == "reply" and [r["mode"] for r in rt.requests] == ["conversa", "direto"]


def test_cora_can_chat_with_her_own_prompt(conn):
    conv = group(conn, "riscos", "auditor")
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, conv, "@cora, como você trabalha?")
    asyncio.run(drain(o))
    assert rt.roles() == ["auditor"]
    chat = load_prompt("auditor", "conversa")
    assert "Não emita veredito" in chat and "Responda EXATAMENTE neste formato" not in chat
    assert "Responda EXATAMENTE neste formato" in load_prompt("auditor")


def test_personalities_reach_the_prompt():
    assert "cético, protetor" in load_prompt("riscos", "conversa")
    assert "empática, perspicaz e bem-humorada" in load_prompt("comportamental", "grupo")
    assert "acolhedor, ponderado e conciliador" in load_prompt("mentor", "conselho_sintese")


def test_intervention_after_the_discussion_still_gets_an_answer(conn):
    conv = council_room(conn)
    rt = FakeRuntime(lambda r, m, p, n: done(f"Fala de {r}."))
    o = orch(conn, rt)
    meeting = send(o, conv, "/rapida Quanto devo ter de reserva?")["run"]  # consulta rápida: não há pauta
    question = send(o, conv, "@rui, e se eu perder o emprego?")
    assert question["run"] is None and question["message"]["meta"]["intervention_for"] == meeting["id"]
    asyncio.run(drain(o))
    follow = [r for r in runs(conn, conv) if r["message_id"] == question["message"]["id"]]
    assert len(follow) == 1 and follow[0]["route"]["agents"] == ["riscos"] and follow[0]["status"] == "succeeded"
    answer = [m for m in agent_messages(conn, conv) if m["run_id"] == follow[0]["id"]]
    assert [m["agent_id"] for m in answer] == ["riscos"]
    assert "Fala de mentor." in rt.prompt_for("riscos")  # a resposta tardia vê a reunião inteira
    asyncio.run(drain(o))
    assert len([r for r in runs(conn, conv) if r["message_id"] == question["message"]["id"]]) == 1  # sem duplicar


def test_jokes_and_hypotheticals_are_not_recorded_as_facts(conn):
    conv = group(conn, "analista")
    o = orch(conn, FakeRuntime())
    send(o, conv, "Galera, estou pensando em investir R$ 1.000 em Bitcoin.")
    send(o, conv, "E se eu ganhasse R$ 1.000.000 na loteria? kkk")
    assert book.list_entries(conn, store.OWNER, status="registrado") == []


# identidade -------------------------------------------------------------------------------------------------------
def test_every_agent_sees_the_configured_name_in_group_and_individual_chats(conn):
    store.set_profile(conn, store.OWNER, nome="Ana", apelido="Aninha", tratamento="pode ser informal")
    conv = group(conn, "comportamental", "riscos")
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, conv, "Bom dia, pessoal!")
    asyncio.run(drain(o))
    direct = store.create_conversation(conn, "Rui", channel="direct", agent_id="riscos")
    send(o, direct, "Oi, Rui")
    asyncio.run(drain(o))
    assert len(rt.requests) == 4
    for r in rt.requests:
        assert "prefere ser chamada de Ana (apelido: Aninha)" in r["text"] and "pode ser informal" in r["text"]
        assert "não em toda mensagem" in r["text"] and "Não presuma gênero" in r["text"]


def test_name_change_is_seen_on_the_next_message_and_after_restart(tmp_path):
    path = tmp_path / "lastro.db"
    first = db.connect(path)
    db.migrate(first)
    conv = store.create_conversation(first, "Bento", channel="direct", agent_id="mentor")
    store.set_profile(first, store.OWNER, nome="Ana")
    rt = FakeRuntime()
    o = orch(first, rt)
    send(o, conv, "Oi")
    asyncio.run(drain(o))
    store.set_profile(first, store.OWNER, nome="Mariana")
    send(o, conv, "Oi de novo")
    asyncio.run(drain(o))
    assert "chamada de Ana" in rt.requests[0]["text"] and "chamada de Mariana" in rt.requests[1]["text"]
    first.close()

    second = db.connect(path)  # reinício do serviço
    rt2 = FakeRuntime()
    o2 = orch(second, rt2)
    send(o2, conv, "Voltei")
    asyncio.run(drain(o2))
    assert "chamada de Mariana" in rt2.requests[0]["text"]
    second.close()


def test_identity_never_leaks_between_accounts(conn):
    store.set_profile(conn, store.OWNER, nome="Ana")
    store.set_profile(conn, "outra-conta", nome="Bia")
    mine = store.create_conversation(conn, "x", channel="direct", agent_id="mentor")
    theirs = store.create_conversation(conn, "y", channel="direct", agent_id="mentor", user_id="outra-conta")
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, mine, "Oi")
    send(o, theirs, "Oi")
    asyncio.run(drain(o))
    texts = {r["text"].count("Ana"): r["text"] for r in rt.requests}
    assert any("chamada de Ana" in t and "Bia" not in t for t in texts.values())
    assert any("chamada de Bia" in t and "Ana" not in t for t in texts.values())


def test_without_a_name_one_agent_asks_once(conn):
    conv = group(conn, "comportamental", "riscos")
    rt = FakeRuntime()
    o = orch(conn, rt)
    first = send(o, conv, "Oi, pessoal!")
    asyncio.run(drain(o))
    second = send(o, conv, "Como vocês estão?")
    asyncio.run(drain(o))
    assert first["run"]["route"].get("ask_name") is True and not second["run"]["route"].get("ask_name")
    asks = [r for r in rt.requests if "pergunte uma vez" in r["text"]]
    assert [r["role"] for r in asks] == ["mentor"]
    assert all("não pergunte de novo" in r["text"] for r in rt.requests if r not in asks)


def test_name_said_in_chat_is_only_a_suggestion(conn):
    conv = group(conn, "analista")
    o = orch(conn, FakeRuntime())
    out = send(o, conv, "Pode me chamar de maitê, tá?")
    suggestion = [n for n in out["notices"] if (n.get("meta") or {}).get("profile_suggestion")]
    assert suggestion and suggestion[0]["meta"]["profile_suggestion"] == {"nome": "Maitê"}
    assert store.get_profile(conn, store.OWNER)["nome"] == ""  # nada muda sem a confirmação da pessoa
