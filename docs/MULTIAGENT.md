# Lastro — equipe de agentes (Mentor, especialistas, grupos e Conselho)

## O que existe
| Agente | Especialidade | Ferramentas (aplicadas em código) |
|---|---|---|
| Mentor | coordena, delega, consolida | dados do dono, memória financeira, mercado, motor, delegação, notas; navegador só em hosts exatos |
| Planejador | orçamento, reserva, dívidas, metas | dados, memória financeira, motor, delegação, notas |
| Analista | investimentos (dados × premissas × cálculos × estimativas × interpretação) | dados, memória financeira, mercado, motor, delegação, notas |
| Economista | macro, Selic/CDI/IPCA/câmbio | mercado, motor, navegador de fontes oficiais, delegação, notas — **sem dados do dono** |
| Gestor de Riscos | perdas, liquidez, concentração, estresse | dados, memória financeira, mercado, motor, delegação, notas |
| Conselheiro | vieses e comportamento | dados, memória financeira, delegação, notas |
| Analista de Ativos Digitais | cripto, stablecoins, custódia e risco operacional | dados, memória financeira, mercado, motor, delegação, notas (o Lastro não coleta preço de cripto: o agente diz que o dado não existe) |
| Auditor | verificação (não conversa) | dados, memória financeira, mercado, motor |

Registro: `backend/team/agents.py` (versão em `REGISTRY_VERSION`). Instruções: `backend/mentor/prompts/<agente>.md` + modo
(`prompts/modos/*.md`: direto, grupo, delegado, integração, Conselho, correção). Nenhum agente tem terminal, arquivos,
web livre ou execução: o worker continua com `tools=[]`, servidor MCP próprio e `can_use_tool` por agente.

## Fluxo
```
Navegador ─POST /api/team/conversations/{id}/messages (202)─► Orquestrador (web app, SQLite)
          ◄─GET …/stream (SSE: snapshot, message, run, step, delta)─┘   │ runs + run_steps (fila persistente)
                                                                     ▼
                                   worker do mentor: op "ephemeral" {role=agente, mode, text}
                                   (uma sessão descartável do Claude por passo)
```
- **Roteamento** (`team/routing.py`): individual → o agente; Conselho → reunião; `/conselho …` no Mentor ou em grupo →
  reunião; grupo com @menções → só os mencionados presentes; resposta a mensagem de agente → o autor; sem menção → Mentor.
- **Delegação**: o agente chama `solicitar_especialista`; o orquestrador aplica profundidade (2), total por execução (6),
  ciclo, duplicata, alvo permitido e participação no grupo. Recusas ficam registradas como passo `rejected`.
  Em grupo, o especialista consultado responde como mensagem própria; em conversa individual, vira parecer interno
  e aparece nas fontes. Depois, o solicitante escreve a resposta final (passo `integracao`).
- **Conselho**: enquadramento (Mentor) → Planejador, Analista e Economista em paralelo (mais o Analista de Ativos
  Digitais quando a questão fala de cripto, `routing.council_agents`) → Riscos e Conselheiro (leem os anteriores) →
  contestação → mapa de posições → síntese com "## Divergências" → Auditor. Cada parecer é uma mensagem expansível.
  - **Parecer estruturado** (`team/opinion.py`, modo `conselho_parecer`): `**Posição:**` declarada (favorável, contrária,
    condicional ou sem base suficiente) e as seções Tese, Evidências, Fontes, Hipóteses, Riscos, Lacunas e Não agir.
    Faltou posição ou seção: o parecer volta uma vez ao agente; se ainda faltar, o Auditor o retém.
  - **Contestação**: só quando há ao menos um favorável e um contrário. Uma rodada (`conselho:contestacao:<agente>`),
    só para os lados opostos, cada um lendo os pareceres que discordam do seu; não há segunda rodada.
  - **Mapa de posições** (`conselho:posicoes`, autor "Lastro"): tabela determinística com a posição de cada parecer e a
    posição após a contestação, publicada antes da síntese. Não depende do modelo que escreveu a síntese.
  - **Dissenso preservado**: se a divergência se mantém, a síntese precisa nomear na seção "## Divergências" cada
    especialista que segue discordando; omitir um deles reprova a síntese (uma correção, depois retenção).
