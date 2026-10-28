# Radar cripto e convocação autônoma do Conselho

**O Radar observa, o Conselho investiga e o Bento explica. Nada aqui compra, vende, custodia ou move ativos.**
Código: `backend/crypto/` (fontes, modelos, sinais, serviço), `backend/app/crypto_web.py`, migração 012,
`frontend/src/pages/CryptoRadar.tsx` e `Notifications.tsx`.

## Fontes (somente leitura)
| Fonte | Chave | O que usamos | Frequência padrão |
|---|---|---|---|
| Binance Public Market Data (`data-api.binance.vision`) | não | `ticker/24hr`, `klines` 1 h, `exchangeInfo`; pares em **USDT** | 5 min (`LASTRO_CRYPTO_BINANCE_SECONDS`) |
| CoinGecko Demo (`api.coingecko.com`) | sim (Demo, gratuita) | `simple/price` em BRL e USD; `coins/markets`, `market_chart`, `coins/list` sob demanda | 15 min (`…_COINGECKO_SECONDS`) |
| DefiLlama (`api.llama.fi`) | não | `/v2/chains`, `/v2/historicalChainTvl` (e `/protocols`, `/protocol/{slug}` na camada de fontes) | 6 h (`…_DEFILLAMA_SECONDS`) |

`crypto/sources.py` é o único módulo com cliente HTTP: hosts fixos, só https, sem seguir redirecionamento,
identificadores validados por regex (sem SSRF), limite de taxa, retentativas com backoff que respeitam `Retry-After`,
418 da Binance bloqueia a fonte até o prazo, peso de requisição da Binance acompanhado, cache por TTL. A chave da
CoinGecko vai só no cabeçalho `x-cg-demo-api-key`; sem chave, a fonte fica "aguarda chave" e as outras funcionam.
Cota da CoinGecko: 10.000 chamadas/mês e 100/minuto (Demo); a coleta automática para quando sobram 15% do mês, para
consultas suas. O consumo do mês fica em `crypto_usage` e aparece na tela.

**Moedas:** preço da Binance é em USDT e é rotulado assim; nada converte USDT, USD e BRL sem taxa e fonte explícitas.
Dado com referência antiga é marcado como desatualizado e nunca convoca o Conselho.

## Quem coleta e quem decide
- `lastro-coletor` (único serviço com saída à internet) coleta e grava (`crypto_quotes`, `crypto_candles`,
  `crypto_tvl`), com trava por trabalho em `crypto_jobs` (um executor só, retomada após reinício, saúde, latência).
- O web (sem acesso à internet em produção) avalia os dados novos e convoca o Conselho. "Coletar agora" e "Testar
  conexão" pedem o trabalho ao coletor. Em desenvolvimento, `LASTRO_CRYPTO_COLLECT_IN_WEB=1` coleta no próprio web.
- `LASTRO_CRYPTO_MONITOR=0` desliga tudo.

## Sinais (sem IA)
`crypto/signals.py`: retornos 1 h/4 h/24 h/7 d, volatilidade realizada, volume relativo (mesma hora em dias anteriores),
queda máxima, correlação, desvio de paridade de stablecoin, variação de TVL e concentração da carteira informada.
Amostra insuficiente não gera indicador. Gravidade: comum → atenção → risco → **conselho** (só quando movimento fora
do padrão recente, volume anormal, dado fresco de boa qualidade e ativo acompanhado ou na carteira coincidem).
Hipóteses são observações; palavras de recomendação são recusadas no código.

## Do evento à reunião
1. Sinais agrupados por ativo e direção; dentro do **cooldown** (padrão 12 h) novas ocorrências **atualizam** o evento
   (e a reunião dele recebe a atualização) em vez de criar outro.
2. Atenção: aparece no Radar. Risco: alerta na central de notificações.
3. Conselho: só se você **autorizou reuniões autônomas** (desligado por padrão) e escolheu "alertas e análises", acima
   da gravidade mínima, dado de boa qualidade, fora da pausa e do horário de silêncio, abaixo do limite diário
   (padrão 2), sem outra reunião automática em andamento e dentro do orçamento mensal de tokens. Faltou algo: o evento
   fica **pendente** com o motivo, e nenhum veredito é inventado.
4. O Bento convoca, conforme o evento, Téo e Rui, mais Caio (preço, volume, volatilidade), Lia (carteira informada ou
   concentração), Vera (stablecoin, DeFi) e Nina (movimento forte). A reunião usa o Conselho deliberativo
   (docs/COUNCIL.md), com a ferramenta de leitura `mercado_cripto`. Você entra a qualquer momento, pergunta e cita.
5. Notificações: "Reunião extraordinária iniciada" (com link) e, no fim, o veredito. O registro da reunião guarda o
   evento de origem e o consumo.

## Configurar a chave gratuita da CoinGecko (Demo)
1. Acesse **https://www.coingecko.com/en/api/pricing** (endereço oficial) e escolha o plano **Demo** (gratuito).
2. Crie a conta com e-mail e senha (ou login social) e confirme o e-mail.
3. Entre no **Developer Dashboard**: https://www.coingecko.com/en/developers/dashboard
4. Clique em **"+ Add New Key"**, dê um nome (ex.: "Lastro") e copie a chave gerada (começa com `CG-`).
5. No Lastro: **Radar cripto → Fontes de dados → CoinGecko Demo**, cole a chave no campo e clique **"Salvar no
   servidor"**. Ela fica num arquivo 0600 do servidor (`<pasta do banco>/coingecko.key`) e nunca volta ao navegador.
   Alternativa para quem administra o servidor: variável `LASTRO_COINGECKO_API_KEY` no ambiente do web e do coletor.
   Não cole a chave em conversas, commits ou no `.env.example`.
6. Clique **"Testar conexão"**. Em produção o teste roda no coletor e o status aparece em até 1 minuto.
7. Confirme que os dados chegam: o cartão do ativo mostra o preço em **R$** "pela CoinGecko" com horário de
   referência, e a fonte aparece como "funcionando" com a última coleta.
8. Consumo do mês: o cartão da fonte mostra "Cota: X de 10.000 chamadas no mês" e quando renova; o Developer
   Dashboard da CoinGecko mostra o uso oficial.
9. Erros comuns: **401/10002** chave ausente ou inválida (salve de novo); **10011** chave Demo usada no endereço Pro
   (o Lastro usa o endereço certo; confira se a chave é Demo); **10005** endpoint fora do plano; **429** limite por
   minuto (o Lastro espera e reduz o ritmo); **1020/403** bloqueio de firewall da CDN (rede do servidor); "cota
   reservada" no Lastro = a coleta automática parou para preservar 15% do mês.

Binance e DefiLlama não exigem chave para os endpoints usados; funcionam sem configuração.
Atribuição exibida: "Data provided by CoinGecko", Binance (pares em USDT) e DefiLlama.

## Implantação
Backup (`pre-v12.db`), `npm run build`, `sudo scripts/deploy.sh` e reiniciar `lastro-web` e `lastro-coletor`.
A migração 012 só cria tabelas.
