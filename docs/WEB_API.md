# Lastro — contrato da API web (v1)

Fonte única de verdade entre backend (`backend/app/web.py`) e frontend (`frontend/`).
Base: mesma origem do app (ex.: `https://lastro.example.com`), prefixo `/api`.

## Convenções
- JSON UTF-8. **Dinheiro, taxas e quantidades são strings decimais com ponto** (`"1234.56"`, `"0.12"`); nunca number.
  O frontend formata para exibição (`R$ 1.234,56`, `12,00%`) e converte a digitação brasileira (`1.234,56`) antes de enviar.
- Taxas são frações: `"0.12"` = 12%. O período vem no nome do campo (`monthly_rate`, `annual_return`).
- Datas: `AAAA-MM-DD`; data-hora: ISO 8601 com fuso.
- Autenticação por cookie de sessão `lastro_session` (HttpOnly, Secure, SameSite=Strict). O frontend usa `fetch(..., {credentials: "same-origin"})`.
- Toda requisição que altera estado (POST/PUT/DELETE) envia o cabeçalho `X-Lastro: 1`; o backend recusa sem ele (proteção CSRF extra).
- Erros: `{"detail": "mensagem em português"}` com 400/401/403/404/409/422/429/503.
- Streams usam **Server-Sent Events** na resposta de um POST (o frontend lê com `fetch` + `ReadableStream`):
  cada evento é `event: <nome>\ndata: <json>\n\n`.

## Autenticação
| Método e rota | Corpo | Resposta |
|---|---|---|
| `GET /api/auth/state` | — | `{"authenticated": bool, "setup_required": bool}` (`setup_required` = senha ainda não definida no servidor) |
| `POST /api/auth/login` | `{"password": str}` | 204 + cookie; 401 senha errada; 429 após 5 erros em 15 min **do mesmo cliente** (IP; IPv6 por /64). Muitos erros somando todos os clientes só atrasam a resposta (≤ 5 s). Destravar: `sudo lastro-admin unlock` ou trocar a senha |
| `POST /api/auth/logout` | — | 204 |

A senha é definida no servidor pelo dono (`lastro-admin set-password`), nunca pela web. `lastro-admin unlock` remove bloqueios de login.

## Situação financeira (snapshots, append-only)
Snapshot = fotografia do mês. Cada edição cria um novo snapshot; o histórico nunca é reescrito.

`Debt`: `{"name": str, "balance": dec, "monthly_rate": dec, "monthly_payment": dec}`

`Snapshot`: `{"id": uuid, "as_of": date, "net_monthly_income": dec, "essential_expenses": dec, "variable_expenses": dec, "liquid_reserve": dec, "available_this_month": dec, "debts": [Debt], "created_at": datetime}`

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/snapshot/latest` | — | `Snapshot` ou `null` |
| `POST /api/snapshot` | `Snapshot` sem `id`/`created_at` | `Snapshot` criado (201) |
| `GET /api/snapshot/history` | — | `[{"id", "as_of", "net_monthly_income", "liquid_reserve", "total_debt", "free_cash_flow"}]` (mais antigo primeiro) |

## Diagnóstico
`GET /api/diagnosis?reserve_months=6&reference_annual_return=0.10` → 404 se não houver snapshot.
```json
{
  "as_of": "2026-10-26",
  "free_cash_flow": "250.00",
  "debt_commitment_ratio": "0.1786" | null,
  "total_debt": "8400.00",
  "reserve": {"target_months": 6, "target_amount": "11400.00", "current": "0.00", "gap": "11400.00", "coverage_months": "0.0" | null, "complete": false},
  "guidance": {
    "stage": "sem_recurso_disponivel" | "organizar_orcamento" | "priorizar_divida" | "construir_reserva" | "investir_para_metas",
    "next_step": str, "situation": [str, str, str],
    "allocation": [{"purpose": str, "amount": dec, "percent": dec /* pontos percentuais 0–100, ex. "100.0" */, "rationale": str}],
    "comparisons": [str], "premises": [str], "missing_information": [str],
    "checklist": [str], "follow_up": str, "disclaimer": str, "notes": [str]
  }
}
```

## Premissas e projeção
`Scenario`: `{"name": str, "annual_return": dec, "annual_inflation": dec, "annual_fee": dec, "note": str}`

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/assumptions` | — | `{"scenarios": [Scenario x3], "is_default": bool, "note": str}` (padrões ilustrativos até o usuário salvar os seus) |
| `PUT /api/assumptions` | `{"scenarios": [Scenario]}` (1 a 5) | igual ao GET |
| `POST /api/projection` | `{"initial": dec, "contribution": dec, "months": int(0-960), "contribution_annual_increase": dec?, "paused_months": [int]?, "include_path": bool?}` | `{"projections": [Projection]}` usando as premissas salvas |

