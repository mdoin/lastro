# Auditoria do repositório para a versão open source (etapa 1)

Data: 2026-10-27. Base: `origin/main` em `aa1702a` (9 commits, 225 arquivos versionados).
Escopo: código, configuração, documentação e **todo o histórico Git** (`git log --all -p`).

## 1. Resumo

| Item | Resultado |
|---|---|
| Segredos no estado atual | nenhum encontrado (chaves de API, tokens, chaves privadas, senhas) |
| Segredos no histórico | nenhum encontrado (mesmos padrões em todos os commits e branches) |
| Dados financeiros reais | nenhum: `tests/fixtures_synthetic/` e os testes usam só personas fictícias |
| Infraestrutura pessoal | **sim**, no estado atual e no histórico (ver §3) |
| Dados pessoais no histórico | **sim**: o e-mail pessoal da autora aparece como autor do commit `9560e1c` |
| Dependência específica do Claude | **sim**, concentrada no worker do mentor (ver §4) |
| Licenças de dependências | todas compatíveis com Apache-2.0 e AGPL-3.0 (ver §6) |
| Código de terceiros copiado | nenhum indício; o OpenBot foi usado só como referência de conceitos |

**Nada do que foi encontrado é credencial**, então a preparação não foi interrompida. Os pontos de §3 precisam
de decisão da dona antes de qualquer publicação (o histórico não foi reescrito).

## 2. Como a varredura foi feita
- `git log --all -p` filtrado por padrões de chaves (`sk-ant-`, `sk-proj-`, `sk-…`, `ghp_`, `github_pat_`, `AKIA…`,
  `xox?-`, `-----BEGIN … PRIVATE KEY-----`, `api_key=`, `token=`, `password=`) e por nomes de arquivos sensíveis
  (`.env`, `*.db`, `*.sqlite`, `*.pem`, `*.key`, `*.ofx`, `*.csv`, `*.xlsx`, `backup`, `credential`, `secret`).
- Busca no estado atual por domínios, IPs, caminhos absolutos (`/home`, `/srv`, `/opt`) e nomes de usuário.
- O teste `tests/security/test_repo_hygiene.py` passou a cobrir também domínios e IPs privados (ver §7).
- Ferramentas dedicadas (gitleaks, trufflehog) não estavam instaladas nesta máquina. **Rode uma delas antes de
  publicar** (o workflow de CI criado roda o gitleaks em todo push).

## 3. Dependências da infraestrutura pessoal

| Onde | O quê | Tratamento |
|---|---|---|
| `deploy/caddy/Caddyfile`, `docs/LASTRO_ARCHITECTURE.md`, `docs/WEB_API.md` | domínio da instância pessoal | Caddyfile usa `{$LASTRO_DOMAIN}`; docs com `lastro.example.com` |
| `docs/PENDING.md` | IP público do servidor e registro DNS | removido do estado atual; **permanece no histórico** |
| `deploy/systemd/*.service`, `scripts/deploy.sh`, `deploy/lastro-admin` | `/opt/meu-patrimonio`, `/etc/meu-patrimonio`, `/var/lib/patrimonio`, usuários `patrimonio`/`mentor` | mantidos como a **instalação systemd** (genérica, sem domínio); a distribuição principal passa a ser Docker Compose |
| `deploy/systemd/lastro-mentor.service` | comentário cita outro projeto da dona ("prumo") | removido |
| `deploy/apparmor/lastro-chrome`, testes do navegador | `/opt/lastro-browsers/...` | caminho vira configurável (`LASTRO_BROWSER_EXECUTABLE`) |
| `docs/DECISIONS.md`, `docs/RUNBOOK.md` | `~/.local/opt/node`, instalação manual no servidor | mantidos como histórico de decisões; RUNBOOK aponta para o guia de instalação |
| commit `9560e1c` | autor com e-mail pessoal (os demais commits usam o endereço `noreply` do GitHub) | **decisão sua** (ver §8) |
| `.claude/launch.json` | caminhos da máquina local | já ignorado pelo `.gitignore`, nunca versionado |

## 4. Dependências específicas do Claude (modelo atual de execução)

```
web app (FastAPI, SQLite rw) ── socket Unix, JSON por linha ──► worker do mentor (usuário mentor)
   ops: turn | ephemeral | panel | interrupt | status              │ claude_agent_sdk.ClaudeSDKClient
                                                                   │ (binário do Claude Code embutido no wheel)
                                                                   │ ferramentas: servidor MCP em processo
                                                                   ▼
                                     API de leitura (GET, loopback, token) ── SQLite mode=ro
```

| Arquivo | Acoplamento |
|---|---|
| `backend/mentor/runner.py` | traduz `StreamEvent`, `AssistantMessage`, `RateLimitEvent`, `ResultMessage` do SDK |
| `backend/mentor/session.py` | monta `ClaudeAgentOptions` (`tools=[]`, `setting_sources=[]`, `can_use_tool`, `max_turns`) |
| `backend/mentor/tools.py` | ferramentas declaradas com `@tool` e `create_sdk_mcp_server` do SDK |
| `backend/mentor/worker.py` | `ClaudeSDKClient` por conversa; `auth_status()` chama o CLI embutido; mensagens "assinatura"/"Claude" |
| `backend/app/store.py`, migração 002 | coluna `conversations.claude_session_id` |
| `backend/app/web.py` `/api/status`, `frontend/src/pages/Settings.tsx`, `Layout.tsx`, `Overview.tsx` | campos `logged_in`/`subscription` e textos sobre "assinatura" |
| `pyproject.toml` | `claude-agent-sdk` obrigatório |

