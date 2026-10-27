# Lastro Radar e Diário de Oportunidades

O Radar observa fontes financeiras legítimas, detecta condições com regras determinísticas, avalia cada sinal (dados,
custos, adequação ao seu momento), chama o Conselho só quando a análise acrescenta algo, alerta com moderação e
**registra tudo no Diário de Oportunidades**, inclusive o que não virou alerta. Depois, volta a cada registro nos
horizontes combinados e mede, com o critério escrito antes, se a hipótese se confirmou.

O Radar **não executa operações**, não promete retorno, não inventa cotação e não muda regras sozinho.

## Arquitetura

```
 lastro-coletor (rede: só fontes oficiais)            lastro-web (sem rede)
 ─────────────────────────────────────────            ─────────────────────────────────────────────────────────
 BCB/SGS · IBGE/SIDRA · Tesouro Transparente ──►  market_observations (revisões nunca sobrescrevem)
 FRED (com chave)                                         │
                                                          ▼  laço do Radar (a cada 60 s; regra no seu intervalo)
                                            Signal Engine (radar/rules.py: função pura dos pontos já conhecidos)
                                                          │ sinal (fingerprint único)
                                                          ▼
                                            Opportunity Evaluator (radar/evaluator.py)
                                            qualidade · adequação · custos · score · hipótese verificável
                                                          │ registro de DETECÇÃO (imutável, SHA-256 encadeado)
                                       ┌──────────────────┴───────────────────┐
                    classificação ≥ 3 e orçamento diário       senão
                                       ▼                                      │
                       Conselho (orquestrador: execução "radar")              │
                       2–3 especialistas → síntese do Mentor → Auditor        │
                       registro de ANÁLISE (imutável)                         │
                                       └──────────────────┬───────────────────┘
                                                          ▼
                                    Alert Manager (radar/alerts.py): dedup, cooldown, silêncio, limites, entregas
                                                          ▼
                                    Outcome Evaluator (radar/outcomes.py): 7/30/90/180/365 dias, por método
                                                          ▼
                                    Métricas e propostas de ajuste (radar/metrics.py) — só com aprovação
```

| Componente | Arquivo | Interface testável |
|---|---|---|
| Market Data Collector | `integrations/collector.py`, `radar/observations.py` | `collect_once`, `collect_tesouro`, `parse_tesouro`, `_parse_sidra`, `record`, `history(known_at=…)` |
| Signal Engine | `radar/rules.py` | `validate`, `evaluate`, `evaluate_reserve`, `evaluate_stale` (puras) |
| Opportunity Evaluator | `radar/evaluator.py` | `data_quality`, `suitability`, `classify`, `hypothesis`, `select_agents` |
| Multi-Agent Analysis | `app/orchestrator.py` (`submit_radar`, `_radar`) | execução persistente em `runs`/`run_steps` |
| Alert Manager | `radar/alerts.py` | `process`, `in_quiet_hours`, `mute`, `set_channel` |
| Opportunity Journal | `radar/journal.py` | `add_snapshot`, `verify_chain`, `set_state`, `add_decision`, `add_operation` |
| Outcome Evaluator | `radar/outcomes.py` | `compute_due`, métodos `td_marcacao`, `preco_total`, `serie_macro`, `reserva` |
| Backtest | `radar/backtest.py` | `run_backtest` |
| Laço | `radar/engine.py` | `Radar.tick()` |
| API web | `app/radar_web.py` | rotas `/api/radar/*` |
| Dashboards | `frontend/src/pages/Radar.tsx`, `Opportunities.tsx` | `/radar`, `/oportunidades`, `/oportunidades/:id` |

O laço roda dentro do web app (que tem o banco e o orquestrador) e não tem rede. Agentes nunca ficam rodando para
consultar preço: só são chamados quando um sinal passa a classificação mínima e há orçamento diário de análises.

## Fontes