`Projection`: `{"scenario", "engine_version", "inputs_fingerprint", "final_nominal", "final_real_todays_money", "total_contributed", "total_withdrawn", "market_result", "plan": {...}, "assumptions": Scenario, "limitations": [str], "path": [[month, nominal, real], ...]?}`

## Metas
`Goal`: `{"id": uuid, "name": str, "target_real_value": dec, "base_date": date, "deadline": date, "priority": int(1-5), "liquidity": "diaria" | "curto_prazo" | "longo_prazo", "current_amount": dec, "required_monthly": {"<scenario>": dec}, "months_left": int, "status": "no_rumo" | "atencao" | "revisar"}`

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/goals` | — | `[Goal]` |
| `POST /api/goals` | campos editáveis (`name`, `target_real_value`, `deadline`, `priority`, `liquidity`, `current_amount`) | `Goal` (201) |
| `PUT /api/goals/{id}` | idem | `Goal` |
| `DELETE /api/goals/{id}` | — | 204 |

## Mentor (chat)
`Conversation`: `{"id": uuid, "title": str, "kind": "chat" | "routine" | "panel", "created_at", "updated_at"}`
`Message`: `{"id": uuid, "role": "user" | "assistant", "content": str (markdown), "status": "ok" | "error" | "interrupted", "tools": [{"name": str, "input": object}], "created_at"}`

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/conversations` | — | `[Conversation]` (mais recente primeiro) |
| `POST /api/conversations` | `{"title": str?}` | `Conversation` (201) |
| `DELETE /api/conversations/{id}` | — | 204 |
| `GET /api/conversations/{id}/messages` | — | `[Message]` |
| `POST /api/conversations/{id}/messages` | `{"text": str}` | **SSE** (abaixo) |
| `POST /api/conversations/{id}/interrupt` | — | 204 |

Eventos SSE do chat:
- `queued` `{"position": int}`: aguardando vaga (outro turno em andamento).
- `waiting_limit` `{"retry_at": datetime | null, "message": str}`: limite da assinatura atingido; o backend reenvia sozinho.
- `tool` `{"name": str, "input": object}`: o mentor consultou uma ferramenta (mostrar como chip discreto: "Consultou diagnóstico").
- `delta` `{"text": str}`: pedaço de texto da resposta (acrescentar).
- `done` `{"message": Message}`: resposta final persistida (substitui o texto acumulado).
- `error` `{"kind": "auth" | "rate_limit" | "network" | "timeout" | "internal", "message": str}`.

Se a conexão cair, o turno continua no servidor; o frontend recarrega `GET .../messages`.

## Painel de especialistas (agentes em paralelo)
`POST /api/panels` `{"question": str, "conversation_id": uuid?}` → **SSE**:
- `plan` `{"agents": [{"role": "diagnostico" | "simulacao" | "riscos" | "educacao" | "pesquisa", "label": str}]}`
- `agent_start` `{"role"}` · `agent_tool` `{"role", "name", "input"}` · `agent_delta` `{"role", "text"}` · `agent_done` `{"role", "text", "status"}`
- `synthesis_delta` `{"text"}` (Coordenador consolidando)
- `audit` `{"verdict": "PASSA" | "REVISAR" | "BLOQUEAR", "reasons": [str]}` (Auditor)
- `done` `{"message": Message, "conversation_id": uuid}`
- `error` (como no chat)

