# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lastro Radar: monitoramento determinístico, Diário de Oportunidades e avaliação histórica.

Separação de responsabilidades (ver docs/RADAR.md):
- observations: observações versionadas por fonte (revisões nunca sobrescrevem);
- rules: regras versionadas e avaliação determinística (sem rede, sem modelo);
- evaluator: qualidade dos dados, adequação ao perfil, classificação e hipótese verificável;
- journal: registro imutável encadeado por hash, linha do tempo, decisões da pessoa;
- alerts: deduplicação, cooldown, silêncio, limites e histórico de entrega;
- outcomes: avaliação posterior por horizonte, com método por tipo de produto;
- metrics / backtest: qualidade do Radar e testes históricos sem dados futuros;
- engine: o laço que liga tudo e aciona o Conselho só quando acrescenta valor.

Nada aqui executa operação financeira: o Radar observa, registra e avalia.
"""
