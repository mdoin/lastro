# Métodos financeiros (motor v0.1.0)

Todo número exibido ao usuário vem de `backend/financial_engine`. Modelos de IA explicam resultados, mas não calculam.

## 1. Representação
- `Decimal` com precisão de 34 dígitos; `float` é recusado (`TypeError`).
- Arredondamento só na apresentação: centavos, `ROUND_HALF_UP`.
- Entrada em formato brasileiro: `parse_brl("1.234,56")`. Entradas ambíguas, como `"10.50"`, são **recusadas** com
  explicação em vez de adivinhadas.

## 2. Taxas
- Mensal a partir da anual efetiva: `r_m = (1 + r_a)^(1/12) − 1`, nunca `r_a / 12`.
- Taxa real (Fisher): `(1 + n) / (1 + i) − 1`.
- Taxa de administração como % do patrimônio ao ano: `(1 + r)(1 − f) − 1`, aplicada antes da conversão mensal.

## 3. Acumulação (`simulate`)
Para cada mês: (1) rende sobre o saldo do início do mês; (2) recebe o aporte **no fim do mês**, exceto nos meses pausados; (3)
resgates no fim do mês. O aporte pode ter reajuste anual. Resgate maior que o saldo gera erro em vez de saldo negativo.

Fórmula fechada usada como prova cruzada (seção 9.1):
`FV = P(1+r)^n + A[((1+r)^n − 1)/r]`; com `r = 0`, `FV = P + A·n`.

`market_result = final − inicial − aportes + resgates`: separa o resultado de mercado do dinheiro depositado.

## 4. Valor real
`real = nominal / (1+i)^(meses/12)` com inflação constante **do cenário**. Séries variáveis exigirão índice encadeado (Fase 3).

## 5. Meta reversa
`A = (FV − P(1+r)^n) · r / ((1+r)^n − 1)`, arredondado **para cima** ao centavo. Para metas em poder de compra atual,
usa-se a taxa real líquida, com a premissa de que o aporte é corrigido pela inflação.

## 6. Diagnóstico mensal (`monthly_guidance`)
Escada determinística:
1. Nada disponível → não investir; revisar o orçamento, sem culpa.
2. Orçamento mensal negativo → cobrir o déficit primeiro.
3. Dívidas com custo mensal **acima do retorno de referência informado** → amortizar da mais cara para a mais barata (avalanche),
   mostrando juros evitados × rendimento hipotético.
4. Reserva abaixo da meta (N meses de despesas essenciais) → reserva.
5. Sobra → investimento para metas. Produtos só serão comparados com fontes verificadas (Fase 3).

O retorno de referência é **premissa do usuário**, não oferta de mercado.

## 7. Limitações conhecidas (v0.1.0)
- **Tributos não modelados.** O IR sobre renda fixa e as isenções serão implementados como regras versionadas, com data de
  vigência e fonte legal verificada (Fase 3), e não como taxa única.
- Cenários determinísticos não têm probabilidade. Monte Carlo só com metodologia validada.
- Câmbio, eventos corporativos, XIRR/TWR: Fase 2.
- Fingerprint: SHA-256 de `engine_version` + entradas canônicas; muda se o motor mudar.
