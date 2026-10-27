# Backup e restauração

## O que existe para guardar

| Volume | Conteúdo | Sensibilidade |
|---|---|---|
| `data` | banco SQLite: retratos, metas, decisões, conversas, Radar, auditoria; backups automáticos em `backups/` | **dados financeiros** |
| `mentor-home` | conexões de IA (`providers.json`, chaves de API), login do Claude Code e do Codex | **credenciais** |
| `caddy-data` | certificados HTTPS | baixa (são reemitidos) |

Os dois primeiros são separados de propósito. Um backup do banco **não** contém credenciais de IA; guardar as
credenciais é opcional (dá para reconectar os provedores depois de restaurar).

## Fazer backup do banco

Cópia consistente com o Lastro rodando (API de backup do SQLite, integridade conferida, arquivo 0600):

```bash
docker compose exec web python -m app.admin backup /data/backups/lastro-$(date +%F).db
docker compose cp web:/data/backups/lastro-$(date +%F).db ./lastro-$(date +%F).db
```

Guarde a cópia fora do servidor e **criptografada** (por exemplo `age -p lastro-AAAA-MM-DD.db > ….age`): o arquivo
contém sua vida financeira.

## Restaurar

```bash
docker compose stop web collector agent-api
docker compose run --rm --no-deps -v "$PWD/lastro-AAAA-MM-DD.db:/restore.db:ro" web \
  python -m app.admin restore /restore.db
docker compose up -d
```

`restore` recusa arquivos corrompidos e backups de uma versão mais nova do Lastro, troca o banco de uma vez (sem
estado intermediário) e aplica as migrações que faltarem. Para restaurar uma cópia automática de antes de uma
atualização, use o caminho dela: `.../restore /data/backups/pre-vN-….db` (sem o `-v`).

## Credenciais de IA (opcional)

```bash
docker compose stop mentor
docker run --rm -v lastro_mentor-home:/v:ro -v "$PWD":/out alpine tar czf /out/mentor-home.tgz -C /v .
docker compose start mentor
```

Trate esse arquivo como uma senha. Se ele vazar, revogue as chaves nos painéis dos provedores e desconecte as contas.

## Exportação legível

Configurações → **Exportar meus dados** baixa um JSON com tudo o que está no banco (portabilidade, não substitui o
backup).
