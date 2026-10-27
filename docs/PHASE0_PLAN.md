# Fase 0 — Plano de execução e status

Resposta do Coordenador ao "prompt de arranque" (plano mestre v1.1, seção 17).
Data: 2026-10-26. Escopo: **somente Fase 0 + protótipo do motor/API da Fase 1, com dados fictícios.**
Nenhuma integração bancária, nenhum dado real, nenhum deploy.

## 1. Arquitetura inicial e premissas técnicas

```
 Usuário ──► Dashboard local (Fase 1, Next.js — pendente de aprovação)
                │
                ▼
     Backend Python (FastAPI) ── Motor financeiro determinístico (Decimal, testado)
                │                         │
                │                  SQLite (esquema v1, append-only onde importa)
                ▼
     API de LEITURA para agentes  (GET-only · loopback · token · só dados sintéticos)
                │
                ▼
     OpenBot (VM/usuário dedicado) ── agentes AG-00..AG-06 ── modelo (Claude Code/Codex)
                │
                ▼
     Fontes públicas em allowlist (Fase 3)

     ✗ Nenhum caminho de escrita para banco/corretora existe no código.
```

Premissas técnicas adotadas:

| Tema | Decisão | Motivo |
|---|---|---|
| Linguagem do motor | Python 3.12 + `decimal.Decimal` (precisão 34) | Sem float binário em valores financeiros |
| Backend | FastAPI + uvicorn | Sugestão do plano; validação de parâmetros nativa |
| Banco | SQLite (esquema em `backend/app/schema.sql`) | MVP local-first; PostgreSQL depois |
| Dependências | `uv` + `uv.lock` com hashes; `exclude-newer` ≈ 2 semanas | Reprodutibilidade e cadeia de suprimentos |
| Ferramentas | uv 0.12.24 e Node v24.22.1 LTS em `~/.local` (checksums verificados) | Sem root, sem mexer no sistema |
| Dados | Apenas `tests/fixtures_synthetic/*.json` com `"synthetic": true` | API recusa qualquer outro arquivo |

## 2. Arquivos e tarefas do repositório

| Caminho | Conteúdo | Status |
|---|---|---|
| `backend/financial_engine/money.py` | Decimal, parse/format BRL, recusa entradas ambíguas | ✅ |
| `backend/financial_engine/rates.py` | Taxas por composição, Fisher, taxa de adm., deflator | ✅ |
| `backend/financial_engine/projection.py` | Simulação mensal, fórmula fechada, cenários, meta reversa, fingerprint | ✅ |
| `backend/financial_engine/budget.py` | Fluxo de caixa, reserva, dívidas, "o que fazer este mês?" | ✅ |
| `backend/financial_engine/handoff.py` | Validação do formato de handoff entre agentes | ✅ |
| `backend/financial_engine/audit.py` | Apoio ao Auditor: recálculo, linguagem proibida, pedidos bloqueados | ✅ |
| `backend/app/agent_api.py` | API GET-only para agentes | ✅ |
| `backend/app/schema.sql` | Esquema v1 (seção 8) com triggers append-only | ✅ |
| `backend/integrations/` | Vazio de propósito até a Fase 3 | ✅ |
| `tests/unit`, `tests/integration`, `tests/security` | 141 testes | ✅ |
| `agents/AG-00..06*.md` | Instruções de cada agente para colar no OpenBot | ✅ |
| `docs/*.md` | Segurança, dados, métodos, contratos, decisões, runbook | ✅ |
| `scripts/demo.py`, `scripts/run_tests.sh` | Demonstração e suíte em ambiente limpo | ✅ |
| `frontend/` | Dashboard | ⏸ aguarda aprovação da Fase 1 |

### Tarefas da Fase 0 (seção 13)

| Tarefa | Status | Quem |
|---|---|---|
| Instalar OpenBot pelo site oficial e validar versão/checksum | ⏳ | **Você**: é app desktop; ver `RUNBOOK.md §2` |
| Conectar Claude Code ou Codex com autenticação própria | ⏳ | **Você**, dentro do OpenBot |
| Criar ambiente isolado com dados sintéticos | 🟡 parcial | Repositório só usa dados sintéticos; VM/usuário dedicado ao OpenBot é seu |
| Repositório com versionamento e `.gitignore` para segredos | ✅ | `git init` feito; sem commit, porque falta definir a identidade git (ver RUNBOOK) |
| Política de acesso, backup, atualização e fontes | ✅ | `SECURITY_MODEL.md` |
| Documentar limites das ferramentas | ✅ | `SECURITY_MODEL.md §1`, `FINANCIAL_METHODS.md §7` |

