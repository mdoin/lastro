# Pesquisa na internet dos agentes

**Os especialistas pesquisam o mundo real antes de afirmar o que é recente, e conversam sobre o que encontraram.**
Código: `backend/mentor/research.py` (ferramentas, buscadores, barreiras de rede), `backend/team/evidence.py` (regras
determinísticas), `backend/app/orchestrator.py` (`_research`), `backend/mentor/prompts/modos/pesquisa_web.md`.

## Como funciona
1. O agente percebe que a resposta depende de algo atual (o Lastro também detecta: eleição, Copom, "hoje",
   notícia, resultado de empresa, lei, indicador) e chama `pesquisar_web` com o **tema público**.
2. O orquestrador abre uma **sessão de pesquisa isolada** do mesmo agente (passo `…>pesquisa#n`, tipo `research`):
   - mesma persona, só as ferramentas de internet;
   - **sem** dados financeiros da pessoa, histórico da conversa, notas, nome ou memória;
   - o pedido sai sem valores, números longos, CPF/CNPJ, e-mail, telefone e o nome da pessoa (`evidence.outbound`).
3. A sessão pesquisa e lê as fontes. Prefere as primárias (TSE, Banco Central, IBGE, CVM, B3, Diário Oficial),
   compara fontes e devolve os achados classificados: confirmado oficialmente, divulgado por terceiros, expectativa,
   projeção, opinião ou não verificado. Cada achado vem com URL, data de publicação e data de acesso.
4. O agente volta à conversa (passo de integração) e explica no tom da conversa, citando só as fontes que
   vieram nos resultados. A mensagem guarda as fontes (`sources`, tipo `web`) e a interface mostra
   "Consultou N fontes na internet · hora" e o botão **Ver fontes**.
5. **No Conselho**, as fontes de cada parecer acompanham o texto na pauta, na síntese e na auditoria
   ("Fontes consultadas por Vera: …"). Assim os colegas usam ou contestam a evidência sabendo de quem e de onde ela veio.

## Ferramentas (sessão de pesquisa)
| Ferramenta | Faz |
|---|---|
| `web_search` | Busca (consulta, idioma, região, período `dia/semana/mes/ano`, domínios preferidos). Devolve título, URL, resumo, fonte, se é oficial, data de publicação, data da consulta e o estado de cada buscador |
| `web_open` | Lê uma página pública por HTTP. Se ela exigir navegador (anti-robô, JavaScript), abre no navegador: oficiais pelo leitor isolado, as demais pela aba livre da sessão |
| `web_find` | Localiza um termo na página e devolve os trechos ao redor |
| `web_extract` | Extrai tabelas, links ou datas citadas |
| `ler_pagina_oficial` | Leitura direta no navegador isolado. Funciona só em domínios oficiais: gov.br, jus.br, leg.br, B3, Tesouro Direto, FGC e Anbima |
| `navegador_abrir`, `navegador_clicar`, `navegador_digitar`, `navegador_rolar`, `navegador_voltar`, `navegador_ler` | **Navegador próprio do agente** (aba livre, `browser.BrowserTab`): qualquer site público, com JavaScript, clique e digitação pelos `elementos` numerados de cada página. A tela aparece ao vivo na conversa |

### Navegador livre (aba da sessão de pesquisa)
Existe só na sessão de pesquisa, que não tem dados da pessoa; por isso navega em qualquer site público. As barreiras
são as mesmas da leitura por HTTP e ficam fora do Chrome: toda requisição da página (qualquer método) sai por
`research.pinned_request`, com `https`, nome resolvido no worker, todos os IPs públicos e conexão no IP conferido, sem
DNS rebinding. Cada redirecionamento é conferido de novo. WebSocket, WebRTC, downloads, service workers, vídeo e
áudio ficam bloqueados. A aba tem contexto anônimo próprio (os cookies morrem com a pesquisa), no máximo 2 abas ao
mesmo tempo, 40 ações por pesquisa, 800 requisições por ação, 5 MB por resposta e 45 s por ação. O agente é orientado a
não fazer login, cadastro, compra nem publicação. Testes: `tests/integration/test_free_browser.py`, com o Chrome real e
a rede simulada.

Os agentes com dados da pessoa só têm `pesquisar_web` (o pedido). As ferramentas acima existem apenas na sessão
de pesquisa. `tools_for` recusa juntar internet aberta e dados do dono na mesma sessão.

## Buscadores (escolha pela variável `LASTRO_SEARCH_PROVIDERS`, nesta ordem)
| Buscador | Custo | Configuração | Observação |
|---|---|---|---|
| SearXNG (auto-hospedado) | gratuito (sua infraestrutura) | `LASTRO_SEARXNG_URL` | **Recomendado.** Ative `search.formats: [html, json]` no `settings.yml` |
| Brave Search API | **pago por uso** (crédito mensal; exige cartão) | `LASTRO_BRAVE_API_KEY` ou `LASTRO_BRAVE_API_KEY_FILE` | Desligado sem chave; nada é cobrado automaticamente pelo Lastro |
| GDELT DOC 2.0 | gratuito, sem chave | — | Notícias com data; limite público de 1 consulta a cada 5 s (aviso de limite conta como indisponível) |
| Wikipédia (API) | gratuito, sem chave | — | Contexto consolidado, não notícia de última hora |