| Fonte | Estado | O que entra |
|---|---|---|
| Banco Central — SGS | **conectada** | Selic meta (432), CDI anualizado (4389) e diário (12, ~420 dias por intervalo de datas), IPCA mensal (433) e 12 meses (13522), PTAX venda (1) |
| IBGE — SIDRA | **conectada** | IPCA mensal direto (tabela 1737, variável 63); cruzado com o IPCA do SGS: divergência marca o dado como `suspeito` |
| Tesouro Transparente (dados abertos) | **conectada** | taxa e PU de compra e de recompra de todos os títulos do Tesouro Direto, diário; arquivo de ~15 MB baixado no máximo a cada 20 h, condicional (`If-Modified-Since`); HTTP 429 respeitado (`Retry-After` × 4) |
| FRED | conectada **se houver `FRED_API_KEY`** | Fed Funds, Treasury 10 anos |
| B3 (cotações de ações, ETFs, FIIs) | **não conectada** | exige licença; enquanto isso, preços, proventos e eventos podem ser **informados pela pessoa** (fonte registrada como "pessoa") |
| ANBIMA, CVM, SEC | **não conectadas** | exigem credencial, licença ou conector a fazer; nunca simuladas |

Cada observação tem: id, fonte, série, data de referência, hora da coleta, valor, unidade, moeda, frequência, revisão
(`supersedes_id`) e qualidade (`ok`/`revisado`/`suspeito` + detalhes). Datas futuras (Selic projetada) não são
avaliadas. Textos das fontes nunca entram nos prompts: rótulos vêm do catálogo do Lastro; tipo de título desconhecido
no arquivo do Tesouro é descartado e contado; cabeçalho diferente do esperado faz o conector parar.

Validação contra as fontes reais (27/10/2026): BCB e SIDRA responderam no formato esperado (IPCA set/2026 = 0,82% nas
duas); o arquivo do Tesouro trouxe 64.164 observações recentes (257 séries, 0 linhas descartadas) e reprocessá-lo não
duplicou nada; o FRED ficou "indisponível" sem chave, como deve.

## Regras

Tipos: `limite` (≥/≤ um valor, com tolerância e rearme), `variacao` (p.p. ou % numa janela, alta/baixa/qualquer),
`queda` (desde a máxima da janela), `reserva` (meses de despesas essenciais) e `dado_desatualizado`. Cada regra tem id,
tipo, parâmetros, padrão de séries (`td_ipca_*_taxa_compra`), filtro de vencimento, intervalo, prioridade, horizontes,
estado e **versão** (toda alteração cria uma nova; o sinal guarda a versão que o disparou). Regras iniciais (origem
"sistema"), todas editáveis:

| Regra | Categoria | Prioridade |
|---|---|---|
| Tesouro IPCA+ com taxa real ≥ 7% a.a., vencimento ≥ 3 anos (rearme 30 dias) | renda fixa | 3 |
| Alta ≥ 0,5 p.p. em 30 dias nas taxas do Tesouro IPCA+ | renda fixa | 3 |
| Tesouro Prefixado ≥ 14% a.a., vencimento ≥ 2 anos | renda fixa | 3 |
| Mudança ≥ 0,25 p.p. na meta Selic em 60 dias | macro | 1 |
| IPCA 12 meses ≥ 4,5% (teto da meta) | macro | 2 |
| Dólar PTAX ±5% em 30 dias | macro | 2 |
| Reserva de emergência < 3 meses | patrimônio | 5 |
| Séries oficiais desatualizadas | macro | 1 |

## Classificação e score

Níveis: 1 Informativo · 2 Em observação · 3 Potencialmente interessante · 4 Alta prioridade para avaliação · 5 Alerta de
risco. Nunca "imperdível" ou "garantido".