**O que já é independente de provedor** (não precisa mudar): motor financeiro (`financial_engine/`), metas,
projeções, retratos, Diário de Decisões, Diário de Oportunidades, motor determinístico do Radar (`radar/`),
auditor determinístico (`team/auditor.py`), roteamento e orquestração da equipe (`app/orchestrator.py`, que só
fala o protocolo do worker), memória financeira e notas (`financial_facts`, `agent_notes`), coletor de séries.

### Observação sobre termos de uso do Claude
A instância pessoal usa o Claude Agent SDK autenticado com a assinatura da dona. A página
[Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) diz que quem constrói produtos com o
Agent SDK deve usar **API key** e que terceiros não podem oferecer login do Claude.ai nem intermediar credenciais
de assinatura; também diz que isso não impede o usuário final de entrar com a própria assinatura no **binário
oficial e não modificado** do Claude Code. Por isso, na distribuição:
- o adaptador `anthropic` (API key, Messages API) é o caminho recomendado para Claude;
- o adaptador `claude_code` roda o binário oficial; o **operador** faz login pelo fluxo da própria Anthropic
  (`claude auth login`) dentro do container do mentor, e o Lastro nunca lê, copia nem guarda esse token;
- nenhuma tela do Lastro coleta credencial de assinatura.
Recomendo que você confirme essa leitura dos termos para o uso pessoal atual (é uma decisão sua, não técnica).

## 5. Componentes que podem ser generalizados
1. **Runtime do agente** → contrato `AI Provider Runtime` (`backend/providers/`), com adaptadores por provedor.
2. **Ferramentas** → especificação neutra (nome, descrição, JSON Schema, handler); cada adaptador converte para o
   formato do provedor (MCP no Claude Code e no Codex, function calling nas APIs).
3. **Barreira de ferramentas** (`tool_gate`) → aplicada no runtime, antes de qualquer handler, para todos os
   provedores.
4. **Sessão** → estado persistente do agente (histórico, memória, notas, relatórios, decisões) fica no banco do
   Lastro; a sessão nativa do provedor é cache descartável, identificada por provedor.
5. **Fuso, moeda e idioma** → hoje fixos (`America/Sao_Paulo`, BRL, pt-BR); viram configuração da instalação.
6. **Senha inicial** → hoje só por terminal (`lastro-admin set-password`); vira assistente com token de instalação.
7. **Implantação** → systemd + Caddy específicos viram Docker Compose genérico, mantendo a separação de privilégios.

## 6. Licenças
- **Python** (venv, 44 distribuições): MIT, BSD-2/3, Apache-2.0, ISC, PSF, MPL-2.0 (`certifi`, só dados).
  `claude-agent-sdk` é MIT, **mas o wheel embute o binário do Claude Code**, regido pelos termos comerciais da
  Anthropic. Por isso ele passa a ser dependência **opcional** (`--extra claude-code`) e as imagens Docker não o
  incluem por padrão. Imagens publicadas não devem redistribuir esse binário.
- **npm** (`package-lock.json`, 194 pacotes): MIT 154, Apache-2.0 23, ISC 2, BSD-3 1, OFL-1.1 2 (fontes Inter e
  Geist Mono), MPL-2.0 12 (`lightningcss`, só ferramenta de build, não vai no pacote).
- **Ativos próprios**: marca (`docs/brand/`), mascotes em pixel art (`frontend/src/components/mascots.ts`, autorais),
  capturas de tela (dados fictícios).
- **OpenBot** (PolyForm Noncommercial 1.0.0): incompatível com Apache-2.0 e AGPL-3.0 para incorporação de código.
  O repositório declara (`docs/LASTRO_ARCHITECTURE.md`) que só ideias foram estudadas; não há trechos copiados nem
  arquivos de origem dele. A camada nova de provedores foi escrita do zero, a partir da documentação oficial de
  cada provedor.

Recomendação de licença: ver [`LICENSING.md`](LICENSING.md). Nenhuma licença foi aplicada.

## 7. Testes de base
`pytest` no Windows (máquina de desenvolvimento): 368 passam, 19 falham/erram, todos por limitação da plataforma
(`asyncio.start_unix_server`, `os.getuid`, encoding do `scripts/demo.py`). No Linux (alvo de produção) a suíte é a
mesma do deploy. O CI criado roda em Linux.

## 8. Decisões que dependem de você
1. **Histórico**: o e-mail pessoal (commit `9560e1c`), o domínio e o IP do servidor ficam no histórico.
   Opções: (a) publicar como está; (b) publicar um repositório novo a partir de um único commit limpo
   (não destrói o histórico privado); (c) reescrever o histórico (destrutivo, exige sua autorização).
   Recomendo (b).
2. **Licença** (ver `LICENSING.md`).
3. **Uso da assinatura do Claude na instância pessoal** (§4).
4. **Sign in with ChatGPT**: a documentação diz que o recurso é oferecido a parceiros selecionados; o adaptador
   está implementado e **desligado** até haver confirmação de elegibilidade (ver `PROVIDERS.md`).
