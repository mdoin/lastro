# Dicionário de dados (esquema v1)

Fonte da verdade: `backend/app/schema.sql`. Convenções:

- **IDs**: UUID em `TEXT`.
- **Datas**: ISO 8601; data-hora sempre com fuso (`2026-10-26T10:00:00-03:00`).
- **Dinheiro, quantidades e taxas**: `TEXT` com `Decimal` serializado. Colunas `REAL`/`FLOAT` são proibidas (há teste).
- **Taxas**: fração decimal (`0.12` = 12%), com o período explícito no nome (`monthly_rate`, `cet_annual`).
- **Moeda**: código ISO 4217 (`BRL`, `USD`).

| Tabela | Finalidade | Regras de integridade |
|---|---|---|
| `users` | Proprietário e preferências | — |
| `financial_profiles` | Perfil de risco versionado (data, versão, motivos) | `UNIQUE(user_id, version)` |
| `accounts` | Contas por **apelido** da instituição | Nunca agência/conta completas |
| `assets` | Cadastro de ativos | — |
| `transactions` | Livro de eventos | `import_hash UNIQUE` (idempotência); retificação via `supersedes_id`; conciliadas não podem ser apagadas |
| `prices` | Cotações com proveniência | `source`, `retrieved_at`, `reference_date`, `is_estimate`, `license` |
| `positions_snapshots` | Posições conciliadas por data | `provenance` obrigatório |
| `liabilities` | Dívidas | `as_of` obrigatório |
| `budgets` | Orçamento planejado × realizado | `status ∈ {planejado, realizado}` |
| `goals` | Metas em poder de compra de `base_date` | — |
| `assumptions` | Premissas de cenário | — |
| `simulations` | Resultado + `engine_version` + `inputs_fingerprint` | **Append-only** |
| `research_reports` | Pareceres de agentes com fontes | `review_status` ∈ PASSA/REVISAR/BLOQUEAR/pendente |
| `decision_log` | Diário de decisões; `confirmed` separa plano de aporte efetivo | **Append-only**; revisão = novo registro (`review_of_id`) |
| `audit_log` | Trilha de acesso | **Append-only** |

## Radar e Diário de Oportunidades (migração 006, ver `RADAR.md`)
| Tabela | Finalidade | Regras de integridade |
|---|---|---|
| `market_series` | Metadados por série (fonte, unidade, moeda, frequência, categoria, validade, vencimento) | — |
| `market_observations` | Observações com revisão (`revision`, `supersedes_id`) e qualidade | Sem UPDATE; usada por sinal não pode ser apagada; retenção apaga a data inteira |
| `market_source_status` | Estado por fonte (próxima tentativa, `Last-Modified`) | — |
| `radar_rules` | Regras versionadas (PK `id, version`) | Sem UPDATE/DELETE |
| `radar_rule_state`, `radar_rule_proposals` | Última avaliação; propostas de ajuste | Proposta só vale aprovada |
| `radar_signals` | Sinal (`fingerprint UNIQUE`, versão da regra, observação de origem) | Imutável |
| `radar_opportunities` | Diário: estado operacional, classificação original, `redundant_of` | Sem DELETE; classificação e score imutáveis |
| `radar_snapshots` | Registros de detecção, análise e correção encadeados por SHA-256 | Imutáveis |
| `radar_events` | Linha do tempo | Append-only |
| `radar_outcomes` | Avaliação por horizonte e versão de método | `UNIQUE(oportunidade, horizonte, versão)`; calculada é imutável |
| `radar_alerts`, `radar_deliveries` | Alerta (1 por oportunidade); histórico de entrega por canal | — |
| `radar_prefs`, `radar_channels`, `radar_mutes` | Preferências, canais com consentimento, silenciamentos | — |
| `radar_decisions`, `radar_user_operations` | Decisões e operações reais informadas pela pessoa | Append-only, fora do desempenho hipotético |
| `radar_corporate_events` | Eventos corporativos informados | `UNIQUE(série, data, tipo)` |
| `radar_backtests` | Resultados simulados | Nunca entram nas métricas |
| `radar_links` | Conversa ↔ oportunidade | — |

## Dados que nunca são armazenados
Senhas, códigos de autenticação, tokens bancários, cookies, número completo de cartão, seed phrases, chaves privadas e
documentos de identificação desnecessários.

## Exclusão e exportação (LGPD, US-10)
Os triggers append-only protegem o histórico contra reescrita **pelos agentes e pela aplicação**. A exclusão total pedida
pelo proprietário é feita fora da API dos agentes, por procedimento próprio (apagar o arquivo do banco e os backups
correspondentes, com verificação). O procedimento será implementado e testado na Fase 2, junto com a exportação aberta.
