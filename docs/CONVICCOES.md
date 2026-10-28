# Convicções: previsões dos agentes e calibração

Os especialistas do Conselho podem declarar expectativas concretas sobre o futuro. O Lastro grava cada uma como foi
dita, confere na data e mede quão bem calibrado cada agente é. Código: `backend/app/convictions.py`, migração 013,
`frontend/src/pages/Convictions.tsx` (tela **Convicções**, menu Mentor).

## Como um agente declara
No parecer ou numa fala do Conselho (`conselho_parecer.md`, `conselho_debate.md`), seção opcional `## Previsões`,
até 3 linhas:

    - 70% · 2027-03-31 · selic_meta < 10.5 · A meta da Selic estará abaixo de 10,5% ao ano.

Probabilidade de 1% a 99% de a afirmação ser verdadeira **na data**; data de amanhã a 5 anos; condição verificável
(série do catálogo de mercado, ou `cripto:BTC`/`ETH`/`SOL`/`USDC` em USDT) ou `—` quando só a pessoa pode conferir.
Linha fora do formato é ignorada. Parecer retido pelo Auditor não grava previsões. A probabilidade e o limiar não
entram na conferência de números do Auditor (não são dados).

## Integridade
Afirmação, probabilidade, data e condição não podem mudar depois (trigger `predictions_frozen`); conferida uma vez,
fica conferida (`predictions_resolved_once`). Idempotente por (mensagem, ordem da linha).

## Conferência
- **Com condição:** o laço do Radar (e a abertura da tela) compara o último dado com data de referência até a data da
  previsão, desde que fresco (validade da série; 2 dias para cripto) e depois que a fonte já publicou algo posterior à
  data. Sem dado utilizável 45 dias depois: **indeterminada**, fora da conta.
- **Sem condição:** a partir da data, a pessoa marca "aconteceu" ou "não aconteceu". Qualquer previsão aberta pode
  ser anulada (também fora da conta).

## Medidas
Brier por previsão `(p − resultado)²` e médio por agente (0 é perfeito; 0,25 = dizer sempre 50%), quantas ficaram do
lado certo, confiança média × frequência observada e calibração por faixa de 20 pontos (diagrama na tela). Menos de 10
conferidas: "amostra pequena". Cada agente recebe no prompt uma linha com o próprio histórico conferido.

## Limitações
- Só previsões no Conselho; conversas livres não geram previsões.
- Condição automática só para o que o Lastro já coleta (séries do catálogo e cripto em USDT).
- "Na data" usa o último valor publicado até a data; não verifica "em algum momento até a data".