**Aceite da Fase 0:** "OpenBot inicia e os agentes executam testes com dados fictícios, sem acesso a arquivos pessoais
ou contas financeiras". A parte do repositório está pronta. A parte do OpenBot depende da instalação na VM dedicada.

## 3. Matriz de riscos e barreiras técnicas reais

| Risco | Impacto | Barreira técnica implementada | Barreira pendente |
|---|---|---|---|
| Agente executa ordem/transferência | Crítico | Não existe rota, função ou cliente de escrita; middleware recusa não-GET (405); testes AST bloqueiam nomes transacionais e clientes de rede | Rodar OpenBot sem sessões bancárias logadas (VM) |
| Agente lê arquivos pessoais | Crítico | API serve só fixtures `synthetic: true` | Usuário de SO dedicado + VM; não montar `$HOME` pessoal |
| Vazamento de credenciais | Crítico | Token só por variável de ambiente; testes de higiene procuram chaves/CPF/cartão; logs sem query string | Cofre de segredos na Fase 5 |
| API exposta na rede | Alto | `serve()` recusa host fora de loopback; sem `/docs` nem `/openapi.json` | Firewall de saída na VM |
| Erro de cálculo | Alto | Motor Decimal + 9.4 coberto em testes + fórmula fechada × iterativa | Revisão especializada de tributação (Fase 3) |
| Alucinação de número | Alto | Auditor recalcula com o motor (`audit_projection_claim`); fingerprint de entradas | Vincular toda resposta material ao fingerprint |
| Reescrita do histórico | Médio | Triggers append-only em `simulations`, `decision_log`, `audit_log`; transação conciliada não é apagada | — |
| Importação duplicada | Alto | `import_hash UNIQUE` + teste | Importador CSV (Fase 2) |
| Dependência maliciosa | Alto | `uv.lock` com hashes, `exclude-newer`, poucas dependências | Revisar changelog a cada atualização |
| Prompt injection | Alto | Nenhuma ferramenta perigosa para ser "ativada"; `screen_request` é só apoio | Testes com PDFs/CSVs adversariais (Fase 2/3) |

## 4. Testes que demonstram ausência de execução financeira

`tests/security/test_no_financial_execution.py`:

- todas as rotas da aplicação são GET/HEAD;
- POST/PUT/PATCH/DELETE/OPTIONS → 405 em qualquer caminho, **mesmo com token válido**;
- "aprovação genérica" (cabeçalho/corpo) não cria rota: `/v1/orders` → 405, `/v1/orders/execute` → 404;
- nenhuma função/classe do backend com nome transacional (`place_order`, `withdraw`, `transfer`, `pix`, `buy`/`sell`…);
- nenhum import de cliente de rede ou shell no backend (`requests`, `httpx`, `urllib.request`, `socket`, `subprocess`, `selenium`…);
- token obrigatório e forte; bind só em loopback; sem documentação interativa exposta;
- dados não sintéticos → 403.

**Teste de mutação manual (feito em 2026-10-26):** foram injetados um módulo com `place_order` e `import urllib.request`
e, em outra rodada, uma rota POST. A suíte falhou nos três casos e passou de novo depois de reverter.

## 5. Plano do MVP (Fase 1) com critérios objetivos

| # | Entrega | Critério de aceite objetivo | Estado |
|---|---|---|---|
| 1 | Motor de projeção | 100% dos casos da seção 9.4 aplicáveis passando | ✅ (eventos corporativos/câmbio: Fase 2) |
| 2 | Três cenários reproduzíveis | Mesmas entradas → mesmo JSON e fingerprint; nominal e real | ✅ API e demo |
| 3 | Diagnóstico + "o que fazer este mês" | Critérios 24.9 cobertos por testes com personas | ✅ |
| 4 | Auditor detecta erro deliberado | Taxa dividida por 12 → REVISAR | ✅ |
| 5 | Onboarding financeiro (cadastro de renda, despesas, dívidas, metas) | Formulário grava no SQLite; dados com `as_of` | ⏸ |
| 6 | Dashboard local (telas 1, 2 e 4) | Unidades e datas visíveis; funciona offline | ⏸ |
| 7 | Agentes AG-00, 01, 02, 06 no OpenBot | Coordenador consulta especialistas via API com handoff válido | ⏸ depende do OpenBot |
| 8 | Backup/restauração de teste | Restaurar e comparar hash | ⏸ |

**Portão:** avançar para 5–8 somente com sua aprovação explícita.
