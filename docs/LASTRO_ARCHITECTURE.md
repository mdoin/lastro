# Lastro — arquitetura em produção (Fase 1)

Lastro é o nome do produto; o repositório continua `meu-patrimonio-ai`.

```
 Navegador ──HTTPS──► Caddy no host (caddy.service, usuário caddy; Let's Encrypt)
                            │  lastro.doinlabs.com.br · API admin só em socket Unix 0600 (/var/lib/caddy/admin.sock)
                            ▼
              lastro-web  (usuário patrimonio, 127.0.0.1:8080; confia em X-Forwarded-For só de 127.0.0.1)
              FastAPI + frontend estático · login · SQLite rw · agendador de rotinas
                            │ socket Unix /run/lastro-mentor/mentor.sock (grupo lastro-sock, 0660; o worker confere
                            │ o usuário do processo que conectou com SO_PEERCRED)
                            ▼
              lastro-mentor  (usuário mentor)
              Claude Agent SDK · Claude Code embutido · assinatura do dono
              tools=[] · setting_sources=[] · MCP em processo, só leitura · ferramentas por papel · can_use_tool nega o resto
              teto de passos (max_turns) e prazo por turno · navegador de pesquisa (Chrome headless, AppArmor lastro-chrome)
              saída: internet sim (Anthropic, fontes oficiais); redes privadas/metadados NÃO (IPAddressDeny)
                            │ HTTP loopback + token (arquivo 0640 root:mentor)
                            ▼
              patrimonio-agent-api  (usuário patrimonio, 127.0.0.1:8765)
              GET apenas · SQLite aberto com mode=ro + query_only · rede só loopback
```

## Separação de privilégios
| Usuário | Pode | Não pode |
|---|---|---|
| `patrimonio` | ler/escrever o banco (`/var/lib/patrimonio`), falar com o socket do mentor | rodar o Claude; ler o home do mentor |
| `mentor` | rodar o Claude com a assinatura; chamar a API de leitura com token | abrir o banco; escrever código em `/opt`; alcançar redes privadas |
| `root` | implantar (`scripts/deploy.sh`), administrar (`lastro-admin`) | — |

O código fica em `/opt/meu-patrimonio`, de propriedade do root (nenhum serviço consegue alterá-lo).
O binário do Claude usado é o embutido no SDK, também em `/opt` (o `mentor` não consegue trocá-lo).

## Peças
| Arquivo | Papel |
|---|---|
| `backend/app/web.py` | rotas de `docs/WEB_API.md`, cabeçalhos de segurança, CSRF (`X-Lastro` + Origin), SPA |
| `backend/app/orchestrator.py` | equipe: fila persistente, roteamento, delegação, Conselho, auditoria (ver `MULTIAGENT.md`) |
| `backend/team/` | registro de agentes, roteamento/@menções, auditor determinístico (sem rede, sem banco) |
| `backend/financial_engine/calculator.py` | calculadora única dos agentes (ferramenta `calcular`) |
| `backend/integrations/` | catálogo e coletor de séries oficiais e do Tesouro Direto (serviço `lastro-coletor`) |
| `backend/radar/` | Radar e Diário de Oportunidades: regras, avaliação, alertas, registro imutável, avaliação posterior (`RADAR.md`) |
| `backend/app/radar_web.py` | rotas `/api/radar/*` |
| `backend/app/turns.py` | turnos legados do chat/painel (rotinas) em segundo plano |
| `backend/app/routines.py` | agenda (fuso IANA), idempotência, perdidas (`skip`/`run_once`), sobreposição, `quiet` |
| `backend/app/auth.py` | scrypt, sessões só como hash, bloqueio por cliente (IP; IPv6 por /64) + atraso global limitado |
| `backend/app/views.py` | diagnóstico/projeção/metas compartilhados entre web e API de leitura |
| `backend/mentor/worker.py` | um processo do Claude por conversa, limite global, espera de limite da assinatura, painel |
| `backend/mentor/tools.py` | as ferramentas de leitura (únicas que o modelo enxerga) e as capacidades de cada papel |
| `backend/mentor/browser.py` | navegador de pesquisa: allowlist, cada salto de redirecionamento conferido, Chrome sem rede própria |
| `backend/mentor/prompts/` | `_base.md` (regras) + um arquivo por papel |

## Agentes em paralelo (painel)
Especialistas `diagnostico`, `simulacao`, `riscos` e `educacao` rodam ao mesmo tempo, em sessões descartáveis
(limite: `LASTRO_MENTOR_CONCURRENCY`, padrão 3). Depois o Coordenador consolida (`sintese`) e o `auditor`
dá o veredito; a checagem determinística de linguagem proibida (`forbidden_claims`) só pode endurecer o veredito.

## Capacidades por papel
| Papel | Dados do dono | Navegador | `sem_novidade` |
|---|---|---|---|
| `coordenador` (chat) | sim | restrito: hosts exatos (`OWNER_CONTEXT_HOSTS`), sem `?query` | não |
| `pesquisa` (painel) | **não** | allowlist inteira (`*.gov.br`, B3, Anbima, FGC, Tesouro Direto) | não |
| `rotina` | sim | não | sim |
| demais especialistas, `sintese`, `auditor` | sim | não | não |

Assim um texto de página injetado nunca está na mesma sessão que pode ler os dados do dono **e** escolher livremente
a URL. Teto de passos por papel (`session.MAX_TURNS`) e prazo por tentativa (`CHAT_DEADLINE_SECONDS` = 600 s,
`EPHEMERAL_DEADLINE_SECONDS` = 420 s): um loop de ferramentas não segura vaga nem suprime rotinas.

## Navegador de pesquisa
O Chrome é lançado com proxy inexistente, resolvedor de nomes travado na allowlist e sem WebRTC; toda requisição
HTTP(S) da página é buscada pela guarda com redirecionamentos desligados, e cada salto é conferido antes de sair
(o Chrome não devolve à guarda o pedido que ele mesmo redirecionaria). WebSockets são recusados. Resposta até 5 MB,
heap de JS de 256 MB, prazo de 60 s por leitura; só os primeiros 15 000 caracteres de texto saem do renderer.

## Limite da assinatura
`RateLimitEvent` com `rejected` → o worker segura a fila até `resets_at` + 30 s e reenvia sozinho, avisando a interface
(`waiting_limit`). Sem horário informado, tenta de novo a cada 15 min, por no máximo 24 h.

## Origem das ideias
O desenho de sessão longa por conversa, espera de limite, rotinas e painel foi inspirado no estudo do código do
OpenBot (licença PolyForm Noncommercial). Nenhum código foi copiado.
