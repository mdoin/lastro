# Laboratório do Conselho

Pergunta de pesquisa: **o Conselho de agentes produz análises financeiras melhores do que o Bento sozinho?** O
Laboratório responde com experimentos reprodutíveis e auditáveis. Qualquer conclusão é válida: Conselho melhor, Bento
melhor, empate, ou "melhor só em certas situações". Nada é declarado sem amostra suficiente.

Código: `backend/lab/` (contrato, dossiê, avaliação, serviço), `backend/app/lab_web.py` (rotas),
`backend/app/migrations/014_lab.sql`, `frontend/src/pages/Lab.tsx`. Testes: `tests/integration/test_lab.py`.

## Como um experimento roda

1. **Dossiê congelado** (`lab/dossier.py`). Reúne o retrato financeiro, o diagnóstico do motor, os fatos confirmados
   e as séries oficiais até a data de corte, com data de referência e horário de coleta de cada série. O dossiê é
   guardado com SHA-256, e o MESMO texto vai para os dois modos.
2. **Duas execuções independentes por repetição** (`lab/service.py: start`). Cada uma roda numa conversa própria e
   oculta da lista da equipe:
   - **Individual:** execução `reply` com `route.lab = "individual"`. O Bento analisa sozinho no modo
     `laboratorio_individual`, sem delegar.
   - **Conselho:** execução `council` com `route.lab = "conselho"`. É a reunião completa de sempre: pareceres
     independentes, pauta, rodadas, auditoria da Cora e veredito do Bento.
   O contexto de cada agente é montado só com a própria conversa, sem anotações nem histórico de Convicções. Nenhum modo
   vê o outro: o teste `test_modes_get_the_same_dossier_and_never_see_each_other` confere isso nos prompts.
3. **Mesmas ferramentas** (`mentor/tools.py: lab_caps`). Todo agente, nos dois modos, recebe só a calculadora
   determinística e, se o experimento permitir, o pedido de pesquisa na internet. As ferramentas de leitura ao vivo,
   memória, Diário e delegação ficam desligadas: os dados chegam só pelo dossiê.
4. **Registro estruturado** (`lab/contract.py`). A mesma instrução é anexada à resposta do Bento sozinho e à síntese
   do Conselho, e o mesmo leitor determinístico confere as duas. "Dados insuficientes" e "sem hipótese testável" são
   respostas aceitas. As hipóteses usam a gramática das Convicções (`selic_meta < 14`, `cripto:BTC > 150000` ou
   `manual`).
5. **Fechamento** (`advance`, a cada minuto no agendador). Grava o texto final, o registro, as hipóteses (imutáveis
   por trigger), a avaliação determinística e o consumo (`runs.result_json`). Depois acrescenta uma entrada
   `analise_ia` ao Diário do Laboratório.

## Controle experimental (snapshot)

Fica em `lab_experiments.snapshot_json`, que não muda depois de criado (trigger), com hash próprio. Contém:

- a pergunta e a data de corte;
- o dossiê e as fontes;
- o hash de cada arquivo de prompt;
- o provedor e o modelo de cada agente;
- os agentes convocados e as ferramentas;
- a versão do motor financeiro e do Lastro;
- as repetições, os limites do Conselho e o esforço de cada agente;
- a nota de amostragem (temperatura padrão do provedor, não configurável; a variação é medida com repetições).

### Bloqueio de look-ahead

Com uma data simulada:

- entra só o que tem data de referência até a data de corte;
- o retrato e os fatos registrados depois dela ficam de fora;
- a pesquisa na internet é recusada.

Mesmo assim, o experimento sai marcado como **não comparável** para previsões: o modelo pode conhecer o período pela
base de treinamento, e as séries podem ter sido revisadas depois. Experimentos não comparáveis ficam fora da calibração.

## Avaliação, em dimensões independentes e sem índice composto

| Dimensão | Como é medida |
|---|---|
| A. Correção factual | Veredito do Auditor determinístico (números refeitos contra o dossiê e as ferramentas), ressalvas e números conferidos. Depois, as hipóteses conferidas |
| B. Calibração | Brier das hipóteses com probabilidade, conferidas nas séries oficiais (`resolve_due`, mesma regra e tolerância das Convicções) ou pela pessoa quando a condição é `manual` |
| C. Riscos | Categorias de um vocabulário explícito (`evaluate.RISK_TERMS`) na lista de riscos e na seção "Riscos" |
| D. Consistência | Problemas do registro, contradições ou cálculos apontados pelo Auditor, "dados insuficientes" com confiança alta, hipótese que vence depois do horizonte declarado |
| E. Utilidade | Avaliações registradas, separadas por avaliador. **IA às cegas:** rótulos A/B sorteados, quatro critérios explícitos, e a nota só vale com trecho literal encontrado no texto. **Pessoa:** notas próprias |
| F. Eficiência | Chamadas, tokens (quando o provedor informa) e segundos de cada execução |
| G. Debate | A partir do registro da reunião: falas, contestações, mudanças de posição, correções depois do Auditor, divergências preservadas e falas repetitivas (Jaccard ≥ 0,6) |

