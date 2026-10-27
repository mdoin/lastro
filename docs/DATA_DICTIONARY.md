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

## Dados que nunca são armazenados
Senhas, códigos de autenticação, tokens bancários, cookies, número completo de cartão, seed phrases, chaves privadas e
documentos de identificação desnecessários.

## Exclusão e exportação (LGPD, US-10)
Os triggers append-only protegem o histórico contra reescrita **pelos agentes e pela aplicação**. A exclusão total pedida
pelo proprietário é feita fora da API dos agentes, por procedimento próprio (apagar o arquivo do banco e os backups
correspondentes, com verificação). O procedimento será implementado e testado na Fase 2, junto com a exportação aberta.
