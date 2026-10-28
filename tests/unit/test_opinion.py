# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parecer estruturado do Conselho: posição declarada, seções, mapa de posições e dissenso na síntese."""
from team import opinion, routing, verdict

FULL = ("**Posição:** contrária\n\n## Tese\nNão agora.\n\n## Evidências\nReserva de 3 meses.\n\n## Fontes\nRetrato.\n\n"
        "## Hipóteses\nRenda estável.\n\n## Riscos\nPerda.\n\n## Lacunas\nPrazo.\n\n## Não agir\nRazoável.")


def test_reads_declared_stance_and_sections():
    assert opinion.stance(FULL) == "contraria"
    assert opinion.stance("Posição: Sem base suficiente para opinar") == "insuficiente"
    assert opinion.stance("**Posição**: Favorável, com ressalvas") == "favoravel"
    assert opinion.stance("Minha posição é contrária.") is None  # precisa ser declarada no formato
    assert opinion.problems(FULL) == []
    assert set(opinion.summary(FULL)["sections"]) == set(opinion.SECTIONS)


def test_missing_structure_is_reported():
    reasons = opinion.problems("Acho arriscado.\n\n## Tese\nNão.\n\n## Riscos\n")
    assert any("sem posição" in r for r in reasons)
    assert any("Evidências" in r and "Riscos" in r for r in reasons)  # seção vazia não conta
    assert opinion.problems("**Posição:** condicional (revista)", ()) == []  # contestação só exige a posição


def test_conflict_and_contested_only_between_opposed_sides():
    stances = {"analista": "favoravel", "riscos": "contraria", "planejador": "condicional", "economista": None}
    assert opinion.conflict(stances)
    assert opinion.contested(stances) == ["analista", "riscos"]
    assert not opinion.conflict({"analista": "favoravel", "riscos": "condicional"})
    assert opinion.contested({"analista": "favoravel", "riscos": "condicional"}) == []


def test_position_map_records_initial_and_final():
    initial = {"analista": "favoravel", "riscos": "contraria"}
    kept = opinion.position_map(initial, initial)
    assert "| Caio | favorável | favorável |" in kept and "Divergência material mantida" in kept
    resolved = opinion.position_map(initial, {"analista": "condicional", "riscos": "contraria"})
    assert "não se manteve" in resolved
    calm = opinion.position_map({"analista": "condicional"}, {"analista": "condicional"})
    assert "| Caio | condicional | — |" in calm and "Sem divergência material" in calm


def test_synthesis_must_name_every_dissenter():
    dissent = ["analista", "cripto", "riscos"]
    ok = "Resumo.\n\n## Divergências\n- @caio e Téo × @rui.\n\n## Próximos passos\n."
    assert opinion.dissent_problems(ok, dissent) == []
    # "ruim" não é o Rui, e "risco" (apelido antigo) não prova que ele foi citado
    partial = "## Divergências\n- @caio e @teo acham o risco ruim.\n"
    assert opinion.dissent_problems(partial, dissent) == ["A síntese apaga a divergência de Rui."]
    # nome citado fora da seção não vale
    outside = "Caio, Téo e Rui falaram.\n\n## Divergências: nenhuma relevante"
    assert opinion.dissent_problems(outside, dissent)
    assert "não tem a seção" in opinion.dissent_problems("Sem seção.", dissent)[0]
    assert opinion.dissent_problems("qualquer coisa", []) == []


def test_crypto_specialist_joins_only_crypto_questions():
    first, second = routing.council_agents("Devo pôr a reserva em Bitcoin?")
    assert "cripto" in first and second == ("riscos", "comportamental")
    assert "cripto" not in routing.council_agents("Quito o financiamento do carro?")[0]
    assert "cripto" in routing.council_agents("E stablecoins como USDC?")[0]
    assert routing.resolve_handle("cripto") == "cripto" and routing.resolve_handle("ativos-digitais") == "cripto"
    # nomes novos e @menções antigas apontam para o mesmo id estável
    assert [routing.resolve_handle(h) for h in ("bento", "mentor", "lia", "planejador", "rui", "riscos", "nina",
                                                 "conselheiro", "teo", "Téo")] == [
        "mentor", "mentor", "planejador", "planejador", "riscos", "riscos", "comportamental", "comportamental",
        "cripto", "cripto"]


def test_verdict_sections_and_structured_mentions():
    text = ("## Conclusão\nNão agora.\n\n## Concordâncias\n- @lia e @rui concordam que a **reserva** vem antes.\n"
            "## Divergências\n- @caio vê espaço; @rui discorda.\n\n## Riscos\n- @rui: concentração.\n"
            "- @ninguem e @bento@x não viram menção\n\n## Próximos passos\n1. Rever a reserva\n2. Não agir")
    v = verdict.parse(text, {"planejador", "riscos", "analista", "mentor"})
    assert [s["key"] for s in v["sections"]] == ["conclusao", "concordancia", "diverg", "risco", "proxim"]
    agree = v["sections"][1]["items"][0]
    assert agree == [{"agent": "planejador"}, {"t": " e "}, {"agent": "riscos"},
                     {"t": " concordam que a reserva vem antes."}]  # sem ** (texto puro)
    risks = v["sections"][3]["items"]
    assert risks[1] == [{"t": "@ninguem e "}, {"agent": "mentor"}, {"t": "@x não viram menção"}]
    assert v["sections"][4]["items"] == [[{"t": "Rever a reserva"}], [{"t": "Não agir"}]]
    assert v["mentioned"] == ["planejador", "riscos", "analista", "mentor"]
    # quem não participou da reunião não vira menção
    assert verdict.parse("## Conclusão\nx\n## Riscos\n- @vera falou", {"riscos"})["sections"][1]["items"] == [
        [{"t": "@vera falou"}]]
    assert verdict.parse("Texto livre sem seções.", {"riscos"}) is None
    assert verdict.parse("## Divergências: nenhuma relevante\n## Riscos\n- x", {"riscos"}) is None  # sem conclusão


def test_prompts_get_display_names_from_registry():
    from mentor.session import load_prompt

    prompt = load_prompt("riscos", "conselho_parecer")
    assert "Seu nome é Rui." in prompt and "- Lia (@lia): Planejadora" in prompt and "**Posição:**" in prompt
