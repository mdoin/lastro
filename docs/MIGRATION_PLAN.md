# Plano de migração: Lastro self-hosted e multi-provedor (etapa 2)

Princípio: **o protocolo entre web app e worker não muda** (`turn`, `ephemeral`, `panel`, `interrupt`,
`status`). O orquestrador, o Radar, o Diário e o motor financeiro continuam como estão. A troca acontece dentro
do worker, atrás de um contrato comum, e ganha operações novas para conexões de provedores.

## Fronteiras

```
web app ─ dono do banco (rw), autenticação do Lastro, configuração por agente (agente → conexão + modelo)
   │ socket Unix (mesmo protocolo + ops providers.*)
worker ─ dono das credenciais de IA (arquivo 0600 no volume do worker), AI Provider Runtime, barreira de ferramentas
   │ HTTP loopback + token
agent-api ─ leitura do banco (mode=ro)
```

- O web app **nunca** recebe segredo de IA de volta: só estado mascarado (`sk-…abcd`), capacidades e modelos.
- O worker **nunca** abre o banco.
- Trocar `base_url` de uma conexão apaga o segredo dela (um web app comprometido não consegue redirecionar uma
  chave existente para outro servidor).

## Etapas e entregas

| # | Etapa | Entrega | Verificação |
|---|---|---|---|
| 1 | Auditoria | `OPEN_SOURCE_AUDIT.md` | revisão |
| 2 | Plano | este arquivo | revisão |
| 3 | Abstração | `backend/providers/base.py` (contrato, capacidades, erros), `toolspec.py` (ferramentas neutras + barreira), `loop.py` (laço de ferramentas para APIs) | testes do contrato |
| 4 | Adaptadores | `claude_code` (SDK atual), `anthropic` (Messages API), `openai` (Responses API; API key ou token do Sign in with ChatGPT), `openai_compatible` (Ollama, LM Studio, vLLM, OpenRouter, Gemini), `codex` (app-server, experimental) | testes com transporte HTTP simulado e app-server falso |
| 5 | Credenciais | `providers/credentials.py` (arquivo atômico 0600), ops `providers.*` no worker, `providers/chatgpt_oauth.py` (PKCE, state, nonce, ID token, escopos, refresh, revogação) | testes de isolamento e do fluxo OAuth com chaves locais |
| 6 | Configuração por agente | migração 008 (`agent_models`, `conversations.provider_session`), web envia `connection`/`model` por passo | testes de troca de provedor sem perda |
| 7 | Onboarding | `/api/setup/*` com token de instalação, tela de assistente, seção de provedores nas Configurações | testes de API |
| 8 | Self-hosted | `Dockerfile`, `compose.yaml`, `.env.example`, backup/restauração no `lastro-admin` | testes de backup/migração; `docker compose config` no CI |
| 9 | Testes | os 20 cenários de `docs/TESTING.md` mapeados para arquivos | `pytest` + `vitest` |
| 10 | Auditoria de publicação | `PUBLICATION_CHECKLIST.md`, teste de higiene ampliado, gitleaks no CI | CI |
| 11 | Documentação | README, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, CHANGELOG, guias | revisão |
| 12 | Release | `CHANGELOG.md` 0.3.0, sem tag, sem push, sem licença aplicada | — |

## Compatibilidade com a instalação atual
- Sem conexões configuradas, o worker cria uma conexão implícita `claude_code` (o comportamento de hoje), então a
  instância pessoal continua funcionando sem nenhuma ação após o deploy.
- A migração 008 só acrescenta tabela e coluna; `claude_session_id` continua sendo lido para retomar sessões
  antigas do Claude Code.
- As unidades systemd continuam válidas; o Docker Compose é um modo novo de instalação, não substituto obrigatório.

## Riscos aceitos e limites declarados
- Modelos locais podem não suportar ferramentas: o adaptador declara `tools=False` e o agente responde sem dados.
- Sessão nativa não é retomada entre provedores; o contexto é reconstruído do histórico do Lastro.
- Codex app-server: integração experimental, desligada por padrão, porque o app-server traz ferramentas nativas
  (shell) que o Lastro só consegue negar por aprovação, não remover.
- Sign in with ChatGPT: desligado até confirmação de elegibilidade do projeto.