O resultado final é salvo como mensagem numa conversa `kind: "panel"`.

## Rotinas
`Schedule`: `{"kind": "daily" | "weekly" | "monthly" | "once", "time": "HH:MM", "weekday": 0-6?, "day": 1-28?, "date": date?}` (weekday 0 = segunda)
`Routine`: `{"id", "name", "instruction", "schedule": Schedule, "timezone": "America/Sao_Paulo", "active": bool, "missed_policy": "skip" | "run_once", "use_panel": bool, "next_run_at": datetime | null, "last_run": RoutineRun | null}`
`RoutineRun`: `{"id", "routine_id", "scheduled_for", "started_at", "finished_at", "status": "queued" | "running" | "succeeded" | "quiet" | "failed" | "skipped" | "missed", "summary": str | null, "conversation_id": uuid | null, "read": bool}`

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/routines` | — | `[Routine]` |
| `POST /api/routines` | campos editáveis | `Routine` (201) |
| `PUT /api/routines/{id}` | idem | `Routine` |
| `DELETE /api/routines/{id}` | — | 204 |
| `POST /api/routines/{id}/run` | — | `RoutineRun` (202; roda agora, fora da agenda) |
| `GET /api/routines/{id}/runs` | — | `[RoutineRun]` (últimas 50) |
| `GET /api/inbox` | — | `[RoutineRun]` com `summary`, não lidas primeiro |
| `POST /api/inbox/{run_id}/read` | — | 204 |

`quiet` = a rotina rodou e não havia novidade (não notifica).

## Diário de decisões — ver `docs/DIARIO.md`
Agentes só propõem (rascunho); toda decisão nasce de uma destas rotas, com sessão e `X-Lastro`. 404 para o que não é do dono.

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/diary` | — | `{drafts, decisions, due_reviews, chain, today}` |
| `POST /api/diary/drafts` | `{"message_id"}` (resposta de agente) | rascunho (idempotente por mensagem); 422 se não for resposta de agente |
| `GET /api/diary/drafts/{id}` | — | rascunho |
| `POST /api/diary/drafts/{id}/confirm` | `{"alternativa"? \| "escolha"?, "justificativa", "correcoes", "review_every_months"?, "radar_decisao"?}` | decisão (reenvio devolve a mesma); 422 sem escolha |
| `POST /api/diary/drafts/{id}/postpone` · `/discard` | `{"until"?, "note"}` · `{"note"}` | rascunho (`adiado` / `descartado`) |
| `POST /api/diary/decisions` | registro manual `{"titulo", "escolha", …, "client_id"?}` | decisão (201; `client_id` repetido devolve a mesma) |
| `GET /api/diary/decisions/{id}` | — | `{decisao, na_epoca, hoje, radar}` (contexto original e atual separados) |
| `POST /api/diary/decisions/{id}/revisions` | `{"escolha", "mantem", "justificativa", "client_id"?}` | decisão com nova versão (201) |
| `POST /api/diary/decisions/{id}/outcomes` | `{"texto", "executada"?, "observado_em"?, "client_id"?}` | decisão (201) |
| `PUT /api/diary/decisions/{id}/review-plan` | `{"every_months": 1..24 \| null}` | decisão |
| `POST /api/diary/decisions/{id}/discuss` | — | conversa com o Mentor ligada à decisão (201) |

As antigas `GET/POST /api/decisions` saíram; o `decision_log` é importado para o Diário na inicialização.

## Estado e dados
| Rota | Resposta |
|---|---|
| `GET /api/status` | `{"app_version", "engine_version", "mentor": {"available": bool, "logged_in": bool \| null, "subscription": str \| null, "busy": int, "queued": int, "limit_until": datetime \| null}, "data": {"latest_snapshot_as_of": date \| null, "stale": bool}}` |
| `GET /api/export` | arquivo JSON com todos os dados do usuário (download) |