Sem configurar nada, valem GDELT, Wikipédia e a leitura direta de páginas. Não presumimos que o modelo tenha busca
própria incluída na assinatura: toda pesquisa passa por estas ferramentas, e o que aparece como fonte foi de fato
consultado.

**SearXNG em 3 passos (Docker):** `docker run -d --name searxng -p 127.0.0.1:8888:8080 -v ./searxng:/etc/searxng
searxng/searxng`. Depois, em `searxng/settings.yml`, inclua `json` em `search.formats` e reinicie. Por fim, defina
`LASTRO_SEARXNG_URL=http://127.0.0.1:8888` no ambiente do **worker do mentor**: no systemd, em
`/etc/meu-patrimonio/pesquisa.env`; no Compose, no `.env`.

**Chave da Brave (opcional):** crie a conta em https://brave.com/search/api/, escolha o plano e copie a chave do painel.
Salve-a num arquivo 0600 e aponte `LASTRO_BRAVE_API_KEY_FILE` para ele. A chave vai só no cabeçalho
`X-Subscription-Token`, nunca para o modelo, a interface ou os logs.

## Barreiras de segurança (no código, testadas em `tests/integration/test_research.py`)
- **Endereços aceitos:** só `https` na porta 443. Ficam de fora usuário/senha na URL, IP literal e nomes internos
  (`localhost`, `.local`, `.internal`…).
- **Resolução e conexão:** o nome é resolvido no worker e **todos** os endereços precisam ser públicos. São recusados
  loopback, redes privadas, link-local (metadados de nuvem em 169.254.169.254), CGNAT, ULA e IPv4 mapeado em IPv6. A
  conexão vai ao IP conferido, sem nova resolução (não há DNS rebinding), com SNI e certificado do nome original.
- **Redirecionamentos:** seguidos à mão, cada salto revalidado (no máximo 5); rebaixar para http também é recusado.
- **Requisição e resposta:** só GET, sem cookies, sem credenciais, cliente novo por leitura. Limite de 3 MB, 15 s e só
  tipos de texto.
- **Injeção de instruções:** o texto das páginas volta marcado como dado não confiável. A sessão de pesquisa não tem
  nada a perder (nenhuma ferramenta de dados, memória, delegação ou escrita), e o resultado entra na conversa entre
  marcadores de dado.
- **Fontes inventadas:** a auditoria aponta URL citada cuja fonte nenhuma ferramenta abriu nesta resposta
  ("Fonte citada sem consulta registrada").
- **Logs:** o que fica registrado é a consulta (já higienizada), os buscadores, as URLs e as datas, no passo da
  execução. Chaves e cookies não são registrados.

## Limites e custo
| Variável | Padrão | O quê |
|---|---|---|
| `LASTRO_RESEARCH_MAX_SEARCHES` / `_MAX_OPENS` | 6 / 8 | Buscas e páginas por sessão de pesquisa |
| `LASTRO_RESEARCH_PER_TURN` | 2 | Pesquisas por fala de um agente |
| `LASTRO_RESEARCH_PER_RUN` | 8 | Pesquisas por execução (uma reunião inteira) |
| `LASTRO_RESEARCH_PER_DAY` | 60 | Pesquisas por pessoa, por dia |
| `LASTRO_RESEARCH_REUSE_MINUTES` | 30 | A mesma pergunta na mesma conversa reaproveita a pesquisa (e as fontes) em vez de repetir |

Cada pesquisa custa chamadas ao modelo (a sessão de pesquisa e a integração) e, se a Brave estiver ligada, consultas
pagas. Limite atingido vira aviso honesto ("pesquisa não feita: limite…"), nunca uma resposta inventada.

## Conversar primeiro
Regra 14 do `_base.md`: conversar primeiro, aprofundar quando precisar e estruturar formalmente só quando pedido
(relatório, tabela, comparativo, estudo detalhado; o Lastro detecta e libera o formato) ou quando a tarefa exige
(parecer do Conselho, delegação). No grupo, uma ideia de cada vez, sem repetir o colega. A fala de um colega
consultado vai direto para a pessoa, nunca como recado ao Bento. Ressalva decisiva fica no texto principal.

## Limitações conhecidas
- Sites com proteção anti-robô às vezes recusam até o navegador (o DuckDuckGo recusa; o Bing funciona). Sem
  `LASTRO_BROWSER_EXECUTABLE`, não há navegador e a ferramenta diz que não conseguiu ler.
- Para indicadores, prefira `dados_mercado`, com as séries oficiais já coletadas.
- A higienização retira valores e identificadores, não o sentido de uma frase. O agente é orientado a escrever só o
  tema público.
- PDFs não são lidos pela pesquisa (só texto, HTML, JSON, XML e CSV).
- Sem SearXNG ou Brave, a busca geral fica limitada (GDELT para notícias, Wikipédia para contexto).
