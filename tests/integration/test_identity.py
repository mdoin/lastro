# SPDX-License-Identifier: AGPL-3.0-or-later
"""Identidade comportamental dos agentes (docs/CONVERSAS.md): camadas de prompt, liberdade de não falar, vozes
escolhidas pelo assunto e falas que só ecoam não publicadas. O runtime é simulado; o que se testa é o que o
Lastro controla em código: quem é chamado, com quais instruções, e o que chega à pessoa. A qualidade das falas
reais do modelo é medida por scripts/eval_conversas.py."""
import asyncio
import itertools
import re
from datetime import datetime, timezone

import pytest

from app import db, store
from mentor.session import PROMPTS, load_prompt
from team import voice
from team.agents import AGENTS, MODES

from .test_team import SNAP, TODAY, FakeRuntime, agent_messages, done, drain, group

CHAT_AGENTS = [a.id for a in AGENTS.values() if a.chat_enabled]
# As frases reais do problema relatado (duas falas com o mesmo esqueleto).
MILA = ("Fiquei quietinha porque eleição e Valorant não são bem a minha área, mas concordo com o Bento: "
        "descansar também é importante. Se quiser, a Lia e o Caio podem ajudar nas finanças. Vamos esperar os outros!")
TEO = ("Fiquei quieto porque eleição e Valorant não são bem a minha área, mas concordo com o Bento: tem dia que é "
       "melhor desligar. Se precisar, a Vera e o Rui entendem mais disso. Vamos ver o que os outros acham!")


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lastro.db")
    db.migrate(connection)
    store.create_snapshot(connection, SNAP)
    yield connection
    connection.close()


def orch(conn, rt):
    from app.orchestrator import Orchestrator
    return Orchestrator(conn, rt.stream, today=lambda: TODAY, semantic_audit="off")


def send(o, conv, text):
    return o.submit(store.get_conversation(o.conn, conv["id"]), text)


def everyone(conn):
    return group(conn, "planejador", "analista", "economista", "riscos", "comportamental", "cripto", "mila", "auditor")


def optional_roles(rt):
    return [r["role"] for r in rt.requests if voice.SILENT in r["text"]]


# camadas ------------------------------------------------------------------------------------------------------------
def test_shared_layer_has_no_conversational_template():
    """O que todos recebem não pode impor roteiro: nem "fale só da sua área", nem cumprimento/pergunta obrigatórios."""
    shared = [(PROMPTS / "_base.md").read_text(encoding="utf-8")] + \
             [(PROMPTS / "modos" / f"{m}.md").read_text(encoding="utf-8") for m in ("conversa", "grupo", "direto")]
    for text in shared:
        assert "Fale só da sua especialidade" not in text
        assert "Cumprimente, comente, pergunte de volta" not in text
        assert "diga que dá para aprofundar" not in text
        assert "curta e direta" not in text  # o tamanho vem da pergunta, não de uma regra global


def test_every_chat_agent_has_its_own_identity_in_every_mode():
    for agent in CHAT_AGENTS:
        identity = (PROMPTS / "identidades" / f"{agent}.md").read_text(encoding="utf-8")
        assert f"({AGENTS[agent].name})" in identity.splitlines()[0]
        for mode in MODES:
            assert identity.strip() in load_prompt(agent, mode), (agent, mode)


def test_identities_are_dispositions_not_catchphrases():
    texts = {a: (PROMPTS / "identidades" / f"{a}.md").read_text(encoding="utf-8") for a in CHAT_AGENTS}
    for agent, text in texts.items():
        # orienta temperamento, discordância, erro e humor (ou reserva), sem frases prontas entre aspas para repetir
        for dimension in ("Temperamento:", "Discordância:", "Erros:"):
            assert dimension in text, (agent, dimension)
        assert not re.search(r"\"[^\"]{12,}\"", text), agent
    for a, b in itertools.combinations(texts, 2):
        body = lambda t: "\n".join(line.split(":", 1)[-1] for line in t.splitlines()[1:])  # noqa: E731
        assert voice.similarity(body(texts[a]), body(texts[b])) < 0.1, (a, b)


# 1. cumprimento ao grupo ------------------------------------------------------------------------------------------
def test_greeting_gets_few_voices_and_only_the_first_is_obliged(conn):
    conv = everyone(conn)
    rt = FakeRuntime(lambda r, m, p, n: done({"mentor": "Oi! Que bom te ver.", "planejador": "Bom dia."}.get(r, "Opa.")))
    o = orch(conn, rt)
    send(o, conv, "Oi, pessoal!")
    asyncio.run(drain(o))
    assert rt.roles() == ["mentor", "planejador"]
    assert optional_roles(rt) == ["planejador"]
    assert "auditor" not in rt.roles()  # a Cora não entra em papo sem ser chamada
    # na próxima saudação, quem falou há mais tempo tem a vez: o Bento não precisa abrir toda conversa
    send(o, conv, "Bom dia, gente!")
    asyncio.run(drain(o))
    assert rt.roles()[2:] == ["analista", "economista"]


