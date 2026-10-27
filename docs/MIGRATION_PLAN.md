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
| 4 | Adaptadores | `claude_code` (SDK atual), `anthropic` (Messages API), `openai` (Responses API, API key), `openai_compatible` (Ollama, LM Studio, vLLM, OpenRouter, Gemini), `codex` (app-server, experimental) | testes com transporte HTTP simulado e app-server falso |
| 5 | Credenciais | `providers/credentials.py` (arquivo atômico 0600), operação `providers` no worker; login pelos executáveis oficiais no desenho do OpenBot (`cli_login.py` para o Claude Code, device code no Codex) | testes de isolamento e dos fluxos com CLIs falsos |
| 6 | Configuração por agente | migração 008 (`agent_models`, `conversations.session_connection`, `app_settings`), web envia `connection`/`model` por passo | testes de troca de provedor sem perda |
| 7 | Onboarding | `/api/setup/*` com token de instalação, tela de assistente, seção de provedores nas Configurações | testes de API |
| 8 | Self-hosted | `Dockerfile`, `compose.yaml`, `.env.example`, backup/restauração no `lastro-admin` | testes de backup/migração; `docker compose config` no CI |
| 9 | Testes | os 20 cenários de `docs/TESTING.md` mapeados para arquivos | `pytest` + `vitest` |
| 10 | Auditoria de publicação | `RELEASE.md`, teste de higiene ampliado, gitleaks no CI | CI |
| 11 | Documentação | README, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, CHANGELOG, guias | revisão |
| 12 | Release | `CHANGELOG.md` 0.3.0, AGPL-3.0-or-later + DCO + política de marca; sem tag, sem push | — |

## Compatibilidade com a instalação atual
- Sem conexões configuradas, o worker cria uma conexão implícita `claude_code` (o comportamento de hoje), então a
  instância pessoal continua funcionando sem nenhuma ação após o deploy.
- A migração 008 só acrescenta tabela e coluna; `claude_session_id` continua sendo lido para retomar sessões
  antigas do Claude Code.
- As unidades systemd continuam válidas; o Docker Compose é um modo novo de instalação, não substituto obrigatório.

## Riscos aceitos e limites declarados
- Modelos locais podem não suportar ferramentas: o adaptador declara `tools=False` e o agente responde sem dados.
- Sessão nativa não é retomada entre provedores; o contexto é reconstruído do histórico do Lastro.
- Codex app-server: integração experimental (depende de campos `experimentalApi`) e fora da imagem por padrão. As
  ferramentas nativas são desligadas por flags do próprio Codex e o que ainda pedir aprovação é recusado; se uma
  versão futura ignorar essas flags, o isolamento cai para a sandbox read-only e o container sem o banco.
- Sign in with ChatGPT (token sharing): não implementado até confirmação de elegibilidade; a conta do ChatGPT entra
  pelo login oficial do Codex.