Score = 0,4 × magnitude + 0,3 × qualidade dos dados + 0,3 × adequação. Magnitude = quanto passou do limite, em unidades
da tolerância (limite), ou a variação sobre 2× o mínimo (variação/queda), limitada a 1. Qualidade = 1 (válido), 0,5
(desatualizado ou divergente), 0 (sem dado). Adequação = 1 (adequado), 0,5 (condicional/desconhecido), 0 (inadequado
agora). **O score ordena sinais para investigação; não é probabilidade de lucro.**

Ajustes da classificação (cada um registrado com o motivo): qualidade abaixo do ideal rebaixa um nível; inadequado ao
momento financeiro limita a 2; queda de preço limita a 3; nível 3 com magnitude máxima, dados bons e adequação plena
sobe a 4 (exceto queda). Risco (5) não é rebaixado.

Adequação (determinística, a partir do diagnóstico, metas e fatos confirmados): etapa "priorizar dívida", "organizar
orçamento" ou "sem recurso" → inadequado agora; reserva incompleta → condicional (exceto Tesouro Selic); título que
vence depois das suas metas → condicional (marcação a mercado); perfil confirmado conservador + renda variável →
condicional.

## Conselho

Agentes por categoria (no máximo 3): renda fixa → Analista, Economista, Riscos; ações/ETFs/FIIs → Analista, Riscos,
Conselheiro; macro → Economista, Riscos; patrimônio → Planejador, Riscos. O Planejador entra quando a adequação é
condicional ou inadequada; o Conselheiro, quando o movimento é extremo (risco de FOMO). Sem delegação, com os prazos
e retentativas do orquestrador, `LASTRO_RUN_CONCURRENCY` e o limite diário `max_analyses_per_day` (padrão 4). O
contexto do sinal na conversa só tem dados de mercado; a adequação ao seu momento vai só na tarefa dos agentes que podem
ver seus dados (o Economista, que lê a web, não recebe). A síntese do Mentor passa pelo Auditor determinístico e
semântico; reprovada, é corrigida uma vez ou substituída por explicação transparente. Pareceres, síntese e veredito da
auditoria entram no registro de análise.

"Discutir com o Mentor" e "Convocar o Conselho" abrem uma conversa com o registro do Diário como contexto (separando o
que se sabia na época do que foi descoberto depois) e guardam o vínculo (`radar_links`); a conversa mostra o caminho de
volta. O Mentor, o Planejador, o Analista e o Gestor de Riscos têm a ferramenta `diario_radar` (somente leitura, pela API
dos agentes) para responder "o que o Radar identificou no último mês?" com os registros, e o Auditor confere os números
contra o mesmo resumo.

## Alertas e notificações

Alerta quando a classificação ≥ `min_priority` (padrão 3) ou é risco. Alertas semelhantes (mesma regra e mesmo
ativo; para o Tesouro, a mesma família — todos os vencimentos do IPCA+ são um assunto) dentro do cooldown (72 h) viram
ocorrência do alerta existente, e a nova oportunidade fica marcada como repetida. Silenciar semelhantes vale de 1 a 365
dias. Limite diário de notificações (padrão 5; risco ignora o limite) e horário de silêncio (22h–7h, fuso de São Paulo)
para canais externos. Histórico de entrega por canal em `radar_deliveries`.

Canais externos (e-mail, Telegram, push PWA): ativar exige consentimento explícito na tela. **Nenhum transporte externo
está implementado**: a entrega fica registrada como "não configurado". Implementar um transporte = registrar a função em
`alerts.TRANSPORTS` (com credenciais fora do repositório) — pendente, ver `PENDING.md`.

## Diário de Oportunidades

- **Registro de detecção** (imutável): regra e versão, parâmetros, sinal, valor e observação de origem (id e revisão),
  últimos 30 pontos, dados do Tesouro no mesmo dia (taxa, PU de compra e de recompra), contexto macro com validade,
  qualidade, adequação e o perfil usado, custos e impostos considerados, classificação com motivos, score com pesos,
  hipótese com critério e mecanismo, horizontes, referência, agentes selecionados e limitações.
