# Testes

```bash
uv run pytest -q                                  # backend: unidade, integração, segurança
(cd frontend && npm test && npm run typecheck)    # frontend
```

O CI (`.github/workflows/ci.yml`) roda tudo em Linux, constrói a imagem, sobe uma instalação limpa, varre o histórico
com gitleaks e audita dependências (`pip-audit`, `npm audit`). Nenhum teste chama um provedor de IA real: os SDKs
recebem transporte HTTP simulado, e o Codex e o login do Claude usam processos falsos (`tests/fixtures/`).

## Cenários obrigatórios

| # | Cenário | Onde |
|---|---|---|
| 1 | Instalação limpa | CI `install` (build, subida, health check, token de instalação); `tests/security/test_deployment.py` |
| 2 | Onboarding | `tests/integration/test_providers_web.py::test_first_password_requires_the_installation_token` e seguintes |
| 3 | Conexão por API key | `tests/unit/test_providers.py` (Anthropic, OpenAI, Ollama); `test_provider_admin_never_returns_secrets` |
| 4 | Fluxos de login oficialmente suportados | Codex device code e app-server: `test_codex_adapter_with_fake_app_server`; Claude Code (link + código no CLI): `test_claude_code_paste_login_with_fake_cli` (Linux) |
| 5 | Revogação | `test_api_key_revoke_clears_it`, `test_codex_revoke_logs_out_through_the_app_server` |
| 6 | Troca de provedor | `test_switching_provider_keeps_history_and_identity`, `test_model_change_reopens_session` |
| 7 | Persistência do histórico | `test_switching_provider_keeps_history_and_identity`, `test_upgrade_keeps_data_and_leaves_a_backup` |
| 8 | Recuperação de sessão | `tests/unit/test_mentor_worker.py::test_lost_session_reopens_with_history_handoff`; `session_connection` em `test_agent_models_are_validated_and_routed` |
| 9 | Isolamento das credenciais | `test_store_keeps_secret_private`, `test_changing_destination_drops_the_key`, `test_secrets_never_come_back_from_the_web_app`, `test_credentials_and_financial_data_never_share_a_container`, `test_codex_runs_with_native_tools_disabled_and_minimal_env` |
| 10 | Bloqueio de ferramentas não autorizadas | `test_run_tool_denies_unknown_and_validates_input`, `test_anthropic_tool_loop_streams_and_keeps_history` (Bash recusado), Codex (`transferir_dinheiro`, aprovação de comando), `tests/security/test_no_financial_execution.py`, `test_unauthorized_tools_are_blocked` |
| 11 | Falha de provedor | `test_anthropic_errors_are_normalized` (401/403/429/500/400), `test_without_provider_the_worker_answers_with_clear_error` |
| 12 | Limite de uso | `test_anthropic_errors_are_normalized[429]` (retry-after), `test_rate_limit_is_per_connection`, `test_rate_limit_waits_and_retries` |
| 13 | Cancelamento | `test_interrupt_cancels_and_leaves_consistent_history`, testes de interrupção do worker e da equipe |
| 14 | Execução multiagente | `test_panel_and_team_steps_use_the_requested_connection`, `tests/integration/test_team.py` |
| 15 | Backup e restauração | `tests/integration/test_backup_upgrade.py` |
| 16 | Atualização sem perda de dados | `test_upgrade_keeps_data_and_leaves_a_backup`, `test_existing_installation_skips_onboarding` |
| 17 | Inicialização sem provedor | `test_runtime_without_connections_reports_not_configured`, `test_without_provider_the_worker_answers_with_clear_error`; o web sobe e serve as funções determinísticas |
| 18 | Ausência de segredos na distribuição | `tests/security/test_repo_hygiene.py`, `test_dockerignore_keeps_secrets_and_data_out_of_the_image`, gitleaks no CI |
| 19 | Execução em ambiente limpo | CI (runner novo, `uv sync --frozen`, `npm ci`, build da imagem) |
| 20 | Compatibilidade com a infraestrutura atual | `test_current_systemd_installation_keeps_working`; testes do worker com a conexão implícita `claude-code` |

## Limites conhecidos
- Socket Unix, `SO_PEERCRED` e o login do Claude por terminal virtual só rodam em Linux (no Windows esses testes são
  pulados).
- Não há teste contra APIs reais (custo e credenciais). Antes de uma release, faça um teste manual com cada provedor
  que você usa (docs/RELEASE.md).
- O teste do Codex usa um app-server falso que segue o protocolo da versão 0.162.1; mudanças futuras do protocolo
  experimental podem exigir ajuste.
