# Meu Patrimônio AI

Mentor financeiro **local-first** para pessoa física no Brasil: diagnóstico, reserva, dívidas, simulação de aportes e
acompanhamento de metas, operado por agentes no OpenBot, **sem nenhum caminho técnico para movimentar dinheiro**.

> Ferramenta de educação, organização e simulação. Não substitui consultoria autorizada nem garante retornos.
> Nenhuma operação financeira é executada pelo sistema.

**Estado:** Fase 0 concluída no repositório + protótipo do motor/API da Fase 1, **somente com dados fictícios**.
Ver [`docs/PHASE0_PLAN.md`](docs/PHASE0_PLAN.md).

## Início rápido
```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync
scripts/run_tests.sh
uv run python scripts/demo.py iniciante-150 150 120
```

## Estrutura
| Caminho | O quê |
|---|---|
| `backend/financial_engine/` | Motor determinístico (Decimal): taxas, projeções, diagnóstico, auditoria |
| `backend/app/agent_api.py` | API GET-only para os agentes (loopback + token + só dados sintéticos) |
| `backend/app/schema.sql` | Esquema SQLite v1 |
| `agents/` | Instruções AG-00..AG-06 para colar no OpenBot |
| `tests/` | Unidade, integração e segurança; `fixtures_synthetic/` |
| `docs/` | Plano da Fase 0, segurança, métodos, dados, contratos, decisões, runbook |

Nunca coloque extratos reais, tokens ou base pessoal neste repositório.