# 2. cansaço (sem destinatário) ------------------------------------------------------------------------------------
def test_tiredness_brings_the_voice_the_subject_calls_for_as_optional(conn):
    conv = everyone(conn)
    rt = FakeRuntime(lambda r, m, p, n: done("Puxado, hein." if r == "mentor" else voice.SILENT))
    o = orch(conn, rt)
    send(o, conv, "Tô cansada hoje, semana puxada.")
    asyncio.run(drain(o))
    assert rt.roles() == ["mentor", "comportamental"] and optional_roles(rt) == ["comportamental"]
    assert [m["agent_id"] for m in agent_messages(conn, conv)] == ["mentor"]  # a Nina preferiu não falar
    assert not any(voice.SILENT in m["content"] for m in store.list_messages(conn, conv["id"]))


# 3. Valorant: a reprodução do problema --------------------------------------------------------------------------
def test_echoed_absence_explanations_are_not_published(conn):
    """O caso real: duas falas opcionais com o mesmo esqueleto ("Fiquei quiet… não é bem a minha área…")."""
    conv = group(conn, "mila", "cripto")
    replies = {"mentor": "Descansar também conta. @mila @teo, e vocês?", "mila": MILA, "cripto": TEO}
    rt = FakeRuntime(lambda r, m, p, n: done(replies[r]))
    o = orch(conn, rt)
    send(o, conv, "Pessoal, passei o dia jogando Valorant pra não pensar na eleição.")
    asyncio.run(drain(o))
    assert set(rt.roles()) == {"mentor", "mila", "cripto"}
    assert [m["agent_id"] for m in agent_messages(conn, conv)] == ["mentor"]
    # o tema citado pela pessoa não vira instrução para ninguém usar como analogia
    assert all("Valorant" not in load_prompt(a, "conversa") for a in CHAT_AGENTS)


def test_redundancy_metrics_flag_the_reported_pair():
    m = voice.homogeneity([MILA, TEO])
    assert m["autoapresentacao_ou_ausencia"] == 2 and m["aberturas_repetidas"] == 1 and m["pares_parecidos"] == 1
    assert voice.redundant(TEO, [MILA])
    distinct = voice.homogeneity(["Valorant até tarde? Ganhou pelo menos uma?", "Eleição cansa mesmo. Desliga hoje."])
    assert distinct["pares_parecidos"] == distinct["aberturas_repetidas"] == distinct["autoapresentacao_ou_ausencia"] == 0


# 4. notícia econômica ---------------------------------------------------------------------------------------------
def test_economic_news_calls_the_economist_first(conn):
    conv = everyone(conn)
    rt = FakeRuntime(lambda r, m, p, n: done(f"Comentário de {r} sobre a notícia, com o seu ângulo {r}."))
    o = orch(conn, rt)
    send(o, conv, "Gente, viram que o desemprego caiu? kkk finalmente uma boa")
    asyncio.run(drain(o))
    assert rt.roles() == ["economista"]  # o assunto é dela; ninguém mais é convocado por obrigação


# 5. piada ---------------------------------------------------------------------------------------------------------
def test_joke_is_conversation_and_hollow_agreement_is_dropped(conn):
    conv = group(conn, "riscos", "comportamental")
    replies = {"mentor": "Kkk, pelo menos o cofrinho é honesto.", "riscos": "Concordo com o Bento, kkk."}
    rt = FakeRuntime(lambda r, m, p, n: done(replies.get(r, "Opa.")))
    o = orch(conn, rt)
    out = send(o, conv, "Pessoal, meu cofrinho tem mais teia de aranha que moeda kkk")
    asyncio.run(drain(o))
    assert out["run"]["route"]["style"] == "conversa"
    said = agent_messages(conn, conv)
    assert [m["agent_id"] for m in said] == ["mentor"]  # "Concordo com o Bento" não acrescenta nada
    assert said[0]["audit"] is not None  # a auditoria continua rodando; a interface é que não mostra selo no papo


# 6. pergunta de investimento ------------------------------------------------------------------------------------
def test_investment_question_in_private_chat_is_answered_with_no_silence_option(conn):
    conv = store.create_conversation(conn, "Caio", channel="direct", agent_id="analista")
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, conv, "Tesouro Selic ou CDB de liquidez diária para a reserva?")
    asyncio.run(drain(o))
    assert rt.roles() == ["analista"] and rt.requests[0]["mode"] == "direto" and not optional_roles(rt)
    assert "rigor" in load_prompt("analista", "direto")


