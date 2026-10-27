# Lastro

Mentor financeiro pessoal **self-hosted**, brasileiro e **independente de provedor de IA**: retratos financeiros,
diagnóstico, metas, projeções, simulações, Radar de oportunidades, Diário de Oportunidades e Diário de Decisões, com
uma equipe de agentes (Mentor, especialistas, Conselho e Auditor) que roda no modelo que você escolher.

> Ferramenta de educação, organização e simulação. Não substitui consultoria autorizada nem garante retornos.
> **Nenhuma operação financeira é executada pelo sistema**: não há caminho técnico para mover dinheiro.

- **Seus dados, sua instalação.** Cada instalação guarda os próprios dados, configurações e credenciais. Não há conta
  central nem servidor do projeto no meio.
- **Qualquer IA, por métodos autorizados.** Claude (API key ou o Claude Code oficial), OpenAI (API key ou o Codex
  oficial com a conta do ChatGPT), Gemini, OpenRouter, Ollama e endpoints compatíveis. Cada agente pode usar um
  provedor e um modelo diferentes.
- **Núcleo verificável.** Contas, metas, projeções, Radar e auditorias matemáticas são determinísticos (Decimal) e
  funcionam sem IA. A IA interpreta, explica e coordena; os números vêm do motor.

## Instalação rápida (Linux + Docker)

```bash
git clone <URL-do-repositório> lastro && cd lastro
sh scripts/init-env.sh            # cria .env com segredos aleatórios
docker compose build
docker compose up -d
docker compose exec web cat /data/setup-token   # token para criar a conta administrativa
```

Abra `http://127.0.0.1:8080` e siga o assistente: conta administrativa, região, provedor de IA (com teste de conexão),
modelo do Mentor e diagnóstico. Guia completo, HTTPS e acesso remoto: [docs/INSTALL.md](docs/INSTALL.md).

## O que funciona com e sem IA

| Sem IA (determinístico) | Com um modelo de IA |
|---|---|
| Retratos financeiros, diagnóstico, reserva e dívidas | Mentor e especialistas (Planejador, Analista, Economista, Riscos, Conselheiro) |
| Metas, projeções e simulações | Conselho multiagente com Auditor |
| Motor do Radar e Diário de Oportunidades | Pareceres do Radar |
| Diário de Decisões, histórico e auditoria matemática | Rotinas com análise |

Provedores externos recebem o contexto necessário a cada pergunta (por exemplo, seu retrato financeiro numa pergunta
sobre reserva). Com um modelo local (Ollama), nada sai da sua máquina. Detalhes: [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Documentação

| Tema | Arquivo |
|---|---|
| Instalação, HTTPS, acesso remoto | [docs/INSTALL.md](docs/INSTALL.md) |
| Atualização de versão | [docs/UPGRADE.md](docs/UPGRADE.md) |
| Backup e restauração | [docs/BACKUP.md](docs/BACKUP.md) |
| Provedores de IA e capacidades | [docs/PROVIDERS.md](docs/PROVIDERS.md) |
| Termos dos provedores (assinaturas Claude/ChatGPT) | [docs/PROVIDER_TERMS.md](docs/PROVIDER_TERMS.md) |
| Arquitetura | [docs/LASTRO_ARCHITECTURE.md](docs/LASTRO_ARCHITECTURE.md), [docs/MULTIAGENT.md](docs/MULTIAGENT.md) |
| Segurança | [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md), [SECURITY.md](SECURITY.md) |
| Fontes de dados | [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) |
| Métodos financeiros | [docs/FINANCIAL_METHODS.md](docs/FINANCIAL_METHODS.md) |
| Radar e Diários | [docs/RADAR.md](docs/RADAR.md), [docs/DIARIO.md](docs/DIARIO.md) |
| Testes | [docs/TESTING.md](docs/TESTING.md) |
| Como contribuir | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Desenvolvimento

```bash
uv sync --extra claude-code       # Python 3.12+, uv 0.12+
uv run pytest -q
(cd frontend && npm ci && npm test && npm run dev)
```

Estrutura: `backend/financial_engine` (motor), `backend/app` (web e API de leitura), `backend/providers` (AI Provider
Runtime), `backend/mentor` (worker dos agentes), `backend/team` (registro e roteamento), `backend/radar`,
`backend/integrations` (séries oficiais), `frontend/` (React), `tests/` (unidade, integração, segurança).

## Licença

**Ainda não definida.** A recomendação fundamentada está em [docs/LICENSING.md](docs/LICENSING.md); até a decisão,
nenhuma licença de uso é concedida. Nome e marca "Lastro" (`docs/brand/`) não fazem parte da licença do código.

O desenho de execução de agentes foi inspirado no estudo do OpenBot (PolyForm Noncommercial); nenhum código dele foi
incorporado.
