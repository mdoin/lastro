# Contratos da API de leitura para agentes (v1)

Base: `http://127.0.0.1:8765`. Cabeçalho obrigatório: `Authorization: Bearer $MPA_AGENT_API_TOKEN`.
Apenas `GET`. Qualquer outro método recebe `405` com `Allow: GET`. Valores monetários vêm como **string decimal**.
Todas as respostas trazem `data_kind: "synthetic"` nesta fase.

| Rota | Parâmetros | Resposta |
|---|---|---|
| `GET /v1/health` | — | `status`, `engine_version`, `mode: read-only` |
| `GET /v1/personas` | — | `as_of`, lista `{id, label}` |
| `GET /v1/personas/{id}/diagnosis` | `reserve_months` (1–24, padrão 6), `reference_annual_return` (padrão `0.10`) | `reserve{…}`, `guidance{stage, next_step, situation[3], allocation[], comparisons[], premises[], missing_information[], checklist[4], follow_up, disclaimer}` |
| `GET /v1/projection` | `initial`, `contribution` (ponto decimal), `months` (0–960) | `projections[]` por cenário: `final_nominal`, `final_real_todays_money`, `total_contributed`, `market_result`, `assumptions`, `limitations`, `inputs_fingerprint` |

Códigos: `401` sem token válido · `403` dado não sintético · `404` inexistente · `405` método de escrita · `422` parâmetro inválido.

## Handoff entre agentes

Formato da seção 4 do plano, validado por `financial_engine.handoff.validate_handoff`. Regras adicionais:
- fato sem fonte → inválido (rotular como hipótese);
- `status: complete` com `missing_information` não vazio → inválido (usar `needs_review`);
- toda fonte precisa de `title`, `url` e `accessed_at`.