- **Registro de análise** (imutável): pareceres, síntese, auditoria, estado da execução. Só aceito antes de existir
  resultado posterior.
- **Correções**: novo registro `correcao` com motivo; o original fica.
- Triggers impedem UPDATE/DELETE de sinais, registros, linha do tempo, decisões, operações, versões de regra e
  avaliações calculadas; a classificação original não muda. Os registros são encadeados por SHA-256 (cada um inclui o
  hash do anterior) e a tela mostra se a cadeia está íntegra.
- Estado operacional (detectada → em análise → avaliada → alerta emitido → em acompanhamento → encerrada / invalidada /
  inconclusiva) é separado do desempenho; cada mudança vai para a linha do tempo.
- Decisões da pessoa (analisei, ignorei, decidi investir, decidi não investir, quero acompanhar, outra) e **operações
  reais informadas** ficam em tabelas próprias, fora do desempenho hipotético. O Lastro não presume que um alerta virou
  compra.

## Metodologia de avaliação

Hipótese e critério vêm do registro de detecção. Cada horizonte (padrão 7, 30, 90, 180 e 365 dias a partir da data de
referência do sinal) é calculado uma vez por versão de método; o primeiro dado até 7 dias depois do horizonte serve
(45 para séries mensais); sem dado, espera mais 10 dias e então registra "dados insuficientes".

| Método | Produto | Cálculo |
|---|---|---|
| `td_marcacao` | Tesouro Direto | PU de compra na detecção → PU de recompra no horizonte (resgate antecipado); custódia 0,20% a.a. pro rata; IOF regressivo (< 30 dias) e IR regressivo sobre o ganho; mesmo IR/IOF aplicados ao CDI acumulado (série 12) como referência; retorno real pelo IPCA mensal; maior queda e volatilidade da trajetória; variação da taxa (mecanismo). O retorno contratado (carregamento até o vencimento) é registrado à parte. Título que vence antes do horizonte: "dados insuficientes" (v1 não avalia vencimento). |
| `preco_total` | ações, ETFs, FIIs (preços informados) | retorno total = (ações × preço final + proventos recebidos) ÷ preço inicial − 1, com desdobramento/grupamento/bonificação ajustando a quantidade; retorno de preço ajustado; comparação bruta com o CDI (impostos e custos dependem de você); maior queda e volatilidade. |
| `serie_macro` | indicadores | evolução do valor; sem hipótese de retorno. |
| `reserva` | patrimônio | reserva em meses no retrato mais recente do período. |

Veredictos (por horizonte): **confirmada** (excesso sobre o CDI ≥ 0 e mecanismo esperado aconteceu, ou sem mecanismo);
**favorável por outro motivo** (bateu o CDI, mas o mecanismo não aconteceu — ex.: ganhou pelo carregamento, não pela
queda da taxa; não conta como acerto do raciocínio); **não confirmada**; **inconclusivo** (|excesso| < 0,10 p.p.);
**invalidada** (o dado que disparou o sinal foi revisado pela fonte); **dados insuficientes**; **sem hipótese**
(informativo). Oportunidade encerra quando todos os horizontes saem: invalidada se algum invalidou; inconclusiva se
todos foram inconclusivos ou sem dados; senão encerrada. Corrigir a metodologia: `outcomes.reschedule_method(conn,
"2", now)` agenda a nova versão para tudo; as métricas usam a versão mais recente e as antigas ficam.

## Métricas e aprendizado controlado

Por período, categoria, regra e mês: sinais, alertas, precisão (confirmadas ÷ avaliáveis), favorável por outro motivo,
invalidados, dados insuficientes, repetidos, utilidade informada por você, excesso médio sobre o CDI e latências
(evento → detecção, detecção → alerta). Toda taxa sai com `n` e `confiavel` (n ≥ 20). Backtests nunca entram.

