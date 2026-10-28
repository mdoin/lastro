# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parecer estruturado do Conselho: posição declarada, seções, mapa de posições e dissenso na síntese."""
from team import opinion, routing

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
    assert "| Analista | favorável | favorável |" in kept and "Divergência material mantida" in kept
    resolved = opinion.position_map(initial, {"analista": "condicional", "riscos": "contraria"})
    assert "não se manteve" in resolved
    calm = opinion.position_map({"analista": "condicional"}, {"analista": "condicional"})
    assert "| Analista | condicional | — |" in calm and "Sem divergência material" in calm


def test_synthesis_must_name_every_dissenter():
    dissent = ["analista", "cripto", "riscos"]
    ok = "Resumo.\n\n## Divergências\nAnalista e Analista de Ativos Digitais × Gestor de Riscos.\n\n## Próximo passo\n."
    assert opinion.dissent_problems(ok, dissent) == []
    # "Analista de Ativos Digitais" não conta como menção ao Analista
    partial = "## Divergências\nO Analista de Ativos Digitais discorda do Gestor de Riscos.\n"
    assert opinion.dissent_problems(partial, dissent) == ["A síntese apaga a divergência de Analista."]
    # nome citado fora da seção não vale
    outside = "O Analista, o Analista de Ativos Digitais e o Gestor de Riscos falaram.\n\n## Divergências: nenhuma relevante"
    assert opinion.dissent_problems(outside, dissent)
    assert "não tem a seção" in opinion.dissent_problems("Sem seção.", dissent)[0]
    assert opinion.dissent_problems("qualquer coisa", []) == []


def test_crypto_specialist_joins_only_crypto_questions():
    first, second = routing.council_agents("Devo pôr a reserva em Bitcoin?")
    assert "cripto" in first and second == ("riscos", "comportamental")
    assert "cripto" not in routing.council_agents("Quito o financiamento do carro?")[0]
    assert "cripto" in routing.council_agents("E stablecoins como USDC?")[0]
    assert routing.resolve_handle("cripto") == "cripto" and routing.resolve_handle("ativos-digitais") == "cripto"
