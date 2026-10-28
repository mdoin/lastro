# Conselho deliberativo

Os especialistas analisam sozinhos, discutem entre si com falas reais e o Bento apresenta um veredito que não força
consenso. Código: `backend/team/deliberation.py` (regras determinísticas), `backend/app/orchestrator.py` (`_council`
e auxiliares), `frontend/src/components/Council.tsx` e `frontend/src/lib/council.ts` (sala, fio, painel, veredito).

## Etapas
| Etapa | O que acontece | Onde fica registrado |
|---|---|---|
| A. Análise independente | Especialistas convocados respondem em paralelo; o prompt **não** traz pareceres dos colegas nem mensagens desta execução | `conselho:<agente>` (`meta.opinion`: posição, seções, trechos) |
| B. Pauta | O Bento devolve JSON (concordâncias, divergências, contradições, hipóteses, lacunas, falas, pergunta à pessoa, encerrar); o Lastro valida: só participantes, uma fala por agente, sem fala para si | `conselho:pauta:<rodada>` (`meta.deliberation.plan`) |
| C. Discussão | Cada fala responde a uma fala real (ou à pessoa) e declara posição (mantida/revista) e reação | `conselho:debate:<rodada>:<agente>` (`reply_to_id`, `meta.deliberation.responds_to`, `reaction`, `revised`) |
| D. Auditoria | Verificação determinística + Cora; ela pode devolver questões (`DEVOLVER: @rui — …`) uma vez | `conselho:devolucao:<n>`, `conselho:auditoria` |
| E. Veredito | Conclusão, argumentos determinantes, participação, posições reconsideradas, divergências, riscos, incertezas, condições que mudariam o resultado, próximos passos; @menções resolvidas no servidor | `conselho:sintese` (`meta.verdict`) |

Sem pauta válida, uma regra decide: só há discussão se houver favorável × contrária, entre os lados opostos, uma rodada.
Divergência que permanece **precisa** aparecer na seção de divergências (senão a síntese é reprovada). O mapa de
posições (`conselho:posicoes`) é calculado pelo Lastro, não pelo modelo.

## Seleção dos participantes
`deliberation.select`: tema da pergunta (palavras por especialidade), @menções e escolha da pessoa. Reunião completa
tem ao menos três vozes; o Rui (riscos) nunca é cortado; o Téo (cripto) só entra em tema de cripto. A escalação fica
em `runs.route.lineup`.

## Modos e comandos
| Comando | Modo |
|---|---|
| (padrão na Sala do Conselho) ou `/conselho` | Conselho completo |
| `/rapida …` | Consulta rápida: 1–2 especialistas, sem pauta nem discussão |
| `/debate @caio @rui hipótese` | Debate: papéis de análise a favor/contra (não crenças); reconhecer evidência contrária |
| `/rodada` | Nova rodada sobre a última reunião (pareceres reaproveitados) |
| `/revisar …` | Novo veredito sobre a última reunião |
| `/encerrar` | Encerra a discussão em curso; o Bento dá o veredito com o que já foi dito |

Durante uma reunião, mensagens da pessoa viram **intervenções** (`meta.intervention_for`): a próxima pauta as
encaminha a quem foi citado; nada abre execução paralela. Chegou tarde demais? Vira pergunta direta depois. Depois da
reunião, `@rui, por que…` ou "Bento, quero ouvir a Nina" vão direto ao especialista, com a reunião no contexto
(com @menção, só os mencionados respondem).

## Limites (`LASTRO_COUNCIL_*`)
`MAX_ROUNDS` (2), `MAX_MESSAGES` (16 falas), `MAX_CALLS` (40), `MAX_SECONDS` (1500), `MAX_TOKENS` (0 = sem teto; usa o
consumo informado pelo provedor), `MAX_PARTICIPANTS` (5), `MAX_PARALLEL` (3 falando ao mesmo tempo), `MAX_RETURNS` (1),
`MAX_TURNS_PER_ROUND` (6). Atingir um limite encerra a discussão com aviso visível e segue para o veredito.
Espera por limite do provedor, retentativas, cancelamento e retomada após reinício continuam os do orquestrador.

## Registro e memória
Cada reunião gera `council_records` (migração 011): tema, modo, participantes, posições iniciais e finais, mudanças,
evidências, falas, divergências, conclusão, condições de revisão, auditoria, limites atingidos, consumo e origem.
É histórico da deliberação, **não** decisão: decisões só existem quando a pessoa confirma no Diário. Agentes leem as
últimas conclusões com a ferramenta `reunioes_anteriores`; a interface, em `GET /api/team/meetings`.

## Estados na sala
Derivados só de passos, eventos e mensagens: aguardando, analisando, consultando informações (o passo chamou
ferramenta), falando (texto chegando), respondendo/questionando (pauta pediu e o passo está rodando), revisando
(correção em curso), parecer disponível, concluído, indisponível (falhou ou esperando limite do provedor).
