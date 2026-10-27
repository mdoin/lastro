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
| 2026-10-27 | Equipe = registro versionado + sessões descartáveis por passo, orquestradas no web app | Um processo vivo por agente; sessão longa do Claude por conversa | Contexto montado pelo Lastro isola memória por conversa, sobrevive a reinício e é auditável |
| 2026-10-27 | Fila persistente em SQLite (`runs`, `run_steps`) no próprio web app | Fila externa (Redis/Celery) | Uma pessoa, poucas execuções; sem dependência nova; idempotência por UNIQUE |
| 2026-10-27 | Delegação só via ferramenta "registrada" + limites no orquestrador | Agentes chamando agentes direto | Rastreável, sem acesso às capacidades de outro agente, ciclo/profundidade/total em código |
| 2026-10-27 | Auditor determinístico em toda mensagem; semântico (modelo) só no Conselho (`LASTRO_SEMANTIC_AUDIT`) | Modelo auditando tudo | Custo; texto de modelo não prova correção, só endurece o veredito |
| 2026-10-27 | Economista sem dados do dono (é quem lê a web) | Todos com tudo | Mesmo princípio de capacidades por papel: injeção em página nunca convive com o patrimônio |
| 2026-10-27 | Coletor de séries em serviço próprio (BCB/SGS; FRED com chave); só número e data entram | Agentes buscando dados na web | Web app sem rede; agentes sem internet irrestrita; texto de terceiros fora do prompt |
| 2026-10-27 | Compactação de contexto determinística (autor, data, início) | Resumo gerado por modelo | Verificável e sem custo; trocar se conversas longas perderem fatos (comentário `shortcut:`) |
| 2026-10-27 | Radar determinístico no web app; Conselho só para sinal com classificação ≥ 3 e orçamento diário | Agentes consultando preço continuamente | Custo, previsibilidade e auditabilidade; modelo só onde agrega |
| 2026-10-27 | Observações versionadas (`market_observations`) ao lado de `market_data` | Sobrescrever o valor | O Diário precisa do dado "como era conhecido"; revisão invalida hipótese |
| 2026-10-27 | Tesouro Direto pelo arquivo de dados abertos do Tesouro Transparente, 1×/dia e condicional | API do site do Tesouro Direto (B3) | Fonte oficial com licença aberta; a API do site não é pública; respeita o limite (429) |
| 2026-10-27 | Registros do Diário append-only + cadeia SHA-256 | Só triggers | Triggers impedem a aplicação; o hash revela alteração por fora |
| 2026-10-27 | Veredito por hipótese e mecanismo registrados antes ("favorável por outro motivo" ≠ acerto) | "Subiu = acertou" | Pedido explícito: avaliar o raciocínio, não só o preço |
| 2026-10-27 | Alertas agrupados por família de título (todos os vencimentos do IPCA+) | Por série | Reprodução com dados reais: 631 alertas em 8 meses viraram 88 |
| 2026-10-27 | Cotações de ações, ETFs e FIIs só informadas pela pessoa | Raspagem de sites | Sem licença da B3; raspagem violaria termos |
| 2026-10-27 | Métricas com `n` e `confiavel` (n ≥ 20); propostas de ajuste só com aprovação | Ajuste automático | Evita overfitting e mudança silenciosa de regra |
| 2026-10-27 | Mascotes em pixel art desenhados como dados (grade 16×16 → SVG com `crispEdges`), um componente `AgentAvatar` | PNG/sprites; ícones de biblioteca | Nítido em qualquer tamanho e tema, leve (sem arquivo extra), testável (grade, paleta, silhuetas distintas) |
| 2026-10-27 | Campo de data próprio (`DateInput`): digitação dd/mm/aaaa + calendário no estilo do sistema | `<input type="date">` | O calendário nativo não aceita estilo em nenhum navegador e destoava; teclado no padrão WAI-ARIA |
| 2026-10-27 | Listas suspensas com `appearance: base-select` (CSS) | Componente de lista próprio | Visual do sistema mantendo acessibilidade e teclado nativos; sem suporte, cai na lista nativa |
| 2026-10-27 | Tema claro/escuro escolhível (Automático/Claro/Escuro), salvo no `localStorage`, aplicado por `public/theme-init.js` | Só `prefers-color-scheme` | Pedido do dono; script externo porque a CSP não permite inline; evita piscar o tema errado |
| 2026-10-27 | Diário: agentes propõem por ferramenta "registrada" (`propor_registro_decisao`); o web app monta e valida o rascunho | Agente escrevendo no banco; rascunho só com o texto do modelo | Separação de privilégios; pergunta, fontes, cálculos (refeitos pelo motor), pareceres e auditoria vêm dos registros, não do modelo |
| 2026-10-27 | Rascunho com conteúdo fixo (trigger) e decisão/revisão/resultado append-only com cadeia SHA-256 por pessoa | Editar o rascunho com as correções | Correção da pessoa fica ao lado do texto dos agentes: autoria nunca se mistura |
| 2026-10-27 | Nenhuma alternativa pré-marcada na confirmação | Pré-selecionar a recomendada | Recomendação do Conselho nunca vira decisão sem escolha explícita |
