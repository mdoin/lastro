# Pendências do Lastro

| # | Item | Depende de | Estado |
|---|---|---|---|
| 1 | Integrar o frontend (React) ao backend e compilar `frontend/dist` | agente da interface | em andamento |
| 2 | Registro DNS do domínio da instância pessoal (fora do repositório) | usuário | feito (27/10/2026) |
| 3 | Publicado em 2026-10-27: Caddy no host (`deploy/caddy/Caddyfile` → `/etc/caddy/Caddyfile`), HTTPS Let's Encrypt, proxy para 127.0.0.1:8080 | — | feito |
| 4 | ~~Validar Caddy → lastro-web com `IPAddressDeny`~~ — moot: web em 127.0.0.1, Caddy no host | — | resolvido |
| 5 | Senha do app: provisória gerada; o dono troca com `sudo lastro-admin set-password` | usuário (via SSH) | trocar quando puder |
| 6 | Auditoria de segurança (cloudflare/security-audit-skill, perfil standard, run-1): relatórios fora do repositório. Achados corrigidos (Caddy admin, bloqueio de login, redirecionamentos e WebSockets do navegador) e as 3 pistas endurecidas. Cobertura parcial: 2 unidades adiadas (WebRTC/preconnect — mitigado; chamadas Playwright sem prazo — mitigado) | — | feito; próxima rodada após mudanças grandes |
| 7 | Navegador de pesquisa: perfil AppArmor `lastro-chrome` aprovado e instalado; ligado em produção | — | feito |
| 8 | Backup criptografado do SQLite + teste de restauração | escolha da ferramenta (ex.: `age`) | planejado |
| 9 | Conta do Claude do mentor é Team | usuário | mantida (decisão do dono) |
| 10 | Tributos no motor (regras versionadas com fonte legal) | Fase 3 | planejado |
| 11 | Implantado em 2026-10-27 junto com as correções da auditoria: redesign "Bloco" + marca nova (`docs/brand`) | — | feito |
| 12 | Endurecimentos restantes da auditoria (REPORT.md §5): UID separado para web e API de leitura; transcrições da CLI e `routine_runs.summary` na exclusão de conversa; `interrupt` cancelar painéis/rotinas; `__Host-` no cookie; AppArmor confinado para o Chrome | dev | planejado |
| 13 | Equipe de agentes (docs/MULTIAGENT.md): implantar com `scripts/deploy.sh` após backup do banco | usuário | pronto para revisão |
| 14 | Login por usuário (hoje um login; dados da equipe já filtram por `user_id`) e dados financeiros multiusuário | produto | planejado (só se houver terceiros) |
| 15 | Fontes não conectadas: CVM, ANBIMA, B3 (cotações), SEC; FRED depende de `FRED_API_KEY`. IBGE/SIDRA e Tesouro Direto conectados em 27/10/2026 | chaves/licenças | planejado |
| 16 | Criptografia em repouso do banco (disco/backup com `age`) | item 8 | planejado |
| 17 | Uso por terceiros exige revisão regulatória (CVM 19/30) e cobrança por API do provedor, não assinatura pessoal | produto | obrigatório antes de abrir |
| 18 | Navegador de pesquisa com tela na interface nova: feito com o navegador livre dos agentes (docs/PESQUISA.md), tela ao vivo no passo de pesquisa | dev | feito (28/10/2026) |
| 19 | Radar e Diário de Oportunidades (docs/RADAR.md): implantar com `scripts/deploy.sh` após backup (`pre-v6.db`) e reiniciar `lastro-coletor` | usuário | pronto para revisão |
| 20 | Transportes de notificação externa (e-mail, Telegram, push PWA): hoje ficam "não configurado" | credenciais (SMTP, bot, VAPID) | planejado |
| 21 | Carteira real (posições) para riscos de concentração, rebalanceamento e vencimentos | cadastro de posições | planejado |
| 22 | Método de renda fixa v2: cupons semestrais e carregamento até o vencimento | dev | planejado |
| 23 | Diário de Decisões assistido por agentes (docs/DIARIO.md, migração 007): implantar com `scripts/deploy.sh` após backup (`pre-v7.db`) (revisão de segurança focada feita; auditoria completa run-2 ainda pendente para equipe/Radar/Diário) | — | implantado em 27/10/2026 |
| 24 | Conselho com parecer estruturado, contestação, mapa de posições e Analista de Ativos Digitais (docs/MULTIAGENT.md, migração 009): implantar com `scripts/deploy.sh` após backup (`pre-v9.db`). O Radar ainda não tem categoria cripto (sem fonte de preço licenciada) | usuário | pronto para revisão |
| 25 | Livro de movimentações, memória automática e Caixa de entrada da Mila (docs/LEDGER.md, migração 010): backup (`pre-v10.db`), `uv sync --extra documents`, opcional `tesseract-ocr-por`, deploy. Leitura de imagem sem tesseract fica "sem leitura" | usuário | pronto para revisão |
| 26 | Conselho deliberativo (docs/COUNCIL.md, migração 011): deploy após backup (`pre-v11.db`); ajustar `LASTRO_COUNCIL_*` ao custo real do provedor | usuário | pronto para revisão |
| 27 | Radar cripto e reuniões autônomas (docs/CRYPTO.md, migração 012): deploy após backup (`pre-v12.db`), reiniciar `lastro-coletor`; chave CoinGecko opcional pela tela; reuniões autônomas ficam desligadas até você autorizar | usuário | pronto para revisão |
| 28 | Laboratório do Conselho (docs/LAB.md, migração 014): Bento sozinho × Conselho, hipóteses conferidas e reavaliações; automação pelo Radar desligada por padrão | — | implantado em 28/10/2026 |
