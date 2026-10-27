# Especificação de produto

A especificação completa é o **plano mestre "Meu Patrimônio AI" v1.1 (26/10/2026)**. Salve o arquivo original como
`docs/PROJETO_MEU_PATRIMONIO_AI_OPENBOT.md`; ele é a referência para escopo, fases e critérios de aceite.

Mapa rápido do que já está coberto no código:

| Seção do plano | Onde |
|---|---|
| 4 — Equipe de agentes e handoff | `agents/`, `financial_engine/handoff.py` |
| 8 — Modelo de dados | `backend/app/schema.sql`, `DATA_DICTIONARY.md` |
| 9 — Motor de simulação e testes 9.4 | `financial_engine/projection.py`, `tests/unit/test_projection.py` |
| 10 — Segurança | `SECURITY_MODEL.md`, `tests/security/` |
| 11 — Qualidade das respostas | `financial_engine/audit.py` |
| 24.4 — "O que fazer com meu dinheiro este mês?" | `financial_engine/budget.py::monthly_guidance` |
| 24.9 — Critérios do mentor | `tests/unit/test_mentor_guidance.py` |