- **Auditoria** (`team/auditor.py`): toda mensagem de agente passa pela verificação determinística (números refeitos
  pelo motor a partir das entradas que o agente usou, dados do dono, séries externas; promessas; pedido de senha ou
  execução; mercado sem fonte/data; série desatualizada; categorias sem riscos; ativo volátil em etapa de dívida).
  No Conselho, o Auditor semântico complementa e só endurece o veredito. REPROVA → uma correção pelo próprio agente;
  se ainda reprovar, a resposta é substituída por explicação transparente.

## Radar
Sinais do Radar (`docs/RADAR.md`) abrem uma execução `radar` numa conversa do Conselho: até 3 especialistas escolhidos pela
categoria (modo `radar_parecer`), síntese do Mentor (`radar_sintese`) e Auditor, sem delegação. A ferramenta
`diario_radar` (Mentor, Planejador, Analista, Riscos e Auditor; leitura) consulta o Diário de Oportunidades.

## Garantias de execução
| Requisito | Como |
|---|---|
| Sobrevive à aba fechada e ao reinício | `runs` no banco; `recover_runs` devolve `running` à fila; passos concluídos são reaproveitados |
| Sem duplicata em retentativa | UNIQUE(run_id, step_key) nas mensagens; UNIQUE(conversation_id, client_id) no envio |
| Falha isolada | passo com erro vira mensagem de erro daquele agente; execução fica `partial` |
| Retentativa limitada | 2 tentativas para `network/internal/timeout`; limite do provedor é esperado pelo worker |
| Cancelamento | `POST /api/team/runs/{id}/cancel`: nenhum passo novo começa e o em andamento é interrompido |
| Concorrência | `LASTRO_RUN_CONCURRENCY` (padrão 2) execuções; uma por conversa, na ordem das mensagens |
| Prazo | 900 s por passo no orquestrador + prazos do worker |

## Memória
- **Financeira** (`financial_facts`): fato com fonte, data e histórico (`superseded`, nunca apagado). Agentes só
  **propõem** (`propor_fato`); a pessoa confirma na tela "Memória e fontes". A API dos agentes só serve confirmados.
- **Individual** (`agent_notes`): `anotar_memoria`. Nota feita na conversa individual do próprio agente vale nas
  conversas individuais dele; feita em grupo ou em consulta, vale só naquela conversa.
- **Autoria** (`messages.meta_json`, migração 009): cada mensagem de agente guarda a conexão e o modelo que a
  escreveram (`route`, vazio = conexão padrão), a versão do registro do agente e, nos pareceres, a posição declarada.
  Trocar de provedor não reescreve nada: pareceres, mapa de posições e divergências antigos continuam como foram
  gravados (teste `test_high_risk_proposal_keeps_dissent_across_provider_switch`).
- **Compartilhada**: o contexto de cada passo é montado só com as mensagens da própria conversa. Mensagens antigas
  entram compactadas (autor, data e início do texto); texto de terceiros não consegue forjar os marcadores `[ … ]`.

## Dados externos
`integrations/collector.py` (serviço `lastro-coletor`, a cada 6 h): BCB/SGS (Selic meta 432, CDI 4389, IPCA 433 e
13522, PTAX 1) e FRED (FEDFUNDS, DGS10) se `FRED_API_KEY` existir. Só número e data entram no banco; rótulo, unidade e
fonte vêm do catálogo. Validade: `valido`/`desatualizado`/`indisponivel` por idade máxima da série; pontos com data
futura são ignorados. Não conectados (nunca simulados): IBGE direto, CVM, Tesouro Direto, ANBIMA, B3, SEC.

## Implantação
1. Backup: `sudo -u patrimonio sqlite3 /var/lib/patrimonio/lastro.db ".backup /var/lib/patrimonio/pre-v5.db"`.
2. `(cd frontend && npm ci && npm run build)` e `sudo scripts/deploy.sh` (aplica a migração 005, instala `lastro-coletor`).
3. Opcional: `/etc/meu-patrimonio/coletor.env` com `FRED_API_KEY=…` (0640 root:patrimonio).
4. Conferir: `systemctl status lastro-coletor`, tela "Mentor e especialistas" → "Memória e fontes".

## Rollback
A migração 005 só acrescenta colunas e tabelas; o código anterior ignora o que não conhece e `migrate` não volta
versão. Para voltar: `git checkout e2f19c0 && (cd frontend && npm ci && npm run build) && sudo scripts/deploy.sh`,
depois `sudo systemctl disable --now lastro-coletor`. Se for preciso o banco antigo, pare os serviços e restaure
`pre-v5.db` (perde o que foi conversado depois do backup).
