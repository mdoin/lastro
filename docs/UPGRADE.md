# Atualização de versão

```bash
cd lastro
docker compose exec web python -m app.admin backup /data/backups/antes-da-atualizacao.db   # recomendado
git pull
docker compose build
docker compose up -d
docker compose ps
```

O que acontece:

1. Ao subir, o `web` confere a versão do banco. Se houver migração pendente, ele **grava uma cópia** em
   `/data/backups/pre-vN-AAAAMMDDTHHMMSSZ.db` e só então migra. Banco novo (instalação limpa) não gera cópia.
2. As migrações só acrescentam tabelas e colunas; dados existentes não são reescritos.
3. `collector` e `agent-api` só sobem depois que o `web` está saudável (migração concluída).
4. Credenciais de IA ficam no volume `mentor-home` e não são tocadas.

## Voltar uma versão

Código: `git checkout <versão anterior> && docker compose build && docker compose up -d`.
Banco: o código anterior ignora tabelas e colunas novas. Se precisar do banco exato de antes, restaure a cópia
automática (ver [BACKUP.md](BACKUP.md#restaurar)).

## Mudanças por versão

Ver [CHANGELOG.md](../CHANGELOG.md). Notas que exigem ação do operador aparecem em **Atualização**.

## Instalação systemd (instância de referência)

`scripts/deploy.sh` instala os extras `claude-code` e `browser`, aplica as migrações (com a mesma cópia automática) e
reinicia as unidades. Na v0.3, a unidade `lastro-mentor` ganhou `LASTRO_IMPLICIT_CLAUDE_CODE=1`: sem conexões salvas,
o worker continua usando o Claude Code já logado no servidor.
