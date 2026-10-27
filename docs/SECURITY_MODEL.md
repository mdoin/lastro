# Modelo de segurança

## 1. Premissa central

Prompts descrevem o comportamento desejado, mas **não isolam nada**. O plano registra (seção 10.1, documentação do
OpenBot conferida pelo autor em 26/10/2026) que os agentes podem ter acesso amplo a arquivos, comandos, rede e navegador, e
que o workspace de um agente não é sandbox. Por isso, toda proteção relevante precisa estar no SO, na rede ou na
ausência de capacidade no código.

## 2. Camadas

| Camada | Controle | Onde |
|---|---|---|
| Código | Nenhuma operação de escrita em instituição financeira existe | `backend/` + testes de segurança |
| API | GET-only, token Bearer ≥ 32 caracteres, loopback, sem OpenAPI público, `Cache-Control: no-store` | `backend/app/agent_api.py` |
| Dados | Fase 0/1: só fixtures `"synthetic": true`; dados reais exigem nova revisão | `load_synthetic()` |
| Banco | Append-only para simulações, decisões e auditoria | `schema.sql` (triggers) |
| Repositório | `.gitignore` para `.env`, bancos, extratos, exportações; testes de higiene | `tests/security/test_repo_hygiene.py` |
| Dependências | `uv.lock` com hashes; `exclude-newer`; poucas libs | `pyproject.toml` |
| SO | **Pendente**: VM ou usuário dedicado para o OpenBot, sem admin, sem pastas pessoais | RUNBOOK §2 |
| Rede | **Pendente**: allowlist de saída na VM (provedor do modelo + fontes da Fase 3) | RUNBOOK §2 |

## 3. Ações proibidas por design (seção 10.3)

`place_order`, `withdraw`, `transfer`, `change_pix_key`, `add_beneficiary`, `approve_payment` e equivalentes **não
existem** na API. O teste `test_no_transactional_functions_or_classes` falha se alguém criar funções ou classes com esses
nomes no backend. O teste `test_only_get_routes_exist` falha se surgir qualquer rota que não seja GET.

`financial_engine.audit.screen_request` bloqueia pedidos de transferência ou credenciais **como apoio ao Auditor**, mas ele
não é controle de segurança: uma frase pode escapar do filtro, e isso não muda nada, porque a capacidade de executar não existe.

## 4. Política de fontes (Fase 3)

Somente leitura, com registro de `source`, `retrieved_at`, `reference_date`, `currency`, `unit`, `is_estimate` e
`license`. Candidatas: BCB/SGS, IBGE/SIDRA, Tesouro Direto, CVM e provedores licenciados. Nada é integrado antes de
verificar endpoint, licença e frequência. Cada novo adaptador exige:

1. atualizar conscientemente a lista `FORBIDDEN_IMPORTS` do teste, liberando o cliente de rede **apenas** em `backend/integrations/`;
2. adicionar o domínio à allowlist de saída da VM;
3. testar falha da fonte: o sistema mostra "não verificado" e nunca inventa um valor.

Primeiro adaptador (2026-10-27): `integrations/collector.py` (BCB/SGS, FRED), liberado no teste de imports, em serviço próprio (`lastro-coletor`) com redes privadas bloqueadas; só número e data chegam ao banco.

## 4a. Provedores de IA (v0.3)

| Ameaça | Controle |
|---|---|
| Chave de IA vazar pelo navegador | O web app só repassa a chave ao worker; respostas trazem `…1234`; `providers_web._clean` descarta campos de segredo |
| Web app comprometido redirecionar uma chave | Mudar `base_url` apaga a chave da conexão (`registry.SECRET_BOUND`) |
| Worker comprometido ler o banco | O worker não tem o volume nem as permissões do banco; dados só pela API GET-only com token |
| Modelo chamar ferramenta não concedida | `toolspec.run_tool` recusa nome fora da concessão do papel, para todos os provedores |
| Ferramentas nativas dos CLIs (shell, arquivos) | Claude Code: `tools=[]`, `can_use_tool`; Codex: recursos nativos desligados, sandbox read-only, aprovações recusadas, ambiente mínimo |
| Intermediar credenciais de assinatura | Login pelo próprio CLI; o código colado vai só ao stdin do CLI, sem log nem resposta; ver PROVIDER_TERMS.md |
| Tomada de uma instalação nova | Primeira senha pela web só com o token de instalação (arquivo 0600 no servidor), limitado como o login |
| Provedor fora do ar ou em limite | Erros normalizados; limite segura só a fila daquela conexão |

## 5. Atualizações

- Python: alterar `exclude-newer` só após ler os changelogs; `uv lock`; rodar a suíte.
- uv/Node: baixar do site oficial, conferir SHA-256 e preferir versões com mais de 2 semanas, **exceto releases de segurança**.
- Claude Code e Codex: versão fixada (wheel no `uv.lock`; `CODEX_VERSION` no Dockerfile); atualizar só após ler o changelog.

## 6. Backup (Fase 1, item 8)

`lastro-admin backup/restore` (API de backup do SQLite, integridade conferida) e cópia automática antes de cada
migração; ver [BACKUP.md](BACKUP.md). A criptografia da cópia fora do servidor (por exemplo `age`) fica com o operador.

## 7. Resposta a incidente

Seguir a seção 10.5 do plano: desconectar, revogar `MPA_AGENT_API_TOKEN`/`LASTRO_AGENT_API_TOKEN`, as chaves de IA nos painéis dos provedores e os logins dos CLIs, preservar logs,
avaliar o escopo, restaurar backup íntegro e documentar.