**Agregados** (`dashboard`):

- Toda proporção vem com o tamanho da amostra, e a porcentagem com intervalo de Wilson só aparece a partir de 5 casos.
- O Brier vem com a amostra e um intervalo aproximado.
- Um "vencedor" só é declarado com pelo menos **10 comparações decisivas e teste do sinal p < 0,05**. Abaixo disso, o
  painel diz "evidência insuficiente".
- A comparação é feita por repetição: mesmo dossiê, Brier médio de cada modo, empate quando a diferença é menor que
  0,02.

## Acompanhamento temporal

As reavaliações de 30, 90 e 180 dias (ou até 4 prazos personalizados) são criadas em `lab_checkpoints`. Quando a data
chega (`checkpoints`):

1. as hipóteses vencidas são conferidas;
2. o retrato das comparações daquele dia é gravado;
3. uma entrada `resultado_observado` é acrescentada ao Diário do Laboratório.

Se houver hipótese vencida sem dado, a reavaliação fica **pendente** e tenta de novo até a tolerância da fonte (45
dias). A hipótese original nunca é reescrita: há trigger contra mudança, e ela só pode ser conferida uma vez.

## Diário

O **Diário do Laboratório** (`lab_journal`) é append-only e encadeado por SHA-256, como o Diário de Decisões. Ele
guarda:

- o problema analisado;
- a conclusão individual e a coletiva;
- as divergências, as evidências e as hipóteses;
- os resultados observados e o aprendizado de cada reavaliação.

Ele **não é** o Diário de Decisões. Nele só existe o que a pessoa registra: o botão "Registrar no Diário" cria uma
decisão manual (`executada: false`) e a vincula ao experimento (`decisao_vinculada`). Operação feita continua
registrada como resultado da decisão. A página do Diário mostra as análises do Laboratório separadas e rotuladas como
"produzidas por IA".

## Radar e automação

Um sinal que o Radar considera relevante (o mesmo critério que aciona a análise do Conselho) chama
`propose_from_radar`. Por padrão a automação vem **desligada**. As opções em "Experimentos sugeridos pelo Radar" são:

- **Desligada.**
- **Propor:** o experimento fica `proposto` até a pessoa rodar ou recusar.
- **Executar:** roda sozinho.

Há limite semanal, teto mensal de tokens e deduplicação por oportunidade. A proposta roda num savepoint: se falhar,
não deixa nada pela metade nem atrapalha o Radar. Nenhuma análise executa operação financeira.

## Primeiro experimento

1. Abra **Laboratório do Conselho** no menu e toque em **Novo experimento**.
2. Escreva uma dúvida real (ex.: "Com a Selic alta, vale alongar a renda fixa agora?"), escolha a categoria e as
   reavaliações. Mantenha 1 repetição para começar, com a pesquisa desligada.
3. As duas análises rodam em paralelo (o Conselho demora mais). A página atualiza sozinha.
4. Compare as colunas, peça a **avaliação às cegas** e, se quiser, dê a sua.
5. Volte nas datas de reavaliação. Hipóteses com condição de série são conferidas sozinhas. As `manual` pedem o seu
   "aconteceu / não aconteceu" na própria página.

## Limitações conhecidas

- **A conclusão estatística demora.** Com hipóteses de 30 a 180 dias, são meses até haver 10 comparações decisivas.
  Até lá, o painel mostra contagens, não vencedores.
- **Modelos e prompts diferentes por agente.** O Conselho usa os modelos e as instruções de cada agente. A comparação é
  "sistema Bento sozinho × sistema Conselho", não "mesmo modelo × mesmo modelo". O snapshot registra tudo.
- **Avaliação às cegas imperfeita.** A síntese do Conselho cita colegas por @menção, então quem avalia pode inferir a
  autoria. A nota da IA é um avaliador entre outros.
- **Riscos por vocabulário.** O classificador de riscos é por palavras-chave (transparente, mas grosseiro). Não há
  ainda marcação de "risco que se materializou".
- **Custo assimétrico.** O Conselho consome muito mais chamadas. A dimensão F mostra isso, e o painel não mistura custo
  com qualidade.
- **Sem controle de amostragem.** O Claude Code não expõe temperatura. A variabilidade é tratada com repetições.
