# Registro de decisões técnicas

| Data | Decisão | Alternativas | Motivo |
|---|---|---|---|
| 2026-10-26 | Python 3.12 do sistema + **uv 0.12.24** em `~/.local/bin` | `sudo apt install python3-venv` | Sem root; o uv cria venv sem `ensurepip` e gera lock com hashes |
| 2026-10-26 | **Node v24.22.1 LTS** em `~/.local/opt/node` | v24.21.0 (mais antigo) | Release de segurança: tem prioridade sobre a regra das 2 semanas |
| 2026-10-26 | `exclude-newer = 2026-10-12` no `pyproject.toml` | Sempre a última versão | Reduz o risco de pacote recém-publicado e comprometido |
| 2026-10-26 | FastAPI para a API dos agentes | `http.server` da stdlib | Plano sugere; validação de parâmetros; registro de rotas inspecionável em teste |
| 2026-10-26 | SQLite com `Decimal` em `TEXT` | Centavos em `INTEGER` | Também comporta quantidades e taxas com muitas casas |
| 2026-10-26 | Tributos **fora** do motor v0.1.0 | Taxa única de IR | Plano proíbe taxa única; regras exigem fonte legal verificada (Fase 3) |
| 2026-10-26 | Cenários de teste com premissas fictícias rotuladas | Valores "de mercado" | Nada de mercado foi verificado nesta fase |
| 2026-10-26 | Dívida "cara" = custo mensal acima do retorno de referência informado | Limite fixo (ex.: 2% a.m.) | Transparente e ajustável; a premissa aparece na resposta |
| 2026-10-26 | Dashboard em Next.js **adiado** até aprovação da Fase 1 | Fazer agora | Portão humano entre fases (seção 17) |
| 2026-10-27 | Redesign "Bloco": base monocromática, painéis aninhados (casca + folha + rodapé), rótulos mono, pílulas | Manter tinta + dourado com serifa | Referências escolhidas pelo dono (Plasma, Project card, Model router, Agent handoff); ouro só onde há significado |
| 2026-10-27 | Marca **Bloco L** (L maciço com faces superiores em ouro) — `docs/brand` | L simples dourado; moeda; lingote | Une as duas leituras de lastro (base que sustenta + lastro-ouro); legível em 16 px e em uma cor |
| 2026-10-27 | Fontes **auto-hospedadas** Inter 4 (com tamanho óptico) + Geist Mono, `@fontsource-variable` 5.2.x, só latim | Pilha de fontes do sistema | Mesma tipografia em qualquer aparelho; `font-src 'self'`; ~105 KB em cache imutável; versões com mais de 14 dias |
| 2026-10-27 | Paletas de gráfico revalidadas (`validate_palette.js`): linhas azul/dourado/verde-água; fluxo azul/laranja/violeta/verde-água | Paleta anterior | Todos os pares passam em claro e escuro; fluxo na ordem essenciais → parcelas → variáveis → livre |
| 2026-10-27 | Participação no fluxo calculada com `ratioDecimal` (BigInt, ROUND_HALF_UP) | Dividir em float | Mantém a regra: valor exibido nunca passa por float |
| 2026-10-27 | Checklist do mês marcável, salvo só no `localStorage` | Persistir no servidor | Conveniência local, sem mudar o contrato da API |
| 2026-10-27 | Bloqueio de login **por cliente** (IP; IPv6 por /64) + atraso global limitado (≤ 5 s), nunca recusa global | Contador global | Auditoria: o contador global deixava qualquer anônimo trancar o dono fora |
| 2026-10-27 | API admin do Caddy em socket Unix 0600 | `localhost:2019` (TCP) | Auditoria: qualquer conta local podia trocar a borda TLS |
| 2026-10-27 | Navegador: guarda busca cada requisição com `max_redirects=0`; Chrome com proxy morto, resolvedor travado e sem WebRTC | Só `context.route` | Auditoria: redirecionamentos e WebSockets passavam ao largo da guarda |
| 2026-10-27 | Capacidades por papel: navegador livre só na `pesquisa` (sem dados do dono); chat com hosts exatos e sem query; rotinas sem navegador | Todos os papéis com tudo | Pista da auditoria: dado do dono poderia sair numa URL após injeção indireta |
| 2026-10-27 | `max_turns` por papel + prazo por tentativa (600 s chat, 420 s efêmero) | Sem limite | Pista da auditoria: loop de ferramentas segurava vagas e suprimia rotinas |
