# Pendências do Lastro

| # | Item | Depende de | Estado |
|---|---|---|---|
| 1 | Integrar o frontend (React) ao backend e compilar `frontend/dist` | agente da interface | em andamento |
| 2 | Registro DNS `A lastro.doinlabs.com.br → 50.114.206.231` na Cloudflare (DNS only) | usuário | feito (27/10/2026) |
| 3 | Publicado em 2026-10-27: Caddy no host (`deploy/caddy/Caddyfile` → `/etc/caddy/Caddyfile`), HTTPS Let's Encrypt, proxy para 127.0.0.1:8080 | — | feito |
| 4 | ~~Validar Caddy → lastro-web com `IPAddressDeny`~~ — moot: web em 127.0.0.1, Caddy no host | — | resolvido |
| 5 | Senha do app: provisória gerada; o dono troca com `sudo lastro-admin set-password` | usuário (via SSH) | trocar quando puder |
| 6 | Auditoria de segurança (cloudflare/security-audit-skill, perfil standard, run-1): relatórios em `~/security-audit-skill/meu-patrimonio-ai/run-1/`. Achados corrigidos (Caddy admin, bloqueio de login, redirecionamentos e WebSockets do navegador) e as 3 pistas endurecidas. Cobertura parcial: 2 unidades adiadas (WebRTC/preconnect — mitigado; chamadas Playwright sem prazo — mitigado) | — | feito; próxima rodada após mudanças grandes |
| 7 | Navegador de pesquisa: perfil AppArmor `lastro-chrome` aprovado e instalado; ligado em produção | — | feito |
| 8 | Backup criptografado do SQLite + teste de restauração | escolha da ferramenta (ex.: `age`) | planejado |
| 9 | Conta do Claude do mentor é Team | usuário | mantida (decisão do dono) |
| 10 | Tributos no motor (regras versionadas com fonte legal) | Fase 3 | planejado |
| 11 | Implantado em 2026-10-27 junto com as correções da auditoria: redesign "Bloco" + marca nova (`docs/brand`) | — | feito |
| 12 | Endurecimentos restantes da auditoria (REPORT.md §5): UID separado para web e API de leitura; transcrições da CLI e `routine_runs.summary` na exclusão de conversa; `interrupt` cancelar painéis/rotinas; `__Host-` no cookie; AppArmor confinado para o Chrome | dev | planejado |