## Conselho deliberativo e Radar cripto — ver `docs/COUNCIL.md` e `docs/CRYPTO.md`
| Rota | Corpo | Resposta |
|---|---|---|
| `POST /api/team/runs/{id}/close` | — | pede o fim da discussão; o veredito sai com o que já foi dito |
| `GET /api/team/meetings?conversation_id=` | — | registros estruturados das reuniões (não são decisões) |
| `GET /api/crypto/overview` | — | ativos (cotação com moeda e fonte, indicadores, série), eventos, fontes, preferências, limitações |
| `PUT /api/crypto/prefs` | preferências (opt-in, limites, silêncio, orçamento, carteira) | preferências validadas |
| `PUT /api/crypto/coingecko-key` · `DELETE …` | `{"key"}` | 204; a chave nunca é devolvida |
| `POST /api/crypto/providers/{binance\|coingecko\|defillama}/test` · `POST /api/crypto/collect` | — | teste/coleta (no coletor, em produção) |
| `POST /api/crypto/events/{id}/convene` | — | pede a análise do Conselho para um evento |
| `GET /api/notifications` · `POST /api/notifications/{id}/read` · `POST /api/notifications/read-all` | — | central interna |

## Livro de movimentações e Caixa de entrada — ver `docs/LEDGER.md`
| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/consents` · `PUT /api/consents/{auto_register\|ai_documents}` | `{"granted"}` | estado dos consentimentos da pessoa |
| `GET /api/ledger?status=&document_id=` | — | movimentações (valor com sinal do fluxo, origem, conciliação) |
| `GET /api/ledger/summary?month=AAAA-MM` | — | totais derivados (receitas, despesas, estornos, transferências à parte, pendências) |
| `POST /api/ledger/{id}/{confirmar\|descartar\|desfazer\|restaurar\|corrigir\|e_duplicada\|nao_e_duplicada}` | `{"changes"?}` | movimentação; cada ação vira evento em `ledger_events` |
| `GET /api/ledger/{id}/events` | — | trilha da movimentação |
| `GET /api/captures?status=` · `POST /api/captures/{id}/{desfazer\|confirmar\|descartar}` | `{"changes"?}` | registros reconhecidos na conversa |
| `POST /api/documents?conversation_id=` | corpo binário, `X-Filename` | 201 documento com `summary`; repetido → `repeated: true`; 413/415/422 |
| `GET /api/documents` · `GET /api/documents/{id}` | — | lista (com OCR/PDF disponíveis e retenção) · documento com lançamentos |
| `POST /api/documents/{id}/approve` · `DELETE /api/documents/{id}?entries=` | — | aprova pendências completas · exclui (e desfaz lançamentos, se pedido) |
| `POST /api/documents/{id}/interpret` | `{"confirm": true}` | 202; exige consentimento `ai_documents`; resultado sempre pendente |

## Equipe (Mentor, especialistas, grupos, Conselho) — ver `docs/MULTIAGENT.md`
Toda rota exige sessão; conversas e execuções de outra pessoa respondem 404 (igual a inexistentes).

| Método e rota | Corpo | Resposta |
|---|---|---|
| `GET /api/agents` | — | agentes de conversa: `id, name, handle, title, kind, summary, examples, tools, version` |
| `GET /api/team/conversations` | — | conversas com `channel` (`direct`/`group`/`council`/`routine`), `agent_id`, `participants`, `last_message` |
| `POST /api/team/conversations` | `{"channel", "agent_id"?, "title"?, "participants"?: [id]}` | 201 conversa. Grupo: Mentor + escolhidos; Conselho: todos |
| `GET/PUT/DELETE /api/team/conversations/{id}` | PUT `{"title"}` | conversa; DELETE 409 se houver execução ativa |
| `POST /api/team/conversations/{id}/participants` | `{"agent_id"}` | só grupos |
| `DELETE /api/team/conversations/{id}/participants/{agent}` | — | o Mentor não sai |
| `GET /api/team/conversations/{id}/messages` | — | mensagens com `agent_id, kind (message/analysis/notice), audit, sources, mentions, reply_to_id, run_id, meta` (`meta`: `route`, `agent_version`, `opinion.stance`; no mapa do Conselho, `positions` e `conflict`) |
| `POST /api/team/conversations/{id}/messages` | `{"text", "client_id"?, "reply_to_id"?}` | 202 `{message, run, notices}`; mesmo `client_id` → mesma mensagem e execução |
| `GET /api/team/conversations/{id}/runs` | — | execuções recentes com `steps` (agente, tipo, pai, profundidade, estado, erro) |
| `POST /api/team/runs/{run_id}/cancel` | — | execução atualizada |
| `GET /api/team/conversations/{id}/stream` | — | SSE (GET, compatível com EventSource): `snapshot`, `message`, `run`, `step`, `delta`, `tool`, `wait`, `fact_proposed`, `ping` |
| `GET /api/team/memory` | — | `{facts, notes, market, not_connected}` |
| `POST /api/team/facts` | `{"key", "value", "note"?}` | fato confirmado pela pessoa (substitui o anterior, com histórico) |
| `POST /api/team/facts/{id}/confirm` · `/reject` | — | decide uma proposta de agente |
| `DELETE /api/team/notes/{id}` | — | apaga uma anotação de agente |

As rotas antigas `/api/conversations/*` e `/api/panels` continuam para compatibilidade (rotinas); a interface usa as da equipe.

## Radar e Diário de Oportunidades — ver `docs/RADAR.md`
Toda rota exige sessão e filtra pelo dono (de outra pessoa = 404). Nenhuma executa operação financeira.

| Método e rota | Corpo | Resposta |
|---|---|---|
| `GET /api/radar/overview` | — | fontes, estado da coleta, não conectadas, alertas novos, preferências, canais (`realtime: false`) |
| `POST /api/radar/tick` | — | avalia todas as regras agora |
| `GET /api/radar/series?category=` | — | séries com último valor, data, validade (títulos vencidos fora) |
| `GET /api/radar/series/{id}/history?days=` | — | pontos com revisão e qualidade |
| `POST /api/radar/assets` | `{"ticker", "kind": "acoes" / "etf" / "fii"}` | 201 ativo informado pela pessoa |
| `POST /api/radar/assets/{id}/observations` | `{"reference_date", "value", "kind": "preco" / "provento"}` | nova observação ou revisão (data futura = 422) |
| `POST /api/radar/assets/{id}/events` | `{"ex_date", "kind", "factor"}` | desdobramento, grupamento, bonificação |
| `GET /api/radar/alerts?status=` | — | alertas com prioridade, ocorrências, condição |
| `POST /api/radar/alerts/{id}/status`, `/feedback`, `/mute` | `{"status"}`, `{"feedback"}`, `{"days"}` | alerta; silenciamento de semelhantes |
| `GET /api/radar/rules`, `POST`, `PUT /{id}`, `POST /{id}/status` | regra | toda mudança = nova versão |
| `GET /api/radar/rules/{id}/versions` | — | versões e backtests |
| `POST /api/radar/rules/{id}/backtest` | `{"start"?, "end"?}` | resultado **simulado** (dentro e fora da amostra, segmentos) |
| `GET /api/radar/proposals`, `POST /{id}/approve`, `/reject` | — | propostas de ajuste (só valem aprovadas) |
| `GET/PUT /api/radar/prefs`, `PUT /api/radar/channels/{canal}` | preferências; `{"enabled", "consent"}` | ativar canal exige consentimento |
| `GET /api/radar/journal?category&state&rule_id&asset&since&until&min_class&verdict&agent` | — | oportunidades com avaliações por horizonte |
| `GET /api/radar/journal/{id}` | — | registros (cadeia SHA-256 verificada), linha do tempo, avaliações, alerta e entregas, decisões, operações, conversas, evolução |
| `POST /api/radar/journal/{id}/decisions`, `/operations`, `/corrections` | decisão; operação informada; `{"reason", "changes"}` | append-only |
| `POST /api/radar/journal/{id}/discuss` | `{"target": "mentor" / "conselho"}` | 201 conversa com o registro como contexto, vinculada |
| `GET /api/radar/links/{conversation_id}` | — | oportunidade de origem da conversa |
| `GET /api/radar/metrics?days&horizon` | — | totais, por categoria, regra e mês, latências; cada taxa com `n` e `confiavel` |