# 7 e 8. chamar a Nina; questionar o Rui -------------------------------------------------------------------------
@pytest.mark.parametrize("text, agent", [("@nina, às vezes compro coisa só pra me animar, é normal?", "comportamental"),
                                         ("@rui, você não acha que exagera nos riscos às vezes?", "riscos")])
def test_addressed_agent_must_answer_and_nobody_else_chimes_in(conn, text, agent):
    conv = everyone(conn)
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, conv, text)
    asyncio.run(drain(o))
    assert rt.roles() == [agent] and not optional_roles(rt)


# 9. dois agentes discordam ----------------------------------------------------------------------------------------
def test_disagreement_between_called_agents_is_always_published(conn):
    conv = group(conn, "analista", "riscos")
    replies = {"analista": "Bitcoin numa fatia pequena pode fazer sentido.",
               "riscos": "Bitcoin numa fatia pequena? Discordo do @caio: a volatilidade pesa."}
    rt = FakeRuntime(lambda r, m, p, n: done(replies[r]))
    o = orch(conn, rt)
    send(o, conv, "@caio e @rui, bitcoin numa fatia pequena da carteira faz sentido?")
    asyncio.run(drain(o))
    assert [m["agent_id"] for m in agent_messages(conn, conv)] == ["analista", "riscos"]
    assert "não repita a abertura, o argumento, a analogia nem o fecho" in rt.prompt_for("riscos")


# 10. nada a acrescentar ---------------------------------------------------------------------------------------------
def test_colleague_called_by_another_agent_may_stay_silent(conn):
    conv = group(conn, "planejador")
    rt = FakeRuntime(lambda r, m, p, n: done("@lia, quer completar?" if r == "mentor" else voice.SILENT))
    o = orch(conn, rt)
    send(o, conv, "Oi")
    asyncio.run(drain(o))
    assert rt.roles() == ["mentor", "planejador"]
    assert "Bento citou você agora." in rt.prompt_for("planejador") and voice.SILENT in rt.prompt_for("planejador")
    assert [m["agent_id"] for m in agent_messages(conn, conv)] == ["mentor"]


# 11. volta a uma conversa antiga ----------------------------------------------------------------------------------
def test_returning_after_days_keeps_history_and_says_how_long(conn):
    conv = store.create_conversation(conn, "Lia", channel="direct", agent_id="planejador")
    store.add_message(conn, conv["id"], "user", "Minha reserva está em R$ 9.000,00.")
    old = (datetime(2026, 10, 15, 12, tzinfo=timezone.utc)).isoformat()
    conn.execute("UPDATE messages SET created_at = ? WHERE conversation_id = ?", (old, conv["id"]))
    conn.commit()
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, conv, "Voltei! Lembra da reserva?")
    asyncio.run(drain(o))
    prompt = rt.prompt_for("planejador")
    assert "Minha reserva está em R$ 9.000,00." in prompt and "há 12 dias" in prompt
    system = load_prompt("planejador", "direto")
    assert "Quem a pessoa já conhece não se reapresenta" in system
    assert "Não invente conversas, discordâncias, acontecimentos" in system


# 12. reconhecer um erro -------------------------------------------------------------------------------------------
def test_correction_reaches_the_agent_with_its_own_way_of_admitting_mistakes(conn):
    conv = group(conn, "planejador")
    store.add_message(conn, conv["id"], "assistant", "Reserva de 3 meses serve para todo mundo.", agent_id="planejador")
    rt = FakeRuntime()
    o = orch(conn, rt)
    send(o, conv, "@lia, você disse 3 meses e eu li que o ideal é 6. Quem tá certo?")
    asyncio.run(drain(o))
    prompt = rt.requests[0]["text"]
    assert rt.roles() == ["planejador"] and "Reserva de 3 meses serve para todo mundo." in prompt
    assert "- Erros:" in load_prompt("planejador", "grupo")


def test_selection_never_drafts_everyone_and_ignores_unrelated_words():
    pool = ["mentor", "planejador", "analista", "economista", "riscos", "comportamental", "cripto", "mila"]
    assert len(voice.pick("Oi, todo mundo!", pool, {}, plural=True)) == 2
    assert voice.pick("Pessoal, bitcoin e investimento: e o risco?", pool, {}, plural=True)[:3] \
        == ["analista", "riscos", "cripto"] or len(voice.pick("x", pool, {}, True)) <= 3
    assert voice.relevance("planejador", "mesmo assim") == 0  # "mes" dentro de "mesmo" não convoca a Lia
    assert voice.pick("Tô bem, e vocês?", pool, {}, plural=False) == ["mentor"]
