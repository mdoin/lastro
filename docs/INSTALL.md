# Instalação (Linux + Docker Compose)

Feito para Ubuntu 24.04 e Debian 12 (o CI roda em Ubuntu 24.04). Requisitos: Docker Engine 24+ com o plugin Compose v2, 2 GB de RAM (4 GB com
Claude Code ou Codex), 5 GB de disco.

## 1. Preparar

```bash
git clone https://github.com/mdoin/lastro.git && cd lastro
sh scripts/init-env.sh
```

`init-env.sh` cria o `.env` (permissão 0600) com o token interno `LASTRO_AGENT_API_TOKEN` aleatório. Revise:

| Variável | Para quê |
|---|---|
| `LASTRO_TZ` | fuso das rotinas e do contexto dos agentes (padrão `America/Sao_Paulo`) |
| `LASTRO_BIND` / `LASTRO_HTTP_PORT` | onde o web é publicado (padrão: só `127.0.0.1:8080`) |
| `LASTRO_DOMAIN` | domínio para o HTTPS automático (perfil `https`) |
| `LASTRO_WITH_CLAUDE_CODE` | `1` inclui o executável oficial do Claude Code na imagem |
| `LASTRO_WITH_CODEX` | `1` inclui o executável oficial do Codex na imagem |
| `FRED_API_KEY` | opcional: séries dos EUA |

Todas as variáveis estão comentadas em [`.env.example`](../.env.example). Chaves de IA **não** vão no `.env`: conecte
os provedores pela interface.

## 2. Subir

```bash
docker compose build
docker compose up -d
docker compose ps        # web e mentor devem ficar "healthy"
```

Serviços: `web` (interface e API, dono do banco), `mentor` (worker dos agentes, dono das credenciais de IA, sem acesso
ao banco), `agent-api` (leitura do banco para as ferramentas, só no loopback do `mentor`) e `collector` (séries
oficiais). Todos rodam sem root, com sistema de arquivos somente leitura e sem capabilities.

## 3. Primeiro acesso

```bash
docker compose exec web cat /data/setup-token
```

Abra `http://127.0.0.1:8080`. O assistente pede o token, cria a conta administrativa e guia a conexão do provedor de
IA, o teste de conexão, a escolha do modelo do Mentor e um diagnóstico da instalação. O token é apagado assim que a
senha é criada. Sem IA conectada, tudo que é determinístico já funciona.

## 4. Acesso de outros aparelhos

Escolha **um**:

- **HTTPS automático** (servidor com IP público e domínio): aponte o DNS do domínio para o servidor, defina
  `LASTRO_DOMAIN` no `.env` e rode `docker compose --profile https up -d`. O Caddy obtém o certificado e o web continua
  publicado só em `127.0.0.1`.
- **Túnel ou VPN** (Tailscale, WireGuard, Cloudflare Tunnel): mantenha `LASTRO_BIND=127.0.0.1` e exponha a porta pelo
  túnel com HTTPS.
- **Rede local sem HTTPS** (não recomendado): `LASTRO_BIND=0.0.0.0` e `LASTRO_COOKIE_SECURE=0`. Qualquer pessoa na
  rede vê o tráfego.

## 5. Provedores com executável oficial

- **Claude Code**: construa com `LASTRO_WITH_CLAUDE_CODE=1`. Faça login no terminal do servidor
  (`docker compose exec -it mentor python -m providers.claude_code login`) ou pela interface (link da Anthropic +
  código). Leia antes [PROVIDER_TERMS.md](PROVIDER_TERMS.md).
- **Codex**: construa com `LASTRO_WITH_CODEX=1`. Entre com a conta do ChatGPT pela interface (device code) ou no
  terminal (`docker compose exec -it mentor codex login --device-auth`).
- **Ollama no próprio host**: crie uma conexão "Ollama" com o endereço `http://host.docker.internal:11434/v1`.

## 6. Operação

| Tarefa | Comando |
|---|---|
| Logs | `docker compose logs -f web mentor` |
| Reiniciar | `docker compose restart` |
| Parar | `docker compose down` (os volumes ficam) |
| Trocar a senha | `docker compose exec -it web python -m app.admin set-password` |
| Encerrar sessões | `docker compose exec web python -m app.admin logout-all` |
| Backup | ver [BACKUP.md](BACKUP.md) |
| Atualizar | ver [UPGRADE.md](UPGRADE.md) |

Logs ficam no driver `local` do Docker com rotação (10 MB × 3 por serviço) e não registram conteúdo de conversas,
chaves nem cookies.

## Instalação sem Docker (systemd)

A instância de referência roda com unidades systemd e usuários dedicados (`deploy/systemd/`, `scripts/deploy.sh`).
Esse caminho exige mais administração manual; veja [RUNBOOK.md](RUNBOOK.md) e
[LASTRO_ARCHITECTURE.md](LASTRO_ARCHITECTURE.md).