Uma vez por dia o Radar procura regras ruidosas (≥ 20 casos: metade repetidos → dobrar o rearme; metade sem dados →
pausar; ≥ 70% irrelevantes → baixar prioridade; < 30% de confirmação numa regra de limite → limite mais exigente) e
cria **propostas** com backtest do ajuste. Nada muda sem você aprovar; aprovar cria nova versão de regra (origem
"proposta"); proposta sobre versão antiga fica obsoleta.

## Backtest

`POST /api/radar/rules/{id}/backtest`: avalia a regra dia a dia só com o passado (mesma função do monitoramento),
calcula os resultados com o mesmo método (custos e impostos), descarta horizontes além do fim dos dados, inclui títulos
já vencidos (sem viés de sobrevivência), separa dentro (60%) e fora (40%) da amostra e mostra segmentos sequenciais.
Resultado rotulado como simulado, guardado em `radar_backtests`, fora das métricas. Limitação: o histórico guardado é
curto (~400 dias do Tesouro, ~420 do CDI) e revisões anteriores à coleta não são conhecidas.

Exemplo real (dados de set/2025 a out/2026): a regra "Tesouro IPCA+ ≥ 7%" confirmou a hipótese em 9% dos casos dentro
da amostra e 28% fora, com excesso médio de −2,89 p.p. e −0,45 p.p. sobre o CDI — sinal fraco no curto prazo enquanto
as taxas subiam. É para isso que o Diário existe.

## Segurança

Sem rota que execute operação (os testes de segurança cobrem nomes de funções e rotas); "operação informada" só
registra. Web app continua sem rede; só o coletor busca dados (allowlist de imports). Especialistas continuam sem
terminal, arquivos ou web livre; o Economista segue sem dados do dono. Rotas `/api/radar/*` exigem sessão, CSRF
(`X-Lastro`) e filtram por dono (registro de outra pessoa = 404). Ações relevantes vão para `audit_log`.
Ferramenta educativa e de organização: não substitui análise ou consultoria de valores mobiliários (CVM 20/21 e 19);
uso por terceiros exige revisão regulatória (PENDING #17).

## Implantação

1. Backup: `sudo -u patrimonio sqlite3 /var/lib/patrimonio/lastro.db ".backup /var/lib/patrimonio/pre-v6.db"`.
2. `(cd frontend && npm ci && npm run build)` e `sudo scripts/deploy.sh` (o web app aplica a migração 006 ao iniciar).
3. `sudo systemctl restart lastro-coletor` (novas séries e o Tesouro; o primeiro arquivo leva alguns segundos).
4. Conferir: tela Radar → Monitoramento (fontes ok), Regras (8 regras do sistema), e o Diário após a primeira volta.
5. Opcional: `LASTRO_RADAR_RETENTION_DAYS` (padrão 3650) no ambiente do `lastro-web`.

Rollback: a migração 006 só acrescenta tabelas; o código anterior as ignora. `git checkout <commit anterior>`, rebuild e
`deploy.sh`. Para voltar o banco, pare os serviços e restaure `pre-v6.db` (perde o que foi registrado depois).

## Limitações e pendências

- Cotações de ações/ETFs/FIIs: sem fonte licenciada (B3); só preços informados pela pessoa.
- CVM (fundamentos, informes de FII), ANBIMA e SEC: não conectadas.
- Carteira real do usuário não existe no Lastro: riscos patrimoniais cobrem só a reserva (retrato financeiro);
  concentração, rebalanceamento e vencimentos da carteira dependem de cadastrar posições.
- Transportes externos de notificação não implementados (ficam "não configurado").
- Método de renda fixa v1 não soma cupons de títulos com juros semestrais: horizontes que cruzam uma data de cupom
  ficam "dados insuficientes" em vez de um veredito enviesado (corrigir = método v2 com cupons e `reschedule_method`).
- Impostos são estimativas (IR regressivo e IOF); renda variável sem IR.
