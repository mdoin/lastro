# Diário de Decisões assistido por agentes

**Os agentes preparam os registros; a pessoa confirma as decisões.** O registro manual continua existindo, como caminho secundário.

## Camadas (cada uma com autoria)
| Camada | Onde | Quem escreve | Muda? |
|---|---|---|---|
| Análise | pareceres dos agentes copiados para o rascunho (`pareceres[]`, com `agent_id`) | agentes | não |
| Proposta | `decision_drafts` | o web app, a pedido do Mentor (`propor_registro_decisao`) ou da pessoa ("Registrar no Diário") | só o estado: `pendente → adiado → confirmado/descartado` |
| Decisão confirmada | `diary_entries` `kind=decisao` | só a pessoa (rota autenticada) | nunca (triggers + cadeia SHA-256) |
| Revisão | `diary_entries` `kind=revisao` (versão + 1, ligada à original) | só a pessoa | nunca |
| Resultado observado | `diary_entries` `kind=resultado` (`executada` só se a pessoa informar) | só a pessoa | nunca |

## Como o rascunho é montado (`backend/app/diary.py`)
O modelo informa só o que foi discutido: título, contexto, alternativas, a favorecida, informações, riscos, divergências
(validado com pydantic, campos extras recusados). O resto vem dos registros da execução:
pergunta original (mensagem da pessoa ou contexto do Radar), data, retrato financeiro do momento, fontes das mensagens,
cálculos **refeitos pelo motor** a partir das entradas que o agente usou, pareceres (mensagens e consultas internas),
síntese, auditoria, referência à conversa e, se houver, o sinal do Radar com o snapshot de detecção original.
O que não apareceu fica vazio e a tela mostra "Não apareceu na conversa".

## Segurança
- Agentes não escrevem no banco: `propor_registro_decisao` é uma ferramenta "registrada" (não faz nada no worker);
  o orquestrador lê a entrada, confere a capacidade (`diary`, só o Mentor) e a chamada do próprio passo, valida e grava
  o rascunho. Um rascunho por mensagem (`message_id` UNIQUE).
- Decisão só por `POST /api/diary/drafts/{id}/confirm` (sessão + `X-Lastro`), com escolha explícita; nada é
  pré-selecionado. Reenvio devolve a mesma decisão; rotas manuais aceitam `client_id` (idempotência).
- `diary_entries` é append-only (triggers) e encadeado por SHA-256 por pessoa; a tela mostra se a cadeia está íntegra.
- Toda ação vai para `audit_log` (`diary.*`).
- Auditor: de `decisoes` só contam como evidência os campos escritos/confirmados pela pessoa (`diary.OWNER_FIELDS`)
  e os cálculos do motor; texto de agente (propostas, sínteses, pareceres) nunca certifica número.
- A mensagem criada por "Discutir com o Mentor" não traz valores do retrato: ela também chega a agentes sem dados do
  dono (ex.: Economista consultado). O Mentor busca os números com `decisoes`/`situacao_atual`.
- Revisão de segurança focada em 27/10/2026 (antes do deploy): dois achados baixos corrigidos (acima); IDOR, CSRF,
  imutabilidade, API somente leitura e XSS conferidos sem achados. Pendentes de validação: export e retrato ainda
  supõem um só dono (item 14).

## Agentes lendo decisões
`decisoes` (todos os agentes com dados do dono) → `GET /v1/me/decisions?q=&id=` na API somente leitura: decisões
confirmadas com premissas, revisões e resultados; propostas não confirmadas vêm à parte, marcadas como não-decisões.
A resposta traz o aviso de que decisões antigas não são instruções (regra 13 do `_base.md`).

## Radar
Rascunho de uma análise do Radar guarda `opportunity_id` e o snapshot de detecção. Na confirmação a pessoa pode
registrar a categoria no Diário de Oportunidades (`radar_decisao`). Decidir não é executar: `executada` só muda quando
a pessoa informa um resultado. A revisão mostra avaliações posteriores e operações informadas, separadas do original.

## Revisão periódica
`decision_review_plans` (configuração, mutável): a cada N meses o Diário pergunta "Há N meses você decidiu…". Revisar
mostra o contexto da época e o de hoje lado a lado, ou abre uma conversa com o Mentor ligada à decisão
(`decision_links`): o rascunho nascido nela vira revisão daquela decisão.

## Implantação e rollback
Migração 007 só cria tabelas. Backup (`.backup /var/lib/patrimonio/pre-v7.db`), `npm run build`, `sudo scripts/deploy.sh`.
Na primeira inicialização o `decision_log` antigo é importado (uma vez por id). Rollback: código anterior ignora as
tabelas novas, mas as decisões registradas depois só existem nelas.
