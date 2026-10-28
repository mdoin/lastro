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
| Grupo | citados, ou vozes escolhidas pelo assunto (`team/voice.py`) | roteamento de sempre | Bento oferece o Conselho | Conselho |
| Sala do Conselho | citados, ou vozes escolhidas pelo assunto | reunião | reunião | reunião |

"Sim, pode reunir" depois de uma oferta (`meta.council_offer`) abre o Conselho com a pergunta original. Pedido de
reunião sem tema usa a última mensagem da pessoa que não era papo; sem nenhuma, o Bento pergunta o tema.

## Conversa em grupo
As respostas saem uma de cada vez: quem fala depois lê quem falou antes. Um agente que cita um colega presente com
@menção dá a vez a ele (`meta.chat.responds_to`, `reply_to_id`). Limites: cada agente fala uma vez por mensagem,
`LASTRO_CHAT_MAX_TURNS` (4) falas e `LASTRO_CHAT_MAX_SPONTANEOUS` (2) chamadas entre agentes: não há laço.
A Cora também conversa (prompt `auditor_conversa.md`, sem formato de auditoria).

## Identidade comportamental
Problema relatado: Mila e Téo, chamados depois de um papo sobre eleição e Valorant, responderam com o mesmo
esqueleto ("Fiquei quiet[a/o] porque … não são bem a minha área, mas concordo com o Bento … os colegas podem ajudar …
vamos esperar os outros"). Mudava o vocabulário, não o comportamento.

**O que causava a repetição** (investigado no código, não suposto):
1. Personalidade era uma linha de adjetivos (`AgentSpec.persona`, "Seu jeito: …") sobre um prompt igual para todos.
   Adjetivo não muda como alguém pergunta, discorda, erra ou fica quieto; o modelo só trocava palavras.
2. A regra 11 do `_base.md` mandava "Fale só da sua especialidade": fora do tema, o agente tinha de justificar
   ("não é bem a minha área") e puxar tudo para a profissão (as analogias com Valorant).
3. O modo `conversa.md`, igual para todos, era um roteiro: "Cumprimente, comente, pergunte de volta, brinque" e
   "diga que dá para aprofundar". Mesmo roteiro, mesma forma de fala.
4. Ninguém podia ficar em silêncio: "@mila @teo" do Bento virava "citou você agora; responda se tiver algo a
   acrescentar", e toda saída era publicada. Sem ter o que dizer, o agente explicava a ausência.
5. "Oi, pessoal" convocava o Bento e mais dois por rodízio, sem olhar o assunto: três vozes obrigadas a falar.
6. Quem falava depois via as falas anteriores sem nenhuma orientação contra imitar; a primeira fala virava molde.
7. Selo "Auditoria: PASSA" e "Registrar no Diário" apareciam em respostas sem nada financeiro (só o modo
   `conversa` escondia o selo, e o botão aparecia em qualquer `pergunta`).

**Camadas do prompt** (`mentor/session.py: load_prompt`):
- Compartilhada (`_base.md`): segurança, honestidade, ferramentas, política financeira, dados e continuidade (regra
  16: lembrar só do que está no histórico, não inventar passado nem vida pessoal, não se reapresentar). Sem estilo.
- Individual (`prompts/identidades/<agente>.md`): temperamento, olhar, jeito de conversar e de perguntar,
  discordância, erros, humor, empatia, relação com os colegas e quando ficar quieto. Disposições, sem frases prontas
  entre aspas (um teste impede), e o que diz dos colegas é jeito de se relacionar, não acontecimento.
- Papel (`<agente>.md`) e situação (`modos/*.md`): `conversa`, `grupo` e `direto` não impõem formato, tamanho,
  cumprimento, analogia nem fecho; o assunto da pessoa não precisa passar pela especialidade de ninguém.
- Contexto da execução (orquestrador): perfil da pessoa, anotações, histórico e quem já falou nesta rodada.

**Quem fala e quem fica quieto** (`team/voice.py`, sem modelo):
- Mensagem sem destinatário: vozes escolhidas pelo assunto (`CHAT_TOPICS`); empate vai para quem falou há mais tempo.
  "Oi, pessoal" sem assunto chama duas vozes, e não necessariamente o Bento. Sem "pessoal", o Bento responde e quem
  tem a ver com o assunto pode entrar. A Cora só fala quando chamada.
- Só a primeira voz e quem a pessoa citou são obrigados a responder. As outras (e quem um colega citou) recebem a
  opção de responder `[silêncio]`, que não é publicado nem justificado.
- Fala opcional que explica a própria ausência, se apresenta pelo cargo, só concorda ou repete o colega (trigramas
  de radicais em comum ≥ 0,25 ou mesma abertura) não é publicada. Fala de quem a pessoa chamou e falas do Conselho
  nunca são retidas; a auditoria continua rodando em todas.

**Interface** (`frontend/src/lib/messageControls.ts`): selo "PASSA" só quando a resposta tem fontes, números
conferidos, análise ou decisão; ressalva e reprovação aparecem sempre. "Registrar no Diário" só para resposta com
conteúdo financeiro, nunca para conversa.

**Avaliação**: `tests/integration/test_identity.py` cobre os 12 cenários (cumprimento, cansaço, Valorant, notícia,
piada, investimento, Nina chamada, Rui questionado, discordância, nada a acrescentar, volta depois de dias, correção
de erro) no que o código controla: quem é chamado, com quais instruções, e o que chega à pessoa. A qualidade das
falas reais é medida com `uv run python scripts/eval_conversas.py --saida relatorio.md` (modelo configurado na
máquina; rodar no commit anterior e no atual dá o comparativo). As medidas (`voice.homogeneity`) não premiam
bordão: contam pares parecidos, aberturas e esqueletos repetidos, autoapresentação e concordância vazia.

Antes e depois no caso relatado (mesmas duas falas, medidas de `voice.homogeneity`):

| | Antes | Depois |
|---|---|---|
| Quem a mensagem do Bento chamava | Mila e Téo, obrigados a responder | Mila e Téo, com a opção de silêncio |
| Instrução sobre o assunto | "Fale só da sua especialidade" | conversar como você, sem precisar da sua área |
| Fala "Fiquei quieta porque não é a minha área…" | publicada duas vezes | retida (explica ausência) |
| Medidas do par | 2 autoapresentações, 1 abertura e 1 esqueleto repetidos, 1 par parecido | não chega à pessoa |

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
- Relevância por palavras-chave: assunto fora de `CHAT_TOPICS` cai no rodízio. O filtro de eco é lexical: uma
  paráfrase completa passa (e uma fala obrigatória nunca é retida).
- Relações entre personagens vêm da identidade e do histórico da conversa; não há memória separada de discordâncias
  antigas entre agentes.
