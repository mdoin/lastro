# Fontes de dados

## Dados da pessoa
Retratos, dívidas, metas, premissas, decisões e conversas são digitados pela própria pessoa e ficam só no banco da
instalação (`data`). O Lastro não se conecta a bancos, corretoras nem Open Finance, e não pede senhas dessas
instituições.

## Séries públicas (serviço `collector`)
Coletadas a cada 6 h (`LASTRO_COLLECT_INTERVAL`). Só número e data de referência entram no banco; rótulo, unidade e
fonte vêm do catálogo (`backend/integrations/catalog.py`). Cada série tem idade máxima: depois dela o valor aparece como
**desatualizado**, e sem coleta como **indisponível** — nunca é simulado.

| Série | Fonte | Código | Validade |
|---|---|---|---|
| Meta Selic | Banco Central do Brasil — SGS | 432 | 10 dias |
| CDI anualizado (base 252) | BCB — SGS | 4389 | 10 dias |
| CDI diário | BCB — SGS | 12 | 10 dias |
| IPCA mensal | BCB — SGS (dado do IBGE) | 433 | 75 dias |
| IPCA mensal (direto) | IBGE — SIDRA | tabela 1737, variável 63 | 75 dias |
| IPCA 12 meses | BCB — SGS | 13522 | 75 dias |
| Dólar PTAX (venda) | BCB — SGS | 1 | 10 dias |
| Fed Funds | FRED (St. Louis Fed) | FEDFUNDS | 75 dias, só com `FRED_API_KEY` |
| Treasury 10 anos | FRED | DGS10 | 10 dias, só com `FRED_API_KEY` |
| Preços e taxas do Tesouro Direto | Tesouro Transparente (CKAN) | conjunto "taxas dos títulos ofertados" | ver `collector.py` |

Não conectadas (os agentes dizem que não têm o dado): CVM, ANBIMA, B3 (cotações), SEC.

Termos: BCB/SGS, IBGE/SIDRA e Tesouro Transparente publicam dados abertos; o FRED exige chave própria e alguns dados
têm direitos de terceiros (as duas séries usadas são de fontes do governo dos EUA). Quem opera a instalação faz a coleta
com a própria identidade e deve respeitar os termos de cada fonte.

## Leitura de páginas oficiais (opcional)
Com `LASTRO_BROWSER_EXECUTABLE` configurado, o Economista (que não vê dados da pessoa) pode ler páginas de uma allowlist
(`*.gov.br`, Tesouro Direto, B3, FGC, Anbima). Desligado por padrão no Docker.

## Dados de demonstração e testes
`tests/fixtures_synthetic/` tem só personas fictícias marcadas com `"synthetic": true`; `scripts/demo.py` usa essas
personas. Nenhum dado pessoal real está no repositório (verificado por `tests/security/test_repo_hygiene.py`).

## O que sai da instalação
| Destino | O quê | Quando |
|---|---|---|
| Fontes públicas acima | requisições de séries (sem dados da pessoa) | coletor |
| Provedor de IA escolhido | pergunta, resumo do histórico, resultados das ferramentas do agente | só ao usar agentes |
| Páginas oficiais | URL lida, sem parâmetros (`?`) quando há dados da pessoa na sessão | navegador opcional |
| Ninguém mais | sem telemetria, sem analytics, sem servidor do projeto | — |
