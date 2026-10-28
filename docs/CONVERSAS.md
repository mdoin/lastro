# Conversas com a equipe

Os agentes conversam como personagens quando a pessoa só quer conversar e viram especialistas quando ela pede
análise. Código: `backend/team/intent.py` (intenção), `backend/app/orchestrator.py` (`_route`, `_chat_route`,
`_conversation`, `_identity`, `_answer_leftovers`), `backend/mentor/prompts/modos/conversa.md`,
`frontend/src/pages/Team.tsx` e `Settings.tsx`.

## Intenção (sem modelo)
`intent.classify` lê o texto e devolve uma de: `conversa` (saudação, papo, humor, pergunta sobre o próprio agente,
sem sinal financeiro forte), `pergunta` (o padrão), `decisao` ("pensando em investir…", "quero discutir minha
carteira"), `analise` (pedido explícito de análise com tema financeiro) e `reuniao` ("Bento, convoca uma reunião").
Na dúvida fica `pergunta`, que segue o comportamento de sempre; os modos `direto` e `grupo` também sabem responder a
papo sem tratá-lo como pedido de análise.

| Onde | conversa | pergunta | decisao | analise / reuniao |
|---|---|---|---|---|
| Conversa individual | modo `conversa` | modo `direto` | Bento: responde e oferece o Conselho | só com o Bento: Conselho |
| Grupo | citados, ou Bento (+2 colegas se falou com todos) | roteamento de sempre | Bento oferece o Conselho | Conselho |
| Sala do Conselho | citados, ou Bento (+2) | reunião | reunião | reunião |

"Sim, pode reunir" depois de uma oferta (`meta.council_offer`) abre o Conselho com a pergunta original. Pedido de
reunião sem tema usa a última mensagem da pessoa que não era papo; sem nenhuma, o Bento pergunta o tema.

## Conversa em grupo
As respostas saem uma de cada vez: quem fala depois lê quem falou antes. Um agente que cita um colega presente com
@menção dá a vez a ele (`meta.chat.responds_to`, `reply_to_id`). Limites: cada agente fala uma vez por mensagem,
`LASTRO_CHAT_MAX_TURNS` (4) falas e `LASTRO_CHAT_MAX_SPONTANEOUS` (2) chamadas entre agentes: não há laço.
A Cora também conversa (prompt `auditor_conversa.md`, sem formato de auditoria).

## Personalidades
`AgentSpec.persona` entra no prompt de todos os modos ("Seu jeito: …"): muda o estilo, nunca os fatos.

## Intervenções durante a reunião
Mensagem enviada na Sala do Conselho durante uma reunião entra na próxima pauta. Se nenhuma fala a respondeu (chegou
depois da última pauta, ou o modo não tem discussão), ao fim da reunião ela vira uma resposta normal de quem foi
citado (ou do Bento), que lê a reunião inteira. Nunca duplica: uma execução por mensagem.

## Identidade da pessoa
Perfil em `users.preferences.profile` (`GET/PUT /api/profile`, tela Configurações): nome de preferência, apelido e
preferências de tratamento. Lido a cada passo e por `user_id` (sem vazamento entre contas), vale após reinício.
Os agentes recebem também a data da última conversa quando faz dois dias ou mais. Sem nome, o primeiro agente da
primeira conversa pergunta uma vez (`asked`); "pode me chamar de Ana" no chat só sugere salvar, e a pessoa confirma.
Nunca se tira nome de documentos, e o prompt pede para não presumir gênero ou pronomes.

## Limitações
- A intenção é por regras de texto: frases fora dos padrões caem em `pergunta` (comportamento anterior).
- Escolha dos dois colegas num "oi, pessoal" é por rodízio (quem falou há mais tempo), não por tema.
